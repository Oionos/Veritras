import { useState } from 'react'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import {
  useKPIData,
  useAnomalies,
  exportAnalytics,
  type AnalyticsFilterInput,
} from '@/hooks/useApi'
import { toast } from 'sonner'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { Anomaly } from '@/types'

const inputClass = 'rounded-lg border border-white/10 bg-black/20 p-2 text-text'
const panelClass = 'rounded-2xl border border-white/10 bg-white/[0.02] p-6'

export default function Analytics() {
  const [draft, setDraft] = useState<AnalyticsFilterInput>({})
  const [filters, setFilters] = useState<AnalyticsFilterInput>({})
  const { data, isLoading, error } = useKPIData(filters)
  const {
    data: anomaliesData,
    isLoading: anomaliesLoading,
    error: anomaliesError,
  } = useAnomalies(filters)
  const anomalies: Anomaly[] = anomaliesData ?? []
  const routes = (data?.routes ?? []).map((r) => ({
    ...r,
    route: `${r.origin} → ${r.destination}`,
  }))
  const completedRoutes = routes.filter((r) => r.avg_transit_time_hours != null)
  const invalidDates = Boolean(
    draft.start_date && draft.end_date && draft.start_date > draft.end_date
  )
  const handleExport = async (
    format: 'csv' | 'pdf',
    report: 'shipments' | 'events' = 'shipments'
  ) => {
    try {
      await exportAnalytics(format, undefined, undefined, filters, report)
      toast.success(`Exported ${format.toUpperCase()} successfully`)
    } catch {
      toast.error('Export failed. Please try again.')
    }
  }

  return (
    <div className="animate-fade-in space-y-6 px-6 pb-16 pt-28 sm:px-12 lg:px-20">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-serif text-4xl text-text">Analytics</h1>
          <p className="mt-2 text-sm text-muted">
            Shipment records and canonical indexed evidence. All dates and times
            are UTC.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            disabled={!data || !!error || isLoading}
            onClick={() => handleExport('csv')}
          >
            Export CSV
          </Button>
          <Button
            variant="secondary"
            disabled={!data || !!error || isLoading}
            onClick={() => handleExport('pdf')}
          >
            Export PDF
          </Button>
          <Button
            variant="secondary"
            disabled={!data || !!error || isLoading}
            onClick={() => handleExport('csv', 'events')}
          >
            Export Events CSV
          </Button>
        </div>
      </header>
      <form
        className={`${panelClass} flex flex-wrap items-end gap-4`}
        onSubmit={(e) => {
          e.preventDefault()
          if (!invalidDates) setFilters({ ...draft })
        }}
      >
        {(['start_date', 'end_date', 'origin', 'destination'] as const).map(
          (key) => (
            <label key={key} className="flex flex-col gap-1 text-sm text-muted">
              {
                {
                  start_date: 'Start date (UTC)',
                  end_date: 'End date inclusive (UTC)',
                  origin: 'Origin',
                  destination: 'Destination',
                }[key]
              }
              <input
                className={inputClass}
                type={key.includes('date') ? 'date' : 'text'}
                maxLength={200}
                value={draft[key] ?? ''}
                onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
              />
            </label>
          )
        )}
        <Button type="submit" disabled={invalidDates}>
          Apply filters
        </Button>
        <p className="w-full text-xs text-muted">
          Filters select shipments by creation date, including the entire end
          day: [start, next day). Routes match exactly after trimming and
          ignoring case. Charts and exports use the applied filters.
        </p>
        {invalidDates && (
          <p role="alert" className="text-red-400">
            Start date must be on or before end date.
          </p>
        )}
      </form>
      {isLoading && (
        <p role="status" aria-label="Loading">
          Loading analytics…
        </p>
      )}
      {error && (
        <div role="alert" className={panelClass}>
          <p>Failed to load analytics data</p>
          <p>{error.message}</p>
        </div>
      )}
      {!isLoading && !error && data && (
        <>
          <section className={panelClass} aria-label="Shipment sample counts">
            <p className="text-text">
              Total shipments: {data.total_shipments} · Active:{' '}
              {data.active_shipments} · Delivered: {data.delivered_shipments}
            </p>
            <p className="mt-2 text-sm text-muted">
              Completed transit: {data.transit_sample_size} samples · Incomplete
              transit: {data.incomplete_transit_shipments} · SLA:{' '}
              {data.sla_sample_size} samples · Unknown SLA deliveries:{' '}
              {data.unknown_sla_deliveries} · Late/unproven SLA deliveries: {data.late_sla_deliveries} · Incomplete SLA deliveries: {data.incomplete_sla_deliveries}
            </p>
            <p className="mt-2 text-sm text-muted">
              Average transit:{' '}
              {data.avg_transit_time_hours == null
                ? 'N/A'
                : `${data.avg_transit_time_hours.toFixed(1)} hours`}{' '}
              · On-time rate:{' '}
              {data.on_time_rate_percent == null
                ? 'N/A'
                : `${data.on_time_rate_percent.toFixed(1)}%`}
            </p>
            <p className="mt-2 text-sm text-muted">
              Active elapsed:{' '}
              {data.avg_active_elapsed_hours == null
                ? 'N/A'
                : `${data.avg_active_elapsed_hours.toFixed(1)} hours`}{' '}
              ({data.active_elapsed_sample_size} departed shipments) · Awaiting
              departure: {data.awaiting_departure_shipments}
            </p>
            <p className="mt-2 text-xs text-muted">
              Incomplete journeys and deliveries without a planned SLA are
              excluded from on-time performance. Active includes shipments
              awaiting departure. SLA is locked after indexed departure.
            </p>
            <p className="mt-2 text-xs text-muted">
              {data.trend
                ? `Previous equal period: ${data.trend.previous_start} to ${data.trend.previous_end_exclusive} exclusive. ${data.trend.current_count} versus ${data.trend.previous_count} shipments. Change: ${data.trend.percent_change == null ? 'Unavailable (zero baseline)' : `${data.trend.percent_change.toFixed(1)}%`}.`
                : 'Trend unavailable: select both dates to compare equal creation periods.'}
            </p>
            <p className="mt-2 break-words text-xs text-muted">
              As of {data.as_of} · Checkpoints: {data.checkpoint_count} ·
              Canonical events: {data.event_count}
            </p>
          </section>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className={panelClass}>
              <h2 className="font-semibold text-text">Volume by Route</h2>
              {routes.length ? (
                <div className="mt-4 h-[300px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={routes}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="route" />
                      <YAxis allowDecimals={false} />
                      <Tooltip />
                      <Bar
                        dataKey="total_shipments"
                        name="Shipment records"
                        fill="#c8f060"
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="mt-4 text-sm text-muted">
                  No shipments in this cohort.
                </p>
              )}
              <ul className="mt-4 text-sm text-muted">
                {routes.map((r) => (
                  <li key={r.route}>
                    {r.route}: {r.total_shipments} shipments ·{' '}
                    {r.transit_sample_size} completed transit samples ·{' '}
                    {r.sla_sample_size} SLA samples
                  </li>
                ))}
              </ul>
            </section>
            <section className={panelClass}>
              <h2 className="font-semibold text-text">Transit Time by Route</h2>
              <p className="text-xs text-muted">
                First indexed departure to indexed delivery, in hours.
              </p>
              {completedRoutes.length ? (
                <div className="mt-4 h-[300px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={completedRoutes}>
                      <XAxis dataKey="route" />
                      <YAxis />
                      <Tooltip />
                      <Bar
                        dataKey="avg_transit_time_hours"
                        name="Completed transit (hours)"
                        fill="#60d0f0"
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="mt-4 text-sm text-muted">
                  No completed transit samples available.
                </p>
              )}
            </section>
            <section className={panelClass}>
              <h2 className="font-semibold text-text">Checkpoint Intervals</h2>
              <p className="text-xs text-muted">
                Consecutive canonical checkpoints, grouped by the earlier
                location. Averages above 24 hours are shown. These intervals
                include travel and are not dwell time.
              </p>
              {(data.bottleneck_locations ?? []).length ? (
                <ul className="mt-4 space-y-2 text-sm text-muted">
                  {data.bottleneck_locations.map((b) => (
                    <li key={b.location}>
                      {b.location}: {b.avg_interval_hours.toFixed(1)} hours (
                      {b.incident_count} intervals)
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-sm text-muted">
                  No checkpoint intervals above the threshold.
                </p>
              )}
            </section>
            <section className={panelClass}>
              <h2 className="font-semibold text-text">Flagged Shipments</h2>
              <p className="text-xs text-muted">{data.anomaly_rule}</p>
              {anomaliesLoading ? (
                <p role="status">Loading anomaly analysis…</p>
              ) : anomaliesError ? (
                <p role="alert">Anomaly analysis unavailable.</p>
              ) : anomalies.length ? (
                <ul className="mt-4 space-y-4">
                  {anomalies.map((a) => (
                    <li key={a.product_id} className="text-sm text-muted">
                      <span>{a.product_id}</span>{' '}
                      <Badge
                        variant={a.severity === 'high' ? 'error' : 'warning'}
                      >
                        {a.severity}
                      </Badge>
                      <p>
                        {a.origin} → {a.destination} ·{' '}
                        {a.transit_time_hours.toFixed(1)} hours · Z-score{' '}
                        {a.z_score.toFixed(2)} · {a.sample_size} samples
                      </p>
                      <time>{a.flagged_at} UTC</time>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-sm text-muted">
                  No qualifying outliers. Routes with fewer than 10 completed
                  samples cannot support this analysis.
                </p>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
