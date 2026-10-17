import { getDefaultConfig } from '@rainbow-me/rainbowkit'
import { injectedWallet } from '@rainbow-me/rainbowkit/wallets'
import { sepolia, hardhat } from 'wagmi/chains'
import { http } from 'wagmi'
import { appEnvironment } from './runtime'

const projectId = import.meta.env.VITE_WALLETCONNECT_PROJECT_ID

const local = appEnvironment.chainId === 31337
if (import.meta.env.PROD && !local && !projectId && !import.meta.env.CI) {
  throw new Error(
    '[Veritras] VITE_WALLETCONNECT_PROJECT_ID is required in production. ' +
      'Get a free Project ID at https://cloud.walletconnect.com',
  )
}

const chains = local ? ([hardhat] as const) : ([sepolia] as const)

export const rainbowKitConfig = getDefaultConfig({
  appName: 'Veritras',
  projectId: projectId || 'local-testing',
  chains,
  transports: { [appEnvironment.chainId]: http(appEnvironment.rpcUrl) },
  ...(local
    ? { wallets: [{ groupName: 'Local testing', wallets: [injectedWallet] }] }
    : {}),
  ssr: false,
})
