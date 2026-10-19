import { lazy, Suspense, useEffect, useState } from "react";
import { observeVitals, reportMetric } from "@/config/telemetry";
const Analytics = lazy(() => import("./PrivateAnalytics"));
export default function Diagnostics() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const stop = observeVitals();
    const reportError = () => reportMetric("client_error", 1);
    window.addEventListener("error", reportError);
    window.addEventListener("unhandledrejection", reportError);
    const idle =
      "requestIdleCallback" in window
        ? window.requestIdleCallback(() => setReady(true), { timeout: 3000 })
        : undefined;
    const timer =
      idle === undefined ? setTimeout(() => setReady(true), 2000) : undefined;
    return () => {
      stop();
      window.removeEventListener("error", reportError);
      window.removeEventListener("unhandledrejection", reportError);
      if (idle !== undefined) window.cancelIdleCallback(idle);
      if (timer !== undefined) clearTimeout(timer);
    };
  }, []);
  return ready ? (
    <Suspense fallback={null}>
      <Analytics />
    </Suspense>
  ) : null;
}
