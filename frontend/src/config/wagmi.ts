import { connectorsForWallets } from "@rainbow-me/rainbowkit";
import {
  injectedWallet,
  safeWallet,
  rainbowWallet,
  base,
  metaMaskWallet,
  walletConnectWallet,
} from "@rainbow-me/rainbowkit/wallets";
import { sepolia, hardhat } from "wagmi/chains";
import { createConfig, http } from "wagmi";
import { deferConnector, storedWalletConnection } from "./deferredWallets";
import { appEnvironment } from "./runtime";

const projectId = import.meta.env.VITE_WALLETCONNECT_PROJECT_ID;

const local = appEnvironment.chainId === 31337;
if (import.meta.env.PROD && !local && !projectId && !import.meta.env.CI) {
  throw new Error(
    "[Veritras] VITE_WALLETCONNECT_PROJECT_ID is required in production. " +
      "Get a free Project ID at https://cloud.walletconnect.com",
  );
}

const chains = local ? ([hardhat] as const) : ([sepolia] as const);

export const hasStoredWalletConnection = storedWalletConnection(() =>
  typeof window === "undefined" ? undefined : window.localStorage,
);
let walletsEnabled = hasStoredWalletConnection;
const connectors = connectorsForWallets(
  [
    {
      groupName: local ? "Local testing" : "Popular",
      wallets: local
        ? [injectedWallet]
        : [
            safeWallet,
            rainbowWallet,
            base,
            metaMaskWallet,
            walletConnectWallet,
          ],
    },
  ],
  { appName: "Veritras", projectId: projectId || "local-testing" },
);
export const rainbowKitConfig = createConfig({
  chains,
  connectors: connectors.map((connector) =>
    deferConnector(connector, () => walletsEnabled),
  ),
  transports: {
    [hardhat.id]: http(appEnvironment.rpcUrl),
    [sepolia.id]: http(appEnvironment.rpcUrl),
  },
  ssr: false,
});

export function activateWallets() {
  walletsEnabled = true;
  // Connector methods are public Wagmi interfaces; no private config mutation.
  for (const connector of rainbowKitConfig.connectors) void connector.setup?.();
}
