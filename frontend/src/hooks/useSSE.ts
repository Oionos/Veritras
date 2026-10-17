import { appEnvironment } from '@/config/runtime'
import { useEffect, useRef } from 'react'

const API_URL = appEnvironment.apiUrl

export function useAnalyticsEvents(onEvent: (type: string, data: unknown) => void) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    let eventSource: EventSource | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      eventSource = new EventSource(`${API_URL}/analytics/events`)

      eventSource.addEventListener('product_created', (e) => {
        try {
          const data = JSON.parse(e.data)
          onEventRef.current('product_created', data)
        } catch {
          onEventRef.current('product_created', e.data)
        }
      })

      eventSource.addEventListener('shipment_created', (e) => {
        try {
          const data = JSON.parse(e.data)
          onEventRef.current('shipment_created', data)
        } catch {
          onEventRef.current('shipment_created', e.data)
        }
      })

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
  }, [])
}
