"""Verify replayed MACS+ PDFs before anyone relies on them as evidence.

    python tools/macs_replay/verify_replay.py --manifest export/manifest.json --pdfs pdfs/
    python tools/macs_replay/verify_replay.py --self-test pdfs/run00000.pdf

Four checks per PDF, each targeting a failure that produces well-formed but
wrong output:

  structure    4-page report from "Microsoft: Print To PDF" that parses
  round-trip   the printed fire load and glazing are this run's own values
  off-by-one   and specifically are not the *previous* run's
  chart        the curves span the plot box, catching the display-scaling
               squash that leaves every number correct while the graphs lie

The chart check is the self-test: at 100% scaling the curves reach ~0.998 of
the box; at 150% they reach ~0.59.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from macs_automation import pdf_oracle  # noqa: E402

REACH_MIN = 0.95

# The one thing that legitimately differs between two prints of the same job.
STAMP = re.compile(r"Date:\s*\d{1,2} \w+ \d{4},\s*\d{1,2}:\d{2}")
MAX_DIFF_LINES = 20


def graphs_page(doc):
    """Index of the 'Graphical output' page. Long fires push it past page 4."""
    for i, pg in enumerate(doc):
        if "Graphical output" in (pg.get_text() or ""):
            return i
    return None


def curve_reach(path):
    """Fraction of the plot box width the drawn curves span, or None."""
    doc = fitz.open(path)
    gi = graphs_page(doc)
    if gi is None:
        return None
    pm = doc[gi].get_pixmap(dpi=150)
    a = np.array(Image.frombytes("RGB", (pm.width, pm.height), pm.samples).convert("L"))
    cols = np.where((a[: int(a.shape[0] * 0.45)] < 120).sum(axis=0) > 200)[0]
    if len(cols) < 3:
        return None
    c0, c1 = int(cols[1]), int(cols[cols < 1000][-1])
    inner = a[172:546, c0 + 6 : c1 - 6] < 140
    if not inner.any():
        return None
    return int(np.where(inner.sum(axis=0) > 0)[0].max()) / inner.shape[1]


def self_test(path: Path) -> int:
    print(f"self-test: {path}")
    reach = curve_reach(path)
    if reach is None:
        print("  FAIL: could not find the graphs page")
        return 1
    print(f"  curve reach: {reach:.3f} (must be >= {REACH_MIN})")
    if reach < REACH_MIN:
        print("  FAIL: charts are squashed - set display scaling to 100%, sign out and back in")
        return 1
    print("  PASS: charts span the plot box, so display scaling is correct")
    return 0


def normalise(lines) -> list[str]:
    """Report lines with the print timestamp masked out."""
    return [STAMP.sub("Date: <stamp>", line).rstrip() for line in lines]


def text_differences(reference, candidate) -> list[str]:
    """Diff lines between two reports, empty when they say the same thing.

    Everything but the timestamp must match: the two routes into MACS's own
    print path snapshot the page at different moments, and the visible symptom
    of getting that wrong is a dropped field label, not a wrong number.
    """
    diff = [
        line
        for line in difflib.unified_diff(
            normalise(reference), normalise(candidate), "dialog", "silent", n=0
        )
        if line[:1] in "+-" and line[:3] not in ("+++", "---")
    ]
    if len(diff) > MAX_DIFF_LINES:
        extra = len(diff) - MAX_DIFF_LINES
        diff = diff[: MAX_DIFF_LINES - 1] + [f"... and {extra + 1} more differing lines"]
    return diff


def pdf_lines(path: Path) -> list[str]:
    return pdf_oracle.read_text(path).splitlines()


def compare(manifest_path: Path, pdf_dir: Path, ref_dir: Path) -> int:
    """Check PDFs against known-good ones for the same runs, run by run."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs = manifest["runs"]
    checked = 0
    skipped = 0
    problems: list[tuple[str, list[str]]] = []

    for entry in runs:
        name = entry["name"]
        new, ref = pdf_dir / f"{name}.pdf", ref_dir / f"{name}.pdf"
        if not new.exists():
            problems.append((name, ["missing PDF"]))
            continue
        if not ref.exists():
            # Only runs with a reference can be compared; say how many were not.
            skipped += 1
            continue
        try:
            diff = text_differences(pdf_lines(ref), pdf_lines(new))
        except Exception as exc:  # noqa: BLE001 - report, don't abort the sweep
            problems.append((name, [f"{type(exc).__name__}: {exc}"]))
            continue
        checked += 1
        if diff:
            problems.append((name, diff))

    print(f"\ncompared {checked} PDF(s) against {ref_dir}")
    if skipped:
        print(f"skipped {skipped} with no reference PDF to compare against")
    print(f"\nreports that differ: {len(problems)}")
    for name, diff in problems[:10]:
        print(f"  {name}:")
        for line in diff:
            print(f"      {line}")
    if len(problems) > 10:
        print(f"  ... and {len(problems) - 10} more")
    if not problems and checked:
        print("  none - identical to the reference reports apart from the timestamp")
    return 1 if problems or not checked else 0


def verify(manifest_path: Path, pdf_dir: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs = manifest["runs"]
    problems: list[tuple[str, str]] = []
    reaches: list[float] = []
    sizes: list[int] = []
    pagecounts: dict[int, int] = {}

    for i, entry in enumerate(runs):
        name = entry["name"]
        path = pdf_dir / f"{name}.pdf"
        if not path.exists():
            problems.append((name, "missing PDF"))
            continue
        sizes.append(path.stat().st_size)
        try:
            doc = fitz.open(path)
            pagecounts[len(doc)] = pagecounts.get(len(doc), 0) + 1
            if (doc.metadata or {}).get("producer") != "Microsoft: Print To PDF":
                problems.append((name, f"producer={(doc.metadata or {}).get('producer')!r}"))
            if graphs_page(doc) is None:
                problems.append((name, "no 'Graphical output' section"))

            text = pdf_oracle.read_text(path)
            if "Fire load" not in text:
                # The signature of a job that reverted to the standard ISO
                # curve: fire load and glazing stop entering the calculation.
                problems.append((name, "NO 'Fire load:' LINE - job reverted to the ISO curve"))
                continue
            o = pdf_oracle.parse_oracle(text)

            expect = entry.get("expect") or {}
            if expect.get("qf") is not None and abs(o["fire_load"] - expect["qf"]) > 0.01:
                prev = runs[i - 1].get("expect", {}) if i else {}
                if prev.get("qf") is not None and abs(o["fire_load"] - prev["qf"]) < 0.01:
                    problems.append((name, f"OFF-BY-ONE: printed the previous run's qf {prev['qf']}"))
                else:
                    problems.append((name, f"qf {o['fire_load']} != expected {expect['qf']}"))
            if expect.get("window_percent") is not None and abs(o["glazing"] - expect["window_percent"]) > 0.01:
                problems.append((name, f"glazing {o['glazing']} != expected {expect['window_percent']}"))
            if expect.get("uf_max") is not None and o["uf_max"] is not None:
                if abs(o["uf_max"] - expect["uf_max"]) > 0.005:
                    problems.append((name, f"uf_max {o['uf_max']} != i-macs {expect['uf_max']}"))

            reach = curve_reach(path)
            if reach is None:
                problems.append((name, "no curves on the graphs page"))
            else:
                reaches.append(reach)
                if reach < REACH_MIN:
                    problems.append((name, f"chart squashed: curves reach {reach:.3f}"))
        except Exception as exc:  # noqa: BLE001 - report, don't abort the sweep
            problems.append((name, f"{type(exc).__name__}: {exc}"))

    print(f"\nbatch {manifest['batch_id']}: {len(runs)} runs expected, {len(sizes)} PDFs present")
    if pagecounts:
        print("page counts: " + ", ".join(f"{n}pp x{c}" for n, c in sorted(pagecounts.items())))
    if reaches:
        print(f"chart reach: min {min(reaches):.3f}  median {sorted(reaches)[len(reaches)//2]:.3f}")
    if sizes:
        mean = sum(sizes) / len(sizes)
        print(f"size: {sum(sizes)/1024**2:.1f} MB total, mean {mean/1024:.0f} KB "
              f"(10,000 runs ≈ {mean*10000/1024**3:.1f} GB)")

    print(f"\nproblems: {len(problems)}")
    for name, msg in problems[:40]:
        print(f"  {name}: {msg}")
    if len(problems) > 40:
        print(f"  ... and {len(problems) - 40} more")
    if not problems:
        print("  none - every PDF carries its own inputs and correct charts")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", type=Path, help="check one PDF's chart geometry and exit")
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--pdfs", type=Path)
    ap.add_argument(
        "--compare-to",
        type=Path,
        help="directory of known-good PDFs; report any difference but the timestamp",
    )
    args = ap.parse_args()

    if args.self_test:
        return self_test(args.self_test)
    if not (args.manifest and args.pdfs):
        ap.error("--manifest and --pdfs are required unless --self-test is used")
    if args.compare_to:
        return compare(args.manifest, args.pdfs, args.compare_to)
    return verify(args.manifest, args.pdfs)


if __name__ == "__main__":
    raise SystemExit(main())
