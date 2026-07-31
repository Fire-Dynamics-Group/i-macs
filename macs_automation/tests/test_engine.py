"""Tests for engine.py — COM engine wrapper.

Tests that need the COM engine are marked with @pytest.mark.com.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from macs_automation.engine import MACSEngine, COMProxy, _get_fy, _set_beam_data, _to_numeric, run_one_com


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
    """A fake COMProxy that stores properties as a dict for testing.

    Indexed output series (uf(i), lofl_temp2(i), ...) are served from
    ``_series``: a ``{name: {index: value}}`` dict; unknown names/indices
    read as 0.0, like a real engine returning zeroed outputs.
    """

    def __init__(self):
        self._props = {}
        self._series = {}

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
        return self._series.get(name, {}).get(index, 0.0)


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


class TestReadOutputs:
    """_read_outputs() reads scalar outputs off the live COM engine.

    Regression coverage for mb1_reqd/mb2_reqd: the real FRACOF property names
    are Mb1_Reqd_1 / Mb2_Reqd_1 (confirmed by enumerating the live COM
    interface's ITypeInfo) — the FillPerim1Beam report table in MACS+'s own
    PrintP.js reads the same two properties to derive each perimeter side's
    "Required moment resistance" and "Line load in fire situation".
    """

    @pytest.fixture
    def mock_engine(self):
        eng = MACSEngine.__new__(MACSEngine)  # skip __init__
        eng.engine = FakeCOMProxy()
        eng.engine_version = None
        eng.engine.COMPFAILURE = 0
        eng.engine.time_intervals_count = 0
        for side in ("A", "B", "C", "D"):
            setattr(eng.engine, f"Side{side}LoadRatio", 0.0)
            setattr(eng.engine, f"Side{side}CriticalTemp", 0.0)
        return eng

    def test_mb1_reqd_reads_the_real_com_property(self, mock_engine):
        mock_engine.engine.Mb1_Reqd_1 = 167.61
        result = mock_engine._read_outputs()
        assert result["mb1_reqd"] == pytest.approx(167.61)

    def test_mb2_reqd_reads_the_real_com_property(self, mock_engine):
        mock_engine.engine.Mb2_Reqd_1 = 105.06
        result = mock_engine._read_outputs()
        assert result["mb2_reqd"] == pytest.approx(105.06)

    def test_mb1_reqd_defaults_to_zero_when_absent(self, mock_engine):
        result = mock_engine._read_outputs()
        assert result["mb1_reqd"] == 0.0


class TestSecondMeshLoop:
    """When mesh_area_min != mesh_area_max (and OneLoop != 1) FRACOF computes a
    SECOND analysis: MACS+'s Calc.js reads uf2/time_intervals_count2, reports
    ufmax = max(UF1Max, UF2Max) and displays the governing loop's table and
    extremes (GraphTbl / CalcExtremes, Calc.js lines 354-380 + 448). Only
    square meshes (main area == transverse area, e.g. A193) skip the loop; any
    B-series mesh diverges without this.
    """

    def _sections_db(self):
        return {
            "IPE_500": {"family": "IPE", "grade": "355", "h": 500.0, "b": 200.0,
                        "tw": 10.2, "tf": 16.0, "name": "IPE 500"}
        }

    def _params(self, **overrides):
        p = {
            "uSecSize": "IPE_500", "uSec1Size": "IPE_500", "uSec2Size": "IPE_500",
            "SideASecSize": "IPE_500", "SideBSecSize": "IPE_500",
            "SideCSecSize": "IPE_500", "SideDSecSize": "IPE_500",
        }
        p.update(overrides)
        return p

    def _engine_with_two_loops(self, uf1=0.5, uf2=0.9):
        eng = MACSEngine.__new__(MACSEngine)  # skip __init__
        eng.engine = FakeCOMProxy()
        eng.engine_version = None
        eng.engine.COMPFAILURE = 0
        for side in ("A", "B", "C", "D"):
            setattr(eng.engine, f"Side{side}LoadRatio", 0.0)
            setattr(eng.engine, f"Side{side}CriticalTemp", 0.0)
        eng.engine.time_intervals_count = 1
        eng.engine.time_intervals_count2 = 1
        eng.engine._series["uf"] = {1: uf1}
        eng.engine._series["uf2"] = {1: uf2}
        eng.engine._series["lofl_temp"] = {1: 500.0}
        eng.engine._series["lofl_temp2"] = {1: 600.0}
        eng.engine._series["time_interval"] = {1: 15.0}
        eng.engine._series["time_interval2"] = {1: 15.0}
        return eng

    def test_second_loop_flag_set_when_mesh_areas_differ(self):
        eng = MACSEngine.__new__(MACSEngine)
        eng.engine = FakeCOMProxy()
        eng.set_inputs(self._params(mesh_area_max=283, mesh_area_min=193),
                       self._sections_db())
        assert eng.second_loop is True

    def test_second_loop_flag_clear_for_square_mesh(self):
        eng = MACSEngine.__new__(MACSEngine)
        eng.engine = FakeCOMProxy()
        eng.set_inputs(self._params(mesh_area_max=193, mesh_area_min=193),
                       self._sections_db())
        assert eng.second_loop is False

    def test_second_loop_flag_clear_when_one_loop_requested(self):
        """MACS+'s OneLoop flag suppresses the second analysis read."""
        eng = MACSEngine.__new__(MACSEngine)
        eng.engine = FakeCOMProxy()
        eng.set_inputs(self._params(mesh_area_max=283, mesh_area_min=193,
                                    OneLoop="1"),
                       self._sections_db())
        assert eng.second_loop is False

    def test_uf_max_is_max_over_both_loops(self):
        eng = self._engine_with_two_loops(uf1=0.5, uf2=0.9)
        eng.second_loop = True
        result = eng._read_outputs()
        assert result["uf_max"] == pytest.approx(0.9)
        assert result["uf1_max"] == pytest.approx(0.5)
        assert result["uf2_max"] == pytest.approx(0.9)

    def test_governing_loop_2_supplies_time_series_and_extremes(self):
        """Mirrors CalcExtremes(GraphTbl): when UF2Max > UF1Max the second
        loop's table and extremes are what MACS+ reports."""
        eng = self._engine_with_two_loops(uf1=0.5, uf2=0.9)
        eng.second_loop = True
        result = eng._read_outputs()
        assert result["governing_mesh_loop"] == 2
        assert result["time_series"][0]["lofl_temp"] == pytest.approx(600.0)
        assert result["max_temperature"] == pytest.approx(600.0)

    def test_governing_loop_1_keeps_first_series(self):
        eng = self._engine_with_two_loops(uf1=0.9, uf2=0.5)
        eng.second_loop = True
        result = eng._read_outputs()
        assert result["governing_mesh_loop"] == 1
        assert result["uf_max"] == pytest.approx(0.9)
        assert result["time_series"][0]["lofl_temp"] == pytest.approx(500.0)

    def test_no_second_loop_reads_nothing_extra(self):
        eng = self._engine_with_two_loops(uf1=0.5, uf2=0.9)
        eng.second_loop = False
        result = eng._read_outputs()
        assert result["uf_max"] == pytest.approx(0.5)
        assert result["uf2_max"] is None
        assert result["governing_mesh_loop"] == 1

    def test_engine_without_loop2_properties_degrades_gracefully(self):
        """An engine variant that never exposes time_intervals_count2 must not
        crash the read — treat it as an empty second loop."""
        eng = self._engine_with_two_loops(uf1=0.5, uf2=0.9)
        eng.engine._props.pop("time_intervals_count2")
        eng.second_loop = True
        result = eng._read_outputs()
        assert result["uf_max"] == pytest.approx(0.5)
        assert result["uf2_max"] is None


class TestComRunnerIsolation:
    """run_one_com spawns com_runner as a subprocess so a FRACOF/COM crash
    or any unhandled exception inside _run_one() can't take down the parent
    FastAPI sidecar."""

    def test_runtime_error_in_runner_surfaces_as_runtime_error_not_crash(self, tmp_path):
        """A RuntimeError raised inside _run_one() comes back through the JSON
        protocol as RuntimeError in the parent — the parent process keeps running."""
        # Simulate the runner by invoking com_runner.main() with patched _run_one.
        # com_runner.main() catches the exception and writes {"error": ...} to stdout;
        # run_one_com() then reads that and raises RuntimeError.
        import io
        import json
        from macs_automation import com_runner

        fake_stdin = io.StringIO(json.dumps({"params": {}, "sections_db": {}}) + "\n")
        fake_stdout = io.StringIO()

        with patch.object(com_runner, "_run_one", side_effect=RuntimeError("boom")), \
             patch.object(sys, "stdin", fake_stdin), \
             patch.object(sys, "stdout", fake_stdout):
            com_runner.main()

        output = json.loads(fake_stdout.getvalue().strip())
        assert "error" in output
        assert "RuntimeError" in output["error"]
        assert "boom" in output["error"]

    def test_run_one_com_translates_runner_error_to_runtime_error(self):
        """When run_one_com() reads {"error": ...} on stdout, it raises RuntimeError
        — without re-raising the runner's own exception class (which lives in a dead process)."""
        fake_proc = MagicMock()
        fake_proc.stdout = '{"error": "RuntimeError: boom"}\n'
        fake_proc.stderr = ""

        with patch("macs_automation.engine.subprocess.run", return_value=fake_proc):
            with pytest.raises(RuntimeError, match="boom"):
                run_one_com({}, {})

    def test_run_one_com_handles_runner_no_output(self):
        """A runner that crashes hard (no stdout) surfaces as RuntimeError in the parent."""
        fake_proc = MagicMock()
        fake_proc.stdout = ""
        fake_proc.stderr = "Fatal Python error: Segmentation fault"

        with patch("macs_automation.engine.subprocess.run", return_value=fake_proc):
            with pytest.raises(RuntimeError, match="Segmentation fault"):
                run_one_com({}, {})

    def test_run_one_com_unfrozen_spawns_with_dash_m(self):
        """In a normal (unfrozen) Python run, the runner is invoked as
        `python -m macs_automation.com_runner` — the import-based form."""
        fake_proc = MagicMock()
        fake_proc.stdout = '{"comp_failure": false}\n'
        fake_proc.stderr = ""

        with patch("macs_automation.engine.subprocess.run", return_value=fake_proc) as mock_run, \
             patch.object(sys, "frozen", False, create=True):
            run_one_com({}, {})

        argv = mock_run.call_args[0][0]
        assert argv == [sys.executable, "-m", "macs_automation.com_runner"]

    def test_run_one_com_frozen_spawns_with_com_runner_flag(self):
        """In a PyInstaller-frozen build, sys.executable is the sidecar exe,
        which doesn't honour `-m module`. Spawn it with the `--com-runner`
        sentinel instead so app.main() can dispatch to com_runner.main()."""
        fake_proc = MagicMock()
        fake_proc.stdout = '{"comp_failure": false}\n'
        fake_proc.stderr = ""

        with patch("macs_automation.engine.subprocess.run", return_value=fake_proc) as mock_run, \
             patch.object(sys, "frozen", True, create=True):
            run_one_com({}, {})

        argv = mock_run.call_args[0][0]
        assert argv == [sys.executable, "--com-runner"]


@pytest.mark.com
@pytest.mark.e2e
class TestCOMIntegration:
    """Integration tests requiring the actual COM engine (32-bit Python + MACS+).

    Run with: pytest -m com   (skips with clear reason if COM/Data not available)
    """

    @pytest.fixture
    def real_data(self):
        from macs_automation.tests.conftest import com_and_data_available
        from macs_automation.data_loader import load_data, DEFAULT_DATA_PATH

        ok, reason = com_and_data_available()
        if not ok:
            pytest.skip(reason)
        return load_data(DEFAULT_DATA_PATH)

    def test_iso_fire_default_params(self, real_data):
        """Run a single ISO fire analysis with defaults and verify outputs."""
        from macs_automation.sweep import DEFAULTS, resolve_deck, resolve_mesh

        params = dict(DEFAULTS)
        resolve_deck(params, real_data["decks"])
        resolve_mesh(params, real_data["meshes"])

        outputs = run_one_com(params, real_data["sections"])

        assert "comp_failure" in outputs
        assert "uf_max" in outputs
        assert "time_series" in outputs
        assert len(outputs["time_series"]) > 0
        assert outputs["uf_max"] >= 0
        assert outputs["duration_ms"] > 0
