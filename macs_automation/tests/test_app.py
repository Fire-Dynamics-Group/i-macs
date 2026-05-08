"""Tests for app.py — FastAPI web application."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from macs_automation.app import app, _sweep_state, _sweep_lock, _run_single_com, DB_PATH


@pytest.fixture(autouse=True)
def mock_ref_data():
    """Provide fake reference data so tests don't need Data.xml."""
    import macs_automation.app as app_module
    app_module._ref_data = {
        "sections": {
            "IPE_500": {"family": "IPE", "name": "IPE 500", "h": 500, "b": 200, "tw": 10.2, "tf": 16},
            "IPE_300": {"family": "IPE", "name": "IPE 300", "h": 300, "b": 150, "tw": 7.1, "tf": 10.7},
            "HE_300A": {"family": "HE", "name": "HE 300 A", "h": 290, "b": 300, "tw": 8.5, "tf": 14},
        },
        "decks": {
            "T14": {"deck_type": "T", "deck_depth": 58, "deck_trug": 207, "deck_top": 106, "deck_bot": 62, "deck_stiff_height": 0, "name": "COFRAPLUS 60"},
        },
        "meshes": {
            "ST15C": {"mainArea": 142, "transArea": 142, "min_mesh_dia": 6, "max_mesh_dia": 6, "name": "ST15C"},
            "A393": {"mainArea": 393, "transArea": 393, "min_mesh_dia": 10, "max_mesh_dia": 10, "name": "A393"},
        },
    }
    yield
    app_module._ref_data = None


@pytest.fixture
def use_tmp_db(tmp_path, monkeypatch):
    """Point the app at a temporary database."""
    import macs_automation.app as app_module
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    return tmp_path / "test.db"


@pytest.fixture
def client(use_tmp_db):
    return TestClient(app)


@pytest.fixture
def seeded_db(use_tmp_db):
    """Create a DB with some sample runs."""
    from macs_automation.db import ResultsDB
    db = ResultsDB(use_tmp_db)
    for i in range(5):
        params = {"span1": 9.0 + i, "span2": 9.0, "uSecSize": "IPE_500",
                  "method": "iso", "time_limit": 60, "fck": 25, "slab_depth": 130}
        outputs = {
            "comp_failure": 0, "mb1_reqd": 100.0, "mb2_reqd": 200.0,
            "factored_hot": 50.0, "uf_max": 0.5 + i * 0.2,
            "max_temperature": 900.0, "max_deflection": 120.0,
            "max_slab_cap": 500.0, "max_beam_cap": 300.0, "max_total_cap": 800.0,
            "side_a_load_ratio": 0.3, "side_a_critical_temp": 650.0,
            "side_b_load_ratio": 0.4, "side_b_critical_temp": 620.0,
            "side_c_load_ratio": 0.35, "side_c_critical_temp": 640.0,
            "side_d_load_ratio": 0.32, "side_d_critical_temp": 645.0,
            "duration_ms": 150.0,
            "time_series": [
                {"time_step": 1, "time_min": 5.0, "fire_temp": 576.0,
                 "lofl_temp": 200.0, "mesh_temp": 100.0,
                 "slabtop_temp": 50.0, "slabbot_temp": 300.0,
                 "beam_hot_capacity": 250.0, "deflection": 10.0,
                 "slab_yield": 5.0, "enhancement": 1.2,
                 "slab_cap": 400.0, "total_plate_capacity": 700.0,
                 "utilization_factor": 0.7},
            ],
        }
        db.insert_run(params, outputs=outputs)
    # Insert one error run
    db.insert_run({"span1": 99.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60},
                  error="COM error")
    db.close()
    return use_tmp_db


class TestRefDataEndpoints:
    def test_get_sections(self, client):
        resp = client.get("/api/sections")
        assert resp.status_code == 200
        data = resp.json()
        assert "IPE" in data
        assert "HE" in data
        assert any(s["id"] == "IPE_500" for s in data["IPE"])

    def test_get_decks(self, client):
        resp = client.get("/api/decks")
        assert resp.status_code == 200
        data = resp.json()
        assert "T14" in data
        assert data["T14"]["deck_type"] == "T"

    def test_get_meshes(self, client):
        resp = client.get("/api/meshes")
        assert resp.status_code == 200
        data = resp.json()
        assert "ST15C" in data
        assert "A393" in data


class TestRunEndpoints:
    def test_list_runs_empty(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"] == []
        assert data["stats"]["total"] == 0

    def test_list_runs_with_data(self, seeded_db):
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 6
        assert data["stats"]["total"] == 6

    def test_get_run(self, seeded_db):
        client = TestClient(app)
        resp = client.get("/api/runs/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["span1"] == 9.0

    def test_get_run_not_found(self, client):
        resp = client.get("/api/runs/999")
        assert resp.status_code == 404

    def test_get_timeseries(self, seeded_db):
        client = TestClient(app)
        resp = client.get("/api/runs/1/timeseries")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["time_min"] == 5.0

    def test_post_runs_uses_run_one_com(self, client):
        """POST /api/runs must use _run_single_com (which spawns the com_runner subprocess)."""
        with patch("macs_automation.app._run_single_com") as mock_run:
            mock_run.return_value = {"uf_max": 0.5, "duration_ms": 100, "comp_failure": 0, "time_series": []}
            resp = client.post("/api/runs", json={"method": "iso"})
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data and data.get("uf_max") == 0.5
        mock_run.assert_called_once()

    def test_single_run_round_trip_with_defaults(self, client):
        """Slice 5 done criterion: POST /api/runs with an empty body fills in
        DEFAULTS for every parameter the engine needs."""
        with patch("macs_automation.app._run_single_com") as mock_run:
            mock_run.return_value = {
                "uf_max": 0.7, "duration_ms": 250, "comp_failure": 0, "time_series": [],
            }
            resp = client.post("/api/runs", json={})
        assert resp.status_code == 200
        sent = mock_run.call_args[0][0]
        # Defaults from sweep.DEFAULTS made it through.
        assert sent["span1"] == 9.0
        assert sent["method"] == "iso"
        assert sent["fck"] == 25
        assert sent["uSecSize"] == "IPE_500"

    def test_qf_below_floor_does_not_crash(self, client):
        """Passing qf=0.5 must not 500 — engine clamps to >=1.0 internally
        (see engine.set_inputs: 'avoid FRACOF thermal instability')."""
        with patch("macs_automation.app._run_single_com") as mock_run:
            mock_run.return_value = {
                "uf_max": 0.3, "duration_ms": 90, "comp_failure": 0, "time_series": [],
            }
            resp = client.post("/api/runs", json={"qf": 0.5, "method": "iso"})
        assert resp.status_code == 200
        # The clamp lives in MACSEngine.set_inputs; the API layer just
        # forwards the user's value verbatim.
        assert mock_run.call_args[0][0]["qf"] == 0.5


class TestSweepLHS:
    def test_lhs_sweep_starts(self, client):
        """POST /api/sweeps with LHS config starts a sweep."""
        payload = {
            "sampling": "lhs",
            "analysis_method": "parametric",
            "n_samples": 9,
            "seed": 42,
            "distributions": {
                "qf": {"preset": "Office"},
                "window_percent": {"preset": "Opening Factor", "transform": "opening_factor"},
            },
            "fixed": {
                "span1": 9, "span2": 9, "numbeam": 2, "slab_depth": 130, "fck": 25,
                "Lc": 27, "Bc": 18, "Hc": 3.6, "Hw": 1.8, "Lw": 30,
                "combustion_factor": 0.8,
            },
        }
        with patch("macs_automation.app._run_sweep_background") as mock_run:
            resp = client.post("/api/sweeps", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 9
            assert "Sweep started" in data["message"]
            # Background thread was started with 9 combinations
            assert mock_run.call_count == 1  # called once via background thread
            # But a thread was created — verify state was set up
            # (the thread target is mock_run, so it won't actually run COM)

    def test_lhs_sweep_generates_correct_combinations(self, client):
        """LHS config produces combinations with varying qf and window_percent."""
        payload = {
            "sampling": "lhs",
            "analysis_method": "parametric",
            "n_samples": 5,
            "seed": 42,
            "distributions": {
                "qf": {"preset": "Office"},
                "window_percent": {"preset": "Opening Factor", "transform": "opening_factor"},
            },
            "fixed": {"span1": 9, "span2": 9},
        }
        combinations = []

        def capture_combinations(combos, sections_db, mode="sweep"):
            combinations.extend(combos)

        with patch("macs_automation.app._run_sweep_background", side_effect=capture_combinations):
            with patch("threading.Thread") as mock_thread:
                # Make thread.start() call the target directly
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"] if "target" in args[1] else args[0][0]
                    target_args = args[1].get("args", ())
                    target(*target_args)

                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance

                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200

        assert len(combinations) == 5
        # All combinations should have parametric method
        assert all(c["method"] == "parametric" for c in combinations)
        # qf values should vary (LHS produces different samples)
        qf_values = [c["qf"] for c in combinations]
        assert len(set(qf_values)) > 1, "LHS should produce varying qf values"
        # window_percent values should vary
        wp_values = [c["window_percent"] for c in combinations]
        assert len(set(wp_values)) > 1, "LHS should produce varying window_percent values"
        # Fixed values should be preserved
        assert all(c["span1"] == 9 for c in combinations)


class TestSweepStatus:
    def test_sweep_status_idle(self, client):
        with _sweep_lock:
            _sweep_state["active"] = False
            _sweep_state["total"] = 0
            _sweep_state["completed"] = 0
        resp = client.get("/api/sweeps/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    def test_sweep_state_includes_mode_key(self):
        """_sweep_state dict includes 'mode' key."""
        assert "mode" in _sweep_state

    def test_sweep_status_returns_mode(self, client):
        """GET /api/sweeps/status includes mode in response."""
        with _sweep_lock:
            _sweep_state["mode"] = "lhs"
        resp = client.get("/api/sweeps/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "lhs"

    def test_sweep_status_returns_sweep_mode(self, client):
        """GET /api/sweeps/status returns 'sweep' mode for grid sweeps."""
        with _sweep_lock:
            _sweep_state["mode"] = "sweep"
        resp = client.get("/api/sweeps/status")
        data = resp.json()
        assert data["mode"] == "sweep"

    def test_lhs_submit_sets_mode_lhs(self, client):
        """POST /api/sweeps with sampling=lhs passes mode='lhs' to background."""
        payload = {
            "sampling": "lhs",
            "analysis_method": "parametric",
            "n_samples": 3,
            "seed": 42,
            "distributions": {"qf": {"preset": "Office"}},
            "fixed": {"span1": 9, "span2": 9},
        }
        with patch("macs_automation.app._run_sweep_background") as mock_run:
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"] if "target" in args[1] else args[0][0]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200
                # Verify mode='lhs' was passed to background function
                mock_run.assert_called_once()
                _, _, mode_arg = mock_run.call_args[0]
                assert mode_arg == "lhs"

    def test_grid_sweep_submit_sets_mode_sweep(self, client):
        """POST /api/sweeps without sampling=lhs passes mode='sweep' to background."""
        payload = {
            "analysis_method": "iso",
            "sweep": {"qf": [300, 500]},
            "fixed": {"span1": 9, "span2": 9},
        }
        with patch("macs_automation.app._run_sweep_background") as mock_run:
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"] if "target" in args[1] else args[0][0]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200
                mock_run.assert_called_once()
                _, _, mode_arg = mock_run.call_args[0]
                assert mode_arg == "sweep"


class TestFrcImport:
    """Tests for the /api/import-frc endpoint."""

    MINIMAL_FRC = """\
<?xml version="1.0" encoding="utf-8"?>
<Root>
    <Signature>FRACOFJobFile</Signature>
    <FormatVersion>4.0</FormatVersion>
    <Input>
        <Project>
            <Property Name="ProjectName" Value="Test%20Project" />
            <Property Name="JobNumber" Value="1234" />
        </Project>
        <GA>
            <Property Name="span1" Value="10.5" />
            <Property Name="span2" Value="8.0" />
            <Property Name="numbeam" Value="3" />
        </GA>
        <Deck>
            <Property Name="DeckId" Value="T14" />
            <Property Name="deck_type" Value="T" />
            <Property Name="deck_depth" Value="58" />
            <Property Name="deck_trug" Value="207" />
            <Property Name="deck_top" Value="106" />
            <Property Name="deck_bot" Value="62" />
            <Property Name="deck_stiff_height" Value="0" />
        </Deck>
        <Slab>
            <Property Name="fck" Value="25" />
            <Property Name="slab_depth" Value="130" />
            <Property Name="conc_type" Value="NW" />
            <Property Name="mesh_type" Value="A393" />
            <Property Name="mesh_area_max" Value="393" />
            <Property Name="mesh_area_min" Value="393" />
            <Property Name="mesh_axis" Value="40" />
            <Property Name="mesh_strength" Value="500" />
        </Slab>
        <Beams>
            <Property Name="uSecSize" Value="IPE_500" />
            <Property Name="fy5" Value="355" />
            <Property Name="ush_con" Value="80" />
            <Property Name="SideASecSize" Value="IPE_500" />
            <Property Name="fy1" Value="355" />
            <Property Name="SideAEdgeFlag" Value="0" />
            <Property Name="SideACompoFlag" Value="1" />
            <Property Name="SideAsh_con" Value="80" />
            <Property Name="SideBSecSize" Value="IPE_500" />
            <Property Name="fy2" Value="355" />
            <Property Name="SideBEdgeFlag" Value="1" />
            <Property Name="SideBCompoFlag" Value="0" />
            <Property Name="SideBsh_con" Value="80" />
            <Property Name="SideCSecSize" Value="IPE_500" />
            <Property Name="fy3" Value="355" />
            <Property Name="SideCEdgeFlag" Value="0" />
            <Property Name="SideCCompoFlag" Value="1" />
            <Property Name="SideCsh_con" Value="80" />
            <Property Name="SideDSecSize" Value="IPE_500" />
            <Property Name="fy4" Value="355" />
            <Property Name="SideDEdgeFlag" Value="1" />
            <Property Name="SideDCompoFlag" Value="0" />
            <Property Name="SideDsh_con" Value="80" />
        </Beams>
        <Loading>
            <Property Name="lead_var_act" Value="5" />
            <Property Name="othr_var_act" Value="0" />
            <Property Name="cold_perm" Value="1.2" />
            <Property Name="lead_var_fac" Value="0.5" />
            <Property Name="othr_var_fac" Value="0.3" />
            <Property Name="slab_weight" Value="2.47" />
        </Loading>
        <Fire>
            <Property Name="Method" Value="0" />
            <Property Name="time_limit" Value="60" />
            <Property Name="Lc" Value="27" />
            <Property Name="Bc" Value="18" />
            <Property Name="Hc" Value="3.6" />
            <Property Name="Hw" Value="1.8" />
            <Property Name="Lw" Value="30" />
            <Property Name="window_percent" Value="95" />
            <Property Name="qf" Value="511" />
            <Property Name="Bfac" Value="720" />
            <Property Name="combustion_factor" Value="0.8" />
            <Property Name="growth_rate" Value="1" />
        </Fire>
    </Input>
</Root>
"""

    def test_import_frc_success(self, client):
        resp = client.post(
            "/api/import-frc",
            files={"file": ("test.frc", self.MINIMAL_FRC, "text/xml")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["params"]["span1"] == 10.5
        assert data["params"]["span2"] == 8.0
        assert data["params"]["numbeam"] == 3
        assert data["params"]["method"] == "iso"
        assert data["project"]["ProjectName"] == "Test Project"
        assert data["project"]["JobNumber"] == "1234"

    def test_import_frc_returns_all_sections(self, client):
        resp = client.post(
            "/api/import-frc",
            files={"file": ("test.frc", self.MINIMAL_FRC, "text/xml")},
        )
        data = resp.json()
        params = data["params"]
        # Beam sections
        assert params["uSecSize"] == "IPE_500"
        assert params["SideASecSize"] == "IPE_500"
        assert params["SideBEdgeFlag"] == 1
        assert params["SideACompoFlag"] == 1
        # Loading
        assert params["lead_var_act"] == 5.0
        assert params["cold_perm"] == 1.2
        # Fire
        assert params["qf"] == 511.0
        assert params["Bfac"] == 720.0

    def test_import_frc_invalid_xml(self, client):
        resp = client.post(
            "/api/import-frc",
            files={"file": ("bad.frc", "not xml at all", "text/xml")},
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_import_frc_wrong_signature(self, client):
        bad_xml = self.MINIMAL_FRC.replace("FRACOFJobFile", "WrongSignature")
        resp = client.post(
            "/api/import-frc",
            files={"file": ("bad.frc", bad_xml, "text/xml")},
        )
        assert resp.status_code == 400
        assert "signature" in resp.json()["error"].lower()

class TestHealthz:
    def test_healthz_shape(self, client):
        """GET /healthz always returns the three keys the Tauri shell expects."""
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sidecar"] == "alive"
        assert isinstance(data["macs_installed"], bool)
        # macs_version is str when installed and version-parseable, else None
        assert data["macs_version"] is None or isinstance(data["macs_version"], str)

    def test_healthz_when_macs_missing(self, client, monkeypatch, tmp_path):
        """If Data.xml resolves to a missing path, macs_installed=False, version=None."""
        from macs_automation import app as app_module
        monkeypatch.setattr(
            app_module, "_find_macs_data_xml",
            lambda: tmp_path / "definitely-not-here" / "Data.xml",
        )
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["macs_installed"] is False
        assert data["macs_version"] is None

    def test_healthz_parses_version_from_folder(self, client, monkeypatch, tmp_path):
        """Folder named MACS+_304/EN/Data/Data.xml → macs_version='304'."""
        from macs_automation import app as app_module
        macs_dir = tmp_path / "MACS+_304" / "EN" / "Data"
        macs_dir.mkdir(parents=True)
        data_xml = macs_dir / "Data.xml"
        data_xml.write_text("<root/>")
        monkeypatch.setattr(app_module, "_find_macs_data_xml", lambda: data_xml)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["macs_installed"] is True
        assert data["macs_version"] == "304"


class TestRefDataAggregate:
    def test_ref_data_endpoint(self, client):
        """GET /api/ref-data returns sections, decks, meshes, defaults, and presets in one shot."""
        resp = client.get("/api/ref-data")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        assert "decks" in data
        assert "meshes" in data
        assert "defaults" in data
        assert "occupancy_presets" in data
        # Sections are grouped by family (same shape as /api/sections)
        assert "IPE" in data["sections"]


class TestSweepWithArbitraryParams:
    """Integration tests: sweep/LHS with non-hardcoded parameter sets."""

    def test_lhs_with_geometry_distributions(self, client):
        """LHS submission with non-fire distributions (span1, slab_depth)."""
        payload = {
            "sampling": "lhs",
            "analysis_method": "parametric",
            "n_samples": 5,
            "seed": 42,
            "distributions": {
                "span1": {"type": "lognormal", "mean": 9.0, "cov": 0.2},
                "slab_depth": {"type": "lognormal", "mean": 130, "cov": 0.15},
            },
            "fixed": {
                "span2": 9, "fck": 25, "numbeam": 2,
                "Lc": 27, "Bc": 18, "Hc": 3.6, "Hw": 1.8, "Lw": 30,
            },
        }
        combinations = []

        def capture_combinations(combos, sections_db, mode="sweep"):
            combinations.extend(combos)

        with patch("macs_automation.app._run_sweep_background", side_effect=capture_combinations):
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"] if "target" in args[1] else args[0][0]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200

        assert len(combinations) == 5
        # span1 should vary
        span1_values = [c["span1"] for c in combinations]
        assert len(set(span1_values)) > 1
        # slab_depth should vary
        sd_values = [c["slab_depth"] for c in combinations]
        assert len(set(sd_values)) > 1
        # Fixed values preserved
        assert all(c["span2"] == 9 for c in combinations)

    def test_sweep_with_fire_params(self, client):
        """Sweep submission with fire parameters (qf, window_percent)."""
        payload = {
            "analysis_method": "parametric",
            "sweep": {
                "qf": [300, 500, 700],
                "window_percent": [50, 80],
            },
            "fixed": {
                "span1": 9, "span2": 9, "fck": 25, "slab_depth": 130,
            },
        }
        combinations = []

        def capture_combinations(combos, sections_db, mode="sweep"):
            combinations.extend(combos)

        with patch("macs_automation.app._run_sweep_background", side_effect=capture_combinations):
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"] if "target" in args[1] else args[0][0]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200

        assert len(combinations) == 6  # 3 x 2
        qf_values = sorted(set(c["qf"] for c in combinations))
        assert qf_values == [300, 500, 700]

    def test_sweep_with_combustion_factor(self, client):
        """Sweep with combustion_factor."""
        payload = {
            "analysis_method": "parametric",
            "sweep": {"combustion_factor": [0.6, 0.8, 1.0]},
            "fixed": {"span1": 9, "span2": 9},
        }
        with patch("macs_automation.app._run_sweep_background"):
            resp = client.post("/api/sweeps", json=payload)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 3


class TestBatchResults:
    """Tests for batch-aware results page."""

    def test_sweep_submit_returns_batch_id(self, client):
        """POST /api/sweeps response includes a 32-char hex batch_id."""
        payload = {
            "analysis_method": "parametric",
            "sweep": {"qf": [300, 500]},
            "fixed": {"span1": 9, "span2": 9},
        }
        with patch("macs_automation.app._run_sweep_background"):
            with patch("threading.Thread") as mock_thread:
                def start_side_effect():
                    args = mock_thread.call_args
                    target = args[1]["target"] if "target" in args[1] else args[0][0]
                    target_args = args[1].get("args", ())
                    target(*target_args)
                mock_instance = MagicMock()
                mock_instance.start = start_side_effect
                mock_thread.return_value = mock_instance
                resp = client.post("/api/sweeps", json=payload)
                assert resp.status_code == 200
                data = resp.json()
                assert "batch_id" in data
                assert len(data["batch_id"]) == 32
                assert all(c in "0123456789abcdef" for c in data["batch_id"])

    def test_detect_varying_columns(self, client):
        """_detect_varying_columns correctly identifies varying vs fixed columns."""
        from macs_automation.app import _detect_varying_columns
        runs = [
            {"span1": 9.0, "span2": 9.0, "qf": 300, "window_percent": 50, "uf_max": 0.5},
            {"span1": 9.0, "span2": 9.0, "qf": 500, "window_percent": 50, "uf_max": 0.8},
            {"span1": 9.0, "span2": 9.0, "qf": 700, "window_percent": 80, "uf_max": 1.1},
        ]
        varying, fixed = _detect_varying_columns(runs)
        assert "qf" in varying
        assert "window_percent" in varying
        assert "span1" not in varying
        # Fixed params should include span1 (tuples are col, label, value)
        assert any(col == "span1" for col, label, value in fixed)

class TestCOMRetry:
    """Tests for COM retry logic in _run_single_com."""

    def test_succeeds_on_first_attempt(self):
        """No retries needed when COM succeeds immediately."""
        mock_outputs = {"uf_max": 0.5, "duration_ms": 100}
        params = {"method": "iso", "span1": 9.0}

        with patch("macs_automation.engine.run_one_com", return_value=mock_outputs) as mock_run:
            result = _run_single_com(params, {})
            assert result == mock_outputs
            assert mock_run.call_count == 1

    def test_retries_on_com_error_then_succeeds(self):
        """Retries after COM error and succeeds on second attempt."""
        from pywintypes import com_error
        mock_outputs = {"uf_max": 0.5, "duration_ms": 100}
        params = {"method": "iso"}

        with patch("macs_automation.engine.run_one_com") as mock_run, \
             patch("time.sleep"):
            mock_run.side_effect = [
                com_error(-2147023179, "The interface is unknown.", None, None),
                mock_outputs,
            ]
            result = _run_single_com(params, {})
            assert result == mock_outputs
            assert mock_run.call_count == 2

    def test_raises_after_max_retries(self):
        """Raises the COM error after exhausting all retries."""
        from pywintypes import com_error
        params = {"method": "iso"}

        with patch("macs_automation.engine.run_one_com") as mock_run, \
             patch("time.sleep"):
            mock_run.side_effect = com_error(
                -2147023179, "The interface is unknown.", None, None
            )
            with pytest.raises(com_error):
                _run_single_com(params, {})
            assert mock_run.call_count == 3  # COM_MAX_RETRIES

    def test_non_com_error_not_retried(self):
        """Non-COM exceptions propagate immediately without retry."""
        params = {"method": "iso"}

        with patch("macs_automation.engine.run_one_com") as mock_run:
            mock_run.side_effect = ValueError("bad param")
            with pytest.raises(ValueError, match="bad param"):
                _run_single_com(params, {})
            assert mock_run.call_count == 1  # no retry
