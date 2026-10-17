vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ token: 'test-token', address: '0x1234567890123456789012345678901234567890', isAuthenticated: true, isLoggingIn: false, loginError: null, login: vi.fn(), logout: vi.fn() }),
  getAuthToken: () => null,
  clearAuthToken: vi.fn(),
}))

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, fireEvent, waitFor } from '@testing-library/react'
import Shipments from './Shipments'
import {
  useShipments,
  useCreateShipment,
  useUpdateShipment,
} from '@/hooks/useApi'
import { useAccount } from 'wagmi'
import {
  useRecordCheckpoint,
  useTransferCustody,
} from '@/hooks/useShipmentTracker'
import { renderWithProviders } from '@/test/test-utils'

vi.mock('wagmi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('wagmi')>()
  return {
    ...actual,
    useAccount: vi.fn(),
    useWriteContract: () => ({
      writeContract: vi.fn(),
      data: undefined,
      isPending: false,
      error: null,
    }),
    useWaitForTransactionReceipt: () => ({
      isLoading: false,
      isSuccess: false,
    }),
  }
})

vi.mock('@/hooks/useShipmentTracker', () => ({
  useShipmentPermissions: () => ({ canRecord: true, canTransfer: true }),
  useRecordCheckpoint: vi.fn(),
  useTransferCustody: vi.fn(),
  StatusLabels: {
    0: 'Created',
    1: 'In Transit',
    2: 'At Checkpoint',
    3: 'Delivered',
  },
  ShipmentStatus: {},
}))

vi.mock('@/hooks/useApi', () => ({
  useShipments: vi.fn(),
  useCreateShipment: vi.fn(),
  useUpdateShipment: vi.fn(),
}))

describe('Shipments on-chain header text', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    vi.mocked(useShipments).mockReturnValue({
      data: {
        items: [
          {
            id: 1,
            shipment_id: 'SHIP-001',
            product_id: 'PROD-001', owner_address: '0x1234567890123456789012345678901234567890', ownership_source: 'signed_draft', block_number: 0, tx_hash: '0x',
            origin: 'NYC',
            destination: 'LA',
            status: '1',
            created_at: '2026-05-19T00:00:00Z',
          },
        ],
        total: 1,
      },
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

    vi.mocked(useAccount).mockReturnValue({
      isConnected: false,
      address: undefined,
    } as any)
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
  })

  it('uses an ASCII separator in the selected shipment header', async () => {
    renderWithProviders(<Shipments />)

    fireEvent.click(
      screen.getByRole('button', { name: 'Track shipment SHIP-001' }),
    )

    await waitFor(() => {
      expect(screen.getByText(/On-Chain Actions -/)).toBeInTheDocument()
    })
  })
})
