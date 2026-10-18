import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import Dashboard from './Dashboard'
import { useKPIData, useProducts, useDailyVolume } from '@/hooks/useApi'
import { renderWithProviders } from '@/test/test-utils'

vi.mock('@/hooks/useApi', () => ({
  useKPIData: vi.fn(),
  useProducts: vi.fn(),
  useDailyVolume: vi.fn(),
}))

vi.mock('@/hooks/useSSE', () => ({
  useAnalyticsEvents: vi.fn(),
}))

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useKPIData).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useProducts).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useDailyVolume).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any)
  })

  it('renders KPI cards with correct values', () => {
    vi.mocked(useKPIData).mockReturnValue({
      data: {
        total_shipments: 150,
        active_shipments: 42,
        avg_transit_time_hours: 24.5,
        on_time_rate_percent: 98.2,
      },
      isLoading: false,
      error: null,
    } as any)

    vi.mocked(useProducts).mockReturnValue({
      data: [
        {
          id: 1,
          product_id: 'PROD-001',
          name: 'Widget',
          registered_at: '2024-01-15T10:00:00Z',
        },
      ],
      isLoading: false,
      error: null,
    } as any)

    renderWithProviders(<Dashboard />)

    expect(screen.getByText('150')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('24.5 hrs')).toBeInTheDocument()
    expect(screen.getByText('98.2%')).toBeInTheDocument()
  })

  it('renders chart area', () => {
    renderWithProviders(<Dashboard />)

    expect(screen.getByText('Shipment Volume')).toBeInTheDocument()
    expect(screen.getByText('Volume data unavailable.')).toBeInTheDocument()
  })

  it('renders recorded data badge', () => {
    renderWithProviders(<Dashboard />)

    expect(screen.getByText('Recorded')).toBeInTheDocument()
  })

  it('renders loading state when KPI data is loading', () => {
    vi.mocked(useKPIData).mockReturnValue({
      data: null,
      isLoading: true,
      error: null,
    } as any)

    vi.mocked(useProducts).mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as any)

    renderWithProviders(<Dashboard />)

    expect(screen.getByLabelText('Loading')).toBeInTheDocument()
  })

  it('renders error state when fetch fails', () => {
    vi.mocked(useKPIData).mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('Network failure'),
    } as any)

    renderWithProviders(<Dashboard />)

    expect(
      screen.getByText('Failed to load dashboard data')
    ).toBeInTheDocument()
    expect(screen.getByText('Network failure')).toBeInTheDocument()
  })
  it('consumes paginated recent products and requests a recent sort', () => {
    vi.mocked(useProducts).mockReturnValue({
      data: {
        items: [
          {
            id: 1,
            product_id: 'PROD-RECENT',
            name: 'Recent widget',
            registration_status: 'draft',
            registered_at: null,
          },
        ],
        total: 60,
      },
      isLoading: false,
      error: null,
    } as any)
    renderWithProviders(<Dashboard />)
    expect(useProducts).toHaveBeenCalledWith(true)
    expect(screen.getByText('Recent widget')).toBeInTheDocument()
    expect(screen.queryByText('1,247')).not.toBeInTheDocument()
    expect(screen.queryByText('18%')).not.toBeInTheDocument()
  })
})
