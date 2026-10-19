import { afterEach, describe, expect, it, vi } from "vitest";
import { sanitizeEvent } from "./sentry";
import { reportMetric, routeLabel, safeAnalyticsUrl } from "./telemetry";
import { deferConnector, storedWalletConnection } from "./deferredWallets";
import type { CreateConnectorFn } from "wagmi";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState({}, "", "/");
});
describe("private diagnostics", () => {
  it("uses route templates and drops identifiers, credentials, query and fragment", () => {
    expect(routeLabel("/shipments/SECRET")).toBe("shipment_detail");
    expect(safeAnalyticsUrl("javascript:SECRET")).toBe(
      `${window.location.origin}/not-found`,
    );
    expect(
      safeAnalyticsUrl(
        "https://user:SECRET@private.example/verify/SECRET?signature=SECRET#SECRET",
      ),
    ).toBe(`${window.location.origin}/verify/:productId`);
    expect(safeAnalyticsUrl("/unknown-SECRET?token=SECRET")).toBe(
      `${window.location.origin}/not-found`,
    );
  });
  it("allowlists errors without wallet, token, note, request or arbitrary context", () => {
    const safe = sanitizeEvent({
      message: "SECRET",
      user: { id: "SECRET" },
      request: { url: "SECRET" },
      extra: { note: "SECRET" },
      breadcrumbs: [{ message: "SECRET" }],
      exception: {
        values: [
          {
            type: "SECRET",
            value: "SECRET",
            stacktrace: {
              frames: [
                {
                  filename: "https://private.example/SECRET.js",
                  vars: { token: "SECRET" },
                },
                {
                  filename: `${window.location.origin}/assets/index-abc.js?token=SECRET`,
                  lineno: 12,
                },
              ],
            },
          },
        ],
      },
    });
    expect(JSON.stringify(safe)).not.toContain("SECRET");
    expect(safe.exception?.values?.[0].stacktrace?.frames?.[1].filename).toBe(
      "/assets/index-abc.js",
    );
    expect(safe).not.toHaveProperty("user");
    expect(safe).not.toHaveProperty("breadcrumbs");
  });
  it("sends bounded aggregate values without authentication and suppresses demo", () => {
    const fetch = vi.fn().mockResolvedValue({});
    vi.stubGlobal("fetch", fetch);
    window.history.replaceState({}, "", "/shipments/PRIVATE-ID?token=PRIVATE");
    reportMetric("api_error", 1);
    reportMetric("api_error", 1);
    reportMetric("LCP", NaN);
    expect(fetch).toHaveBeenCalledTimes(1);
    const options = fetch.mock.calls[0][1];
    expect(options.credentials).toBe("omit");
    expect(options.headers).toEqual({ "Content-Type": "application/json" });
    expect(options.body).not.toContain("PRIVATE");
    expect(JSON.parse(options.body).route).toBe("shipment_detail");
    window.history.replaceState({}, "", "/demo");
    reportMetric("client_error", 1);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
describe("wallet startup boundaries", () => {
  it("handles missing, corrupt and inaccessible storage and restores existing connections", () => {
    expect(storedWalletConnection(() => undefined)).toBe(false);
    expect(
      storedWalletConnection(() => {
        throw Error("blocked");
      }),
    ).toBe(false);
    expect(storedWalletConnection(() => ({ getItem: () => "{bad" }))).toBe(
      false,
    );
    expect(
      storedWalletConnection(() => ({
        getItem: () => JSON.stringify({ state: { current: "connection" } }),
      })),
    ).toBe(true);
  });
  it("defers remote SDK setup until intent, runs once, and initializes injected wallets immediately", async () => {
    let enabled = false;
    const setup = vi.fn();
    const factory = (() => ({
      type: "walletConnect",
      setup,
    })) as unknown as CreateConnectorFn;
    const connector = deferConnector(factory, () => enabled)({} as never);
    await connector.setup?.();
    expect(setup).not.toHaveBeenCalled();
    enabled = true;
    await connector.setup?.();
    await connector.setup?.();
    expect(setup).toHaveBeenCalledOnce();
    const injected = deferConnector(
      (() => ({ type: "injected", setup })) as unknown as CreateConnectorFn,
      () => false,
    )({} as never);
    await injected.setup?.();
    expect(setup).toHaveBeenCalledTimes(2);
  });
  it("permits retry after a failed setup", async () => {
    const setup = vi
      .fn()
      .mockRejectedValueOnce(Error("offline"))
      .mockResolvedValue(undefined);
    const connector = deferConnector(
      (() => ({
        type: "walletConnect",
        setup,
      })) as unknown as CreateConnectorFn,
      () => true,
    )({} as never);
    await connector.setup?.();
    await connector.setup?.();
    expect(setup).toHaveBeenCalledTimes(2);
  });
});
