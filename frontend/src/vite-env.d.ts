/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_RELEASE_COMMIT: string
  readonly VITE_APP_ENV: string
  readonly VITE_CHAIN_ID: string
  readonly VITE_RPC_URL: string
  readonly VITE_VERCEL_ENV: string
  readonly VITE_API_URL: string
  readonly VITE_WALLETCONNECT_PROJECT_ID: string
  readonly VITE_PRODUCT_REGISTRY_CONTRACT: string
  readonly VITE_SHIPMENT_TRACKER_CONTRACT: string
  readonly VITE_SENTRY_DSN: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  requestIdleCallback: (
    callback: IdleRequestCallback,
    options?: IdleRequestOptions
  ) => number
  cancelIdleCallback: (handle: number) => void
}
