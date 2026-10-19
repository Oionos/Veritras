import { appEnvironment } from "./runtime";

export const release = /^[0-9a-f]{40}$/.test(
  import.meta.env.VITE_RELEASE_COMMIT ?? "",
)
  ? import.meta.env.VITE_RELEASE_COMMIT
  : null;
export function routeLabel(path = window.location.pathname) {
  if (path === "/") return "dashboard";
  if (/^\/shipments\/[^/]+\/?$/.test(path)) return "shipment_detail";
  if (/^\/verify(?:\/[^/]+)?\/?$/.test(path)) return "verify";
  const label = path.replace(/^\//, "").replace(/\/$/, "");
  return [
    "products",
    "shipments",
    "analytics",
    "exceptions",
    "demo",
    "privacy",
    "terms",
  ].includes(label)
    ? label
    : "not_found";
}
export function safeAnalyticsUrl(value: string) {
  const url = new URL(value, window.location.origin);
  const route = routeLabel(url.pathname);
  const paths: Record<string, string> = {
    dashboard: "/",
    shipment_detail: "/shipments/:shipmentId",
    verify: "/verify/:productId",
    not_found: "/not-found",
  };
  url.pathname = paths[route] ?? `/${route}`;
  url.search = "";
  url.hash = "";
  url.protocol = window.location.protocol;
  url.host = window.location.host;
  url.username = "";
  url.password = "";
  return url.toString();
}
export type Metric =
  | "LCP"
  | "CLS"
  | "interaction_max_ms"
  | "client_error"
  | "api_error"
  | "stream_disconnected"
  | "stream_recovered";
const lastSent = new Map<string, number>();
export function reportMetric(
  metric: Metric,
  value: number,
  path = window.location.pathname,
) {
  if (!Number.isFinite(value) || value < 0 || value > 600000) return;
  const route = routeLabel(path),
    key = `${metric}:${route}`,
    now = Date.now();
  // The guided demo remains free of all live business/telemetry API calls.
  if (
    routeLabel() === "demo" ||
    route === "demo" ||
    now - (lastSent.get(key) ?? -Infinity) < 30000
  )
    return;
  lastSent.set(key, now);
  const body = JSON.stringify({
    metric,
    route,
    value,
    environment: appEnvironment.name,
    release,
  });
  // No wallet/session headers, arbitrary error text, URL, identifiers or input.
  void fetch(`${appEnvironment.apiUrl}/telemetry/browser`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    credentials: "omit",
    keepalive: true,
  }).catch(() => {});
}
export function observeVitals() {
  if (!("PerformanceObserver" in window)) return () => {};
  const observers: PerformanceObserver[] = [];
  const initialPath = window.location.pathname;
  let lcp = 0,
    cls = 0,
    maxInteraction = 0,
    sessionValue = 0,
    sessionStart = 0,
    lastShift = 0;
  const observe = (
    type: string,
    callback: (entries: PerformanceEntry[]) => void,
    extra = {},
  ) => {
    try {
      const observer = new PerformanceObserver((list) =>
        callback(list.getEntries()),
      );
      observer.observe({ type, buffered: true, ...extra });
      observers.push(observer);
    } catch {
      /* Unsupported metric is omitted. */
    }
  };
  observe("largest-contentful-paint", (entries) => {
    lcp = entries[entries.length - 1]?.startTime ?? lcp;
  });
  observe("layout-shift", (entries) => {
    for (const entry of entries) {
      const shift = entry as PerformanceEntry & {
        hadRecentInput: boolean;
        value: number;
      };
      if (shift.hadRecentInput) continue;
      if (
        shift.startTime - lastShift > 1000 ||
        shift.startTime - sessionStart > 5000
      ) {
        sessionValue = 0;
        sessionStart = shift.startTime;
      }
      sessionValue += shift.value;
      lastShift = shift.startTime;
      cls = Math.max(cls, sessionValue);
    }
  });
  observe(
    "event",
    (entries) => {
      for (const entry of entries) {
        const event = entry as PerformanceEntry & { interactionId?: number };
        if (event.interactionId)
          maxInteraction = Math.max(maxInteraction, event.duration);
      }
    },
    { durationThreshold: 40 },
  );
  const flush = () => {
    if (lcp) reportMetric("LCP", lcp, initialPath);
    reportMetric("CLS", cls, initialPath);
    if (maxInteraction)
      reportMetric("interaction_max_ms", maxInteraction, initialPath);
  };
  const hidden = () => {
    if (document.visibilityState === "hidden") flush();
  };
  document.addEventListener("visibilitychange", hidden);
  window.addEventListener("pagehide", flush);
  return () => {
    observers.forEach((o) => o.disconnect());
    document.removeEventListener("visibilitychange", hidden);
    window.removeEventListener("pagehide", flush);
  };
}
