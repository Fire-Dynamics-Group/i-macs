import { test, expect } from "@playwright/test";

import { installSidecarMock } from "./fixtures/sidecar-mock";
import { installTauriShim } from "./fixtures/tauri-mock";

const SIDECAR_PORT = 9999;
const LOG_DIR = "C:\\Users\\Test\\AppData\\Local\\i-macs\\logs";

test.beforeEach(async ({ page }) => {
  await installTauriShim(page, { sidecarPort: SIDECAR_PORT, logDir: LOG_DIR });
  await installSidecarMock(page, { sidecarPort: SIDECAR_PORT });
});

test.describe("ConfigPage smoke", () => {
  test("shows starting screen, then renders the config form once /healthz responds", async ({ page }) => {
    await page.goto("/");

    // SidecarReadyGate's "Starting…" copy is visible briefly. Don't assert on
    // it — the gate may resolve before the next event loop tick. Instead wait
    // for the form heading.
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();

    // The section picker is now a SearchableSelect (cmdk + Radix Popover).
    // Open the popover, then assert the listbox contains the mocked options.
    const sectionTrigger = page.getByLabel("Unprotected (centre) section");
    await expect(sectionTrigger).toBeVisible();
    await sectionTrigger.click();
    const listbox = page.getByRole("listbox");
    await expect(listbox.getByRole("option", { name: /UB 457 x 191 x 89/ }))
      .toBeVisible();
    await expect(listbox.getByRole("option", { name: /IPE 500/ }))
      .toBeVisible();
  });

  test("searchable picker fuzzy-matches a partial name and selects on Enter", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();

    const sectionTrigger = page.getByLabel("Unprotected (centre) section");
    await expect(sectionTrigger).toBeVisible();
    await sectionTrigger.click();

    // Typing a partial name fuzzy-matches via fuse.js. "457" picks out the
    // single UB section whose name includes 457.
    const searchInput = page.getByPlaceholder("Search…");
    await searchInput.fill("457");

    const listbox = page.getByRole("listbox");
    await expect(listbox.getByRole("option", { name: /UB 457 x 191 x 89/ }))
      .toBeVisible();
    await expect(listbox.getByRole("option", { name: /IPE 500/ }))
      .toHaveCount(0);

    // ArrowDown then Enter selects the highlighted match. The trigger should
    // then display the picked option's label.
    await searchInput.press("ArrowDown");
    await searchInput.press("Enter");
    await expect(sectionTrigger).toContainText("UB 457 x 191 x 89");

    // Submit and capture the POST body — the form should send the selected id.
    const submitBodyPromise = new Promise<Record<string, unknown>>((resolve) => {
      page.on("request", (req) => {
        if (req.method() === "POST" && req.url().endsWith("/api/runs")) {
          resolve(JSON.parse(req.postData() ?? "{}"));
        }
      });
    });
    await page.getByRole("button", { name: "Submit calculation" }).click();
    const body = await submitBodyPromise;
    expect(body.u_sec_size).toBe("UB_457x191x89");
  });

  test("submits a run and navigates to the run-detail page", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();

    // Wait until the form is hydrated with the sidecar's defaults — the
    // submit button is the easiest signal for that.
    const submit = page.getByRole("button", { name: "Submit calculation" });
    await expect(submit).toBeEnabled();

    await submit.click();

    await expect(page).toHaveURL(/\/runs\/1$/);
    await expect(page.getByRole("heading", { name: "Run #1" })).toBeVisible();
    // The badge + the breakdown table both show "Pass"; assert at least one.
    await expect(page.getByText("Pass").first()).toBeVisible();
    // The breakdown table renders one row per check including per-side beam loads.
    await expect(page.getByText(/Side A beam load/i)).toBeVisible();
  });

  test("submit payload includes per-side fy + edge/composite/sh_con flags", async ({ page }) => {
    // Capture the request body sent to POST /api/runs without breaking the
    // existing mock — Playwright lets us listen alongside the route handler.
    const submitBodyPromise = new Promise<Record<string, unknown>>((resolve) => {
      page.on("request", (req) => {
        if (req.method() === "POST" && req.url().endsWith("/api/runs")) {
          resolve(JSON.parse(req.postData() ?? "{}"));
        }
      });
    });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();
    const submit = page.getByRole("button", { name: "Submit calculation" });
    await expect(submit).toBeEnabled();
    await submit.click();

    const body = await submitBodyPromise;

    // Per-side steel grade must be in the payload (not just the centre beam).
    expect(body).toMatchObject({
      side_a_fy: expect.any(String),
      side_b_fy: expect.any(String),
      side_c_fy: expect.any(String),
      side_d_fy: expect.any(String),
    });
    // Edge / composite flags (0 or 1) per side.
    for (const side of ["a", "b", "c", "d"] as const) {
      expect(body[`side_${side}_edge`]).toEqual(expect.any(Number));
      expect(body[`side_${side}_composite`]).toEqual(expect.any(Number));
      expect(body[`side_${side}_sh_con`]).toEqual(expect.any(Number));
    }
    // Centre beam shear connector spacing.
    expect(body.u_sec_sh_con).toEqual(expect.any(Number));
  });

  test("shows the parametric-only fields when the user picks parametric", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "MACS+ Automation" })).toBeVisible();

    const methodSelect = page.getByLabel("Analysis method");
    await methodSelect.selectOption("parametric");

    await expect(page.getByLabel("Compartment Lc (m)")).toBeVisible();
    await expect(page.getByLabel("Bfac (J/m²s½K)")).toBeVisible();
  });

  test("error boundary renders when /api/ref-data 500s", async ({ page }) => {
    // Override the default mock with an error for ref-data.
    await page.route(`http://127.0.0.1:${SIDECAR_PORT}/api/ref-data`, (route) =>
      route.fulfill({ status: 500, json: { detail: "boom" } }),
    );

    await page.goto("/");

    await expect(
      page.getByText("MACS+ Automation can't reach its background service"),
    ).toBeVisible();
    await expect(page.getByText(LOG_DIR)).toBeVisible();
  });
});
