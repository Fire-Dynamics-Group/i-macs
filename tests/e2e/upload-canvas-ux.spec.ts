import { test, expect } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";
const BATCH_ID = "batchaaaa1111";

test.describe("Upload Canvas UX — loading bar and single window launch", () => {
  test.beforeEach(async ({ page }) => {
    await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
    await page.addInitScript(() => {
      const opened: string[] = [];
      (window as unknown as { __openedUrls: string[] }).__openedUrls = opened;
      window.open = ((url?: string | URL) => {
        if (url) opened.push(String(url));
        return null;
      }) as typeof window.open;
    });
  });

  test("shows loading bar while creating handoff and opens browser once", async ({ page }) => {
    const completeSummary = {
      batch_id: BATCH_ID,
      created_at: "2026-04-01T12:00:00+00:00",
      mode: "lhs",
      sampling: "lhs",
      total_expected: 10000,
      run_count: 10000,
      pass_count: 9984,
      fail_count: 16,
      error_count: 0,
      varying_params: { qf: { type: "lognormal", mean: 500, cov: 0.3 } },
      fixed_params: { span1: 8 },
    };

    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      batches: { total: 1, batches: [completeSummary] },
      batchSummaries: { [BATCH_ID]: completeSummary },
      batchRuns: [
        {
          id: 1,
          batch_id: BATCH_ID,
          qf: 450,
          uf_max: 0.65,
          error: null,
          overall_pass: true,
          checks: [],
        },
      ],
      sweepEvents: [],
    });

    await page.route(`http://127.0.0.1:${SIDECAR_PORT}/api/imacs/config`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          backend_base_url: "https://backendfornextapp-production.up.railway.app",
          upload_canvas_base_url: "https://upload-canvas.vercel.app",
          has_app_key: false,
          signed_in: true,
          account_email: "engineer@firedynamicsgroup.com",
          account_name: "Test Engineer",
        }),
      }),
    );

    await page.route(
      `http://127.0.0.1:${SIDECAR_PORT}/api/imacs/jobs/${BATCH_ID}/upload-canvas-summary`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            job_id: BATCH_ID,
            imacs_job_id: "imacs-uuid-1",
            summary: null,
          }),
        }),
    );

    await page.route(
      `http://127.0.0.1:${SIDECAR_PORT}/api/imacs/upload-canvas-projects*`,
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ projects: [] }),
        }),
    );

    let releaseHandoff!: () => void;
    const handoffGate = new Promise<void>((resolve) => {
      releaseHandoff = resolve;
    });

    await page.route(
      `http://127.0.0.1:${SIDECAR_PORT}/api/imacs/jobs/${BATCH_ID}/upload-canvas-handoff`,
      async (route) => {
        await handoffGate;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            handoff_id: "handoff-e2e-1",
            url: "https://upload-canvas.vercel.app/structural-fire?handoff=handoff-e2e-1",
            expires_at: "2026-11-17T15:00:00Z",
          }),
        });
      },
    );

    await page.goto(`/batches/${BATCH_ID}`);

    const openBtn = page.getByRole("button", { name: /Open in Upload Canvas/i });
    await expect(openBtn).toBeVisible();
    await openBtn.click();

    const createBtn = page.getByRole("button", { name: /Create new project/i });
    await expect(createBtn).toBeVisible();
    await createBtn.click();

    // While handoff is in flight, loading bar and clear explanation must be visible
    await expect(page.getByRole("button", { name: /Creating handoff…/i })).toBeDisabled();
    await expect(
      page.getByRole("progressbar", { name: /Creating Upload Canvas handoff/i }),
    ).toBeVisible();
    await expect(
      page.getByText(/Rendering batch charts & uploading handoff to Upload Canvas/i),
    ).toBeVisible();

    // Release the delayed handoff response
    releaseHandoff();

    await expect(page.getByText(/Opened in browser:/i)).toBeVisible();
    await expect(
      page.getByRole("link", {
        name: /upload-canvas\.vercel\.app\/structural-fire\?handoff=handoff-e2e-1/i,
      }),
    ).toBeVisible();

    const openedUrls = await page.evaluate(
      () => (window as unknown as { __openedUrls: string[] }).__openedUrls,
    );
    expect(openedUrls).toEqual([
      "https://upload-canvas.vercel.app/structural-fire?handoff=handoff-e2e-1",
    ]);
  });
});
