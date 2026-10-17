import { sepolia } from 'viem/chains'

export const LIVE_API_ORIGIN = 'https://chainlens-4qvy.onrender.com'
export const LIVE_CONTRACTS = [
  '0x1f76018532d619194f6628adc186e3c86fcb5aaa',
  '0x95b09c0aed53f6b63c072f4ecac18861fcbbfb30',
]
const ZERO_ADDRESS = `0x${'0'.repeat(40)}`

export interface AppEnvironment {
  name: 'development' | 'testing' | 'production'
  apiUrl: string
  rpcUrl?: string
  chainId: 31337 | 11155111
  productRegistry: string
  shipmentTracker: string
}

export function resolveEnvironment(
  env: Record<string, string | undefined>,
  context: { production?: boolean; preview?: boolean; ci?: boolean } = {},
): AppEnvironment {
  const name =
    env.VITE_APP_ENV || (context.production ? 'production' : 'development')
  if (!['development', 'testing', 'production'].includes(name)) {
    throw new Error('VITE_APP_ENV must be development, testing, or production')
  }
  if (context.preview && name !== 'testing') {
    throw new Error(
      'Vercel Preview requires VITE_APP_ENV=testing and isolated services',
    )
  }
  const required = name === 'testing' || (name === 'production' && !context.ci)
  const apiUrl = (env.VITE_API_URL || 'http://localhost:8000').replace(
    /\/$/,
    '',
  )
  const api = new URL(apiUrl)
  if (
    !['http:', 'https:'].includes(api.protocol) ||
    api.username ||
    api.password
  ) {
    throw new Error('VITE_API_URL must be an HTTP(S) URL without credentials')
  }
  const chainId = Number(env.VITE_CHAIN_ID || '11155111')
  if (chainId !== 31337 && chainId !== 11155111) {
    throw new Error('VITE_CHAIN_ID must be 31337 or 11155111')
  }
  if (name === 'production' && chainId !== 11155111) {
    throw new Error('Production requires Sepolia; Hardhat is only for testing')
  }
  const addresses = [
    env.VITE_PRODUCT_REGISTRY_CONTRACT,
    env.VITE_SHIPMENT_TRACKER_CONTRACT,
  ]
  if (
    required &&
    (!env.VITE_API_URL ||
      addresses.some(
        (a) =>
          !a || !/^0x[\da-f]{40}$/i.test(a) || a.toLowerCase() === ZERO_ADDRESS,
      ))
  ) {
    throw new Error(
      'Explicit API URL and deployed contract addresses are required',
    )
  }
  if (
    name === 'testing' &&
    (api.origin === LIVE_API_ORIGIN ||
      addresses.some((a) => LIVE_CONTRACTS.includes(a?.toLowerCase() || '')))
  ) {
    throw new Error(
      'Testing environments cannot use the live API or live contracts',
    )
  }
  if (
    context.preview &&
    (api.protocol !== 'https:' ||
      chainId !== 11155111 ||
      ['localhost', '127.0.0.1'].includes(api.hostname))
  ) {
    throw new Error(
      'Hosted Preview requires an HTTPS testing API and Sepolia test contracts',
    )
  }
  if (
    env.VITE_RPC_URL &&
    !/^https?:$/.test(new URL(env.VITE_RPC_URL).protocol)
  ) {
    throw new Error('VITE_RPC_URL must be an HTTP(S) URL')
  }
  if (chainId === 31337 && !env.VITE_RPC_URL) {
    throw new Error('Local Hardhat testing requires VITE_RPC_URL')
  }
  return {
    name: name as AppEnvironment['name'],
    apiUrl,
    chainId,
    rpcUrl: env.VITE_RPC_URL || sepolia.rpcUrls.default.http[0],
    productRegistry: addresses[0] || ZERO_ADDRESS,
    shipmentTracker: addresses[1] || ZERO_ADDRESS,
  }
}

export function connectSources(
  env: AppEnvironment,
  development = false,
): string {
  const sources = new Set([new URL(env.apiUrl).origin])
  if (env.rpcUrl) sources.add(new URL(env.rpcUrl).origin)
  if (development) {
    // Vite's WebSocket stays on the frontend's own origin.
    sources.add('ws://localhost:*')
    sources.add('ws://127.0.0.1:*')
  }
  return [...sources].join(' ')
}
