import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright runs against a `vite preview` of the React bundle, with Tauri
 * commands mocked via `page.addInitScript` and the sidecar's HTTP API mocked
 * via `page.route`. This catches form/routing/race regressions in seconds —
 * the actual Tauri shell is exercised manually + by the workflow build (slice 6).
 *
 * Skip in CI if matrix bandwidth gets tight; vitest still covers pure logic.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  timeout: 30_000,

  use: {
    baseURL: "http://localhost:4173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],

  webServer: {
    // Build the React bundle once, then serve it on :4173. Mirrors what the
    // user sees in Tauri's webview far more closely than `vite dev`.
    command: "npm run build:vite && npx vite preview --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
