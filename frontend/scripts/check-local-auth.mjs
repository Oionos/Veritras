// Real browser -> API -> PostgreSQL regression, using unlocked Hardhat wallets.
// Run only after `make testing-up`; no hosted credentials or funded wallets.
import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { chromium } from 'playwright'

const rpc = 'http://localhost:18545'
const api = 'http://localhost:18000'
async function rpcRequest(method, params = []) {
  const response = await fetch(rpc, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  })
  const result = await response.json()
  if (result.error) throw new Error(result.error.message)
  return result.result
}
assert.equal(await rpcRequest('eth_chainId'), '0x7a69', 'Only the isolated Hardhat chain is allowed')
const health = await (await fetch(`${api}/health/ready`)).json()
assert.equal(health.environment, 'testing')
assert.equal(health.chain_id, 31337)
const accounts = await rpcRequest('eth_accounts')
assert.ok(accounts.length >= 2)

// Prove challenges live in PostgreSQL, rather than in the API process.
const pending = await (await fetch(`${api}/auth/challenge`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ address: accounts[0] }),
})).json()
const pendingSignature = await rpcRequest('personal_sign', [
  `0x${Buffer.from(pending.message).toString('hex')}`, accounts[0],
])
const restarted = spawnSync('make', ['testing-restart-api'], {
  cwd: new URL('../../', import.meta.url), stdio: 'inherit',
})
assert.equal(restarted.status, 0, 'The isolated API must restart successfully')
for (let attempt = 0; attempt < 40; attempt++) {
  try { if ((await fetch(`${api}/health/ready`)).ok) break } catch { /* Starting. */ }
  await new Promise(resolve => setTimeout(resolve, 500))
}
const afterRestart = await fetch(`${api}/auth/verify`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message: pending.message, signature: pendingSignature }),
})
assert.equal(afterRestart.status, 200, 'The persisted challenge must survive an API restart')

const browser = await chromium.launch({
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
  args: ['--no-sandbox'],
})
let page
try {
  page = await browser.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(({ accounts, rpc }) => {
    let selected = accounts[0]
    const listeners = new Map()
    const provider = {
      isConnected: () => true,
      on(event, fn) {
        if (!listeners.has(event)) listeners.set(event, new Set())
        listeners.get(event).add(fn)
      },
      removeListener(event, fn) { listeners.get(event)?.delete(fn) },
      async request({ method, params = [] }) {
        if (method === 'eth_requestAccounts' || method === 'eth_accounts') return [selected]
        if (method === 'wallet_requestPermissions') return [{ parentCapability: 'eth_accounts' }]
        if (method === 'wallet_switchEthereumChain') {
          if (params[0]?.chainId !== '0x7a69') throw new Error('Only local Hardhat is permitted')
          return null
        }
        const response = await fetch(rpc, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
        })
        const result = await response.json()
        if (result.error) throw new Error(result.error.message)
        return result.result
      },
    }
    window.ethereum = provider
    window.switchTestingWallet = index => {
      selected = accounts[index]
      listeners.get('accountsChanged')?.forEach(fn => fn([selected]))
    }
  }, { accounts, rpc })
  await page.goto('http://localhost:13000/products', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Add Product', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Add Product', exact: true }).isDisabled(), true)
  if (!await page.getByRole('button', { name: 'Sign In', exact: true }).count()) {
    await page.getByRole('button', { name: /connect.*wallet/i }).first().click()
    await page.getByText('Browser Wallet', { exact: true }).click()
  }
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
  await page.getByRole('button', { name: 'Add Product', exact: true }).click()
  const manufacturer = page.getByLabel('Manufacturer address from your signed-in wallet')
  assert.equal((await manufacturer.inputValue()).toLowerCase(), accounts[0].toLowerCase())
  assert.equal(await manufacturer.getAttribute('readonly'), '')
  const itemName = `Auth browser item ${Date.now()}`
  await page.getByPlaceholder('e.g., Organic Coffee Beans').fill(itemName)
  const createdResponse = page.waitForResponse(response => response.status() === 200 && response.url().startsWith(`${api}/products`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create Product', exact: true }).click()
  const draft = await (await createdResponse).json()
  assert.equal(draft.owner_address, accounts[0].toLowerCase())
  assert.equal(draft.ownership_source, 'signed_draft')
  await page.getByRole('button', { name: 'Skip', exact: true }).click()
  await page.getByPlaceholder('Search by product name...').fill(itemName)
  await page.getByRole('button', { name: `Edit ${draft.product_id}`, exact: true }).click()
  await page.getByPlaceholder('e.g., Organic Coffee Beans').fill('Updated auth browser item')
  const updated = page.waitForResponse(response => response.url().includes(draft.product_id) && response.request().method() === 'PUT')
  await page.getByRole('button', { name: 'Save Changes', exact: true }).click()
  assert.equal((await updated).status(), 200)

  // Register the saved draft, reload, and inspect the persisted attempt/evidence.
  const lookup = page.getByPlaceholder('Enter product ID (e.g., PROD-8842)')
  await lookup.fill(draft.product_id)
  await lookup.press('Enter')
  const registrationSaved = page.waitForResponse(response => response.url().endsWith(`/products/${draft.product_id}/registration`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Register existing draft on blockchain', exact: true }).click()
  assert.equal((await registrationSaved).status(), 200)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder('Enter product ID (e.g., PROD-8842)').fill(draft.product_id)
  await page.getByPlaceholder('Enter product ID (e.g., PROD-8842)').press('Enter')
  const lifecycle = page.getByRole('region', { name: 'Registration lifecycle' })
  await lifecycle.waitFor()
  await page.waitForFunction(async ({ api, productId }) => {
    const response = await fetch(`${api}/products/${productId}/verify`)
    return (await response.json()).evidence?.status === 'verified'
  }, { api, productId: draft.product_id })
  await lifecycle.getByRole('button', { name: 'Refresh transaction evidence' }).first().click()
  await lifecycle.getByText('registration · indexed · matching confirmed event', { exact: true }).waitFor()
  await lifecycle.getByLabel('New metadata URI').fill('ipfs://browser-confirmed-version')
  const metadataSaved = page.waitForResponse(response => response.url().endsWith(`/products/${draft.product_id}/registration`) && response.request().method() === 'POST')
  await lifecycle.getByRole('button', { name: 'Sign metadata update' }).click()
  assert.equal((await metadataSaved).status(), 200)
  await page.waitForFunction(async ({ api, productId }) => (await (await fetch(`${api}/products/${productId}`)).json()).product.metadata_uri === 'ipfs://browser-confirmed-version', { api, productId: draft.product_id })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder('Enter product ID (e.g., PROD-8842)').fill(draft.product_id)
  await page.getByPlaceholder('Enter product ID (e.g., PROD-8842)').press('Enter')
  const restoredLifecycle = page.getByRole('region', { name: 'Registration lifecycle' })
  await restoredLifecycle.getByText('Metadata version history').click()
  await restoredLifecycle.locator('details p').filter({ hasText: 'ipfs://browser-confirmed-version' }).waitFor()

  await page.getByRole('link', { name: /shipments/i }).first().click()
  await page.getByRole('button', { name: 'Add Shipment', exact: true }).click()
  await page.getByPlaceholder('e.g., PROD-8842').fill(draft.product_id)
  await page.getByPlaceholder('Origin location').fill('Auth test factory')
  await page.getByPlaceholder('Destination location').fill('Auth test depot')
  const shipmentResponse = page.waitForResponse(response => response.status() === 200 && response.url().startsWith(`${api}/shipments`) && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Create Shipment', exact: true }).click()
  const shipment = await (await shipmentResponse).json()
  assert.ok(shipment.shipment_id)

  await page.evaluate(() => window.switchTestingWallet(1))
  await page.getByRole('button', { name: 'Sign In', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Sign out', exact: true }).count(), 0)
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: `Edit shipment ${shipment.shipment_id}`, exact: true }).count(), 0)
  const checks = await page.evaluate(async ({ api, productId, shipmentId }) => {
    const auth = { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('veritras_auth_token')}` }
    const edit = await fetch(`${api}/products/${productId}`, { method: 'PUT', headers: auth, body: JSON.stringify({ name: 'Unauthorized' }) })
    const plan = await fetch(`${api}/shipments/`, { method: 'POST', headers: auth, body: JSON.stringify({ product_id: productId, origin: 'Other', destination: 'Other' }) })
    const shipmentEdit = await fetch(`${api}/shipments/${shipmentId}`, { method: 'PUT', headers: auth, body: JSON.stringify({ notes: 'Unauthorized' }) })
    const anonymous = await fetch(`${api}/products/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Anonymous' }) })
    const publicRead = await fetch(`${api}/products/${productId}`)
    return [edit.status, plan.status, shipmentEdit.status, anonymous.status, publicRead.status]
  }, { api, productId: draft.product_id, shipmentId: shipment.shipment_id })
  assert.deepEqual(checks, [403, 403, 403, 401, 200])
  assert.deepEqual(errors, [])
  mkdirSync('../.testing', { recursive: true })
  await page.screenshot({ path: '../.testing/auth-browser.png', fullPage: true })
  console.log('PASS: real browser registration/reload recovery, metadata update/history, wallet sign-in, owned draft/shipment writes, wallet-switch logout, cross-wallet denial, and anonymous public reads')
} catch (error) {
  if (page) await page.screenshot({ path: '../.testing/registration-browser-failure.png', fullPage: true })
  console.error({ buttons: page ? await page.locator('button').allTextContents() : [], lifecycle: page ? await page.getByRole('region', { name: 'Registration lifecycle' }).allTextContents() : [] })
  throw error
} finally {
  await browser.close()
}
