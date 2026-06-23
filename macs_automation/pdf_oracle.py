"""Parse a MACS+ desktop report PDF into engine inputs and oracle outputs.

A MACS+ report prints essentially every input the FRACOF engine needs for the
parametric / solid-beam case, plus the full results (summary unity factor,
factored fire load, the time-series table, and per-side critical temperatures).
This module turns that PDF into:

  - ``params``: a dict accepted by ``MACSEngine.set_inputs`` (so a report can be
    replayed through the engine with no ``.frc`` on hand), and
  - ``oracle``: the reference outputs to validate the engine against.

Only the handful of inputs MACS+ never prints (concrete thermal conductivity,
analysis time limit, a few encoding flags) are filled from ``_TEMPLATE`` — these
are constants for the parametric solid-beam workflow, not scenario geometry.

Mappings were reverse-engineered and cross-checked against two real reports
(Atlantic Park Units 6 and 7); see ``tests/test_pdf_oracle_parser.py``. The
factored-fire-load identity is the proof the load model is mapped correctly:

    factored_hot = (cold_perm + slab_weight)            # permanent, factor 1.0
                 + lead_var_fac * lead_var_act
                 + othr_var_fac * othr_var_act
"""

from __future__ import annotations

import re
from pathlib import Path

# MACS+ growth-rate label -> FRACOF integer encoding (Slow/Medium/Fast).
_GROWTH_RATE = {"Slow": 0.0, "Medium": 1.0, "Fast": 2.0}

# Engine inputs MACS+ does not print. Constant for the parametric solid-beam
# workflow these reports use; not scenario geometry.
_TEMPLATE = {
    "SteelDeck": "1",          # a steel deck is present (deck dims are printed)
    "conc_lambda": 1.0,        # normal-weight concrete thermal conductivity
    "time_limit": 60.0,        # analysis duration (minutes)
    "USecTypeFlag": "1",       # solid (not cellular) unprotected beam
    "uSecDiam": 0.0,           # no cell opening for a solid beam
    "method": "parametric",
}


def read_text(pdf_path: str | Path) -> str:
    """Extract all text from a PDF as one newline-joined string."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _num(pattern: str, text: str, *, required: bool = True) -> float | None:
    m = re.search(pattern, text)
    if not m:
        if required:
            raise ValueError(f"pattern not found in PDF: {pattern!r}")
        return None
    return float(m.group(1))


def _section_size(raw: str) -> str:
    """'UB 356x127x33' -> 'UB_356x127x33' (engine section-DB key form)."""
    return re.sub(r"\s+", "_", raw.strip())


# Per-side beam block on the tabular-results page: section, construction,
# location, shear connection, degree of utilization, critical temperature.
_SIDE_BLOCK = re.compile(
    r"Side ([ABCD])\s+Beam type:[^\n]*?(Composite|Non-composite)"
    r"(Internal|Edge) beam\s*Section size:\s*(UB\s*[0-9x]+)"
    r".*?Shear connection:\s*([0-9]+)"
    r".*?Degree of utilization:\s*([0-9.]+)"
    r".*?Critical temperature:\s*([0-9]+)",
    re.DOTALL,
)

# A results-table data row: integer time + 11 numeric columns, at least one of
# which is a decimal (capacities always are). The decimal requirement rejects
# the page-4 graph axis tick line (e.g. "4 8 12 ... 48"), which is all integers
# and otherwise matches the 12-column shape when a fire runs the full duration.
_TABLE_ROW = re.compile(r"^\d+(?:\s+-?[0-9.]+){11}$")
_HAS_DECIMAL = re.compile(r"\d\.\d")

_TABLE_COLUMNS = (
    "time", "beam_temp", "mesh_temp", "slab_top_temp", "slab_bottom_temp",
    "beam_capacity", "max_deflection", "slab_yield", "enhancement",
    "slab_capacity", "total_capacity", "unity_factor",
)


def parse_params(text: str) -> dict:
    """Reconstruct engine inputs from the report text."""
    params: dict = dict(_TEMPLATE)

    # --- General arrangement ---
    params["numbeam"] = int(_num(r"Number of internal unprotected beams:\s*([0-9]+)", text))
    params["span1"] = _num(r"Span 1:\s*([0-9.]+)", text)
    params["span2"] = _num(r"Span 2:\s*([0-9.]+)", text)

    # --- Deck ---
    deck_type = re.search(r"Type:\s*(Trapezoidal|Re-entrant)", text)
    params["deck_type"] = "T" if (deck_type and deck_type.group(1) == "Trapezoidal") else "R"
    params["deck_depth"] = _num(r"Depth:\s*([0-9.]+)\s*mm", text)
    params["deck_top"] = _num(r"Top flange:\s*([0-9.]+)", text)
    params["deck_bot"] = _num(r"Bottom flange:\s*([0-9.]+)", text)
    params["deck_trug"] = _num(r"Pitch:\s*([0-9.]+)", text)
    params["deck_stiff_height"] = _num(r"Stiffener height:\s*([0-9.]+)", text)

    # --- Slab / concrete ---
    params["conc_type"] = "NW" if re.search(r"Concrete type:\s*Normal", text) else "LW"
    params["slab_depth"] = _num(r"Slab depth:\s*([0-9.]+)", text)
    params["fck"] = _num(r"\(fck\):\s*([0-9.]+)", text)

    # --- Mesh ---
    params["mesh_area_max"] = _num(r"Longitudinal mesh area:\s*([0-9.]+)", text)
    params["mesh_area_min"] = _num(r"Transverse mesh area:\s*([0-9.]+)", text)
    bars = re.findall(r"Bar size:\s*([0-9.]+)", text)
    params["max_mesh_dia"] = float(bars[0])
    params["min_mesh_dia"] = float(bars[1] if len(bars) > 1 else bars[0])
    params["mesh_axis"] = _num(r"Average mesh axis distance:\s*([0-9.]+)", text)
    params["mesh_strength"] = _num(r"Mesh yield stress:\s*([0-9.]+)", text)
    grade = re.search(r"Steel grade:\s*S?([0-9]+)", text)
    fy = grade.group(1) if grade else "355"
    for i in range(1, 6):
        params[f"fy{i}"] = fy

    # --- Beams: unprotected internal, then the four perimeter sides ---
    first_section = re.search(r"Section size:\s*(UB\s*[0-9x]+)", text)
    params["uSecSize"] = _section_size(first_section.group(1))
    params["ush_con"] = 80.0
    for m in _SIDE_BLOCK.finditer(text):
        side, construction, location, size, shear, _util, _temp = m.groups()
        params[f"Side{side}SecSize"] = _section_size(size)
        params[f"Side{side}EdgeFlag"] = 1 if location == "Edge" else 0
        params[f"Side{side}CompoFlag"] = 1 if construction == "Composite" else 0
        params[f"Side{side}sh_con"] = float(shear)

    # --- Loading ---
    params["lead_var_act"] = _num(r"Leading variable action:\s*([0-9.]+)", text)
    params["othr_var_act"] = _num(r"Accompanying variable action:\s*([0-9.]+)", text)
    params["cold_perm"] = _num(r"Dead load including beam, excluding slab:\s*([0-9.]+)", text)
    params["slab_weight"] = _num(r"Calculated slab weight including mesh:\s*([0-9.]+)", text)
    params["lead_var_fac"] = _num(r"Combination factor for leading variable action:\s*([0-9.]+)", text)
    params["othr_var_fac"] = _num(r"Combination factor for other variable action:\s*([0-9.]+)", text)

    # --- Fire / compartment ---
    params["Lc"] = _num(r"Compartment length:\s*([0-9.]+)", text)
    params["Bc"] = _num(r"Compartment width:\s*([0-9.]+)", text)
    params["Hc"] = _num(r"Compartment height:\s*([0-9.]+)", text)
    params["Hw"] = _num(r"Window height:\s*([0-9.]+)", text)
    params["Lw"] = _num(r"Window length:\s*([0-9.]+)", text)
    params["window_percent"] = _num(r"Glazing breakage:\s*([0-9.]+)", text)
    params["qf"] = _num(r"Fire load:\s*([0-9.]+)", text)
    params["Bfac"] = _num(r"Wall lining \(B\) factor:\s*([0-9.]+)", text)
    params["combustion_factor"] = _num(r"Combustion factor:\s*([0-9.]+)", text)
    growth = re.search(r"Growth rate:\s*(\w+)", text)
    params["growth_rate"] = _GROWTH_RATE.get(growth.group(1) if growth else "Medium", 1.0)

    return params


def parse_oracle(text: str) -> dict:
    """Extract the reference outputs the engine must reproduce."""
    table = []
    for line in text.splitlines():
        stripped = line.strip()
        if _TABLE_ROW.match(stripped) and _HAS_DECIMAL.search(stripped):
            table.append(dict(zip(_TABLE_COLUMNS, (float(t) for t in stripped.split()))))

    sides = {}
    for m in _SIDE_BLOCK.finditer(text):
        side, _con, _loc, _size, _shear, util, temp = m.groups()
        sides[side.lower()] = {"load_ratio": float(util), "critical_temp": float(temp)}

    return {
        "uf_max": _num(r"Maximum unity factor:\s*([0-9.]+)", text),
        "factored_hot": _num(r"Factored load in fire:\s*([0-9.]+)", text),
        "fire_load": _num(r"Fire load:\s*([0-9.]+)", text),
        "glazing": _num(r"Glazing breakage:\s*([0-9.]+)", text),
        "sides": sides,
        "table": table,
    }


def parse_pdf(pdf_path: str | Path) -> dict:
    """Parse a MACS+ report PDF into ``{'params', 'oracle'}``."""
    text = read_text(pdf_path)
    return {"params": parse_params(text), "oracle": parse_oracle(text)}
