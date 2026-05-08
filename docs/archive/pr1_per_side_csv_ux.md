# PR 1 Plan — Per-side beams, float inputs, CSV sweep upload

> Three UX upgrades to the desktop config builder. All in `macs_automation/app.py` and `macs_automation/templates/config.html`. Sweep backend already supports everything we need — most work is client-side. Build order is TDD; e2e covers what unit tests can't reach. Read end-to-end before touching code.

## Goal

Three independent improvements to the MACS+ desktop UI:

1. **Per-side beams** — surface the 4-side beam configuration that the engine already supports, with an "All sides identical" default so the common case stays one click.
2. **Float numeric inputs** — drop the rounding-to-step behaviour on numeric fields (e.g. mesh axis was step=5, slab depth step=10). Allow any decimal.
3. **CSV upload for sweep values** — let the user paste/upload a comma-or-newline-separated list of values for any varying numeric param in sweep mode, replacing the min/max/step generator for that one parameter.

When done: a fresh `python -m macs_automation` lets the engineer (a) configure each of the 4 perimeter beams independently when needed, (b) type any decimal into any numeric field, (c) upload one CSV per param to drive sweep values explicitly. Existing single-run, FRC-import, LHS, and dashboard flows continue to work unchanged.

## Starting state (already in place)

- App: `macs_automation/app.py` (FastAPI). Templates in `macs_automation/templates/`. We are **only** building this app, not `macs_automation/web/` (per CLAUDE.md).
- Sweep backend (`macs_automation/sweep.py`):
  - `BEAM_SIDE_MAP` (lines 54-63) maps `side_a/b/c/d` to internal `SideASecSize`/`fy1`/`SideAEdgeFlag`/`SideACompoFlag`/`SideAsh_con` etc. Already supports per-side input.
  - `generate_combinations()` (lines 95-171) does `itertools.product` over `sweep[param]` — accepts arbitrary lists. **Backend needs no change for CSV.**
- DB schema (`macs_automation/db.py:9-49`) already has all 4 sides (`side_a/b/c/d_sec`/`fy`/`edge`/`composite`/`sh_con`). **No migration.**
- Engine (`macs_automation/engine.py:104-204`) already calls per-side properties; it's the UI that collapses them via the unified "Perimeter" fieldset (`config.html:283-329`) which replicates Side A across all four on submit (`config.html:863-873`).
- FRC parser (`macs_automation/frc_parser.py`) already returns `SideASecSize`/`SideBSecSize`/`SideCSecSize`/`SideDSecSize` independently — the existing UI collapses them on import (`config.html:606-616`).
- Tests: `pytest` is green. Existing relevant tests:
  - `tests/test_app.py` — FastAPI TestClient with mocked ref data and tmp DB.
  - `tests/test_sweep.py` — `generate_combinations` correctness.
  - `tests/conftest.py` — `populated_db` fixture, `_insert_populated_run` helper (already populates all 4 sides).

## Architecture decisions (locked)

| #  | Topic | Decision |
|----|---|---|
| 1  | Per-side default UX | Top-level radio inside the "Beams — Perimeter" fieldset: `All sides identical` (default) / `Configure per side`. Identical mode keeps the existing single block. Per-side mode reveals 4 sub-fieldsets (Side A/B/C/D) each with section + fy + edge + composite + sh_con. |
| 2  | Per-side fields | 5 fields per side: `section`, `fy`, `edge` (checkbox), `composite` (checkbox), `sh_con` (numeric, %). Five — not four — because `engine.py:115-118` reads `sh_con` per side. |
| 3  | FRC import behaviour | Auto-detect. If all four `SideX*` values from FRC match → unified mode (current behaviour). If they differ → switch radio to per-side and populate each side independently. Use lossless mapping; the existing `params.SideA*…SideD*` fields are already in the parsed FRC. |
| 4  | Sweep picker | Per-side beam sections are NOT added to the "Parameters to vary" picker. Sections stay fixed across a sweep batch (out of scope; backlog). |
| 5  | DB schema | Unchanged. All side columns already exist. |
| 6  | Float `step` — float params | `step="any"` on: span1, span2, fck, slab_depth, mesh_axis, ush_con, lead_var_act, othr_var_act, cold_perm, lead_var_fac, othr_var_fac, Lc, Bc, Hc, Hw, Lw, window_percent, qf, Bfac, growth_rate, combustion_factor. Also custom-section/deck/mesh add-forms (h, b, tw, tf, deck_depth, deck_trug, deck_top, deck_bot, deck_stiff_height, main_area, trans_area). |
| 7  | Float `step` — integer params | `numbeam` and `time_limit` keep `step="1"` (count and minutes; SQL INTEGER columns). Edge/composite/SteelDeck checkboxes unchanged. |
| 8  | CSV scope | Sweep mode only. Hidden in single-run and LHS. CSV upload control appears inside the per-param `sweep-extra` block, alongside min/max/step. |
| 9  | CSV format | Split on commas AND newlines. Strip whitespace. Skip empty tokens. Every remaining token must parse via `parseFloat` to a finite number. No header detection — fail loudly with the bad token if any token is non-numeric. |
| 10 | CSV affects integer params | `numbeam` and `time_limit` do NOT show a CSV button (they don't appear in the picker today; if added later, integer parsing applies). |
| 11 | CSV UI states | Unloaded: `[Upload CSV] (no file)`. Loaded: `[Clear] · 121 values · 10.0–95.0`. Loading visually disables the min/max/step inputs in the same `sweep-extra` block via a `data-csv-loaded` attribute (still present in DOM so the user can clear and revert). |
| 12 | CSV state lifecycle | Per-param `Map<string, number[]>`. Cleared when (a) user clicks `[Clear]`, (b) param chip is deselected, (c) run-mode radio changes. |
| 13 | CSV size warning | If projected combination count (Cartesian product across all selected sweep params) > 10,000 at submit time, show a `confirm()` dialog. No hard cap. |
| 14 | Backend impact | `app.py`: extend FRC import response so the JS can populate per-side fields (already there — `parse_frc_string` returns all four sides). One small `app.py` change: the single-run handler currently relies on JS replicating to `side_a/b/c/d_*` keys; that JS path stays — adapt it to send per-side values when the radio is in per-side mode. **No new endpoints.** |
| 15 | Test strategy | TDD: failing pytest test → implementation → green. Python-side tests for everything that survives a TestClient round-trip (per-side payload, sweep CSV-list payload, template-rendered `step="any"` attributes). Playwright Python for the CSV file-upload flow that pytest can't reach. Marked `@pytest.mark.e2e`; skipped automatically if Playwright/browsers absent. |
| 16 | E2E framework | Playwright Python (`pip install playwright pytest-playwright` + `playwright install chromium`). Chosen over Vitest because it doesn't introduce a Node toolchain, runs in the same `pytest` invocation as the rest of the suite, and exercises the actual rendered page. |

## Build order (TDD — failing test first, then implementation, then green)

Implementation is split into three slices that can be reviewed independently. Within each slice, write the failing test first; the implementation must be the minimum that turns the test green. Refactor only after green.

### Slice 1: Float `step="any"` (smallest, additive — do first)

1. **Test (`tests/test_app.py::TestConfigPageRendering`):** new class. Use `TestClient(app).get("/")` to render the config page; assert that a known float param input (e.g. `name="mesh_axis"`) carries `step="any"` and a known integer param (`name="numbeam"`) carries `step="1"`. One test method per category.
2. **Implementation:** modify the `param_field` macro in `templates/config.html:5-24` and its callsites. Either change every callsite's `step="…"` to `step="any"`, or change the macro's default and override only for `numbeam`/`time_limit`. Apply the same to the standalone `<input type="number">` blocks in the custom-section / custom-deck / custom-mesh `<details>` panels.
3. **Done when:** new tests pass; existing tests still pass; manual page render in a browser shows that any decimal can be typed.

### Slice 2: Per-side beams (UI restructure)

1. **Test (`tests/test_app.py::TestPerSideBeams`):** new class.
   - `test_post_run_with_distinct_per_side_values`: POST `/api/runs` with `side_a_sec="IPE_500", side_b_sec="IPE_300", side_c_sec="HE_300A", side_d_sec="IPE_500"` plus distinct fy/edge/composite/sh_con per side. Mock `_run_single_com` to capture `params`. Assert each side's value reached `params` independently (no replication).
   - `test_post_run_unified_mode_replicates`: when only `perim_sec` is sent (legacy), still replicates to all 4 sides (back-compat for any direct API caller).
   - `test_frc_import_per_side_detected`: feed an FRC string with mismatched per-side values to `/api/import-frc`; assert response includes all 4 distinct values.
2. **Implementation:**
   - **Template (`templates/config.html`):**
     - Inside the "Beams — Perimeter" fieldset, add a radio:
       ```
       ( ) All sides identical    ( ) Configure per side
       ```
     - Wrap the existing unified block in a `<div id="perim-unified">` (visible by default).
     - Add a `<div id="perim-per-side" hidden>` containing 4 sub-fieldsets (`<details open>` so each can be collapsed) labelled Side A/B/C/D, each with: section `<select>`, fy `<select>`, edge checkbox, composite checkbox, sh_con `<input type="number" step="any">`. Reuse the section dropdown rendering pattern from the unified block.
   - **JS (`templates/config.html` `<script>` block):**
     - Toggle visibility on radio change.
     - On form submit (single-run path): if radio is `unified`, replicate as today (lines 863-873). If radio is `per-side`, read `side_{a,b,c,d}_sec`/`fy`/`edge`/`composite`/`sh_con` directly from the per-side inputs and put them on `params`.
     - On FRC import (`importFrc`, lines 537-636): inspect `params.SideASecSize..SideDSecSize`, `fy1..fy4`, `SideAEdgeFlag..SideDEdgeFlag`, `SideACompoFlag..SideDCompoFlag`, `SideAsh_con..SideDsh_con`. If all four match across each field → set radio to `unified` and populate the unified block (current behaviour). Else → set radio to `per-side`, reveal the per-side block, and populate each side from its FRC value.
   - **`app.py`:** no changes required (it already reads `side_a_sec`/`side_b_sec`/etc through `PARAM_ALIASES` in `sweep.py`).
3. **Done when:** new TestClient tests pass; existing single-run and FRC-import tests still pass; an FRC file with mixed sides round-trips into the form correctly.

### Slice 3: CSV upload for sweep values

1. **Test (`tests/test_sweep.py::TestSweepWithExplicitLists`):** verify that `generate_combinations({"sweep": {"qf": [400, 510.5, 600, 720]}, "fixed": {…}})` produces exactly 4 combinations with those qf values. *(This may already be covered — confirm and add if missing.)*
2. **Test (`tests/test_app.py::TestSweepEndpointAcceptsLists`):** POST `/api/sweeps` with `{"sweep": {"window_percent": [10, 25, 50.5, 95], "qf": [400, 510]}, "fixed": {…}}`; mock the COM background thread; assert the batch was created with `total = 8` and the first combination has the expected values.
3. **Test (Playwright, `tests/test_e2e_ui.py::test_csv_upload_drives_sweep_values`):** new file, marked `@pytest.mark.e2e`.
   - Spin up `app` on an ephemeral port via `uvicorn` in a thread (or `pytest-asyncio` task).
   - Mock `_run_single_com` so the COM call is replaced by an instant deterministic stub returning fake outputs (so the test doesn't need MACS+ installed).
   - Open `/`, switch to sweep mode, click the `qf` chip, click its CSV upload button, `page.set_input_files(..., "fixture.csv")` with `400,500,600\n720`. Assert the on-screen indicator reads `4 values · 400.0–720.0`. Submit, navigate to `/dashboard`, wait for completion, then query the DB and assert 4 runs with those qf values exist.
4. **Implementation:**
   - **Template (`templates/config.html`):**
     - Inside the `param_field` macro (or via a parallel injected element on the picker chip's matching `label`), add an `<input type="file" accept=".csv,.txt" hidden>` plus a styled button that triggers it, plus a status `<span>`. Markup must be discoverable from JS by `data-param`.
   - **JS:** new helper module-style block:
     ```
     const csvValues = new Map();   // paramName -> number[]
     function parseCsvText(text) { … }   // splits on /[,\n\r]+/, strips, parses; throws with bad token
     function attachCsvHandlers() { … }
     ```
     - On file change: read as text, call `parseCsvText`. On error, render the bad token inline and clear. On success, store in `csvValues` and update label to `[Clear] · N values · min–max`. Set `data-csv-loaded` on the matching label so CSS greys the min/max/step inputs.
     - On `[Clear]`: delete from map, restore inputs.
     - In `buildSweepRange(name)` (lines 740-751), short-circuit: if `csvValues.has(name)` return `csvValues.get(name)`.
     - In `toggleMode()` and chip-deselect: clear `csvValues` for affected params.
     - At submit time: compute Cartesian product size from `Object.values(sweep)`; if > 10000, `if (!confirm(`This sweep will run \${n} combinations. Continue?`)) return;`.
   - **CSS:** add `[data-csv-loaded] .sweep-input { opacity: 0.5; pointer-events: none; }` (or equivalent) in `static/` or inline.
   - **No backend change.**
5. **Done when:** unit tests pass; the Playwright e2e test passes locally with `pytest -m e2e`; manual upload of a malformed CSV shows the failing token inline; clearing the CSV reverts to min/max/step generation.

## Done criteria

- `pytest` (without `-m e2e`) is green. Coverage on changed Python paths ≥ existing baseline (no regressions).
- `pytest -m e2e` (after `playwright install chromium`) passes the new `test_e2e_ui.py`.
- Browser smoke check (manual once at the end):
  - Single run with default unified perimeter still works.
  - Switch to per-side mode, set Side A = IPE_500, Side B = IPE_300, others IPE_500. Run. Verify the run-detail page shows distinct sides.
  - In sweep mode, type `9.123` into Span 1 — accepted, no rounding.
  - In sweep mode, click the `qf` chip, upload a CSV `400,500,600,720`. Submit. Dashboard shows 4 runs queued with those qf values.
  - Import an FRC file with non-matching per-side values — radio flips to `per-side` and each side populates correctly.
- No changes to `macs_automation/web/` (per CLAUDE.md).
- No new database columns; no new HTTP endpoints.

## Out of scope (deferred to later PRs / backlog)

- Per-side beam values in the sweep picker (vary section per side across runs).
- Vitest / pure-JS unit tests for the CSV parser (Playwright covers the integrated flow).
- Resume capability for sweeps that include CSV-driven params (existing `run_exists` keying may not pick up float-equality in the right places — confirm in a follow-up).
- CSV upload for `numbeam` / `time_limit` (need integer parse path).
- Hard cap on combination count (current is soft-warning only).
- Re-running the existing batch DOCX report with per-side variations highlighted (existing report renders all four sides already; visual polish pending).

## Sources

- `CLAUDE.md` — only `macs_automation/app.py` is in scope; `macs_automation/web/` is deprecated.
- `macs_automation/sweep.py:11-63` — `DEFAULTS`, `PARAM_ALIASES`, `BEAM_SIDE_MAP` (per-side support already wired).
- `macs_automation/sweep.py:95-171` — `generate_combinations` accepts arbitrary list values; backend supports CSV-driven sweeps with no change.
- `macs_automation/engine.py:115-204` — confirms per-side `sh_con` and section dimensions are read independently.
- `macs_automation/templates/config.html:283-329` — current unified perimeter fieldset.
- `macs_automation/templates/config.html:606-616` — current FRC-import flow that collapses Side A onto unified perimeter.
- `macs_automation/templates/config.html:740-751` — `buildSweepRange()` is the integration point for CSV override.
- `macs_automation/templates/config.html:863-873` — current Side A → Side B/C/D replication on single-run submit.
- `macs_automation/db.py:23-25, 39-42` — all four sides already exist in `runs` schema.
- `macs_automation/tests/conftest.py:91-142` — `_insert_populated_run` already populates all 4 sides; reuse pattern in new tests.
- `macs_automation/tests/test_app.py:81-120` — TestClient / fixtures pattern.
- `email-filer/PR1_PLAN.md` — TDD slicing template followed for this doc.
