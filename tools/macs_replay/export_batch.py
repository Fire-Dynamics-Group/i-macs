"""Export a finished batch as per-run .frc files for MACS+ PDF replay.

    python tools/macs_replay/export_batch.py --batch-id <id> --out <dir>
    python tools/macs_replay/export_batch.py --batch-id <id> --out <dir> --sample 200

Reads the batch's seed .frc out of `frc_imports`, works out which inputs the
batch actually varied, and writes one .frc per run plus a manifest for
`Invoke-MacsReplay.ps1` to consume.

Which parameters varied is derived from the **run rows**, not from
`batches.config_json` — that column records the form's intent and has been
seen naming 2 of 61 varied inputs on a real batch. The rows are what MACS was
actually given.

Any input that varies but cannot be mapped onto a property in the seed .frc is
a hard error. Guessing, or skipping it, would produce a full set of
well-formed, plausible, wrong PDFs.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from macs_automation.frc_parser import _SKIP_PROPS  # noqa: E402
from macs_automation.replay_frc import UnknownParameterError, build_replay_frc  # noqa: E402

# Structural template used by --from-runs. Only its shape and its UI-only
# properties survive; every engine input is overwritten from the run row.
DEFAULT_TEMPLATE = Path(__file__).resolve().parents[2] / "macs_automation/tests/fixtures/atlantic_park_run00000.frc"

# Written by LoadJob bookkeeping, not engine inputs.
_NON_INPUT_PROPS = {"CurrentTab", "CurrentGroup", "CurrentTabs", "InputTabEnablers"}

# Input columns on `runs`, per db.py's schema. Outputs, timings and provenance
# are deliberately absent: a varying output is expected and means nothing here.
INPUT_COLUMNS = [
    # Geometry
    "span1", "span2", "numbeam",
    # Deck
    "steel_deck", "deck_name", "deck_type", "deck_depth", "deck_trug",
    "deck_top", "deck_bot", "deck_stiff_height",
    # Slab
    "conc_type", "conc_lambda", "fck", "slab_depth", "mesh_type",
    "mesh_area_max", "mesh_area_min", "mesh_axis", "mesh_strength",
    # Beams
    "u_sec_size", "u_sec_fy", "ush_con",
    "side_a_sec", "side_a_fy", "side_a_edge", "side_a_composite", "side_a_sh_con",
    "side_b_sec", "side_b_fy", "side_b_edge", "side_b_composite", "side_b_sh_con",
    "side_c_sec", "side_c_fy", "side_c_edge", "side_c_composite", "side_c_sh_con",
    "side_d_sec", "side_d_fy", "side_d_edge", "side_d_composite", "side_d_sh_con",
    # Loading
    "lead_var_act", "othr_var_act", "cold_perm", "slab_weight",
    "lead_var_fac", "othr_var_fac",
    # Fire
    "method", "time_limit", "Lc", "Bc", "Hc", "Hw", "Lw",
    "window_percent", "qf", "Bfac", "combustion_factor", "growth_rate",
]

# Most run columns are named after the .frc property directly. Only genuine
# mismatches belong here; anything absent falls back to an identity match that
# is verified against the seed file, so a wrong guess fails loudly rather than
# writing a file that ignores it.
COLUMN_ALIASES = {
    "method": "Method",
    "u_sec_size": "uSecSize",
    "steel_deck": "SteelDeck",
    "deck_name": "DeckName",
    # fy1 is the unprotected beam, fy2..fy5 are sides A..D. Verified against a
    # real batch: with these aliases the seed check reports no disagreement.
    "u_sec_fy": "fy1",
    "side_a_fy": "fy2",
    "side_b_fy": "fy3",
    "side_c_fy": "fy4",
    "side_d_fy": "fy5",
}
for _side in "ABCD":
    _col = _side.lower()
    COLUMN_ALIASES[f"side_{_col}_sec"] = f"Side{_side}SecSize"
    COLUMN_ALIASES[f"side_{_col}_sh_con"] = f"Side{_side}sh_con"
    COLUMN_ALIASES[f"side_{_col}_composite"] = f"Side{_side}CompoFlag"
    COLUMN_ALIASES[f"side_{_col}_edge"] = f"Side{_side}EdgeFlag"

# i-macs stores the fire model as text; MACS stores the combo index.
METHOD_TO_FRC = {"iso": "0", "parametric": "1", "udf": "2"}


def default_db() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "i-macs" / "results.db"
    return Path("results.db")


def seed_xml_for(conn: sqlite3.Connection, batch_id: str, override: Path | None) -> str:
    row = conn.execute(
        "SELECT frc_import_id, name FROM batches WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"no such batch: {batch_id}")

    if override:
        return override.read_text(encoding="utf-8-sig")

    if not row["frc_import_id"]:
        raise SystemExit(
            f"batch {batch_id} has no frc_import_id, so its seed .frc is unknown.\n"
            "Replay needs the original file to reproduce every input the batch did\n"
            "not vary. Pass --seed <file.frc> to supply it; the fixed inputs are\n"
            "then checked against the run rows before anything is written."
        )
    imp = conn.execute(
        "SELECT xml FROM frc_imports WHERE id = ?", (row["frc_import_id"],)
    ).fetchone()
    if imp is None or not imp["xml"]:
        raise SystemExit(f"frc_import {row['frc_import_id']} is missing or empty")
    return imp["xml"]


def _values_agree(seed_raw: str, run_value) -> bool:
    seed_text = unquote(seed_raw)
    # Some properties are pipe-composites where the run column holds only the
    # primary field — ush_con is "41|355|8" in the .frc but 41.0 in `runs`.
    if "|" in seed_text:
        seed_text = seed_text.split("|", 1)[0]
    try:
        return abs(float(seed_text) - float(run_value)) <= 1e-6 * max(1.0, abs(float(run_value)))
    except (TypeError, ValueError):
        return seed_text.strip() == str(run_value).strip()


def reconstructable_columns(template_xml: str, run: sqlite3.Row) -> tuple[list[str], list[str]]:
    """Split the run's input columns into those the template can carry and those it can't."""
    root = ET.fromstring(template_xml)
    props = {p.get("Name") for p in root.iter("Property")}
    available = set(run.keys())
    ok, missing = [], []
    for col in INPUT_COLUMNS:
        if col not in available:
            continue
        (ok if COLUMN_ALIASES.get(col, col) in props else missing).append(col)
    return ok, missing


def residual_properties(template_xml: str, columns: list[str]) -> list[str]:
    """Engine inputs in the template that no run column overrides.

    These are inherited from the template rather than reconstructed, so they are
    the entire risk of --from-runs and are reported rather than hidden. UI-only
    properties (per frc_parser._SKIP_PROPS) are excluded because they do not
    reach the engine.
    """
    root = ET.fromstring(template_xml)
    inp = root.find("Input")
    overridden = {COLUMN_ALIASES.get(c, c) for c in columns}
    return sorted(
        p.get("Name")
        for p in inp.iter("Property")
        if p.get("Name") not in overridden
        and p.get("Name") not in _SKIP_PROPS
        and p.get("Name") not in _NON_INPUT_PROPS
    )


def check_seed_matches_batch(seed_xml: str, run: sqlite3.Row, fixed_columns: list[str]) -> list[str]:
    """Compare the seed's fixed inputs against what the batch actually ran.

    A seed from the wrong job would reproduce every non-varying input
    incorrectly — quietly, because the varying ones would still look right.
    """
    root = ET.fromstring(seed_xml)
    props = {p.get("Name"): p.get("Value", "") for p in root.iter("Property")}
    mismatches = []
    for col in fixed_columns:
        value = run[col]
        if value is None:
            continue
        name = COLUMN_ALIASES.get(col, col)
        if col == "method":
            value = METHOD_TO_FRC.get(value, value)
        if name not in props:
            continue  # not representable in the .frc; nothing to compare
        if not _values_agree(props[name], value):
            mismatches.append(f"{col}: seed={unquote(props[name])!r} batch={value!r}")
    return mismatches


def varying_columns(runs: list[sqlite3.Row]) -> list[str]:
    """Input columns that take more than one value across the batch."""
    available = set(runs[0].keys())
    varying = []
    for col in INPUT_COLUMNS:
        if col not in available:
            continue
        seen = {r[col] for r in runs}
        if len(seen) > 1:
            varying.append(col)
    return varying


def overrides_for(run: sqlite3.Row, columns: list[str]) -> dict:
    out = {}
    for col in columns:
        value = run[col]
        if value is None:
            continue
        name = COLUMN_ALIASES.get(col, col)
        if col == "method":
            if value not in METHOD_TO_FRC:
                raise SystemExit(f"unknown fire method {value!r} on run {run['id']}")
            value = METHOD_TO_FRC[value]
        out[name] = value
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=default_db())
    ap.add_argument("--batch-id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--sample",
        type=int,
        help="export only the first N runs (auditable sample instead of all)",
    )
    ap.add_argument(
        "--seed",
        type=Path,
        help="seed .frc to use when the batch has no stored frc_import "
             "(its fixed inputs are checked against the run rows)",
    )
    ap.add_argument(
        "--from-runs",
        action="store_true",
        help="rebuild every input from the run rows instead of needing the "
             "batch's own seed .frc (uses --template only for structure)",
    )
    ap.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help="structural .frc for --from-runs (default: the repo fixture)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="export even if the seed disagrees with the batch's fixed inputs",
    )
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"no database at {args.db}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.from_runs:
        if not args.template.exists():
            raise SystemExit(f"no template .frc at {args.template}")
        seed = args.template.read_text(encoding="utf-8-sig")
    else:
        seed = seed_xml_for(conn, args.batch_id, args.seed)
    runs = conn.execute(
        "SELECT * FROM runs WHERE batch_id = ? AND (error IS NULL OR error = '') "
        "ORDER BY sample_index, id",
        (args.batch_id,),
    ).fetchall()
    if not runs:
        raise SystemExit(f"batch {args.batch_id} has no successful runs")

    total = len(runs)

    # Work out what varies across the WHOLE batch before sampling. Deriving it
    # from a sample would classify a varying input as fixed whenever the sample
    # happens not to move it — at --sample 1, always — and it would then never
    # be overridden, so every PDF would print the seed's value instead.
    columns = varying_columns(runs)

    if args.sample:
        runs = runs[: args.sample]
    print(f"batch {args.batch_id}: {total} runs, exporting {len(runs)}")
    print(f"varying inputs ({len(columns)}): {', '.join(columns) or '(none)'}")

    if args.from_runs:
        # Rebuild every input from the run row, so the batch's own seed file is
        # not needed. The template supplies structure and UI-only properties.
        columns, unreachable = reconstructable_columns(seed, runs[0])
        blocked = [c for c in unreachable if c in varying_columns(runs)]
        if blocked:
            raise SystemExit(
                "these inputs vary but have no property in the template: "
                + ", ".join(blocked)
                + "\nAdd the correct MACS property name to COLUMN_ALIASES."
            )
        residual = residual_properties(seed, columns)
        print(f"reconstructing {len(columns)} inputs per run from the run rows")
        if residual:
            print(
                f"inherited from the template, NOT reconstructed ({len(residual)}): "
                + ", ".join(residual)
            )
            print(
                "  verify_replay.py compares MACS's uf_max against i-macs's per run, "
                "so any of these that actually matters will show up there."
            )
    else:
        fixed = [c for c in INPUT_COLUMNS if c in runs[0].keys() and c not in columns]
        mismatches = check_seed_matches_batch(seed, runs[0], fixed)
        if mismatches:
            head = f"the seed .frc disagrees with the batch on {len(mismatches)} fixed input(s):"
            detail = "\n".join(f"  {m}" for m in mismatches)
            if not args.force:
                raise SystemExit(
                    f"{head}\n{detail}\n\n"
                    "Those inputs would be reproduced incorrectly in every PDF, silently,\n"
                    "because the varying ones would still look right. Supply the correct\n"
                    "seed, use --from-runs to rebuild the inputs from the batch itself,\n"
                    "or re-run with --force if you are certain."
                )
            print(f"WARNING: {head}")
            print(detail)
        elif fixed:
            print(f"seed agrees with the batch on all {len(fixed)} fixed inputs")

    frc_dir = args.out / "frc"
    frc_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for run in runs:
        idx = run["sample_index"] if run["sample_index"] is not None else run["id"]
        overrides = overrides_for(run, columns)
        try:
            xml = build_replay_frc(seed, overrides)
        except UnknownParameterError as exc:
            raise SystemExit(
                f"run {run['id']}: {exc}\n\n"
                "A varying input has no matching property in the seed .frc. Add it "
                "to COLUMN_ALIASES in this script once you have confirmed the "
                "correct MACS property name — do not drop it, or the replayed PDFs "
                "will silently not reflect it."
            ) from exc
        name = f"run{idx:05d}"
        (frc_dir / f"{name}.frc").write_text(xml, encoding="utf-8")
        entries.append(
            {
                "name": name,
                "run_id": run["id"],
                "sample_index": run["sample_index"],
                "frc": str((frc_dir / f"{name}.frc").resolve()),
                # what the printed report must agree with, so the verifier can
                # catch a run that printed someone else's inputs
                "expect": {
                    "qf": run["qf"],
                    "window_percent": run["window_percent"],
                    "uf_max": run["uf_max"],
                },
            }
        )

    manifest = args.out / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "batch_id": args.batch_id,
                "db": str(args.db.resolve()),
                "total_runs_in_batch": total,
                "exported": len(entries),
                "varying_inputs": columns,
                "runs": entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} .frc files and {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
