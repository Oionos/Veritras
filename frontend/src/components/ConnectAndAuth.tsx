import { useEffect } from 'react'
import { ConnectButton } from '@rainbow-me/rainbowkit'
import { useAccount } from 'wagmi'
import { Shield, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useAuth } from '@/hooks/useAuth'

export default function ConnectAndAuth() {
  const { isConnected } = useAccount()
  const { isAuthenticated, isLoggingIn, loginError, login, logout } = useAuth()

  useEffect(() => {
    if (loginError) {
      toast.error('Sign-in failed', { description: loginError })
    }
  }, [loginError])

  const handleLogin = async () => {
    try {
      await login()
      toast.success('Signed in successfully', {
        description: 'Your wallet is now authenticated.',
      })
    } catch {
      // Error is already surfaced via loginError + toast above
    }
  }

  return (
    <div className="flex items-center gap-3">
      <ConnectButton
        showBalance={false}
        accountStatus="address"
        chainStatus="icon"
      />

      {isConnected && !isAuthenticated && (
        <button
          onClick={handleLogin}
          disabled={isLoggingIn}
          className="inline-flex items-center gap-2 rounded-lg bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-50"
        >
          {isLoggingIn ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Signing...
            </>
          ) : (
            <>
              <Shield className="h-3.5 w-3.5" />
              Sign In
            </>
          )}
        </button>
      )}

      {isConnected && isAuthenticated && (
        <button
          onClick={logout}
          title="Clear this browser's sign-in session"
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-400"
        >
          <Shield className="h-3.5 w-3.5" />
          Sign out
        </button>
      )}
    </div>
  )
}
