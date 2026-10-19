import { test, expect } from '@playwright/test'
import { setupRoutes, isApiOrigin } from './helpers/routes'
import { MOCK_KPI } from './helpers/data'

// Each test calls setupRoutes itself so the loading-spinner test can register
// an override route BETWEEN setupRoutes and page.goto().
test.beforeEach(async ({ page }) => {
  await setupRoutes(page)
})

test('KPI cards render with mocked values', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByText('Total Shipments')).toBeVisible()
  await expect(page.getByText('Active Shipments')).toBeVisible()
  await expect(page.getByText('Avg Transit Time')).toBeVisible()
  await expect(page.getByText('On-Time Rate')).toBeVisible()
  // Spot-check computed display values from MOCK_KPI
  await expect(page.getByText('24.5 hrs')).toBeVisible()
  await expect(page.getByText('87.3%')).toBeVisible()
})

test('Shipment Volume chart section renders', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Shipment Volume', exact: true })).toBeVisible()
})

test('Recent Products section renders', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Recent Products')).toBeVisible()
})

test('loading spinner appears while KPI data is being fetched', async ({ page }) => {
  // Register a slow KPI route AFTER setupRoutes so it takes priority (last-wins).
  // The 500 ms delay gives Playwright time to assert the spinner before it disappears.
  await page.route(
    url => isApiOrigin(url) && url.pathname === '/analytics/kpis',
    async route => {
      await new Promise<void>(r => setTimeout(r, 500))
      await route.fulfill({ json: MOCK_KPI })
    }
  )

  await page.goto('/')

  // The spinner must be visible while the KPI request is in flight
  await expect(page.locator('[aria-label="Loading"]')).toBeVisible()
})
