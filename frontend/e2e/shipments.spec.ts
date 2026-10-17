import { test, expect } from '@playwright/test'
import { setupRoutes } from './helpers/routes'

test.beforeEach(async ({ page }) => {
  await setupRoutes(page)
  await page.goto('/shipments')
  // Wait for the table to render before each test
  await expect(page.getByText('SHP-001')).toBeVisible()
})

test('shipment table renders rows from mocked data', async ({ page }) => {
  await expect(page.getByText('SHP-001')).toBeVisible()
  await expect(page.getByText('Shanghai')).toBeVisible()
  await expect(page.getByText('Rotterdam')).toBeVisible()
  await expect(page.getByText('SHP-002')).toBeVisible()
  await expect(page.getByText('New York')).toBeVisible()
  await expect(page.getByText('London')).toBeVisible()
})

test('search input has the correct placeholder', async ({ page }) => {
  await expect(
    page.getByPlaceholder('Search by origin or destination...')
  ).toBeVisible()
})

test('guest shipment creation requires wallet sign-in', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Add Shipment' })).toBeDisabled()
  await expect(page.getByText('Connect your wallet and sign in to plan shipments for products you own.')).toBeVisible()
})

test('guest cannot edit another wallet’s shipment', async ({ page }) => {
  await expect(page.getByRole('button', { name: 'Edit shipment SHP-001' })).toHaveCount(0)
})

test('status filter select shows all status options', async ({ page }) => {
  // The status select contains "All Statuses" as its first option
  const statusSelect = page.locator('select').filter({ hasText: 'All Statuses' })
  await expect(statusSelect).toBeVisible()
  // 5 options: All Statuses, Created, In Transit, At Checkpoint, Delivered
  await expect(statusSelect.locator('option')).toHaveCount(5)
})
