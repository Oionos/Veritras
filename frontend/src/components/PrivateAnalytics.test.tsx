import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
const hooks = vi.hoisted(() => ({ analytics: vi.fn(), speed: vi.fn() }));
vi.mock("@vercel/analytics/react", () => ({
  Analytics: (props: unknown) => {
    hooks.analytics(props);
    return null;
  },
}));
vi.mock("@vercel/speed-insights/react", () => ({
  SpeedInsights: (props: unknown) => {
    hooks.speed(props);
    return null;
  },
}));
import PrivateAnalytics from "./PrivateAnalytics";
it("removes identifiers from analytics URLs and speed insight routes", () => {
  render(<PrivateAnalytics />);
  const event = {
    type: "vital",
    url: "/shipments/SECRET?token=SECRET#SECRET",
    route: "/shipments/SECRET",
  };
  const speed = hooks.speed.mock.calls[0][0].beforeSend(event);
  expect(JSON.stringify(speed)).not.toContain("SECRET");
  expect(speed.route).toBe("/shipments/:shipmentId");
  const analytics = hooks.analytics.mock.calls[0][0].beforeSend({
    type: "pageview",
    url: "/verify/SECRET?signature=SECRET",
  });
  expect(JSON.stringify(analytics)).not.toContain("SECRET");
});
