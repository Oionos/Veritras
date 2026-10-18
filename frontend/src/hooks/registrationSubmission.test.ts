import { beforeEach, describe, expect, it, vi } from 'vitest'
import { saveSubmission, flushSubmissionOutbox, pendingSubmissionKey } from './registrationSubmission'
import { fetchApi } from './useApi'
import { getAuthToken } from './useAuth'
vi.mock('./useApi', () => ({ fetchApi: vi.fn() }))
vi.mock('./useAuth', () => ({ getAuthToken: vi.fn() }))
const address = `0x${'1'.repeat(40)}`
const original = { tx_hash: `0x${'a'.repeat(64)}`, operation: 'registration' as const }
const replacement = { ...original, tx_hash: `0x${'b'.repeat(64)}`, replaces_tx_hash: original.tx_hash }
beforeEach(() => { localStorage.clear(); vi.resetAllMocks(); vi.mocked(getAuthToken).mockReturnValue('test-token') })
describe('registration tracking outbox', () => {
  it('persists before sending and clears after the API accepts it', async () => {
    vi.mocked(fetchApi).mockImplementation(async () => {
      expect(JSON.parse(localStorage.getItem(pendingSubmissionKey('PROD-1', address))!)).toEqual([original])
      return {}
    })
    await saveSubmission('PROD-1', address, original)
    expect(localStorage.length).toBe(0)
  })
  it('survives an API outage and replays original before replacement on reload', async () => {
    vi.mocked(fetchApi).mockRejectedValue(new Error('offline'))
    await expect(saveSubmission('PROD-1', address, original)).rejects.toThrow('offline')
    await expect(saveSubmission('PROD-1', address, replacement)).rejects.toThrow('offline')
    vi.mocked(fetchApi).mockReset().mockResolvedValue({})
    await flushSubmissionOutbox('PROD-1', address)
    expect(JSON.parse(vi.mocked(fetchApi).mock.calls[0][1]!.body as string)).toEqual(original)
    expect(JSON.parse(vi.mocked(fetchApi).mock.calls[1][1]!.body as string)).toEqual(replacement)
    expect(localStorage.length).toBe(0)
  })
  it('retains public hashes when the session expires without sending an anonymous write', async () => {
    vi.mocked(getAuthToken).mockReturnValue(null)
    await expect(saveSubmission('PROD-1', address, original)).rejects.toThrow('Sign in')
    expect(fetchApi).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(1)
  })
  it('isolates tracking by wallet and product', async () => {
    vi.mocked(fetchApi).mockRejectedValue(new Error('offline'))
    await expect(saveSubmission('PROD-1', address, original)).rejects.toThrow()
    vi.mocked(fetchApi).mockReset().mockResolvedValue({})
    await flushSubmissionOutbox('PROD-1', `0x${'2'.repeat(40)}`)
    await flushSubmissionOutbox('PROD-2', address)
    expect(fetchApi).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(1)
  })
})
