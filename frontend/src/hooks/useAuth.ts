import { appEnvironment } from '@/config/runtime'
import { rainbowKitConfig } from '@/config/wagmi'
import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { useAccount, useSignMessage } from 'wagmi'
import { getAccount } from 'wagmi/actions'
import type { components } from '@/types/api'
import {
  bindSessionWallet,
  clearAuthToken,
  sessionGeneration,
  sessionSnapshot,
  storeAuthToken,
  subscribeSession,
  tokenClaims,
  updateSession,
} from './authSession'

export { clearAuthToken } from './authSession'
export function getAuthToken(): string | null {
  const account = getAccount(rainbowKitConfig)
  bindSessionWallet(account.address, account.chainId, account.status)
  const token = sessionSnapshot().token
  const claims = token && tokenClaims(token)
  return account.status === 'connected' &&
    claims &&
    claims.sub.toLowerCase() === account.address?.toLowerCase() &&
    account.chainId === appEnvironment.chainId
    ? token
    : null
}

export interface AuthState {
  token: string | null
  address: string | null
  isAuthenticated: boolean
  isLoggingIn: boolean
  loginError: string | null
  login: () => Promise<void>
  logout: () => void
}

let pendingLogin: Promise<void> | null = null

export function useAuth(): AuthState {
  const { address, chainId, status } = useAccount()
  const { signMessageAsync } = useSignMessage()
  const state = useSyncExternalStore(
    subscribeSession,
    sessionSnapshot,
    sessionSnapshot,
  )
  const claims = state.token && tokenClaims(state.token)
  const isAuthenticated = !!(
    claims &&
    status === 'connected' &&
    claims.sub.toLowerCase() === address?.toLowerCase() &&
    chainId === appEnvironment.chainId
  )

  useEffect(() => {
    bindSessionWallet(address, chainId, status)
  }, [address, chainId, status])

  const login = useCallback(async () => {
    if (pendingLogin) return pendingLogin
    if (
      !address ||
      status !== 'connected' ||
      chainId !== appEnvironment.chainId
    ) {
      updateSession({
        loginError:
          'Connect your wallet to the selected network before signing in',
      })
      throw new Error(
        'Connect your wallet to the selected network before signing in',
      )
    }
    const wallet = address.toLowerCase()
    const attempt = sessionGeneration()
    const checkWallet = () => {
      const current = getAccount(rainbowKitConfig)
      if (
        sessionGeneration() !== attempt ||
        current.status !== 'connected' ||
        current.address?.toLowerCase() !== wallet ||
        current.chainId !== appEnvironment.chainId
      ) {
        throw new Error('Wallet changed during sign-in. Please sign in again.')
      }
    }
    updateSession({ isLoggingIn: true, loginError: null })
    pendingLogin = (async () => {
      try {
        const response = await fetch(
          `${appEnvironment.apiUrl}/auth/challenge`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address }),
            cache: 'no-store',
          },
        )
        if (!response.ok)
          throw new Error('Could not create a sign-in challenge')
        const challenge: components['schemas']['ChallengeResponse'] =
          await response.json()
        const expiry = Date.parse(challenge.expires_at)
        if (
          challenge.uri !== window.location.origin ||
          challenge.domain !== window.location.host ||
          challenge.chain_id !== appEnvironment.chainId ||
          typeof challenge.message !== 'string' ||
          !challenge.message.startsWith(
            `${window.location.host} wants you to sign in with your Ethereum account:\n`,
          ) ||
          challenge.message.split('\n')[1]?.toLowerCase() !== wallet ||
          !Number.isFinite(expiry) ||
          expiry <= Date.now()
        ) {
          throw new Error(
            'Sign-in challenge does not match this app and wallet',
          )
        }
        checkWallet()
        const signature = await signMessageAsync({
          message: challenge.message,
        })
        checkWallet()
        const verify = await fetch(`${appEnvironment.apiUrl}/auth/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: challenge.message, signature }),
          cache: 'no-store',
        })
        if (!verify.ok)
          throw new Error(
            'Sign-in was rejected. Please request a new challenge.',
          )
        const result: components['schemas']['VerifyResponse'] =
          await verify.json()
        const jwt =
          typeof result.access_token === 'string' &&
          tokenClaims(result.access_token)
        if (
          !jwt ||
          jwt.sub.toLowerCase() !== wallet ||
          result.token_type !== 'bearer' ||
          typeof result.address !== 'string' ||
          result.address.toLowerCase() !== wallet ||
          !Number.isFinite(Date.parse(result.expires_at)) ||
          Date.parse(result.expires_at) <= Date.now()
        ) {
          throw new Error('Invalid sign-in response')
        }
        checkWallet()
        storeAuthToken(result.access_token)
      } catch (error) {
        if (sessionGeneration() === attempt) {
          updateSession({
            loginError:
              error instanceof Error ? error.message : 'Sign-in failed',
          })
        }
        throw error
      } finally {
        pendingLogin = null
        updateSession({ isLoggingIn: false })
      }
    })()
    return pendingLogin
  }, [address, chainId, status, signMessageAsync])

  return {
    token: isAuthenticated ? state.token : null,
    address: isAuthenticated && claims ? claims.sub : null,
    isAuthenticated,
    isLoggingIn: state.isLoggingIn,
    loginError: state.loginError,
    login,
    logout: clearAuthToken,
  }
}
