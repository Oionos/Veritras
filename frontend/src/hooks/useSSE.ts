import { appEnvironment } from '@/config/runtime'
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'

const API_URL = appEnvironment.apiUrl

export function useAnalyticsEvents(onEvent: (type: string, data: unknown) => void, enabled = true) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    if (!enabled) return
    let eventSource: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      eventSource = new EventSource(`${API_URL}/analytics/events`)

      for (const type of ['product_created', 'shipment_created', 'chain_updated', 'resync']) {
        eventSource.addEventListener(type, (event) => {
          try {
            onEventRef.current(type, JSON.parse((event as MessageEvent).data))
          } catch {
            onEventRef.current(type, {})
          }
        })
      }

      eventSource.onerror = () => {
        eventSource?.close()
        eventSource = null
        reconnectTimer = setTimeout(connect, 5000)
      }
    }

    connect()

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer)
      eventSource?.close()
    }
  }, [enabled])
}

/** One stream for every page; a reconnect/resync refreshes committed state. */
export function useChainEvents(enabled = true) {
  const queryClient = useQueryClient()
  useAnalyticsEvents(() => {
    for (const key of ['products', 'product', 'product-history', 'product-transfers',
      'shipments', 'shipment', 'timeline', 'verify', 'registration', 'metadata-history', 'exceptions', 'kpis', 'anomalies', 'bottlenecks', 'daily-volume']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }, enabled)
}
