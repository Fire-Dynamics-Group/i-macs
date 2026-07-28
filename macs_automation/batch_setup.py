"""Derive a batch's shared setup from the runs it actually produced.

The batch detail page needs to answer "what configuration do all these runs
have in common?" — the question you ask when reviewing someone else's batch,
or your own six months later.

The source is the stored `runs` rows, NOT `batches.config_json`, for two
reasons:

* config_json only exists for batches submitted after it was added; the runs
  have always been there. Legacy batches would otherwise show nothing.
* config_json records what the *form intended*. The engine params are built
  by layering the request over `sweep.DEFAULTS`, so an input the form doesn't
  model is silently defaulted — the run row is what the engine actually
  received. Showing intent instead of reality is how a 40-vs-52 `mesh_axis`
  divergence hides in plain sight.

A column with one distinct value across every run is part of the shared setup;
anything else varied, and is reported as a range (numeric) or a value list.
"""

from __future__ import annotations

from typing import Any, Optional

# Ordered (group title, [(column, label, unit)]) mirroring the config form's
# sections and the `runs` table layout in db.SCHEMA_SQL. Only columns listed
# here are treated as inputs — everything else in the row (outputs, timing,
# sync provenance) is deliberately absent.
INPUT_GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Geometry", [
        ("span1", "Span 1", "m"),
        ("span2", "Span 2", "m"),
        ("numbeam", "Number of beams", ""),
    ]),
    ("Deck", [
        ("steel_deck", "Steel deck", ""),
        ("deck_name", "Deck profile", ""),
        ("deck_type", "Deck type", ""),
        ("deck_depth", "Deck depth", "mm"),
        ("deck_trug", "Trough pitch", "mm"),
        ("deck_top", "Top width", "mm"),
        ("deck_bot", "Bottom width", "mm"),
        ("deck_stiff_height", "Stiffener height", "mm"),
    ]),
    ("Slab", [
        ("conc_type", "Concrete type", ""),
        ("conc_lambda", "Concrete λ", ""),
        ("fck", "fck", "MPa"),
        ("slab_depth", "Slab depth", "mm"),
        ("mesh_type", "Mesh", ""),
        ("mesh_area_max", "Mesh area (main)", "mm²/m"),
        ("mesh_area_min", "Mesh area (transverse)", "mm²/m"),
        ("mesh_axis", "Mesh axis distance", "mm"),
        ("mesh_strength", "Mesh strength", "MPa"),
    ]),
    ("Beams", [
        ("u_sec_size", "Unprotected section", ""),
        ("u_sec_fy", "Unprotected fy", "MPa"),
        ("ush_con", "Unprotected shear connector spacing", "mm"),
        ("side_a_sec", "Side A section", ""),
        ("side_a_fy", "Side A fy", "MPa"),
        ("side_a_edge", "Side A edge beam", ""),
        ("side_a_composite", "Side A composite", ""),
        ("side_a_sh_con", "Side A shear connector spacing", "mm"),
        ("side_b_sec", "Side B section", ""),
        ("side_b_fy", "Side B fy", "MPa"),
        ("side_b_edge", "Side B edge beam", ""),
        ("side_b_composite", "Side B composite", ""),
        ("side_b_sh_con", "Side B shear connector spacing", "mm"),
        ("side_c_sec", "Side C section", ""),
        ("side_c_fy", "Side C fy", "MPa"),
        ("side_c_edge", "Side C edge beam", ""),
        ("side_c_composite", "Side C composite", ""),
        ("side_c_sh_con", "Side C shear connector spacing", "mm"),
        ("side_d_sec", "Side D section", ""),
        ("side_d_fy", "Side D fy", "MPa"),
        ("side_d_edge", "Side D edge beam", ""),
        ("side_d_composite", "Side D composite", ""),
        ("side_d_sh_con", "Side D shear connector spacing", "mm"),
    ]),
    ("Loading", [
        ("lead_var_act", "Leading variable action", "kN/m²"),
        ("othr_var_act", "Other variable action", "kN/m²"),
        ("cold_perm", "Superimposed dead load", "kN/m²"),
        ("slab_weight", "Slab self-weight", "kN/m²"),
        ("lead_var_fac", "Leading variable factor", ""),
        ("othr_var_fac", "Other variable factor", ""),
    ]),
    ("Fire", [
        ("method", "Analysis method", ""),
        ("time_limit", "Time limit", "min"),
        ("Lc", "Compartment length Lc", "m"),
        ("Bc", "Compartment breadth Bc", "m"),
        ("Hc", "Compartment height Hc", "m"),
        ("Hw", "Window height Hw", "m"),
        ("Lw", "Window length Lw", "m"),
        ("window_percent", "Window opening", "%"),
        ("qf", "Fire load density qf", "MJ/m²"),
        ("Bfac", "Bfac", "J/m²s½K"),
        ("combustion_factor", "Combustion factor", ""),
        ("growth_rate", "Growth rate", ""),
    ]),
]

# Cap on how many distinct values a varying non-numeric field reports. A 500-run
# LHS batch would otherwise ship 500 strings per field; the count is what tells
# the story, the sample is just a flavour of it.
MAX_LISTED_VALUES = 10


def _numeric(values: list[Any]) -> Optional[list[float]]:
    """The values as floats, or None if any isn't numeric (bools excluded —
    the edge/composite flags read better as a value list than a 0–1 range)."""
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        out.append(float(v))
    return out


def _describe(key: str, label: str, unit: str, values: list[Any]) -> dict:
    """Build the field entry for one input column across a batch's runs."""
    distinct = {v for v in values}
    field = {"key": key, "label": label, "unit": unit}

    if len(distinct) == 1:
        field["varies"] = False
        field["value"] = next(iter(distinct))
        return field

    field["varies"] = True
    field["distinct"] = len(distinct)
    # A NULL in some runs but not others is variation too, but it can't take
    # part in a range — fall back to the value list so the gap stays visible.
    nums = _numeric(list(distinct)) if None not in distinct else None
    if nums is not None:
        field["min"] = min(nums)
        field["max"] = max(nums)
    else:
        listed = sorted(distinct, key=lambda v: (v is None, str(v)))
        field["values"] = listed[:MAX_LISTED_VALUES]
    return field


def derive_setup(runs: list[dict]) -> dict:
    """Partition the input columns of `runs` into shared vs varying.

    Columns absent from the rows, or NULL in every row, are omitted — a legacy
    batch has whole groups of NULLs and showing 20 empty fields would bury the
    ones that matter. Groups left with no fields are dropped.
    """
    if not runs:
        return {"run_count": 0, "groups": []}

    groups = []
    for title, fields in INPUT_GROUPS:
        described = []
        for key, label, unit in fields:
            if not any(key in run for run in runs):
                continue
            values = [run.get(key) for run in runs]
            if all(v is None for v in values):
                continue
            described.append(_describe(key, label, unit, values))
        if described:
            groups.append({"title": title, "fields": described})

    return {"run_count": len(runs), "groups": groups}
