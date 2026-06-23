"""Validate the MACS+ report PDF parser (`macs_automation.pdf_oracle`).

These run without COM / MACS+ — they check the parser against the eight Atlantic
Park Unit 6 reference reports using self-consistency invariants internal to each
report. The PDF is the single source of truth: the run filenames encode the
intended sweep inputs but are known to be unreliable (e.g. run00002's filename
says fireload 323.69 while the report itself ran 321.83), so nothing here is
asserted against the filename.

Invariants checked, all PDF-internal:
  * the load model reproduces the report's "Factored load in fire";
  * the parsed fire load / glazing agree between the engine inputs and the
    oracle outputs (same printed values, read independently);
  * the summary unity factor equals the max of the printed time-series table;
  * all four perimeter sides parse with a sane critical temp + load ratio.
"""

from pathlib import Path

import pytest

from macs_automation.pdf_oracle import parse_oracle, parse_params, parse_pdf, read_text

FIXTURES = Path(__file__).parent / "fixtures"
REF_DIR = FIXTURES / "macs_reference_pdfs"
# Reference reports are grouped by project unit (unit6/, unit7/); run-ids repeat
# across units, so each fixture is identified as "<unit>-<runNNNNN>".
PDFS = sorted(REF_DIR.glob("*/run*.pdf"))


def _run_id(pdf: Path) -> str:
    return f"{pdf.parent.name}-{pdf.stem[:8]}"


def test_fixtures_present():
    by_unit = {u: len(list((REF_DIR / u).glob("run*.pdf"))) for u in ("unit6", "unit7")}
    assert by_unit == {"unit6": 8, "unit7": 12}, by_unit


@pytest.mark.parametrize("pdf", PDFS, ids=_run_id)
def test_inputs_and_oracle_agree_on_fire_load(pdf):
    """Fire load and glazing are read independently for inputs vs oracle."""
    parsed = parse_pdf(pdf)
    assert parsed["params"]["qf"] == pytest.approx(parsed["oracle"]["fire_load"], abs=0.01)
    assert parsed["params"]["window_percent"] == pytest.approx(parsed["oracle"]["glazing"], abs=0.01)


@pytest.mark.parametrize("pdf", PDFS, ids=_run_id)
def test_factored_load_identity(pdf):
    """The parsed load model reproduces the report's factored fire load."""
    p = parse_params(read_text(pdf))
    oracle = parse_oracle(read_text(pdf))
    reconstructed = (
        p["cold_perm"] + p["slab_weight"]
        + p["lead_var_fac"] * p["lead_var_act"]
        + p["othr_var_fac"] * p["othr_var_act"]
    )
    assert reconstructed == pytest.approx(oracle["factored_hot"], abs=0.01)


@pytest.mark.parametrize("pdf", PDFS, ids=_run_id)
def test_summary_uf_equals_table_max(pdf):
    oracle = parse_oracle(read_text(pdf))
    assert oracle["table"], "no time-series rows parsed"
    table_max = max(row["unity_factor"] for row in oracle["table"])
    assert oracle["uf_max"] == pytest.approx(table_max, abs=0.005)


@pytest.mark.parametrize("pdf", PDFS, ids=_run_id)
def test_four_sides_parsed(pdf):
    oracle = parse_oracle(read_text(pdf))
    assert set(oracle["sides"]) == {"a", "b", "c", "d"}
    for side in oracle["sides"].values():
        assert side["critical_temp"] > 0
        assert 0 <= side["load_ratio"] <= 2


def test_params_complete_for_engine():
    """Every input MACSEngine.set_inputs reads is present and typed."""
    params = parse_pdf(PDFS[0])["params"]
    required = [
        "numbeam", "span1", "span2", "slab_depth", "fck", "mesh_axis",
        "deck_depth", "deck_trug", "deck_top", "deck_bot", "deck_stiff_height",
        "mesh_area_max", "mesh_area_min", "mesh_strength", "slab_weight",
        "lead_var_act", "lead_var_fac", "cold_perm", "othr_var_act", "othr_var_fac",
        "Lc", "Bc", "Hc", "Hw", "Lw",
        "window_percent", "qf", "Bfac", "combustion_factor", "growth_rate",
        "conc_type", "deck_type", "method", "uSecSize",
        "SideASecSize", "SideBSecSize", "SideCSecSize", "SideDSecSize",
        "SideAEdgeFlag", "SideBEdgeFlag", "SideCEdgeFlag", "SideDEdgeFlag",
    ]
    missing = [k for k in required if k not in params]
    assert not missing, f"missing engine inputs: {missing}"


def test_unit6_geometry_and_mesh_axis():
    """Spot-check the reconstructed Unit 6 geometry against the report."""
    p = parse_pdf(REF_DIR / "unit6" / next(f.name for f in (REF_DIR / "unit6").glob("run00001*")))["params"]
    assert p["span1"] == pytest.approx(7.1)
    assert p["span2"] == pytest.approx(9.0)
    assert p["mesh_axis"] == pytest.approx(40.0)   # Unit 6 used 40 mm (cf. Unit 7's 52)
    assert p["numbeam"] == 2
    assert p["SideASecSize"] == "UB_356x127x33"
    assert p["SideBSecSize"] == "UB_457x152x52"
    assert p["SideAEdgeFlag"] == 0 and p["SideBEdgeFlag"] == 1
    assert p["growth_rate"] == 1.0   # "Medium"


def test_unit7_geometry_and_mesh_axis():
    """Unit 7 has different spans and mesh axis (52 mm) — the field at the
    centre of the 0.65-vs-0.686 discrepancy study."""
    p = parse_pdf(next((REF_DIR / "unit7").glob("run*.pdf")))["params"]
    assert p["span1"] == pytest.approx(7.3)
    assert p["span2"] == pytest.approx(7.48)
    assert p["mesh_axis"] == pytest.approx(52.0)
