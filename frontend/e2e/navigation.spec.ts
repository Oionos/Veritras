import { test, expect } from '@playwright/test'
import { setupRoutes } from './helpers/routes'

// Routes must be set up before navigation so mocked responses are in place.
test.beforeEach(async ({ page }) => {
  await setupRoutes(page)
})

test('default route renders the Dashboard page', async ({ page }) => {
  await page.goto('/')
  // "Supply Chain" h2 heading is unique to the Dashboard overview section
  await expect(page.getByRole('heading', { name: 'Supply Chain' })).toBeVisible()
})

test('nav links navigate to the correct pages', async ({ page }) => {
  await page.goto('/')

  // Navigate to Products
  await page.getByRole('link', { name: 'Products' }).first().click()
  // "Add Product" button is unique to the Products page
  await expect(page.getByRole('button', { name: 'Add Product' })).toBeVisible()

  // Navigate to Shipments
  await page.getByRole('link', { name: 'Shipments' }).first().click()
  // "Add Shipment" button is unique to the Shipments page
  await expect(page.getByRole('button', { name: 'Add Shipment' })).toBeVisible()

  // Navigate to Verify
  await page.getByRole('link', { name: 'Verify' }).first().click()
  await expect(page.getByText('Verify Registration')).toBeVisible()
})

test('Veritras logo navigates back to the Dashboard from a sub-page', async ({ page }) => {
  await page.goto('/products')
  // Wait for the Products page to fully render
  await expect(page.getByRole('button', { name: 'Add Product' })).toBeVisible()

  await page.getByRole('link', { name: 'Veritras' }).click()
  await expect(page.getByRole('heading', { name: 'Supply Chain' })).toBeVisible()
})
