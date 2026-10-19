import { reportMetric } from '@/config/telemetry'
import { appEnvironment } from '@/config/runtime'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Product, ProductDetail, Shipment } from '@/types'
import type { components } from '@/types/api'
import { getAuthToken, clearAuthToken } from './useAuth'

const API_URL = appEnvironment.apiUrl

export async function fetchApi(endpoint: string, options?: RequestInit) {
  const token = getAuthToken()
  const headers: Record<string, string> = {
    ...((options?.headers as Record<string, string>) || {}),
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  let response: Response
  try { response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  }) } catch (error) { if (!(error instanceof DOMException && error.name === 'AbortError')) reportMetric('api_error', 1); throw error }

  if (response.status === 401) {
    clearAuthToken()
  }

  if (!response.ok) {
    if (response.status >= 500) reportMetric('api_error', 1)
    const errorText = await response.text().catch(() => response.statusText)
    throw new Error(
      `API Error (${response.status}): ${errorText || response.statusText}`
    )
  }
  // Handle empty responses gracefully
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

// ─── Existing hooks (unchanged) ───────────────────────────────────────────────

export function useProducts(recent = false) {
  return useQuery({
    queryKey: recent ? ['products', 'recent'] : ['products'],
    queryFn: () =>
      fetchApi(
        recent
          ? '/products?sort_by=created_at&sort_order=desc&limit=5'
          : '/products'
      ),
  })
}

export function useProduct(id: string) {
  return useQuery<ProductDetail>({
    queryKey: ['product', id],
    queryFn: () => fetchApi(`/products/${encodeURIComponent(id)}`),
    enabled: !!id,
  })
}

export function useProductHistory(id: string) {
  return useQuery({
    queryKey: ['product-history', id],
    queryFn: () => fetchApi(`/shipments/${id}/history`),
    enabled: !!id,
  })
}

export function useProductTransfers(id: string) {
  return useQuery({
    queryKey: ['product-transfers', id],
    queryFn: () => fetchApi(`/shipments/${id}/transfers`),
    enabled: !!id,
  })
}

export interface AnalyticsFilterInput {
  start_date?: string
  end_date?: string
  origin?: string
  destination?: string
}

export function analyticsQuery(filters?: AnalyticsFilterInput) {
  const params = new URLSearchParams()
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  return params.size ? `?${params}` : ''
}

export function useKPIData(filters?: AnalyticsFilterInput) {
  return useQuery({
    queryKey: ['kpis', filters],
    queryFn: () =>
      fetchApi(`/analytics/kpis${analyticsQuery(filters)}`) as Promise<
        components['schemas']['KPIResponse']
      >,
  })
}

export function useAnomalies(filters?: AnalyticsFilterInput) {
  return useQuery({
    queryKey: ['anomalies', filters],
    queryFn: () => fetchApi(`/analytics/anomalies${analyticsQuery(filters)}`),
  })
}

export function useBottlenecks(minDwellHours?: number) {
  return useQuery({
    queryKey: ['bottlenecks', minDwellHours],
    queryFn: () =>
      fetchApi(
        `/analytics/bottlenecks${minDwellHours ? `?min_dwell_hours=${minDwellHours}` : ''}`
      ),
  })
}

export function useDailyVolume() {
  return useQuery({
    queryKey: ['daily-volume'],
    queryFn: () => fetchApi('/analytics/daily-volume'),
  })
}

export function useVerifyProduct(id: string) {
  return useQuery({
    queryKey: ['verify', id],
    queryFn: () =>
      fetchApi(`/products/${encodeURIComponent(id)}/verify`) as Promise<
        components['schemas']['VerificationResponse']
      >,
    enabled: !!id,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  })
}

export async function exportAnalytics(
  format: 'csv' | 'pdf',
  startDate?: string,
  endDate?: string,
  filters?: AnalyticsFilterInput,
  report: 'shipments' | 'events' = 'shipments'
) {
  const params = new URLSearchParams({ format })
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  Object.entries(filters ?? {}).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('report', report)
  const response = await fetch(`${API_URL}/analytics/export?${params}`, {
    headers: getAuthToken()
      ? { Authorization: `Bearer ${getAuthToken()}` }
      : {},
  })
  if (response.status === 401) {
    clearAuthToken()
  }
  if (!response.ok) throw new Error('Export failed')
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `veritras-${report}.${format}`
  a.click()
  window.URL.revokeObjectURL(url)
}

// ─── Paginated / extended hooks ───────────────────────────────────────────────

interface PaginatedResponse<T> {
  items: T[]
  total: number
}

export function useProductsPaginated(
  page = 1,
  limit = 10,
  search?: string,
  sortBy?: string,
  sortOrder?: 'asc' | 'desc'
) {
  const skip = (page - 1) * limit
  const params = new URLSearchParams()
  params.set('skip', String(skip))
  params.set('limit', String(limit))
  if (search) params.set('search', search)
  if (sortBy) params.set('sort_by', sortBy)
  if (sortOrder) params.set('sort_order', sortOrder)
  return useQuery<PaginatedResponse<Product>>({
    queryKey: ['products', 'paginated', page, limit, search, sortBy, sortOrder],
    queryFn: () => fetchApi(`/products?${params.toString()}`),
  })
}

export function useShipments(
  page = 1,
  limit = 10,
  status?: string,
  search?: string,
  sortBy?: string,
  sortOrder?: 'asc' | 'desc'
) {
  const skip = (page - 1) * limit
  const params = new URLSearchParams()
  params.set('skip', String(skip))
  params.set('limit', String(limit))
  if (status && status !== 'all') params.set('status', status)
  if (search) params.set('search', search)
  if (sortBy) params.set('sort_by', sortBy)
  if (sortOrder) params.set('sort_order', sortOrder)
  return useQuery<PaginatedResponse<Shipment>>({
    queryKey: ['shipments', page, limit, status, search, sortBy, sortOrder],
    queryFn: () => fetchApi(`/shipments?${params.toString()}`),
  })
}

// ─── Mutations ────────────────────────────────────────────────────────────────

/** Derived from generated ProductCreate schema */
export type ProductMutationInput = components['schemas']['ProductCreate']

/**
 * ShipmentCreate has `status` as a required field (openapi-typescript v7 emits
 * @default fields as required TypeScript properties). Callers never pass status
 * on creation — the backend defaults it — so we Omit it here.
 */
export type ShipmentMutationInput = Omit<
  components['schemas']['ShipmentCreate'],
  'status'
>

export function useCreateProduct() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data: ProductMutationInput) => {
      return fetchApi('/products', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
    },
  })
}

export function useUpdateProduct() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      product_id,
      data,
    }: {
      product_id: string
      data: components['schemas']['ProductUpdate']
    }) => {
      return fetchApi(`/products/${product_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
    },
    onSuccess: async (_data, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['products'] }),
        queryClient.invalidateQueries({
          queryKey: ['product', variables.product_id],
        }),
        queryClient.invalidateQueries({
          queryKey: ['verify', variables.product_id],
        }),
      ])
    },
  })
}

export function useCreateShipment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data: ShipmentMutationInput) => {
      return fetchApi('/shipments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
    },
    onSuccess: () => {
      for (const key of [
        'shipments',
        'kpis',
        'anomalies',
        'bottlenecks',
        'daily-volume',
      ]) {
        void queryClient.invalidateQueries({ queryKey: [key] })
      }
    },
  })
}

export function useUpdateShipment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      shipment_id,
      data,
    }: {
      shipment_id: string
      data: components['schemas']['ShipmentUpdate']
    }) => {
      return fetchApi(`/shipments/${shipment_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
    },
    onSuccess: () => {
      for (const key of [
        'shipments',
        'kpis',
        'anomalies',
        'bottlenecks',
        'daily-volume',
      ]) {
        void queryClient.invalidateQueries({ queryKey: [key] })
      }
    },
  })
}
