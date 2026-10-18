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

vi.mock('wagmi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('wagmi')>()
  return {
    ...actual,
    useAccount: () => ({
      isConnected: true,
      address: '0x1234567890123456789012345678901234567890',
    }),
    useWriteContract: () => ({
      writeContract: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
    }),
    useWaitForTransactionReceipt: () => ({ isLoading: false, isSuccess: true }),
  }
})

vi.mock('@/hooks/useRegisterProduct', () => ({
  useRegisterProduct: () => ({
    register: vi.fn(),
    hash: '0xabc',
    isPending: false,
    isConfirming: false,
    isSuccess: true,
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
  StatusLabels: {
    0: 'Created',
    1: 'In Transit',
    2: 'At Checkpoint',
    3: 'Delivered',
  },
}))

vi.mock('@/hooks/useApi', () => ({
  useProductsPaginated: vi.fn(),
  useProduct: vi.fn(),
  useProductHistory: vi.fn(),
  useProductTransfers: vi.fn(),
  useCreateProduct: vi.fn(),
  useUpdateProduct: vi.fn(),
}))

describe('Products blockchain status text', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    vi.mocked(useProductsPaginated).mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useProduct).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useProductHistory).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useProductTransfers).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useCreateProduct).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({
        id: 1,
        product_id: 'PROD-NEW',
        name: 'Coffee Beans',
        description: '',
        metadata_uri: '',
        manufacturer_address: '0x1234567890123456789012345678901234567890',
        registered_at: '2026-05-19T00:00:00Z',
      }),
      isPending: false,
      error: null,
    } as any)

    vi.mocked(useUpdateProduct).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
      error: null,
    } as any)
  })

  it('shows a clean registered status after blockchain registration succeeds', async () => {
    renderWithProviders(<Products />)

    fireEvent.click(screen.getByRole('button', { name: /add product/i }))
    fireEvent.change(
      screen.getByPlaceholderText('e.g., Organic Coffee Beans'),
      {
        target: { value: 'Coffee Beans' },
      },
    )
    fireEvent.change(screen.getByPlaceholderText('0x...'), {
      target: { value: '0x1234567890123456789012345678901234567890' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create Product' }))

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'Receipt received — awaiting indexing' }),
      ).toBeInTheDocument()
    })
  })
})
