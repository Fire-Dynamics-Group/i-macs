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

    // Mocked /api/ref-data populated dropdowns with two UB sections + IPE 500.
    const sectionSelect = page.getByLabel("Unprotected (centre) section");
    await expect(sectionSelect).toBeVisible();
    await expect(sectionSelect.getByRole("option", { name: /UB 457 x 191 x 89/ }))
      .toBeAttached();
    await expect(sectionSelect.getByRole("option", { name: /IPE 500/ }))
      .toBeAttached();
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
    await expect(page.getByText("Pass")).toBeVisible();
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
