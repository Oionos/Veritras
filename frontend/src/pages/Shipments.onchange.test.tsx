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

describe('Shipments form — on-change validation', () => {
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

  const openAddModal = () =>
    fireEvent.click(screen.getByRole('button', { name: /add shipment/i }))

  it('shows origin error immediately when a single character is typed — without submit', async () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('Origin location'), {
      target: { value: 'A' },
    })

    await waitFor(() => {
      expect(screen.getByText('Origin must be at least 2 characters')).toBeInTheDocument()
    })
  })

  it('shows destination error immediately when a single character is typed — without submit', async () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('Destination location'), {
      target: { value: 'A' },
    })

    await waitFor(() => {
      expect(screen.getByText('Destination must be at least 2 characters')).toBeInTheDocument()
    })
  })

  it('clears origin error as soon as a valid origin replaces the invalid one', async () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('Origin location'), {
      target: { value: 'A' },
    })
    await waitFor(() => {
      expect(screen.getByText('Origin must be at least 2 characters')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('Origin location'), {
      target: { value: 'Rotterdam' },
    })
    await waitFor(() => {
      expect(screen.queryByText('Origin must be at least 2 characters')).not.toBeInTheDocument()
    })
  })
})
