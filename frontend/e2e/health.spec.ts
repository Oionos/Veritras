import { test, expect } from '@playwright/test'
import { setupRoutes, isApiOrigin } from './helpers/routes'

test.beforeEach(async ({ page }) => { await setupRoutes(page) })
for (const [status, message] of [
  ['catching_up', 'Blockchain activity is syncing.'],
  ['degraded', 'Blockchain updates are delayed.'],
  ['disabled', 'Blockchain updates are paused.'],
]) {
  test(`explains synchronization state ${status}`, async ({ page }) => {
    await page.route(url => isApiOrigin(url) && url.pathname === '/health/ready', route => route.fulfill({
      status: status === 'disabled' ? 200 : 503,
      json: { status: status === 'disabled' ? 'ready' : 'not_ready', database: 'connected', indexer: { status } },
    }))
    await page.goto('/products')
    await expect(page.getByRole('status', { name: 'Blockchain synchronization' })).toContainText(message)
  })
}
