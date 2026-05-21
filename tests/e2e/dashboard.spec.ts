import { test, expect } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
});

test.describe("Runs dashboard (slice 1)", () => {
  test("renders stat cards and the batches list at /runs", async ({ page }) => {
    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      stats: {
        total: 5, successful: 4, errors: 1, pass_count: 3, fail_count: 1,
      },
      batches: {
        total: 1,
        batches: [
          {
            batch_id: "abc12345deadbeef",
            created_at: "2026-04-01T12:00:00+00:00",
            mode: "sweep",
            total_expected: 4,
            run_count: 4,
            pass_count: 3,
            fail_count: 1,
            error_count: 0,
            varying_params: { qf: [400, 500, 600] },
            fixed_params: { span1: 9 },
          },
        ],
      },
      ungrouped: { runs: [], total: 0 },
    });

    await page.goto("/runs");
    await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
    // Stat cards land in their own grid section, not in the batches table.
    // 'Total' card shows 5 and isn't ambiguous; 'Success rate' = 60% (3/5).
    await expect(page.getByText("5", { exact: true })).toBeVisible();
    await expect(page.getByText(/60%/)).toBeVisible();

    // Varying-param chip surfaces what was swept.
    await expect(page.getByText("qf").first()).toBeVisible();
  });

  test("clicking a batch row lands on /batches/:id with the analytical view", async ({ page }) => {
    const batchId = "abc12345deadbeef";
    const summary = {
      batch_id: batchId,
      created_at: "2026-04-01T12:00:00+00:00",
      mode: "sweep",
      sampling: "paired",
      total_expected: 2,
      run_count: 2,
      pass_count: 2,
      fail_count: 0,
      error_count: 0,
      varying_params: { qf: [400, 500] },
      fixed_params: { span1: 9 },
    };
    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      stats: { total: 2, successful: 2, errors: 0, pass_count: 2, fail_count: 0 },
      batches: { total: 1, batches: [summary] },
      batchSummaries: { [batchId]: summary },
      batchRuns: [
        { id: 1, batch_id: batchId, qf: 400, uf_max: 0.4, error: null, overall_pass: true, checks: [] },
        { id: 2, batch_id: batchId, qf: 500, uf_max: 0.6, error: null, overall_pass: true, checks: [] },
      ],
      // No SSE events — the analytical view doesn't need them; the
      // backfill is what populates the table.
      sweepEvents: [],
    });

    await page.goto("/runs");
    // Click the batch row — the link uses the first 8 chars of the id.
    await page.getByRole("link", { name: batchId.slice(0, 8) }).click();
    await expect(page).toHaveURL(new RegExp(`/batches/${batchId}$`));
    // Analytical-view action buttons confirm the right branch rendered.
    await expect(page.getByRole("link", { name: /download report/i })).toBeVisible();
    await expect(page.getByRole("link", { name: /rerun batch/i })).toBeVisible();
  });

  test("empty state shows a Start your first run CTA when nothing exists", async ({ page }) => {
    await installSidecarMock(page, { sidecarPort: SIDECAR_PORT });
    await page.goto("/runs");
    await expect(page.getByText(/no runs yet/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /start your first run/i }))
      .toHaveAttribute("href", "/");
  });
});
