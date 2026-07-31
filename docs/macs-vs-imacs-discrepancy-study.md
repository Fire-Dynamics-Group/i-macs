# MACS+ vs i-MACS Unity-Factor Discrepancy Study

Why i-MACS reported **max unity factor 0.686** where MACS+ desktop reported **0.65** for the
same scenario — Atlantic Park Phase 2 Unit 7, run00000 (fire load 656.57 MJ/m²,
glazing 80.22 %). A colleague noted "temperature and capacity look so similar" yet UF differed.

## Root cause (proven against the real FRACOF engine)

The **average mesh axis distance (`mesh_axis`)** is being dropped. The project uses **52 mm**;
i-MACS runs the engine with the backend default **40 mm**.

Running the actual `SCTI9.FRACOF` engine on the run00000 inputs:

| `mesh_axis` | `uf_max` | |
|---|---|---|
| 52 mm (project value) | **0.654** | matches MACS+ 0.65 |
| 40 mm (i-MACS default) | **0.6863** | matches the reported 0.686 |

`mesh_axis` is an **independent MACS+ input** — the cover/axis distance of the reinforcement
mesh from the slab top. It drives tensile-membrane **slab capacity** (hence UF) but barely moves
temperatures, which is exactly the symptom observed. It is **not** derivable from `mesh_type`
(which only fixes bar areas).

## How it was proven (real engine, not guessing)

MACS+ 3.0.4 is installed at `C:\Program Files (x86)\MACS+`; the engine is the 32-bit .NET COM
server `SCTI9.FRACOF` (`Objects\FRACOF.dll`), driven from a 32-bit Python 3.10 venv. (Setup
notes for re-running are at the end.)

**Faithful reproduction** — parse the `.frc`, override only the run00000 sample
(`qf=656.5674`, `window_percent=80.2204`), run `AnalyseUsingParametricFire`:

| Output | i-MACS (real engine) | Reference PDF |
|---|---|---|
| max unity factor | **0.654** | 0.65 |
| factored load | 7.08 | 7.08 |
| side temps A/B/C/D | 705/728/705/728 | 706/728/706/728 |
| UF series | 0.23,0.23,0.22,0.29,0.50,0.65,0.47,0.28,0.22,0.23,0.23,0.23 | identical |

So the **engine and `engine.py` input mapping are faithful**. The discrepancy is purely an
i-MACS **input-assembly** problem upstream of the engine.

**Sensitivity battery** — from the faithful baseline (0.654), flip each suspect to its i-MACS
default/transform and read `uf_max`:

| Change | `uf_max` | Reproduces 0.686? |
|---|---|---|
| **`mesh_axis` 52 → 40 (DEFAULT)** | **0.6863** | **yes — exact** |
| baseline (`mesh_axis` 52) | 0.6540 | — |
| `mesh_area` 193 → 142 | 0.7481 | no |
| `slab_depth` 150 → 130 | 0.6576 | no |
| `fck` 30 → 25 | 0.6565 | no |
| `cold_perm` 0.5 → 1.2 | 0.7187 | no |
| `lead_var_act` 7.5 → 5.0 | 0.5386 | no |
| `Bfac` 1700 → 720 | 0.9677 | no |
| `window` → `(1−x)·100` = 19.78 | 0.8526 | no — **ruled out** |

Only `mesh_axis = 40` reproduces 0.686. The glazing-transform theory is **disproved** (would give
0.85), confirming the run used `window_percent ≈ 80.22` correctly.

## Where the value is lost (code path)

1. `src/types/formValues.ts` — `FormValues` has **no `mesh_axis`** field; only `mesh_type`.
2. `src/lib/hydrateFormFromFrcParams.ts` — `.frc` → form mapping does **not** carry `mesh_axis`
   (nor is it in `SOURCE_KEYS`). The parsed 52 mm is discarded here.
3. `macs_automation/sweep.py` — `resolve_mesh()` sets `mesh_area_max/min` from the mesh DB but
   **not `mesh_axis`**; `DEFAULTS["mesh_axis"] = 40` is the only source, so 40 is always used.
4. `macs_automation/engine.py` — faithfully sends whatever `mesh_axis` it receives (it is in
   `direct_props`). It receives 40.

## Recommended fix

1. Add `mesh_axis` to `FormValues`, the ConfigPage mesh section, `SOURCE_KEYS`, and
   `hydrateFormFromFrcParams` (carry `params.mesh_axis`).
2. Thread `mesh_axis` through the sweep config builder so single-run and sweep paths both send it.
3. Optionally have `resolve_mesh()` supply a sensible per-mesh axis only when none is given.
4. Keep the regression test below green.

## Regression test

`macs_automation/tests/test_e2e_pdf_oracle.py` parses the Atlantic Park `.frc`
(`tests/fixtures/atlantic_park_run00000.frc`), overrides `qf`/`window_percent` to run00000, runs
the real engine, and asserts `uf_max ≈ 0.65`, `factored_hot ≈ 7.08`, side temps 706/728, and the
full UF series. A companion test locks `mesh_axis=40 → 0.686` so the bug cannot silently return.
Skips cleanly when COM/Data.xml are unavailable (gated by `conftest.com_and_data_available`).

## Secondary findings (latent traps — not this bug)

- **glazing → window unit contract** is ambiguous: the LHS path applies `(1−x)·100`, the paired
  path is verbatim, the engine wants 0–100. A 0.8022 vs 80.22 mix-up swings UF hugely (0.85 vs
  0.65). Centralise to one transform + test.
- `perm_var_fac` and `calc_slab_weight` are **not** engine inputs — confirmed in MACS+'s own
  `Scripts/Calc.js` (slab weight is pre-computed in the UI; the permanent-action factor is never
  sent). Dropping them is correct; `engine.py` `direct_props` matches Calc.js's `InputProps`.
- `min/max_mesh_dia` are parsed but unused by the engine — harmless.

## Round 2: blindspot audit against the installed MACS+ scripts (2026-07-31)

A follow-up sweep of `Calc.js`/`PrintP.js`/`TABs.js` for further places where i-MACS output
could diverge from MACS+. All four fixed (tests alongside each):

1. **Second mesh loop was entirely unread.** When `mesh_area_min != mesh_area_max` and
   `OneLoop != 1`, FRACOF computes a second analysis; MACS+ reads `uf2`/`time_intervals_count2`
   (Calc.js 354-379), reports `ufmax = max(UF1Max, UF2Max)` and displays the governing loop's
   table/extremes (`GraphTbl`, `CalcExtremes`). i-MACS read only loop 1 — and `resolve_mesh`
   maps `mainArea`/`transArea`, which differ for every **B-series mesh**, so any such run
   understated `uf_max`. (The 10k corpora are square A193 — historical results unaffected.)
   `engine.py` now mirrors the whole dance (`second_loop` flag, `uf1_max`/`uf2_max`/
   `governing_mesh_loop` in results); `frc_parser` now carries `OneLoop` instead of skipping it.
   Perimeter side ratios stay loop-1 — MACS+'s own FillPerim2Beam prints loop-1 values too.
2. **Side B/D line load didn't match the printed PDF.** PrintP.js computes B/D as
   `8·Mb1_Reqd/(span1·span2)` — not the textbook `8M/span2²` — in *both* report variants
   (lines 524/600). Atlantic Park is 7.3 × 7.48 m, so this was visibly wrong against corpus
   PDFs (23.97 vs 24.56 kN/m). `PerimeterBeamCheck` now reproduces MACS+ verbatim.
3. **Side-ratio verdict threshold.** MACS+ bolds "ratio fails" only at `> 1.01`; `status.py`
   failed at `> 1.0`, so ratios in (1.0, 1.01] disagreed with the PDF. Now 1.01. (Gating the
   overall verdict on side ratios at all is still deliberately stricter than MACS+'s summary
   cell, which reads UF only.)
4. **`calc_slab_weight = 1` never recomputed.** MACS+ recomputes `slab_weight` in the UI before
   every calc (TABs.js `SlabWeight()`); the .frc value is just the last computed one. i-MACS
   held it frozen, so sweeping `slab_depth`/deck geometry diverged — and even pure-DEFAULTS
   runs used the static 2.47 where MACS+ computes **2.28** for that geometry.
   `resolve_slab_weight()` (sweep.py) now mirrors the formula incl. the parseInt rounding;
   validated bit-for-bit against the Atlantic Park .frc (150/Multideck 60 → 2.83). Wired into
   the single-run, sweep and CLI paths after `resolve_deck`/`resolve_mesh`.

Also added: `engine.set_inputs` now logs a warning listing any `InputProps` key absent from
params (MACS+ always sets every input; a missing key silently inherits FRACOF's internal
default — the exact failure class of the original `mesh_axis` bug).

Known remaining divergences (deliberate/accepted): `_get_fy` falls back to 355 where MACS+
returns `undefined` for unknown grades; engine.py prefers `SCTI11.FRACOF` while the 3.0.4 HTA
instantiates `SCTI9` (engine version is stamped on every result, ±3 °C on perimeter critical
temps); `OneLoop` is not threaded through the React form (an imported .frc with `OneLoop=1`
run via the UI computes both loops — rare, and the stricter direction).

## Environment notes (for re-running the real engine on this box)

- `MACS_DATA_PATH=C:\Program Files (x86)\MACS+\EN\Data\Data.xml` — the code default points at
  `MACS+_304`, which doesn't exist here.
- 32-bit Python 3.10 + `venv-32` with `pywin32 numpy pyyaml pytest`. (The full sidecar install
  fails on `httptools` — no 32-bit wheel — but that's the web server, not the engine.)
- The COM ProgID was unregistered on this fresh pull; registered **per-user without admin** via
  `regasm /regfile` → rewrite `HKCR` → `HKCU\Software\Classes` and `…\Wow6432Node` → `reg import`,
  with `RuntimeVersion` forced to `v4.0.30319` (the .NET 2.0 assembly loads fine under the v4 CLR;
  .NET 3.5/CLR v2 is not enabled here).
- MACS+'s authoritative property-setting reference is `C:\Program Files (x86)\MACS+\Scripts\Calc.js`
  (the "Calc.js lines …" cited throughout `engine.py`).
