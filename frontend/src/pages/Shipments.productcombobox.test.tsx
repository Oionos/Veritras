import { appEnvironment } from '@/config/runtime'
import { toProductBytes32 } from '@/utils/productId'
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
import type { Product } from '@/types'

// ── Mutable mock state for useProductList ─────────────────────────────────────

const mockProductListReturn: {
  data: { items: Product[]; total: number } | undefined
  isLoading: boolean
  error: Error | null
} = { data: undefined, isLoading: false, error: null }

vi.mock('@/hooks/useProductList', () => ({
  useProductList: () => mockProductListReturn,
}))

// ── Mock overrides (same pattern as Shipments.validation.test.tsx) ────────────

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

// ── Sample data ───────────────────────────────────────────────────────────────

const PRODUCTS: Product[] = [
  {
    id: 1,
    product_id: 'PROD-001', on_chain_product_id: toProductBytes32('PROD-001'), chain_id: appEnvironment.chainId, registry_address: appEnvironment.productRegistry, tracker_address: appEnvironment.shipmentTracker, owner_address: '0x1234567890123456789012345678901234567890', ownership_source: 'signed_draft', block_number: 0, tx_hash: '0x',
    name: 'Alpha Widget',
    manufacturer_address: '0xabc',
    registered_at: '',
  },
]

const MOCK_SHIPMENT = {
  id: 1,
  shipment_id: 'SHIP-001',
  product_id: 'PROD-001', on_chain_product_id: toProductBytes32('PROD-001'), chain_id: appEnvironment.chainId, registry_address: appEnvironment.productRegistry, tracker_address: appEnvironment.shipmentTracker, owner_address: '0x1234567890123456789012345678901234567890', ownership_source: 'signed_draft', block_number: 0, tx_hash: '0x',
  origin: 'Rotterdam',
  destination: 'Shanghai',
  status: '1',
  created_at: '2024-01-15T10:00:00Z',
  notes: '',
}

// ── Shared setup ──────────────────────────────────────────────────────────────

describe('Shipments page — ProductCombobox integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Reset mutable product list mock
    mockProductListReturn.data = undefined
    mockProductListReturn.isLoading = false
    mockProductListReturn.error = null

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

  // ── Test 1: Combobox renders in the form ────────────────────────────────────

  it('renders the product_id combobox input when the Add Shipment modal is open', () => {
    renderWithProviders(<Shipments />)
    openAddModal()

    expect(screen.getByPlaceholderText('e.g., PROD-8842')).toBeInTheDocument()
  })

  // ── Test 2: Suggestions appear on typing when products are available ─────────

  it('shows product suggestions when user types a matching query', async () => {
    mockProductListReturn.data = { items: PRODUCTS, total: PRODUCTS.length }

    renderWithProviders(<Shipments />)
    openAddModal()

    fireEvent.change(screen.getByPlaceholderText('e.g., PROD-8842'), {
      target: { value: 'PROD' },
    })

    await waitFor(() => {
      expect(screen.getByText('PROD-001')).toBeInTheDocument()
    })
  })

  // ── Test 3: Clicking a suggestion sets the field value ──────────────────────

  it('sets the combobox input value to the selected product_id when a suggestion is clicked', async () => {
    mockProductListReturn.data = { items: PRODUCTS, total: PRODUCTS.length }

    renderWithProviders(<Shipments />)
    openAddModal()

    const input = screen.getByPlaceholderText('e.g., PROD-8842')
    fireEvent.change(input, { target: { value: 'PROD' } })

    await waitFor(() => {
      expect(screen.getByText('PROD-001')).toBeInTheDocument()
    })

    fireEvent.mouseDown(screen.getByText('PROD-001'))
    fireEvent.click(screen.getByText('PROD-001'))

    expect(screen.getByPlaceholderText('e.g., PROD-8842')).toHaveValue('PROD-001')
  })

  // ── Test 4: Combobox is disabled in edit mode ───────────────────────────────

  it('disables the product_id combobox when editing an existing shipment', () => {
    vi.mocked(useShipments).mockReturnValue({
      data: { items: [MOCK_SHIPMENT], total: 1 },
      isLoading: false,
      error: null,
    } as any)

    renderWithProviders(<Shipments />)

    fireEvent.click(
      screen.getByRole('button', { name: `Edit shipment ${MOCK_SHIPMENT.shipment_id}` })
    )

    expect(screen.getByPlaceholderText('e.g., PROD-8842')).toBeDisabled()
  })
})
