import { appEnvironment } from '@/config/runtime'
import { useQuery } from '@tanstack/react-query'
import type { Product } from '@/types'
import { getAuthToken } from '@/hooks/useAuth'

const API_URL = appEnvironment.apiUrl

async function fetchProductList(limit: number): Promise<{ items: Product[]; total: number }> {
  const token = getAuthToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  const params = new URLSearchParams({ skip: '0', limit: String(limit) })
  const response = await fetch(`${API_URL}/products?${params}`, { headers })

  if (!response.ok) {
    throw new Error(`Failed to fetch products (${response.status})`)
  }

  const text = await response.text()
  if (!text) return { items: [], total: 0 }
  return JSON.parse(text) as { items: Product[]; total: number }
}

export function useProductList(limit = 100) {
  return useQuery<{ items: Product[]; total: number }>({
    queryKey: ['product-list', limit],
    queryFn: () => fetchProductList(limit),
    staleTime: 5 * 60 * 1000, // cache for 5 minutes — products change infrequently
  })
}
