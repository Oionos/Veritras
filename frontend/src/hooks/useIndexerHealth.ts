import { useQuery } from '@tanstack/react-query'
import { appEnvironment } from '@/config/runtime'
import type { components } from '@/types/api'

export type Readiness = components['schemas']['ReadinessResponse']

export async function fetchIndexerHealth(
  signal?: AbortSignal,
): Promise<Readiness> {
  const timeout = AbortSignal.timeout(5000)
  const response = await fetch(`${appEnvironment.apiUrl}/health/ready`, {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  })
  if (!response.ok && response.status !== 503)
    throw new Error('Synchronization status unavailable')
  const data: Readiness = await response.json()
  if (
    !['ready', 'not_ready'].includes(data?.status) ||
    !data?.indexer?.status
  ) {
    throw new Error('Synchronization status unavailable')
  }
  return data
}

export function useIndexerHealth() {
  return useQuery({
    queryKey: ['indexer-health'],
    queryFn: ({ signal }) => fetchIndexerHealth(signal),
    staleTime: 15000,
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
    retry: false,
  })
}
