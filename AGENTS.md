# MACS+ Automation — Project Instructions

## Active App
i-macs is a Tauri + React desktop app with a PyInstaller-frozen Python sidecar (FastAPI). Source layout:

- Frontend: `src/` (React + TypeScript + Vite), routed via React Router (`src/App.tsx`).
- Backend (sidecar): `macs_automation/app.py` (FastAPI), entry built via `pyinstaller-server.spec`.
- Tauri shell: `src-tauri/`. Tauri spawns the sidecar on launch and pipes its port to the frontend via IPC.

The legacy Jinja-template app under `macs_automation/templates/` and `macs_automation/web/` is dead code post-PR #1 (the rebuild) and will be removed in cleanup. Do NOT add new features there.

## Tests

- Python: `pytest` (see `macs_automation/tests/`).
- Frontend unit: `vitest` (configured in `vite.config.ts`).
- E2E: Playwright (`tests/e2e/`, `playwright.config.ts`).

Practice TDD: write tests first, then implementation.

## Development Servers & Hot Reload

Backend and sidecar servers **must always run with auto-reload (`--reload`) enabled for development**.

- **Why was the i-macs backend not running on hot reload?**
  - Tauri's `spawn_sidecar` was launching the Python sidecar without a `--reload` option, and uvicorn was running in static single-process mode.
  - We added the `--reload` CLI flag to `macs_automation/app.py` and updated `src-tauri/src/main.rs` to pass it in dev mode.
- All dev servers should be running with reload so backend code changes take effect immediately without requiring manual process or container restarts.

## Honest Engineering Metrics (No Fake / Mock Fallback Data)

- **Never display fake, hardcoded mock values, or invented success metrics as fallbacks in engineering assessment UI.**
  - Real calculations and simulations must always reflect actual pipeline data.
  - Fallbacks such as hardcoded run counts (`10,000 runs`), artificial pass counts (`9,999 pass`, `passCount ?? 9999`), or default success percentages (`?? 100% Rel.`) disguise broken pipelines and give false engineering confidence.
  - If data is loading, missing, or an error occurs, display honest states: explicit loading indicators, skeletons, empty states (`—` or `0`), or clear error badges. Never show invented or optimistic defaults.
