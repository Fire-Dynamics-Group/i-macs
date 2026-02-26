"""Retry failed runs from the most recent batch with clamped qf (fix FRACOF thermal instability).

Run from project root:
  python retry_failed_batch.py [--batch-id BATCH_ID] [--dry-run]

Failed runs are often caused by negative fire load (qf) from LHS Gumbel sampling.
This script re-runs each failed run with qf clamped to max(1.0, qf) and updates
the run row with the new outputs.
"""

import argparse
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from macs_automation.db import ResultsDB
from macs_automation.engine import run_one_com
from macs_automation.data_loader import load_data


MIN_QF = 1.0  # MJ/m² — FRACOF thermal analysis unstable for negative/zero
# Aggressive retry: also clamp window_percent and raise very low qf (use --aggressive)
RETRY_QF_FLOOR = 50.0
WINDOW_PCT_MIN = 1.0
WINDOW_PCT_MAX = 99.0


def main():
    ap = argparse.ArgumentParser(description="Retry failed runs from latest batch with clamped qf")
    ap.add_argument("--batch-id", default=None, help="Batch ID (default: most recent)")
    ap.add_argument("--db", default=None, help="Path to results.db (default: results.db in project root)")
    ap.add_argument("--dry-run", action="store_true", help="Only list failed runs, do not re-run")
    ap.add_argument("--aggressive", action="store_true",
                    help="Also clamp window_percent to [1,99] and qf to min 50 MJ/m² for retry")
    args = ap.parse_args()

    db_path = Path(args.db or ROOT / "results.db")
    if not db_path.is_file():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    db = ResultsDB(db_path)
    batches = db.get_batches()
    if not batches:
        print("No batches in database.", file=sys.stderr)
        db.close()
        sys.exit(1)

    batch_id = args.batch_id or batches[0]["batch_id"]
    if args.batch_id and not any(b["batch_id"] == batch_id for b in batches):
        print(f"Batch not found: {batch_id}", file=sys.stderr)
        db.close()
        sys.exit(1)

    runs = db.get_batch_runs(batch_id)
    failed = [r for r in runs if r.get("error")]
    if not failed:
        print(f"Batch {batch_id[:8]}... has no failed runs.")
        db.close()
        return

    print(f"Batch {batch_id[:8]}...: {len(failed)} failed runs (of {len(runs)} total)")

    if args.dry_run:
        for r in failed[:10]:
            qf = r.get("qf")
            print(f"  run_id={r['id']} qf={qf}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")
        db.close()
        return

    print("Loading sections data...")
    data = load_data()
    sections_db = data["sections"]

    ok = 0
    err = 0
    for i, run_row in enumerate(failed, 1):
        run_id = run_row["id"]
        params = db.run_row_to_params(run_row)
        # Clamp qf (negative/zero causes FRACOF thermal instability)
        qf = params.get("qf")
        if qf is not None:
            params["qf"] = max(RETRY_QF_FLOOR if args.aggressive else MIN_QF, float(qf))
        if args.aggressive:
            wp = params.get("window_percent")
            if wp is not None:
                params["window_percent"] = max(WINDOW_PCT_MIN, min(WINDOW_PCT_MAX, float(wp)))

        try:
            outputs = run_one_com(params, sections_db)
            db.update_run_from_outputs(run_id, params, outputs)
            ok += 1
            if i % 20 == 0 or i == len(failed):
                print(f"  {i}/{len(failed)} OK (run_id={run_id})")
        except Exception as e:
            err += 1
            print(f"  run_id={run_id} failed again: {e}", file=sys.stderr)

    print(f"Done: {ok} updated, {err} still failing")
    db.close()
    if err:
        sys.exit(1)


if __name__ == "__main__":
    main()
