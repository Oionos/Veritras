import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import Analytics from './Analytics'
import { useKPIData, useAnomalies, exportAnalytics } from '@/hooks/useApi'
import { renderWithProviders } from '@/test/test-utils'

vi.mock('@/hooks/useApi', () => ({
  useKPIData: vi.fn(),
  useAnomalies: vi.fn(),
  exportAnalytics: vi.fn(),
}))
const metrics = {
  total_shipments: 6,
  active_shipments: 2,
  delivered_shipments: 4,
  avg_transit_time_hours: 20,
  on_time_rate_percent: 50,
  transit_sample_size: 3,
  incomplete_transit_shipments: 3,
  sla_sample_size: 2,
  unknown_sla_deliveries: 1,
  active_elapsed_sample_size: 1,
  awaiting_departure_shipments: 1,
  avg_active_elapsed_hours: null,
  routes: [],
  bottleneck_locations: [],
}
describe('Analytics', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useKPIData).mockReturnValue({
      data: metrics,
      isLoading: false,
      error: null,
    } as any)
    vi.mocked(useAnomalies).mockReturnValue({
      data: [
        {
          product_id: 'PROD-001',
          transit_time_hours: 72,
          z_score: 2.5,
          severity: 'high',
          flagged_at: '2024-01-15T10:00:00Z',
          sample_size: 10,
        },
      ],
      isLoading: false,
      error: null,
    } as any)
  })
  it('renders real route charts and checkpoint interval labels', () => {
    renderWithProviders(<Analytics />)
    expect(screen.getByText('Volume by Route')).toBeInTheDocument()
    expect(screen.getByText('Checkpoint Intervals')).toBeInTheDocument()
    expect(screen.getByText('Transit Time by Route')).toBeInTheDocument()
    expect(
      screen.getByText('No completed transit samples available.')
    ).toBeInTheDocument()
    expect(screen.queryByText('NA-EU')).not.toBeInTheDocument()
  })
  it('renders anomalies with sample counts', () => {
    renderWithProviders(<Analytics />)
    expect(screen.getByText('PROD-001')).toBeInTheDocument()
    expect(screen.getByText('high')).toBeInTheDocument()
    expect(screen.getByText(/Z-score 2.50 · 10 samples/)).toBeInTheDocument()
  })
  it('shows controlled shipment and SLA sample counts', () => {
    renderWithProviders(<Analytics />)
    expect(screen.getByText(/Total shipments: 6/)).toHaveTextContent(
      'Delivered: 4'
    )
    expect(screen.getByText(/Completed transit: 3 samples/)).toHaveTextContent(
      'SLA: 2 samples'
    )
    expect(screen.getByText(/On-time rate: 50.0%/)).toBeInTheDocument()
    expect(screen.getByText(/Trend unavailable/)).toBeInTheDocument()
  })
  it('renders loading state', () => {
    vi.mocked(useKPIData).mockReturnValue({
      data: null,
      isLoading: true,
      error: null,
    } as any)
    renderWithProviders(<Analytics />)
    expect(screen.getByLabelText('Loading')).toBeInTheDocument()
  })
  it('applies the same UTC and route filters to queries and exports', async () => {
    renderWithProviders(<Analytics />)
    fireEvent.change(screen.getByLabelText('Start date (UTC)'), {
      target: { value: '2026-01-01' },
    })
    fireEvent.change(screen.getByLabelText('End date inclusive (UTC)'), {
      target: { value: '2026-01-01' },
    })
    fireEvent.change(screen.getByLabelText('Origin'), {
      target: { value: 'A' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }))
    const filters = {
      start_date: '2026-01-01',
      end_date: '2026-01-01',
      origin: 'A',
    }
    expect(useKPIData).toHaveBeenLastCalledWith(filters)
    expect(useAnomalies).toHaveBeenLastCalledWith(filters)
    for (const [name, format, report] of [
      ['Export CSV', 'csv', 'shipments'],
      ['Export Events CSV', 'csv', 'events'],
      ['Export PDF', 'pdf', 'shipments'],
    ] as const) {
      fireEvent.click(screen.getByRole('button', { name }))
      await waitFor(() =>
        expect(exportAnalytics).toHaveBeenLastCalledWith(
          format,
          undefined,
          undefined,
          filters,
          report
        )
      )
    }
  })
  it('rejects reversed dates and disables exports on API failure', () => {
    vi.mocked(useKPIData).mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('Offline'),
    } as any)
    renderWithProviders(<Analytics />)
    fireEvent.change(screen.getByLabelText('Start date (UTC)'), {
      target: { value: '2026-02-01' },
    })
    fireEvent.change(screen.getByLabelText('End date inclusive (UTC)'), {
      target: { value: '2026-01-01' },
    })
    expect(screen.getByRole('button', { name: 'Apply filters' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled()
    expect(
      screen.getByText('Failed to load analytics data')
    ).toBeInTheDocument()
  })
  it('shows zero baselines and unavailable anomaly data explicitly', () => {
    vi.mocked(useKPIData).mockReturnValue({
      data: {
        ...metrics,
        trend: {
          current_count: 6,
          previous_count: 0,
          percent_change: null,
          previous_start: '2025-12-31T00:00:00Z',
          previous_end_exclusive: '2026-01-01T00:00:00Z',
        },
      },
      isLoading: false,
      error: null,
    } as any)
    vi.mocked(useAnomalies).mockReturnValue({
      data: null,
      isLoading: false,
      error: new Error('Offline'),
    } as any)
    renderWithProviders(<Analytics />)
    expect(
      screen.getByText(/Unavailable \(zero baseline\)/)
    ).toBeInTheDocument()
    expect(
      screen.getByText('Anomaly analysis unavailable.')
    ).toBeInTheDocument()
  })
})
