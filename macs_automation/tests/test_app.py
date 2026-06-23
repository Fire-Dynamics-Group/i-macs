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


class TestStartupProbe:
    """A bad DB_PATH must fail at FastAPI lifespan startup — _get_db is lazy
    (per-request), so without a startup probe a path issue only surfaces on
    the first API call. Tauri's 30s /healthz wait would happily return 200
    while writes silently fail. The lifespan probe makes the sidecar crash
    deterministically so SidecarErrorScreen surfaces it instead."""

    def test_unwriteable_path_crashes_startup(self, tmp_path, monkeypatch):
        # Make the "parent dir" actually be a regular file, so sqlite3 can't
        # open or create anything under it.
        blocker = tmp_path / "blocker.txt"
        blocker.write_text("not a directory")
        bad_path = blocker / "results.db"

        import macs_automation.app as app_module
        monkeypatch.setattr(app_module, "DB_PATH", bad_path)

        with pytest.raises(Exception):
            with TestClient(app_module.app):
                # If startup succeeded, this is the bug we're testing against.
                pass

    def test_writeable_path_starts_cleanly(self, tmp_path, monkeypatch):
        good_path = tmp_path / "ok.db"
        import macs_automation.app as app_module
        monkeypatch.setattr(app_module, "DB_PATH", good_path)
        with TestClient(app_module.app) as client:
            resp = client.get("/healthz")
            assert resp.status_code == 200


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
        assert sent["method"] == "parametric"
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


class TestSweepRunCap:
    """The 30k server-side hard cap (Q5)."""

    @pytest.fixture(autouse=True)
    def reset_sweep_state(self):
        with _sweep_lock:
            _sweep_state["active"] = False
        yield
        with _sweep_lock:
            _sweep_state["active"] = False

    def test_rejects_over_cap(self, client):
        """POST /api/sweeps with > 30000 paired rows returns 400."""
        payload = {
            "analysis_method": "iso",
            "sweep": {"qf": list(range(30001))},
        }
        resp = client.post("/api/sweeps", json=payload)
        assert resp.status_code == 400
        msg = resp.json().get("error", "")
        assert "30000" in msg
        assert "30001" in msg

    def test_allows_at_cap(self, client):
        """POST /api/sweeps with exactly 30000 paired rows is accepted."""
        payload = {
            "analysis_method": "iso",
            "sweep": {"qf": list(range(30000))},
        }
        with patch("macs_automation.app._run_sweep_background"):
            resp = client.post("/api/sweeps", json=payload)
            assert resp.status_code == 200

    def test_rejects_unequal_paired_lengths(self, client):
        """POST /api/sweeps with unequal paired arrays returns 400."""
        payload = {
            "analysis_method": "parametric",
            "sweep": {
                "qf": [300, 500, 700],
                "window_percent": [50, 80],
            },
        }
        resp = client.post("/api/sweeps", json=payload)
        assert resp.status_code == 400
        msg = resp.json().get("error", "")
        assert "qf" in msg
        assert "window_percent" in msg


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
    @pytest.fixture(autouse=True)
    def _reset_detect_cache(self):
        from macs_automation import macs_detect as _md
        _md.reset_cache()
        yield
        _md.reset_cache()

    def test_healthz_shape(self, client):
        """GET /healthz always returns the keys the Tauri shell expects.

        Back-compat keys (rc.5): sidecar, macs_installed, macs_version.
        New keys (#23): data_xml, com, install_path, attempted_paths.
        """
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sidecar"] == "alive"
        assert isinstance(data["macs_installed"], bool)
        # macs_version is str when installed and version-parseable, else None
        assert data["macs_version"] is None or isinstance(data["macs_version"], str)
        # New fields
        assert isinstance(data["data_xml"], bool)
        assert isinstance(data["com"], bool)
        assert data["install_path"] is None or isinstance(data["install_path"], str)
        assert isinstance(data["attempted_paths"], list)

    def test_healthz_when_macs_missing(self, client, monkeypatch, tmp_path):
        """When detection returns no Data.xml, macs_installed/data_xml are False
        and macs_version is None."""
        from macs_automation import macs_detect as _md
        monkeypatch.setattr(
            _md, "_detect_uncached",
            lambda: _md.DetectResult(
                data_xml_path=None, install_path=None,
                version=None, com_registered=False,
                attempted_paths=["mock: nothing found"],
            ),
        )
        _md.reset_cache()
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["macs_installed"] is False
        assert data["data_xml"] is False
        assert data["macs_version"] is None
        assert data["install_path"] is None
        assert data["com"] is False
        assert "mock: nothing found" in data["attempted_paths"]

    def test_healthz_parses_version_from_folder(self, client, monkeypatch, tmp_path):
        """Folder named MACS+_304/EN/Data/Data.xml → macs_version='304'."""
        from macs_automation import macs_detect as _md
        macs_dir = tmp_path / "MACS+_304" / "EN" / "Data"
        macs_dir.mkdir(parents=True)
        data_xml = macs_dir / "Data.xml"
        data_xml.write_text("<root/>")
        install_root = tmp_path / "MACS+_304"
        monkeypatch.setattr(
            _md, "_detect_uncached",
            lambda: _md.DetectResult(
                data_xml_path=data_xml, install_path=install_root,
                version="304", com_registered=True,
                attempted_paths=["mock: hit"],
            ),
        )
        _md.reset_cache()
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["macs_installed"] is True
        assert data["macs_version"] == "304"
        assert data["data_xml"] is True
        assert data["com"] is True
        assert data["install_path"] == str(install_root)

    def test_healthz_com_missing_but_data_xml_present(self, client, monkeypatch, tmp_path):
        """Acceptance: Data.xml found but COM not registered surfaces as
        macs_installed=True, com=False — the UI banner relies on this split."""
        from macs_automation import macs_detect as _md
        macs_dir = tmp_path / "MACS+_304" / "EN" / "Data"
        macs_dir.mkdir(parents=True)
        data_xml = macs_dir / "Data.xml"
        data_xml.write_text("<root/>")
        monkeypatch.setattr(
            _md, "_detect_uncached",
            lambda: _md.DetectResult(
                data_xml_path=data_xml,
                install_path=tmp_path / "MACS+_304",
                version="304",
                com_registered=False,
                attempted_paths=[],
            ),
        )
        _md.reset_cache()
        data = client.get("/healthz").json()
        assert data["data_xml"] is True
        assert data["com"] is False


class TestInstallLocationEndpoint:
    @pytest.fixture(autouse=True)
    def _reset_detect_cache(self):
        from macs_automation import macs_detect as _md
        _md.reset_cache()
        yield
        _md.reset_cache()

    def _make_valid_install(self, tmp_path):
        install = tmp_path / "MyMacs"
        data_dir = install / "EN" / "Data"
        data_dir.mkdir(parents=True)
        (data_dir / "Data.xml").write_text("<root/>")
        return install

    def test_rejects_folder_without_data_xml(self, client, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        resp = client.post("/api/install-location", json={"folder": str(empty)})
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False
        assert body["validated_path"] is None
        assert body["error"]

    def test_rejects_unparseable_xml(self, client, tmp_path):
        install = tmp_path / "MyMacs"
        data_dir = install / "EN" / "Data"
        data_dir.mkdir(parents=True)
        (data_dir / "Data.xml").write_text("<not closed")
        resp = client.post("/api/install-location", json={"folder": str(install)})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    def test_accepts_and_persists_valid_folder(self, client, tmp_path):
        install = self._make_valid_install(tmp_path)
        resp = client.post("/api/install-location", json={"folder": str(install)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["validated_path"] == str(install / "EN" / "Data" / "Data.xml")

        # Persisted to settings.
        get_resp = client.get("/api/install-location")
        assert get_resp.status_code == 200
        assert get_resp.json()["macs_data_path"] == str(
            install / "EN" / "Data" / "Data.xml"
        )


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
        """Paired sweep with fire parameters (qf, window_percent) — row-aligned."""
        payload = {
            "analysis_method": "parametric",
            "sweep": {
                "qf": [300, 500, 700],
                "window_percent": [50, 80, 95],
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

        assert len(combinations) == 3  # paired zip
        assert [c["qf"] for c in combinations] == [300, 500, 700]
        assert [c["window_percent"] for c in combinations] == [50, 80, 95]

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

class TestRunsListBatchFilter:
    """Tests for the optional batch_id query parameter on GET /api/runs."""

    def _seed_two_batches(self, db_path):
        from macs_automation.db import ResultsDB
        db = ResultsDB(db_path)
        try:
            db.insert_batch("batch_alpha", mode="sweep", total_expected=2)
            db.insert_batch("batch_beta", mode="sweep", total_expected=1)
            outputs = {
                "comp_failure": 0, "mb1_reqd": 100.0, "mb2_reqd": 200.0,
                "factored_hot": 50.0, "uf_max": 0.5,
                "max_temperature": 900.0, "max_deflection": 120.0,
                "max_slab_cap": 500.0, "max_beam_cap": 300.0, "max_total_cap": 800.0,
                "side_a_load_ratio": 0.3, "side_a_critical_temp": 650.0,
                "side_b_load_ratio": 0.4, "side_b_critical_temp": 620.0,
                "side_c_load_ratio": 0.35, "side_c_critical_temp": 640.0,
                "side_d_load_ratio": 0.32, "side_d_critical_temp": 645.0,
                "duration_ms": 150.0,
                "time_series": [],
            }
            for i in range(2):
                params = {
                    "_batch_id": "batch_alpha",
                    "span1": 9.0 + i, "span2": 9.0,
                    "method": "iso", "fck": 25, "uSecSize": "IPE_500",
                }
                db.insert_run(params, outputs=outputs)
            db.insert_run(
                {
                    "_batch_id": "batch_beta",
                    "span1": 12.0, "span2": 9.0,
                    "method": "iso", "fck": 25, "uSecSize": "IPE_500",
                },
                outputs=outputs,
            )
        finally:
            db.close()

    def test_filter_returns_only_runs_in_that_batch(self, use_tmp_db):
        self._seed_two_batches(use_tmp_db)
        client = TestClient(app)
        resp = client.get("/api/runs", params={"batch_id": "batch_alpha"})
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert len(runs) == 2
        assert all(r["batch_id"] == "batch_alpha" for r in runs)

    def test_no_filter_returns_all_runs(self, use_tmp_db):
        self._seed_two_batches(use_tmp_db)
        client = TestClient(app)
        resp = client.get("/api/runs")
        runs = resp.json()["runs"]
        assert len(runs) == 3

    def test_filter_unknown_batch_returns_empty(self, use_tmp_db):
        self._seed_two_batches(use_tmp_db)
        client = TestClient(app)
        resp = client.get("/api/runs", params={"batch_id": "no-such-batch"})
        assert resp.status_code == 200
        assert resp.json()["runs"] == []


class TestSSEEvents:
    """Tests for the SSE event flow.

    The formatter is unit-tested directly; a route-level smoke check confirms
    /api/sweeps/events is wired with the right content-type. Full HTTP
    streaming is exercised end-to-end in the Playwright e2e suite — TestClient
    on Windows blocks on truly-streaming responses, so we don't try to drive
    an indefinite stream through it here.
    """

    @staticmethod
    def _parse_sse(raw_text: str):
        events: list[tuple] = []
        event_name = None
        data_parts: list[str] = []
        for raw in raw_text.split("\n"):
            line = raw.rstrip("\r")
            if line == "":
                if data_parts:
                    events.append((event_name, "\n".join(data_parts)))
                event_name = None
                data_parts = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_parts.append(line[5:].lstrip())
        return events

    @pytest.mark.asyncio
    async def test_format_sse_events_emits_run_completed_then_batch_done(self):
        """The formatter yields one SSE record per event, with the correct
        event-name line and JSON data, and returns after batch_done."""
        import asyncio
        import json
        from macs_automation.app import _format_sse_events
        from macs_automation.sse_broker import Broker

        broker = Broker()

        async def collect():
            chunks = []
            async for chunk in _format_sse_events(broker):
                chunks.append(chunk)
            return chunks

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)  # let subscribe register

        broker.publish({
            "type": "run_completed",
            "run": {"id": 1, "batch_id": "B1", "uf_max": 0.7, "error": None},
        })
        broker.publish({
            "type": "batch_done",
            "batch_id": "B1",
            "total": 1, "completed": 1, "errors": 0,
        })

        chunks = await asyncio.wait_for(task, timeout=1.0)
        events = self._parse_sse("".join(chunks))
        events = [(name, data) for name, data in events if data]

        assert len(events) == 2
        name0, data0 = events[0]
        name1, data1 = events[1]
        assert name0 == "run_completed"
        assert json.loads(data0)["run"]["id"] == 1
        assert name1 == "batch_done"
        assert json.loads(data1)["batch_id"] == "B1"

    @pytest.mark.asyncio
    async def test_format_sse_events_returns_after_batch_done(self):
        """A run_completed event published AFTER batch_done must not be
        emitted — the generator must have returned by then."""
        import asyncio
        from macs_automation.app import _format_sse_events
        from macs_automation.sse_broker import Broker

        broker = Broker()
        chunks: list[str] = []

        async def collect():
            async for chunk in _format_sse_events(broker):
                chunks.append(chunk)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0)

        broker.publish({"type": "batch_done", "batch_id": "B1"})
        await asyncio.wait_for(task, timeout=1.0)

        # Subsequent publish goes to no subscriber.
        broker.publish({"type": "run_completed", "run": {"id": 99}})
        await asyncio.sleep(0.01)

        joined = "".join(chunks)
        assert "batch_done" in joined
        assert '"id": 99' not in joined

    def test_events_route_is_registered_with_event_stream_content_type(self, client):
        """Smoke check: the route exists and advertises text/event-stream.

        Triggers batch_done from a thread so TestClient's buffered .get()
        completes promptly when the generator returns.
        """
        import threading
        import time as _t
        from macs_automation.app import sweep_broker

        def trigger():
            _t.sleep(0.05)
            sweep_broker.publish({"type": "batch_done", "batch_id": "X"})

        threading.Thread(target=trigger, daemon=True).start()
        response = client.get("/api/sweeps/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


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


# ─── Dashboard slice (issue #7) ──────────────────────────────────────────────


def _patch_thread_to_run_inline():
    """Return a context manager pair: (background patch, thread patch) so the
    sweep handler runs synchronously under TestClient (no real COM)."""
    return None  # documentation hook; helpers below use the pattern inline


class TestSweepHandlerWritesConfigJson:
    """The dashboard's *Rerun batch* button needs the full sweep spec back.

    POST /api/sweeps must persist the request body into batches.config_json
    so /api/batches can derive varying_params and slice 2 can hydrate.
    """

    def test_grid_sweep_writes_config_json(self, client, use_tmp_db):
        import json
        payload = {
            "analysis_method": "iso",
            "sweep": {"qf": [300, 500]},
            "fixed": {"span1": 9, "span2": 9},
        }
        with patch("macs_automation.app._run_sweep_background"):
            resp = client.post("/api/sweeps", json=payload)
            assert resp.status_code == 200
            batch_id = resp.json()["batch_id"]

        from macs_automation.db import ResultsDB
        with ResultsDB(use_tmp_db) as db:
            row = db.conn.execute(
                "SELECT config_json FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        assert row is not None
        stored = json.loads(row[0])
        # Round-trip preserves the sweep spec verbatim.
        assert stored["sweep"] == {"qf": [300, 500]}
        assert stored["fixed"] == {"span1": 9, "span2": 9}
        assert stored.get("analysis_method") == "iso"

    def test_lhs_sweep_writes_config_json(self, client, use_tmp_db):
        import json
        payload = {
            "sampling": "lhs",
            "analysis_method": "parametric",
            "n_samples": 3,
            "seed": 42,
            "distributions": {"qf": {"preset": "Office"}},
            "fixed": {"span1": 9, "span2": 9},
        }
        with patch("macs_automation.app._run_sweep_background"):
            resp = client.post("/api/sweeps", json=payload)
            assert resp.status_code == 200
            batch_id = resp.json()["batch_id"]

        from macs_automation.db import ResultsDB
        with ResultsDB(use_tmp_db) as db:
            row = db.conn.execute(
                "SELECT config_json FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
        stored = json.loads(row[0])
        assert stored["sampling"] == "lhs"
        assert "distributions" in stored


def _seed_batch(db_path, batch_id, *, mode="sweep", config_json=None,
                pass_count=0, fail_count=0, error_count=0,
                total_expected=None, started_at=None):
    """Seed a batch with its requested pass/fail/error breakdown."""
    import json
    from macs_automation.db import ResultsDB
    total = pass_count + fail_count + error_count
    if total_expected is None:
        total_expected = total
    db = ResultsDB(db_path)
    try:
        db.insert_batch(batch_id, mode=mode, total_expected=total_expected,
                        config_json=config_json)
        if started_at is not None:
            db.conn.execute(
                "UPDATE batches SET created_at = ? WHERE batch_id = ?",
                (started_at, batch_id),
            )
            db.conn.commit()
        base_params = {
            "_batch_id": batch_id,
            "span1": 9.0, "span2": 9.0, "method": "iso",
            "fck": 25, "uSecSize": "IPE_500", "time_limit": 60,
        }
        passing_outputs = {
            "comp_failure": 0, "uf_max": 0.5,
            "side_a_load_ratio": 0.3, "side_b_load_ratio": 0.4,
            "side_c_load_ratio": 0.35, "side_d_load_ratio": 0.32,
            "time_series": [],
        }
        failing_outputs = {
            "comp_failure": 0, "uf_max": 1.3,
            "side_a_load_ratio": 0.3, "side_b_load_ratio": 0.4,
            "side_c_load_ratio": 0.35, "side_d_load_ratio": 0.32,
            "time_series": [],
        }
        for _ in range(pass_count):
            db.insert_run(base_params, outputs=passing_outputs)
        for _ in range(fail_count):
            db.insert_run(base_params, outputs=failing_outputs)
        for _ in range(error_count):
            db.insert_run(base_params, error="COM error")
    finally:
        db.close()


class TestBatchesListEndpoint:
    """GET /api/batches — paginated, server-aggregated, newest first."""

    def test_empty_db(self, client):
        resp = client.get("/api/batches")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"batches": [], "total": 0}

    def test_response_shape_includes_aggregations_and_varying(self, use_tmp_db):
        import json
        spec = {
            "analysis_method": "iso",
            "sweep": {"qf": [400, 500]},
            "fixed": {"span1": 9},
        }
        _seed_batch(use_tmp_db, "b1", config_json=json.dumps(spec),
                    pass_count=1, fail_count=1, error_count=0,
                    total_expected=2)
        client = TestClient(app)
        resp = client.get("/api/batches")
        data = resp.json()
        assert data["total"] == 1
        batch = data["batches"][0]
        assert batch["batch_id"] == "b1"
        assert batch["mode"] == "sweep"
        assert batch["total_expected"] == 2
        assert batch["run_count"] == 2
        assert batch["pass_count"] == 1
        assert batch["fail_count"] == 1
        assert batch["error_count"] == 0
        # Derived from config_json — the single source of truth.
        assert batch["varying_params"] == {"qf": [400, 500]}
        assert batch["fixed_params"] == {"span1": 9}

    def test_newest_first(self, use_tmp_db):
        _seed_batch(use_tmp_db, "old", started_at="2026-01-01T00:00:00+00:00",
                    pass_count=1)
        _seed_batch(use_tmp_db, "new", started_at="2026-03-01T00:00:00+00:00",
                    pass_count=1)
        client = TestClient(app)
        resp = client.get("/api/batches")
        ids = [b["batch_id"] for b in resp.json()["batches"]]
        assert ids == ["new", "old"]

    def test_pagination_limit_and_offset(self, use_tmp_db):
        for i in range(5):
            _seed_batch(
                use_tmp_db, f"b{i}",
                started_at=f"2026-0{i+1}-01T00:00:00+00:00",
                pass_count=1,
            )
        client = TestClient(app)
        resp = client.get("/api/batches", params={"limit": 2, "offset": 1})
        data = resp.json()
        assert data["total"] == 5  # total reflects all rows, not page
        assert len(data["batches"]) == 2
        # Skipped the newest; second + third newest expected.
        assert data["batches"][0]["batch_id"] == "b3"
        assert data["batches"][1]["batch_id"] == "b2"

    def test_null_config_json_tolerated(self, use_tmp_db):
        _seed_batch(use_tmp_db, "legacy", config_json=None, pass_count=1)
        client = TestClient(app)
        resp = client.get("/api/batches")
        batch = resp.json()["batches"][0]
        # Legacy batches show as fully-fixed-but-empty; Rerun button is
        # disabled client-side when both are empty.
        assert batch["varying_params"] == {}
        assert batch["fixed_params"] == {}

    def test_pass_count_respects_beam_check(self, use_tmp_db):
        """pass_count uses the shared _pass_where (not just uf_max)."""
        import json
        from macs_automation.db import ResultsDB
        spec = {"sweep": {"qf": [400]}, "fixed": {}}
        db = ResultsDB(use_tmp_db)
        try:
            db.insert_batch("b1", mode="sweep", total_expected=1,
                            config_json=json.dumps(spec))
            # uf_max OK but side B load ratio > 1.0 → must count as fail.
            db.insert_run(
                {"_batch_id": "b1", "span1": 9.0, "method": "iso",
                 "uSecSize": "IPE_500", "time_limit": 60},
                outputs={"comp_failure": 0, "uf_max": 0.5,
                         "side_b_load_ratio": 1.3, "time_series": []},
            )
        finally:
            db.close()
        client = TestClient(app)
        batch = client.get("/api/batches").json()["batches"][0]
        assert batch["pass_count"] == 0
        assert batch["fail_count"] == 1


class TestUngroupedRunsEndpoint:
    """GET /api/runs/ungrouped — paginated rows with batch_id IS NULL."""

    def test_empty_db(self, client):
        resp = client.get("/api/runs/ungrouped")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"runs": [], "total": 0}

    def test_excludes_batched_runs(self, use_tmp_db):
        _seed_batch(use_tmp_db, "b1", pass_count=2)
        # Ungrouped (no batch_id) run
        from macs_automation.db import ResultsDB
        with ResultsDB(use_tmp_db) as db:
            db.insert_run(
                {"span1": 11.0, "method": "iso", "uSecSize": "IPE_500",
                 "time_limit": 60},
                outputs={"comp_failure": 0, "uf_max": 0.6, "time_series": []},
            )
        client = TestClient(app)
        resp = client.get("/api/runs/ungrouped")
        data = resp.json()
        assert data["total"] == 1
        assert len(data["runs"]) == 1
        assert data["runs"][0]["batch_id"] is None
        assert data["runs"][0]["span1"] == 11.0

    def test_newest_first(self, use_tmp_db):
        from macs_automation.db import ResultsDB
        with ResultsDB(use_tmp_db) as db:
            for s in [1.0, 2.0, 3.0]:
                db.insert_run(
                    {"span1": s, "method": "iso", "uSecSize": "IPE_500",
                     "time_limit": 60},
                    outputs={"comp_failure": 0, "uf_max": 0.5, "time_series": []},
                )
        client = TestClient(app)
        resp = client.get("/api/runs/ungrouped")
        spans = [r["span1"] for r in resp.json()["runs"]]
        assert spans == [3.0, 2.0, 1.0]

    def test_pagination(self, use_tmp_db):
        from macs_automation.db import ResultsDB
        with ResultsDB(use_tmp_db) as db:
            for i in range(5):
                db.insert_run(
                    {"span1": float(i), "method": "iso", "uSecSize": "IPE_500",
                     "time_limit": 60},
                    outputs={"comp_failure": 0, "uf_max": 0.5, "time_series": []},
                )
        client = TestClient(app)
        resp = client.get("/api/runs/ungrouped", params={"limit": 2, "offset": 1})
        data = resp.json()
        assert data["total"] == 5
        assert len(data["runs"]) == 2

    def test_runs_carry_overall_pass(self, use_tmp_db):
        """Status is attached so the table can color rows without re-fetching."""
        from macs_automation.db import ResultsDB
        with ResultsDB(use_tmp_db) as db:
            db.insert_run(
                {"span1": 9.0, "method": "iso", "uSecSize": "IPE_500",
                 "time_limit": 60},
                outputs={"comp_failure": 0, "uf_max": 0.5, "time_series": []},
            )
        client = TestClient(app)
        run = client.get("/api/runs/ungrouped").json()["runs"][0]
        assert "overall_pass" in run
        assert run["overall_pass"] is True


class TestBatchByIdEndpoint:
    """GET /api/batches/{batch_id} — single-batch summary for the
    analytical view to know when to switch from live progress."""

    def test_returns_summary_with_aggregations(self, use_tmp_db):
        import json
        _seed_batch(
            use_tmp_db, "b1",
            config_json=json.dumps({"sweep": {"qf": [400, 500]}, "fixed": {"span1": 9}}),
            pass_count=2, fail_count=0, total_expected=2,
        )
        client = TestClient(app)
        resp = client.get("/api/batches/b1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_id"] == "b1"
        assert data["run_count"] == 2
        assert data["total_expected"] == 2
        assert data["varying_params"] == {"qf": [400, 500]}
        assert data["fixed_params"] == {"span1": 9}

    def test_unknown_batch_returns_404(self, client):
        resp = client.get("/api/batches/nope")
        assert resp.status_code == 404


class TestStatsEndpoint:
    """GET /api/stats — global counts."""

    def test_empty_db(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.json() == {
            "total": 0, "successful": 0, "errors": 0,
            "pass_count": 0, "fail_count": 0,
        }

    def test_mixed_runs(self, use_tmp_db):
        from macs_automation.db import ResultsDB
        with ResultsDB(use_tmp_db) as db:
            db.insert_run(
                {"span1": 9.0, "method": "iso", "uSecSize": "IPE_500",
                 "time_limit": 60},
                outputs={"comp_failure": 0, "uf_max": 0.5, "time_series": []},
            )
            db.insert_run(
                {"span1": 10.0, "method": "iso", "uSecSize": "IPE_500",
                 "time_limit": 60},
                outputs={"comp_failure": 0, "uf_max": 1.3, "time_series": []},
            )
            db.insert_run(
                {"span1": 11.0, "method": "iso", "uSecSize": "IPE_500",
                 "time_limit": 60},
                error="broke",
            )
        client = TestClient(app)
        stats = client.get("/api/stats").json()
        assert stats == {
            "total": 3, "successful": 2, "errors": 1,
            "pass_count": 1, "fail_count": 1,
        }


class TestComRunnerDispatch:
    """The frozen sidecar exe is the only entry point in production builds.
    engine.run_one_com() spawns it with `--com-runner`; app.main() must see
    that sentinel and dispatch to com_runner.main() before argparse runs."""

    def test_main_dispatches_com_runner_flag(self):
        """app.main(['--com-runner']) calls com_runner.main() and does NOT
        start uvicorn or hit argparse."""
        from macs_automation import app as app_module

        with patch("macs_automation.com_runner.main") as mock_runner_main, \
             patch("uvicorn.run") as mock_uvicorn_run:
            app_module.main(["--com-runner"])

        mock_runner_main.assert_called_once()
        mock_uvicorn_run.assert_not_called()

    def test_main_without_com_runner_flag_starts_uvicorn(self):
        """Normal CLI args still route to uvicorn — the dispatcher must not
        swallow regular startup."""
        from macs_automation import app as app_module

        with patch("macs_automation.com_runner.main") as mock_runner_main, \
             patch("uvicorn.run") as mock_uvicorn_run:
            app_module.main(["--port", "8123"])

        mock_runner_main.assert_not_called()
        mock_uvicorn_run.assert_called_once()

    def test_com_runner_dispatch_via_real_subprocess(self):
        """End-to-end: spawn `python -m macs_automation.app --com-runner` as a
        real subprocess and verify it round-trips a JSON stdin → JSON stdout
        without hitting argparse. This is the regression test for the prod
        bug where the PyInstaller-frozen sidecar errored with
        `unrecognized arguments: -m macs_automation.com_runner`. Mocks can't
        catch that — only an actual subprocess can.

        We send an empty `{}` so com_runner raises KeyError on data['params'],
        which it catches and serialises to {"error": "KeyError: ..."} — no
        COM dependency, but proves the full wiring."""
        import json
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, "-m", "macs_automation.app", "--com-runner"],
            input="{}\n",
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert proc.returncode == 0, (
            f"dispatcher exited {proc.returncode}; stderr={proc.stderr!r}"
        )
        out_line = proc.stdout.strip()
        assert out_line, f"no stdout from dispatcher; stderr={proc.stderr!r}"
        result = json.loads(out_line)
        assert "error" in result
        assert "KeyError" in result["error"]


def _beam_params(batch_id, ush_con=80.0):
    """Minimal params for a run with all beams internal+composite at a given
    unprotected shear connection. span1=9 -> EN minimum ~52%."""
    p = {
        "_batch_id": batch_id,
        "span1": 9.0, "span2": 8.5,
        "uSecSize": "IPE_500", "fy5": 355, "ush_con": ush_con,
        "method": "iso", "time_limit": 60, "fck": 25, "slab_depth": 130,
    }
    for side, fy in (("A", "fy1"), ("B", "fy2"), ("C", "fy3"), ("D", "fy4")):
        p[f"Side{side}SecSize"] = "IPE_500"
        p[fy] = 355
        p[f"Side{side}EdgeFlag"] = 0
        p[f"Side{side}CompoFlag"] = 1
        p[f"Side{side}sh_con"] = 80.0
    return p


def _beam_outputs(uf_max=0.5):
    return {
        "comp_failure": 0, "mb1_reqd": 100.0, "mb2_reqd": 200.0,
        "factored_hot": 50.0, "uf_max": uf_max,
        "max_temperature": 900.0, "max_deflection": 120.0,
        "max_slab_cap": 500.0, "max_beam_cap": 300.0, "max_total_cap": 800.0,
        "side_a_load_ratio": 0.3, "side_a_critical_temp": 650.0,
        "side_b_load_ratio": 0.4, "side_b_critical_temp": 620.0,
        "side_c_load_ratio": 0.35, "side_c_critical_temp": 640.0,
        "side_d_load_ratio": 0.32, "side_d_critical_temp": 645.0,
        "duration_ms": 150.0, "time_series": [],
    }


class TestShearCheckEndpoint:
    def test_flags_sublimit_run(self, client, use_tmp_db):
        from macs_automation.db import ResultsDB
        db = ResultsDB(use_tmp_db)
        db.insert_run(_beam_params("b1", ush_con=80.0), outputs=_beam_outputs())
        db.insert_run(_beam_params("b1", ush_con=30.0), outputs=_beam_outputs())
        db.close()

        resp = client.get("/api/batches/b1/shear-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_id"] == "b1"
        assert data["checked"] == 2
        assert len(data["sub_limit_runs"]) == 1
        flag = data["sub_limit_runs"][0]["flags"][0]
        assert flag["beam"] == "Unprotected"
        assert flag["sh_con"] == 30.0
        assert flag["eta_min_pct"] == pytest.approx(52.0)

    def test_clean_batch_returns_empty(self, client, use_tmp_db):
        from macs_automation.db import ResultsDB
        db = ResultsDB(use_tmp_db)
        db.insert_run(_beam_params("b2", ush_con=80.0), outputs=_beam_outputs())
        db.close()

        resp = client.get("/api/batches/b2/shear-check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["checked"] == 1
        assert data["sub_limit_runs"] == []

    def test_unknown_batch_is_empty_not_error(self, client, use_tmp_db):
        resp = client.get("/api/batches/nope/shear-check")
        assert resp.status_code == 200
        assert resp.json()["sub_limit_runs"] == []


class TestRunDetailProvenance:
    """The run-detail endpoint surfaces the engine version and per-run
    shear-connection flags so the UI can show them on the run page."""

    def test_run_detail_includes_engine_version(self, client, use_tmp_db):
        from macs_automation.db import ResultsDB
        db = ResultsDB(use_tmp_db)
        outs = _beam_outputs()
        outs["engine_version"] = "2.0.0.2"
        run_id = db.insert_run(_beam_params("b1", ush_con=80.0), outputs=outs)
        db.close()

        data = client.get(f"/api/runs/{run_id}").json()
        assert data["engine_version"] == "2.0.0.2"

    def test_run_detail_flags_sublimit_shear(self, client, use_tmp_db):
        from macs_automation.db import ResultsDB
        db = ResultsDB(use_tmp_db)
        run_id = db.insert_run(_beam_params("b1", ush_con=30.0), outputs=_beam_outputs())
        db.close()

        data = client.get(f"/api/runs/{run_id}").json()
        assert data["shear_flags"], "expected a shear-connection flag"
        assert data["shear_flags"][0]["beam"] == "Unprotected"
        assert data["shear_flags"][0]["sh_con"] == 30.0

    def test_run_detail_no_shear_flags_when_adequate(self, client, use_tmp_db):
        from macs_automation.db import ResultsDB
        db = ResultsDB(use_tmp_db)
        run_id = db.insert_run(_beam_params("b1", ush_con=90.0), outputs=_beam_outputs())
        db.close()

        data = client.get(f"/api/runs/{run_id}").json()
        assert data["shear_flags"] == []
