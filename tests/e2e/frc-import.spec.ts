import path from "node:path";
import { fileURLToPath } from "node:url";

import { test, expect } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.resolve(
  __dirname,
  "..",
  "..",
  "macs_automation",
  "tests",
  "fixtures",
);

// Catalogue mirrors the IDs referenced by sample.frc so the mapper considers
// them known. Without UB_457x152x60 / UB_533x210x101 / UB_610x229x101 / T10 /
// A193 in scope, every section/deck/mesh would be flagged unknown.
const REF_DATA = {
  sections: {
    UB: [
      { id: "UB_457x152x60", name: "UB 457 x 152 x 60", h: 454.6, b: 152.9 },
      { id: "UB_533x210x101", name: "UB 533 x 210 x 101", h: 536.7, b: 210 },
      { id: "UB_610x229x101", name: "UB 610 x 229 x 101", h: 602.6, b: 227.6 },
      { id: "IPE_500", name: "IPE 500", h: 500, b: 200 },
    ],
  },
  decks: { T10: { name: "Metflor 60", deck_type: "T", deck_depth: 60 } },
  meshes: { A193: { name: "A193", mainArea: 193, transArea: 193 } },
  defaults: {
    span1: 9,
    span2: 9,
    numbeam: 2,
    slab_depth: 130,
    fck: 25,
    conc_type: "NW",
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
    DeckId: "T10",
    mesh_type: "A193",
    uSecSize: "IPE_500",
    fy5: "355",
    ush_con: 80,
    SideASecSize: "IPE_500",
    fy1: "355",
    SideAEdgeFlag: 1,
    SideACompoFlag: 0,
    SideAsh_con: 80,
    SideBSecSize: "IPE_500",
    fy2: "355",
    SideBEdgeFlag: 0,
    SideBCompoFlag: 1,
    SideBsh_con: 80,
    SideCSecSize: "IPE_500",
    fy3: "355",
    SideCEdgeFlag: 0,
    SideCCompoFlag: 1,
    SideCsh_con: 80,
    SideDSecSize: "IPE_500",
    fy4: "355",
    SideDEdgeFlag: 1,
    SideDCompoFlag: 0,
    SideDsh_con: 80,
  },
  occupancy_presets: [{ name: "Office", mean: 420, type: "gumbel", cov: 0.3 }],
};

// Mirrors what the Python parser would return for sample.frc. The vitest
// unit suite covers the engine-key → form-key mapping; this hard-coded
// fixture is what the e2e mocks /api/import-frc with so we don't need a
// real sidecar in scope.
const SAMPLE_FRC_RESPONSE = {
  params: {
    span1: 11.2,
    span2: 9.2,
    numbeam: 2,
    DeckId: "T10",
    conc_type: "NW",
    fck: 30,
    slab_depth: 150,
    mesh_type: "A193",
    uSecSize: "UB_457x152x60",
    fy5: "355",
    ush_con: 80,
    SideASecSize: "UB_457x152x60",
    fy1: "355",
    SideAEdgeFlag: 0,
    SideACompoFlag: 1,
    SideAsh_con: 80,
    SideBSecSize: "UB_533x210x101",
    fy2: "355",
    SideBEdgeFlag: 1,
    SideBCompoFlag: 0,
    SideBsh_con: 80,
    SideCSecSize: "UB_457x152x60",
    fy3: "355",
    SideCEdgeFlag: 0,
    SideCCompoFlag: 1,
    SideCsh_con: 80,
    SideDSecSize: "UB_610x229x101",
    fy4: "355",
    SideDEdgeFlag: 1,
    SideDCompoFlag: 0,
    SideDsh_con: 80,
    slab_weight: 2.83,
    cold_perm: 2,
    lead_var_act: 5,
    othr_var_act: 0,
    lead_var_fac: 0.5,
    othr_var_fac: 0.3,
    method: "parametric",
    time_limit: 120,
    qf: 511,
    window_percent: 95,
    Lc: 63,
    Bc: 12,
    Hc: 3.6,
    Hw: 3.6,
    Lw: 63,
    Bfac: 1400,
    combustion_factor: 0.8,
    growth_rate: 1,
  },
  project: {
    ProjectName: "Test Project",
    ClientName: "Test Client",
    JobNumber: "0000",
    CalculationBy: "Test User",
  },
};

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
  await installSidecarMock(page, {
    sidecarPort: SIDECAR_PORT,
    refData: REF_DATA,
  });
});

test.describe("FRC import", () => {
  test("header button → sample.frc populates form + shows import banner", async ({
    page,
  }) => {
    await page.route(
      `http://127.0.0.1:${SIDECAR_PORT}/api/import-frc`,
      (route) => route.fulfill({ status: 200, json: SAMPLE_FRC_RESPONSE }),
    );

    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "MACS+ Automation" }),
    ).toBeVisible();

    // Click the header entry point and feed in the .frc fixture. The hidden
    // <input> triggers a filechooser event the Playwright runner intercepts.
    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByTestId("import-frc-button").click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(FIXTURES, "sample.frc"));

    // Banner shows file name, project, client.
    const banner = page.getByTestId("frc-import-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("sample.frc");
    await expect(banner).toContainText("Test Project");
    await expect(banner).toContainText("Test Client");

    // Form populated from FRC params, not defaults.
    await expect(page.getByLabel("Span 1 (m)")).toHaveValue("11.2");
    await expect(page.getByLabel("Span 2 (m)")).toHaveValue("9.2");
    await expect(page.getByLabel("Number of beams")).toHaveValue("2");
    await expect(page.getByLabel("Slab depth (mm)")).toHaveValue("150");
    await expect(page.getByLabel("fck (MPa)")).toHaveValue("30");
    await expect(page.getByLabel("Fire load qf (MJ/m²)")).toHaveValue("511");
    await expect(page.getByLabel("Time limit (min)")).toHaveValue("120");
    // method = parametric → compartment fields render
    await expect(page.getByLabel("Analysis method")).toHaveValue("parametric");
    await expect(page.getByLabel("Compartment Lc (m)")).toHaveValue("63");
    await expect(page.getByLabel("Compartment Bc (m)")).toHaveValue("12");

    // No yellow hints — every section/deck/mesh ID is in scope.
    await expect(page.getByTestId("frc-hint-side_a_sec")).toHaveCount(0);
    await expect(page.getByTestId("frc-hint-deck_id")).toHaveCount(0);
  });

  test("unknown section → yellow hint on Side A, other sides unaffected", async ({
    page,
  }) => {
    const unknownResponse = {
      ...SAMPLE_FRC_RESPONSE,
      params: {
        ...SAMPLE_FRC_RESPONSE.params,
        SideASecSize: "UB_FAKE_999",
      },
    };
    await page.route(
      `http://127.0.0.1:${SIDECAR_PORT}/api/import-frc`,
      (route) => route.fulfill({ status: 200, json: unknownResponse }),
    );

    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "MACS+ Automation" }),
    ).toBeVisible();

    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByTestId("import-frc-button").click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(FIXTURES, "sample_unknown_section.frc"));

    // Side A flagged, sides B/C/D clean.
    const hint = page.getByTestId("frc-hint-side_a_sec");
    await expect(hint).toBeVisible();
    await expect(hint).toContainText("UB_FAKE_999");
    await expect(hint).toContainText("not in catalogue");
    await expect(page.getByTestId("frc-hint-side_b_sec")).toHaveCount(0);
    await expect(page.getByTestId("frc-hint-side_c_sec")).toHaveCount(0);
    await expect(page.getByTestId("frc-hint-side_d_sec")).toHaveCount(0);
  });

  test("Ctrl+O opens the same file picker", async ({ page }) => {
    await page.route(
      `http://127.0.0.1:${SIDECAR_PORT}/api/import-frc`,
      (route) => route.fulfill({ status: 200, json: SAMPLE_FRC_RESPONSE }),
    );

    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "MACS+ Automation" }),
    ).toBeVisible();

    // Click the page first so the keystroke targets the window, not whatever
    // chrome-side surface Playwright opened to. Without this the keyboard
    // event occasionally never reaches the listener under parallel workers.
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    const fileChooserPromise = page.waitForEvent("filechooser");
    // Press Ctrl+O — the window-level keyboard listener should trigger the
    // same file input click as the header button.
    await page.keyboard.press("Control+o");
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(FIXTURES, "sample.frc"));

    await expect(page.getByTestId("frc-import-banner")).toBeVisible();
    await expect(page.getByLabel("Span 1 (m)")).toHaveValue("11.2");
  });

  test("import error → inline error message, no form changes", async ({
    page,
  }) => {
    await page.route(
      `http://127.0.0.1:${SIDECAR_PORT}/api/import-frc`,
      (route) =>
        route.fulfill({
          status: 400,
          json: { error: "Invalid .frc file signature: 'WrongSig'" },
        }),
    );

    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "MACS+ Automation" }),
    ).toBeVisible();

    // Capture the seeded default so we can prove the form isn't touched.
    const span1Before = await page.getByLabel("Span 1 (m)").inputValue();

    const fileChooserPromise = page.waitForEvent("filechooser");
    await page.getByTestId("import-frc-button").click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.join(FIXTURES, "sample.frc"));

    await expect(page.getByTestId("frc-import-error")).toBeVisible();
    await expect(page.getByTestId("frc-import-error")).toContainText(
      "signature",
    );
    await expect(page.getByTestId("frc-import-banner")).toHaveCount(0);
    await expect(page.getByLabel("Span 1 (m)")).toHaveValue(span1Before);
  });
});
