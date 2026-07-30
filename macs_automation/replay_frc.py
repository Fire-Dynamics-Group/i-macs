"""Build per-run .frc files for replaying a batch through MACS+ itself.

Colleagues want per-run PDF evidence from the vendor application, not just
i-macs's numbers. The replay drives a running MACS+ instance and re-seeds it
per run via `LoadJob(path)`, so every input comes from the file and a batch
that varies *any* parameter is covered — no mapping of parameters onto form
controls, and no visit to the Fire & Analysis tab.

Two things here are load-bearing:

1. **An unknown parameter is an error.** A substitution that silently matches
   nothing yields 10,000 well-formed, identical, wrong reports. That failure
   has happened here more than once and it never announces itself.

2. **The job must not land on the Fire & Analysis tab.** MACS stores the tab
   that was active when the job was saved, and `LoadJob` restores it. That
   tab's *unload* handler writes its form back over the freshly-loaded values,
   and its fire-model combo never initialises from the loaded job — so
   `Method` flips from parametric to standard and the report silently becomes
   the ISO curve. Landing anywhere else avoids it entirely.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any, Mapping
from urllib.parse import quote

__all__ = [
    "FIRE_TAB",
    "UnknownParameterError",
    "build_replay_frc",
    "format_frc_value",
]

# Tab 7 in group 1 is Fire & Analysis. Never land on it — see module docstring.
FIRE_TAB = 7

_SIGNATURE = "FRACOFJobFile"

# Properties describing which tab the job reopens on, rather than engine inputs.
_LANDING_PROPS = ("CurrentTab", "CurrentGroup")


class UnknownParameterError(KeyError):
    """A requested override does not name a property present in the seed file."""


def format_frc_value(value: Any) -> str:
    """Render a Python value the way MACS stores it.

    Floats use repr's shortest round-trip form: writing a raw double can
    produce '76.35204374199999', which MACS then prints verbatim into the
    report instead of '76.352043742'. Bools become 1/0 rather than True/False.
    Everything is percent-encoded, as MACS itself does.
    """
    if isinstance(value, bool):
        text = "1" if value else "0"
    elif isinstance(value, float):
        # SQLite hands back REAL for columns MACS wrote as integers, so an
        # untouched value would come back as "41.0" where MACS had "41" — a
        # gratuitous difference that also reaches the printed report.
        text = str(int(value)) if value.is_integer() else repr(value)
    else:
        text = str(value)
    return quote(text, safe="")


def _property_names(root: ET.Element) -> Counter:
    return Counter(
        p.get("Name", "") for p in root.iter("Property") if p.get("Name")
    )


def _replace_property(xml: str, name: str, encoded: str) -> str:
    """Swap one Property's Value, leaving the rest of the document byte-identical.

    Editing textually rather than re-serialising the tree keeps MACS's own
    formatting, attribute order and encoding intact — the file stays as close
    to something MACS wrote as possible.
    """
    pattern = re.compile(
        r'(<Property\s+Name="%s"\s+Value=")[^"]*(")' % re.escape(name)
    )
    new_xml, count = pattern.subn(
        lambda m: m.group(1) + encoded.replace("\\", "\\\\") + m.group(2), xml
    )
    if count != 1:
        raise UnknownParameterError(
            f"expected exactly one <Property Name={name!r}>, matched {count}"
        )
    return new_xml


def build_replay_frc(
    seed_xml: str,
    overrides: Mapping[str, Any],
    *,
    landing_tab: int = 1,
    landing_group: int = 1,
) -> str:
    """Return `seed_xml` with `overrides` applied and a safe landing tab.

    `seed_xml` should be the batch's own seed .frc, so every input the batch
    did not vary is exactly what MACS was given originally.

    Raises `UnknownParameterError` if an override names a property the seed
    does not contain, and `ValueError` for a non-.frc document or a landing
    tab of Fire & Analysis.
    """
    if landing_tab == FIRE_TAB:
        raise ValueError(
            "refusing to land on the Fire & Analysis tab: its unload handler "
            "reverts the job to the standard ISO curve"
        )

    try:
        root = ET.fromstring(seed_xml)
    except ET.ParseError as exc:
        raise ValueError(f"seed is not well-formed XML: {exc}") from exc

    if (root.findtext("Signature") or "") != _SIGNATURE:
        raise ValueError(
            f"bad .frc signature: expected {_SIGNATURE!r}, "
            f"got {root.findtext('Signature')!r}"
        )

    counts = _property_names(root)
    unknown = sorted(set(overrides) - set(counts))
    if unknown:
        raise UnknownParameterError(
            "no such property in the seed .frc: " + ", ".join(unknown)
        )
    ambiguous = sorted(n for n in overrides if counts[n] > 1)
    if ambiguous:
        raise UnknownParameterError(
            "property name is not unique in the seed .frc: " + ", ".join(ambiguous)
        )

    out = seed_xml
    for name, value in overrides.items():
        out = _replace_property(out, name, format_frc_value(value))

    for prop, value in zip(_LANDING_PROPS, (landing_tab, landing_group)):
        if counts.get(prop):
            out = _replace_property(out, prop, format_frc_value(value))

    return out
