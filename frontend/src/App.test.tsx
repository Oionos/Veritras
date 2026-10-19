import { describe, it, expect, vi } from 'vitest'
import type { ReactNode } from 'react'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import App from './App'

// ─── Mock heavy providers so tests stay fast and deterministic ───
vi.mock('@rainbow-me/rainbowkit', () => ({
  RainbowKitProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  darkTheme: () => ({}),
}))

vi.mock('wagmi', () => ({
  WagmiProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

vi.mock('@tanstack/react-query', () => ({
  QueryClient: class {
    defaultOptions = {}
  },
  QueryClientProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@vercel/analytics/react', () => ({
  Analytics: () => null,
}))

vi.mock('@vercel/speed-insights/react', () => ({
  SpeedInsights: () => null,
}))

vi.mock('./config/wagmi', () => ({
  rainbowKitConfig: {},
  hasStoredWalletConnection: false,
}))

vi.mock('./components/EtherealBackground', () => ({
  default: () => null,
}))

vi.mock('./components/Layout', async () => {
  const { Outlet } = await vi.importActual('react-router-dom')
  return {
    default: () => <Outlet />,
  }
})

vi.mock('./components/ui/LoadingSpinner', () => ({
  default: ({ size }: { size: string }) => <div data-testid={`spinner-${size}`}>Loading</div>,
}))

// ─── Mock heavy libraries so Dashboard renders for real without blocking tests ───
vi.mock('framer-motion', () => {
  const motionPropsToFilter = new Set([
    'initial',
    'animate',
    'whileInView',
    'viewport',
    'transition',
    'variants',
    'custom',
    'whileHover',
    'whileTap',
    'exit',
    'layout',
    'layoutId',
  ])
  const MotionProxy = new Proxy({} as Record<string, React.FC<any>>, {
    get(_, tag: string) {
      return function MotionComponent({ children, ...props }: any) {
        const cleaned = Object.fromEntries(
          Object.entries(props).filter(([key]) => !motionPropsToFilter.has(key))
        )
        return <div {...cleaned}>{children}</div>
      }
    },
  })
  return {
    motion: MotionProxy,
    MotionConfig: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    AnimatePresence: ({ children }: { children: ReactNode }) => <>{children}</>,
  }
})

vi.mock('recharts', () => ({
  // Render a shell without children to avoid jsdom SVG warnings
  AreaChart: () => <div data-testid="area-chart" />,
  Area: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
}))

vi.mock('@/hooks/useApi', () => ({
  useKPIData: () => ({ data: null, isLoading: false, error: null }),
  useProducts: () => ({ data: [], isLoading: false, error: null }),
  useDailyVolume: () => ({ data: null, isLoading: false, error: null }),
}))

vi.mock('@/hooks/useSSE', () => ({
  useAnalyticsEvents: () => {},
}))

// ─── Tests ───

describe('App', () => {
  describe('route-level code splitting (regression: LCP 10.84s)', () => {
    it('renders Dashboard content immediately on the root route without showing a Suspense fallback', () => {
      const { container } = render(<App />)

      // Hero text from PremiumHero (inside Dashboard) should be present synchronously
      expect(screen.getByText('Track')).toBeInTheDocument()
      expect(screen.getByText('Beyond')).toBeInTheDocument()
      expect(screen.getByText('The Ordinary')).toBeInTheDocument()

      // Dashboard content should also be visible immediately
      expect(screen.getByText('Supply Chain')).toBeInTheDocument()

      // Layout's Suspense fallback (spinner) must NOT appear for the eager route
      expect(
        container.querySelector('[data-testid^="spinner-"]')
      ).not.toBeInTheDocument()
    })

    it('wraps routes in Suspense with a fallback UI', () => {
      const layoutPath = resolve(import.meta.dirname, './components/Layout.tsx')
      const layoutSource = readFileSync(layoutPath, 'utf-8')

      expect(layoutSource).toContain('<Suspense')
      expect(layoutSource).toContain('fallback=')

      const appPath = resolve(import.meta.dirname, './App.tsx')
      const appSource = readFileSync(appPath, 'utf-8')
      expect(appSource).toContain('<Routes>')
      expect(appSource).toContain('<Route')
    })
  })
})
