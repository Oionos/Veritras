import { MotionConfig } from 'framer-motion'
import { lazy, useMemo } from 'react'
import { RainbowKitProvider, darkTheme } from '@rainbow-me/rainbowkit'
import '@rainbow-me/rainbowkit/styles.css'
import { WagmiProvider } from 'wagmi'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Diagnostics from './components/Diagnostics'
import { Toaster } from 'sonner'
import { rainbowKitConfig, hasStoredWalletConnection } from './config/wagmi'
import EtherealBackground from './components/EtherealBackground'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'

const ShipmentDetail = lazy(() => import('./pages/ShipmentDetail'))
const Exceptions = lazy(() => import('./pages/Exceptions'))
const Demo = lazy(() => import('./pages/Demo'))
const NotFound = lazy(() => import('./pages/NotFound'))
const Products = lazy(() => import('./pages/Products'))
const Shipments = lazy(() => import('./pages/Shipments'))
const AnalyticsPage = lazy(() => import('./pages/Analytics'))
const Verify = lazy(() => import('./pages/Verify'))
const Privacy = lazy(() => import('./pages/Privacy'))
const Terms = lazy(() => import('./pages/Terms'))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,
      refetchOnWindowFocus: false,
    },
  },
})

function App() {
  const rainbowTheme = useMemo(
    () =>
      darkTheme({
        accentColor: '#c8f060',
        accentColorForeground: '#0d0d0d',
        borderRadius: 'medium',
        fontStack: 'system',
      }),
    []
  )

  return (
    <WagmiProvider config={rainbowKitConfig} reconnectOnMount={hasStoredWalletConnection}>
      <QueryClientProvider client={queryClient}>
        <RainbowKitProvider theme={rainbowTheme}>
          <MotionConfig reducedMotion="user"><BrowserRouter>
            <EtherealBackground />
            <Diagnostics />
            <Toaster position="top-right" richColors />
            <ErrorBoundary>
              <Routes>
                <Route path="/index.html" element={<Navigate to="/" replace />} />
                <Route element={<Layout />}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/products" element={<Products />} />
                  <Route path="/shipments" element={<Shipments />} />
                  <Route path="/shipments/:shipmentId" element={<ShipmentDetail />} />
                  <Route path="/analytics" element={<AnalyticsPage />} />
                  <Route path="/exceptions" element={<Exceptions />} />
                  <Route path="/verify" element={<Verify />} />
                  <Route path="/verify/:productId" element={<Verify />} />
                  <Route path="/demo" element={<Demo />} />
                  <Route path="*" element={<NotFound />} />
                  <Route path="/privacy" element={<Privacy />} />
                  <Route path="/terms" element={<Terms />} />
                </Route>
              </Routes>
            </ErrorBoundary>
          </BrowserRouter></MotionConfig>
        </RainbowKitProvider>
      </QueryClientProvider>
    </WagmiProvider>
  )
}

export default App
