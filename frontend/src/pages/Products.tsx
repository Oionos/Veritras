import { useState, useEffect, useCallback, useRef } from 'react'
import { motion } from 'framer-motion'
import { toHex, pad } from 'viem'
import { useAccount } from 'wagmi'
import Card from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import Modal from '@/components/ui/Modal'
import {
  useProductsPaginated,
  useProduct,
  useProductHistory,
  useProductTransfers,
  useCreateProduct,
  useUpdateProduct,
} from '@/hooks/useApi'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { ProductSchema, type ProductFormData } from '@/schemas'
import { useRegisterProduct } from '@/hooks/useRegisterProduct'
import {
  useRecordCheckpoint,
  useTransferCustody,
  ShipmentStatus,
  StatusLabels,
} from '@/hooks/useShipmentTracker'
import {
  Search,
  MapPin,
  User,
  ArrowRight,
  CheckCircle2,
  ShieldCheck,
  AlertCircle,
  Package,
  Plus,
  Pencil,
  ChevronLeft,
  ChevronRight,
  Eye,
  ArrowUpDown,
  ChevronDown,
  ChevronUp,
  Link as LinkIcon,
  Loader2,
} from 'lucide-react'
import { formatAddress, formatDate } from '@/utils/formatters'
import { toast } from 'sonner'
import type { Product, Checkpoint, CustodyTransfer } from '@/types'

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

const DEFAULT_LIMIT = 10

// ─── Helpers ────────────────────────────────────────────────────────────────

function toBytes32(productId: string): `0x${string}` {
  const hex = toHex(productId) // UTF-8 → hex
  // bytes32 can hold at most 32 bytes (64 hex chars + "0x" prefix = 66 chars).
  if (hex.length > 66) {
    throw new Error(
      `product_id "${productId}" exceeds 32 bytes and cannot fit in bytes32`
    )
  }
  // Solidity bytes32 string literals are right-padded with zeroes.
  return pad(hex, { size: 32, dir: 'right' }) as `0x${string}`
}

function isValidEthAddress(value: string): boolean {
  return /^0x[0-9a-fA-F]{40}$/.test(value)
}

// ─── Component ──────────────────────────────────────────────────────────────

export default function Products() {
  const { isConnected } = useAccount()

  // ── Pagination / table state ──────────────────────────────────────────────
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(DEFAULT_LIMIT)
  const [serverSearch, setServerSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [sortBy, setSortBy] = useState<'product_id' | 'name' | null>(null)
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc')

  // ── Modal state ───────────────────────────────────────────────────────────
  const [modalOpen, setModalOpen] = useState(false)
  const [editingProduct, setEditingProduct] = useState<Product | null>(null)
  const [modalStep, setModalStep] = useState<'form' | 'blockchain'>('form')
  const [createdProduct, setCreatedProduct] = useState<Product | null>(null)

  // ── Detail / lookup state ─────────────────────────────────────────────────
  const [searchId, setSearchId] = useState('')
  const [submittedId, setSubmittedId] = useState('')

  // ── Blockchain action panel state ─────────────────────────────────────────
  const [showCheckpointForm, setShowCheckpointForm] = useState(false)
  const [showTransferForm, setShowTransferForm] = useState(false)

  // ── Ref for scrolling to product detail section ───────────────────────────
  const detailSectionRef = useRef<HTMLDivElement>(null)

  // Checkpoint form fields
  const [cpLocation, setCpLocation] = useState('')
  const [cpStatus, setCpStatus] = useState<ShipmentStatus>(0)
  const [cpNotes, setCpNotes] = useState('')

  // Transfer form fields
  const [txHandler, setTxHandler] = useState('')
  const [txHandlerError, setTxHandlerError] = useState('')

  // ── Blockchain hooks ──────────────────────────────────────────────────────
  const {
    register: registerOnChain,
    hash: registerHash,
    isPending: registerPending,
    isConfirming: registerConfirming,
    isSuccess: registerSuccess,
  } = useRegisterProduct()

  const {
    record,
    isPending: cpPending,
    isConfirming: cpConfirming,
    isSuccess: cpSuccess,
  } = useRecordCheckpoint()

  const {
    transfer,
    isPending: txPending,
    isConfirming: txConfirming,
    isSuccess: txSuccess,
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
    data: paginatedData,
    isLoading: tableLoading,
    error: tableError,
  } = useProductsPaginated(page, limit, debouncedSearch || undefined, sortBy ?? undefined, sortOrder)

  const createProduct = useCreateProduct()
  const updateProduct = useUpdateProduct()

  const rawItems: Product[] = Array.isArray(paginatedData)
    ? paginatedData
    : paginatedData?.items ?? []
  const totalRaw = Array.isArray(paginatedData)
    ? paginatedData.length
    : paginatedData?.total ?? 0

  const totalPages = Math.max(1, Math.ceil(totalRaw / limit))

  const {
    data: productDetail,
    isLoading: productLoading,
    error: productError,
  } = useProduct(submittedId)

  const {
    data: historyData,
    isLoading: historyLoading,
  } = useProductHistory(submittedId)

  const {
    data: transfersData,
    isLoading: transfersLoading,
  } = useProductTransfers(submittedId)

  const product = productDetail?.product
  const history: Checkpoint[] = historyData ?? []
  const transfers: CustodyTransfer[] = transfersData ?? []
  const isDelivered = history.some((c) => c.status === '3')
  const loadingDetail = productLoading || historyLoading || transfersLoading

  const isNotFound =
    productError instanceof Error &&
    (productError.message.includes('404') || productError.message.includes('not found'))

  // ── Form ──────────────────────────────────────────────────────────────────
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ProductFormData>({
    resolver: zodResolver(ProductSchema),
    mode: 'onChange',
    defaultValues: {
      name: '',
      manufacturer_address: '',
      description: '',
      metadata_uri: '',
    },
  })

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleSearchChange = (value: string) => {
    setServerSearch(value)
    setPage(1)
  }

  const handleSort = (column: 'product_id' | 'name') => {
    if (sortBy === column) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(column)
      setSortOrder('asc')
    }
    setPage(1)
  }

  const handleLookupSearch = () => {
    if (!searchId.trim()) return
    setSubmittedId(searchId.trim())
    // Reset blockchain action panels when looking up a new product
    setShowCheckpointForm(false)
    setShowTransferForm(false)
    setCpLocation('')
    setCpStatus(0)
    setCpNotes('')
    setTxHandler('')
    setTxHandlerError('')
  }

  const closeModal = useCallback(() => {
    // If the user bails out of the blockchain step without registering on-chain,
    // show a nudge so they know the product is saved and can be registered later.
    if (createdProduct !== null && modalStep === 'blockchain' && !registerSuccess) {
      toast.info('Product saved. Register it on-chain later from the product list.', {
        description: createdProduct.product_id,
      })
    }
    setModalOpen(false)
    setEditingProduct(null)
    setModalStep('form')
    setCreatedProduct(null)
    reset()
  }, [reset, createdProduct, modalStep, registerSuccess])

  // ── Auto-close modal after successful blockchain registration ─────────────
  useEffect(() => {
    if (registerSuccess && modalStep === 'blockchain') {
      const timer = setTimeout(() => {
        closeModal()
      }, 2000)
      return () => clearTimeout(timer)
    }
  }, [registerSuccess, modalStep, closeModal])

  const openAddModal = () => {
    setEditingProduct(null)
    setModalStep('form')
    setCreatedProduct(null)
    reset({ name: '', manufacturer_address: '', description: '', metadata_uri: '' })
    setModalOpen(true)
  }

  const openEditModal = (productItem: Product) => {
    setEditingProduct(productItem)
    setModalStep('form')
    setCreatedProduct(null)
    reset({
      name: productItem.name,
      manufacturer_address: productItem.manufacturer_address,
      description: productItem.description ?? '',
      metadata_uri: productItem.metadata_uri ?? '',
    })
    setModalOpen(true)
  }

  const viewProduct = (productId: string) => {
    setSearchId(productId)
    setSubmittedId(productId)
    setShowCheckpointForm(false)
    setShowTransferForm(false)
    setTimeout(() => detailSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  const onSubmit = async (formData: ProductFormData) => {
    try {
      if (editingProduct) {
        // Edit flow: single-step, no blockchain step
        await updateProduct.mutateAsync({
          product_id: editingProduct.product_id,
          data: formData,
        })
        closeModal()
      } else {
        // Create flow: step 1 — DB record
        const newProduct = await createProduct.mutateAsync(formData)
        setCreatedProduct(newProduct)
        setModalStep('blockchain')
      }
    } catch {
      // Error handled by mutation state
    }
  }

  const handleRegisterOnChain = () => {
    if (!createdProduct) return
    const productIdBytes32 = toBytes32(createdProduct.product_id)
    registerOnChain(
      productIdBytes32,
      createdProduct.name,
      createdProduct.description ?? '',
      createdProduct.metadata_uri ?? ''
    )
  }

  const handleSubmitCheckpoint = () => {
    if (!product || !cpLocation.trim()) return
    const productIdBytes32 = toBytes32(product.product_id)
    record(productIdBytes32, cpLocation.trim(), cpStatus, cpNotes.trim())
  }

  const handleTransferCustody = () => {
    if (!product) return
    if (!isValidEthAddress(txHandler)) {
      setTxHandlerError('Must be a valid Ethereum address (0x…40 hex chars)')
      return
    }
    setTxHandlerError('')
    const productIdBytes32 = toBytes32(product.product_id)
    transfer(productIdBytes32, txHandler as `0x${string}`)
  }

  const isMutating = createProduct.isPending || updateProduct.isPending
  const mutationError = createProduct.error || updateProduct.error

  const registerBusy = registerPending || registerConfirming

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="animate-fade-in space-y-6 px-6 sm:px-12 lg:px-20">
      {/* ─── Registry Header ───────────────────────────────────────── */}
      <div className="flex flex-col gap-4 pt-28 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <div className="h-px w-8 bg-accent/40" />
            <span className="text-xs font-semibold uppercase tracking-[0.2em] text-accent/60">
              Registry
            </span>
          </div>
          <h1 className="font-serif text-3xl leading-[1.1] tracking-tight text-text sm:text-4xl">
            Products
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-muted">
            Browse registered products, manage records, or search by ID to inspect
            blockchain history and custody transfers.
          </p>
        </div>
        <Button onClick={openAddModal} className="gap-2">
          <Plus className="h-4 w-4" />
          Add Product
        </Button>
      </div>

      {/* ─── Filters ───────────────────────────────────────────────── */}
      <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-5 backdrop-blur-2xl">
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/40" />
            <input
              type="text"
              placeholder="Search by product name..."
              value={serverSearch}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 pl-10 pr-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
            />
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

      {/* ─── Table Error ───────────────────────────────────────────── */}
      {tableError && (
        <div className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-5 backdrop-blur-xl">
          <AlertCircle className="h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="font-medium text-red-400">Failed to load products</p>
            <p className="text-sm text-red-400/70">
              {tableError instanceof Error ? tableError.message : 'Please try again later.'}
            </p>
          </div>
        </div>
      )}

      {/* ─── Products Table ────────────────────────────────────────── */}
      <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.02] backdrop-blur-2xl">
        {tableLoading ? (
          <div className="flex items-center justify-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        ) : rawItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="rounded-2xl bg-white/[0.02] p-4 mb-4">
              <Package className="h-10 w-10 text-muted/30" />
            </div>
            <p className="text-sm font-medium text-text">
              {serverSearch
                ? 'No products match your search'
                : 'No products registered yet'}
            </p>
            <p className="mt-1 text-xs text-muted">
              {serverSearch
                ? 'Try adjusting your search terms'
                : 'Register your first product to start tracking its journey'}
            </p>
            {!serverSearch && (
              <Button onClick={openAddModal} className="mt-4 gap-2">
                <Plus className="h-4 w-4" />
                Register Product
              </Button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-white/[0.06]">
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">
                    <button
                      onClick={() => handleSort('product_id')}
                      className="flex items-center gap-1 transition-colors hover:text-text"
                    >
                      Product ID
                      <ArrowUpDown className="h-3 w-3" />
                    </button>
                  </th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">
                    <button
                      onClick={() => handleSort('name')}
                      className="flex items-center gap-1 transition-colors hover:text-text"
                    >
                      Name
                      <ArrowUpDown className="h-3 w-3" />
                    </button>
                  </th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Manufacturer</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Registered</th>
                  <th className="px-6 py-4 text-xs font-medium uppercase tracking-wider text-muted/60">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {rawItems.map((item) => (
                  <tr
                    key={item.id}
                    className="transition-colors duration-150 ease-out hover:bg-white/[0.03]"
                  >
                    <td className="px-6 py-4 font-mono text-text">
                      {item.product_id}
                    </td>
                    <td className="px-6 py-4 text-text">{item.name}</td>
                    <td className="px-6 py-4 font-mono text-muted">
                      {formatAddress(item.manufacturer_address)}
                    </td>
                    <td className="px-6 py-4 text-muted">
                      {formatDate(item.registered_at)}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => viewProduct(item.product_id)}
                          className="rounded-lg p-2 text-muted/40 transition-colors hover:bg-white/[0.04] hover:text-text"
                          aria-label={`View ${item.product_id}`}
                        >
                          <Eye className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => openEditModal(item)}
                          className="rounded-lg p-2 text-muted/40 transition-colors hover:bg-white/[0.04] hover:text-text"
                          aria-label={`Edit ${item.product_id}`}
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
        {!tableLoading && rawItems.length > 0 && (
          <div className="flex items-center justify-between border-t border-white/[0.06] px-6 py-4">
            <p className="text-sm text-muted">
              Page <span className="text-text">{page}</span> of{' '}
              <span className="text-text">{totalPages}</span>{' '}
              <span className="text-muted/50">({totalRaw} total)</span>
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || tableLoading}
                className="px-3"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="secondary"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || tableLoading}
                className="px-3"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* ─── Product Lookup ────────────────────────────────────────── */}
      <div className="space-y-3 pt-4">
        <div className="flex items-center gap-4">
          <div className="h-px w-8 bg-accent/40" />
          <span className="text-xs font-semibold uppercase tracking-[0.2em] text-accent/60">
            Search
          </span>
        </div>
        <h2 className="font-serif text-2xl leading-[1.1] tracking-tight text-text sm:text-3xl">
          Product Lookup
        </h2>
        <p className="max-w-xl text-sm leading-relaxed text-muted">
          Search for a product by ID to view its complete blockchain history,
          custody transfers, and verification status.
        </p>
      </div>

      <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-1 backdrop-blur-2xl">
        <div className="flex flex-col gap-3 p-5 sm:flex-row">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/40" />
            <input
              type="text"
              placeholder="Enter product ID (e.g., PROD-8842)"
              value={searchId}
              onChange={(e) => setSearchId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleLookupSearch()}
              className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 pl-10 pr-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
            />
          </div>
          <Button onClick={handleLookupSearch} disabled={loadingDetail} className="min-w-[120px]">
            {loadingDetail ? <LoadingSpinner size="sm" /> : 'Search'}
          </Button>
        </div>
      </div>

      {/* ─── Not Found ─────────────────────────────────────────────── */}
      {isNotFound && (
        <div className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-5 backdrop-blur-xl">
          <AlertCircle className="h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="font-medium text-red-400">Product Not Found</p>
            <p className="text-sm text-red-400/70">
              No product with ID &quot;{submittedId}&quot; was found on the blockchain.
            </p>
          </div>
        </div>
      )}

      {/* ─── Error (other than 404) ────────────────────────────────── */}
      {productError && !isNotFound && (
        <div className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-5 backdrop-blur-xl">
          <AlertCircle className="h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="font-medium text-red-400">Error</p>
            <p className="text-sm text-red-400/70">
              {productError instanceof Error ? productError.message : 'Failed to load product'}
            </p>
          </div>
        </div>
      )}

      {/* ─── Product Details ───────────────────────────────────────── */}
      {product && !loadingDetail && (
        <div ref={detailSectionRef} className="space-y-4">
          <Card variant="accent">
            <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <h2 className="font-mono text-xl font-semibold text-text">
                    {product.product_id}
                  </h2>
                  <Badge variant={isDelivered ? 'success' : 'blue'}>
                    {isDelivered ? 'Delivered' : 'In Transit'}
                  </Badge>
                </div>
                <h3 className="text-lg text-text">{product.name}</h3>
                {product.description && (
                  <p className="text-sm text-muted">{product.description}</p>
                )}
                <div className="flex flex-wrap gap-4 text-sm text-muted">
                  <div className="flex items-center gap-2">
                    <User className="h-4 w-4" />
                    Manufacturer: {formatAddress(product.manufacturer_address)}
                  </div>
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="h-4 w-4 text-accent" />
                    Registered {formatDate(product.registered_at)}
                  </div>
                </div>
              </div>
              <div className="rounded-xl bg-accent/[0.06] p-4 text-center">
                <CheckCircle2 className="mx-auto h-8 w-8 text-accent" />
                <p className="mt-2 text-xs font-medium text-accent">Blockchain Verified</p>
              </div>
            </div>
          </Card>

          {/* ─── Blockchain Actions ─────────────────────────────────── */}
          {isConnected ? (
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
                    transition={{
                      duration: 0.25,
                      ease: [0.23, 1, 0.32, 1],
                    }}
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

                    <div className="flex justify-end">
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
                    transition={{
                      duration: 0.25,
                      ease: [0.23, 1, 0.32, 1],
                    }}
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

                    <div className="flex justify-end">
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
          ) : (
            <div className="flex items-center gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.02] px-5 py-4 text-sm text-muted backdrop-blur-2xl">
              <LinkIcon className="h-4 w-4 shrink-0 text-muted/40" />
              Connect your wallet to record checkpoints or transfer custody on-chain.
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <h3 className="mb-6 font-semibold text-text">Shipment Timeline</h3>
              {history.length === 0 ? (
                <p className="text-sm text-muted">No checkpoint history available.</p>
              ) : (
                <div className="relative space-y-0">
                  <div className="absolute left-[19px] top-2 bottom-2 w-px bg-white/[0.06]" />
                  {history.map((checkpoint, index) => (
                    <motion.div
                      key={checkpoint.id}
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{
                        duration: 0.4,
                        delay: index * 0.06,
                        ease: [0.23, 1, 0.32, 1],
                      }}
                    >
                    <div className="relative flex gap-4 pb-8 last:pb-0">
                      <div
                        className={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 ${
                          checkpoint.status === '3'
                            ? 'border-accent bg-accent/10'
                            : 'border-white/[0.1] bg-white/[0.04]'
                        }`}
                      >
                        {checkpoint.status === '3' ? (
                          <CheckCircle2 className="h-4 w-4 text-accent" />
                        ) : (
                          <div className="h-2.5 w-2.5 rounded-full bg-muted/40" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1 space-y-1 pt-1">
                        <div className="flex items-center justify-between">
                          <p className="font-medium text-text">
                            {checkpoint.notes || statusLabels[checkpoint.status] || 'Update'}
                          </p>
                          <span className="font-mono text-xs text-muted/60">
                            {formatDate(checkpoint.timestamp)}
                          </span>
                        </div>
                        <p className="flex items-center gap-1 text-sm text-muted">
                          <MapPin className="h-3 w-3" />
                          {checkpoint.location}
                        </p>
                        <Badge variant={statusVariant[checkpoint.status] || 'default'} className="mt-1">
                          {statusLabels[checkpoint.status] || checkpoint.status}
                        </Badge>
                        <p className="font-mono text-xs text-muted/40">
                          By {formatAddress(checkpoint.handler_address)}
                        </p>
                      </div>
                    </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </Card>

            <Card>
              <h3 className="mb-6 font-semibold text-text">Custody Transfers</h3>
              {transfers.length === 0 ? (
                <p className="text-sm text-muted">No custody transfers available.</p>
              ) : (
                <div className="space-y-3">
                  {transfers.map((transfer) => (
                    <div
                      key={transfer.id}
                      className="rounded-xl bg-white/[0.02] p-3 transition-colors hover:bg-white/[0.04]"
                    >
                      <div className="flex items-center gap-2 text-xs text-muted">
                        <span className="font-mono">{formatAddress(transfer.from_address)}</span>
                        <ArrowRight className="h-3 w-3 text-accent" />
                        <span className="font-mono">{formatAddress(transfer.to_address)}</span>
                      </div>
                      <p className="mt-2 text-xs text-muted/50">
                        {formatDate(transfer.timestamp)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}

      {!product && !loadingDetail && !productError && !submittedId && (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/[0.06] bg-white/[0.02] py-16 text-center backdrop-blur-xl">
          <Package className="h-12 w-12 text-muted/20" />
          <p className="mt-4 text-sm text-muted">Enter a product ID to view its details</p>
        </div>
      )}

      {/* ─── Add/Edit Modal ────────────────────────────────────────── */}
      <Modal
        open={modalOpen}
        onClose={() => {
          if (!isMutating && !registerBusy) {
            closeModal()
          }
        }}
        title={
          modalStep === 'blockchain'
            ? 'Register on Blockchain'
            : editingProduct
            ? 'Edit Product'
            : 'Add Product'
        }
      >
        {/* ── Step 1: Form ── */}
        {modalStep === 'form' && (
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {mutationError && (
              <div className="rounded-xl border border-red-500/20 bg-red-500/[0.06] p-3 text-sm text-red-400">
                {mutationError instanceof Error ? mutationError.message : 'An error occurred'}
              </div>
            )}

            <div>
              <label className="mb-1 block text-sm font-medium text-text">
                Product Name
              </label>
              <input
                {...register('name')}
                placeholder="e.g., Organic Coffee Beans"
                className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
              />
              {errors.name && (
                <p className="mt-1 text-xs text-red-400">{errors.name.message}</p>
              )}
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-text">
                Manufacturer Address
              </label>
              <input
                {...register('manufacturer_address')}
                placeholder="0x..."
                className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
              />
              {errors.manufacturer_address && (
                <p className="mt-1 text-xs text-red-400">{errors.manufacturer_address.message}</p>
              )}
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-text">
                Description <span className="text-muted">(optional)</span>
              </label>
              <textarea
                {...register('description')}
                rows={2}
                placeholder="Brief description of the product..."
                className="w-full resize-none rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
              />
              {errors.description && (
                <p className="mt-1 text-xs text-red-400">{errors.description.message}</p>
              )}
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-text">
                Metadata URI <span className="text-muted">(optional)</span>
              </label>
              <input
                {...register('metadata_uri')}
                placeholder="https://..."
                className="w-full rounded-xl border border-white/[0.06] bg-bg py-2.5 px-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
              />
              {errors.metadata_uri && (
                <p className="mt-1 text-xs text-red-400">{errors.metadata_uri.message}</p>
              )}
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <Button
                type="button"
                variant="secondary"
                onClick={closeModal}
                disabled={isMutating}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isMutating}>
                {isMutating ? (
                  <LoadingSpinner size="sm" />
                ) : editingProduct ? (
                  'Save Changes'
                ) : (
                  'Create Product'
                )}
              </Button>
            </div>
          </form>
        )}

        {/* ── Step 2: Blockchain confirmation ── */}
        {modalStep === 'blockchain' && createdProduct && (
          <div className="space-y-5">
            {/* Success banner */}
            <div className="flex items-start gap-3 rounded-xl border border-accent/20 bg-accent/[0.06] p-4">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
              <div className="space-y-1">
                <p className="text-sm font-medium text-text">
                  Product created successfully!
                </p>
                <p className="font-mono text-xs text-muted">
                  ID: {createdProduct.product_id}
                </p>
              </div>
            </div>

            {/* Blockchain registration prompt */}
            {isConnected ? (
              <div className="space-y-4">
                <p className="text-sm text-muted">
                  Register{' '}
                  <span className="font-mono text-text">{createdProduct.product_id}</span>{' '}
                  on the Sepolia blockchain to anchor it on-chain.
                </p>

                {/* Tx hash on success */}
                {registerSuccess && registerHash && (
                  <div className="flex items-center gap-2 rounded-xl border border-accent/20 bg-accent/[0.06] px-4 py-3 text-xs">
                    <LinkIcon className="h-3.5 w-3.5 shrink-0 text-accent" />
                    <span className="text-muted">Transaction submitted!</span>
                    <span className="font-mono text-accent break-all">{registerHash}</span>
                  </div>
                )}

                <div className="flex justify-end gap-3">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={closeModal}
                    disabled={registerBusy}
                  >
                    Skip
                  </Button>
                  <Button
                    type="button"
                    onClick={handleRegisterOnChain}
                    disabled={registerBusy || registerSuccess}
                  >
                    {registerBusy && <Loader2 className="h-4 w-4 animate-spin" />}
                    {registerPending
                      ? 'Submitting...'
                      : registerConfirming
                      ? 'Confirming...'
                      : registerSuccess
                      ? 'Registered!'
                      : 'Register on Blockchain'}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-4 py-3 text-sm text-muted">
                  <LinkIcon className="h-4 w-4 shrink-0 text-muted/40" />
                  Connect your wallet to register this product on the blockchain.
                </div>
                <div className="flex justify-end">
                  <Button type="button" onClick={closeModal}>
                    Done
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
