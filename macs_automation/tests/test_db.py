"""Tests for db.py — SQLite database layer."""

import sqlite3

import pytest

from macs_automation.db import ResultsDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_results.db"
    with ResultsDB(db_path) as database:
        yield database


class TestSchema:
    def test_creates_runs_table(self, db):
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
        )
        assert cursor.fetchone() is not None

    def test_creates_time_series_table(self, db):
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='time_series'"
        )
        assert cursor.fetchone() is not None

    def test_creates_index(self, db):
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_time_series_run_id'"
        )
        assert cursor.fetchone() is not None


class TestInsertRun:
    def test_insert_successful_run(self, db):
        params = {
            "span1": 9.0, "span2": 9.0, "numbeam": 2,
            "fck": 25, "slab_depth": 130,
            "uSecSize": "IPE_500", "method": "iso", "time_limit": 60,
        }
        outputs = {
            "comp_failure": 0, "mb1_reqd": 100.5, "mb2_reqd": 200.3,
            "factored_hot": 50.0,
            "uf_max": 0.85, "max_temperature": 900.0, "max_deflection": 120.0,
            "max_slab_cap": 500.0, "max_beam_cap": 300.0, "max_total_cap": 800.0,
            "side_a_load_ratio": 0.3, "side_a_critical_temp": 650.0,
            "side_b_load_ratio": 0.4, "side_b_critical_temp": 620.0,
            "side_c_load_ratio": 0.35, "side_c_critical_temp": 640.0,
            "side_d_load_ratio": 0.32, "side_d_critical_temp": 645.0,
            "duration_ms": 150.0,
            "time_series": [
                {
                    "time_step": 1, "time_min": 5.0, "fire_temp": 576.0,
                    "lofl_temp": 200.0, "mesh_temp": 100.0,
                    "slabtop_temp": 50.0, "slabbot_temp": 300.0,
                    "beam_hot_capacity": 250.0, "deflection": 10.0,
                    "slab_yield": 5.0, "enhancement": 1.2,
                    "slab_cap": 400.0, "total_plate_capacity": 700.0,
                    "utilization_factor": 0.7,
                },
                {
                    "time_step": 2, "time_min": 10.0, "fire_temp": 678.0,
                    "lofl_temp": 350.0, "mesh_temp": 200.0,
                    "slabtop_temp": 100.0, "slabbot_temp": 450.0,
                    "beam_hot_capacity": 200.0, "deflection": 25.0,
                    "slab_yield": 8.0, "enhancement": 1.5,
                    "slab_cap": 450.0, "total_plate_capacity": 650.0,
                    "utilization_factor": 0.85,
                },
            ],
        }
        run_id = db.insert_run(params, outputs=outputs)
        assert run_id == 1

        # Verify runs table
        row = db.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None

        # Verify time_series
        ts_count = db.conn.execute(
            "SELECT COUNT(*) FROM time_series WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        assert ts_count == 2

    def test_insert_failed_run(self, db):
        params = {
            "span1": 9.0, "span2": 9.0, "uSecSize": "IPE_500",
            "method": "iso", "time_limit": 60,
        }
        run_id = db.insert_run(params, error="COM error: engine crashed")
        assert run_id == 1

        row = db.conn.execute("SELECT error FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row[0] == "COM error: engine crashed"

    def test_multiple_runs(self, db):
        for i in range(5):
            db.insert_run(
                {"span1": float(i), "uSecSize": "IPE_500", "method": "iso", "time_limit": 60},
                outputs={"comp_failure": 0, "time_series": []},
            )
        assert db.get_run_count() == 5


class TestRunExists:
    def test_exists_after_insert(self, db):
        params = {
            "span1": 9.0, "span2": 9.0, "numbeam": 2,
            "slab_depth": 130, "fck": 25,
            "uSecSize": "IPE_500", "time_limit": 60, "method": "iso",
        }
        db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        assert db.run_exists(params) is True

    def test_not_exists(self, db):
        params = {
            "span1": 12.0, "span2": 12.0, "numbeam": 3,
            "slab_depth": 180, "fck": 40,
            "uSecSize": "IPE_300", "time_limit": 90, "method": "iso",
        }
        assert db.run_exists(params) is False

    def test_failed_run_not_counted(self, db):
        params = {
            "span1": 9.0, "span2": 9.0, "numbeam": 2,
            "slab_depth": 130, "fck": 25,
            "uSecSize": "IPE_500", "time_limit": 60, "method": "iso",
        }
        db.insert_run(params, error="some error")
        assert db.run_exists(params) is False


class TestLHSResume:
    def test_match_by_sample_index_and_seed(self, db):
        params = {
            "span1": 9.0, "uSecSize": "IPE_500", "method": "parametric",
            "time_limit": 60, "_sample_index": 5, "_seed": 42,
        }
        db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        assert db.run_exists(params) is True

    def test_different_index_not_found(self, db):
        params = {
            "span1": 9.0, "uSecSize": "IPE_500", "method": "parametric",
            "time_limit": 60, "_sample_index": 5, "_seed": 42,
        }
        db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        other = dict(params, _sample_index=6)
        assert db.run_exists(other) is False

    def test_different_seed_not_found(self, db):
        params = {
            "span1": 9.0, "uSecSize": "IPE_500", "method": "parametric",
            "time_limit": 60, "_sample_index": 5, "_seed": 42,
        }
        db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        other = dict(params, _seed=99)
        assert db.run_exists(other) is False

    def test_lhs_columns_stored(self, db):
        params = {
            "span1": 9.0, "uSecSize": "IPE_500", "method": "parametric",
            "time_limit": 60, "_sample_index": 7, "_seed": 42,
        }
        run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        row = db.conn.execute(
            "SELECT sample_index, seed FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row == (7, 42)

    def test_grid_run_no_lhs_columns(self, db):
        """Grid mode params (no _sample_index) should store NULL for LHS columns."""
        params = {
            "span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60,
        }
        run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        row = db.conn.execute(
            "SELECT sample_index, seed FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row == (None, None)


class TestCounts:
    def test_empty_db(self, db):
        assert db.get_run_count() == 0
        assert db.get_successful_run_count() == 0

    def test_mixed_runs(self, db):
        db.insert_run(
            {"uSecSize": "IPE_500", "method": "iso", "time_limit": 60},
            outputs={"comp_failure": 0, "time_series": []},
        )
        db.insert_run(
            {"uSecSize": "IPE_300", "method": "iso", "time_limit": 60},
            error="failed",
        )
        assert db.get_run_count() == 2
        assert db.get_successful_run_count() == 1
