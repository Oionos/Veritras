import type { CreateConnectorFn } from "wagmi";

export function storedWalletConnection(
  storage: () => Pick<Storage, "getItem"> | undefined,
): boolean {
  try {
    return !!JSON.parse(storage()?.getItem("wagmi.store") ?? "null")?.state
      ?.current;
  } catch {
    return false;
  }
}

/** Wagmi eagerly calls setup, which loads remote SDKs even for anonymous readers. */
export function deferConnector(
  factory: CreateConnectorFn,
  enabled: () => boolean,
): CreateConnectorFn {
  return (config) => {
    const connector = factory(config);
    let initialized = false;
    return {
      ...connector,
      async setup() {
        if (initialized || (connector.type !== "injected" && !enabled()))
          return;
        initialized = true;
        try {
          await connector.setup?.call(this);
        } catch {
          initialized = false;
        }
      },
    };
  };
}
