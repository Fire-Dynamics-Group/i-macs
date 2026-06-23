"""End-to-end oracle test: reproduce the MACS+ desktop PDF for Atlantic Park
Phase 2 Unit 7, run00000, against the real FRACOF engine.

The oracle values are **parsed from the actual MACS+ report PDF**
(`fixtures/atlantic_park_run00000_macs.pdf`) at runtime — not transcribed — so
the test stays honest if the reference is ever regenerated. The run inputs
(fire load, glazing) are also read from the PDF; the project `.frc` supplies the
rest (including the mesh axis distance of 52 mm).

Pins two things:
  1. With the project's mesh axis distance the engine reproduces the PDF's 0.65.
  2. With the i-MACS legacy default (40 mm) the engine yields 0.686 — the
     regression a colleague reported. `mesh_axis` was dropped on .frc import
     because it was absent from the frontend FormValues / hydration (now fixed);
     see docs/macs-vs-imacs-discrepancy-study.md.

Skipped with a clear reason when COM / Data.xml are unavailable (64-bit Python,
MACS+ not installed). On a MACS+ box run with:  pytest -m e2e -v
"""

import re
from pathlib import Path

import pytest

from macs_automation.tests.conftest import com_and_data_available

FIXTURES = Path(__file__).parent / "fixtures"
FRC = FIXTURES / "atlantic_park_run00000.frc"
PDF = FIXTURES / "atlantic_park_run00000_macs.pdf"

PROJECT_MESH_AXIS = 52.0   # the .frc value (mm)
LEGACY_DEFAULT_MESH_AXIS = 40.0  # old sweep.DEFAULTS — reproduced the 0.686 bug


def _parse_pdf_oracle() -> dict:
    """Read the reference values straight out of the MACS+ report PDF."""
    pypdf = pytest.importorskip("pypdf")
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(str(PDF)).pages)

    def grab(pattern: str) -> float:
        m = re.search(pattern, text)
        assert m, f"pattern not found in PDF: {pattern!r}"
        return float(m.group(1))

    return {
        "uf_max": grab(r"Maximum unity factor:\s*([0-9.]+)"),
        "factored": grab(r"Factored load in fire:\s*([0-9.]+)"),
        "fire_load": grab(r"Fire load:\s*([0-9.]+)"),
        "glazing": grab(r"Glazing breakage:\s*([0-9.]+)"),
        "crit_temps": [float(t) for t in re.findall(r"Critical temperature:\s*([0-9]+)", text)],
    }


def _build_params(mesh_axis: float, oracle: dict) -> dict:
    from macs_automation.frc_parser import parse_frc

    params = parse_frc(FRC)["params"]
    params["qf"] = oracle["fire_load"]        # 656.56 MJ/m² (from the PDF)
    params["window_percent"] = oracle["glazing"]  # 80.220 % (from the PDF)
    params["mesh_axis"] = mesh_axis
    return params


@pytest.mark.e2e
@pytest.mark.com
class TestPdfOracle:
    @pytest.fixture(scope="class")
    def oracle(self):
        return _parse_pdf_oracle()

    @pytest.fixture
    def sections_db(self):
        from macs_automation.data_loader import DEFAULT_DATA_PATH, load_data

        ok, reason = com_and_data_available()
        if not ok:
            pytest.skip(reason)
        return load_data(DEFAULT_DATA_PATH)["sections"]

    def _run(self, params, sections_db):
        from macs_automation.engine import MACSEngine

        eng = MACSEngine()
        eng.set_inputs(params, sections_db)
        return eng.run(method="parametric")

    def test_matches_macs_pdf_with_project_mesh_axis(self, sections_db, oracle):
        """mesh_axis = 52 mm (the project value) reproduces the MACS+ PDF."""
        out = self._run(_build_params(PROJECT_MESH_AXIS, oracle), sections_db)

        assert out["uf_max"] == pytest.approx(oracle["uf_max"], abs=0.005)
        assert out["factored_hot"] == pytest.approx(oracle["factored"], abs=0.01)

        engine_temps = sorted(
            round(out[f"side_{s}_critical_temp"]) for s in ("a", "b", "c", "d")
        )
        assert engine_temps == pytest.approx(sorted(oracle["crit_temps"]), abs=2)

    def test_legacy_default_mesh_axis_reproduces_regression(self, sections_db, oracle):
        """mesh_axis = 40 mm (old i-MACS default) yields the reported 0.686 —
        guards against the mesh_axis drop silently returning."""
        out = self._run(_build_params(LEGACY_DEFAULT_MESH_AXIS, oracle), sections_db)
        assert out["uf_max"] == pytest.approx(0.686, abs=0.002)
