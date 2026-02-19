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


def _insert_sample_run(db, span1=9.0, span2=9.0, fck=25, slab_depth=130,
                        sec_size="IPE_500", time_limit=60, uf_max=0.85,
                        error=None, with_ts=True):
    """Helper to insert a run with standard params and optional time series."""
    params = {
        "span1": span1, "span2": span2, "numbeam": 2,
        "fck": fck, "slab_depth": slab_depth,
        "uSecSize": sec_size, "method": "iso", "time_limit": time_limit,
    }
    outputs = None
    if not error:
        outputs = {
            "comp_failure": 0, "mb1_reqd": 100.5, "mb2_reqd": 200.3,
            "factored_hot": 50.0,
            "uf_max": uf_max, "max_temperature": 900.0, "max_deflection": 120.0,
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
            ] if with_ts else [],
        }
    return db.insert_run(params, outputs=outputs, error=error)


class TestGetRuns:
    def test_returns_list_of_dicts(self, db):
        _insert_sample_run(db)
        runs = db.get_runs()
        assert isinstance(runs, list)
        assert len(runs) == 1
        assert isinstance(runs[0], dict)

    def test_returns_key_fields(self, db):
        _insert_sample_run(db)
        run = db.get_runs()[0]
        assert run["span1"] == 9.0
        assert run["uf_max"] == 0.85
        assert "id" in run

    def test_pagination_limit(self, db):
        for i in range(5):
            _insert_sample_run(db, span1=float(i))
        runs = db.get_runs(limit=3)
        assert len(runs) == 3

    def test_pagination_offset(self, db):
        for i in range(5):
            _insert_sample_run(db, span1=float(i))
        runs = db.get_runs(limit=2, offset=3)
        assert len(runs) == 2

    def test_ordered_by_id_desc(self, db):
        _insert_sample_run(db, span1=1.0)
        _insert_sample_run(db, span1=2.0)
        runs = db.get_runs()
        assert runs[0]["id"] > runs[1]["id"]

    def test_empty_db(self, db):
        assert db.get_runs() == []


class TestGetRun:
    def test_returns_single_dict(self, db):
        run_id = _insert_sample_run(db)
        run = db.get_run(run_id)
        assert isinstance(run, dict)
        assert run["id"] == run_id

    def test_returns_all_fields(self, db):
        run_id = _insert_sample_run(db)
        run = db.get_run(run_id)
        assert run["span1"] == 9.0
        assert run["uf_max"] == 0.85
        assert run["error"] is None

    def test_not_found_returns_none(self, db):
        assert db.get_run(999) is None


class TestGetTimeSeries:
    def test_returns_time_series(self, db):
        run_id = _insert_sample_run(db)
        ts = db.get_time_series(run_id)
        assert isinstance(ts, list)
        assert len(ts) == 2

    def test_time_series_fields(self, db):
        run_id = _insert_sample_run(db)
        ts = db.get_time_series(run_id)
        assert ts[0]["time_min"] == 5.0
        assert ts[0]["utilization_factor"] == 0.7
        assert ts[1]["fire_temp"] == 678.0

    def test_ordered_by_time_step(self, db):
        run_id = _insert_sample_run(db)
        ts = db.get_time_series(run_id)
        assert ts[0]["time_step"] < ts[1]["time_step"]

    def test_no_time_series(self, db):
        run_id = _insert_sample_run(db, with_ts=False)
        ts = db.get_time_series(run_id)
        assert ts == []


class TestGetStats:
    def test_empty_db(self, db):
        stats = db.get_stats()
        assert stats["total"] == 0
        assert stats["successful"] == 0
        assert stats["errors"] == 0
        assert stats["pass_count"] == 0
        assert stats["fail_count"] == 0

    def test_with_runs(self, db):
        _insert_sample_run(db, uf_max=0.8)   # pass
        _insert_sample_run(db, uf_max=1.2, span1=10.0)   # fail
        _insert_sample_run(db, span1=11.0, error="broke")  # error
        stats = db.get_stats()
        assert stats["total"] == 3
        assert stats["successful"] == 2
        assert stats["errors"] == 1
        assert stats["pass_count"] == 1
        assert stats["fail_count"] == 1


class TestReportQueries:
    """Tests for report-oriented query methods added in Phase 0.2."""

    def test_get_successful_run_ids_empty(self, db):
        assert db.get_successful_run_ids() == []

    def test_get_successful_run_ids(self, db):
        _insert_sample_run(db, span1=1.0)           # id=1, success
        _insert_sample_run(db, span1=2.0)           # id=2, success
        _insert_sample_run(db, span1=3.0, error="e")  # id=3, error
        ids = db.get_successful_run_ids()
        assert ids == [1, 2]

    def test_get_all_time_series_column(self, db):
        _insert_sample_run(db, span1=1.0)  # has 2 time steps
        rows = db.get_all_time_series_column("lofl_temp")
        assert len(rows) == 2
        # Each row is (run_id, time_min, value)
        assert rows[0][0] == 1  # run_id
        assert rows[0][1] == 5.0  # time_min
        assert rows[0][2] == 200.0  # lofl_temp at step 1

    def test_get_all_time_series_column_excludes_errors(self, db):
        _insert_sample_run(db, span1=1.0)
        _insert_sample_run(db, span1=2.0, error="e")
        rows = db.get_all_time_series_column("mesh_temp")
        # Only run 1 has time series (run 2 is error)
        assert all(r[0] == 1 for r in rows)

    def test_get_all_time_series_column_rejects_invalid(self, db):
        with pytest.raises(ValueError, match="Invalid time_series column"):
            db.get_all_time_series_column("DROP TABLE runs")

    def test_get_time_grid(self, db):
        run_id = _insert_sample_run(db)
        grid = db.get_time_grid(run_id)
        assert grid == [5.0, 10.0]

    def test_get_time_grid_empty(self, db):
        run_id = _insert_sample_run(db, with_ts=False)
        assert db.get_time_grid(run_id) == []

    def test_get_time_of_max_uf(self, db):
        run_id = _insert_sample_run(db)
        # Step 2 has uf=0.85 (higher than step 1's 0.7)
        t = db.get_time_of_max_uf(run_id)
        assert t == 10.0

    def test_get_time_of_max_uf_no_data(self, db):
        run_id = _insert_sample_run(db, with_ts=False)
        assert db.get_time_of_max_uf(run_id) is None

    def test_get_time_exceed_one_none(self, db):
        run_id = _insert_sample_run(db)  # uf_max=0.85, never >= 1.0
        assert db.get_time_exceed_one(run_id) is None

    def test_get_time_exceed_one_found(self, db):
        # Insert a run with UF > 1.0
        params = {"span1": 99.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        outputs = {
            "comp_failure": 0, "uf_max": 1.5,
            "time_series": [
                {"time_step": 1, "time_min": 5.0, "fire_temp": 500.0,
                 "lofl_temp": 300.0, "mesh_temp": 200.0,
                 "slabtop_temp": 50.0, "slabbot_temp": 300.0,
                 "beam_hot_capacity": 200.0, "deflection": 10.0,
                 "slab_yield": 5.0, "enhancement": 1.2,
                 "slab_cap": 400.0, "total_plate_capacity": 650.0,
                 "utilization_factor": 0.8},
                {"time_step": 2, "time_min": 10.0, "fire_temp": 700.0,
                 "lofl_temp": 500.0, "mesh_temp": 350.0,
                 "slabtop_temp": 100.0, "slabbot_temp": 450.0,
                 "beam_hot_capacity": 150.0, "deflection": 30.0,
                 "slab_yield": 8.0, "enhancement": 1.5,
                 "slab_cap": 350.0, "total_plate_capacity": 500.0,
                 "utilization_factor": 1.2},
            ],
        }
        run_id = db.insert_run(params, outputs=outputs)
        assert db.get_time_exceed_one(run_id) == 10.0

    def test_get_successful_runs(self, db):
        _insert_sample_run(db, span1=1.0)
        _insert_sample_run(db, span1=2.0, error="fail")
        _insert_sample_run(db, span1=3.0)
        runs = db.get_successful_runs()
        assert len(runs) == 2
        assert all(isinstance(r, dict) for r in runs)
        assert runs[0]["span1"] == 1.0
        assert runs[1]["span1"] == 3.0
