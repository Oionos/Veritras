/**
 * Network route setup for Playwright E2E tests.
 *
 * The app uses VITE_API_URL=https://chainlens-4qvy.onrender.com (from .env).
 * That origin is allowed by the app's CSP connect-src, so fetch() calls
 * reach the network layer where Playwright's CDP interceptor can catch them.
 *
 * We intercept using URL predicate functions (not glob strings) to avoid
 * ambiguity with query-string `?` characters.
 *
 * Registration order: broad/default routes first, specific ones last.
 * In Playwright, the LAST registered matching route handler wins.
 * Per-test overrides should be registered AFTER calling setupRoutes().
 */

import type { Page } from '@playwright/test'
import {
  MOCK_PRODUCTS,
  MOCK_PAGINATED_PRODUCTS,
  MOCK_PRODUCT_LIST,
  MOCK_PRODUCT_DETAIL,
  MOCK_SHIPMENTS,
  MOCK_KPI,
  MOCK_DAILY_VOLUME,
  MOCK_VERIFY_OK,
} from './data'

/**
 * All origins that the app may use for API calls.
 *
 * The primary origin is https://chainlens-4qvy.onrender.com (from frontend/.env).
 * http://localhost:8000 is retained as a fallback for local backend runs.
 */
export const API_ORIGINS = [
  'http://localhost:8000',
  'https://chainlens-4qvy.onrender.com',
]

/** Returns true when the request originates from any known API host. */
export function isApiOrigin(url: URL): boolean {
  return API_ORIGINS.includes(url.origin)
}

/** Returns true when the request URL targets the given API pathname exactly. */
function apiPath(url: URL, pathname: string): boolean {
  return isApiOrigin(url) && url.pathname === pathname
}

export async function setupRoutes(page: Page): Promise<void> {
  await page.route(url => isApiOrigin(url) && url.pathname.replace(/\/$/, '') === '/exceptions', route => route.fulfill({ json: { items: [], total: 0, evaluation: { paused: true, reason: 'indexing_disabled', evaluated_at: null, block_number: null, uncertain_shipments: 0 } } }))
  await page.route(url => isApiOrigin(url) && /^\/shipments\/[^/]+$/.test(url.pathname), route => route.fulfill({ json: MOCK_SHIPMENTS.items[0] }))
  await page.route(url => isApiOrigin(url) && /^\/products\/[^/]+\/timeline$/.test(url.pathname), route => route.fulfill({ json: { product_id: 'PROD-001', items: [], total: 0, skip: 0, limit: 100 } }))
  // SSE — return an empty event stream so EventSource does not keep reconnecting
  await page.route(
    url => apiPath(url, '/analytics/events'),
    route => route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
  )

  // Cached synchronization status is mocked with the business fixtures.
  await page.route(
    url => apiPath(url, '/health/ready'),
    route => route.fulfill({ json: { status: 'ready', database: 'connected', indexer: { status: 'current' } } })
  )

  // Analytics endpoints
  await page.route(
    url => apiPath(url, '/analytics/kpis'),
    route => route.fulfill({ json: MOCK_KPI })
  )
  await page.route(
    url => apiPath(url, '/analytics/daily-volume'),
    route => route.fulfill({ json: MOCK_DAILY_VOLUME })
  )
  await page.route(
    url => apiPath(url, '/analytics/anomalies'),
    route => route.fulfill({ json: [] })
  )
  await page.route(
    url => isApiOrigin(url) && url.pathname.startsWith('/analytics/bottlenecks'),
    route => route.fulfill({ json: [] })
  )

  // Shipment sub-resources — must be registered before the generic /shipments route
  // so the more-specific regex takes priority (last registered wins only when URLs
  // would otherwise match the same predicate; here the regexes are exclusive, but
  // keeping specific routes later is good practice).
  await page.route(
    url => isApiOrigin(url) && /^\/shipments\/[^/]+\/history$/.test(url.pathname),
    route => route.fulfill({ json: [] })
  )
  await page.route(
    url => isApiOrigin(url) && /^\/shipments\/[^/]+\/transfers$/.test(url.pathname),
    route => route.fulfill({ json: [] })
  )

  // Shipments list — any paginated request to /shipments
  await page.route(
    url => apiPath(url, '/shipments') && new URLSearchParams(url.search).has('skip'),
    route => route.fulfill({ json: MOCK_SHIPMENTS })
  )

  // Product verify — register before product detail to avoid regex overlap
  await page.route(
    url => isApiOrigin(url) && /^\/products\/[^/]+\/verify$/.test(url.pathname),
    route => route.fulfill({ json: MOCK_VERIFY_OK })
  )

  // Product detail — single resource, no trailing path segment
  await page.route(
    url => isApiOrigin(url) && /^\/products\/[^/]+$/.test(url.pathname),
    route => route.fulfill({ json: MOCK_PRODUCT_DETAIL })
  )

  // Products — Dashboard (GET /products with no query params → raw array)
  await page.route(
    url => apiPath(url, '/products') && !new URLSearchParams(url.search).has('skip'),
    route => route.fulfill({ json: MOCK_PRODUCTS })
  )

  // Products — ProductCombobox (skip=0, limit=100)
  await page.route(
    url => apiPath(url, '/products') && new URLSearchParams(url.search).get('limit') === '100',
    route => route.fulfill({ json: MOCK_PRODUCT_LIST })
  )

  // Products — paginated table (skip present, limit ≠ 100)
  await page.route(
    url =>
      apiPath(url, '/products') &&
      new URLSearchParams(url.search).has('skip') &&
      new URLSearchParams(url.search).get('limit') !== '100',
    route => route.fulfill({ json: MOCK_PAGINATED_PRODUCTS })
  )
}
