import { test, expect } from '@playwright/test'
import { setupRoutes, isApiOrigin } from './helpers/routes'
import { MOCK_PRODUCT_DETAIL } from './helpers/data'

test.beforeEach(async ({ page }) => {
  await setupRoutes(page)
  await page.goto('/products')
  // Wait for the table to render before each test
  await expect(page.getByText('PROD-001')).toBeVisible()
})

test('product table renders rows from mocked data', async ({ page }) => {
  await expect(page.getByText('PROD-001')).toBeVisible()
  await expect(page.getByText('Alpha Widget')).toBeVisible()
  await expect(page.getByText('PROD-002')).toBeVisible()
  await expect(page.getByText('Beta Gadget')).toBeVisible()
})

test('search input has the correct placeholder', async ({ page }) => {
  await expect(
    page.getByPlaceholder('Search by product name...')
  ).toBeVisible()
})

test('pagination Next button navigates to page 2', async ({ page }) => {
  // Initial state: page 1 of 3 (total=25 with limit=10)
  await expect(page.getByText('Page')).toBeVisible()

  // Click the Next button (ChevronRight icon-only button)
  const nextBtn = page.locator('button').filter({
    has: page.locator('.lucide-chevron-right'),
  })
  await nextBtn.click()

  // After navigation, the pagination indicator should show "Page 2 of …"
  // getByText('2') matches 8+ elements; scope to the pagination <p> to avoid strict-mode violation.
  await expect(page.locator('p').filter({ hasText: /Page 2 of/ })).toBeVisible()
})

test('guest product creation requires wallet sign-in', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Add Product' })).toBeDisabled()
  await expect(page.getByText('Connect your wallet and sign in to create products or edit your drafts.')).toBeVisible()
})

test('guest cannot edit another wallet’s product', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Edit PROD-001' })).toHaveCount(0)
})

test('lookup by product ID shows the product detail card', async ({ page }) => {
  await page.getByPlaceholder('Enter product ID (e.g., PROD-8842)').fill('PROD-001')
  await page.getByRole('button', { name: 'Search' }).click()
  // The product detail card should render the product_id
  await expect(page.getByText(MOCK_PRODUCT_DETAIL.product.product_id).nth(0)).toBeVisible()
})

test('lookup with unknown ID shows Product Not Found error', async ({ page }) => {
  // Override the product detail route to return 404 (last registered wins)
  await page.route(
    url => isApiOrigin(url) && /^\/products\/[^/]+$/.test(url.pathname),
    route => route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not found' }),
    })
  )

  await page.getByPlaceholder('Enter product ID (e.g., PROD-8842)').fill('NONEXISTENT')
  await page.getByRole('button', { name: 'Search' }).click()
  await expect(page.getByText('Product Not Found')).toBeVisible({ timeout: 15000 })
})

test('guest product lookup remains available without a creation dialog', async ({ page }) => {
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Search' })).toBeEnabled()
})
