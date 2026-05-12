"""Derive `{fixed, varying}` from a stored sweep spec.

Single source of truth for the dashboard's batches list, the analytical
batch detail's chart axes, and slice 2's *Rerun batch* prefill. The spec
arrives as a JSON-encoded string from `batches.config_json`; the parsing
must tolerate NULL and malformed input because old batches predate this
column and partial writes happen.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def _empty() -> dict[str, dict]:
    return {"fixed": {}, "varying": {}}


def varying_params_from_config(config_json: Optional[str]) -> dict[str, dict]:
    """Parse a stored sweep spec JSON string into `{fixed, varying}`.

    Returns `{fixed: {}, varying: {}}` for NULL / empty / malformed input.
    For LHS specs, the `distributions` dict drives `varying` (each entry is
    the distribution descriptor — preset/mean/cov/etc. — since the actual
    samples aren't part of the spec).
    For grid sweeps, `sweep` drives `varying` (values normalised to lists).
    """
    if not config_json:
        return _empty()
    try:
        spec = json.loads(config_json)
    except (ValueError, TypeError):
        return _empty()
    if not isinstance(spec, dict):
        return _empty()

    fixed = spec.get("fixed", {})
    if not isinstance(fixed, dict):
        fixed = {}

    varying: dict[str, Any] = {}
    if spec.get("sampling") == "lhs":
        dists = spec.get("distributions", {})
        if isinstance(dists, dict):
            for name, descriptor in dists.items():
                varying[name] = descriptor if isinstance(descriptor, dict) else {}
    else:
        sweep = spec.get("sweep", {})
        if isinstance(sweep, dict):
            for name, values in sweep.items():
                if isinstance(values, list):
                    varying[name] = list(values)
                else:
                    varying[name] = [values]

    return {"fixed": dict(fixed), "varying": varying}
