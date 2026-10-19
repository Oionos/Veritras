import { render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
const metrics = vi.hoisted(() => ({
  stop: vi.fn(),
  observeVitals: vi.fn(),
  reportMetric: vi.fn(),
}));
vi.mock("@/config/telemetry", () => metrics);
vi.mock("./PrivateAnalytics", () => ({ default: () => null }));
import Diagnostics from "./Diagnostics";
afterEach(() => vi.useRealTimers());
it("reports only generic errors without a configured SDK and removes listeners on unmount", () => {
  vi.useFakeTimers();
  metrics.observeVitals.mockReturnValue(metrics.stop);
  const add = vi.spyOn(window, "addEventListener"),
    remove = vi.spyOn(window, "removeEventListener");
  const { unmount } = render(<Diagnostics />);
  const handler = add.mock.calls.find(
    ([type]) => type === "error",
  )![1] as EventListener;
  handler(
    new ErrorEvent("error", {
      message: "SECRET signature",
      error: new Error("SECRET wallet"),
    }),
  );
  expect(metrics.reportMetric).toHaveBeenCalledWith("client_error", 1);
  expect(JSON.stringify(metrics.reportMetric.mock.calls)).not.toContain(
    "SECRET",
  );
  unmount();
  expect(metrics.stop).toHaveBeenCalledOnce();
  expect(remove).toHaveBeenCalledWith("error", handler);
  expect(remove).toHaveBeenCalledWith("unhandledrejection", handler);
  add.mockRestore();
  remove.mockRestore();
});
