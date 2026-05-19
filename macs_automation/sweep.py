"""Parameter sweep generator — reads YAML config and produces all combinations."""

import itertools
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

    # Generate sweep combinations
    sweep = config.get("sweep", {})
    if not sweep:
        return [base]

    # Normalize keys and ensure all values are lists
    sweep_keys = []
    sweep_values = []
    for key, values in sweep.items():
        internal_key = PARAM_ALIASES.get(key, key)
        sweep_keys.append(internal_key)
        if not isinstance(values, list):
            values = [values]
        sweep_values.append(values)

    combinations = []
    for combo in itertools.product(*sweep_values):
        params = dict(base)
        for key, val in zip(sweep_keys, combo):
            params[key] = val
        combinations.append(params)

    return combinations
