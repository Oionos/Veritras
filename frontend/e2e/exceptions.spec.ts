import { test, expect } from "@playwright/test";
import { setupRoutes, isApiOrigin } from "./helpers/routes";

test("exceptions explain disabled evaluation without declaring shipments on time", async ({
  page,
}) => {
  await setupRoutes(page);
  await page.goto("/exceptions");
  await expect(
    page.getByRole("heading", { name: "Shipment exceptions" }),
  ).toBeVisible();
  await expect(page.getByText(/Evaluation paused/)).toBeVisible();
  await expect(page.getByText(/timeliness is not established/)).toBeVisible();
  await expect(page).toHaveTitle("Veritras — Shipment Exceptions");
  await page.getByLabel("Show observations").selectOption("resolved");
  await expect(page.getByText(/No stored observations/)).toBeVisible();
});

test("mobile exception list links to evidence and exposes resolved history", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setupRoutes(page);
  await page.route(
    (url) =>
      isApiOrigin(url) && url.pathname.replace(/\/$/, "") === "/exceptions",
    (route) => {
      const resolved =
        new URL(route.request().url()).searchParams.get("state") === "resolved";
      return route.fulfill({
        json: {
          total: 1,
          evaluation: {
            paused: false,
            evaluated_at: "2026-10-19T01:00:00Z",
            block_number: 100,
            uncertain_shipments: 0,
          },
          items: [
            {
              id: resolved ? "old" : "current",
              shipment_id: "SHIP-001",
              kind: "custody_followup",
              triggered_at: "2026-10-19T00:00:00Z",
              last_observed_at: "2026-10-19T01:00:00Z",
              acknowledged_at: null,
              resolved_at: resolved ? "2026-10-19T02:00:00Z" : null,
              resolution: resolved ? "condition_cleared" : null,
              evidence: {
                threshold_hours: 6,
                receiving_handler: "0x5555555555555555555555555555555555555555",
              },
            },
          ],
        },
      });
    },
  );
  await page.goto("/exceptions");
  await expect(page.getByText(/Custody already transferred/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Acknowledge occurrence" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: /View shipment evidence/ }),
  ).toHaveAttribute("href", "/shipments/SHIP-001");
  await page.getByLabel("Show observations").selectOption("resolved");
  await expect(page.getByText(/Resolved .*condition cleared/)).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: /View shipment evidence/ }).click();
  await expect(
    page.getByRole("heading", { name: "Shipment SHIP-001", exact: true }),
  ).toBeVisible();
});

test("exception read failure supports retry", async ({ page }) => {
  await setupRoutes(page);
  let failed = true;
  await page.route(
    (url) =>
      isApiOrigin(url) && url.pathname.replace(/\/$/, "") === "/exceptions",
    (route) =>
      failed
        ? route.fulfill({ status: 503, json: { detail: "unavailable" } })
        : route.fulfill({
            json: {
              items: [],
              total: 0,
              evaluation: { paused: true, reason: "indexing_disabled" },
            },
          }),
  );
  await page.goto("/exceptions");
  await expect(
    page.getByRole("button", { name: "Retry exceptions" }),
  ).toBeVisible({ timeout: 20000 });
  failed = false;
  await page.getByRole("button", { name: "Retry exceptions" }).click();
  await expect(page.getByText(/No stored observations/)).toBeVisible();
});
