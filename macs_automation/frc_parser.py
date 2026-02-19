"""Parse MACS+ .frc project files into internal parameter dicts."""

import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote


# FRC Method integer → internal method string
_METHOD_MAP = {
    "0": "iso",
    "1": "parametric",
    "2": "udf",
}

# Properties that should remain as strings (not cast to float)
_STRING_PROPS = {
    "conc_type", "DeckId", "DeckName", "deck_type", "SteelDeck",
    "mesh_type", "USecTypeFlag", "calc_slab_weight",
    "uSecSize", "uSec1Size", "uSec2Size",
    "SideASecSize", "SideBSecSize", "SideCSecSize", "SideDSecSize",
    "SideASecName", "SideBSecName", "SideCSecName", "SideDSecName",
    "fy1", "fy2", "fy3", "fy4", "fy5",
}

# Properties we skip (display/UI-only, not engine inputs)
_SKIP_PROPS = {
    "DeckTree", "deck_cover", "deck_scale", "OneLoop",
    "SecFamily1", "SecFamily2", "SecFamily3", "SecFamily4", "SecFamily5",
    "SecFlags1", "SecFlags2", "SecFlags3", "SecFlags4", "SecFlags5",
    "SideASecName", "SideBSecName", "SideCSecName", "SideDSecName",
    "SideASecTypeFlag", "SideBSecTypeFlag", "SideCSecTypeFlag", "SideDSecTypeFlag",
    "uSecName",
    "perm_var_fac",
}


def _extract_properties(section_elem: ET.Element) -> dict:
    """Extract Name/Value pairs from Property elements in a section."""
    props = {}
    for prop in section_elem.findall("Property"):
        name = prop.get("Name", "")
        value = unquote(prop.get("Value", ""))
        if name:
            props[name] = value
    return props


def _coerce_value(name: str, raw: str):
    """Convert a raw string value to the appropriate Python type."""
    if name in _STRING_PROPS:
        return raw
    # Try numeric conversion
    try:
        f = float(raw)
        # Return int if it's a whole number and commonly used as int
        if f == int(f) and name in {
            "numbeam", "SideAEdgeFlag", "SideBEdgeFlag", "SideCEdgeFlag", "SideDEdgeFlag",
            "SideACompoFlag", "SideBCompoFlag", "SideCCompoFlag", "SideDCompoFlag",
        }:
            return int(f)
        return f
    except (ValueError, TypeError):
        return raw


def _parse_root(root: ET.Element) -> dict:
    """Parse an already-parsed XML root element."""
    # Validate signature
    sig = root.findtext("Signature", "")
    if sig != "FRACOFJobFile":
        raise ValueError(f"Invalid .frc file signature: '{sig}' (expected 'FRACOFJobFile')")

    input_elem = root.find("Input")
    if input_elem is None:
        raise ValueError("No <Input> section found in .frc file")

    params = {}
    project = {}

    # --- Project metadata ---
    proj_elem = input_elem.find("Project")
    if proj_elem is not None:
        project = _extract_properties(proj_elem)

    # --- GA (geometry) ---
    ga_elem = input_elem.find("GA")
    if ga_elem is not None:
        for name, raw in _extract_properties(ga_elem).items():
            params[name] = _coerce_value(name, raw)

    # --- Deck ---
    deck_elem = input_elem.find("Deck")
    if deck_elem is not None:
        for name, raw in _extract_properties(deck_elem).items():
            if name in _SKIP_PROPS:
                continue
            params[name] = _coerce_value(name, raw)

    # --- Slab ---
    slab_elem = input_elem.find("Slab")
    if slab_elem is not None:
        for name, raw in _extract_properties(slab_elem).items():
            if name in _SKIP_PROPS:
                continue
            params[name] = _coerce_value(name, raw)

    # --- Beams ---
    beams_elem = input_elem.find("Beams")
    if beams_elem is not None:
        for name, raw in _extract_properties(beams_elem).items():
            if name in _SKIP_PROPS:
                continue
            params[name] = _coerce_value(name, raw)

    # --- Loading ---
    loading_elem = input_elem.find("Loading")
    if loading_elem is not None:
        for name, raw in _extract_properties(loading_elem).items():
            if name in _SKIP_PROPS:
                continue
            params[name] = _coerce_value(name, raw)

    # --- Fire ---
    fire_elem = input_elem.find("Fire")
    if fire_elem is not None:
        fire_props = _extract_properties(fire_elem)
        # Handle Method mapping specially
        method_raw = fire_props.pop("Method", "0")
        params["method"] = _METHOD_MAP.get(method_raw, "iso")
        # Handle UDFFire path (skip if empty)
        fire_props.pop("UDFFire", None)
        for name, raw in fire_props.items():
            if name in _SKIP_PROPS:
                continue
            params[name] = _coerce_value(name, raw)

    return {"params": params, "project": project}


def parse_frc(path: str | Path) -> dict:
    """Parse a .frc file from disk.

    Returns dict with:
        - 'params': dict of engine input parameters
        - 'project': dict of project metadata (name, client, job number, etc.)
    """
    tree = ET.parse(path)
    return _parse_root(tree.getroot())


def parse_frc_string(xml_string: str) -> dict:
    """Parse a .frc file from a string.

    Same return format as parse_frc().
    """
    root = ET.fromstring(xml_string)
    return _parse_root(root)
