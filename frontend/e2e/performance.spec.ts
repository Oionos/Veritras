import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { setupRoutes } from "./helpers/routes";

test("anonymous mobile startup keeps remote SDKs and below-fold chart deferred within its measured budget", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setupRoutes(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Track Beyond The Ordinary" }),
  ).toBeVisible();
  await page.waitForTimeout(3500); // Include idle diagnostics, not just the first paint.
  const scripts = await page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .map((e) => new URL(e.name).pathname)
      .filter((p) => p.startsWith("/assets/") && p.endsWith(".js")),
  );
  expect(
    scripts.some((p) =>
      /ShipmentVolumeChart|reown|walletconnect|recharts|web3-vendor/.test(p),
    ),
  ).toBe(false);
  const bytes = [...new Set(scripts)].reduce(
    (sum, p) => sum + gzipSync(readFileSync(`dist${p}`)).length,
    0,
  );
  expect(bytes).toBeLessThan(450000);
  await page.getByLabel("Shipment volume chart").scrollIntoViewIfNeeded();
  await expect
    .poll(async () =>
      page.evaluate(() =>
        performance
          .getEntriesByType("resource")
          .some((e) => e.name.includes("ShipmentVolumeChart")),
      ),
    )
    .toBe(true);
  await page.getByRole("button", { name: "Open navigation menu" }).click();
  await page
    .getByRole("button", { name: "Connect Wallet", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("button", { name: /MetaMask/i })).toBeVisible();
});
