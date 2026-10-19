import { useStreamHealth } from '@/hooks/streamHealth'
import { useIndexerHealth } from '@/hooks/useIndexerHealth'

export default function IndexerStatusNotice() {
  const stream = useStreamHealth()
  const { data, isError } = useIndexerHealth()
  let message: string | undefined
  if (isError)
    message =
      'Synchronization status is unavailable. Recent activity may be delayed.'
  else if (data?.database !== undefined && data.database !== 'connected')
    message = 'Live data is temporarily unavailable. Please try again shortly.'
  else if (data?.indexer.status === 'disabled')
    message =
      'Blockchain updates are paused. Recent activity may not appear yet.'
  else if (
    data?.indexer.status === 'catching_up' ||
    data?.indexer.status === 'starting'
  )
    message =
      'Blockchain activity is syncing. Recent changes may take a little longer to appear.'
  else if (data && data.indexer.status !== 'current')
    message =
      'Blockchain updates are delayed. Some recent activity may be missing.'
  if (!message && (stream === 'reconnecting' || stream === 'stale')) message = 'Live updates are disconnected. Showing previously fetched data while the connection retries.'
  if (!message) return null
  return (
    <div
      className="-mb-20 px-6 pt-24 sm:px-12 lg:px-20"
      role="status"
      aria-label="Blockchain synchronization"
      aria-live="polite"
    >
      <p className="rounded-lg border border-amber-400/20 bg-amber-400/[0.05] px-4 py-2 text-xs text-amber-200">
        {message}
      </p>
    </div>
  )
}
