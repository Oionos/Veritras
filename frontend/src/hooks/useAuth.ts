import { appEnvironment } from '@/config/runtime'
import { useCallback, useEffect, useState } from 'react'
import { useAccount, useSignMessage } from 'wagmi'

const AUTH_TOKEN_KEY = 'veritras_auth_token'
const API_URL = appEnvironment.apiUrl

export interface AuthState {
  token: string | null
  isAuthenticated: boolean
  isLoggingIn: boolean
  loginError: string | null
  login: () => Promise<void>
  logout: () => void
}

export function useAuth(): AuthState {
  const { address, isConnected } = useAccount()
  const { signMessageAsync } = useSignMessage()

  const [token, setToken] = useState<string | null>(() => {
    return localStorage.getItem(AUTH_TOKEN_KEY)
  })
  const [isLoggingIn, setIsLoggingIn] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)

  const isAuthenticated = !!token

  // Listen for auth logout events triggered by 401 responses in useApi
  useEffect(() => {
    const handleLogout = () => {
      setToken(null)
    }
    window.addEventListener('veritras:logout', handleLogout)
    return () => window.removeEventListener('veritras:logout', handleLogout)
  }, [])

  // Sync token state with localStorage changes from other tabs
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === AUTH_TOKEN_KEY) {
        setToken(e.newValue)
      }
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  const login = useCallback(async () => {
    if (!isConnected || !address) {
      setLoginError('Wallet not connected')
      return
    }

    setIsLoggingIn(true)
    setLoginError(null)

    try {
      // 1. Fetch nonce from backend
      const nonceRes = await fetch(`${API_URL}/auth/nonce`)
      if (!nonceRes.ok) {
        throw new Error('Failed to fetch nonce')
      }
      const { nonce } = await nonceRes.json()

      // 2. Create SIWE message (Sepolia chain ID: 11155111)
      const domain = window.location.host
      const uri = window.location.origin
      const issuedAt = new Date().toISOString()
      const message = `${domain} wants you to sign in with your Ethereum account:\n${address}\n\nSign in to Veritras\n\nURI: ${uri}\nVersion: 1\nChain ID: ${appEnvironment.chainId}\nNonce: ${nonce}\nIssued At: ${issuedAt}`

      // 3. Sign message with wallet
      const signature = await signMessageAsync({ message })

      // 4. Verify signature and get JWT
      const verifyRes = await fetch(`${API_URL}/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, signature, address }),
      })

      if (!verifyRes.ok) {
        const errText = await verifyRes.text().catch(() => 'Verification failed')
        throw new Error(errText)
      }

      const { access_token: jwt } = await verifyRes.json()
      if (typeof jwt !== 'string' || !jwt) throw new Error('Invalid sign-in response')
      localStorage.setItem(AUTH_TOKEN_KEY, jwt)
      setToken(jwt)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed'
      setLoginError(message)
      throw err
    } finally {
      setIsLoggingIn(false)
    }
  }, [isConnected, address, signMessageAsync])

  const logout = useCallback(() => {
    localStorage.removeItem(AUTH_TOKEN_KEY)
    setToken(null)
  }, [])

  return {
    token,
    isAuthenticated,
    isLoggingIn,
    loginError,
    login,
    logout,
  }
}

export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY)
}

export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY)
  window.dispatchEvent(new CustomEvent('veritras:logout'))
}
