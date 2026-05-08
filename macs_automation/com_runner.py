"""Per-calculation FRACOF COM runner.

Spawned as a subprocess by engine.run_one_com() so a FRACOF crash kills only
the runner — not the parent FastAPI sidecar. Same architecture as the parent
(both 32-bit). Reads {params, sections_db} as one JSON line on stdin and
writes one JSON output line (or {"error": ...}) on stdout.
"""

import json
import sys


def _run_one(params: dict, sections_db: dict) -> dict:
    """Execute one COM run in this process. Returns outputs dict or raises."""
    import pythoncom
    from macs_automation.engine import MACSEngine

    pythoncom.CoInitialize()
    try:
        eng = MACSEngine()
        eng.set_inputs(params, sections_db)
        return eng.run(method=params.get("method", "iso"))
    finally:
        pythoncom.CoUninitialize()


def main():
    """Read one JSON line from stdin, run COM, write one JSON line to stdout."""
    try:
        line = sys.stdin.readline()
        if not line:
            out = {"error": "No input"}
        else:
            data = json.loads(line)
            params = data["params"]
            sections_db = data["sections_db"]
            out = _run_one(params, sections_db)
    except Exception as e:
        out = {"error": f"{type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
