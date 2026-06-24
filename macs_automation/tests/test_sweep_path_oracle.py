"""Sweep-pipeline oracle: the *path* (config -> generate_combinations -> engine)
must reproduce the MACS+ Dropbox reports, not just the bare engine.

This guards the failure mode that produced the rc.9 / Atlantic Park 10k divergence:
`mesh_axis` was absent from the sweep `fixed` block, so `sweep.DEFAULTS["mesh_axis"]=40`
silently overrode the .frc's 52, shifting every membrane capacity. The bare-engine
oracle (`test_e2e_macs_sweep_oracle.py`) could not catch it because it fed the engine
inputs parsed straight from the PDF. These tests drive the real sweep merge.
"""

from pathlib import Path

import pytest

from macs_automation.pdf_oracle import parse_pdf
from macs_automation.sweep import generate_combinations
from macs_automation.tests.conftest import com_and_data_available

REF_DIR = Path(__file__).parent / "fixtures" / "macs_reference_pdfs" / "unit7"
PDFS = sorted(REF_DIR.glob("run*.pdf"))


def _sweep_config_from(params: dict, *, drop_mesh_axis: bool = False) -> dict:
    """Build a sweep config the way the form does: structural inputs fixed,
    qf + window_percent swept. `drop_mesh_axis` simulates the rc.9 bug."""
    fixed = {k: v for k, v in params.items() if k not in ("qf", "window_percent")}
    if drop_mesh_axis:
        fixed.pop("mesh_axis", None)
    return {
        "analysis_method": "parametric",
        "fixed": fixed,
        "sweep": {"qf": [params["qf"]], "window_percent": [params["window_percent"]]},
    }


def test_sweep_path_carries_mesh_axis():
    """A .frc-supplied mesh_axis must survive the DEFAULTS+fixed merge (not fall to 40)."""
    params = parse_pdf(PDFS[0])["params"]
    assert params["mesh_axis"] == 52  # the Unit 7 reference value
    combo = generate_combinations(_sweep_config_from(params))[0]
    assert combo["mesh_axis"] == 52


def test_sweep_path_drops_to_default_when_omitted():
    """Teeth: if the form omits mesh_axis (the rc.9 bug), the sweep silently uses 40.
    This documents the failure and proves the carrying test above has teeth."""
    params = parse_pdf(PDFS[0])["params"]
    combo = generate_combinations(_sweep_config_from(params, drop_mesh_axis=True))[0]
    assert combo["mesh_axis"] == 40  # sweep.DEFAULTS — the silent wrong value


@pytest.mark.e2e
@pytest.mark.com
class TestSweepPathOracle:
    @pytest.fixture(scope="class")
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

    @pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem[:8])
    def test_sweep_path_reproduces_macs(self, pdf, sections_db):
        """Full path: config -> generate_combinations -> engine matches the Dropbox PDF."""
        parsed = parse_pdf(pdf)
        oracle = parsed["oracle"]
        combo = generate_combinations(_sweep_config_from(parsed["params"]))[0]
        out = self._run(combo, sections_db)
        assert out["uf_max"] == pytest.approx(oracle["uf_max"], abs=0.005)

    def test_sub5pct_opening_floored_like_macs(self, sections_db):
        """MACS floors window_percent to a 5% minimum (opening factor 0.01). A raw
        sub-5% opening from the sweep must still reproduce MACS — not under-ventilate
        and floor to the cold value. run09134's sampled opening was 0.216%; its MACS
        report used 5.0% and gives uf~0.32."""
        ref = next(p for p in PDFS if p.stem.startswith("run09134"))
        parsed = parse_pdf(ref)
        oracle = parsed["oracle"]
        params = dict(parsed["params"])
        params["window_percent"] = 0.215696885  # the raw sampled value the sweep feeds
        out = self._run(params, sections_db)
        assert out["uf_max"] == pytest.approx(oracle["uf_max"], abs=0.005)

    def test_dropping_mesh_axis_breaks_the_match(self, sections_db):
        """Teeth at the engine level: the rc.9 bug (mesh_axis=40) must NOT match Dropbox.

        The bug is utilisation-dependent — a fixed ~0.5 kN/m2 capacity offset is
        negligible when cold but tips a hot run over the line. So we test the
        *hottest* reference run, where mesh_axis=40 clearly over-predicts uf."""
        hot = max(PDFS, key=lambda p: parse_pdf(p)["oracle"]["uf_max"])
        parsed = parse_pdf(hot)
        oracle = parsed["oracle"]
        buggy = generate_combinations(
            _sweep_config_from(parsed["params"], drop_mesh_axis=True)
        )[0]
        out = self._run(buggy, sections_db)
        assert out["uf_max"] != pytest.approx(oracle["uf_max"], abs=0.005)
        assert out["uf_max"] > oracle["uf_max"]  # the bug over-predicts utilisation
