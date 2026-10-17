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
