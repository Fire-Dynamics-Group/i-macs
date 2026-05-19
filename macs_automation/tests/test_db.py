"""Tests for db.py — SQLite database layer."""

import socket
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

    def test_high_side_load_ratio_counts_as_fail(self, db):
        """A run with uf_max <= 1.0 but a perimeter beam load_ratio > 1.0 is a FAIL."""
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        outputs = {
            "comp_failure": 0, "uf_max": 0.5, "time_series": [],
            "side_a_load_ratio": 0.3, "side_b_load_ratio": 1.4,
            "side_c_load_ratio": 0.35, "side_d_load_ratio": 0.32,
        }
        db.insert_run(params, outputs=outputs)
        stats = db.get_stats()
        assert stats["successful"] == 1
        assert stats["pass_count"] == 0
        assert stats["fail_count"] == 1

    def test_comp_failure_does_not_count_as_fail(self, db):
        """A run with comp_failure=1 but uf_max below the threshold is a PASS.

        comp_failure is a MACS+ failure-mode *label*, not an independent
        pass/fail gate — the verdict (PrintP.js:388) never reads COMPFAILURE
        when UF passes. _pass_where() must mirror that.
        """
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        outputs = {"comp_failure": 1, "uf_max": 0.6, "time_series": []}
        db.insert_run(params, outputs=outputs)
        stats = db.get_stats()
        assert stats["pass_count"] == 1
        assert stats["fail_count"] == 0

    def test_uf_below_strict_threshold_passes(self, db):
        """uf_max in (1.0, 1.001) is a PASS — MACS+ verdict is uf < 1.001."""
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        outputs = {"comp_failure": 0, "uf_max": 1.0005, "time_series": []}
        db.insert_run(params, outputs=outputs)
        stats = db.get_stats()
        assert stats["pass_count"] == 1
        assert stats["fail_count"] == 0

    def test_uf_at_strict_threshold_fails(self, db):
        """uf_max >= 1.001 is a FAIL — MACS+ uses a strict < 1.001 comparison."""
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        outputs = {"comp_failure": 0, "uf_max": 1.001, "time_series": []}
        db.insert_run(params, outputs=outputs)
        stats = db.get_stats()
        assert stats["pass_count"] == 0
        assert stats["fail_count"] == 1

    def test_null_side_ratios_dont_block_pass(self, db):
        """A run with NULL side ratios (side wasn't analyzed) still passes if uf_max OK."""
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        outputs = {"comp_failure": 0, "uf_max": 0.6, "time_series": []}
        db.insert_run(params, outputs=outputs)
        stats = db.get_stats()
        assert stats["pass_count"] == 1


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


class TestBatches:
    """Tests for batch grouping functionality."""

    def test_insert_batch(self, db):
        """insert_batch creates a row in the batches table."""
        db.insert_batch("abc123", mode="lhs", total_expected=10)
        row = db.conn.execute(
            "SELECT batch_id, mode, total_expected FROM batches WHERE batch_id = ?",
            ("abc123",),
        ).fetchone()
        assert row is not None
        assert row[0] == "abc123"
        assert row[1] == "lhs"
        assert row[2] == 10

    def test_batch_id_stored_on_run(self, db):
        """_batch_id in params maps to batch_id column on runs."""
        db.insert_batch("batch42", mode="sweep", total_expected=1)
        params = {
            "span1": 9.0, "uSecSize": "IPE_500", "method": "iso",
            "time_limit": 60, "_batch_id": "batch42",
        }
        run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        row = db.conn.execute(
            "SELECT batch_id FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row[0] == "batch42"

    def test_get_batches(self, db):
        """get_batches returns aggregated stats per batch."""
        db.insert_batch("b1", mode="lhs", total_expected=3)
        # 2 pass, 1 error
        db.insert_run(
            {"span1": 1.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b1"},
            outputs={"comp_failure": 0, "uf_max": 0.5, "time_series": []},
        )
        db.insert_run(
            {"span1": 2.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b1"},
            outputs={"comp_failure": 0, "uf_max": 1.2, "time_series": []},
        )
        db.insert_run(
            {"span1": 3.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b1"},
            error="COM error",
        )
        batches = db.get_batches()
        assert len(batches) == 1
        b = batches[0]
        assert b["batch_id"] == "b1"
        assert b["mode"] == "lhs"
        assert b["run_count"] == 3
        assert b["pass_count"] == 1
        assert b["error_count"] == 1

    def test_get_batches_pass_count_includes_beam_check(self, db):
        """get_batches.pass_count must respect side load ratios, not just uf_max.

        comp_failure does NOT gate the verdict — it's a MACS+ failure-mode
        label — so a run with comp_failure=1 but uf_max below threshold passes.
        """
        db.insert_batch("b2", mode="sweep", total_expected=3)
        # Slab passes but beam B is overloaded — should be FAIL
        db.insert_run(
            {"span1": 1.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b2"},
            outputs={"comp_failure": 0, "uf_max": 0.5, "side_b_load_ratio": 1.3,
                     "time_series": []},
        )
        # Slab passes, comp_failure flag set — still a PASS (label, not a gate)
        db.insert_run(
            {"span1": 2.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b2"},
            outputs={"comp_failure": 1, "uf_max": 0.7, "time_series": []},
        )
        # Genuine pass
        db.insert_run(
            {"span1": 3.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b2"},
            outputs={"comp_failure": 0, "uf_max": 0.6, "time_series": []},
        )
        batches = db.get_batches()
        b2 = next(b for b in batches if b["batch_id"] == "b2")
        assert b2["pass_count"] == 2

    def test_get_batch_runs(self, db):
        """get_batch_runs returns correct runs for a batch, ordered by id."""
        db.insert_batch("b1", mode="sweep", total_expected=2)
        db.insert_run(
            {"span1": 1.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b1"},
            outputs={"comp_failure": 0, "uf_max": 0.5, "time_series": []},
        )
        db.insert_run(
            {"span1": 2.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b1"},
            outputs={"comp_failure": 0, "uf_max": 0.8, "time_series": []},
        )
        # Another run NOT in batch
        db.insert_run(
            {"span1": 3.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60},
            outputs={"comp_failure": 0, "uf_max": 0.9, "time_series": []},
        )
        runs = db.get_batch_runs("b1")
        assert len(runs) == 2
        assert runs[0]["span1"] == 1.0
        assert runs[1]["span1"] == 2.0

    def test_get_ungrouped_runs(self, db):
        """get_ungrouped_runs excludes batched runs."""
        db.insert_batch("b1", mode="sweep", total_expected=1)
        db.insert_run(
            {"span1": 1.0, "uSecSize": "IPE_500", "method": "iso",
             "time_limit": 60, "_batch_id": "b1"},
            outputs={"comp_failure": 0, "uf_max": 0.5, "time_series": []},
        )
        db.insert_run(
            {"span1": 2.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60},
            outputs={"comp_failure": 0, "uf_max": 0.9, "time_series": []},
        )
        ungrouped = db.get_ungrouped_runs()
        assert len(ungrouped) == 1
        assert ungrouped[0]["span1"] == 2.0

    def test_null_batch_id_for_legacy_runs(self, db):
        """Runs without _batch_id have NULL batch_id."""
        run_id = db.insert_run(
            {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60},
            outputs={"comp_failure": 0, "time_series": []},
        )
        row = db.conn.execute(
            "SELECT batch_id FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row[0] is None


class TestBatchConfigJson:
    """The dashboard's *Rerun batch* button needs the full sweep spec back.

    Stored as TEXT (JSON) on the batches table; legacy rows pre-dating this
    column must remain readable (NULL tolerated).
    """

    def test_config_json_column_present(self, db):
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(batches)")}
        assert "config_json" in cols

    def test_insert_batch_with_config_json(self, db):
        spec = {"mode": "sweep", "sweep": {"qf": [400, 500]}, "fixed": {"span1": 9}}
        import json
        db.insert_batch("b9", mode="sweep", total_expected=2, config_json=json.dumps(spec))
        row = db.conn.execute(
            "SELECT config_json FROM batches WHERE batch_id = ?", ("b9",)
        ).fetchone()
        assert row[0] is not None
        assert json.loads(row[0]) == spec

    def test_legacy_insert_batch_without_config_json(self, db):
        """Backwards compat: old call sites omit config_json — column is NULL."""
        db.insert_batch("b_legacy", mode="lhs", total_expected=5)
        row = db.conn.execute(
            "SELECT config_json FROM batches WHERE batch_id = ?", ("b_legacy",)
        ).fetchone()
        assert row[0] is None

    def test_ensure_schema_adds_column_to_legacy_db(self, tmp_path):
        """A DB created before this migration is upgraded on open."""
        legacy = tmp_path / "legacy.db"
        conn = sqlite3.connect(legacy)
        conn.executescript("""
            CREATE TABLE batches (
                batch_id TEXT PRIMARY KEY,
                created_at TEXT,
                mode TEXT,
                total_expected INTEGER
            );
        """)
        conn.execute(
            "INSERT INTO batches (batch_id, created_at, mode, total_expected) VALUES (?, ?, ?, ?)",
            ("old", "2026-01-01", "lhs", 3),
        )
        conn.commit()
        conn.close()

        with ResultsDB(legacy) as upgraded:
            cols = {row[1] for row in upgraded.conn.execute("PRAGMA table_info(batches)")}
            assert "config_json" in cols
            row = upgraded.conn.execute(
                "SELECT config_json FROM batches WHERE batch_id = ?", ("old",)
            ).fetchone()
            assert row[0] is None


class TestSyncProvenanceColumns:
    """uuid + device_name + app_version + synced_at columns for future
    multi-desktop cloud sync. INTEGER row IDs collide across machines, so the
    server-generated TEXT uuid is the cross-device join key. device_name +
    app_version stamp where/when each row was made; synced_at is the
    catch-up queue marker."""

    _NEW_RUN_COLS = ("uuid", "device_name", "app_version", "synced_at")
    _NEW_BATCH_COLS = ("device_name", "app_version", "synced_at")
    _NEW_CUSTOM_COLS = ("uuid", "device_name", "app_version", "synced_at")

    def test_runs_has_new_columns(self, db):
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(runs)")}
        for c in self._NEW_RUN_COLS:
            assert c in cols, f"runs missing column {c}"

    def test_batches_has_new_columns(self, db):
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(batches)")}
        for c in self._NEW_BATCH_COLS:
            assert c in cols, f"batches missing column {c}"

    @pytest.mark.parametrize("table", ["custom_sections", "custom_decks", "custom_meshes"])
    def test_custom_tables_have_new_columns(self, db, table):
        cols = {r[1] for r in db.conn.execute(f"PRAGMA table_info({table})")}
        for c in self._NEW_CUSTOM_COLS:
            assert c in cols, f"{table} missing column {c}"

    @pytest.mark.parametrize("table", ["runs", "custom_sections", "custom_decks", "custom_meshes"])
    def test_unique_index_on_uuid(self, db, table):
        idx_name = f"idx_{table}_uuid"
        rows = list(db.conn.execute(
            "SELECT name, [unique] FROM pragma_index_list(?)", (table,)
        ))
        match = next((r for r in rows if r[0] == idx_name), None)
        assert match is not None, f"missing index {idx_name}"
        assert match[1] == 1, f"index {idx_name} is not UNIQUE"

    def test_insert_run_populates_uuid(self, db):
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        row = db.conn.execute("SELECT uuid FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row[0] is not None
        assert len(row[0]) == 32  # uuid4().hex

    def test_insert_run_uuids_are_unique(self, db):
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        ids = [db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
               for _ in range(5)]
        uuids = {db.conn.execute("SELECT uuid FROM runs WHERE id = ?", (rid,)).fetchone()[0]
                 for rid in ids}
        assert len(uuids) == 5

    def test_insert_run_default_device_name_from_hostname(self, db, monkeypatch):
        monkeypatch.delenv("MACS_DEVICE_NAME", raising=False)
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        row = db.conn.execute("SELECT device_name FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row[0] == socket.gethostname()

    def test_insert_run_device_name_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MACS_DEVICE_NAME", "fdg-laptop-42")
        with ResultsDB(tmp_path / "dev.db") as db:
            params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
            run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
            row = db.conn.execute("SELECT device_name FROM runs WHERE id = ?", (run_id,)).fetchone()
            assert row[0] == "fdg-laptop-42"

    def test_insert_run_app_version_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MACS_APP_VERSION", "0.1.0-rc.4")
        with ResultsDB(tmp_path / "ver.db") as db:
            params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
            run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
            row = db.conn.execute("SELECT app_version FROM runs WHERE id = ?", (run_id,)).fetchone()
            assert row[0] == "0.1.0-rc.4"

    def test_insert_run_synced_at_starts_null(self, db):
        params = {"span1": 9.0, "uSecSize": "IPE_500", "method": "iso", "time_limit": 60}
        run_id = db.insert_run(params, outputs={"comp_failure": 0, "time_series": []})
        row = db.conn.execute("SELECT synced_at FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row[0] is None

    def test_insert_batch_populates_provenance(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MACS_DEVICE_NAME", "dev-box")
        monkeypatch.setenv("MACS_APP_VERSION", "9.9.9")
        with ResultsDB(tmp_path / "batch.db") as db:
            db.insert_batch("bX", mode="sweep", total_expected=1)
            row = db.conn.execute(
                "SELECT device_name, app_version, synced_at FROM batches WHERE batch_id = ?",
                ("bX",),
            ).fetchone()
            assert row[0] == "dev-box"
            assert row[1] == "9.9.9"
            assert row[2] is None

    @pytest.mark.parametrize("adder_method,getter_method,args", [
        ("add_custom_section", "get_custom_sections", ("name", 500.0, 200.0, 10.0, 16.0)),
        ("add_custom_deck", "get_custom_decks",
         ("name", "T", 58.0, 207.0, 106.0, 62.0, 0.0)),
        ("add_custom_mesh", "get_custom_meshes", ("name", 142.0, 142.0)),
    ])
    def test_custom_add_populates_uuid_and_provenance(
        self, tmp_path, monkeypatch, adder_method, getter_method, args
    ):
        monkeypatch.setenv("MACS_DEVICE_NAME", "dev-box")
        monkeypatch.setenv("MACS_APP_VERSION", "9.9.9")
        with ResultsDB(tmp_path / "c.db") as db:
            getattr(db, adder_method)(*args)
            rows = getattr(db, getter_method)()
            assert len(rows) == 1
            r = rows[0]
            assert r.get("uuid") is not None and len(r["uuid"]) == 32
            assert r.get("device_name") == "dev-box"
            assert r.get("app_version") == "9.9.9"
            assert r.get("synced_at") is None


class TestSchemaMigrationLegacy:
    """Opening a DB created before issue #11 must additively upgrade it:
    columns added, existing rows backfilled with uuids and hostname-derived
    device_name, app_version + synced_at left NULL (we can't reconstruct what
    version produced the row, so don't lie)."""

    def _build_legacy(self, path):
        """Build a pre-#11 schema: no uuid / device_name / app_version / synced_at."""
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_timestamp TEXT,
                span1 REAL,
                error TEXT,
                uf_max REAL,
                comp_failure INTEGER,
                side_a_load_ratio REAL,
                side_b_load_ratio REAL,
                side_c_load_ratio REAL,
                side_d_load_ratio REAL,
                batch_id TEXT
            );
            CREATE TABLE batches (
                batch_id TEXT PRIMARY KEY,
                created_at TEXT,
                mode TEXT,
                total_expected INTEGER
            );
            CREATE TABLE custom_sections (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                h REAL NOT NULL, b REAL NOT NULL, tw REAL NOT NULL, tf REAL NOT NULL,
                created_at TEXT
            );
            CREATE TABLE custom_decks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                deck_type TEXT, deck_depth REAL, deck_trug REAL,
                deck_top REAL, deck_bot REAL, deck_stiff_height REAL,
                created_at TEXT
            );
            CREATE TABLE custom_meshes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                main_area REAL, trans_area REAL,
                created_at TEXT
            );
        """)
        conn.execute(
            "INSERT INTO runs (run_timestamp, span1, uf_max) VALUES (?, ?, ?)",
            ("2026-01-01", 9.0, 0.7),
        )
        conn.execute(
            "INSERT INTO runs (run_timestamp, span1, uf_max) VALUES (?, ?, ?)",
            ("2026-01-02", 10.0, 0.8),
        )
        conn.execute(
            "INSERT INTO batches (batch_id, created_at, mode, total_expected) VALUES (?, ?, ?, ?)",
            ("old_batch", "2026-01-01", "sweep", 5),
        )
        conn.execute(
            "INSERT INTO custom_sections (id, name, h, b, tw, tf, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("CUSTOM_1", "Legacy UB", 500.0, 200.0, 10.0, 16.0, "2026-01-01"),
        )
        conn.commit()
        conn.close()

    def test_legacy_runs_backfilled(self, tmp_path):
        legacy = tmp_path / "legacy.db"
        self._build_legacy(legacy)

        with ResultsDB(legacy) as upgraded:
            rows = list(upgraded.conn.execute(
                "SELECT uuid, device_name, app_version, synced_at FROM runs ORDER BY id"
            ))
        # Both legacy rows have uuids
        assert all(r[0] is not None and len(r[0]) == 32 for r in rows)
        # uuids are unique
        assert len({r[0] for r in rows}) == len(rows)
        # device_name backfilled to current hostname (best guess)
        host = socket.gethostname()
        assert all(r[1] == host for r in rows)
        # app_version + synced_at left NULL — stamping them would lie
        assert all(r[2] is None for r in rows)
        assert all(r[3] is None for r in rows)

    def test_legacy_custom_sections_backfilled(self, tmp_path):
        legacy = tmp_path / "legacy.db"
        self._build_legacy(legacy)

        with ResultsDB(legacy) as upgraded:
            cols = {r[1] for r in upgraded.conn.execute("PRAGMA table_info(custom_sections)")}
            assert "uuid" in cols and "device_name" in cols
            row = upgraded.conn.execute(
                "SELECT uuid, device_name, app_version, synced_at "
                "FROM custom_sections WHERE id = ?", ("CUSTOM_1",)
            ).fetchone()
        assert row[0] is not None and len(row[0]) == 32
        assert row[1] == socket.gethostname()
        assert row[2] is None and row[3] is None

    def test_legacy_unique_index_created(self, tmp_path):
        """Backfill must precede the unique-index create — otherwise the
        index build fails on NULL collisions and the migration aborts."""
        legacy = tmp_path / "legacy.db"
        self._build_legacy(legacy)

        with ResultsDB(legacy) as upgraded:
            idx = upgraded.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_runs_uuid'"
            ).fetchone()
        assert idx is not None


class TestSettings:
    """Issue #23 — key/value settings table for the manual MACS+ install-location override."""

    def test_settings_table_exists(self, db):
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        )
        assert cursor.fetchone() is not None

    def test_get_setting_missing_returns_none(self, db):
        assert db.get_setting("does_not_exist") is None

    def test_set_and_get_roundtrip(self, db):
        db.set_setting("macs_data_path", r"C:\foo\bar\Data.xml")
        assert db.get_setting("macs_data_path") == r"C:\foo\bar\Data.xml"

    def test_set_overwrites(self, db):
        db.set_setting("macs_data_path", "old")
        db.set_setting("macs_data_path", "new")
        assert db.get_setting("macs_data_path") == "new"

    def test_delete(self, db):
        db.set_setting("k", "v")
        db.delete_setting("k")
        assert db.get_setting("k") is None

    def test_legacy_db_gets_settings_table(self, tmp_path):
        """Opening a legacy DB without `settings` must auto-create it
        via the `CREATE TABLE IF NOT EXISTS` in SCHEMA_SQL."""
        legacy = tmp_path / "legacy.db"
        conn = sqlite3.connect(legacy)
        # Pre-existing tables; intentionally NO settings table.
        conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        with ResultsDB(legacy) as upgraded:
            assert upgraded.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
            ).fetchone() is not None
            upgraded.set_setting("k", "v")
            assert upgraded.get_setting("k") == "v"
