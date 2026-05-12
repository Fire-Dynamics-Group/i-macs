import { test, expect } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
});

test.describe("Duplicate run (slice 2)", () => {
  test("Duplicate run button on /runs/N navigates to /?from_run=N with prefilled form + banner", async ({
    page,
  }) => {
    const runId = 7;
    // Run row that diverges from the default — proves hydration is reading
    // the row, not the form's defaults.
    const sourceRun = {
      id: runId,
      uf_max: 0.95,
      duration_ms: 1200,
      error: null,
      overall_pass: true,
      checks: [],
      // Inputs (the duplicate target)
      span1: 12.5,
      span2: 8,
      numbeam: 3,
      slab_depth: 150,
      fck: 30,
      conc_type: "NW",
      mesh_type: "A393",
      deck_name: "T14",
      u_sec_size: "IPE_500",
      u_sec_fy: 355,
      ush_con: 80,
      side_a_sec: "IPE_500",
      side_a_fy: 355,
      side_a_edge: 1,
      side_a_composite: 0,
      side_a_sh_con: 80,
      side_b_sec: "IPE_500",
      side_b_fy: 355,
      side_b_edge: 0,
      side_b_composite: 1,
      side_b_sh_con: 80,
      side_c_sec: "IPE_500",
      side_c_fy: 355,
      side_c_edge: 0,
      side_c_composite: 1,
      side_c_sh_con: 80,
      side_d_sec: "IPE_500",
      side_d_fy: 355,
      side_d_edge: 1,
      side_d_composite: 0,
      side_d_sh_con: 80,
      slab_weight: 2.47,
      cold_perm: 1.2,
      lead_var_act: 5.0,
      othr_var_act: 0.0,
      lead_var_fac: 0.5,
      othr_var_fac: 0.3,
      method: "iso",
      time_limit: 60,
      qf: 750,
      window_percent: 95,
      Lc: 27,
      Bc: 18,
      Hc: 3.6,
      Hw: 1.8,
      Lw: 30,
      Bfac: 720,
      combustion_factor: 0.8,
      growth_rate: 1,
    };
    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      runs: { [String(runId)]: sourceRun },
    });

    await page.goto(`/runs/${runId}`);
    // RunDetailPage's heading confirms the route resolved before we click.
    await expect(page.getByRole("heading", { name: `Run #${runId}` })).toBeVisible();

    await page.getByRole("link", { name: /duplicate run/i }).click();

    // Now we're on the config page with the param + banner.
    await expect(page).toHaveURL(new RegExp(`/\\?from_run=${runId}$`));
    const banner = page.getByTestId("duplicate-run-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(`run #${runId}`);

    // Form is prefilled from the source run, not from defaults (span1=9).
    await expect(page.getByLabel("Span 1 (m)")).toHaveValue("12.5");
    await expect(page.getByLabel("Number of beams")).toHaveValue("3");
    await expect(page.getByLabel("Fire load qf (MJ/m²)")).toHaveValue("750");

    // Dismiss clears the param + the banner.
    await banner.getByRole("button", { name: /dismiss/i }).click();
    await expect(banner).toHaveCount(0);
    await expect(page).toHaveURL(/\/(\?.*)?$/);
    await expect(page).not.toHaveURL(/from_run=/);
  });

  test("errored runs are still duplicatable — inputs hydrate even with null outputs", async ({
    page,
  }) => {
    const runId = 11;
    const erroredRun = {
      id: runId,
      // Engine produced no outputs
      uf_max: null,
      duration_ms: null,
      error: "COMException: insufficient capacity",
      overall_pass: false,
      checks: [],
      // Inputs still recorded on insert — that's what makes retry possible
      span1: 15,
      span2: 9,
      numbeam: 4,
      slab_depth: 130,
      fck: 25,
      conc_type: "NW",
      mesh_type: "ST15C",
      deck_name: "T14",
      u_sec_size: "IPE_500",
      u_sec_fy: 355,
      ush_con: 80,
      side_a_sec: "IPE_500",
      side_a_fy: 355,
      side_a_edge: 1,
      side_a_composite: 0,
      side_a_sh_con: 80,
      side_b_sec: "IPE_500",
      side_b_fy: 355,
      side_b_edge: 0,
      side_b_composite: 1,
      side_b_sh_con: 80,
      side_c_sec: "IPE_500",
      side_c_fy: 355,
      side_c_edge: 0,
      side_c_composite: 1,
      side_c_sh_con: 80,
      side_d_sec: "IPE_500",
      side_d_fy: 355,
      side_d_edge: 1,
      side_d_composite: 0,
      side_d_sh_con: 80,
      slab_weight: 2.47,
      cold_perm: 1.2,
      lead_var_act: 5.0,
      othr_var_act: 0.0,
      lead_var_fac: 0.5,
      othr_var_fac: 0.3,
      method: "iso",
      time_limit: 60,
      qf: 511,
      window_percent: 95,
      Lc: 27,
      Bc: 18,
      Hc: 3.6,
      Hw: 1.8,
      Lw: 30,
      Bfac: 720,
      combustion_factor: 0.8,
      growth_rate: 1,
    };
    await installSidecarMock(page, {
      sidecarPort: SIDECAR_PORT,
      runs: { [String(runId)]: erroredRun },
    });

    await page.goto(`/runs/${runId}`);
    await page.getByRole("link", { name: /duplicate run/i }).click();
    await expect(page).toHaveURL(new RegExp(`/\\?from_run=${runId}$`));
    await expect(page.getByLabel("Span 1 (m)")).toHaveValue("15");
    await expect(page.getByLabel("Number of beams")).toHaveValue("4");
  });
});
