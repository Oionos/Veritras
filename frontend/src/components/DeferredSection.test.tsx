import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import DeferredSection from "./DeferredSection";
afterEach(() => vi.unstubAllGlobals());
it("loads chart only as its reserved section approaches the viewport and disconnects", () => {
  let callback: IntersectionObserverCallback = () => {};
  const disconnect = vi.fn(),
    observe = vi.fn();
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(cb: IntersectionObserverCallback) {
        callback = cb;
      }
      observe = observe;
      disconnect = disconnect;
    },
  );
  const { unmount } = render(
    <DeferredSection label="Chart">
      <div>EXPENSIVE CHART</div>
    </DeferredSection>,
  );
  expect(screen.queryByText("EXPENSIVE CHART")).not.toBeInTheDocument();
  act(() =>
    callback(
      [{ isIntersecting: true }] as IntersectionObserverEntry[],
      {} as IntersectionObserver,
    ),
  );
  expect(screen.getByText("EXPENSIVE CHART")).toBeInTheDocument();
  unmount();
  expect(disconnect).toHaveBeenCalled();
});
it("loads without IntersectionObserver support", () => {
  vi.stubGlobal("IntersectionObserver", undefined);
  // Missing property, rather than an explicitly undefined browser constructor.
  delete (window as unknown as Record<string, unknown>).IntersectionObserver;
  render(<DeferredSection label="Chart">Accessible chart</DeferredSection>);
  expect(screen.getByText("Accessible chart")).toBeInTheDocument();
});
