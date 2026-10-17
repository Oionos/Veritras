import { appEnvironment } from '@/config/runtime'

const TOKEN_KEY = 'veritras_auth_token'
const SCOPE_KEY = 'veritras_auth_scope'
const scope = `${appEnvironment.apiUrl}|${appEnvironment.chainId}`
const listeners = new Set<() => void>()

export interface SessionClaims {
  sub: string
  exp: number
  chain_id: number
}

export function tokenClaims(token: string): SessionClaims | null {
  try {
    const parts = token.split('.')
    if (
      parts.length !== 3 ||
      parts.some((part) => !/^[A-Za-z0-9_-]+$/.test(part))
    )
      return null
    const decode = (part: string) =>
      JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')))
    const header = decode(parts[0])
    const claims = decode(parts[1])
    if (
      header.alg !== 'HS256' ||
      typeof claims.sub !== 'string' ||
      !/^0x[\da-f]{40}$/i.test(claims.sub) ||
      typeof claims.exp !== 'number' ||
      claims.exp * 1000 <= Date.now() ||
      claims.chain_id !== appEnvironment.chainId
    )
      return null
    // The backend verifies the signature and full JWT scope. This check only
    // keeps expired/malformed or wrong-wallet sessions out of the UI.
    return claims
  } catch {
    return null
  }
}

function persistedToken(): string | null {
  if (typeof window === 'undefined') return null
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    if (
      !token ||
      localStorage.getItem(SCOPE_KEY) !== scope ||
      !tokenClaims(token)
    ) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(SCOPE_KEY)
      return null
    }
    return token
  } catch {
    return null
  }
}

let state = {
  token: persistedToken(),
  isLoggingIn: false,
  loginError: null as string | null,
}
let generation = 0
let walletIdentity = ''
let expiryTimer: ReturnType<typeof setTimeout> | undefined

export function sessionGeneration() {
  return generation
}
export function sessionSnapshot() {
  return state
}
export function subscribeSession(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function updateSession(changes: Partial<typeof state>) {
  state = { ...state, ...changes }
  clearTimeout(expiryTimer)
  const claims = state.token && tokenClaims(state.token)
  if (claims)
    expiryTimer = setTimeout(
      clearAuthToken,
      Math.max(0, claims.exp * 1000 - Date.now()),
    )
  listeners.forEach((listener) => listener())
}

export function clearAuthToken() {
  generation++
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(SCOPE_KEY)
  } catch {
    /* Browser storage can be unavailable; clear memory regardless. */
  }
  updateSession({ token: null, loginError: null })
}

export function bindSessionWallet(
  address?: string,
  chainId?: number,
  status?: string,
) {
  if (status === 'connecting' || status === 'reconnecting') return
  const identity =
    address && status === 'connected'
      ? `${address.toLowerCase()}|${chainId}`
      : ''
  if (walletIdentity && identity !== walletIdentity) clearAuthToken()
  walletIdentity = identity
  const claims = state.token && tokenClaims(state.token)
  if (
    state.token &&
    (!claims ||
      !address ||
      claims.sub.toLowerCase() !== address.toLowerCase() ||
      chainId !== appEnvironment.chainId ||
      status !== 'connected')
  )
    clearAuthToken()
}

export function storeAuthToken(token: string) {
  if (!tokenClaims(token)) throw new Error('Invalid sign-in response')
  localStorage.setItem(SCOPE_KEY, scope)
  localStorage.setItem(TOKEN_KEY, token)
  updateSession({ token })
}

export function getAuthToken(): string | null {
  const token = state.token
  if (token && !tokenClaims(token)) {
    clearAuthToken()
    return null
  }
  return token
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (
      event.key === TOKEN_KEY ||
      event.key === SCOPE_KEY ||
      event.key === null
    ) {
      generation++
      updateSession({ token: persistedToken() })
    }
  })
  window.addEventListener('veritras:logout', clearAuthToken)
  updateSession({})
}
