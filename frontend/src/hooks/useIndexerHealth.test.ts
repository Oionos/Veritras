import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchIndexerHealth } from './useIndexerHealth'
afterEach(() => vi.unstubAllGlobals())
describe('bounded public health fetch', () => {
  it('accepts 503 as a readable synchronization state', async () => {
    const data = { status: 'not_ready', indexer: { status: 'catching_up' } }
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: false, status: 503, json: async () => data })
    vi.stubGlobal('fetch', fetch)
    expect(await fetchIndexerHealth()).toEqual(data)
    expect(fetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal)
    expect(fetch.mock.calls[0][1].headers).toBeUndefined()
  })
  it.each([500, 401])(
    'rejects HTTP %s without echoing private bodies',
    async (status) => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status }))
      await expect(fetchIndexerHealth()).rejects.toThrow(
        'Synchronization status unavailable',
      )
    },
  )
  it('rejects malformed bodies', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
    )
    await expect(fetchIndexerHealth()).rejects.toThrow(
      'Synchronization status unavailable',
    )
  })
})
