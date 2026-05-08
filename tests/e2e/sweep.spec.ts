import { test, expect } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
});

test.describe("Sweep config + batch dashboard", () => {
  test("submits a sweep with a varying parameter and lands on the dashboard", async ({
    page,
  }) => {
    await installSidecarMock(page, { sidecarPort: SIDECAR_PORT });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();

    // Switch to sweep mode.
    await page.getByRole("button", { name: "Sweep", exact: true }).click();
    await expect(page.getByText(/Parameters to vary/i)).toBeVisible();

    // Pick "qf" to vary; enter a list.
    await page.getByRole("checkbox", { name: /Fire load qf/i }).check();
    await page
      .getByPlaceholder(/comma-separated/i)
      .first()
      .fill("400, 500");

    // Submit, expect navigation to the batch URL the mock returns.
    await page.getByRole("button", { name: "Run sweep" }).click();
    await expect(page).toHaveURL(/\/batches\/BATCH123$/);
    await expect(page.getByRole("heading", { name: /Batch BATCH123/i })).toBeVisible();
  });

  test("dashboard backfills runs and shows run rows from streamed events", async ({
    page,
  }) => {
    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      // No backfill rows; the SSE event sequence in the default mock will
      // populate the table as run_completed events arrive.
      batchRuns: [],
    });

    await page.goto("/batches/BATCH123");
    // Both run rows from the SSE event stream should land in the table.
    await expect(page.getByRole("link", { name: "#1" })).toBeVisible();
    await expect(page.getByRole("link", { name: "#2" })).toBeVisible();
    // Progress freezes at 2 of 2 once batch_done arrives.
    await expect(page.getByText(/2 of 2 complete/i)).toBeVisible();
    await expect(page.getByText(/Complete/)).toBeVisible();
  });

  test("submit payload contains the parsed varying values and fixed analysis_method", async ({
    page,
  }) => {
    await installSidecarMock(page, { sidecarPort: SIDECAR_PORT });

    const submitBodyPromise = new Promise<Record<string, unknown>>((resolve) => {
      page.on("request", (req) => {
        if (req.method() === "POST" && req.url().endsWith("/api/sweeps")) {
          resolve(JSON.parse(req.postData() ?? "{}"));
        }
      });
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();
    await page.getByRole("button", { name: "Sweep", exact: true }).click();
    await page.getByRole("checkbox", { name: /Fire load qf/i }).check();
    await page
      .getByPlaceholder(/comma-separated/i)
      .first()
      .fill("400, 500, 720");
    await page.getByRole("button", { name: "Run sweep" }).click();

    const body = await submitBodyPromise;
    expect(body).toMatchObject({
      analysis_method: expect.stringMatching(/iso|parametric/),
      sweep: { qf: [400, 500, 720] },
    });
    // The varying parameter is NOT also in the fixed dict.
    expect((body.fixed as Record<string, unknown>).qf).toBeUndefined();
  });

  test("CSV upload populates the loaded-state count + range, and submits with parsed values", async ({
    page,
  }) => {
    await installSidecarMock(page, { sidecarPort: SIDECAR_PORT });

    const submitBodyPromise = new Promise<Record<string, unknown>>((resolve) => {
      page.on("request", (req) => {
        if (req.method() === "POST" && req.url().endsWith("/api/sweeps")) {
          resolve(JSON.parse(req.postData() ?? "{}"));
        }
      });
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();
    await page.getByRole("button", { name: "Sweep", exact: true }).click();
    await page.getByRole("checkbox", { name: /Fire load qf/i }).check();

    // Upload a small CSV.
    const csv = "10, 20, 30, 40, 95";
    await page
      .getByLabel(/CSV file/i)
      .setInputFiles({ name: "qf.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });

    // Loaded-state indicator shows count + min–max.
    await expect(page.getByText(/5 values · 10–95/)).toBeVisible();

    await page.getByRole("button", { name: "Run sweep" }).click();
    const body = await submitBodyPromise;
    expect(body).toMatchObject({
      sweep: { qf: [10, 20, 30, 40, 95] },
    });
  });
});
