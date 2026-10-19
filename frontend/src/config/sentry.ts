import { appEnvironment } from "./runtime";
import { release, routeLabel, reportMetric } from "./telemetry";
import type { ErrorEvent } from "@sentry/react";

/** Allowlist the diagnostic shape, never try to redact arbitrary business text. */
export function sanitizeEvent(event: ErrorEvent): ErrorEvent {
  return {
    type: undefined,
    event_id: /^[0-9a-f]{32}$/.test(event.event_id ?? "")
      ? event.event_id
      : undefined,
    timestamp: event.timestamp,
    level: "error",
    platform: "javascript",
    message: "Unexpected application error (details omitted)",
    environment: appEnvironment.name,
    release: release ?? undefined,
    tags: { route: routeLabel() },
    exception: {
      values: (event.exception?.values ?? []).slice(0, 1).map((value) => ({
        type: [
          "Error",
          "TypeError",
          "RangeError",
          "ReferenceError",
          "SyntaxError",
        ].includes(value.type ?? "")
          ? value.type
          : "Error",
        value: "Details omitted to protect wallet and shipment input",
        stacktrace: {
          frames: (value.stacktrace?.frames ?? []).slice(-20).map((frame) => ({
            filename: safeFrame(frame.filename),
            lineno: frame.lineno,
            colno: frame.colno,
          })),
        },
      })),
    },
  };
}
function safeFrame(value?: string) {
  try {
    const url = new URL(value ?? "", window.location.origin);
    return url.origin === window.location.origin &&
      /^\/assets\/[\w.-]+\.js$/.test(url.pathname)
      ? url.pathname
      : undefined;
  } catch {
    return undefined;
  }
}
let capture: ((error: unknown) => void) | undefined;
export function captureClientError(error: unknown) {
  reportMetric("client_error", 1);
  capture?.(error);
}
export async function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;
  // Optional SDK is not part of startup or the build when no DSN is configured.
  const Sentry = await import("@sentry/react");
  Sentry.init({
    dsn,
    environment: appEnvironment.name,
    release: release ?? undefined,
    sendDefaultPii: false,
    defaultIntegrations: false,
    integrations: [
      Sentry.globalHandlersIntegration(),
      Sentry.browserApiErrorsIntegration(),
      Sentry.dedupeIntegration(),
    ],
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    beforeBreadcrumb: () => null,
    beforeSend: sanitizeEvent,
  });
  capture = (error) => Sentry.captureException(error);
}
