import { test, expect, type Page } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

/**
 * The results download: mode selector, progress feedback, error surfacing.
 *
 * Worth covering here rather than only in vitest because the behaviour depends
 * on real browser plumbing — Content-Disposition parsing, Blob save, and the
 * download event — none of which jsdom models.
 *
 * CORS is real here: the page is cross-origin to the sidecar, and a fulfilled
 * route still goes through the browser's CORS checks. Drop
 * Access-Control-Expose-Headers from the mock below and the filename assertion
 * fails exactly as it did in the live app — so the mock must keep mirroring the
 * sidecar's headers. That the *sidecar* actually sends them is asserted
 * separately by test_app.py::TestDownloadFilenameIsReadable.
 */

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";
const BATCH_ID = "batchdddd4444";

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
});

const COMPLETE_SUMMARY = {
  batch_id: BATCH_ID,
  created_at: "2026-04-01T12:00:00+00:00",
  mode: "lhs",
  sampling: "lhs",
  name: "Unit 7",
  total_expected: 4,
  run_count: 4,
  pass_count: 4,
  fail_count: 0,
  error_count: 0,
  varying_params: { qf: {}, window_percent: {} },
  fixed_params: { span1: 9 },
};

function makeRuns(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    batch_id: BATCH_ID,
    qf: 400 + i * 30,
    window_percent: 30 + i * 5,
    uf_max: 0.4 + i * 0.05,
    error: null,
    overall_pass: true,
    checks: [],
  }));
}

function makeDistribution() {
  const time = [0, 5, 10, 15, 20];
  return {
    average: time.map((t) => [t, 700 - t * 5] as [number, number]),
    spaghetti: [
      { run_id: 1, points: time.map((t) => [t, 700 - t * 5] as [number, number]) },
    ],
    factored_hot_min: 5.6,
    factored_hot_max: 5.6,
  };
}

async function showBatch(page: Page) {
  await installSidecarMock(page, {
    sidecarPort: SIDECAR_PORT,
    batches: { total: 1, batches: [COMPLETE_SUMMARY] },
    batchSummaries: { [BATCH_ID]: COMPLETE_SUMMARY },
    batchRuns: makeRuns(4),
    sweepEvents: [],
    distribution: {
      total_plate_capacity: makeDistribution(),
      lofl_temp: makeDistribution(),
      mesh_temp: makeDistribution(),
    },
  });
}

/** Stand in for the export endpoint. Registered after the sidecar mock so it wins. */
async function mockExport(
  page: Page,
  opts: { delayMs?: number; status?: number; filename?: string; detail?: string } = {},
) {
  const seen: string[] = [];
  await page.route("**/api/report/zip**", async (route) => {
    seen.push(route.request().url());
    if (opts.delayMs) {
      await new Promise((r) => setTimeout(r, opts.delayMs));
    }
    if (opts.status && opts.status >= 400) {
      await route.fulfill({
        status: opts.status,
        contentType: "application/json",
        body: JSON.stringify({ detail: opts.detail ?? "boom" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/zip",
      headers: {
        "Content-Disposition": `attachment; filename="${opts.filename ?? "macs_data_Unit_7.zip"}"`,
        // Mirrors the sidecar's CORS config. The page is cross-origin to the
        // sidecar, so without this the browser hides Content-Disposition and
        // the client silently falls back to a generated filename.
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Disposition",
      },
      body: Buffer.from("PK\u0003\u0004stub-zip-payload"),
    });
  });
  return seen;
}

const downloadButton = (page: Page) =>
  page.getByRole("button", { name: /download|preparing/i });

test.describe("Batch detail — results download", () => {
  test("shows progress while the export is being built, then clears", async ({
    page,
  }) => {
    await showBatch(page);
    await mockExport(page, { delayMs: 1500 });
    await page.goto(`/batches/${BATCH_ID}`);

    const button = downloadButton(page);
    await expect(button).toBeVisible();

    const download = page.waitForEvent("download");
    await button.click();

    // A 10k chart export takes ~25s server-side, so the wait must be visible.
    await expect(page.getByRole("status")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /preparing/i }),
    ).toBeDisabled();
    // The mode selector is locked too, so the request can't change mid-flight.
    await expect(page.getByLabel(/what to download/i)).toBeDisabled();

    await download;
    await expect(page.getByRole("status")).toBeHidden();
    await expect(page.getByRole("button", { name: /^download$/i })).toBeEnabled();
  });

  test("saves under the name the sidecar chose", async ({ page }) => {
    await showBatch(page);
    await mockExport(page, { filename: "macs_data_charts_Unit_7.zip" });
    await page.goto(`/batches/${BATCH_ID}`);

    const download = page.waitForEvent("download");
    await downloadButton(page).click();

    expect((await download).suggestedFilename()).toBe(
      "macs_data_charts_Unit_7.zip",
    );

    // The webview saves with no download bar of its own, so the page has to
    // confirm it — otherwise the spinner vanishes and nothing seems to happen.
    await expect(page.getByTestId("download-saved")).toContainText(
      "macs_data_charts_Unit_7.zip",
    );
  });

  test.describe("mode selector", () => {
    for (const [mode, expected] of [
      ["data", "include=data"],
      ["charts", "include=charts"],
      ["both", "include=both"],
    ] as const) {
      test(`requests ${mode}`, async ({ page }) => {
        await showBatch(page);
        const seen = await mockExport(page);
        await page.goto(`/batches/${BATCH_ID}`);

        await expect(downloadButton(page)).toBeVisible();
        await page.getByLabel(/what to download/i).selectOption(mode);

        const download = page.waitForEvent("download");
        await downloadButton(page).click();
        await download;

        expect(seen.some((u) => u.includes(expected))).toBe(true);
      });
    }
  });

  test("surfaces a sidecar failure in the page", async ({ page }) => {
    await showBatch(page);
    await mockExport(page, {
      status: 500,
      detail: "No module named 'matplotlib'",
    });
    await page.goto(`/batches/${BATCH_ID}`);

    await downloadButton(page).click();

    // The user must not be handed a raw JSON body, which is what a plain
    // <a href> download does on error.
    await expect(page.getByRole("alert")).toContainText(
      "No module named 'matplotlib'",
    );
    await expect(page.getByRole("button", { name: /^download$/i })).toBeEnabled();
  });

  test("a retry clears the previous error", async ({ page }) => {
    await showBatch(page);
    await mockExport(page, { status: 500, detail: "transient" });
    await page.goto(`/batches/${BATCH_ID}`);

    await downloadButton(page).click();
    await expect(page.getByRole("alert")).toBeVisible();

    await mockExport(page); // now succeeds
    const download = page.waitForEvent("download");
    await downloadButton(page).click();
    await download;

    await expect(page.getByRole("alert")).toBeHidden();
  });
});
