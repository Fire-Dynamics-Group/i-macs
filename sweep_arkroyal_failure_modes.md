# Failure-mode coverage sweep — Ark Royal Control Office A

A sweep setup that exercises **every branch of the pass/fail verdict** in a
single batch, built from one of the project 0395 `.frc` files:

```
C:\Users\IanShaw\Fire Dynamics Group Dropbox\01 Projects\0000 - Completed\
0395 - Ark Royal (Winvic)\6. Calculations\Control Office A.frc
```

`sweep_arkroyal_control_office_a.yaml` already exercises the slab-UF axis only
(its perimeter-beam ratios stay 0.15–0.40, so UF governs every verdict). This
setup additionally drives the **perimeter-beam** and **error** verdict paths.

## The verdict failure modes

The verdict is `compute_status()` in `macs_automation/status.py`, mirrored by
`_pass_where()` in `macs_automation/db.py`. A run **passes** only when:

- `uf_max < 1.001` — slab utilisation factor, **and**
- `side_{a,b,c,d}_load_ratio <= 1.0` — every defined perimeter-beam load ratio.

So the distinct ways a run can come back **not-PASS**:

| Mode | Trigger | Verdict |
|------|---------|---------|
| Slab UF | `uf_max >= 1.001` | FAIL |
| Side A beam load | `side_a_load_ratio > 1.0` | FAIL |
| Side B beam load | `side_b_load_ratio > 1.0` | FAIL |
| Side C beam load | `side_c_load_ratio > 1.0` | FAIL |
| Side D beam load | `side_d_load_ratio > 1.0` | FAIL |
| Combination | any mix of the above | FAIL (multiple rose rows) |
| Error | run raised — e.g. unknown section | ERROR (`overall_pass = None`) |

## How the sweep reaches them

A sweep YAML is a **Cartesian product** (`itertools.product` in
`sweep.py:generate_combinations`), *not* a curated one-row-per-scenario list.
The failure modes are therefore reached as **corners of a 2×2×3 grid**:

- `mesh_type` — `A393` (strong slab) → `A142` (weak slab) — drives **slab UF**
- `side_b_sec` — as-built → undersized — drives **Side B** (internal beam, `edge=0`)
- `side_c_sec` — as-built → undersized → invalid — drives **Side C** (edge beam) and **ERROR**

Sides A and D are edge beams whose verdict code path is identical to Side C, so
isolating them adds runs without adding coverage. To exercise their UI rows
too, add `side_a_sec` / `side_d_sec` axes the same way (each extra 2-value axis
doubles the run count).

## The sweep config

Save this block as `sweep_arkroyal_failure_modes.yaml` next to the existing
sweep file:

```yaml
# MACS+ sweep — Ark Royal (Winvic), Control Office A — FAILURE-MODE COVERAGE
# Base inputs imported from "Control Office A.frc" (project 0395).
analysis_method: "iso"            # .frc Method=2

sweep:
  mesh_type:  ["A393", "A142"]                                    # slab UF: strong -> weak
  side_b_sec: ["UB_533x210x82", "UB_178x102x19"]                  # Side B: as-built -> undersized
  side_c_sec: ["UB_406x140x39", "UB_178x102x19", "INVALID_X999"]  # Side C: as-built -> undersized -> invalid

fixed:
  # --- Geometry (GA) ---
  numbeam: 2
  span1: 8.225
  span2: 8.5
  # --- Fire ---
  time_limit: 60
  # --- Deck ---
  deck_id: "T8"                   # Multideck 60
  # --- Slab ---
  conc_type: "NW"
  conc_lambda: 1
  fck: 25
  slab_depth: 140
  mesh_axis: 40
  mesh_strength: 500
  # --- Internal (unprotected) secondary beam ---
  u_sec_size: "UB_457x152x52"
  u_sec_fy: "355"
  u_sec_sh_con: 80
  # --- Loading ---
  slab_weight: 2.59
  cold_perm: 1.2
  lead_var_act: 5
  othr_var_act: 0
  lead_var_fac: 0.5
  othr_var_fac: 0.3
  # --- Fire compartment (carried from .frc; inert under ISO) ---
  Lc: 27
  Bc: 18
  Hc: 3.6
  Hw: 1.8
  Lw: 30

# Perimeter (protected) beams — from .frc Beams block.
# side_b / side_c sec_size here is the baseline; the `sweep:` block above
# overrides it per run. fy / edge / composite / sh_con always come from here.
beams:
  side_a:
    sec_size: "UB_457x152x52"
    fy: 355
    edge: true
    composite: true
    sh_con: 80
  side_b:
    sec_size: "UB_533x210x82"
    fy: 355
    edge: false                   # internal beam
    composite: true
    sh_con: 80
  side_c:
    sec_size: "UB_406x140x39"
    fy: 355
    edge: true
    composite: true
    sh_con: 80
  side_d:
    sec_size: "UB_457x152x52"
    fy: 355
    edge: true
    composite: true
    sh_con: 80
```

## Run matrix — 12 runs (2 × 2 × 3)

`itertools.product` varies the **last** sweep key fastest, so the runs land in
this order:

| # | mesh | side_b | side_c | Predicted verdict |
|---|------|--------|--------|-------------------|
| 1 | A393 | UB_533x210x82 | UB_406x140x39 | **PASS** |
| 2 | A393 | UB_533x210x82 | UB_178x102x19 | FAIL — Side C beam load |
| 3 | A393 | UB_533x210x82 | INVALID_X999 | **ERROR** — unknown section |
| 4 | A393 | UB_178x102x19 | UB_406x140x39 | FAIL — Side B beam load |
| 5 | A393 | UB_178x102x19 | UB_178x102x19 | FAIL — Side B + Side C |
| 6 | A393 | UB_178x102x19 | INVALID_X999 | **ERROR** |
| 7 | A142 | UB_533x210x82 | UB_406x140x39 | FAIL — Slab UF |
| 8 | A142 | UB_533x210x82 | UB_178x102x19 | FAIL — Slab UF + Side C |
| 9 | A142 | UB_533x210x82 | INVALID_X999 | **ERROR** |
| 10 | A142 | UB_178x102x19 | UB_406x140x39 | FAIL — Slab UF + Side B |
| 11 | A142 | UB_178x102x19 | UB_178x102x19 | FAIL — Slab UF + Side B + Side C |
| 12 | A142 | UB_178x102x19 | INVALID_X999 | **ERROR** |

Coverage: PASS (1) · Slab-UF only (7) · Side B only (4) · Side C only (2) ·
every multi-fail combination (5, 8, 10, 11) · ERROR (3, 6, 9, 12).

> **Predicted, not verified.** Verdicts above are reasoned, not measured.
> Baselines: slab UF `A393/60min ≈ 0.67` (pass) and `A142/60min ≈ 1.12` (fail)
> are from `sweep_arkroyal_control_office_a.yaml` (verified 2026-05-19). As-built
> perimeter ratios for this `.frc` are ≈ 0.22 (Side B) and ≈ 0.40 (Side C) —
> both pass. Run the batch once on the real FRACOF engine and replace this
> table with measured values.

## Tuning the undersized section

`UB_178x102x19` must push the perimeter-beam load ratio **over 1.0 without the
engine erroring**. FRACOF's behaviour on a grossly undersized section is not
known in advance, so after the verification run:

- If a "FAIL — Side X" run still **passes**, step the section down:
  `UB_178x102x19 → UB_152x89x16 → UB_127x76x13` (smallest UB available).
- If it **ERRORs** instead of failing, step up:
  `UB_178x102x19 → UB_203x102x23 → UB_254x102x22`.

`UB_127x76x13` (Wₚₗ ≈ 84 cm³) is ~8× weaker than the as-built Side C section
and ~24× weaker than Side B, so somewhere in that ladder both sides fail
cleanly.

The invalid value `INVALID_X999` is any string absent from the section
database. `_set_beam_data` does a plain `sections_db[sec_size]` lookup, so it
raises `KeyError`; `run_batch_with_callback` catches it per-run and records the
run with `error` set — the batch keeps going (verified in `runner.py`).

## Running & verifying

```
python -m macs_automation.main --config sweep_arkroyal_failure_modes.yaml \
    --db results.db --no-resume
```

Requires MACS+ installed (for `Data.xml` and the FRACOF COM engine). 12 runs at
~1.3 s each ≈ 16 s. `--no-resume` forces a re-run even if matching rows exist.

Then check the batch in the app's batch view, or query directly:

```sql
SELECT id, mesh_type, side_b_sec, side_c_sec,
       uf_max, side_b_load_ratio, side_c_load_ratio, error
FROM runs WHERE batch_id = '<batch_id>' ORDER BY id;
```

A correct result set shows 1 PASS, 7 FAIL, 4 ERROR.

## Scope note

This sweep covers the **implemented** verdict modes only. The engine also
outputs `side_{a,b,c,d}_critical_temp`, but no verdict gate compares a beam's
in-fire temperature against it — so there is no critical-temp failure path to
test here. If a critical-temp check is later added to `compute_status()`, this
file should grow an axis to exercise it.
