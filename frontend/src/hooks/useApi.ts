import { appEnvironment } from '@/config/runtime'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Product, Shipment } from '@/types'
import type { components } from '@/types/api'
import { getAuthToken, clearAuthToken } from './useAuth'

const API_URL = appEnvironment.apiUrl

async function fetchApi(endpoint: string, options?: RequestInit) {
  const token = getAuthToken()
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string> || {}),
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  })

  if (response.status === 401) {
    clearAuthToken()
  }

  if (!response.ok) {
    const errorText = await response.text().catch(() => response.statusText)
    throw new Error(`API Error (${response.status}): ${errorText || response.statusText}`)
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

export function useProducts() {
  return useQuery({
    queryKey: ['products'],
    queryFn: () => fetchApi('/products'),
  })
}

export function useProduct(id: string) {
  return useQuery({
    queryKey: ['product', id],
    queryFn: () => fetchApi(`/products/${id}`),
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

export function useKPIData() {
  return useQuery({
    queryKey: ['kpis'],
    queryFn: () => fetchApi('/analytics/kpis'),
  })
}

export function useAnomalies() {
  return useQuery({
    queryKey: ['anomalies'],
    queryFn: () => fetchApi('/analytics/anomalies'),
  })
}

export function useBottlenecks(minDwellHours?: number) {
  return useQuery({
    queryKey: ['bottlenecks', minDwellHours],
    queryFn: () => fetchApi(`/analytics/bottlenecks${minDwellHours ? `?min_dwell_hours=${minDwellHours}` : ''}`),
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
    queryFn: () => fetchApi(`/products/${id}/verify`),
    enabled: !!id,
  })
}

export async function exportAnalytics(format: 'csv' | 'pdf', startDate?: string, endDate?: string) {
  const params = new URLSearchParams({ format })
  if (startDate) params.append('start_date', startDate)
  if (endDate) params.append('end_date', endDate)
  const response = await fetch(`${API_URL}/analytics/export?${params}`, {
    headers: getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {},
  })
  if (response.status === 401) {
    clearAuthToken()
  }
  if (!response.ok) throw new Error('Export failed')
  const blob = await response.blob()
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `veritras-export.${format}`
  a.click()
  window.URL.revokeObjectURL(url)
}

// ─── Paginated / extended hooks ───────────────────────────────────────────────

interface PaginatedResponse<T> {
  items: T[]
  total: number
}

export function useProductsPaginated(page = 1, limit = 10, search?: string, sortBy?: string, sortOrder?: 'asc' | 'desc') {
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

export function useShipments(page = 1, limit = 10, status?: string, search?: string, sortBy?: string, sortOrder?: 'asc' | 'desc') {
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
export type ShipmentMutationInput = Omit<components['schemas']['ShipmentCreate'], 'status'>

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
    mutationFn: async ({ product_id, data }: { product_id: string; data: components['schemas']['ProductUpdate'] }) => {
      return fetchApi(`/products/${product_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] })
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
      queryClient.invalidateQueries({ queryKey: ['shipments'] })
    },
  })
}

export function useUpdateShipment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ shipment_id, data }: { shipment_id: string; data: components['schemas']['ShipmentUpdate'] }) => {
      return fetchApi(`/shipments/${shipment_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['shipments'] })
    },
  })
}
