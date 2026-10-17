import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  account: { address: '0x1234567890123456789012345678901234567890', chainId: 11155111, status: 'connected' },
  sign: vi.fn(),
}))
vi.mock('wagmi', () => ({ useAccount: () => mocks.account, useSignMessage: () => ({ signMessageAsync: mocks.sign }) }))
vi.mock('wagmi/actions', () => ({ getAccount: () => mocks.account }))
vi.mock('@/config/wagmi', () => ({ rainbowKitConfig: {} }))
vi.mock('@/config/runtime', () => ({ appEnvironment: { apiUrl: 'http://api.test', chainId: 11155111 } }))

import { useAuth } from './useAuth'
import { bindSessionWallet, clearAuthToken, sessionSnapshot } from './authSession'

function prepareFetch() {
  const address = mocks.account.address
  const encode = (value: unknown) => btoa(JSON.stringify(value)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_')
  const exp = Math.floor(Date.now() / 1000) + 3600
  const token = `${encode({ alg: 'HS256' })}.${encode({ sub: address, chain_id: 11155111, exp })}.c2ln`
  const message = `${window.location.host} wants you to sign in with your Ethereum account:\n${address}\n\nSign in to Veritras`
  const fetch = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ domain: window.location.host, uri: window.location.origin, chain_id: 11155111, message, expires_at: new Date(Date.now() + 300000).toISOString() }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: token, address, token_type: 'bearer', expires_at: new Date(exp * 1000).toISOString() }) })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

beforeEach(() => {
  mocks.account = { address: '0x1234567890123456789012345678901234567890', chainId: 11155111, status: 'connected' }
  mocks.sign.mockReset().mockResolvedValue('0xsignature')
  clearAuthToken()
  bindSessionWallet(mocks.account.address, mocks.account.chainId, mocks.account.status)
})

describe('wallet sign-in', () => {
  it('shares a successful login between hook consumers', async () => {
    prepareFetch()
    const first = renderHook(useAuth), second = renderHook(useAuth)
    await act(async () => { await first.result.current.login() })
    expect(first.result.current.isAuthenticated).toBe(true)
    expect(second.result.current.isAuthenticated).toBe(true)
    act(() => first.result.current.logout())
    expect(second.result.current.isAuthenticated).toBe(false)
  })

  it('discards an old wallet signature when the account changes during signing', async () => {
    const fetch = prepareFetch()
    let finish!: (signature: string) => void
    mocks.sign.mockReturnValue(new Promise<string>(resolve => { finish = resolve }))
    const hook = renderHook(useAuth)
    let login!: Promise<void>
    act(() => { login = hook.result.current.login() })
    const rejected = expect(login).rejects.toThrow('Wallet changed')
    await waitFor(() => expect(mocks.sign).toHaveBeenCalled())
    mocks.account = { ...mocks.account, address: '0x0987654321098765432109876543210987654321' }
    hook.rerender()
    await act(async () => { finish('0xsignature'); await rejected })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(sessionSnapshot().token).toBeNull()
  })

  it('rejects a missing bearer token before persisting credentials', async () => {
    const fetch = prepareFetch()
    fetch.mockReset()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ domain: window.location.host, uri: window.location.origin, chain_id: 11155111, message: `${window.location.host} wants you to sign in with your Ethereum account:\n${mocks.account.address}\n`, expires_at: new Date(Date.now() + 300000).toISOString() }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ token_type: 'bearer' }) })
    const hook = renderHook(useAuth)
    await act(async () => { await expect(hook.result.current.login()).rejects.toThrow('Invalid sign-in response') })
    expect(sessionSnapshot().token).toBeNull()
  })
})
