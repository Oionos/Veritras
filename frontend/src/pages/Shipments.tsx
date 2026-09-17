import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { toHex, pad } from 'viem'
import { useAccount } from 'wagmi'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Modal from '@/components/ui/Modal'
import { useShipments, useCreateShipment, useUpdateShipment } from '@/hooks/useApi'
import { useForm, Controller } from 'react-hook-form'
import { ProductCombobox } from '@/components/ui/ProductCombobox'
import { zodResolver } from '@hookform/resolvers/zod'
import { ShipmentSchema, type ShipmentFormData } from '@/schemas'
import {
  useRecordCheckpoint,
  useTransferCustody,
  ShipmentStatus,
  StatusLabels,
} from '@/hooks/useShipmentTracker'
import {
  Truck,
  Plus,
  Pencil,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  Package,
  Search,
  Activity,
  X,
  MapPin,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Loader2,
  Link as LinkIcon,
} from 'lucide-react'
import { formatDate } from '@/utils/formatters'
import type { Shipment } from '@/types'

const statusLabels: Record<string, string> = {
  '0': 'Created',
  '1': 'In Transit',
  '2': 'At Checkpoint',
  '3': 'Delivered',
}

const statusVariant: Record<string, 'default' | 'blue' | 'orange' | 'success'> = {
  '0': 'default',
  '1': 'blue',
  '2': 'orange',
  '3': 'success',
}

const statusOptions = [
  { value: 'all', label: 'All Statuses' },
  { value: '0', label: 'Created' },
  { value: '1', label: 'In Transit' },
  { value: '2', label: 'At Checkpoint' },
  { value: '3', label: 'Delivered' },
]

const DEFAULT_LIMIT = 10

// ─── Helpers ────────────────────────────────────────────────────────────────

function toBytes32(productId: string): `0x${string}` {
  const hex = toHex(productId)
  if (hex.length > 66) {
    throw new Error(`product_id "${productId}" exceeds 32 bytes and cannot fit in bytes32`)
  }
  return pad(hex, { size: 32, dir: 'right' }) as `0x${string}`
}

function isValidEthAddress(value: string): boolean {
  return /^0x[0-9a-fA-F]{40}$/.test(value)
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function Shipments() {
  const { isConnected } = useAccount()

  // ── Pagination / table state ──────────────────────────────────────────────
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(DEFAULT_LIMIT)
  const [statusFilter, setStatusFilter] = useState('all')
  const [serverSearch, setServerSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  // ── Modal state ───────────────────────────────────────────────────────────
  const [modalOpen, setModalOpen] = useState(false)
  const [editingShipment, setEditingShipment] = useState<Shipment | null>(null)

  // ── Selected shipment for on-chain actions ────────────────────────────────
  const [selectedShipment, setSelectedShipment] = useState<Shipment | null>(null)

  // ── Blockchain action panel state ─────────────────────────────────────────
  const [showCheckpointForm, setShowCheckpointForm] = useState(false)
  const [showTransferForm, setShowTransferForm] = useState(false)

  // Checkpoint form fields
  const [cpLocation, setCpLocation] = useState('')
  const [cpStatus, setCpStatus] = useState<ShipmentStatus>(0)
  const [cpNotes, setCpNotes] = useState('')

  // Transfer form fields
  const [txHandler, setTxHandler] = useState('')
  const [txHandlerError, setTxHandlerError] = useState('')

  // ── Blockchain hooks ──────────────────────────────────────────────────────
  const {
    record,
    isPending: cpPending,
    isConfirming: cpConfirming,
    isSuccess: cpSuccess,
    error: cpError,
  } = useRecordCheckpoint()

  const {
    transfer,
    isPending: txPending,
    isConfirming: txConfirming,
    isSuccess: txSuccess,
    error: txError,
  } = useTransferCustody()

  // ── Debounce search ───────────────────────────────────────────────────────
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(serverSearch), 300)
    return () => clearTimeout(timer)
  }, [serverSearch])

  // ── Reset checkpoint form after success ───────────────────────────────────
  useEffect(() => {
    if (cpSuccess) {
      setCpLocation('')
      setCpStatus(0)
      setCpNotes('')
      setShowCheckpointForm(false)
    }
  }, [cpSuccess])

  // ── Reset transfer custody form after success ─────────────────────────────
  useEffect(() => {
    if (txSuccess) {
      setTxHandler('')
      setTxHandlerError('')
      setShowTransferForm(false)
    }
  }, [txSuccess])

  // ── API queries ───────────────────────────────────────────────────────────
  const {
    data,
    isLoading,
    error,
  } = useShipments(page, limit, statusFilter, debouncedSearch || undefined)

  const createShipment = useCreateShipment()
  const updateShipment = useUpdateShipment()

  const shipments: Shipment[] = Array.isArray(data) ? data : data?.items ?? []
  const total = Array.isArray(data) ? data.length : data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / limit))

  // ── Form ──────────────────────────────────────────────────────────────────
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
    control,
  } = useForm<ShipmentFormData>({
    resolver: zodResolver(ShipmentSchema),
    mode: 'onChange',
    defaultValues: {
      product_id: '',
      origin: '',
      destination: '',
      notes: '',
    },
  })

  // ── Handlers ──────────────────────────────────────────────────────────────
  const openAddModal = () => {
    setEditingShipment(null)
    reset({ product_id: '', origin: '', destination: '', notes: '' })
    setModalOpen(true)
  }

  const openEditModal = (shipment: Shipment) => {
    setEditingShipment(shipment)
    reset({
      product_id: shipment.product_id,
      origin: shipment.origin,
      destination: shipment.destination,
      notes: shipment.notes ?? '',
    })
    setModalOpen(true)
  }

  const handleTrackShipment = useCallback((shipment: Shipment) => {
    setSelectedShipment(shipment)
    setShowCheckpointForm(false)
    setShowTransferForm(false)
    setCpLocation('')
    setCpStatus(0)
    setCpNotes('')
    setTxHandler('')
    setTxHandlerError('')
  }, [])

  const handleClearSelected = useCallback(() => {
    setSelectedShipment(null)
    setShowCheckpointForm(false)
    setShowTransferForm(false)
    setCpLocation('')
    setCpStatus(0)
    setCpNotes('')
    setTxHandler('')
    setTxHandlerError('')
  }, [])

  const handleSubmitCheckpoint = () => {
    if (!cpLocation.trim() || !selectedShipment) return
    record(toBytes32(selectedShipment.product_id), cpLocation.trim(), cpStatus, cpNotes.trim())
  }

  const handleTransferCustody = () => {
    if (!isValidEthAddress(txHandler) || !selectedShipment) return
    transfer(toBytes32(selectedShipment.product_id), txHandler as `0x${string}`)
  }

  const onSubmit = async (formData: ShipmentFormData) => {
    try {
      if (editingShipment) {
        const { product_id, ...updateData } = formData
        await updateShipment.mutateAsync({
          shipment_id: editingShipment.shipment_id,
          data: updateData,
        })
      } else {
        await createShipment.mutateAsync(formData)
      }
      setModalOpen(false)
      reset()
      setEditingShipment(null)
    } catch {
      // Error handled by mutation state
    }
  }

  const isMutating = createShipment.isPending || updateShipment.isPending
  const mutationError = createShipment.error || updateShipment.error

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="animate-fade-in space-y-6 px-6 sm:px-12 lg:px-20">
      {/* ─── Header ──────────────────────────────────────────────── */}
      <div className="flex flex-col gap-4 pt-28 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <div className="h-px w-8 bg-accent/40" />
            <span className="text-xs font-semibold uppercase tracking-[0.2em] text-accent/60">
              Supply Chain
            </span>
          </div>
          <h1 className="font-serif text-3xl leading-[1.1] tracking-tight text-text sm:text-4xl">
            Shipments
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-muted">
            Manage and track product shipments across the supply chain.
          </p>
        </div>
        <Button onClick={openAddModal} className="gap-2">
          <Plus className="h-4 w-4" />
          Add Shipment
        </Button>
      </div>

      {/* ─── Filters ─────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-5 backdrop-blur-2xl">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/40" />
            <input
              type="text"
              placeholder="Search by origin or destination..."
              value={serverSearch}
              onChange={(e) => {
                setServerSearch(e.target.value)
                setPage(1)
              }}
              className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 pl-10 pr-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
            />
          </div>
          <div className="flex items-center gap-2">
            <Truck className="h-4 w-4 text-muted/40" />
            <span className="text-sm text-muted">Status</span>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value)
                setPage(1)
              }}
              className="rounded-xl border border-white/[0.06] bg-bg py-2.5 pl-3 pr-8 text-sm text-text outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
            >
              {statusOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted">Show</span>
            <select
              value={limit}
              onChange={(e) => {
                setLimit(Number(e.target.value))
                setPage(1)
              }}
              className="rounded-xl border border-white/[0.06] bg-bg py-2.5 pl-3 pr-8 text-sm text-text outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </div>
        </div>
      </div>

      {/* ─── Error ─────────────────────────────────────────────────── */}
      {error && (
        <div className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-5 backdrop-blur-xl">
          <AlertCircle className="h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="font-medium text-red-400">Failed to load shipments</p>
            <p className="text-sm text-red-400/70">
              {error instanceof Error ? error.message : 'Please try again later.'}
            </p>
          </div>
        </div>
      )}

      {/* ─── Table ─────────────────────────────────────────────────── */}
      <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.02] backdrop-blur-2xl">
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        ) : shipments.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="rounded-2xl bg-white/[0.02] p-4 mb-4">
              <Package className="h-10 w-10 text-muted/30" />
            </div>
            <p className="text-sm font-medium text-text">No shipments found</p>
            <p className="mt-1 text-xs text-muted">
              {statusFilter !== 'all'
                ? 'Try changing the status filter or search terms'
                : 'Create your first shipment to start tracking'}
            </p>
            {statusFilter === 'all' && (
              <Button onClick={openAddModal} className="mt-4 gap-2">
                <Plus className="h-4 w-4" />
                Add Your First Shipment
              </Button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Shipment ID</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Product ID</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Origin</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Destination</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Status</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Created</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {shipments.map((shipment) => (
                  <tr
                    key={shipment.id}
                    className="transition-colors duration-150 ease-out hover:bg-white/[0.03]"
                  >
                    <td className="px-6 py-4 font-mono text-text">
                      {shipment.shipment_id}
                    </td>
                    <td className="px-6 py-4 font-mono text-muted">
                      {shipment.product_id}
                    </td>
                    <td className="px-6 py-4 text-text">{shipment.origin}</td>
                    <td className="px-6 py-4 text-text">{shipment.destination}</td>
                    <td className="px-6 py-4">
                      <Badge variant={statusVariant[shipment.status] || 'default'}>
                        {statusLabels[shipment.status] || shipment.status}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 text-muted">
                      {formatDate(shipment.created_at)}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleTrackShipment(shipment)}
                          className={`rounded-lg p-2 transition-colors hover:bg-white/[0.04] hover:text-text ${
                            selectedShipment?.id === shipment.id
                              ? 'text-accent'
                              : 'text-muted/40'
                          }`}
                          aria-label={`Track shipment ${shipment.shipment_id}`}
                        >
                          <Activity className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => openEditModal(shipment)}
                          className="rounded-lg p-2 text-muted/40 transition-colors hover:bg-white/[0.04] hover:text-text"
                          aria-label={`Edit shipment ${shipment.shipment_id}`}
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {!isLoading && shipments.length > 0 && (
          <div className="flex items-center justify-between border-t border-white/[0.06] px-6 py-4">
            <p className="text-sm text-muted">
              Page <span className="text-text">{page}</span> of{' '}
              <span className="text-text">{totalPages}</span>{' '}
              <span className="text-muted/50">({total} total)</span>
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || isLoading}
                className="px-3"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="secondary"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || isLoading}
                className="px-3"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* ─── Blockchain Action Panel ────────────────────────────────── */}
      {selectedShipment !== null && (
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.23, 1, 0.32, 1] }}
          className="space-y-3"
        >
          {/* Header */}
          <div className="flex items-center justify-between rounded-2xl border border-white/[0.06] bg-white/[0.02] px-5 py-4 backdrop-blur-2xl">
            <div className="flex items-center gap-3">
              <Activity className="h-4 w-4 text-accent" />
              <span className="text-sm font-medium text-text">
                On-Chain Actions -{' '}
                <span className="font-mono">{selectedShipment.shipment_id}</span>
              </span>
            </div>
            <button
              onClick={handleClearSelected}
              className="rounded-lg p-1.5 text-muted/40 transition-all duration-150 ease-out hover:bg-white/[0.04] hover:text-text active:scale-90"
              aria-label="Close on-chain actions"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Wallet guard */}
          {!isConnected ? (
            <div className="flex items-center gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.02] px-5 py-4 text-sm text-muted backdrop-blur-2xl">
              <LinkIcon className="h-4 w-4 shrink-0 text-muted/40" />
              Connect your wallet to use blockchain actions.
            </div>
          ) : (
            <div className="space-y-3">
              {/* Record Checkpoint */}
              <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.02] backdrop-blur-2xl">
                <button
                  onClick={() => setShowCheckpointForm((v) => !v)}
                  className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-white/[0.02]"
                >
                  <div className="flex items-center gap-3">
                    <MapPin className="h-4 w-4 text-accent" />
                    <span className="text-sm font-medium text-text">Record Checkpoint</span>
                  </div>
                  {showCheckpointForm ? (
                    <ChevronUp className="h-4 w-4 text-muted/60" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted/60" />
                  )}
                </button>

                {showCheckpointForm && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="border-t border-white/[0.06] px-5 pb-5 pt-4 space-y-4">
                    {/* Location */}
                    <div>
                      <label className="mb-1 block text-sm font-medium text-text">
                        Location <span className="text-red-400">*</span>
                      </label>
                      <input
                        type="text"
                        value={cpLocation}
                        onChange={(e) => setCpLocation(e.target.value)}
                        placeholder="e.g., Port of Rotterdam"
                        disabled={cpPending || cpConfirming}
                        className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10 disabled:opacity-50"
                      />
                    </div>

                    {/* Status */}
                    <div>
                      <label className="mb-1 block text-sm font-medium text-text">
                        Status
                      </label>
                      <select
                        value={cpStatus}
                        onChange={(e) => setCpStatus(Number(e.target.value) as ShipmentStatus)}
                        disabled={cpPending || cpConfirming}
                        className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10 disabled:opacity-50"
                      >
                        {(Object.entries(StatusLabels) as [string, string][]).map(([val, label]) => (
                          <option key={val} value={val}>
                            {label}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Notes */}
                    <div>
                      <label className="mb-1 block text-sm font-medium text-text">
                        Notes <span className="text-muted">(optional)</span>
                      </label>
                      <textarea
                        value={cpNotes}
                        onChange={(e) => setCpNotes(e.target.value)}
                        placeholder="Any additional notes..."
                        rows={2}
                        disabled={cpPending || cpConfirming}
                        className="w-full resize-none rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10 disabled:opacity-50"
                      />
                    </div>

                    {/* Error */}
                    {cpError && (
                      <p className="text-xs text-red-400">
                        {cpError instanceof Error ? cpError.message : 'Transaction failed'}
                      </p>
                    )}

                    <div className="flex justify-end gap-3">
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => setShowCheckpointForm(false)}
                        disabled={cpPending || cpConfirming}
                      >
                        Cancel
                      </Button>
                      <Button
                        onClick={handleSubmitCheckpoint}
                        disabled={cpPending || cpConfirming || !cpLocation.trim()}
                      >
                        {(cpPending || cpConfirming) && (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        )}
                        {cpPending
                          ? 'Submitting...'
                          : cpConfirming
                          ? 'Confirming...'
                          : 'Submit Checkpoint'}
                      </Button>
                    </div>
                    </div>
                  </motion.div>
                )}
              </div>

              {/* Transfer Custody */}
              <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.02] backdrop-blur-2xl">
                <button
                  onClick={() => setShowTransferForm((v) => !v)}
                  className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-white/[0.02]"
                >
                  <div className="flex items-center gap-3">
                    <ArrowRight className="h-4 w-4 text-accent" />
                    <span className="text-sm font-medium text-text">Transfer Custody</span>
                  </div>
                  {showTransferForm ? (
                    <ChevronUp className="h-4 w-4 text-muted/60" />
                  ) : (
                    <ChevronDown className="h-4 w-4 text-muted/60" />
                  )}
                </button>

                {showTransferForm && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
                    className="overflow-hidden"
                  >
                    <div className="border-t border-white/[0.06] px-5 pb-5 pt-4 space-y-4">
                    <div>
                      <label className="mb-1 block text-sm font-medium text-text">
                        New Handler Address <span className="text-red-400">*</span>
                      </label>
                      <input
                        type="text"
                        value={txHandler}
                        onChange={(e) => {
                          setTxHandler(e.target.value)
                          setTxHandlerError('')
                        }}
                        placeholder="0x..."
                        disabled={txPending || txConfirming}
                        className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 font-mono text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10 disabled:opacity-50"
                      />
                      {txHandlerError && (
                        <p className="mt-1 text-xs text-red-400">{txHandlerError}</p>
                      )}
                    </div>

                    {/* Error */}
                    {txError && (
                      <p className="text-xs text-red-400">
                        {txError instanceof Error ? txError.message : 'Transaction failed'}
                      </p>
                    )}

                    <div className="flex justify-end gap-3">
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => setShowTransferForm(false)}
                        disabled={txPending || txConfirming}
                      >
                        Cancel
                      </Button>
                      <Button
                        onClick={handleTransferCustody}
                        disabled={txPending || txConfirming || !txHandler.trim()}
                      >
                        {(txPending || txConfirming) && (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        )}
                        {txPending
                          ? 'Submitting...'
                          : txConfirming
                          ? 'Confirming...'
                          : 'Transfer'}
                      </Button>
                    </div>
                    </div>
                  </motion.div>
                )}
              </div>
            </div>
          )}
        </motion.div>
      )}

      {/* ─── Add/Edit Modal ────────────────────────────────────────── */}
      <Modal
        open={modalOpen}
        onClose={() => {
          if (!isMutating) {
            setModalOpen(false)
            setEditingShipment(null)
            reset()
          }
        }}
        title={editingShipment ? 'Edit Shipment' : 'Add Shipment'}
      >
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {mutationError && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/[0.06] p-3 text-sm text-red-400">
              {mutationError instanceof Error ? mutationError.message : 'An error occurred'}
            </div>
          )}

          <div>
            <label className="mb-1 block text-sm font-medium text-text">
              Product ID
            </label>
            <Controller
              name="product_id"
              control={control}
              render={({ field }) => (
                <ProductCombobox
                  value={field.value}
                  onChange={field.onChange}
                  disabled={!!editingShipment}
                  error={errors.product_id?.message}
                />
              )}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium text-text">
                Origin
              </label>
              <input
                {...register('origin')}
                placeholder="Origin location"
                className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
              />
              {errors.origin && (
                <p className="mt-1 text-xs text-red-400">{errors.origin.message}</p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-text">
                Destination
              </label>
              <input
                {...register('destination')}
                placeholder="Destination location"
                className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
              />
              {errors.destination && (
                <p className="mt-1 text-xs text-red-400">{errors.destination.message}</p>
              )}
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-text">
              Notes <span className="text-muted">(optional)</span>
            </label>
            <textarea
              {...register('notes')}
              rows={3}
              placeholder="Additional notes..."
              className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
            />
            {errors.notes && (
              <p className="mt-1 text-xs text-red-400">{errors.notes.message}</p>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setModalOpen(false)
                setEditingShipment(null)
                reset()
              }}
              disabled={isMutating}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isMutating}>
              {isMutating ? <LoadingSpinner size="sm" /> : editingShipment ? 'Save Changes' : 'Create Shipment'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
