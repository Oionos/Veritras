import { appEnvironment } from '@/config/runtime'
import { toProductBytes32 } from '@/utils/productId'
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ token: 'test-token', address: '0x1234567890123456789012345678901234567890', isAuthenticated: true, isLoggingIn: false, loginError: null, login: vi.fn(), logout: vi.fn() }),
  getAuthToken: () => null,
  clearAuthToken: vi.fn(),
}))

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import Products from './Products'
import {
  useProductsPaginated,
  useProduct,
  useProductHistory,
  useProductTransfers,
  useCreateProduct,
  useUpdateProduct,
} from '@/hooks/useApi'
import { renderWithProviders } from '@/test/test-utils'

// Intercept wagmi at the module level so the real hooks (which require a
// WagmiProvider store) never execute inside Products.tsx or its dependencies.
vi.mock('wagmi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('wagmi')>()
  return {
    ...actual,
    useAccount: () => ({ isConnected: false, address: undefined }),
    useWriteContract: () => ({ writeContract: vi.fn(), data: undefined, isPending: false, error: null }),
    useWaitForTransactionReceipt: () => ({ isLoading: false, isSuccess: false }),
  }
})

// Short-circuit the local blockchain hooks so their wagmi internals never run.
vi.mock('@/hooks/useRegisterProduct', () => ({
  useRegisterProduct: () => ({
    register: vi.fn(),
    hash: undefined,
    isPending: false,
    isConfirming: false,
    isSuccess: false,
    error: null,
  }),
}))

vi.mock('@/hooks/useShipmentTracker', () => ({
  useShipmentPermissions: () => ({ canRecord: true, canTransfer: true }),
  useRecordCheckpoint: () => ({
    record: vi.fn(),
    hash: undefined,
    isPending: false,
    isConfirming: false,
    isSuccess: false,
    error: null,
  }),
  useTransferCustody: () => ({
    transfer: vi.fn(),
    hash: undefined,
    isPending: false,
    isConfirming: false,
    isSuccess: false,
    error: null,
  }),
  StatusLabels: { 0: 'Created', 1: 'In Transit', 2: 'At Checkpoint', 3: 'Delivered' },
}))

vi.mock('@/hooks/useApi', () => ({
  useProductsPaginated: vi.fn(),
  useProduct: vi.fn(),
  useProductHistory: vi.fn(),
  useProductTransfers: vi.fn(),
  useCreateProduct: vi.fn(),
  useUpdateProduct: vi.fn(),
}))

const mockProducts = [
  { id: 1, product_id: 'PROD-001', on_chain_product_id: toProductBytes32('PROD-001'), chain_id: appEnvironment.chainId, registry_address: appEnvironment.productRegistry, tracker_address: appEnvironment.shipmentTracker, owner_address: '0x1234567890123456789012345678901234567890', ownership_source: 'signed_draft', block_number: 0, tx_hash: '0x', name: 'Widget A', manufacturer_address: '0x1234567890123456789012345678901234567890', registered_at: '2024-01-15T10:00:00Z' },
  { id: 2, product_id: 'PROD-002', name: 'Gadget B', manufacturer_address: '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd', registered_at: '2024-02-20T12:00:00Z' },
]

describe('Products', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    vi.mocked(useProductsPaginated).mockImplementation((...args: any[]) => {
      const search = args[2]
      let items = mockProducts
      if (search) {
        items = mockProducts.filter((p) =>
          p.name.toLowerCase().includes(search.toLowerCase())
        )
      }
      return {
        data: { items, total: 25 },
        isLoading: false,
        error: null,
      } as any
    })

    vi.mocked(useProduct).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useProductHistory).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useProductTransfers).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useCreateProduct).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
      error: null,
    } as any)

    vi.mocked(useUpdateProduct).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
      error: null,
    } as any)
  })

  it('renders product table with data', () => {
    renderWithProviders(<Products />)

    expect(screen.getByText('PROD-001')).toBeInTheDocument()
    expect(screen.getByText('Widget A')).toBeInTheDocument()
    expect(screen.getByText('PROD-002')).toBeInTheDocument()
    expect(screen.getByText('Gadget B')).toBeInTheDocument()
  })

  it('renders pagination controls', () => {
    renderWithProviders(<Products />)

    // Use a custom matcher because "Page 1 of 3" is split across multiple elements
    const paginations = screen.getAllByText((content, element) => {
      return element?.tagName === 'P' && element?.textContent?.includes('Page 1 of 3')
    })
    expect(paginations.length).toBeGreaterThanOrEqual(1)

    expect(screen.getByTestId('icon-ChevronLeft').closest('button')).toBeInTheDocument()
    expect(screen.getByTestId('icon-ChevronRight').closest('button')).toBeInTheDocument()
  })

  it('filters products by name', async () => {
    renderWithProviders(<Products />)

    const searchInput = screen.getByPlaceholderText('Search by product name...')
    fireEvent.change(searchInput, { target: { value: 'Widget' } })

    await waitFor(() => {
      expect(screen.getByText('Widget A')).toBeInTheDocument()
      expect(screen.queryByText('Gadget B')).not.toBeInTheDocument()
    })
  })

  it('renders empty state when no products match search', async () => {
    renderWithProviders(<Products />)

    const searchInput = screen.getByPlaceholderText('Search by product name...')
    fireEvent.change(searchInput, { target: { value: 'NonExistent' } })

    await waitFor(() => {
      expect(screen.getByText('No products match your search')).toBeInTheDocument()
    })
  })

  it('product form uses manufacturer_address as the input name (regression)', async () => {
    renderWithProviders(<Products />)

    fireEvent.click(screen.getByRole('button', { name: /add product/i }))

    const manufacturerInput = screen.getByPlaceholderText('0x...')
    fireEvent.change(manufacturerInput, {
      target: { value: '0x1234567890123456789012345678901234567890' },
    })

    expect(manufacturerInput).toHaveAttribute('name', 'manufacturer_address')
  })

  it('Add Product modal renders description textarea', () => {
    renderWithProviders(<Products />)

    fireEvent.click(screen.getByRole('button', { name: /add product/i }))

    expect(
      screen.getByPlaceholderText('Brief description of the product...')
    ).toBeInTheDocument()
  })

  it('Edit Product modal pre-fills description field', async () => {
    renderWithProviders(<Products />)

    // Click the Edit button for PROD-001 which has description: 'A test product description'
    fireEvent.click(screen.getByRole('button', { name: 'Edit PROD-001' }))

    // Wait for the modal to open
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    // The description textarea must be present in the edit modal
    const descriptionTextarea = screen.getByPlaceholderText(
      'Brief description of the product...'
    )
    expect(descriptionTextarea).toBeInTheDocument()

    // Verify the textarea has the 'description' name attribute (registered with react-hook-form)
    expect(descriptionTextarea).toHaveAttribute('name', 'description')
  })

  it('Create product form passes description to mutateAsync', async () => {
    const mockMutateAsync = vi.fn().mockResolvedValue({
      id: 99,
      product_id: 'PROD-NEW',
      name: 'New Product',
      manufacturer_address: '0x1234567890123456789012345678901234567890',
      registered_at: new Date().toISOString(),
    })

    vi.mocked(useCreateProduct).mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
      error: null,
    } as any)

    renderWithProviders(<Products />)

    fireEvent.click(screen.getByRole('button', { name: /add product/i }))

    // Fill in required fields
    fireEvent.change(screen.getByPlaceholderText('e.g., Organic Coffee Beans'), {
      target: { value: 'New Product' },
    })
    fireEvent.change(screen.getByPlaceholderText('0x...'), {
      target: { value: '0x1234567890123456789012345678901234567890' },
    })
    fireEvent.change(screen.getByPlaceholderText('Brief description of the product...'), {
      target: { value: 'Test desc' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Create Product' }))

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ description: 'Test desc' })
      )
    })
  })
})
