import { useState } from 'react'
import { motion } from 'framer-motion'
import Card from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Badge from '@/components/ui/Badge'
import LoadingSpinner from '@/components/ui/LoadingSpinner'
import { useVerifyProduct, useProduct } from '@/hooks/useApi'
import { Search, ShieldCheck, CheckCircle2, XCircle, MapPin, User } from 'lucide-react'
import { formatAddress, formatDate } from '@/utils/formatters'

export default function Verify() {
  const [inputId, setInputId] = useState('')
  const [submittedId, setSubmittedId] = useState('')

  const {
    data: verifyResult,
    isLoading: verifyLoading,
    error: verifyError,
  } = useVerifyProduct(submittedId)

  const {
    data: productDetail,
    isLoading: productLoading,
  } = useProduct(submittedId)

  const handleVerify = () => {
    if (!inputId.trim()) return
    setSubmittedId(inputId.trim())
  }

  const loading = verifyLoading || (verifyResult?.is_registered && productLoading)

  const isNotFound =
    verifyError instanceof Error &&
    (verifyError.message.includes('404') || verifyError.message.includes('not found'))

  const isFailed =
    (verifyResult && !verifyResult.is_registered) || isNotFound

  const isVerified = verifyResult?.is_registered === true

  return (
    <div className="animate-fade-in space-y-6 px-6 sm:px-12 lg:px-20">
      {/* ─── Header ──────────────────────────────────────────────── */}
      <div className="space-y-3 pt-28">
        <div className="flex items-center gap-4">
          <div className="h-px w-8 bg-accent/40" />
          <span className="text-xs font-semibold uppercase tracking-[0.2em] text-accent/60">
            Authenticity Check
          </span>
        </div>
        <h1 className="font-serif text-3xl leading-[1.1] tracking-tight text-text sm:text-4xl">
          Verify Authenticity
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted">
          Enter a product ID to verify its authenticity and view its complete blockchain history.
        </p>
      </div>

      {/* ─── Verification Input ───────────────────────────────────── */}
      <div className="max-w-2xl">
        <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-1 backdrop-blur-2xl transition-all duration-200 ease-out focus-within:border-accent/20 focus-within:shadow-[0_0_20px_rgba(200,240,96,0.05)]">
          <div className="flex flex-col gap-3 p-5 sm:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/40" />
              <input
                type="text"
                placeholder="Enter product ID"
                value={inputId}
                onChange={(e) => setInputId(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleVerify()}
                className="w-full rounded-xl border border-white/[0.06] bg-bg py-3 pl-10 pr-4 text-sm text-text placeholder-muted/40 outline-hidden transition-colors focus:border-accent/30 focus:ring-1 focus:ring-accent/10"
              />
            </div>
            <Button
              onClick={handleVerify}
              disabled={loading}
              className="min-w-[140px] gap-2"
            >
              {loading ? (
                <LoadingSpinner size="sm" />
              ) : (
                <>
                  <ShieldCheck className="h-4 w-4" />
                  Verify
                </>
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* ─── Not Found / Failed ───────────────────────────────────── */}
      {isFailed && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }}
          className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-5 backdrop-blur-xl"
        >
          <XCircle className="h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="font-medium text-red-400">Verification Failed</p>
            <p className="text-sm text-red-400/70">
              Product ID not found on the blockchain. This may indicate a counterfeit product.
            </p>
          </div>
        </motion.div>
      )}

      {/* ─── Error (other than 404) ───────────────────────────────── */}
      {verifyError && !isNotFound && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.23, 1, 0.32, 1] }}
          className="flex items-center gap-3 rounded-2xl border border-red-500/20 bg-red-500/[0.06] p-5 backdrop-blur-xl"
        >
          <XCircle className="h-5 w-5 shrink-0 text-red-400" />
          <div>
            <p className="font-medium text-red-400">Error</p>
            <p className="text-sm text-red-400/70">
              {verifyError instanceof Error ? verifyError.message : 'Verification failed'}
            </p>
          </div>
        </motion.div>
      )}

      {/* ─── Verification Result ──────────────────────────────────── */}
      {isVerified && verifyResult && (
        <div className="max-w-2xl space-y-4">
          {/* Success Banner */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          >
            <div className="flex items-center gap-3 rounded-2xl border border-accent/20 bg-accent/[0.06] p-6 backdrop-blur-xl">
              <CheckCircle2 className="h-8 w-8 shrink-0 text-accent" />
              <div>
                <p className="font-semibold text-accent">Authentic Product Verified</p>
                <p className="text-sm text-accent/70">
                  This product has been verified on the blockchain with{' '}
                  <span className="font-mono">{verifyResult.checkpoint_count}</span> checkpoint(s)
                </p>
              </div>
            </div>
          </motion.div>

          {/* Verification Details */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.1, ease: [0.23, 1, 0.32, 1] }}
          >
            <Card variant="accent">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted">Registration Status</p>
                    <p className="font-mono text-lg text-text">
                      {verifyResult.is_registered ? 'Registered on blockchain' : 'Not registered'}
                    </p>
                  </div>
                  <Badge variant="success">Verified</Badge>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted">Delivery Status</p>
                    <p className="text-sm text-text">
                      {verifyResult.is_delivered ? 'Delivered' : 'In Transit'}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted">Checkpoints</p>
                    <p className="font-mono text-sm text-text">{verifyResult.checkpoint_count}</p>
                  </div>
                </div>
              </div>
            </Card>
          </motion.div>

          {/* Product Details */}
          {productDetail?.product && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.2, ease: [0.23, 1, 0.32, 1] }}
            >
              <Card>
                <div className="space-y-4">
                  <h3 className="font-semibold text-text">Product Details</h3>
                  <div>
                    <p className="text-sm text-muted">Product ID</p>
                    <p className="font-mono text-lg text-text">{productDetail.product.product_id}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted">Name</p>
                    <p className="text-text">{productDetail.product.name}</p>
                  </div>
                  {productDetail.product.description && (
                    <div>
                      <p className="text-sm text-muted">Description</p>
                      <p className="text-text">{productDetail.product.description}</p>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-4 text-sm text-muted">
                    <div className="flex items-center gap-2">
                      <User className="h-4 w-4" />
                      Manufacturer: {formatAddress(productDetail.product.manufacturer_address)}
                    </div>
                    <div className="flex items-center gap-2">
                      <MapPin className="h-4 w-4" />
                      Registered {formatDate(productDetail.product.registered_at)}
                    </div>
                  </div>
                </div>
              </Card>
            </motion.div>
          )}
        </div>
      )}

      {/* ─── Initial State Helper ─────────────────────────────────── */}
      {!isVerified && !isFailed && !loading && !verifyError && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4 }}
          className="max-w-2xl"
        >
          <div className="rounded-2xl border border-dashed border-white/[0.06] bg-white/[0.02] p-10 text-center backdrop-blur-xl">
            <div className="mx-auto mb-4 rounded-2xl bg-white/[0.02] p-4">
              <ShieldCheck className="mx-auto h-10 w-10 text-muted/30" />
            </div>
            <p className="text-sm font-medium text-text">Verify Product Authenticity</p>
            <p className="mt-2 text-xs leading-relaxed text-muted">
              Enter a product ID to verify its authenticity
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted/60">
              Check blockchain-verified provenance, view checkpoint history,
              and confirm integrity.
            </p>
            <div className="mt-6 flex flex-col items-center gap-2">
              <div className="flex items-center gap-2 text-xs text-muted/60">
                <span className="h-1.5 w-1.5 rounded-full bg-accent/40" />
                <span>Blockchain-verified on Ethereum Sepolia</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted/60">
                <span className="h-1.5 w-1.5 rounded-full bg-accent2/40" />
                <span>View complete checkpoint history</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted/60">
                <span className="h-1.5 w-1.5 rounded-full bg-accent3/40" />
                <span>Confirm custody chain integrity</span>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </div>
  )
}
