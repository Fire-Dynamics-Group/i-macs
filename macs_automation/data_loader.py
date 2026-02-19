"""Parse MACS+ Data.xml for steel sections, deck types, and mesh types."""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

DEFAULT_DATA_PATH = Path(r"C:\Program Files (x86)\MACS+\EN\Data\Data.xml")

SECTION_FAMILIES = ["IPE", "HE", "HL", "HD", "UB", "UC", "UBP", "HPUK", "W", "HPUS", "H"]


def load_data(data_path: Optional[Path] = None) -> dict:
    """Load all reference data from Data.xml.

    Returns dict with keys: 'sections', 'decks', 'meshes'.
    """
    path = data_path or DEFAULT_DATA_PATH
    tree = ET.parse(path)
    root = tree.getroot()

    return {
        "sections": _load_all_sections(root),
        "decks": _load_decks(root),
        "meshes": _load_meshes(root),
    }


def _load_all_sections(root: ET.Element) -> dict:
    """Load all section families into a single flat dict keyed by section ID.

    Each value is a dict with: family, grade, h, b, tw, tf, name.
    """
    sections = {}
    for family in SECTION_FAMILIES:
        family_elem = root.find(family)
        if family_elem is None:
            continue
        for sec in family_elem.findall("Section"):
            sec_id = sec.get("Id")
            if not sec_id:
                continue
            sections[sec_id] = {
                "family": family,
                "grade": sec.get("grade", ""),
                "h": float(sec.get("h", 0)),
                "b": float(sec.get("b", 0)),
                "tw": float(sec.get("tw", 0)),
                "tf": float(sec.get("tf", 0)),
                "name": (sec.text or "").strip(),
            }
    return sections


def _load_decks(root: ET.Element) -> dict:
    """Load deck types from the DeckRoot tree structure.

    Returns dict keyed by deck ID (e.g. 'T14') with deck properties.
    """
    decks = {}
    deck_root = root.find(".//DeckRoot")
    if deck_root is None:
        return decks
    _walk_deck_tree(deck_root, decks)
    return decks


def _walk_deck_tree(elem: ET.Element, decks: dict):
    """Recursively walk the deck tree, collecting leaf nodes with deck_type attr."""
    for child in elem:
        deck_id = child.get("Id")
        deck_type = child.get("deck_type")
        if deck_type and deck_id:
            depth_str = child.get("deck_depth", "")
            if depth_str:  # skip UDF with empty values
                decks[deck_id] = {
                    "deck_type": deck_type,
                    "deck_depth": float(child.get("deck_depth", 0)),
                    "deck_trug": float(child.get("deck_trug", 0)),
                    "deck_top": float(child.get("deck_top", 0)),
                    "deck_bot": float(child.get("deck_bot", 0)),
                    "deck_stiff_height": float(child.get("deck_stiff_height", 0)),
                    "name": (child.text or "").strip(),
                }
        # Recurse into sub-trees (e.g. UKDecksT, UKDecksR)
        _walk_deck_tree(child, decks)


def _load_meshes(root: ET.Element) -> dict:
    """Load mesh types from MeshRoot.

    Returns dict keyed by mesh ID (e.g. 'A393') with mesh properties.
    """
    meshes = {}
    mesh_root = root.find("MeshRoot")
    if mesh_root is None:
        return meshes
    for mesh in mesh_root.findall("Mesh"):
        mesh_id = mesh.get("Id")
        if not mesh_id:
            continue
        main_area = mesh.get("mainArea", "")
        if not main_area:  # skip UDF
            continue
        meshes[mesh_id] = {
            "mainArea": float(mesh.get("mainArea", 0)),
            "transArea": float(mesh.get("transArea", 0)),
            "min_mesh_dia": float(mesh.get("min_mesh_dia", 0)),
            "max_mesh_dia": float(mesh.get("max_mesh_dia", 0)),
            "name": (mesh.text or "").strip(),
        }
    return meshes


def lookup_section(sections: dict, sec_id: str) -> dict:
    """Look up a section by ID, returning h, b, tw, tf.

    Raises KeyError if not found.
    """
    if sec_id not in sections:
        raise KeyError(f"Section '{sec_id}' not found in database")
    return sections[sec_id]
