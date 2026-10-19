// Real browser -> API -> PostgreSQL regression, using unlocked Hardhat wallets.
// Run only after `make testing-up`; no hosted credentials or funded wallets.
import assert from 'node:assert/strict'
import { mkdirSync, readFileSync } from 'node:fs'
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
async function waitForApi(path, predicate, label) {
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    const response = await fetch(`${api}${path}`)
    if (response.ok && predicate(await response.json())) { console.log(`PASS: ${label}`); return }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  throw new Error(`Timed out waiting for ${label}`)
}
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
  page.on('console', message => { if (message.text().startsWith('Local wallet RPC failed')) console.warn(message.text()) })
  await page.addInitScript(({ accounts, rpc }) => {
    let selected = accounts[Number(sessionStorage.getItem('veritras_testing_wallet') || '0')] || accounts[0]
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
        if (result.error) { console.warn('Local wallet RPC failed', method, result.error.code, String(result.error.message).slice(0, 180)); throw new Error(result.error.message) }
        return result.result
      },
    }
    window.ethereum = provider
    window.switchTestingWallet = index => {
      selected = accounts[index]
      sessionStorage.setItem('veritras_testing_wallet', String(index))
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
  await waitForApi(`/products/${draft.product_id}/verify`, data => data.evidence?.status === 'verified', 'canonical registration evidence')
  await lifecycle.getByRole('button', { name: 'Refresh transaction evidence' }).first().click()
  await lifecycle.getByText('registration · indexed · matching confirmed event', { exact: true }).waitFor()
  await lifecycle.getByLabel('New metadata URI').fill('ipfs://browser-confirmed-version')
  const metadataSaved = page.waitForResponse(response => response.url().endsWith(`/products/${draft.product_id}/registration`) && response.request().method() === 'POST')
  await lifecycle.getByRole('button', { name: 'Sign metadata update' }).click()
  assert.equal((await metadataSaved).status(), 200)
  await waitForApi(`/products/${draft.product_id}`, data => data.product.metadata_uri === 'ipfs://browser-confirmed-version', 'indexed metadata update')
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

  // Increment 8: real mobile detail actions, canonical history and public labels.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`http://localhost:13000/shipments/${shipment.shipment_id}`, { waitUntil: 'domcontentloaded' })
  // Increment 9: owner policy is a durable API write, separate from chain custody.
  await page.getByLabel('Hours without a checkpoint during transit', { exact: true }).fill('30')
  const policyResponse = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes(`/exceptions/policies/${shipment.shipment_id}`))
  await page.getByRole('button', { name: 'Save exception policy', exact: true }).click()
  const policy = await (await policyResponse).json()
  assert.equal(policy.inactivity_hours, 30)
  assert.equal(policy.revision, 1)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.getByLabel('Hours without a checkpoint during transit', { exact: true }).waitFor()
  assert.equal(await page.getByLabel('Hours without a checkpoint during transit', { exact: true }).inputValue(), '30')
  const recordButton = page.getByRole('button', { name: 'Record checkpoint', exact: true })
  await recordButton.waitFor()
  await recordButton.click()
  let actionDialog = page.getByRole('dialog', { name: 'Record checkpoint', exact: true })
  await actionDialog.getByLabel('Location', { exact: true }).fill('Mobile factory departure')
  await actionDialog.getByLabel('Status', { exact: true }).selectOption('0')
  await actionDialog.getByRole('button', { name: 'Submit checkpoint', exact: true }).click()
  await waitForApi(`/products/${draft.product_id}/timeline`, data => data.items.some(item => item.location === 'Mobile factory departure'), 'first Created checkpoint')
  await recordButton.click()
  await actionDialog.getByLabel('Location', { exact: true }).fill('Mobile route departure')
  await actionDialog.getByLabel('Status', { exact: true }).selectOption('1')
  await actionDialog.getByRole('button', { name: 'Submit checkpoint', exact: true }).click()
  await waitForApi(`/products/${draft.product_id}/timeline`, data => data.items.some(item => item.location === 'Mobile route departure'), 'In Transit checkpoint')
  await page.getByRole('button', { name: 'Transfer custody', exact: true }).click()
  actionDialog = page.getByRole('dialog', { name: 'Transfer custody', exact: true })
  await actionDialog.getByLabel('New handler address', { exact: true }).fill(accounts[1])
  await actionDialog.getByRole('button', { name: 'Confirm custody transfer', exact: true }).click()
  await waitForApi(`/products/${draft.product_id}/timeline`, data => data.items.some(item => item.event_type === 'CustodyTransferred'), 'canonical custody transfer')
  await page.setViewportSize({ width: 1440, height: 1000 })

  await page.evaluate(() => window.switchTestingWallet(1))
  await page.getByRole('button', { name: 'Sign In', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Sign out', exact: true }).count(), 0)
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await page.getByRole('button', { name: 'Sign out', exact: true }).waitFor()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Record checkpoint', exact: true }).click()
  actionDialog = page.getByRole('dialog', { name: 'Record checkpoint', exact: true })
  await actionDialog.getByLabel('Location', { exact: true }).fill('Mobile final depot')
  await actionDialog.getByLabel('Status', { exact: true }).selectOption('3')
  await actionDialog.getByRole('button', { name: 'Submit checkpoint', exact: true }).click()
  await waitForApi(`/shipments/${shipment.shipment_id}`, data => data.status === '3', 'canonical delivery')
  await page.getByText('This shipment is delivered. No further checkpoint or custody actions are available.', { exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: 'Record checkpoint', exact: true }).count(), 0)
  assert.equal(await page.getByRole('button', { name: 'Transfer custody', exact: true }).count(), 0)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  const visitor = await browser.newPage({ viewport: { width: 390, height: 844 } })
  visitor.on('pageerror', error => errors.push(error.message))
  await visitor.goto(`http://localhost:13000/verify/${draft.product_id}`, { waitUntil: 'domcontentloaded' })
  await visitor.getByText('Blockchain Registration Confirmed', { exact: true }).waitFor()
  const timeline = visitor.getByRole('region', { name: 'Evidence timeline' })
  await timeline.getByRole('heading', { name: 'Delivery completed', exact: true }).waitFor()
  await visitor.getByRole('button', { name: 'Share / QR label', exact: true }).click()
  const label = visitor.getByRole('dialog', { name: 'Public verification label' })
  assert.equal(await label.getByLabel('Public verification URL').inputValue(), `http://localhost:13000/verify/${draft.product_id}`)
  const qrDownloadPromise = visitor.waitForEvent('download')
  await label.getByRole('link', { name: 'Download QR label' }).click()
  const qrDownload = await qrDownloadPromise
  assert.ok(readFileSync(await qrDownload.path(), 'utf8').includes('Does not authenticate a physical item'))
  await visitor.keyboard.press('Escape')
  await visitor.screenshot({ path: '../.testing/journey-local-public-mobile.png', fullPage: true })
  await visitor.close()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('http://localhost:13000/shipments', { waitUntil: 'domcontentloaded' })

  assert.equal(await page.getByRole('button', { name: `Edit shipment ${shipment.shipment_id}`, exact: true }).count(), 0)
  const checks = await page.evaluate(async ({ api, productId, shipmentId }) => {
    if (!localStorage.getItem('veritras_auth_token')) throw new Error('Expected signed session for cross-wallet checks')
    const auth = { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('veritras_auth_token')}` }
    const edit = await fetch(`${api}/products/${productId}`, { method: 'PUT', headers: auth, body: JSON.stringify({ name: 'Unauthorized' }) })
    const plan = await fetch(`${api}/shipments/`, { method: 'POST', headers: auth, body: JSON.stringify({ product_id: productId, origin: 'Other', destination: 'Other' }) })
    const shipmentEdit = await fetch(`${api}/shipments/${shipmentId}`, { method: 'PUT', headers: auth, body: JSON.stringify({ notes: 'Unauthorized' }) })
    const exceptionPolicy = await fetch(`${api}/exceptions/policies/${shipmentId}`, { method: 'PUT', headers: auth, body: JSON.stringify({ expected_revision: 1, inactivity_hours: 31 }) })
    const anonymous = await fetch(`${api}/products/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Anonymous' }) })
    const publicRead = await fetch(`${api}/products/${productId}`)
    return [edit.status, plan.status, shipmentEdit.status, exceptionPolicy.status, anonymous.status, publicRead.status]
  }, { api, productId: draft.product_id, shipmentId: shipment.shipment_id })
  assert.deepEqual(checks, [403, 403, 403, 403, 401, 200])
  // Real browser analytics and downloads must agree with the same API cohort.
  await page.goto('http://localhost:13000/analytics', { waitUntil: 'domcontentloaded' })
  await page.getByRole('region', { name: 'Shipment sample counts' }).waitFor()
  await page.getByLabel('Origin', { exact: true }).fill(shipment.origin)
  await page.getByLabel('Destination', { exact: true }).fill(shipment.destination)
  const cohortResponse = page.waitForResponse(response => response.ok() && response.url().includes('/analytics/kpis?') && response.url().includes('origin='))
  await page.getByRole('button', { name: 'Apply filters' }).click()
  const metrics = await (await cohortResponse).json()
  const sampleRegion = page.getByRole('region', { name: 'Shipment sample counts' })
  assert.ok((await sampleRegion.innerText()).includes(`Total shipments: ${metrics.total_shipments}`))
  assert.ok((await sampleRegion.innerText()).includes(`SLA: ${metrics.sla_sample_size} samples`))
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click()
  const download = await downloadPromise
  const csv = readFileSync(await download.path(), 'utf8')
  assert.equal(csv.trim().split('\n').length-1, metrics.total_shipments)
  assert.ok(csv.includes(shipment.shipment_id))
  const pdfPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export PDF', exact: true }).click()
  const pdf = await pdfPromise
  assert.ok(readFileSync(await pdf.path()).subarray(0,4).equals(Buffer.from('%PDF')))
  await page.screenshot({ path: '../.testing/analytics-local-browser.png', fullPage: true })
  assert.deepEqual(errors, [])
  mkdirSync('../.testing', { recursive: true })
  await page.screenshot({ path: '../.testing/auth-browser.png', fullPage: true })
  console.log('PASS: real browser registration/reload recovery, metadata update/history, wallet sign-in, owned draft/shipment writes, wallet-switch logout, mobile detail checkpoints/custody/delivery, public QR download/evidence, cross-wallet denial, and anonymous public reads')
} catch (error) {
  if (page) await page.screenshot({ path: '../.testing/registration-browser-failure.png', fullPage: true })
  console.error({ buttons: page ? await page.locator('button').allTextContents() : [], lifecycle: page ? await page.getByRole('region', { name: 'Registration lifecycle' }).allTextContents() : [] })
  throw error
} finally {
  await browser.close()
}
