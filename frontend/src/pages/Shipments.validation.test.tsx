vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ token: 'test-token', address: '0x1234567890123456789012345678901234567890', isAuthenticated: true, isLoggingIn: false, loginError: null, login: vi.fn(), logout: vi.fn() }),
  getAuthToken: () => null,
  clearAuthToken: vi.fn(),
}))

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import Shipments from './Shipments'
import { useShipments, useCreateShipment, useUpdateShipment } from '@/hooks/useApi'
import { useAccount } from 'wagmi'
import { useRecordCheckpoint, useTransferCustody } from '@/hooks/useShipmentTracker'
import { renderWithProviders } from '@/test/test-utils'

// ── Mock overrides ────────────────────────────────────────────────────────────

vi.mock('wagmi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('wagmi')>()
  return {
    ...actual,
    useAccount: vi.fn(),
    useWriteContract: () => ({ writeContract: vi.fn(), data: undefined, isPending: false, error: null }),
    useWaitForTransactionReceipt: () => ({ isLoading: false, isSuccess: false }),
  }
})

vi.mock('@/hooks/useShipmentTracker', () => ({
  useShipmentPermissions: () => ({ canRecord: true, canTransfer: true }),
  useRecordCheckpoint: vi.fn(),
  useTransferCustody: vi.fn(),
  StatusLabels: { 0: 'Created', 1: 'In Transit', 2: 'At Checkpoint', 3: 'Delivered' },
  ShipmentStatus: {},
}))

vi.mock('@/hooks/useApi', () => ({
  useShipments: vi.fn(),
  useCreateShipment: vi.fn(),
  useUpdateShipment: vi.fn(),
}))

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Shipments form validation', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    vi.mocked(useAccount).mockReturnValue({ isConnected: false, address: undefined } as any)
    vi.mocked(useRecordCheckpoint).mockReturnValue({
      record: vi.fn(),
      isPending: false,
      isConfirming: false,
      isSuccess: false,
      error: null,
    } as any)
    vi.mocked(useTransferCustody).mockReturnValue({
      transfer: vi.fn(),
      isPending: false,
      isConfirming: false,
      isSuccess: false,
      error: null,
    } as any)
    vi.mocked(useShipments).mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      error: null,
    } as any)
    vi.mocked(useCreateShipment).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
      error: null,
    } as any)
    vi.mocked(useUpdateShipment).mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
      isPending: false,
      error: null,
    } as any)
  })

  // Open the Add Shipment modal before each interaction
  const openAddModal = () =>
    fireEvent.click(screen.getByRole('button', { name: /add shipment/i }))

  it('shows product_id required error when the form is submitted empty', async () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.click(screen.getByRole('button', { name: 'Create Shipment' }))

    await waitFor(() => {
      expect(screen.getByText('Product ID is required')).toBeInTheDocument()
    })
  })

  it('shows origin min-length error when origin is exactly 1 character', async () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), {
      target: { value: 'PROD-001' },
    })
    fireEvent.change(screen.getByPlaceholderText('Origin location'), {
      target: { value: 'A' },
    })
    fireEvent.change(screen.getByPlaceholderText('Destination location'), {
      target: { value: 'Shanghai' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Create Shipment' }))

    await waitFor(() => {
      expect(screen.getByText('Origin must be at least 2 characters')).toBeInTheDocument()
    })
  })

  it('shows destination min-length error when destination is exactly 1 character', async () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), {
      target: { value: 'PROD-001' },
    })
    fireEvent.change(screen.getByPlaceholderText('Origin location'), {
      target: { value: 'Rotterdam' },
    })
    fireEvent.change(screen.getByPlaceholderText('Destination location'), {
      target: { value: 'A' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Create Shipment' }))

    await waitFor(() => {
      expect(screen.getByText('Destination must be at least 2 characters')).toBeInTheDocument()
    })
  })

  it('shows notes max-length error when notes exceed 500 characters', async () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), {
      target: { value: 'PROD-001' },
    })
    fireEvent.change(screen.getByPlaceholderText('Origin location'), {
      target: { value: 'Rotterdam' },
    })
    fireEvent.change(screen.getByPlaceholderText('Destination location'), {
      target: { value: 'Shanghai' },
    })
    fireEvent.change(screen.getByPlaceholderText('Additional notes...'), {
      target: { value: 'N'.repeat(501) },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Create Shipment' }))

    await waitFor(() => {
      expect(screen.getByText('Notes must be at most 500 characters')).toBeInTheDocument()
    })
  })

  it('calls mutateAsync with form data when all required fields are valid (validation passes)', async () => {
    const mockMutateAsync = vi.fn().mockResolvedValue({})
    vi.mocked(useCreateShipment).mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
      error: null,
    } as any)

    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), {
      target: { value: 'PROD-001' },
    })
    fireEvent.change(screen.getByPlaceholderText('Origin location'), {
      target: { value: 'Rotterdam' },
    })
    fireEvent.change(screen.getByPlaceholderText('Destination location'), {
      target: { value: 'Shanghai' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Create Shipment' }))

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({
          product_id: 'PROD-001',
          origin: 'Rotterdam',
          destination: 'Shanghai',
        })
      )
    })
  })
})
