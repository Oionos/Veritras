import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import { useKPIData, useAnomalies, useBottlenecks, exportAnalytics } from '@/hooks/useApi'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import { Download, AlertTriangle, TrendingUp, Clock, Route, AlertCircle } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import type { Anomaly, BottleneckLocation } from '@/types'

// TODO: Replace with real route/daily volume data from backend when available
const volumeData = [
  { route: 'NA-EU', volume: 420, delay: 2.1 },
  { route: 'AS-NA', volume: 380, delay: 3.2 },
  { route: 'EU-AS', volume: 290, delay: 1.8 },
  { route: 'NA-SA', volume: 240, delay: 1.5 },
  { route: 'EU-AF', volume: 180, delay: 4.2 },
  { route: 'AS-AU', volume: 150, delay: 2.8 },
]

const PIE_COLORS = ['#c8f060', '#60d0f0', '#f0a060', '#d060f0', '#888888', '#f06090', '#60f0a0']

export default function Analytics() {
  const { data: kpiData, isLoading: kpiLoading, error: kpiError } = useKPIData()
  const { data: anomaliesData, isLoading: anomaliesLoading } = useAnomalies()
  const { isLoading: bottlenecksLoading } = useBottlenecks()

  const isLoading = kpiLoading || anomaliesLoading || bottlenecksLoading
  const error = kpiError

  const anomalies: Anomaly[] = anomaliesData ?? []

  const bottleneckPieData: { name: string; value: number; color: string }[] =
    (kpiData?.bottleneck_locations ?? []).map((b: BottleneckLocation, i: number) => ({
      name: b.location,
      value: b.incident_count,
      color: PIE_COLORS[i % PIE_COLORS.length],
    }))

  const handleExport = async (format: 'csv' | 'pdf') => {
    try {
      await exportAnalytics(format)
      toast.success(`Exported ${format.toUpperCase()} successfully`)
    } catch {
      toast.error('Export failed. Please try again.')
    }
  }

  return (
    <div className="animate-fade-in space-y-6 px-6 sm:px-12 lg:px-20">
      {/* ─── Header ──────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 pt-28 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <div className="h-px w-8 bg-accent/40" />
            <span className="text-xs font-semibold uppercase tracking-[0.2em] text-accent/60">
              Insights
            </span>
          </div>
          <h1 className="font-serif text-3xl leading-[1.1] tracking-tight text-text sm:text-4xl">
            Analytics
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-muted">
            Deep insights into shipment performance, transit patterns, and anomaly detection.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => handleExport('csv')} className="gap-2">
            <Download className="h-4 w-4" />
            Export CSV
          </Button>
          <Button variant="secondary" onClick={() => handleExport('pdf')} className="gap-2">
            <Download className="h-4 w-4" />
            Export PDF
          </Button>
        </div>
      </div>

      {/* ─── Loading State ─────────────────────────────────────────── */}
      {isLoading && (
        <div
          aria-label="Loading"
          role="status"
          className="grid grid-cols-1 gap-4 lg:grid-cols-2"
        >
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-2xl"
            >
              <div className="mb-6 flex items-center justify-between">
                <div className="space-y-2">
                  <div className="h-5 w-32 animate-pulse rounded bg-white/[0.06]" />
                  <div className="h-3 w-48 animate-pulse rounded bg-white/[0.04]" />
                </div>
              </div>
              <div className="h-[300px] animate-pulse rounded-xl bg-white/[0.03]" />
            </div>
          ))}
        </div>
      )}

      {/* ─── Error State ───────────────────────────────────────────── */}
      {error && (
        <div className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-5 backdrop-blur-xl">
          <AlertCircle className="h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="font-medium text-red-400">Failed to load analytics data</p>
            <p className="text-sm text-red-400/70">
              {error instanceof Error ? error.message : 'Please try again later.'}
            </p>
          </div>
        </div>
      )}

      {!isLoading && !error && (
        <>
          {/* ─── Charts Grid ───────────────────────────────────────── */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Shipment Volume by Route */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0, ease: [0.23, 1, 0.32, 1] }}
            >
              <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-2xl transition-all duration-200 ease-out hover:border-white/[0.1]">
                <div className="mb-6 flex items-center justify-between">
                  <div>
                    <h2 className="font-semibold text-text">Volume by Route</h2>
                    <p className="text-sm text-muted/60">Shipment count per trade lane</p>
                  </div>
                  <Route className="h-5 w-5 text-muted/30" />
                </div>
                <div className="h-[300px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={volumeData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                      <XAxis dataKey="route" stroke="rgba(255,255,255,0.2)" fontSize={12} tickLine={false} axisLine={false} />
                      <YAxis stroke="rgba(255,255,255,0.2)" fontSize={12} tickLine={false} axisLine={false} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: 'rgba(10,10,10,0.9)',
                          border: '1px solid rgba(255,255,255,0.06)',
                          borderRadius: '12px',
                          fontSize: '12px',
                          backdropFilter: 'blur(20px)',
                        }}
                        itemStyle={{ color: '#f0ece4' }}
                      />
                      <Bar dataKey="volume" fill="#c8f060" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </motion.div>

            {/* Bottleneck Distribution */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1, ease: [0.23, 1, 0.32, 1] }}
            >
              <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-2xl transition-all duration-200 ease-out hover:border-white/[0.1]">
                <div className="mb-6 flex items-center justify-between">
                  <div>
                    <h2 className="font-semibold text-text">Bottleneck Locations</h2>
                    <p className="text-sm text-muted/60">Incident count by location</p>
                  </div>
                  <Clock className="h-5 w-5 text-muted/30" />
                </div>
                <div className="flex h-[300px] items-center">
                  {bottleneckPieData.length === 0 ? (
                    <p className="w-full text-center text-sm text-muted">No bottleneck data available.</p>
                  ) : (
                    <>
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie
                            data={bottleneckPieData}
                            cx="50%"
                            cy="50%"
                            innerRadius={60}
                            outerRadius={100}
                            paddingAngle={4}
                            dataKey="value"
                          >
                            {bottleneckPieData.map((entry, index) => (
                              <Cell key={`cell-${index}`} fill={entry.color} />
                            ))}
                          </Pie>
                          <Tooltip
                            contentStyle={{
                              backgroundColor: 'rgba(10,10,10,0.9)',
                              border: '1px solid rgba(255,255,255,0.06)',
                              borderRadius: '12px',
                              fontSize: '12px',
                              backdropFilter: 'blur(20px)',
                            }}
                            itemStyle={{ color: '#f0ece4' }}
                          />
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="space-y-2">
                        {bottleneckPieData.map((item) => (
                          <div key={item.name} className="flex items-center gap-2 text-xs">
                            <div className="h-3 w-3 rounded-full" style={{ backgroundColor: item.color }} />
                            <span className="text-muted">{item.name}</span>
                            <span className="font-mono text-text">{item.value}</span>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </motion.div>

            {/* Transit Time by Route */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2, ease: [0.23, 1, 0.32, 1] }}
            >
              <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-2xl transition-all duration-200 ease-out hover:border-white/[0.1]">
                <div className="mb-6 flex items-center justify-between">
                  <div>
                    <h2 className="font-semibold text-text">Transit Time by Route</h2>
                    <p className="text-sm text-muted/60">Average delay in days</p>
                  </div>
                  <TrendingUp className="h-5 w-5 text-muted/30" />
                </div>
                <div className="h-[300px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={volumeData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" horizontal={false} />
                      <XAxis type="number" stroke="rgba(255,255,255,0.2)" fontSize={12} tickLine={false} axisLine={false} />
                      <YAxis dataKey="route" type="category" stroke="rgba(255,255,255,0.2)" fontSize={12} tickLine={false} axisLine={false} width={60} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: 'rgba(10,10,10,0.9)',
                          border: '1px solid rgba(255,255,255,0.06)',
                          borderRadius: '12px',
                          fontSize: '12px',
                          backdropFilter: 'blur(20px)',
                        }}
                        itemStyle={{ color: '#f0ece4' }}
                        formatter={(value) => [`${value ?? 0} days`, 'Avg Delay']}
                      />
                      <Bar dataKey="delay" fill="#60d0f0" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </motion.div>

            {/* Anomaly Table */}
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 backdrop-blur-2xl">
              <div className="mb-6 flex items-center justify-between">
                <div>
                  <h2 className="font-semibold text-text">Flagged Shipments</h2>
                  <p className="text-sm text-muted/60">Detected anomalies requiring attention</p>
                </div>
                <AlertTriangle className="h-5 w-5 text-accent3" />
              </div>
              <div className="overflow-x-auto">
                {anomalies.length === 0 ? (
                  <p className="text-sm text-muted">No anomalies detected.</p>
                ) : (
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-white/[0.06] text-xs uppercase tracking-wider text-muted/60">
                        <th className="pb-3 font-medium">Product ID</th>
                        <th className="pb-3 font-medium">Severity</th>
                        <th className="pb-3 font-medium">Transit (hrs)</th>
                        <th className="pb-3 font-medium">Z-Score</th>
                        <th className="pb-3 font-medium">Flagged At</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/[0.04]">
                      {anomalies.map((item) => (
                        <tr key={`${item.product_id}-${item.flagged_at}`} className="transition-colors hover:bg-white/[0.02]">
                          <td className="py-3 font-mono text-text">{item.product_id}</td>
                          <td className="py-3">
                            <Badge
                              variant={
                                item.severity === 'high'
                                  ? 'error'
                                  : item.severity === 'medium'
                                  ? 'warning'
                                  : 'default'
                              }
                            >
                              {item.severity}
                            </Badge>
                          </td>
                          <td className="py-3 text-muted">{item.transit_time_hours.toFixed(1)}</td>
                          <td className="py-3 text-muted">{item.z_score.toFixed(2)}</td>
                          <td className="py-3 text-muted">
                            {new Date(item.flagged_at).toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
