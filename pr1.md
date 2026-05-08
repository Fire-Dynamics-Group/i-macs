# PR 1 — i-macs Desktop: Tauri + PyInstaller + React, single-run v1

> Repackage i-macs as a zero-Python-install Windows desktop app. End users install MACS+ (free) and the i-macs `.exe`; nothing else. v1 ships single-run calc through the bundle to prove the pipeline; sweep, LHS, FRC import, and report generation each become their own follow-up PR. Auto-update via GitHub Releases. Read end-to-end before touching code.

## Goal

Today, running i-macs requires the user to RDP into a Windows box, open a folder, and run `python run_dashboard.py` against a hand-installed Python + 32-bit Python pair. v1 of this PR replaces that with a single NSIS installer that bundles Python, FastAPI, the COM runner, and a React UI inside a Tauri shell. After v1: a fire safety engineer downloads MACS+ from macs-steel.org, downloads the i-macs `.exe`, double-clicks each — done. Auto-update keeps them current via Tauri's GitHub-Releases-backed updater.

When done: a fresh Windows account with MACS+ installed and the i-macs `.exe` runs through:

1. App launches in <30 s; if MACS+ is missing, a Tauri dialog points to the macs-steel.org download.
2. Config form renders (single-run mode only — sweep/LHS hidden in v1).
3. Submitting one calculation completes through FRACOF and shows pass/fail + engine outputs on a run-detail page.
4. `git tag v0.1.0-rc.1 && git push --tags` triggers the GH Actions release pipeline; installed users pick up the update on next launch.

## Starting state (already in place)

- Python sidecar (`macs_automation/app.py`): FastAPI + Jinja templates, runs the COM engine via `engine.run_one_com()` which today subprocess-bridges to 32-bit Python via `com_bridge.py`. 195+ pytest tests green.
- COM engine (`macs_automation/engine.py`): `MACSEngine` wraps FRACOF via `win32com.client` + explicit `IDispatch.Invoke` (DllSurrogate-safe). 32-bit-only.
- Reference data: `data_loader.py:_find_macs_data_xml` auto-detects `Data.xml` under `C:\Program Files (x86)\MACS+*\EN\Data\`. Lives in MACS+ install — **not bundled with us.**
- Env-var overrides already exist: `MACS_DATA_PATH`, `MACS_DB_PATH`, `PYTHON32`. The new shell sets `MACS_DB_PATH` to `%LOCALAPPDATA%\i-macs\results.db`.
- Reference apps in same org for build-pipeline patterns: `cfd-post-processing` (PyInstaller spec, NSIS bundle, GH Actions release.yml, Job Object KILL_ON_JOB_CLOSE), `email-filer` (Tauri 2 + minisign updater).
- Existing route inventory in `app.py` (slice 1 will classify each — see *Route classification* table below).

## Build-machine prerequisites

Before starting slice 1, the build machine needs:

- **32-bit Python 3.10** at a known path (e.g. `C:\Users\<you>\AppData\Local\Programs\Python\Python310-32\python.exe`). All slice 1+ work happens inside a 32-bit venv created from this interpreter.
- **Node.js 20 LTS+** and **npm**.
- **Rust stable toolchain** + `cargo install tauri-cli --version "^2"`.
- **Visual Studio Build Tools 2022** with the "Desktop development with C++" workload (MSVC linker for the Tauri release build).
- **MACS+_304** installed at `C:\Program Files (x86)\MACS+_304\` for any e2e/COM tests; mocked tests work without it.
- **`cfd-post-processing` cloned as a sibling directory** to `i-macs` (i.e. `..\cfd-post-processing\` from this repo). Several slices copy files (`pyinstaller-server.spec`, `src-tauri/src/main.rs`, `.github/workflows/release.yml`, `src-tauri/capabilities/default.json`, `src/lib/updater.ts`) from there. Repo: `https://github.com/Fire-Dynamics-Group/cfd-post-processing.git`.
- This repo: `https://github.com/Fire-Dynamics-Group/i-macs.git` (origin already configured).

The build venv is created from `requirements.txt` (the truth — `pyproject.toml` is incomplete and missing FastAPI/uvicorn/jinja2). Add `pyinstaller>=6.0` to that venv on top:

```powershell
py -3.10-32 -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
pip install pyinstaller>=6.0
```

## Architecture decisions (locked)

| #  | Topic | Decision |
|----|---|---|
| 1  | Frontend stack | React 18 + Vite + TypeScript SPA inside the Tauri webview. Replaces every Jinja template. |
| 2  | Python arch | 32-bit Python 3.10 only inside the bundle. Delete the 32/64 bridge dance, `PYTHON32` env var, `run_dashboard.py` auto-detect. |
| 3  | COM crash isolation | Keep a per-calculation subprocess (rename `com_bridge.py` → `com_runner.py`). Same arch as parent (both 32-bit), but isolated process per calc so a FRACOF crash doesn't take the FastAPI sidecar with it. |
| 4  | API contract | Pure JSON over HTTP. React `fetch`s `http://127.0.0.1:<port>/api/...`. Tauri exposes only `get_sidecar_port()` and `shutdown_sidecar()` (the latter for the auto-update file-lock dance). |
| 5  | Live updates | Server-Sent Events via `EventSource`. Defer until sweep PR — v1 has no live dashboard. |
| 6  | Routing | React Router DOM v6, `BrowserRouter` inside the webview. v1 routes: `/` (config), `/runs/:id` (run detail). |
| 7  | Data fetching | TanStack Query v5. GET endpoints cached by query key; mutations via `useMutation`. |
| 8  | Forms | react-hook-form, uncontrolled by default. Conditional reveal via `watch`. Zod for validation when needed. |
| 9  | Styling | Tailwind + shadcn/ui. Components copy-pasted into the repo (no runtime dep). v1 uses `Form`, `Select`, `Input`, `Button`, `Card`, `Toast`, `Dialog`. |
| 10 | Charts | Plotly.js. Defer until sweep PR — v1 has no charts on run-detail beyond raw numbers + a single time-series table. |
| 11 | First-run UX | New `/healthz` endpoint returns `{macs_installed: bool, macs_version: str|null}`. Tauri shell hits it after `wait_for_health`; if `macs_installed=false`, shows a `tauri_plugin_dialog` modal with the macs-steel.org link before opening the React UI. Doesn't block startup — engineer might want to read logs. |
| 12 | Dev loop | `npm run dev` → `tauri dev` orchestrates Vite + Python sidecar + Tauri webview. No `--reload` on the sidecar; Python changes mean ctrl-c + restart. |
| 13 | Test pyramid | pytest stays for Python (TestClient). vitest + Testing Library for React. Manual smoke on a clean Windows VM before each release. **Playwright deferred to v2.** |
| 14 | DB location | `%LOCALAPPDATA%\i-macs\results.db`. Tauri shell sets `MACS_DB_PATH`. No migration of any existing `results.db` from the old run-from-source layout — fresh start. |
| 15 | Logs location | `%LOCALAPPDATA%\i-macs\logs\sidecar.log` (rotating, 5 MB × 5). Sidecar takes `--log-dir` CLI arg; mirrors cfd-post-processing's pattern. |
| 16 | Sidecar lifecycle | Win32 Job Object with `KILL_ON_JOB_CLOSE` so the sidecar dies with the parent under any exit path (graceful, panic, NSIS update kill, Task Manager). Direct port of cfd's `assign_sidecar_to_job`. |
| 17 | Bundler | NSIS installer via Tauri's `bundle.targets`. Per-user install (no admin). Match cfd's NSIS layout. |
| 18 | Code signing | Skipped for v1, same as cfd. SmartScreen warning on first download is acceptable. Revisit if external distribution becomes a requirement. |
| 19 | Auto-update | Tauri updater plugin + GitHub Releases. New minisign keypair (private in GH Action secrets, public in `tauri.conf.json`). Public release channel at `https://github.com/Fire-Dynamics-Group/i-macs/releases/latest/download/latest.json`. |
| 20 | Versioning | Three places aligned: `package.json`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`. Bump together each release. |
| 21 | App identity | `productName`: `MACS+ Automation`. Identifier: `com.firedynamicsgroup.i-macs`. |
| 22 | Repo cleanup | Delete `macs_automation/web/` (dead per CLAUDE.md). Delete `run_dashboard.py` (replaced by Tauri shell). Delete the 32/64 detection logic; rename `com_bridge.py` → `com_runner.py`. |
| 23 | pr1.md handling | Existing `pr1.md` (per-side beams + float inputs + CSV upload) moved to `docs/archive/pr1_per_side_csv_ux.md`. Float inputs (`step="any"`) fold into v1 React forms. Per-side beams + CSV come back in the sweep follow-up PR, citing the archived decisions table. |
| 24 | v1 feature scope | Single-run config form + run-detail page only. Hidden in v1: sweep mode, LHS, FRC import, report generation, custom-section/deck/mesh forms. Each becomes a follow-up PR. |

## Route classification (slice 1 input)

Audit of `macs_automation/app.py` routes as of branch `slab-weight-and-beam-failure-fixes`. Slice 1 acts on this table.

| Route | Today | v1 action |
|---|---|---|
| `GET /` | `HTMLResponse` (Jinja) | **Delete.** React owns the home page. |
| `GET /dashboard` | `HTMLResponse` (Jinja) | **Delete.** Sweep dashboard returns in sweep PR. |
| `GET /results` | `HTMLResponse` (Jinja) | **Delete.** React owns the results list. |
| `GET /results/{run_id}` | `HTMLResponse` (Jinja) | **Delete.** React owns run detail. |
| `POST /api/runs` | JSON | **Keep, v1.** Single-run submit. |
| `GET /api/runs` | JSON | **Keep, v1.** Run list (React may use later; trivial to keep). |
| `GET /api/runs/{run_id}` | JSON | **Keep, v1.** Run detail. |
| `GET /api/runs/{run_id}/timeseries` | JSON | **Keep, v1.** Run-detail capacity-vs-time table. |
| `GET /api/sections` | JSON | **Keep, v1.** Config form section dropdown. |
| `GET /api/decks` | JSON | **Keep, v1.** Config form deck dropdown. |
| `GET /api/meshes` | JSON | **Keep, v1.** Config form mesh dropdown. |
| `POST /api/custom-sections` + `GET` + `DELETE` | JSON | **Keep but un-exposed in v1 React UI.** Cheaper to leave the routes than to half-delete. UI lands in custom sections/decks/meshes follow-up PR. |
| `POST /api/custom-decks` + `GET` + `DELETE` | JSON | Same. |
| `POST /api/custom-meshes` + `GET` + `DELETE` | JSON | Same. |
| `POST /api/sweeps` + `GET /api/sweeps/status` | JSON | **Keep but un-exposed.** Reactivated in sweep PR. |
| `POST /api/import-frc` | JSON | **Keep but un-exposed.** Reactivated in FRC follow-up PR. |
| `GET /api/report/docx` + `GET /api/report/chart/{type}` | JSON / file | **Keep but un-exposed.** Reactivated in report follow-up PR. |
| `GET /healthz` | — | **Add.** Returns `{sidecar, macs_installed, macs_version}`. |

## Build order (slices)

Each slice ends green tests + a manual checkpoint. Slices 1–3 are sequential; slice 4 can run in parallel with 1–2.

### Slice 1 — Python sidecar refactor (no UI, no Tauri)

Outcome: a 32-bit Python 3.10 venv that runs `python -m macs_automation.app --port 8123 --log-dir ./logs` and exposes a JSON-only API plus `/healthz`.

1. Delete `macs_automation/web/` and any tests scoped to it.
2. Delete the 32/64 detection in `engine.run_one_com()` and `run_dashboard.py`. Rename `com_bridge.py` → `com_runner.py`; keep the subprocess pattern but stop branching on `PYTHON32`. Add a test that confirms a `RuntimeError` raised inside `_run_one` doesn't crash the parent.
3. Add CLI args to `app.py` (`--port`, `--log-dir`). Wire `--log-dir` to a `RotatingFileHandler` (5 MB × 5).
4. Add `/healthz`: returns `{"sidecar": "alive", "macs_installed": <bool>, "macs_version": <str|null>}`. Reuse `_find_macs_data_xml` + parse the `MACS+_NNN` folder name for the version.
5. Audit Jinja-rendering routes. Convert each kept-for-v1 route to JSON: ref-data → `GET /api/ref-data`; submit run → `POST /api/runs`; run detail → `GET /api/runs/:id`. Hide everything used only by sweep/LHS/FRC/report — they ship in follow-up PRs.
6. Verify `pytest` green on 32-bit Python 3.10 in a fresh venv. Any 64-bit-only deps surface here.

Done when: `pytest` green; `python -m macs_automation.app --port 8123` boots; `curl http://127.0.0.1:8123/healthz` returns expected JSON; `curl http://127.0.0.1:8123/api/ref-data` returns sections; `POST /api/runs` with a fixture payload completes through the COM subprocess.

### Slice 2 — PyInstaller bundle

Outcome: `dist/i-macs-sidecar/i-macs-sidecar.exe` runs identically to slice 1's `python -m macs_automation.app`.

1. Copy `..\cfd-post-processing\pyinstaller-server.spec` to `pyinstaller-server.spec`; replace entry point (`pipeline/server.py` → `macs_automation/app.py`), exe name (`pipeline-server` → `i-macs-sidecar`), hidden imports, and datas. Hidden imports for i-macs: `pythoncom`, `win32com.client`, `pywintypes`, `collect_submodules('uvicorn')`, `collect_submodules('fastapi')`, `collect_submodules('pydantic')`, plus `uvicorn.logging`, `uvicorn.loops.auto`, `uvicorn.protocols.http.auto`, `uvicorn.protocols.websockets.auto`, `uvicorn.lifespan.on`. Data files: none — `Data.xml` lives in MACS+ install. **Pre-existing build inputs**: the venv must be 32-bit Python 3.10 with `requirements.txt` + `pip install -e .` + `pyinstaller` installed (per *Build-machine prerequisites*). Python 3.10 32-bit is required because FRACOF COM is 32-bit — verify `python -c "import struct; print(struct.calcsize('P')*8)"` prints `32` before running PyInstaller.
2. Copy `..\cfd-post-processing\scripts\build-sidecar.ps1` to `scripts\build-sidecar.ps1`; adjust paths and bundle name. The script: activates venv, runs `pyinstaller --clean --noconfirm pyinstaller-server.spec`, copies the onedir tree to `src-tauri/binaries/i-macs-sidecar-x86_64-pc-windows-msvc/`. The `x86_64` triple is preserved by Tauri convention even for a 32-bit sidecar — the triple refers to the Tauri shell's arch, not the sidecar's.
3. Standalone smoke test before chasing PyInstaller bugs through the Tauri build: `cd dist\i-macs-sidecar && .\i-macs-sidecar.exe --port 9999 --log-dir tmp_logs`, then `Invoke-RestMethod http://127.0.0.1:9999/healthz` and one `POST /api/runs`. Catches missing hidden imports before they bite inside Tauri.

Done when: bundled exe runs the same e2e calculation slice 1 verified.

### Slice 3 — Tauri shell scaffold

Outcome: `npm run dev` opens a webview that says "hello from React" served from Vite + a sidecar that responds to `/healthz`.

1. `npm create tauri-app@latest` → React + TypeScript + npm template inside the existing repo. Move output into place; line up `src/`, `src-tauri/`, `package.json` at the repo root, alongside `macs_automation/`.
2. Install Tauri-side deps:
   ```powershell
   npm install @tauri-apps/api @tauri-apps/plugin-dialog @tauri-apps/plugin-updater @tauri-apps/plugin-process @tauri-apps/plugin-shell @tauri-apps/plugin-opener
   npm install -D @tauri-apps/cli
   ```
   And the Rust-side crate equivalents in `src-tauri/Cargo.toml` — copy from `..\cfd-post-processing\src-tauri\Cargo.toml` (`tauri`, `tauri-plugin-dialog`, `tauri-plugin-updater`, `tauri-plugin-process`, `tauri-plugin-shell`, `tauri-plugin-opener`, `ureq`, `win32job`).
3. Port cfd's `src-tauri/src/main.rs` (decisions #4, #11, #16): port discovery via `TcpListener`, `spawn_sidecar` with debug-vs-release branch, `wait_for_health`, Job Object binding, `get_sidecar_port` + `shutdown_sidecar` commands, `RunEvent::ExitRequested` cleanup. Adapt only the spawn module name (`macs_automation.app` instead of `pipeline.server`) and the sidecar binary name (`i-macs-sidecar` instead of `pipeline-server`).
4. Copy `..\cfd-post-processing\src-tauri\capabilities\default.json` to `src-tauri\capabilities\default.json` and update `description`. Required permissions: `core:default`, `core:window:default`, `core:webview:default`, `core:event:default`, `dialog:default`, `dialog:allow-open`, `shell:default`, `opener:default`, `opener:allow-open-path`, `opener:allow-reveal-item-in-dir`, `updater:default`, `process:default`.
5. Wire MACS+-missing dialog (decision #11). On `wait_for_health`'s response, if `macs_installed=false`, show `tauri_plugin_dialog::message` with the download link (`https://www.macs-steel.org/`).
6. `tauri.conf.json`: `productName: "MACS+ Automation"`, `identifier: "com.firedynamicsgroup.i-macs"`, NSIS target, `bundle.resources` glob `binaries/i-macs-sidecar-x86_64-pc-windows-msvc/**/*`, updater endpoint `https://github.com/Fire-Dynamics-Group/i-macs/releases/latest/download/latest.json`, pubkey placeholder (filled in slice 6 once `npx @tauri-apps/cli signer generate` is run).

Done when: `npm run dev` boots through to the React placeholder; `curl` against the sidecar port (Tauri logs it on stdout) responds; killing the Tauri window kills the sidecar (Job Object check).

### Slice 4 — React skeleton (parallel to slices 1–3)

Outcome: routed React app with TanStack Query provider, react-hook-form set up, Tailwind + shadcn primitives installed, but no real screens yet.

1. Install React + tooling deps:
   ```powershell
   # Frontend runtime deps
   npm install react react-dom react-router-dom @tanstack/react-query react-hook-form
   npm install zod @hookform/resolvers
   # Plotly is installed but unused in v1 — keeps the dep graph stable for the sweep PR
   npm install plotly.js-dist-min @types/plotly.js

   # Dev deps
   npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom
   npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
   npm install -D tailwindcss postcss autoprefixer
   ```
2. Tailwind init: `npx tailwindcss init -p`. Configure `content: ['./index.html', './src/**/*.{ts,tsx}']`.
3. shadcn init: `npx shadcn@latest init` (pick the `default` style + `slate` base color + CSS variables yes). Add v1 primitives:
   ```powershell
   npx shadcn@latest add form select input button card dialog toast label badge separator
   ```
4. `BrowserRouter` with two routes: `/` (placeholder), `/runs/:id` (placeholder).
5. `QueryClientProvider`, default options (`staleTime: 30_000`, `retry: 1`).
6. Typed API client (`src/api/client.ts`) that reads the port from the Tauri command (`invoke<number>('get_sidecar_port')`) and exposes typed `fetchRefData()`, `submitRun(payload)`, `getRun(id)`, `getRunTimeseries(id)`. One vitest smoke test per function with `fetch` mocked.
7. vitest + Testing Library wired (`vitest.config.ts` with `environment: 'jsdom'`, `setupFiles: ['./src/test/setup.ts']` that imports `@testing-library/jest-dom/vitest`); one passing smoke test of the API client.

Done when: `npm test` passes; routing works in `tauri dev`.

### Slice 5 — Config form + single-run + run detail (the v1 feature)

Outcome: a user can fill the config form, submit a calculation, and see results.

1. Build the config form in React (single-run subset only). Reproduces the inputs from `templates/config.html`'s single-run path, minus sweep/LHS/FRC controls. Uses react-hook-form. Float inputs use `step="any"` (folding in pr1's archived decision #6).
2. Section/deck/mesh selects pull from `useQuery(['ref-data'], fetchRefData)`. Custom-section/deck/mesh add-forms hidden in v1.
3. Submit calls `useMutation` against `POST /api/runs`. On success, navigate to `/runs/:id`.
4. Run-detail page: `useQuery(['run', id], () => getRun(id))`. Renders pass/fail badge, max unity factor, time of max, and a single capacity-vs-time table (no Plotly chart yet — that lands with the sweep PR).
5. **Sidecar-unreachable fallback** (`src/components/SidecarErrorScreen.tsx`): an error boundary / route guard around the routed app. If `get_sidecar_port` rejects, or the first `fetchRefData()` retry-exhausts, render a card with: (a) "MACS+ Automation can't reach its background service", (b) the resolved `sidecar.log` path (passed via Tauri command `get_log_dir`), (c) an "Open log folder" button using `@tauri-apps/plugin-opener`, (d) a "Retry" button. Don't paper over with a white screen.
6. vitest tests for the config form: required-field validation, float-input acceptance, mutation called with correct shape. vitest test for `SidecarErrorScreen` rendering when the API client throws.
7. pytest TestClient tests for the corresponding routes: a single-run round-trip with all defaults completes; a run with `qf=0.5` is clamped to 1.0 and doesn't crash; `/healthz` returns the expected shape with and without MACS+ on `PATH`.

Done when: full config → submit → run-detail flow works in `tauri dev` against the dev sidecar.

### Slice 6 — GH Actions release pipeline + auto-updater

Outcome: pushing a `v*` tag produces a signed NSIS installer + `latest.json` on GitHub Releases.

1. `npx @tauri-apps/cli signer generate -w $HOME\.tauri\i-macs.key`. Public key into `tauri.conf.json`. Private key + passphrase into repo secrets at `https://github.com/Fire-Dynamics-Group/i-macs/settings/secrets/actions` (`TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`). Back the `.key` file up to a password manager — losing it forces every existing install to be reinstalled by hand.
2. Port `..\cfd-post-processing\.github\workflows\release.yml` to `.github/workflows/release.yml`. Runner: `windows-latest`. Triggers on `v*`. Steps: setup Python 3.10 (32-bit), `pip install -r requirements.txt && pip install -e . && pip install pyinstaller`, run `scripts/build-sidecar.ps1`, setup Node 20, `npm ci`, `npm run tauri build`, then publish via `tauri-action` to a GitHub Release. Verify `actions/setup-python@v5` supports `architecture: 'x86'` (it does).
3. JS-side updater: copy `..\cfd-post-processing\src\lib\updater.ts` to `src/lib/updater.ts`. Silent check on launch (called from `App.tsx` `useEffect`) + a manual "Check for updates" entry inside a settings sheet (`Sheet` from shadcn).
4. Cut a `v0.1.0-rc.1` tag end-to-end on a test branch first; verify the workflow goes green and the artifact shape is right.

Done when: tagging produces a working installer + an installed previous-version app updates itself on next launch.

### Slice 7 — Smoke test on clean VM

Outcome: cfd-style acceptance gate, but for i-macs.

1. Fresh Windows VM (or teammate's machine that has never had Python).
2. Install MACS+ from macs-steel.org.
3. Install i-macs from the Release `.exe`.
4. Launch → MACS+ detected, no dialog. Submit one fixture calc → run-detail renders. Reasonable wall-clock time. Logs at `%LOCALAPPDATA%\i-macs\logs\sidecar.log` populated.
5. Without MACS+ installed (separate VM), launch i-macs → dialog with download link appears.

Done when: both VM tests pass on the same `.exe`.

## Done criteria

- `pytest` green on 32-bit Python 3.10 (slice 1 acceptance).
- `npm test` (vitest) green (slices 4–5).
- Standalone bundled sidecar smoke test (slice 2).
- `npm run dev` end-to-end happy path in dev (slice 5 acceptance).
- GH Actions release workflow goes green on a release-candidate tag (slice 6).
- Manual VM smoke test passes (slice 7).
- Existing single-run e2e test (`test_e2e_real.py`) still passes when run inside 32-bit Python with MACS+ installed (sanity check that the sidecar refactor didn't change semantics).

## Out of scope (deferred to follow-up PRs / backlog)

- **Sweep PR**: parameter sweep mode + live dashboard with Plotly + SSE + per-side beams + CSV-driven sweep values (resurrects `docs/archive/pr1_per_side_csv_ux.md` decisions #1–14).
- **LHS PR**: probabilistic sampling, distribution presets.
- **FRC import PR**: drag-and-drop FRC parsing into the React form.
- **Report PR**: ZIP report download with matplotlib PNGs + per-curve CSVs (the existing `report.py` ships unchanged, but a route + UI button get added).
- **Custom sections/decks/meshes PR**: re-add the add-form `<details>` panels in React.
- **Code signing**: revisit if external distribution becomes a thing (decision #18).
- **Playwright e2e for the bundle**: v2 (decision #13).
- **Existing data migration**: not in scope; users with results from the old run-from-source layout copy `results.db` over manually if they care (decision #14).

## Sources

- `cfd-post-processing/pyinstaller-server.spec` — PyInstaller pattern to copy.
- `cfd-post-processing/src-tauri/src/main.rs` — Tauri shell pattern (port discovery, sidecar spawn, Job Object, health probe).
- `cfd-post-processing/BUILD.md`, `RELEASE.md` — build and release runbook patterns.
- `cfd-post-processing/.github/workflows/release.yml` — GH Actions release pipeline.
- `email-filer/src-tauri/tauri.conf.json` — minisign updater pattern reference.
- `macs_automation/engine.py` — COM wrapping, FRACOF stability constraints (`qf >= 1.0` clamp).
- `macs_automation/com_bridge.py` — subprocess-per-calc pattern that becomes `com_runner.py`.
- `macs_automation/data_loader.py` — `Data.xml` auto-detect logic that informs `/healthz`.
- `docs/archive/pr1_per_side_csv_ux.md` — original UX-uplift plan; resurrected in the sweep follow-up PR.
- `CLAUDE.md` — `macs_automation/web/` is out of scope; only `macs_automation/app.py` is built.

---

# Status — 2026-05-08 (handoff for a fresh agent)

This section is the source of truth on what's actually done. Read it before
making any decisions based on the slice descriptions above — the plan and
reality have diverged in a few places.

## Slice progress

| Slice | Topic | Status |
|---|---|---|
| 1 | Python sidecar refactor | **Done.** 359 pytest pass, 4 com-marker skip, 1 pre-existing failure (see *Open issues*). |
| 2 | PyInstaller bundle | **Done.** `dist/i-macs-sidecar/i-macs-sidecar.exe --port N --log-dir D` boots cleanly; `/healthz` + `/api/ref-data` return 200 standalone. 36 MB onedir. |
| 3 | Tauri shell scaffold | **Done.** `npm run tauri dev` builds clean, spawns sidecar, Job Object binds, parses `/healthz` JSON, surfaces MACS+-missing dialog when `macs_installed=false`. |
| 4 | React skeleton | **Done.** `npm test` (vitest) green, 4/4. Routing + TanStack Query + react-hook-form + Tailwind wired. shadcn primitives **not** installed (deferred to slice 5 polish or beyond). |
| 4.5 | Playwright UI smoke (**not in original plan** — see *Deviations*) | **Done.** `npm run test:e2e` green, 4/4 cases. `tests/e2e/` + `playwright.config.ts`. |
| 5 | Config form + run detail | **Done — minimum viable.** Form covers geometry / slab / deck / mesh / beams (centre + 4 sides) / fire (with parametric reveal). Submits to `/api/runs`, navigates to `/runs/:id`, run-detail renders pass/fail badge + UF + capacity-vs-time table. **Not** built: shadcn primitives, edge/composite/sh_con flags per side (defaulted), full validation. Add as polish if needed before tagging. |
| 6 | GH Actions release pipeline + auto-updater | **Partially done.** `.github/workflows/release.yml` and `src/lib/updater.ts` are in. **You** still owe: (a) `npx @tauri-apps/cli signer generate`, (b) repo secrets, (c) replace `REPLACE_ME_WITH_GENERATED_PUBKEY_IN_SLICE_6` in `src-tauri/tauri.conf.json`. See `RELEASE.md`. |
| 7 | Clean-VM smoke test | **Not started.** End-user verification step; can't be agent-driven. Run after slice 6 produces an installer. |

## Deviations from the plan above (and the *why*)

1. **scipy on 32-bit Python 3.10** — pr1.md slice 2 step 1 says `pip install -r requirements.txt` works in the 32-bit venv. It doesn't. scipy stopped publishing 32-bit Windows wheels around scipy 1.10 and there is no cp310-win32 wheel at all. Workarounds:
   - `requirements-sidecar.txt` is the 32-bit subset (no scipy, matplotlib, python-docx).
   - `requirements.txt` stays as the 64-bit dev/test deps (full set).
   - `pyproject.toml`'s runtime `dependencies` are 32-bit-safe; `optional-dependencies.dev` carries scipy/matplotlib/python-docx for the 64-bit env.
   - `macs_automation/sampling.py` lazy-imports scipy inside the LHS functions so `from macs_automation.sampling import FIRE_LOAD_PRESETS` works without scipy.
   - Implication: LHS code paths fail at call-time on the bundled sidecar, which is fine — LHS is deferred to a follow-up PR.

2. **Vite output dir** — pr1.md doesn't specify, but Vite defaults to `dist/` which collides with PyInstaller's `dist/i-macs-sidecar/`. We use `dist-frontend/` instead. `vite.config.ts` sets `build.outDir`; `src-tauri/tauri.conf.json` sets `frontendDist: "../dist-frontend"`. Both `.gitignore`'d.

3. **`ureq` JSON feature** — slice 3 step 3 doesn't mention it. We needed `ureq::Response::into_json()` to parse `/healthz` so the shell knows whether to pop the MACS+-missing dialog. `Cargo.toml` carries `features = ["tls", "json"]`.

4. **`SidecarReadyGate` component** — not in pr1.md. The original setup hook in `main.rs` was async-spawn for the health check, which let React mount before `/healthz` was reachable → `Failed to fetch` → error boundary fired. The gate listens for the Tauri `sidecar-ready` event AND polls `/healthz` directly with backoff (so a missed event doesn't strand the UI). Lives at `src/components/SidecarReadyGate.tsx`, wraps `Routes` inside `App.tsx`.

5. **CORS middleware** — not in pr1.md. The Tauri webview's origin (`tauri://localhost` in prod, `http://localhost:1420` in dev) is cross-origin to `http://127.0.0.1:<port>`. `app.py` adds `CORSMiddleware(allow_origins=["*"])` — safe because the sidecar binds 127.0.0.1 only.

6. **Slice 4.5 — Playwright** — pr1.md decision #13 explicitly defers Playwright to v2. We added it anyway because vitest can't exercise the actual `useQuery`/`useMutation` plumbing across the form, and the gate-race bug above wouldn't have been caught by anything else. Tests live in `tests/e2e/`, run against `vite preview` on :4173, mock Tauri commands via string-template `addInitScript` and the sidecar via `page.route()`. Don't tear it back out.

7. **Reorganised pyproject.toml** — slice 1 quietly added `[build-system]`, `[tool.setuptools.packages.find]`, and the runtime/dev deps split. pr1.md doesn't mention this; it was forced by `pip install -e .` failing with the new `docs/` directory.

## Open issues (known gotchas for a fresh agent)

- **Pre-existing pytest failure**: `test_submit_run_with_custom_deck` in `macs_automation/tests/test_custom_sections.py:528` (or near there) expects `deck_type == "R"` but `app.py:api_submit_run`'s deck-id resolution returns `"T"`. Verified pre-existing by `git stash` on the `slab-weight-and-beam-failure-fixes` branch. **Don't try to fix as part of slice 1–7** — file as a separate issue. The bug appears to be in how `resolve_deck` consults `params["DeckId"]` vs `params["deck_id"]` after `api_submit_run`'s alias mapping.
- **`tauri.conf.json` pubkey is a placeholder**. The string `REPLACE_ME_WITH_GENERATED_PUBKEY_IN_SLICE_6` will fail at first updater check. Replace per `RELEASE.md` step 3 before tagging.
- **`src-tauri/binaries/i-macs-sidecar-x86_64-pc-windows-msvc/`** must exist before `cargo check` / `cargo build` succeeds (the bundle's `resources` glob errors out otherwise). Run `scripts/build-sidecar.ps1` to populate it. The CI workflow does this automatically.
- **Tauri dev requires the 32-bit venv at `venv-32/`**. `main.rs:spawn_sidecar` prefers `venv-32/Scripts/python.exe`. If only a 64-bit `venv/` exists, the COM bridge will fail at run time (FRACOF is 32-bit only).
- **`pip install -r requirements.txt`** will fail on 32-bit Python (scipy can't build). Use `requirements-sidecar.txt` for the 32-bit venv; `requirements.txt` for the 64-bit dev venv.

## What a fresh agent should do next

In priority order:

1. **CI workflow** (`.github/workflows/ci.yml`) — runs vitest + Playwright + pytest on every PR. Currently only `release.yml` exists; PRs are unguarded. ~1 hour. The Playwright job needs `npx playwright install --with-deps chromium`. This is the highest-leverage outstanding item and fully agent-actionable.
2. **Polish slice 5** — wire the per-side `edge`/`composite`/`sh_con` flags + steel-grade selects into the form. The DEFAULTS cover them today, but a real engineer will need them. ~2 hours.
3. **Fix the pre-existing deck_type bug** — once you've reproduced it, the fix is small (probably normalising `DeckId` vs `deck_id` in `resolve_deck`'s key lookup or in `api_submit_run`'s alias map).
4. **Sweep / LHS / FRC / report follow-up PRs** — listed in *Out of scope* above. Each is its own PR per the original plan; the sweep one is biggest because it pulls in `docs/archive/pr1_per_side_csv_ux.md` and live dashboard + Plotly + SSE.

For slice 6 finalisation (signer-generate, secrets, pubkey, tag-and-push), an agent **cannot** do these — they need human interaction with the keyboard (passphrase prompt) and GitHub repo settings. The runbook is `RELEASE.md`.
