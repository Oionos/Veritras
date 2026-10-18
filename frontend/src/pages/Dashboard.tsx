import { useState } from 'react'
import { motion } from 'framer-motion'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import PremiumHero from '@/components/PremiumHero'
import { useKPIData, useProducts, useDailyVolume } from '@/hooks/useApi'
import { formatDate } from '@/utils/formatters'
import {
  Package,
  Truck,
  Clock,
  TrendingUp,
  Activity,
  AlertCircle,
  ArrowUpRight,
  Shield,
} from 'lucide-react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import type { Product } from '@/types'

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
}

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.5,
      ease: [0.22, 1, 0.36, 1] as [number, number, number, number],
    },
  },
}

export default function Dashboard() {
  const [hoveredKpi, setHoveredKpi] = useState<number | null>(null)
  const { data: kpiData, isLoading: kpiLoading, error: kpiError } = useKPIData()
  const { data: productsData, isLoading: productsLoading } = useProducts(true)
  const {
    data: volumeData,
    isLoading: volumeLoading,
    error: volumeError,
  } = useDailyVolume()

  const chartData = volumeData?.items ?? []

  const isLoading = kpiLoading || productsLoading
  const error = kpiError

  const kpis = kpiData
    ? [
        {
          label: 'Total Shipments',
          value: kpiData.total_shipments?.toLocaleString() ?? '0',
          icon: Package,
          color: '#c8f060',
          gradient: 'from-accent/10 to-transparent',
        },
        {
          label: 'Active Shipments',
          value: kpiData.active_shipments?.toLocaleString() ?? '0',
          icon: Truck,
          color: '#60d0f0',
          gradient: 'from-accent2/10 to-transparent',
        },
        {
          label: 'Avg Transit Time',
          value:
            kpiData.avg_transit_time_hours != null
              ? `${kpiData.avg_transit_time_hours.toFixed(1)} hrs`
              : 'N/A',
          icon: Clock,
          color: '#f0a060',
          gradient: 'from-accent3/10 to-transparent',
        },
        {
          label: 'On-Time Rate',
          value:
            kpiData.on_time_rate_percent != null
              ? `${kpiData.on_time_rate_percent.toFixed(1)}%`
              : 'N/A',
          icon: TrendingUp,
          color: '#d060f0',
          gradient: 'from-accent4/10 to-transparent',
        },
      ]
    : []

  const recentProducts: Product[] = (
    productsData?.items ?? (Array.isArray(productsData) ? productsData : [])
  ).slice(0, 5)

  return (
    <div className="relative">
      {/* Hero */}
      <PremiumHero />

      {/* Dashboard Content */}
      <div
        data-testid="dashboard-overview"
        className="relative mx-auto max-w-7xl px-6 pb-20 pt-12 sm:px-12 sm:pt-14 lg:px-20 lg:pt-16"
      >
        {/* Section Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.6 }}
          className="mb-10"
        >
          <div className="flex items-center gap-3 mb-2">
            <span className="inline-block h-px w-6 bg-accent" />
            <span className="text-xs font-medium uppercase tracking-[0.25em] text-accent">
              Overview
            </span>
          </div>
          <div className="flex flex-1 items-end justify-between">
            <div>
              <h2 className="font-serif text-3xl tracking-tight text-text sm:text-4xl">
                Supply Chain
              </h2>
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted">
                Real-time visibility into your product journey from manufacturer
                to consumer.
              </p>
            </div>
            <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 backdrop-blur-xl sm:flex">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
              </span>
              <span className="text-xs font-medium text-muted">Recorded</span>
            </div>
          </div>
        </motion.div>

        {/* Loading State */}
        {isLoading && (
          <div className="flex items-center justify-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/10 p-4 backdrop-blur-sm"
          >
            <AlertCircle className="h-5 w-5 shrink-0 text-red-400" />
            <div>
              <p className="font-medium text-red-400">
                Failed to load dashboard data
              </p>
              <p className="text-sm text-red-400/70">
                {error instanceof Error
                  ? error.message
                  : 'Please try again later.'}
              </p>
            </div>
          </motion.div>
        )}

        {!isLoading && !error && (
          <>
            {/* Narrative Summary */}
            <motion.p
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5 }}
              className="mb-6 text-sm text-muted"
            >
              {kpiData?.total_shipments?.toLocaleString() ?? 'Unknown'} shipment
              records across all time (UTC). Transit uses{' '}
              {kpiData?.transit_sample_size ?? 0} completed journeys; on-time
              performance uses {kpiData?.sla_sample_size ?? 0} journeys with a
              planned SLA. Unknown SLA deliveries:{' '}
              {kpiData?.unknown_sla_deliveries ?? 0}. Active includes shipments
              awaiting departure. Trends are unavailable without two explicit
              comparable periods.
            </motion.p>

            {/* KPI Grid */}
            <motion.div
              variants={containerVariants}
              initial="hidden"
              whileInView="visible"
              viewport={{ once: true }}
              className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
            >
              {kpis.map((kpi, index) => (
                <motion.div
                  key={kpi.label}
                  variants={itemVariants}
                  onMouseEnter={() => setHoveredKpi(index)}
                  onMouseLeave={() => setHoveredKpi(null)}
                >
                  <div
                    className="group relative overflow-hidden rounded-3xl border border-white/5 bg-white/[0.02] p-6 backdrop-blur-2xl transition-all duration-500 hover:border-white/10 hover:bg-white/[0.04]"
                    style={{
                      boxShadow:
                        hoveredKpi === index
                          ? `0 0 40px ${kpi.color}15, 0 8px 32px rgba(0,0,0,0.3)`
                          : '0 4px 24px rgba(0,0,0,0.2)',
                    }}
                  >
                    {/* Gradient background on hover */}
                    <div
                      className={`absolute inset-0 bg-linear-to-br ${kpi.gradient} opacity-0 transition-opacity duration-500 group-hover:opacity-100`}
                    />

                    {/* Halo ring */}
                    <div
                      className="absolute -right-6 -top-6 h-16 w-16 rounded-full border opacity-0 transition-all duration-500 group-hover:opacity-100"
                      style={{ borderColor: `${kpi.color}20` }}
                    />

                    <div className="relative">
                      <div className="flex items-start justify-between">
                        <div className="space-y-2">
                          <p className="text-xs font-medium uppercase tracking-wider text-muted">
                            {kpi.label}
                          </p>
                          <p className="font-mono text-3xl font-medium text-text">
                            {kpi.value}
                          </p>
                        </div>
                        <div
                          className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/5 transition-all group-hover:scale-110"
                          style={{
                            boxShadow:
                              hoveredKpi === index
                                ? `0 0 20px ${kpi.color}20`
                                : 'none',
                          }}
                        >
                          <kpi.icon
                            className="h-4 w-4"
                            style={{ color: kpi.color }}
                          />
                        </div>
                      </div>

                      {/* Bottom accent line */}
                      <div
                        className="mt-4 h-px w-full bg-linear-to-r opacity-40"
                        style={{
                          backgroundImage: `linear-gradient(to right, ${kpi.color}30, transparent)`,
                        }}
                      />
                    </div>
                  </div>
                </motion.div>
              ))}
            </motion.div>

            {/* Chart + Recent Activity */}
            <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: 0.2 }}
                className="lg:col-span-2"
              >
                <div className="relative overflow-hidden rounded-3xl border border-white/5 bg-white/[0.02] p-6 backdrop-blur-2xl transition-all hover:border-white/10">
                  <div className="mb-6 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="inline-block h-px w-4 bg-accent" />
                      <div>
                        <h2 className="font-sans text-lg font-semibold text-text">
                          Shipment Volume
                        </h2>
                        <p className="text-xs text-muted">
                          Daily shipments and product registrations
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted">
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-accent shadow-[0_0_8px_rgba(200,240,96,0.4)]" />
                        Shipments
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-accent2 shadow-[0_0_8px_rgba(96,208,240,0.4)]" />
                        Products
                      </span>
                    </div>
                  </div>
                  <div className="h-[300px]">
                    {volumeLoading ? (
                      <div className="flex h-full items-center justify-center">
                        <LoadingSpinner size="sm" />
                      </div>
                    ) : volumeError || !volumeData ? (
                      <p className="text-sm text-muted">
                        Volume data unavailable.
                      </p>
                    ) : (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData}>
                          <defs>
                            <linearGradient
                              id="shipments"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="5%"
                                stopColor="#c8f060"
                                stopOpacity={0.15}
                              />
                              <stop
                                offset="95%"
                                stopColor="#c8f060"
                                stopOpacity={0}
                              />
                            </linearGradient>
                            <linearGradient
                              id="products"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="5%"
                                stopColor="#60d0f0"
                                stopOpacity={0.15}
                              />
                              <stop
                                offset="95%"
                                stopColor="#60d0f0"
                                stopOpacity={0}
                              />
                            </linearGradient>
                          </defs>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#ffffff08"
                            vertical={false}
                          />
                          <XAxis
                            dataKey="name"
                            stroke="#ffffff15"
                            fontSize={11}
                            tickLine={false}
                            axisLine={false}
                          />
                          <YAxis
                            stroke="#ffffff15"
                            fontSize={11}
                            tickLine={false}
                            axisLine={false}
                          />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: '#0a0a0a',
                              border: '1px solid #ffffff10',
                              borderRadius: '16px',
                              fontSize: '12px',
                              backdropFilter: 'blur(20px)',
                              boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                            }}
                            itemStyle={{ color: '#f0ece4' }}
                          />
                          <Area
                            type="monotone"
                            dataKey="shipments"
                            stroke="#c8f060"
                            strokeWidth={2}
                            fill="url(#shipments)"
                          />
                          <Area
                            type="monotone"
                            dataKey="products"
                            stroke="#60d0f0"
                            strokeWidth={2}
                            fill="url(#products)"
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    )}
                  </div>
                </div>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: 0.3 }}
              >
                <div className="relative h-full overflow-hidden rounded-3xl border border-white/5 bg-white/[0.02] p-6 backdrop-blur-2xl transition-all hover:border-white/10">
                  <div className="mb-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="inline-block h-px w-4 bg-accent2" />
                      <h2 className="font-sans text-lg font-semibold text-text">
                        Recent Products
                      </h2>
                    </div>
                    <Activity className="h-4 w-4 text-muted" />
                  </div>
                  <div className="space-y-2">
                    {recentProducts.length === 0 && (
                      <div className="flex flex-col items-center justify-center py-8 text-center">
                        <Shield className="mb-3 h-8 w-8 text-muted/30" />
                        <p className="text-sm text-muted">
                          No products registered yet.
                        </p>
                      </div>
                    )}
                    {recentProducts.map((item, i) => (
                      <motion.div
                        key={item.id}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.05 }}
                        className="group flex items-start gap-3 rounded-2xl p-3 transition-all hover:bg-white/5"
                      >
                        <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-accent shadow-[0_0_8px_rgba(200,240,96,0.4)]" />
                        <div className="min-w-0 flex-1 space-y-0.5">
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-sm font-medium text-text">
                              {item.product_id}
                            </span>
                            <ArrowUpRight className="h-3 w-3 text-muted opacity-0 transition-all group-hover:opacity-100 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                          </div>
                          <p className="text-xs text-muted truncate">
                            {item.name}
                          </p>
                          <p className="text-xs text-muted/40">
                            {item.registered_at
                              ? formatDate(item.registered_at)
                              : 'Not registered'}
                          </p>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                </div>
              </motion.div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
