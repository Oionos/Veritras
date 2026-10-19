import { appEnvironment } from "@/config/runtime";
import { useEffect, useRef } from "react";
import { reportMetric } from "@/config/telemetry";
import { setStreamHealth } from "./streamHealth";
import { useQueryClient } from "@tanstack/react-query";

const API_URL = appEnvironment.apiUrl;

export function useAnalyticsEvents(
  onEvent: (type: string, data: unknown) => void,
  enabled = true,
) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return;
    let eventSource: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let watchdog: ReturnType<typeof setInterval> | null = null;
    let attempt = 0,
      lastSeen = Date.now(),
      recovering = false,
      stopped = false;
    const clear = () => {
      eventSource?.close();
      eventSource = null;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (watchdog) clearInterval(watchdog);
      reconnectTimer = null;
      watchdog = null;
    };
    const fail = (stale = false) => {
      if (stopped || document.visibilityState === "hidden") return;
      clear();
      setStreamHealth(stale ? "stale" : "reconnecting");
      if (!recovering) reportMetric("stream_disconnected", 1);
      recovering = true;
      reconnectTimer = setTimeout(
        connect,
        Math.min(30000, 5000 * 2 ** Math.min(attempt++, 3)),
      );
    };
    const touch = () => {
      lastSeen = Date.now();
      attempt = 0;
      setStreamHealth("connected");
      if (recovering) {
        reportMetric("stream_recovered", 1);
        recovering = false;
      }
    };
    const connect = () => {
      if (stopped || document.visibilityState === "hidden") return;
      clear();
      lastSeen = Date.now();
      setStreamHealth(recovering ? "reconnecting" : "connecting");
      eventSource = new EventSource(`${API_URL}/analytics/events`);
      eventSource.addEventListener("open", touch);
      eventSource.addEventListener("heartbeat", touch);
      eventSource.addEventListener("unavailable", () => fail());
      for (const type of [
        "product_created",
        "shipment_created",
        "chain_updated",
        "resync",
      ]) {
        eventSource.addEventListener(type, (event) => {
          touch();
          try {
            onEventRef.current(type, JSON.parse((event as MessageEvent).data));
          } catch {
            onEventRef.current(type, {});
          }
        });
      }
      eventSource.onerror = () => fail();
      watchdog = setInterval(() => {
        if (Date.now() - lastSeen > 35000) fail(true);
      }, 10000);
    };
    const visibility = () => {
      clear();
      if (document.visibilityState === "hidden") setStreamHealth("idle");
      else connect();
    };
    document.addEventListener("visibilitychange", visibility);
    connect();
    return () => {
      stopped = true;
      clear();
      setStreamHealth("idle");
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [enabled]);
}

/** One stream for every page; a reconnect/resync refreshes committed state. */
export function useChainEvents(enabled = true) {
  const queryClient = useQueryClient();
  useAnalyticsEvents(() => {
    for (const key of [
      "products",
      "product",
      "product-history",
      "product-transfers",
      "shipments",
      "shipment",
      "timeline",
      "verify",
      "registration",
      "metadata-history",
      "exceptions",
      "kpis",
      "anomalies",
      "bottlenecks",
      "daily-volume",
    ]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  }, enabled);
}
