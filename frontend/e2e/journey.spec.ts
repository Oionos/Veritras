import { test, expect } from "@playwright/test";
import jsQR from "jsqr";
import { setupRoutes, isApiOrigin } from "./helpers/routes";

test("direct public link loads without a wallet and its downloaded QR decodes to that link", async ({
  page,
}) => {
  await setupRoutes(page);
  await page.goto("/verify/PROD-001");
  await expect(
    page.getByText("Blockchain Registration Confirmed"),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Evidence timeline" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Share / QR label" }).click();
  const dialog = page.getByRole("dialog", {
    name: "Public verification label",
  });
  const image = dialog.getByRole("img", {
    name: "QR verification label for PROD-001",
  });
  await expect(image).toBeVisible();
  const pixels = await image.evaluate(async (img: HTMLImageElement) => {
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth * 2;
    canvas.height = img.naturalHeight * 2;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return {
      data: Array.from(
        ctx.getImageData(0, 0, canvas.width, canvas.height).data,
      ),
      width: canvas.width,
      height: canvas.height,
    };
  });
  expect(
    jsQR(new Uint8ClampedArray(pixels.data), pixels.width, pixels.height)?.data,
  ).toBe("http://localhost:3001/verify/PROD-001");
  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("link", { name: "Download QR label" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("veritras-PROD-001.svg");
  await dialog.getByRole("button", { name: "Close modal" }).focus();
  await page.keyboard.press("Shift+Tab");
  await expect(
    dialog.getByRole("link", { name: "Download QR label" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    dialog.getByRole("button", { name: "Close modal" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Share / QR label" }),
  ).toBeFocused();
  await page.reload();
  await expect(
    page.getByText("Blockchain Registration Confirmed"),
  ).toBeVisible();
});

test("shipment IDs open unified detail with ordered evidence and no unauthorized actions", async ({
  page,
}) => {
  await setupRoutes(page);
  await page.route(
    (url) => isApiOrigin(url) && url.pathname.endsWith("/timeline"),
    (route) =>
      route.fulfill({
        json: {
          product_id: "PROD-001",
          total: 2,
          skip: 0,
          limit: 100,
          items: ["ProductRegistered", "CustodyTransferred"].map(
            (event_type, index) => ({
              event_id: String(index),
              event_type,
              timestamp: "2026-10-19T00:00:00Z",
              block_number: 100,
              transaction_index: index,
              log_index: 0,
              transaction_hash: `0x${"a".repeat(64)}`,
              block_hash: `0x${"b".repeat(64)}`,
              from_address: index ? "Manufacturer" : null,
              to_address: index ? "Carrier" : null,
            }),
          ),
        },
      }),
  );
  await page.goto("/shipments");
  await page.getByRole("link", { name: "SHP-001", exact: true }).click();
  await expect(page).toHaveURL(/\/shipments\/SHP-001$/);
  await expect(
    page.getByRole("heading", { name: "Shipment SHP-001" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Shipment summary" }),
  ).toContainText("Shanghai → Rotterdam");
  const timeline = page.getByRole("region", { name: "Evidence timeline" });
  await expect(timeline.getByRole("listitem")).toHaveCount(2);
  await expect(timeline.getByRole("listitem").nth(0)).toContainText(
    "Product registered",
  );
  await expect(timeline.getByRole("listitem").nth(1)).toContainText(
    "Custody transferred",
  );
  await expect(
    page.getByRole("button", { name: "Record checkpoint", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Transfer custody", exact: true }),
  ).toHaveCount(0);
});

test("mobile navigation exposes wallet connection, sign-in guidance and Escape handling", async ({
  page,
}) => {
  await setupRoutes(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/demo");
  const menu = page.getByRole("button", { name: "Open navigation menu" });
  await menu.click();
  const nav = page.getByRole("navigation", { name: "Mobile navigation" });
  await expect(
    nav.getByRole("button", { name: /connect wallet/i }),
  ).toBeVisible();
  await nav.getByRole("button", { name: /connect wallet/i }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("simulated demo makes no business API requests and visits every step", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (isApiOrigin(new URL(request.url()))) requests.push(request.url());
  });
  await page.goto("/demo");
  await expect(page.getByText("Guided demo · Simulated data")).toBeVisible();
  for (let step = 0; step < 5; step++)
    await page.getByRole("button", { name: "Next step" }).click();
  await expect(
    page.getByRole("heading", { name: "Share the evidence" }),
  ).toBeVisible();
  await expect(page).toHaveTitle("Veritras — Guided Demo");
  expect(
    await page.locator('meta[name="robots"]').getAttribute("content"),
  ).toBe("noindex, nofollow");
  expect(requests).toEqual([]);
});

test("missing routes offer usable recovery links", async ({ page }) => {
  await setupRoutes(page);
  await page.goto("/does-not-exist");
  await expect(
    page.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Verify a product", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Verify Registration" }),
  ).toBeVisible();
});
