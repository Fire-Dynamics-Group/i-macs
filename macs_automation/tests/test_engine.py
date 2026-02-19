"""Tests for engine.py — COM engine wrapper.

Tests that need the COM engine are marked with @pytest.mark.com.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from macs_automation.engine import MACSEngine, COMProxy, _get_fy, _set_beam_data, _to_numeric


class TestHelpers:
    def test_to_numeric_int(self):
        assert _to_numeric(42) == 42

    def test_to_numeric_float(self):
        assert _to_numeric(3.14) == 3.14

    def test_to_numeric_string_int(self):
        assert _to_numeric("100") == 100

    def test_to_numeric_string_float(self):
        assert _to_numeric("3.14") == 3.14

    def test_to_numeric_bad_string(self):
        assert _to_numeric("abc") == 0

    def test_get_fy_235(self):
        assert _get_fy("235") == 235

    def test_get_fy_355(self):
        assert _get_fy("355") == 355

    def test_get_fy_35H(self):
        assert _get_fy("35H") == 355

    def test_get_fy_460(self):
        assert _get_fy("460") == 460

    def test_get_fy_46H(self):
        assert _get_fy("46H") == 460

    def test_get_fy_numeric_passthrough(self):
        assert _get_fy(355) == 355


class TestSetBeamData:
    def test_sets_section_properties(self):
        """Test that _set_beam_data calls setattr with correct values."""
        eng = MagicMock(spec=[])  # no spec attrs so setattr works
        sections_db = {
            "IPE_500": {"family": "IPE", "grade": "355", "h": 500.0, "b": 200.0,
                        "tw": 10.2, "tf": 16.0, "name": "IPE 500"}
        }
        _set_beam_data(eng, sections_db, "IPE_500",
                       "USectionDepth", "USectionWidth", "UWebThickness", "UFlangeThickness")
        assert eng.USectionDepth == 500.0
        assert eng.USectionWidth == 200.0
        assert eng.UWebThickness == 10.2
        assert eng.UFlangeThickness == 16.0


class FakeCOMProxy:
    """A fake COMProxy that stores properties as a dict for testing."""

    def __init__(self):
        self._props = {}

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._props[name] = value

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._props.get(name)

    def call(self, name, *args):
        pass

    def call_indexed(self, name, index):
        return 0.0


class TestSetInputs:
    """Test the full set_inputs method with a fake COM proxy."""

    @pytest.fixture
    def mock_engine(self):
        eng = MACSEngine.__new__(MACSEngine)  # skip __init__
        eng.engine = FakeCOMProxy()
        return eng

    def _sections_db(self):
        return {
            "IPE_500": {"family": "IPE", "grade": "355", "h": 500.0, "b": 200.0,
                        "tw": 10.2, "tf": 16.0, "name": "IPE 500"}
        }

    def test_shear_connection_divided_by_100(self, mock_engine):
        params = {
            "ush_con": 80, "SideAsh_con": 60, "SideBsh_con": 70,
            "SideCsh_con": 50, "SideDsh_con": 90,
            "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
            "SideASecSize": "IPE_500", "SideBSecSize": "IPE_500",
            "SideCSecSize": "IPE_500", "SideDSecSize": "IPE_500",
        }
        mock_engine.set_inputs(params, self._sections_db())
        assert mock_engine.engine._props["ush_con"] == pytest.approx(0.8)
        assert mock_engine.engine._props["SideAsh_con"] == pytest.approx(0.6)

    def test_conc_type_nw(self, mock_engine):
        params = {
            "conc_type": "NW",
            "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
            "SideASecSize": "IPE_500", "SideBSecSize": "IPE_500",
            "SideCSecSize": "IPE_500", "SideDSecSize": "IPE_500",
        }
        mock_engine.set_inputs(params, self._sections_db())
        assert mock_engine.engine._props["conc_type"] == 0

    def test_conc_type_lw(self, mock_engine):
        params = {
            "conc_type": "LW",
            "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
            "SideASecSize": "IPE_500", "SideBSecSize": "IPE_500",
            "SideCSecSize": "IPE_500", "SideDSecSize": "IPE_500",
        }
        mock_engine.set_inputs(params, self._sections_db())
        assert mock_engine.engine._props["conc_type"] == 1

    def test_deck_type_trapezoidal(self, mock_engine):
        params = {
            "deck_type": "T",
            "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
            "SideASecSize": "IPE_500", "SideBSecSize": "IPE_500",
            "SideCSecSize": "IPE_500", "SideDSecSize": "IPE_500",
        }
        mock_engine.set_inputs(params, self._sections_db())
        assert mock_engine.engine._props["deck_type"] == 0

    def test_no_steel_deck_zeroes_depth(self, mock_engine):
        params = {
            "SteelDeck": "0", "deck_depth": 58,
            "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
            "SideASecSize": "IPE_500", "SideBSecSize": "IPE_500",
            "SideCSecSize": "IPE_500", "SideDSecSize": "IPE_500",
        }
        mock_engine.set_inputs(params, self._sections_db())
        assert mock_engine.engine._props["deck_depth"] == 0

    def test_cellular_beam_zeroes_diam(self, mock_engine):
        params = {
            "USecTypeFlag": "1",
            "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
            "SideASecSize": "IPE_500", "SideBSecSize": "IPE_500",
            "SideCSecSize": "IPE_500", "SideDSecSize": "IPE_500",
        }
        mock_engine.set_inputs(params, self._sections_db())
        assert mock_engine.engine._props["uSecDiam"] == 0


@pytest.mark.com
class TestCOMIntegration:
    """Integration tests requiring the actual COM engine.

    Run with: pytest -m com
    """

    @pytest.fixture
    def real_data(self):
        from macs_automation.data_loader import load_data
        data_path = Path(r"C:\Program Files (x86)\MACS+\EN\Data\Data.xml")
        if not data_path.exists():
            pytest.skip("MACS+ not installed")
        return load_data(data_path)

    def test_iso_fire_default_params(self, real_data):
        """Run a single ISO fire analysis with defaults and verify outputs."""
        from macs_automation.sweep import DEFAULTS, resolve_deck, resolve_mesh

        params = dict(DEFAULTS)
        resolve_deck(params, real_data["decks"])
        resolve_mesh(params, real_data["meshes"])

        engine = MACSEngine()
        engine.set_inputs(params, real_data["sections"])
        outputs = engine.run(method="iso")

        assert "comp_failure" in outputs
        assert "uf_max" in outputs
        assert "time_series" in outputs
        assert len(outputs["time_series"]) > 0
        assert outputs["uf_max"] >= 0
        assert outputs["duration_ms"] > 0
