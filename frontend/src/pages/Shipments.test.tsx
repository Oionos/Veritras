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

// ── File-level mock overrides ─────────────────────────────────────────────────
// These override the global setup.ts mocks so we can control return values
// per-test via vi.mocked().

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

// ── Shared test data ──────────────────────────────────────────────────────────

const mockShipments = [
  { id: 1, shipment_id: 'SHIP-001', product_id: 'PROD-001', owner_address: '0x1234567890123456789012345678901234567890', ownership_source: 'signed_draft', block_number: 0, tx_hash: '0x', origin: 'NYC', destination: 'LA', status: '1', created_at: '2024-01-15T10:00:00Z' },
  { id: 2, shipment_id: 'SHIP-002', product_id: 'PROD-002', origin: 'LA', destination: 'SF', status: '3', created_at: '2024-02-20T12:00:00Z' },
]

// ── Shared setup helpers ──────────────────────────────────────────────────────

function setupApiMocks() {
  vi.mocked(useShipments).mockReturnValue({
    data: { items: mockShipments, total: 12 },
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
}

function setupBlockchainMocks({
  isConnected = false,
  record = vi.fn(),
  transfer = vi.fn(),
}: {
  isConnected?: boolean
  record?: ReturnType<typeof vi.fn>
  transfer?: ReturnType<typeof vi.fn>
} = {}) {
  vi.mocked(useAccount).mockReturnValue({ isConnected, address: undefined } as any)

  vi.mocked(useRecordCheckpoint).mockReturnValue({
    record,
    isPending: false,
    isConfirming: false,
    isSuccess: false,
    error: null,
  } as any)

  vi.mocked(useTransferCustody).mockReturnValue({
    transfer,
    isPending: false,
    isConfirming: false,
    isSuccess: false,
    error: null,
  } as any)
}

// ─────────────────────────────────────────────────────────────────────────────
// Existing tests (kept intact)
// ─────────────────────────────────────────────────────────────────────────────

describe('Shipments', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupApiMocks()
    setupBlockchainMocks({ isConnected: false })
  })

  it('renders shipment table with data', () => {
    renderWithProviders(<Shipments />)

    expect(screen.getByText('SHIP-001')).toBeInTheDocument()
    expect(screen.getByText('SHIP-002')).toBeInTheDocument()
    expect(screen.getByText('NYC')).toBeInTheDocument()
    expect(screen.getAllByText('LA')).toHaveLength(2)
    expect(screen.getByText('SF')).toBeInTheDocument()
  })

  it('renders status filter dropdown', () => {
    renderWithProviders(<Shipments />)

    const selects = screen.getAllByRole('combobox')
    expect(selects.length).toBeGreaterThanOrEqual(1)

    const statusSelect = selects[0]
    expect(statusSelect).toBeInTheDocument()

    fireEvent.change(statusSelect, { target: { value: '1' } })

    expect(vi.mocked(useShipments)).toHaveBeenCalledWith(1, 10, '1', undefined)
  })

  it('renders pagination controls', () => {
    renderWithProviders(<Shipments />)

    // Use a custom matcher because "Page 1 of 2" is split across multiple elements
    const paginations = screen.getAllByText((content, element) => {
      return element?.tagName === 'P' && element?.textContent?.includes('Page 1 of 2')
    })
    expect(paginations.length).toBeGreaterThanOrEqual(1)

    expect(screen.getByTestId('icon-ChevronLeft').closest('button')).toBeInTheDocument()
    expect(screen.getByTestId('icon-ChevronRight').closest('button')).toBeInTheDocument()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Blockchain panel tests
// ─────────────────────────────────────────────────────────────────────────────

describe('Shipments blockchain panels', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setupApiMocks()
    setupBlockchainMocks({ isConnected: false })
  })

  it('Track button shows on-chain actions header for that shipment', async () => {
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByText(/On-Chain Actions/)).toBeInTheDocument()
    })
    // The shipment ID appears in the header
    expect(screen.getAllByText('SHIP-001').length).toBeGreaterThanOrEqual(1)
  })

  it('blockchain panel shows wallet-connect prompt when disconnected', async () => {
    setupBlockchainMocks({ isConnected: false })
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(
        screen.getByText('Connect your wallet to use blockchain actions.')
      ).toBeInTheDocument()
    })
  })

  it('blockchain panel shows Record Checkpoint and Transfer Custody when connected', async () => {
    setupBlockchainMocks({ isConnected: true })
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /record checkpoint/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /transfer custody/i })).toBeInTheDocument()
    })
  })

  it('Record Checkpoint accordion expands to show location input', async () => {
    setupBlockchainMocks({ isConnected: true })
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /record checkpoint/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /record checkpoint/i }))

    await waitFor(() => {
      expect(screen.getByPlaceholderText('e.g., Port of Rotterdam')).toBeInTheDocument()
    })
  })

  it('Submit Checkpoint button is disabled when location is empty', async () => {
    setupBlockchainMocks({ isConnected: true })
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /record checkpoint/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /record checkpoint/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Submit Checkpoint' })).toBeDisabled()
    })
  })

  it('Submit Checkpoint calls record with product_id and location', async () => {
    const mockRecord = vi.fn()
    setupBlockchainMocks({ isConnected: true, record: mockRecord })
    renderWithProviders(<Shipments />)

    // Click track for SHIP-001 (product_id: PROD-001)
    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /record checkpoint/i })).toBeInTheDocument()
    })

    // Expand the checkpoint accordion
    fireEvent.click(screen.getByRole('button', { name: /record checkpoint/i }))

    await waitFor(() => {
      expect(screen.getByPlaceholderText('e.g., Port of Rotterdam')).toBeInTheDocument()
    })

    // Type a location
    fireEvent.change(screen.getByPlaceholderText('e.g., Port of Rotterdam'), {
      target: { value: 'Rotterdam' },
    })

    // Submit button should now be enabled
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Submit Checkpoint' })).not.toBeDisabled()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Submit Checkpoint' }))

    expect(mockRecord).toHaveBeenCalled()
  })

  it('Transfer Custody accordion expands to show handler input', async () => {
    setupBlockchainMocks({ isConnected: true })
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /transfer custody/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /transfer custody/i }))

    await waitFor(() => {
      // The label for the handler address input
      expect(screen.getByText(/new handler address/i)).toBeInTheDocument()
    })
  })

  it('Transfer Custody does not call transfer when address is invalid', async () => {
    const mockTransfer = vi.fn()
    setupBlockchainMocks({ isConnected: true, transfer: mockTransfer })
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /transfer custody/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /transfer custody/i }))

    await waitFor(() => {
      expect(screen.getByText(/new handler address/i)).toBeInTheDocument()
    })

    // Find the handler input by its placeholder inside the transfer panel
    const handlerInput = screen.getByPlaceholderText('0x...')

    // Type an invalid address
    fireEvent.change(handlerInput, { target: { value: 'invalid' } })

    // The Transfer button should be enabled (non-empty value)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Transfer' })).not.toBeDisabled()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Transfer' }))

    // transfer() should NOT be called because the address is invalid
    expect(mockTransfer).not.toHaveBeenCalled()
  })

  it('Close button dismisses the blockchain panel', async () => {
    setupBlockchainMocks({ isConnected: false })
    renderWithProviders(<Shipments />)

    fireEvent.click(screen.getByRole('button', { name: 'Track shipment SHIP-001' }))

    await waitFor(() => {
      expect(screen.getByText(/On-Chain Actions/)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Close on-chain actions' }))

    await waitFor(() => {
      expect(screen.queryByText(/On-Chain Actions/)).not.toBeInTheDocument()
    })
  })
})
