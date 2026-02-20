"""End-to-end tests for LHS sweep → results page flow.

Tests the full pipeline: submit LHS config → batch created → runs inserted
→ results page renders batch groups with fixed/varying column detection.

Run with: python -m pytest macs_automation/tests/test_e2e_lhs.py -v
"""

import sqlite3
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from macs_automation.app import app, _DISPLAY_COLUMNS, _detect_varying_columns
from macs_automation.db import ResultsDB
from macs_automation.tests.conftest import _make_time_series


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_ref_data():
    """Provide fake reference data so tests don't need Data.xml."""
    import macs_automation.app as app_module
    app_module._ref_data = {
        "sections": {
            "IPE_500": {"family": "IPE", "name": "IPE 500", "h": 500, "b": 200, "tw": 10.2, "tf": 16},
        },
        "decks": {
            "T14": {"deck_type": "T", "deck_depth": 58, "deck_trug": 207,
                    "deck_top": 106, "deck_bot": 62, "deck_stiff_height": 0,
                    "name": "COFRAPLUS 60"},
        },
        "meshes": {
            "ST15C": {"mainArea": 142, "transArea": 142, "min_mesh_dia": 6,
                      "max_mesh_dia": 6, "name": "ST15C"},
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


LHS_PAYLOAD = {
    "sampling": "lhs",
    "analysis_method": "parametric",
    "n_samples": 5,
    "seed": 42,
    "distributions": {
        "qf": {"preset": "Office"},
        "window_percent": {"preset": "Opening Factor", "transform": "opening_factor"},
    },
    "fixed": {
        "span1": 9, "span2": 9, "numbeam": 2,
        "slab_depth": 130, "fck": 25,
        "Lc": 27, "Bc": 18, "Hc": 3.6, "Hw": 1.8, "Lw": 30,
        "combustion_factor": 0.8,
    },
}


def _mock_com_outputs(uf_max=0.65):
    """Build a mock engine output dict with time series."""
    ts = _make_time_series(n_steps=6, uf_peak=uf_max)
    return {
        "comp_failure": 0,
        "mb1_reqd": 100.0, "mb2_reqd": 200.0,
        "factored_hot": 3.7,
        "uf_max": uf_max,
        "max_temperature": 900.0, "max_deflection": 120.0,
        "max_slab_cap": 500.0, "max_beam_cap": 300.0, "max_total_cap": 800.0,
        "side_a_load_ratio": 0.3, "side_a_critical_temp": 620.0,
        "side_b_load_ratio": 0.4, "side_b_critical_temp": 756.0,
        "side_c_load_ratio": 0.35, "side_c_critical_temp": 620.0,
        "side_d_load_ratio": 0.32, "side_d_critical_temp": 623.0,
        "duration_ms": 1200.0,
        "time_series": ts,
    }


def _run_lhs_sweep_synchronously(client, payload=None):
    """Submit LHS config, run background thread synchronously with mocked COM.

    Returns (response, batch_id, db_path).
    """
    if payload is None:
        payload = LHS_PAYLOAD

    # UF values for each sample: 4 pass, 1 fail
    uf_values = [0.45, 0.62, 0.78, 0.91, 1.15]
    call_count = [0]

    def mock_com(params, sections_db):
        idx = call_count[0]
        call_count[0] += 1
        uf = uf_values[idx] if idx < len(uf_values) else 0.5
        return _mock_com_outputs(uf_max=uf)

    with patch("macs_automation.app._run_single_com", side_effect=mock_com):
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

    return resp


# ─── E2E: LHS Submit → Batch Created ─────────────────────────────────────────

class TestLHSSubmission:
    """POST /api/sweeps with LHS config creates a batch."""

    def test_returns_batch_id(self, client):
        resp = _run_lhs_sweep_synchronously(client)
        assert resp.status_code == 200
        data = resp.json()
        assert "batch_id" in data
        assert len(data["batch_id"]) == 32

    def test_correct_sample_count(self, client):
        resp = _run_lhs_sweep_synchronously(client)
        data = resp.json()
        assert data["total"] == 5

    def test_batch_recorded_in_db(self, client, use_tmp_db):
        resp = _run_lhs_sweep_synchronously(client)
        batch_id = resp.json()["batch_id"]

        db = ResultsDB(use_tmp_db)
        batches = db.get_batches()
        db.close()

        assert len(batches) == 1
        assert batches[0]["batch_id"] == batch_id
        assert batches[0]["mode"] == "lhs"
        assert batches[0]["total_expected"] == 5

    def test_runs_have_batch_id(self, client, use_tmp_db):
        resp = _run_lhs_sweep_synchronously(client)
        batch_id = resp.json()["batch_id"]

        db = ResultsDB(use_tmp_db)
        runs = db.get_batch_runs(batch_id)
        db.close()

        assert len(runs) == 5
        assert all(r["batch_id"] == batch_id for r in runs)

    def test_runs_have_varying_qf_and_wp(self, client, use_tmp_db):
        resp = _run_lhs_sweep_synchronously(client)
        batch_id = resp.json()["batch_id"]

        db = ResultsDB(use_tmp_db)
        runs = db.get_batch_runs(batch_id)
        db.close()

        qf_values = {r["qf"] for r in runs}
        wp_values = {r["window_percent"] for r in runs}
        assert len(qf_values) > 1, "LHS should produce varying qf values"
        assert len(wp_values) > 1, "LHS should produce varying window_percent values"

    def test_fixed_params_constant(self, client, use_tmp_db):
        resp = _run_lhs_sweep_synchronously(client)
        batch_id = resp.json()["batch_id"]

        db = ResultsDB(use_tmp_db)
        runs = db.get_batch_runs(batch_id)
        db.close()

        assert all(r["span1"] == 9.0 for r in runs)
        assert all(r["span2"] == 9.0 for r in runs)
        assert all(r["slab_depth"] == 130.0 for r in runs)


# ─── E2E: Results Page Renders Batch Groups ───────────────────────────────────

class TestResultsPageBatchRendering:
    """GET /results after LHS sweep shows batch group layout."""

    def test_results_page_loads(self, client):
        _run_lhs_sweep_synchronously(client)
        resp = client.get("/results")
        assert resp.status_code == 200

    def test_shows_batch_group_header(self, client):
        resp = _run_lhs_sweep_synchronously(client)
        batch_id = resp.json()["batch_id"]
        html = client.get("/results").text
        assert batch_id[:8] in html
        assert "LHS" in html

    def test_shows_fixed_parameters_card(self, client):
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        assert "Fixed Parameters" in html
        assert "Span 1 (m)" in html
        assert "Span 2 (m)" in html

    def test_shows_varying_column_headers(self, client):
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        # qf and window_percent should be table headers
        assert "Fire Load" in html
        assert "Window %" in html

    def test_shows_run_count(self, client):
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        assert "5 runs" in html

    def test_shows_pass_fail_counts(self, client):
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        assert "4 pass" in html  # 4 runs with UF <= 1.0
        # 1 fail (UF = 1.15)
        assert "1 fail" in html or "Fail" in html

    def test_shows_uf_values(self, client):
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        assert "0.450" in html  # first run UF
        assert "1.150" in html  # last run UF (fail)

    def test_no_individual_runs_section(self, client):
        """When all runs are batched, no 'Individual Runs' section."""
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        assert "Individual Runs" not in html

    def test_no_runs_found_message_absent(self, client):
        """After a sweep, 'No runs found' should NOT appear."""
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        assert "No runs found" not in html

    def test_clickable_rows_have_detail_links(self, client):
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        assert 'data-href="/results/' in html

    def test_stats_cards_reflect_runs(self, client):
        _run_lhs_sweep_synchronously(client)
        html = client.get("/results").text
        # Should show total, pass, fail, errors
        assert ">5<" in html  # 5 total runs in a <strong> tag


# ─── E2E: Mixed Batch + Individual Runs ──────────────────────────────────────

class TestMixedBatchAndIndividual:
    """Results page with both batched and unbatched runs."""

    def test_individual_run_appears_separately(self, client, use_tmp_db):
        """A single run (no batch) shows under 'Individual Runs'."""
        # First run a sweep
        _run_lhs_sweep_synchronously(client)

        # Then insert a single run without batch_id
        db = ResultsDB(use_tmp_db)
        db.insert_run(
            {"span1": 12.0, "span2": 12.0, "uSecSize": "IPE_500",
             "method": "iso", "time_limit": 90},
            outputs={"comp_failure": 0, "uf_max": 0.42, "time_series": []},
        )
        db.close()

        html = client.get("/results").text
        assert "Individual Runs" in html
        # Both sections should be present
        assert "Fixed Parameters" in html  # batch section
        assert "0.420" in html  # individual run UF


# ─── Schema migration regression ─────────────────────────────────────────────

class TestSchemaMigration:
    """Verify DB schema migration works on databases created before batch support."""

    def test_open_existing_db_without_batch_id(self, tmp_path):
        """Opening a pre-batch DB adds batch_id column and batches table."""
        db_path = tmp_path / "legacy.db"

        # Create a DB with the OLD schema (no batch_id, no batches table)
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                span1 REAL, span2 REAL, numbeam INTEGER,
                u_sec_size TEXT, method TEXT, time_limit INTEGER,
                qf REAL, window_percent REAL,
                uf_max REAL, error TEXT, duration_ms REAL,
                sample_index INTEGER, seed INTEGER
            );
            CREATE TABLE time_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES runs(id),
                time_step INTEGER, time_min REAL,
                fire_temp REAL, lofl_temp REAL, mesh_temp REAL,
                slabtop_temp REAL, slabbot_temp REAL,
                beam_hot_capacity REAL, deflection REAL,
                slab_yield REAL, enhancement REAL,
                slab_cap REAL, total_plate_capacity REAL,
                utilization_factor REAL
            );
        """)
        # Insert a legacy run
        conn.execute(
            "INSERT INTO runs (span1, span2, u_sec_size, method, time_limit, uf_max) "
            "VALUES (9.0, 9.0, 'IPE_500', 'iso', 60, 0.75)"
        )
        conn.commit()
        conn.close()

        # Open with new code — migration should succeed
        db = ResultsDB(db_path)

        # Verify batch_id column was added
        cursor = db.conn.execute("PRAGMA table_info(runs)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "batch_id" in cols

        # Verify batches table was created
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='batches'"
        )
        assert cursor.fetchone() is not None

        # Legacy run should be ungrouped
        ungrouped = db.get_ungrouped_runs()
        assert len(ungrouped) == 1
        assert ungrouped[0]["uf_max"] == 0.75

        # No batches
        assert db.get_batches() == []

        db.close()

    def test_migration_preserves_existing_data(self, tmp_path):
        """Migration doesn't corrupt existing runs."""
        db_path = tmp_path / "legacy2.db"

        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT, span1 REAL, span2 REAL, numbeam INTEGER,
                steel_deck INTEGER, deck_name TEXT, deck_type TEXT,
                deck_depth REAL, deck_trug REAL, deck_top REAL, deck_bot REAL,
                deck_stiff_height REAL,
                conc_type TEXT, conc_lambda REAL, fck REAL, slab_depth REAL,
                mesh_type TEXT, mesh_area_max REAL, mesh_area_min REAL,
                mesh_axis REAL, mesh_strength REAL,
                u_sec_size TEXT, u_sec_fy INTEGER, ush_con REAL,
                side_a_sec TEXT, side_a_fy INTEGER, side_a_edge INTEGER,
                side_a_composite INTEGER, side_a_sh_con REAL,
                side_b_sec TEXT, side_b_fy INTEGER, side_b_edge INTEGER,
                side_b_composite INTEGER, side_b_sh_con REAL,
                side_c_sec TEXT, side_c_fy INTEGER, side_c_edge INTEGER,
                side_c_composite INTEGER, side_c_sh_con REAL,
                side_d_sec TEXT, side_d_fy INTEGER, side_d_edge INTEGER,
                side_d_composite INTEGER, side_d_sh_con REAL,
                lead_var_act REAL, othr_var_act REAL, cold_perm REAL,
                slab_weight REAL, lead_var_fac REAL, othr_var_fac REAL,
                method TEXT, time_limit INTEGER,
                Lc REAL, Bc REAL, Hc REAL, Hw REAL, Lw REAL,
                window_percent REAL, qf REAL, Bfac REAL,
                combustion_factor REAL, growth_rate REAL,
                comp_failure INTEGER,
                mb1_reqd REAL, mb2_reqd REAL, factored_hot REAL,
                uf_max REAL, max_temperature REAL, max_deflection REAL,
                max_slab_cap REAL, max_beam_cap REAL, max_total_cap REAL,
                side_a_load_ratio REAL, side_a_critical_temp REAL,
                side_b_load_ratio REAL, side_b_critical_temp REAL,
                side_c_load_ratio REAL, side_c_critical_temp REAL,
                side_d_load_ratio REAL, side_d_critical_temp REAL,
                sample_index INTEGER, seed INTEGER,
                error TEXT, duration_ms REAL
            );
            CREATE TABLE time_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER REFERENCES runs(id),
                time_step INTEGER, time_min REAL,
                fire_temp REAL, lofl_temp REAL, mesh_temp REAL,
                slabtop_temp REAL, slabbot_temp REAL,
                beam_hot_capacity REAL, deflection REAL,
                slab_yield REAL, enhancement REAL,
                slab_cap REAL, total_plate_capacity REAL,
                utilization_factor REAL
            );
            CREATE INDEX idx_time_series_run_id ON time_series(run_id);
        """)
        for i in range(5):
            conn.execute(
                "INSERT INTO runs (span1, uf_max) VALUES (?, ?)",
                (9.0 + i, 0.5 + i * 0.1),
            )
        conn.commit()
        conn.close()

        # Open with new code
        db = ResultsDB(db_path)
        assert db.get_run_count() == 5
        ungrouped = db.get_ungrouped_runs()
        assert len(ungrouped) == 5
        db.close()
