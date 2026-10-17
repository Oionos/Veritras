import { act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/config/runtime', () => ({
  appEnvironment: { apiUrl: 'http://api.test', chainId: 11155111 },
}))

import {
  bindSessionWallet, clearAuthToken, sessionGeneration, sessionSnapshot,
  storeAuthToken, subscribeSession, tokenClaims,
} from './authSession'

const wallet = '0x1234567890123456789012345678901234567890'
const other = '0x0987654321098765432109876543210987654321'
function token(overrides: Record<string, unknown> = {}) {
  const encode = (value: unknown) => btoa(JSON.stringify(value)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_')
  return `${encode({ alg: 'HS256' })}.${encode({ sub: wallet, exp: Math.floor(Date.now() / 1000) + 3600, chain_id: 11155111, ...overrides })}.c2ln`
}

beforeEach(() => {
  localStorage.clear()
  clearAuthToken()
  bindSessionWallet(wallet, 11155111, 'connected')
})
afterEach(() => { clearAuthToken(); vi.useRealTimers() })

describe('shared browser authentication', () => {
  it.each(['undefined', 'null', '', 'bad.token.parts'])('rejects malformed persisted token %s', value => {
    expect(tokenClaims(value)).toBeNull()
    expect(() => storeAuthToken(value)).toThrow('Invalid sign-in response')
    expect(sessionSnapshot().token).toBeNull()
  })

  it('notifies all subscribers in the same tab on sign-in and sign-out', () => {
    const first = vi.fn(), second = vi.fn()
    const stopFirst = subscribeSession(first), stopSecond = subscribeSession(second)
    storeAuthToken(token())
    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(1)
    clearAuthToken()
    expect(first).toHaveBeenCalledTimes(2)
    expect(second).toHaveBeenCalledTimes(2)
    stopFirst(); stopSecond()
  })

  it.each([
    [other, 11155111, 'connected'],
    [wallet, 31337, 'connected'],
    [undefined, undefined, 'disconnected'],
  ])('clears credentials when wallet binding changes', (address, chainId, status) => {
    storeAuthToken(token())
    bindSessionWallet(address as string | undefined, chainId as number | undefined, status as string)
    expect(sessionSnapshot().token).toBeNull()
    expect(localStorage.getItem('veritras_auth_token')).toBeNull()
  })

  it('expires a session without waiting for an API failure', () => {
    vi.useFakeTimers()
    const expires = Math.floor(Date.now() / 1000) + 5
    storeAuthToken(token({ exp: expires }))
    act(() => { vi.advanceTimersByTime(5001) })
    expect(sessionSnapshot().token).toBeNull()
  })

  it('synchronizes sign-out from another tab', () => {
    storeAuthToken(token())
    localStorage.removeItem('veritras_auth_token')
    window.dispatchEvent(new StorageEvent('storage', { key: 'veritras_auth_token', newValue: null }))
    expect(sessionSnapshot().token).toBeNull()
  })

  it('invalidates an in-flight sign-in generation when signing out', () => {
    const before = sessionGeneration()
    clearAuthToken()
    expect(sessionGeneration()).toBeGreaterThan(before)
  })
})
