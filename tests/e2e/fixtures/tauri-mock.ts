import { type Page } from "@playwright/test";

/**
 * Inject a Tauri-shape window object so calls to `invoke('get_sidecar_port')`,
 * event listeners, and `revealItemInDir` resolve without a real Tauri shell.
 *
 * Tauri 2.x looks for `window.__TAURI_INTERNALS__.invoke` and walks plugin
 * channels through there. Mocking at this layer means the React code stays
 * untouched and we can replay the same shape across every test.
 *
 * Implemented as a string-template `addInitScript` because the
 * function-with-arg form has surprised us before — closure capture across
 * Playwright's process boundary can drop the arg silently in some versions.
 */
export async function installTauriShim(
  page: Page,
  opts: { sidecarPort: number; logDir: string },
) {
  const script = `
    (function() {
      const sidecarPort = ${opts.sidecarPort};
      const logDir = ${JSON.stringify(opts.logDir)};
      const handlers = {};

      window.__TAURI_INTERNALS__ = {
        invoke: async function(cmd) {
          switch (cmd) {
            case 'get_sidecar_port': return sidecarPort;
            case 'get_log_dir': return logDir;
            case 'shutdown_sidecar': return null;
            default:
              throw new Error('[tauri-shim] unmocked command: ' + cmd);
          }
        },
        transformCallback: function(cb) {
          const id = Math.floor(Math.random() * 1e9);
          handlers[id.toString()] = cb;
          return id;
        },
        metadata: { plugins: [], windows: [] },
        plugins: { event: { listen: function() { return Promise.resolve(function(){}); } } },
      };

      // Test-side hook for emitting events into the shim.
      window.__TAURI_E2E__ = {
        emit: function(event, payload) {
          for (const cb of Object.values(handlers)) {
            cb({ event: event, payload: payload, id: 0 });
          }
        },
      };
    })();
  `;
  await page.addInitScript({ content: script });
}
