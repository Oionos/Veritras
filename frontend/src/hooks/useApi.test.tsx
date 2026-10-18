vi.mock('@/hooks/useAuth', () => ({ getAuthToken: () => null, clearAuthToken: vi.fn() }))
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import {
  useProducts,
  useProduct,
  useKPIData,
  useCreateProduct,
  useUpdateProduct,
} from './useApi'

const createTestQueryClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  })

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={createTestQueryClient()}>
    {children}
  </QueryClientProvider>
)

describe('useApi hooks', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  describe('useProducts', () => {
    it('fetches and returns product data', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(JSON.stringify([{ id: 1, name: 'Test Product' }])),
      } as Response)

      const { result } = renderHook(() => useProducts(), { wrapper })

      expect(result.current.isPending).toBe(true)

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      expect(result.current.data).toEqual([{ id: 1, name: 'Test Product' }])
    })

    it('handles loading state', () => {
      globalThis.fetch = vi.fn(() => new Promise(() => {}))

      const { result } = renderHook(() => useProducts(), { wrapper })

      expect(result.current.isPending).toBe(true)
      expect(result.current.isFetching).toBe(true)
    })
  })

  describe('useProduct', () => {
    it('does not fetch when id is empty', () => {
      globalThis.fetch = vi.fn()

      const { result } = renderHook(() => useProduct(''), { wrapper })

      expect(result.current.isPending).toBe(true)
      expect(result.current.fetchStatus).toBe('idle')
      expect(globalThis.fetch).not.toHaveBeenCalled()
    })

    it('fetches when id is provided', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ id: 1, name: 'Widget' })),
      } as Response)

      const { result } = renderHook(() => useProduct('PROD-001'), { wrapper })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/products/PROD-001'),
        expect.objectContaining({ headers: expect.any(Object) })
      )
      expect(result.current.data).toEqual({ id: 1, name: 'Widget' })
    })
  })

  describe('useKPIData', () => {
    it('returns error when fetch fails', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        text: () => Promise.resolve('Server error'),
      } as Response)

      const { result } = renderHook(() => useKPIData(), { wrapper })

      await waitFor(() => expect(result.current.isError).toBe(true))

      expect(result.current.error).toBeInstanceOf(Error)
      expect(result.current.error?.message).toContain('500')
      expect(result.current.error?.message).toContain('Server error')
    })

    it('handles empty response gracefully', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(''),
      } as Response)

      const { result } = renderHook(() => useKPIData(), { wrapper })

      await waitFor(() => expect(result.current.isSuccess).toBe(true))

      expect(result.current.data).toBeNull()
    })
  })

  describe('useCreateProduct', () => {
    it('invalidates products query on success', async () => {
      const queryClient = createTestQueryClient()
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

      const customWrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      )

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ id: 1, product_id: 'PROD-001' })),
      } as Response)

      const { result } = renderHook(() => useCreateProduct(), {
        wrapper: customWrapper,
      })

      await result.current.mutateAsync({
        name: 'Test Product',
        manufacturer_address: '0x1234567890123456789012345678901234567890',
      })

      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['products'] })
    })

    it('returns error when mutation fails', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        text: () => Promise.resolve('Invalid data'),
      } as Response)

      const { result } = renderHook(() => useCreateProduct(), { wrapper })

      await expect(
        result.current.mutateAsync({
          name: 'Test',
          manufacturer_address: '0x1234567890123456789012345678901234567890',
        })
      ).rejects.toThrow('Invalid data')
    })

    it('sends manufacturer_address in the request body (regression)', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ id: 1, product_id: 'PROD-001' })),
      } as Response)
      globalThis.fetch = fetchMock

      const { result } = renderHook(() => useCreateProduct(), { wrapper })

      await result.current.mutateAsync({
        name: 'Test Product',
        manufacturer_address: '0x1234567890123456789012345678901234567890',
      })

      const [, options] = fetchMock.mock.calls[0]
      const body = JSON.parse(options.body as string)

      expect(body).toHaveProperty('manufacturer_address', '0x1234567890123456789012345678901234567890')
      expect(body).not.toHaveProperty('manufacturer')
    })
  })

  describe('useUpdateProduct', () => {
    it('sends manufacturer_address in the request body (regression)', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        text: () => Promise.resolve(JSON.stringify({ id: 1, product_id: 'PROD-001' })),
      } as Response)
      globalThis.fetch = fetchMock

      const { result } = renderHook(() => useUpdateProduct(), { wrapper })

      await result.current.mutateAsync({
        product_id: 'PROD-001',
        data: {
          name: 'Updated Product',
          manufacturer_address: '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd',
        },
      })

      const [, options] = fetchMock.mock.calls[0]
      const body = JSON.parse(options.body as string)

      expect(body).toHaveProperty('manufacturer_address', '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd')
      expect(body).not.toHaveProperty('manufacturer')
    })
  })
  it('requests a recent product page with explicit descending creation order', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve(JSON.stringify({ items: [], total: 0 })) } as Response)
    const { result } = renderHook(() => useProducts(true), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining('/products?sort_by=created_at&sort_order=desc&limit=5'), expect.any(Object))
  })

})
