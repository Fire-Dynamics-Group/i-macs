"""Tests for frc_parser module — parses MACS+ .frc project files.

The canonical happy-path fixture is ``fixtures/sample.frc`` — same file the
frontend vitest + Playwright suites consume, so a single source of truth.
"""

from pathlib import Path

import pytest

from macs_automation.frc_parser import parse_frc, parse_frc_string


FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_FRC_PATH = FIXTURES / "sample.frc"
SAMPLE_ISO_FRC_PATH = FIXTURES / "sample_iso.frc"
SAMPLE_UNKNOWN_SECTION_FRC_PATH = FIXTURES / "sample_unknown_section.frc"


def _sample_frc_text() -> str:
    return SAMPLE_FRC_PATH.read_text(encoding="utf-8")


@pytest.fixture
def sample_frc_file():
    return SAMPLE_FRC_PATH


class TestParseFrc:
    """Test parsing .frc files into internal parameter dicts."""

    def test_returns_params_and_project(self, sample_frc_file):
        result = parse_frc(sample_frc_file)
        assert "params" in result
        assert "project" in result

    def test_project_metadata(self, sample_frc_file):
        result = parse_frc(sample_frc_file)
        proj = result["project"]
        assert proj["ProjectName"] == "Test Project"
        assert proj["ClientName"] == "Test Client"
        assert proj["JobNumber"] == "0000"
        assert proj["CalculationBy"] == "Test User"
        # URL-decoded comments
        assert "First Floor Slab" in proj["Comments"]

    def test_geometry(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["span1"] == 11.2
        assert params["span2"] == 9.2
        assert params["numbeam"] == 2

    def test_deck(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["DeckId"] == "T10"
        assert params["deck_type"] == "T"
        assert params["deck_depth"] == 60.0
        assert params["deck_trug"] == 300.0
        assert params["deck_top"] == 144.8
        assert params["deck_bot"] == 125.0
        assert params["deck_stiff_height"] == 15.0

    def test_slab(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["conc_type"] == "NW"
        assert params["fck"] == 30.0
        assert params["slab_depth"] == 150.0
        assert params["mesh_type"] == "A193"
        assert params["mesh_area_max"] == 193.0
        assert params["mesh_area_min"] == 193.0
        assert params["mesh_axis"] == 40.0
        assert params["mesh_strength"] == 500.0

    def test_beams_unprotected(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["uSecSize"] == "UB_457x152x60"
        assert params["fy5"] == "355"
        assert params["ush_con"] == 80.0

    def test_beams_side_a(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["SideASecSize"] == "UB_457x152x60"
        assert params["fy1"] == "355"
        assert params["SideAEdgeFlag"] == 0
        assert params["SideACompoFlag"] == 1
        assert params["SideAsh_con"] == 80.0

    def test_beams_side_b_edge(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["SideBSecSize"] == "UB_533x210x101"
        assert params["SideBEdgeFlag"] == 1
        assert params["SideBCompoFlag"] == 0

    def test_beams_side_d(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["SideDSecSize"] == "UB_610x229x101"
        assert params["SideDEdgeFlag"] == 1
        assert params["SideDCompoFlag"] == 0

    def test_loading(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["lead_var_act"] == 5.0
        assert params["othr_var_act"] == 0.0
        assert params["cold_perm"] == 2.0
        assert params["lead_var_fac"] == 0.5
        assert params["othr_var_fac"] == 0.3
        assert params["slab_weight"] == 2.83

    def test_fire_method_parametric(self, sample_frc_file):
        """Method=1 in FRC should map to 'parametric'."""
        params = parse_frc(sample_frc_file)["params"]
        assert params["method"] == "parametric"

    def test_fire_compartment(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["Lc"] == 63.0
        assert params["Bc"] == 12.0
        assert params["Hc"] == 3.6
        assert params["Hw"] == 3.6
        assert params["Lw"] == 63.0
        assert params["window_percent"] == 95.0
        assert params["qf"] == 511.0
        assert params["Bfac"] == 1400.0
        assert params["combustion_factor"] == 0.8
        assert params["growth_rate"] == 1.0

    def test_fire_time_limit(self, sample_frc_file):
        params = parse_frc(sample_frc_file)["params"]
        assert params["time_limit"] == 120.0


class TestFireMethodMapping:
    """Test the FRC Method integer → internal method string mapping."""

    def _make_frc_with_method(self, method_val, tmp_path):
        xml = _sample_frc_text().replace(
            'Name="Method" Value="1"',
            f'Name="Method" Value="{method_val}"',
        )
        frc_file = tmp_path / "test.frc"
        frc_file.write_text(xml, encoding="utf-8")
        return frc_file

    def test_method_0_is_iso(self, tmp_path):
        frc = self._make_frc_with_method(0, tmp_path)
        params = parse_frc(frc)["params"]
        assert params["method"] == "iso"

    def test_method_1_is_parametric(self, tmp_path):
        frc = self._make_frc_with_method(1, tmp_path)
        params = parse_frc(frc)["params"]
        assert params["method"] == "parametric"

    def test_method_2_is_udf(self, tmp_path):
        frc = self._make_frc_with_method(2, tmp_path)
        params = parse_frc(frc)["params"]
        assert params["method"] == "udf"

    def test_sample_iso_fixture_method_is_iso(self):
        """The committed sample_iso.frc fixture must parse as ISO."""
        params = parse_frc(SAMPLE_ISO_FRC_PATH)["params"]
        assert params["method"] == "iso"


class TestParseFrcString:
    """Test parsing from a string (for API upload use case)."""

    def test_parse_from_string(self):
        result = parse_frc_string(_sample_frc_text())
        assert result["params"]["span1"] == 11.2
        assert result["project"]["ProjectName"] == "Test Project"


class TestUrlDecoding:
    """Test that URL-encoded values are properly decoded."""

    def _make_frc_with_project_name(self, encoded_name, tmp_path):
        xml = _sample_frc_text().replace(
            'Name="ProjectName" Value="Test%20Project"',
            f'Name="ProjectName" Value="{encoded_name}"',
        )
        frc_file = tmp_path / "test.frc"
        frc_file.write_text(xml, encoding="utf-8")
        return frc_file

    def test_decodes_percent_encoded_spaces(self, tmp_path):
        frc = self._make_frc_with_project_name("Test%20Project%20Name", tmp_path)
        result = parse_frc(frc)
        assert result["project"]["ProjectName"] == "Test Project Name"

    def test_decodes_special_chars(self, tmp_path):
        frc = self._make_frc_with_project_name("Block%20A%2FB", tmp_path)
        result = parse_frc(frc)
        assert result["project"]["ProjectName"] == "Block A/B"


class TestInvalidFrcFile:
    """Test error handling for invalid files."""

    def test_not_xml(self, tmp_path):
        frc_file = tmp_path / "bad.frc"
        frc_file.write_text("this is not xml", encoding="utf-8")
        with pytest.raises(Exception):
            parse_frc(frc_file)

    def test_wrong_signature(self, tmp_path):
        xml = _sample_frc_text().replace("FRACOFJobFile", "SomethingElse")
        frc_file = tmp_path / "wrong.frc"
        frc_file.write_text(xml, encoding="utf-8")
        with pytest.raises(ValueError, match="signature"):
            parse_frc(frc_file)

    def test_missing_input_section(self, tmp_path):
        xml = '<?xml version="1.0"?><Root><Signature>FRACOFJobFile</Signature></Root>'
        frc_file = tmp_path / "noinput.frc"
        frc_file.write_text(xml, encoding="utf-8")
        with pytest.raises(ValueError, match="Input"):
            parse_frc(frc_file)


class TestUnknownSectionFixture:
    """The unknown-section fixture must still parse — the catalogue lookup
    happens client-side, the parser is content-agnostic."""

    def test_parses_with_unknown_section_id(self):
        result = parse_frc(SAMPLE_UNKNOWN_SECTION_FRC_PATH)
        assert result["params"]["SideASecSize"] == "UB_FAKE_999"
        # Other sides untouched.
        assert result["params"]["SideBSecSize"] == "UB_533x210x101"
