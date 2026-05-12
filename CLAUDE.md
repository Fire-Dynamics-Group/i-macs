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
