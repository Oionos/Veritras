import { Suspense } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Menu, X } from 'lucide-react'
import { useState, useEffect } from 'react'
import LoadingSpinner from './ui/LoadingSpinner'
import ConnectAndAuth from './ConnectAndAuth'
import BrandLogo from './BrandLogo'
import { appEnvironment } from '@/config/runtime'
import { useChainEvents } from '@/hooks/useSSE'

const navItems = [
  { to: '/', label: 'Dashboard' },
  { to: '/products', label: 'Products' },
  { to: '/shipments', label: 'Shipments' },
  { to: '/analytics', label: 'Analytics' },
  { to: '/verify', label: 'Verify' },
]

export default function Layout() {
  useChainEvents()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 50)
    window.addEventListener('scroll', handleScroll)
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  return (
    <div className="min-h-screen bg-bg text-text">
      {/* Top Navigation - LUMINA Style */}
      <motion.header
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
        className={`fixed top-0 left-0 right-0 z-50 transition-all duration-500 ${
          scrolled
            ? 'border-b border-white/5 bg-bg/80 backdrop-blur-2xl'
            : 'bg-transparent'
        }`}
      >
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6 sm:px-12 lg:px-20">
          {/* Logo */}
          <NavLink to="/" className="group flex items-center gap-2">
            <BrandLogo className="h-9 w-9" />
            <span className="font-serif text-xl tracking-wider text-text">
              Veritras
            </span>
            {appEnvironment.name === 'testing' && (
              <span className="rounded border border-amber-400/40 px-2 py-1 text-[10px] font-medium text-amber-300">
                Testing · {appEnvironment.chainId === 31337 ? 'Local chain' : 'Sepolia'}
              </span>
            )}
          </NavLink>

          {/* Desktop Navigation - Center */}
          <nav className="hidden items-center gap-1 md:flex">
            {navItems.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `relative px-4 py-2 text-[11px] font-medium uppercase tracking-[0.15em] transition-colors duration-300 ${
                    isActive
                      ? 'text-text'
                      : 'text-muted hover:text-text'
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    {label}
                    {isActive && (
                      <motion.div
                        layoutId="nav-underline"
                        className="absolute bottom-0 left-4 right-4 h-px bg-accent"
                        transition={{ type: 'spring', bounce: 0.2, duration: 0.6 }}
                      />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>

          {/* Right side - Wallet + Mobile Menu */}
          <div className="flex items-center gap-4">
            <div className="hidden sm:block">
              <ConnectAndAuth />
            </div>
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="flex h-9 w-9 items-center justify-center text-muted transition-colors hover:text-text md:hidden"
            >
              {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>

        {/* Mobile Navigation */}
        <AnimatePresence>
          {mobileMenuOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="border-t border-white/5 bg-bg/95 backdrop-blur-2xl md:hidden"
            >
              <div className="space-y-1 px-6 py-4">
                {navItems.map(({ to, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setMobileMenuOpen(false)}
                    className={({ isActive }) =>
                      `flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-all ${
                        isActive
                          ? 'bg-white/5 text-text'
                          : 'text-muted hover:bg-white/[0.02] hover:text-text'
                      }`
                    }
                  >
                    {label}
                  </NavLink>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.header>

      {/* Main Content */}
      <main className="relative z-10">
        <Suspense
          fallback={
            <div className="flex h-[calc(100vh-5rem)] items-center justify-center">
              <LoadingSpinner size="lg" />
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>

      {/* Footer */}
      <footer className="border-t border-white/[0.04] bg-bg/60 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-col items-center gap-4 px-6 py-8 sm:flex-row sm:justify-between sm:px-12 lg:px-20">
          <p className="text-xs text-muted/60">
            &copy; 2026 Veritras. All rights reserved.
          </p>
          <nav className="flex items-center gap-6">
            <NavLink
              to="/privacy"
              className="text-xs text-muted/60 transition-colors hover:text-text"
            >
              Privacy Policy
            </NavLink>
            <NavLink
              to="/terms"
              className="text-xs text-muted/60 transition-colors hover:text-text"
            >
              Terms &amp; Conditions
            </NavLink>
          </nav>
        </div>
      </footer>
    </div>
  )
}
