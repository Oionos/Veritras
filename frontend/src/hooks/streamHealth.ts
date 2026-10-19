import { useSyncExternalStore } from "react";
export type StreamState =
  "idle" | "connecting" | "connected" | "reconnecting" | "stale";
let state: StreamState = "idle";
const listeners = new Set<() => void>();
export function setStreamHealth(value: StreamState) {
  if (state === value) return;
  state = value;
  listeners.forEach((listener) => listener());
}
export function useStreamHealth() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
    () => "idle" as StreamState,
  );
}
