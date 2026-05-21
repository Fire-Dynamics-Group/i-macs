import { test, expect } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
});

const BATCH_ID = "batchaaaa1111";

const COMPLETE_SUMMARY = {
  batch_id: BATCH_ID,
  created_at: "2026-04-01T12:00:00+00:00",
  mode: "lhs",
  sampling: "lhs",
  total_expected: 12,
  run_count: 12,
  pass_count: 10,
  fail_count: 2,
  error_count: 0,
  varying_params: { qf: { type: "lognormal", mean: 500, cov: 0.3 }, window_percent: {} },
  fixed_params: { span1: 9 },
};

function makeRuns(n: number) {
  const runs = [];
  for (let i = 0; i < n; i++) {
    runs.push({
      id: i + 1,
      batch_id: BATCH_ID,
      qf: 400 + i * 30,
      window_percent: 30 + i * 5,
      uf_max: i < 10 ? 0.4 + i * 0.05 : 1.1 + (i - 10) * 0.1,
      error: null,
      overall_pass: i < 10,
      checks: [],
    });
  }
  return runs;
}

function makeDistribution() {
  const time = [0, 5, 10, 15, 20];
  const spaghetti = [];
  for (let r = 0; r < 5; r++) {
    spaghetti.push({
      run_id: r + 1,
      points: time.map((t) => [t, 700 - t * 5 + r * 10] as [number, number]),
    });
  }
  return {
    average: time.map((t) => [t, 700 - t * 5] as [number, number]),
    spaghetti,
    factored_hot_min: 5.6,
    factored_hot_max: 5.6,
  };
}

test.describe("Batch detail — MACS+ Monte Carlo Summary (4 charts)", () => {
  test("renders the 4 chart containers and the expected legend titles", async ({
    page,
  }) => {
    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      batches: { total: 1, batches: [COMPLETE_SUMMARY] },
      batchSummaries: { [BATCH_ID]: COMPLETE_SUMMARY },
      batchRuns: makeRuns(12),
      sweepEvents: [], // analytical view doesn't need live events
      distribution: {
        total_plate_capacity: makeDistribution(),
        lofl_temp: { ...makeDistribution(), factored_hot_min: null, factored_hot_max: null },
        mesh_temp: { ...makeDistribution(), factored_hot_min: null, factored_hot_max: null },
      },
    });

    await page.goto(`/batches/${BATCH_ID}`);
    // Confirm analytical view rendered (Rerun batch only on this branch).
    await expect(page.getByRole("link", { name: /rerun batch/i })).toBeVisible();

    // Chart 1: MACS+ scatter (qf vs window_percent — both vary in this batch).
    await expect(page.locator("[data-chart='macs-scatter']")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Fire Load Density vs Glazing Breakage/i }),
    ).toBeVisible();

    // Chart 2: Total Capacity Distribution.
    await expect(
      page.locator("[data-chart='total_plate_capacity']"),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Total Capacity Distribution/i }),
    ).toBeVisible();

    // Chart 3: Unprotected Beam Temperature Distribution.
    await expect(page.locator("[data-chart='lofl_temp']")).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /Unprotected Beam Temperature Distribution/i,
      }),
    ).toBeVisible();

    // Chart 4: Reinforcement Bar Temperature Distribution.
    await expect(page.locator("[data-chart='mesh_temp']")).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /Reinforcement Bar Temperature Distribution/i,
      }),
    ).toBeVisible();
  });

  test("hides the MACS+ scatter when neither qf nor window_percent varies", async ({
    page,
  }) => {
    const flatSummary = {
      ...COMPLETE_SUMMARY,
      varying_params: { span1: [9, 10, 12] },
    };
    // Every run has identical qf + window_percent; only span1 changes.
    const flatRuns = makeRuns(12).map((r, i) => ({
      ...r,
      qf: 500,
      window_percent: 50,
      span1: 9 + Math.floor(i / 4),
    }));

    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      batches: { total: 1, batches: [flatSummary] },
      batchSummaries: { [BATCH_ID]: flatSummary },
      batchRuns: flatRuns,
      sweepEvents: [],
      distribution: {
        total_plate_capacity: makeDistribution(),
        lofl_temp: makeDistribution(),
        mesh_temp: makeDistribution(),
      },
    });

    await page.goto(`/batches/${BATCH_ID}`);
    await expect(page.getByRole("link", { name: /rerun batch/i })).toBeVisible();

    // MACS+ scatter is hidden.
    await expect(page.locator("[data-chart='macs-scatter']")).toHaveCount(0);

    // The three distribution charts still render.
    await expect(page.locator("[data-chart='total_plate_capacity']")).toBeVisible();
    await expect(page.locator("[data-chart='lofl_temp']")).toBeVisible();
    await expect(page.locator("[data-chart='mesh_temp']")).toBeVisible();
  });

  test("shows 'No successful runs' placeholder when the batch has zero successful runs", async ({
    page,
  }) => {
    const erroredSummary = {
      ...COMPLETE_SUMMARY,
      pass_count: 0,
      fail_count: 0,
      error_count: 12,
    };

    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      batches: { total: 1, batches: [erroredSummary] },
      batchSummaries: { [BATCH_ID]: erroredSummary },
      // Errored runs only — no time series, so detectVarying won't trigger
      // the scatter axes either; placeholder appears on all 3 distributions.
      batchRuns: makeRuns(12).map((r) => ({
        ...r,
        qf: null,
        window_percent: null,
        uf_max: null,
        error: "COM error",
        overall_pass: false,
      })),
      sweepEvents: [],
      // Default distribution payload (empty arrays) → placeholder branch.
    });

    await page.goto(`/batches/${BATCH_ID}`);
    await expect(page.getByRole("link", { name: /rerun batch/i })).toBeVisible();

    // The three distribution chart sections are present, each showing the
    // empty-state placeholder.
    const placeholders = page.getByText(/No successful runs in this batch/i);
    await expect(placeholders).toHaveCount(3);
  });
});
