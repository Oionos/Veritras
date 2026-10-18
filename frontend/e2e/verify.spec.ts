import { test, expect } from '@playwright/test'
import { setupRoutes, isApiOrigin } from './helpers/routes'
import { MOCK_VERIFY_FAIL } from './helpers/data'

// Each test navigates individually so the failure test can register its route
// override BEFORE clicking Verify (last registered wins in Playwright).
test.beforeEach(async ({ page }) => {
  await setupRoutes(page)
  await page.goto('/verify')
  await expect(page.getByRole('heading', { name: 'Verify Registration' })).toBeVisible()
})

test('initial state shows the empty-state placeholder', async ({ page }) => {
  await expect(page.getByPlaceholder('Enter product ID')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Verify' })).toBeVisible()
  await expect(
    page.getByText('Enter a product ID to check its blockchain registration and recorded history.', { exact: true })
  ).toBeVisible()
})

test('successful verification shows registration evidence banner', async ({ page }) => {
  // Default route returns MOCK_VERIFY_OK with is_registered: true
  await page.getByPlaceholder('Enter product ID').fill('PROD-001')
  await page.getByRole('button', { name: 'Verify' }).click()
  await expect(page.getByText('Blockchain Registration Confirmed')).toBeVisible()
})

test('failed verification shows Registration Not Confirmed message', async ({ page }) => {
  // Override the verify route to return is_registered: false (last registered wins)
  await page.route(
    url =>
      isApiOrigin(url) &&
      /^\/products\/[^/]+\/verify$/.test(url.pathname),
    route => route.fulfill({ json: MOCK_VERIFY_FAIL })
  )

  await page.getByPlaceholder('Enter product ID').fill('FAKE-001')
  await page.getByRole('button', { name: 'Verify' }).click()
  await expect(page.getByText('Registration Not Confirmed')).toBeVisible()
})

for (const state of [
  { status: 'pending', reason: 'awaiting_indexer', registration_status: 'indexing', heading: 'Registration Pending' },
  { status: 'unavailable', reason: 'evidence_unavailable', registration_status: 'submitted', heading: 'Evidence Unavailable' },
  { status: 'mismatched', reason: 'registration_event_mismatch', registration_status: 'failed', heading: 'Registration Evidence Mismatch' },
]) {
  test(`${state.status} evidence explains the state without claiming verification`, async ({ page }) => {
    await page.route(url => isApiOrigin(url) && /^\/products\/[^/]+\/verify$/.test(url.pathname), route => route.fulfill({ json: {
      ...MOCK_VERIFY_FAIL,
      evidence: { ...state, chain_id: 11155111, registry_address: `0x${'1'.repeat(40)}`, on_chain_product_id: `0x${'a'.repeat(64)}`, manufacturer_address: `0x${'2'.repeat(40)}`, transaction_hash: `0x${'b'.repeat(64)}`, block_number: 100, block_hash: `0x${'c'.repeat(64)}`, required_confirmations: 12, observed_confirmations: 12, physical_authenticity_verified: false },
      synchronization: { status: 'catching_up', reason: 'awaiting_confirmed_target', lag_blocks: 2, confirmation_policy: 'depth', confirmations: 12, indexer_enabled: true, cursor_storage: 'database', indexed_block: 98, last_successful_sync: null },
    } }))
    await page.getByPlaceholder('Enter product ID').fill('PROD-PENDING')
    await page.getByRole('button', { name: 'Verify' }).click()
    await expect(page.getByText(state.heading, { exact: true })).toBeVisible()
    await expect(page.getByLabel('Registration evidence').getByText(/does not authenticate a physical item/)).toBeVisible()
    await expect(page.getByText('Blockchain Registration Confirmed')).toHaveCount(0)
    await expect(page.getByRole('link', { name: `0x${'b'.repeat(64)}` })).toHaveAttribute('href', `https://sepolia.etherscan.io/tx/0x${'b'.repeat(64)}`)
  })
}
