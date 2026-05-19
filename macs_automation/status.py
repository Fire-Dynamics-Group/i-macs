"""Combined pass/fail status for a MACS+ run.

A run passes only when every applicable check passes:
  - Slab utilization factor (uf_max) < 1.001
  - Each defined perimeter beam load ratio (side_X_load_ratio) <= 1.0

This mirrors the verdict cell MACS+ itself computes (PrintP.js:388,
TabReport.js:846): ``UF1Max < 1.001 ? 'strAdequate' : ...``. MACS+'s
``COMPFAILURE`` flag is a failure-mode *label*, not an independent pass/fail
criterion, so it does not gate the verdict here.

NULL side ratios are skipped (e.g. when a side wasn't analyzed). A run with an
error or no uf_max returns overall_pass=None — we can't say either way.
"""

UF_LIMIT = 1.001
LOAD_RATIO_LIMIT = 1.0


def _check(name: str, value, limit: float, passed: bool) -> dict:
    return {"name": name, "value": value, "limit": limit, "pass": passed}


def compute_status(row: dict) -> dict:
    """Return {overall_pass, checks} for a runs-table row or raw outputs dict."""
    if row.get("error"):
        return {"overall_pass": None, "checks": []}

    uf_max = row.get("uf_max")
    if uf_max is None:
        return {"overall_pass": None, "checks": []}

    checks = []

    slab_pass = uf_max < UF_LIMIT
    checks.append(_check("Slab UF", uf_max, UF_LIMIT, slab_pass))

    for letter in ("a", "b", "c", "d"):
        ratio = row.get(f"side_{letter}_load_ratio")
        if ratio is None:
            continue
        side_pass = ratio <= LOAD_RATIO_LIMIT
        checks.append(_check(
            f"Side {letter.upper()} beam load",
            ratio, LOAD_RATIO_LIMIT, side_pass,
        ))

    overall_pass = all(c["pass"] for c in checks)
    return {"overall_pass": overall_pass, "checks": checks}
