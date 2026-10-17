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

// ── Mock overrides ────────────────────────────────────────────────────────────

vi.mock('wagmi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('wagmi')>()
  return {
    ...actual,
    useAccount: () => ({ isConnected: false, address: undefined }),
    useWriteContract: () => ({ writeContract: vi.fn(), data: undefined, isPending: false, error: null }),
    useWaitForTransactionReceipt: () => ({ isLoading: false, isSuccess: false }),
  }
})

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

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Products form — on-change validation', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    vi.mocked(useProductsPaginated).mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      error: null,
    } as any)
    vi.mocked(useProduct).mockReturnValue({ data: null, isLoading: false, error: null } as any)
    vi.mocked(useProductHistory).mockReturnValue({ data: null, isLoading: false, error: null } as any)
    vi.mocked(useProductTransfers).mockReturnValue({ data: null, isLoading: false, error: null } as any)
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

  const openAddModal = () =>
    fireEvent.click(screen.getByRole('button', { name: /add product/i }))

  it('shows name error immediately when a single character is typed — without submit', async () => {
    renderWithProviders(<Products />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('e.g., Organic Coffee Beans'), {
      target: { value: 'A' },
    })

    await waitFor(() => {
      expect(screen.getByText('Name must be at least 2 characters')).toBeInTheDocument()
    })
  })

  it('shows address error immediately when an invalid address is typed — without submit', async () => {
    renderWithProviders(<Products />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('0x...'), {
      target: { value: 'not-an-address' },
    })

    await waitFor(() => {
      expect(screen.getByText('Must be a valid Ethereum address')).toBeInTheDocument()
    })
  })

  it('shows metadata_uri error immediately when an invalid URL is typed — without submit', async () => {
    renderWithProviders(<Products />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('https://...'), {
      target: { value: 'not-a-valid-url' },
    })

    await waitFor(() => {
      expect(screen.getByText('Must be a valid URL')).toBeInTheDocument()
    })
  })

  it('clears name error as soon as a valid name replaces the invalid one', async () => {
    renderWithProviders(<Products />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('e.g., Organic Coffee Beans'), {
      target: { value: 'A' },
    })
    await waitFor(() => {
      expect(screen.getByText('Name must be at least 2 characters')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('e.g., Organic Coffee Beans'), {
      target: { value: 'Valid Product' },
    })
    await waitFor(() => {
      expect(screen.queryByText('Name must be at least 2 characters')).not.toBeInTheDocument()
    })
  })
})
