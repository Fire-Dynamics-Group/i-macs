import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE_DIR = resolve(HERE, "..", "..", "macs_automation", "tests", "fixtures");
const PAIRED_QF = readFileSync(resolve(FIXTURE_DIR, "paired_qf.csv"));
const PAIRED_OPENING = readFileSync(resolve(FIXTURE_DIR, "paired_opening.csv"));

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
});

test.describe("Paired-mode sweep (#36)", () => {
  test("happy path: two equal-length CSVs zip row-wise and submit succeeds", async ({
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
    await page.getByRole("button", { name: "Sweep", exact: true }).click();
    await page.getByRole("checkbox", { name: /Fire load qf/i }).check();
    await page.getByRole("checkbox", { name: /Window opening/i }).check();

    const csvInputs = page.getByLabel(/CSV file/i);
    await csvInputs.nth(0).setInputFiles({
      name: "qf.csv",
      mimeType: "text/csv",
      buffer: PAIRED_QF,
    });
    await csvInputs.nth(1).setInputFiles({
      name: "opening.csv",
      mimeType: "text/csv",
      buffer: PAIRED_OPENING,
    });

    // Both CSVs are length 50 — total runs displays exactly 50, not 2500.
    await expect(page.getByText(/Total runs:.*50/)).toBeVisible();

    await page.getByRole("button", { name: "Run sweep" }).click();
    const body = await submitBodyPromise;
    expect(body.sampling).toBe("paired");
    expect(Array.isArray((body.sweep as Record<string, unknown>).qf)).toBe(true);
    expect(((body.sweep as { qf: number[] }).qf).length).toBe(50);
    expect(((body.sweep as { window_percent: number[] }).window_percent).length).toBe(50);
  });

  test("length mismatch blocks Run with an inline error", async ({ page }) => {
    await installSidecarMock(page, { sidecarPort: SIDECAR_PORT });

    await page.goto("/");
    await page.getByRole("button", { name: "Sweep", exact: true }).click();
    await page.getByRole("checkbox", { name: /Fire load qf/i }).check();
    await page.getByRole("checkbox", { name: /Window opening/i }).check();

    // qf gets the 50-row CSV, window_percent gets a 3-value comma-list.
    await page.getByLabel(/CSV file/i).first().setInputFiles({
      name: "qf.csv",
      mimeType: "text/csv",
      buffer: PAIRED_QF,
    });
    // Find the comma-list for window_percent (the second card).
    const lists = page.getByPlaceholder(/comma-separated/i);
    await lists.nth(1).fill("50, 80, 95");

    // Mismatch error appears on the window_percent card.
    await expect(page.getByText(/Needs 50 values \(got 3\)/i)).toBeVisible();
    // Run button is disabled.
    const runBtn = page.getByRole("button", { name: "Run sweep" });
    await expect(runBtn).toBeDisabled();
  });

  test("multi-column CSV rejected with a row-numbered error", async ({ page }) => {
    await installSidecarMock(page, { sidecarPort: SIDECAR_PORT });

    await page.goto("/");
    await page.getByRole("button", { name: "Sweep", exact: true }).click();
    await page.getByRole("checkbox", { name: /Fire load qf/i }).check();

    const badCsv = Buffer.from("10\n20, 30\n40");
    await page.getByLabel(/CSV file/i).setInputFiles({
      name: "bad.csv",
      mimeType: "text/csv",
      buffer: badCsv,
    });

    await expect(page.getByText(/Row 2.*one numeric value/i)).toBeVisible();
    const runBtn = page.getByRole("button", { name: "Run sweep" });
    await expect(runBtn).toBeDisabled();
  });
});
