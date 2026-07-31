"""Parameter sweep generator — reads YAML config and produces all combinations.

Two sampling modes are supported:

* ``sampling: "paired"`` (default) — row-aligned zip across all sweep arrays.
  All arrays must have equal length; unequal lengths raise ``ValueError``.
  Used for Monte Carlo flows where the user has externally generated samples
  (e.g. one CSV per parameter) and wants them combined row-wise.
* ``sampling: "lhs"`` — Latin Hypercube Sampling from analytic distributions.
  Dispatches to ``macs_automation.sampling.generate_lhs_samples``.

The cartesian-product (``grid``) mode was removed in #36; see
``docs/archive/sweep_grid_removed.md`` for the original code and rationale.
"""

from pathlib import Path
from typing import Optional

import yaml


# Default parameter values from Defaults.xml
DEFAULTS = {
    # Geometry
    "span1": 9.0, "span2": 9.0, "numbeam": 2,
    # Deck
    "SteelDeck": "1", "DeckName": "COFRAPLUS 60", "DeckId": "T14",
    "deck_type": "T", "deck_depth": 58, "deck_trug": 207,
    "deck_top": 106, "deck_bot": 62, "deck_stiff_height": 0,
    # Slab
    "conc_type": "NW", "conc_lambda": 1, "fck": 25, "slab_depth": 130,
    "mesh_type": "ST15C",
    "mesh_axis": 40, "mesh_strength": 500,
    # Beams - unprotected
    "USecTypeFlag": "1",
    "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
    "uSec1Depth": 250, "uSec2Depth": 250, "uSecDiam": 200,
    "fy5": "355", "ush_con": 80,
    # Beams - sides
    "SideASecSize": "IPE_500", "fy1": "355", "SideAEdgeFlag": 1, "SideACompoFlag": 0, "SideAsh_con": 80,
    "SideBSecSize": "IPE_500", "fy2": "355", "SideBEdgeFlag": 0, "SideBCompoFlag": 1, "SideBsh_con": 80,
    "SideCSecSize": "IPE_500", "fy3": "355", "SideCEdgeFlag": 0, "SideCCompoFlag": 1, "SideCsh_con": 80,
    "SideDSecSize": "IPE_500", "fy4": "355", "SideDEdgeFlag": 1, "SideDCompoFlag": 0, "SideDsh_con": 80,
    # Loading
    # cold_perm = SDL only (finishes/services/etc.); slab_weight is the slab self-weight.
    # MACS+ adds them internally — keep them as separate inputs to mirror the desktop tool.
    "lead_var_act": 5.0, "othr_var_act": 0.0, "cold_perm": 1.2,
    "slab_weight": 2.47,
    "calc_slab_weight": "1",
    "lead_var_fac": 0.5, "othr_var_fac": 0.3,
    # Fire
    "method": "parametric", "time_limit": 60,
    "Lc": 27, "Bc": 18, "Hc": 3.6, "Hw": 1.8, "Lw": 30,
    "window_percent": 95, "qf": 511, "Bfac": 720,
    "combustion_factor": 0.8, "growth_rate": 1,
}

# Map from friendly YAML config keys to internal MACS+ parameter names
PARAM_ALIASES = {
    "u_sec_size": "uSecSize",
    "u_sec_fy": "fy5",
    "side_a_sec": "SideASecSize", "side_a_fy": "fy1",
    "side_b_sec": "SideBSecSize", "side_b_fy": "fy2",
    "side_c_sec": "SideCSecSize", "side_c_fy": "fy3",
    "side_d_sec": "SideDSecSize", "side_d_fy": "fy4",
    # Per-side beam flags + shear-connector spacing. Sweep YAML uses nested
    # `beams.side_x.{edge,composite,sh_con}` (BEAM_SIDE_MAP); the React form's
    # flat single-run JSON aliases here keep both paths producing the same
    # internal keys.
    "side_a_edge": "SideAEdgeFlag", "side_a_composite": "SideACompoFlag", "side_a_sh_con": "SideAsh_con",
    "side_b_edge": "SideBEdgeFlag", "side_b_composite": "SideBCompoFlag", "side_b_sh_con": "SideBsh_con",
    "side_c_edge": "SideCEdgeFlag", "side_c_composite": "SideCCompoFlag", "side_c_sh_con": "SideCsh_con",
    "side_d_edge": "SideDEdgeFlag", "side_d_composite": "SideDCompoFlag", "side_d_sh_con": "SideDsh_con",
    "u_sec_sh_con": "ush_con",
    # DEFAULTS["DeckId"] = "T14" is always present; without this alias the
    # single-run path in app.api_submit_run leaves the user's deck_id at
    # params["deck_id"] while DeckId stays "T14", so resolve_deck picks T14.
    "deck_id": "DeckId",
}

# Map from friendly beam config keys to MACS+ parameter names
BEAM_SIDE_MAP = {
    "side_a": {"sec_size": "SideASecSize", "fy": "fy1", "edge": "SideAEdgeFlag",
               "composite": "SideACompoFlag", "sh_con": "SideAsh_con"},
    "side_b": {"sec_size": "SideBSecSize", "fy": "fy2", "edge": "SideBEdgeFlag",
               "composite": "SideBCompoFlag", "sh_con": "SideBsh_con"},
    "side_c": {"sec_size": "SideCSecSize", "fy": "fy3", "edge": "SideCEdgeFlag",
               "composite": "SideCCompoFlag", "sh_con": "SideCsh_con"},
    "side_d": {"sec_size": "SideDSecSize", "fy": "fy4", "edge": "SideDEdgeFlag",
               "composite": "SideDCompoFlag", "sh_con": "SideDsh_con"},
}


def load_config(config_path: str | Path) -> dict:
    """Load a YAML sweep configuration file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def resolve_deck(params: dict, decks_db: dict):
    """If params has a deck_id, look up deck properties from the deck database."""
    deck_id = params.get("DeckId") or params.get("deck_id")
    if deck_id and deck_id in decks_db:
        deck = decks_db[deck_id]
        params["DeckName"] = deck.get("name", deck_id)
        params["deck_type"] = deck["deck_type"]
        params["deck_depth"] = deck["deck_depth"]
        params["deck_trug"] = deck["deck_trug"]
        params["deck_top"] = deck["deck_top"]
        params["deck_bot"] = deck["deck_bot"]
        params["deck_stiff_height"] = deck["deck_stiff_height"]


def resolve_mesh(params: dict, meshes_db: dict):
    """If params has a mesh_type, look up mesh areas from the mesh database."""
    mesh_id = params.get("mesh_type")
    if mesh_id and mesh_id in meshes_db:
        mesh = meshes_db[mesh_id]
        params["mesh_area_max"] = mesh["mainArea"]
        params["mesh_area_min"] = mesh["transArea"]


def resolve_slab_weight(params: dict):
    """Recompute slab_weight from geometry when calc_slab_weight is on.

    Mirrors MACS+ exactly: with the 'Calculate slab weight' box ticked, the
    desktop app recomputes slab_weight in the UI immediately before every
    calculation (Calc.js SetInputValues line 151 -> TABs.js SlabWeight()); the
    slab_weight stored in a .frc is only the last computed value. Recomputing
    here keeps sweeps that vary slab_depth or deck geometry in line with what
    MACS+ would send the engine run-for-run.

    Validated against the Atlantic Park run00000 .frc: slab 150 / Multideck 60
    (60/323/142/119) -> 2.83, the value MACS+ stored.
    """
    if str(params.get("calc_slab_weight", "0")) != "1":
        return

    def _num(key):
        try:
            return float(params.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    slab_depth = _num("slab_depth")
    deck_depth = _num("deck_depth")
    deck_trug = _num("deck_trug")

    weight = 0.0
    if slab_depth > 0 and slab_depth >= deck_depth + 30:
        # Rib displacement of the deck profile. deck_trug=0 would be a
        # division by zero in MACS+ too (only reachable with a zero-pitch
        # custom deck); treat the rib term as absent there.
        rib = 0.0
        if deck_trug > 0:
            rib = deck_depth * (1 - 0.5 * ((deck_trug - _num("deck_top") + _num("deck_bot")) / deck_trug))
        density = 24 if str(params.get("conc_type", "NW")) == "NW" else 19
        weight = (slab_depth - rib) * density / 1000
        weight = int(weight * 100 + 0.5) / 100  # TABs.js parseInt(w*100+0.5)/100
    params["slab_weight"] = weight


def _check_window_percent_units(config: dict) -> None:
    """Reject window_percent supplied as fractions instead of percent.

    The legacy sampler's opening_perc files store fractions in [0, 1]; the old
    GUI clicker converted at type-in with max(g, 0.05) * 100. MACS+ takes
    percent (0-100), so an all-<=1 batch simulates near-sealed compartments and
    every run comes out ambient. Genuine percent arrays may contain the odd
    sub-1% row (the opening-factor transform can emit them) but never consist
    of them entirely, so only reject when ALL values are <= 1.
    """
    sweep = config.get("sweep", {})
    if "window_percent" in sweep:
        values = sweep["window_percent"]
        candidates = values if isinstance(values, list) else [values]
    elif "window_percent" in config.get("fixed", {}):
        candidates = [config["fixed"]["window_percent"]]
    else:
        return
    numeric = [v for v in candidates if isinstance(v, (int, float))]
    if numeric and all(v <= 1 for v in numeric):
        raise ValueError(
            "window_percent values look like fractions (all <= 1), but MACS+ "
            "takes a percentage (0-100). If these came from a legacy "
            "opening_perc file, multiply by 100 first (the old GUI clicker "
            "applied max(value, 0.05) * 100 at type-in)."
        )


def generate_combinations(config: dict) -> list[dict]:
    """Generate all parameter combinations from a sweep config.

    Config format:
        analysis_method: "iso"
        sweep:
            param_name: [val1, val2, ...]
        fixed:
            param_name: value
        beams:
            side_a: {sec_size: ..., fy: ..., edge: ..., composite: ..., sh_con: ...}
            ...

    Returns a list of param dicts, one per combination.
    """
    _check_window_percent_units(config)

    if config.get("sampling") == "lhs":
        from macs_automation.sampling import generate_lhs_samples
        return generate_lhs_samples(config)

    # Start with defaults
    base = dict(DEFAULTS)

    # Apply analysis method
    method = config.get("analysis_method", "iso")
    # Map string method to the internal method code
    method_map = {"parametric": "parametric", "iso": "iso", "udf": "udf"}
    base["method"] = method_map.get(method, method)

    # Apply fixed overrides
    fixed = config.get("fixed", {})
    for key, value in fixed.items():
        internal_key = PARAM_ALIASES.get(key, key)
        base[internal_key] = value

    # Apply beam configuration
    beams = config.get("beams", {})
    for side, cfg in beams.items():
        if side in BEAM_SIDE_MAP:
            mapping = BEAM_SIDE_MAP[side]
            if "sec_size" in cfg:
                base[mapping["sec_size"]] = cfg["sec_size"]
            if "fy" in cfg:
                base[mapping["fy"]] = str(cfg["fy"])
            if "edge" in cfg:
                base[mapping["edge"]] = int(cfg["edge"])
            if "composite" in cfg:
                base[mapping["composite"]] = int(cfg["composite"])
            if "sh_con" in cfg:
                base[mapping["sh_con"]] = cfg["sh_con"]

    # Handle deck_id in fixed overrides
    if "deck_id" in fixed:
        base["DeckId"] = fixed["deck_id"]

    # Generate sweep combinations (paired / row-aligned zip)
    sweep = config.get("sweep", {})
    if not sweep:
        return [base]

    sweep_keys = []
    sweep_values = []
    sweep_lengths: dict[str, int] = {}
    for key, values in sweep.items():
        internal_key = PARAM_ALIASES.get(key, key)
        if not isinstance(values, list):
            values = [values]
        sweep_keys.append(internal_key)
        sweep_values.append(values)
        sweep_lengths[key] = len(values)

    if len(set(sweep_lengths.values())) > 1:
        details = ", ".join(f"{k}={n}" for k, n in sweep_lengths.items())
        raise ValueError(
            f"All paired sweep parameters must have equal length; got: {details}"
        )

    combinations = []
    for row in zip(*sweep_values):
        params = dict(base)
        for key, val in zip(sweep_keys, row):
            params[key] = val
        combinations.append(params)

    return combinations
