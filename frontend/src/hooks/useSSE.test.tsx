import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChainEvents } from './useSSE'

class Stream {
  static instances: Stream[] = []
  listeners = new Map<string, (event: MessageEvent) => void>()
  onerror: (() => void) | null = null
  close = vi.fn()
  constructor(public url: string) { Stream.instances.push(this) }
  addEventListener(type: string, callback: (event: MessageEvent) => void) { this.listeners.set(type, callback) }
  send(type: string) { this.listeners.get(type)?.({ data: '{}' } as MessageEvent) }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); Stream.instances = [] })

describe('committed chain events', () => {
  it('refreshes evidence/history/shipments and cleans up reconnects', () => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', Stream)
    const client = new QueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { unmount } = renderHook(() => useChainEvents(), { wrapper })
    const first = Stream.instances[0]
    expect(first.url).toContain('/analytics/events')
    act(() => first.send('chain_updated'))
    for (const key of ['products', 'product-history', 'product-transfers', 'shipments', 'verify', 'kpis']) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: [key] })
    }
    act(() => first.onerror?.())
    expect(first.close).toHaveBeenCalledOnce()
    act(() => vi.advanceTimersByTime(5000))
    expect(Stream.instances).toHaveLength(2)
    invalidate.mockClear()
    act(() => Stream.instances[1].send('resync'))
    expect(invalidate).toHaveBeenCalled()
    unmount()
    expect(Stream.instances[1].close).toHaveBeenCalledOnce()
    act(() => vi.advanceTimersByTime(10000))
    expect(Stream.instances).toHaveLength(2)
  })
})
