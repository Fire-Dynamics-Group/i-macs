"""Degree-of-shear-connection check, mirroring MACS+ exactly.

MACS+ flags a beam when, for an *internal* beam (edge flag 0), its degree of
shear connection falls below the EN 1994-1-1 minimum:

    eta_min = 1 - (355 / fy) * (0.75 - 0.03 * span)        # span in metres

and ``sh_con / 100 < eta_min``. This is the whole of MACS+'s ``CheckBeam``
(``TABs.js:571``). Two deliberate fidelity points:

- **No EN clamps.** MACS+ uses the bare formula — no ``>= 0.40`` floor and no
  ``span > 25 m -> 1.0`` cap that EN 1994-1-1 cl. 6.6.1.2 itself defines. To
  *match MACS+* we omit them too. (This is why a colleague saw "40%": their
  span simply computed to ~0.40, not because 40% is a threshold.)
- **Advisory only.** MACS+ warns and still runs the analysis (``PrintP.js``
  prints the warning alongside the result). It is NOT a pass/fail gate, so this
  module is intentionally separate from ``status.compute_status``.

Per-beam inputs (from ``CheckBeams`` in ``TABs.js`` / ``PrintP.js``):

    unprotected -> span1, fy5   (always internal + composite)
    Side A      -> span1, fy1
    Side B      -> span2, fy2
    Side C      -> span1, fy3
    Side D      -> span2, fy4

Perimeter sides are only checked when composite (``CompoFlag == 1``); edge beams
(``EdgeFlag != 0``) are never flagged.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

# (display name, sh_con col, fy col, span col, edge col, composite col)
# edge/composite None => always internal/composite (the unprotected beam).
BEAMS = (
    ("Unprotected", "ush_con", "u_sec_fy", "span1", None, None),
    ("Side A", "side_a_sh_con", "side_a_fy", "span1", "side_a_edge", "side_a_composite"),
    ("Side B", "side_b_sh_con", "side_b_fy", "span2", "side_b_edge", "side_b_composite"),
    ("Side C", "side_c_sh_con", "side_c_fy", "span1", "side_c_edge", "side_c_composite"),
    ("Side D", "side_d_sh_con", "side_d_fy", "span2", "side_d_edge", "side_d_composite"),
)


def eta_min(fy, span) -> float:
    """EN 1994-1-1 minimum degree of shear connection, as a fraction (0..1).

    Bare formula, matching MACS+ (no 0.40 floor, no span>25m cap).
    """
    return 1.0 - (355.0 / float(fy)) * (0.75 - 0.03 * float(span))


def is_below_min(sh_con_pct, fy, span) -> bool:
    """True when sh_con (percent) is below the MACS+/EN minimum for fy + span."""
    return float(sh_con_pct) / 100.0 < eta_min(fy, span)


def _flag(value) -> int | None:
    """Normalise an edge/composite flag (int, float, or string) to an int."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def check_beam(edge_flag, sh_con_pct, fy, span) -> bool:
    """Exact port of MACS+ ``CheckBeam`` — True means "below the EN minimum".

    Only internal beams (edge flag 0) are ever flagged.
    """
    if _flag(edge_flag) == 0:  # internal beam
        return is_below_min(sh_con_pct, fy, span)
    return False


def _get(row, key):
    """Read a column from a dict or sqlite3.Row, returning None if absent."""
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def flags_for_run(row) -> list[dict]:
    """Return the beams in this run that fall below the MACS+/EN minimum.

    Each entry: {beam, sh_con, fy, span, eta_min_pct}. Empty list means the run
    raises no shear-connection warning. Beams with missing inputs are skipped.
    """
    flags = []
    for name, sh_col, fy_col, span_col, edge_col, comp_col in BEAMS:
        sh_con = _get(row, sh_col)
        fy = _get(row, fy_col)
        span = _get(row, span_col)
        if sh_con is None or fy is None or span is None:
            continue

        # Perimeter sides are only checked when composite; the unprotected beam
        # (comp_col is None) is composite by nature.
        if comp_col is not None and _flag(_get(row, comp_col)) != 1:
            continue

        # The unprotected beam (edge_col is None) is always internal ('0').
        edge_flag = 0 if edge_col is None else _get(row, edge_col)
        if check_beam(edge_flag, sh_con, fy, span):
            flags.append({
                "beam": name,
                "sh_con": float(sh_con),
                "fy": fy,
                "span": float(span),
                "eta_min_pct": round(eta_min(fy, span) * 100.0, 1),
            })
    return flags


def scan_db(db_path, batch_id: str | None = None) -> list[dict]:
    """Scan a results.db for runs that raise a shear-connection warning.

    Returns one entry per flagged run: {run_id, batch_id, flags}. Runs whose
    beams are all at or above the limit are omitted.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if batch_id is None:
            rows = conn.execute("SELECT * FROM runs")
        else:
            rows = conn.execute("SELECT * FROM runs WHERE batch_id = ?", (batch_id,))
        results = []
        for row in rows:
            flags = flags_for_run(row)
            if flags:
                results.append({
                    "run_id": _get(row, "id"),
                    "batch_id": _get(row, "batch_id"),
                    "flags": flags,
                })
        return results
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="List runs whose degree of shear connection is below the "
                    "EN 1994-1-1 minimum (matching the MACS+ beam-check warning)."
    )
    parser.add_argument("--db", required=True, help="Path to results.db")
    parser.add_argument("--batch", default=None, help="Limit to one batch_id")
    args = parser.parse_args(argv)

    if not Path(args.db).is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2

    results = scan_db(args.db, batch_id=args.batch)
    if not results:
        print("No sub-limit runs: every checked beam is at or above the "
              "EN 1994-1-1 minimum degree of shear connection.")
        return 0

    total = sum(len(r["flags"]) for r in results)
    print(f"{len(results)} run(s) with {total} sub-limit beam(s):\n")
    print(f"{'run':>6}  {'batch':<12}  {'beam':<12}  {'sh_con':>7}  {'EN_min':>7}")
    print("-" * 52)
    for r in results:
        for f in r["flags"]:
            print(f"{str(r['run_id']):>6}  {str(r['batch_id'])[:12]:<12}  "
                  f"{f['beam']:<12}  {f['sh_con']:>6.0f}%  {f['eta_min_pct']:>6.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
