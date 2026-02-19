"""Tests for runner.py — batch runner with callback support."""

import threading

import pytest

from macs_automation.db import ResultsDB
from macs_automation.runner import BatchProgress, run_batch_with_callback


class FakeEngine:
    """Mock engine that returns canned results."""

    def __init__(self, outputs=None, error=None):
        self._outputs = outputs
        self._error = error

    def set_inputs(self, params, sections_db):
        if self._error:
            raise RuntimeError(self._error)

    def run(self, method="iso"):
        if self._error:
            raise RuntimeError(self._error)
        return self._outputs or {
            "comp_failure": 0,
            "mb1_reqd": 100.0, "mb2_reqd": 200.0,
            "factored_hot": 3.7, "uf_max": 0.5,
            "max_temperature": 900.0, "max_deflection": 120.0,
            "max_slab_cap": 500.0, "max_beam_cap": 300.0, "max_total_cap": 800.0,
            "side_a_load_ratio": 0.3, "side_a_critical_temp": 650.0,
            "side_b_load_ratio": 0.4, "side_b_critical_temp": 620.0,
            "side_c_load_ratio": 0.35, "side_c_critical_temp": 640.0,
            "side_d_load_ratio": 0.32, "side_d_critical_temp": 645.0,
            "duration_ms": 100.0,
            "time_series": [],
        }


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_runner.db"
    with ResultsDB(db_path) as database:
        yield database


def _make_combos(n=3):
    """Generate n simple parameter combinations."""
    return [
        {"span1": float(i), "span2": 9.0, "numbeam": 2,
         "uSecSize": "IPE_500", "method": "iso", "time_limit": 60,
         "fck": 25, "slab_depth": 130}
        for i in range(n)
    ]


class TestBatchProgress:
    def test_defaults(self):
        p = BatchProgress()
        assert p.status == "pending"
        assert p.total == 0
        assert p.completed == 0
        assert p.errors == 0

    def test_error_log_is_independent(self):
        """Each instance should have its own error_log list."""
        p1 = BatchProgress()
        p2 = BatchProgress()
        p1.error_log.append("e")
        assert p2.error_log == []


class TestRunBatch:
    def test_runs_all_combinations(self, db):
        combos = _make_combos(3)
        progress = run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(),
            resume=False,
        )
        assert progress.status == "completed"
        assert progress.completed == 3
        assert progress.errors == 0
        assert db.get_run_count() == 3

    def test_callback_called_per_run(self, db):
        combos = _make_combos(3)
        callback_args = []

        def on_complete(run_id, params, outputs, error, progress):
            callback_args.append((run_id, error, progress.completed))

        run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(),
            on_run_complete=on_complete,
            resume=False,
        )
        assert len(callback_args) == 3
        # Progress should increment 1, 2, 3
        assert [a[2] for a in callback_args] == [1, 2, 3]
        # All should have no error
        assert all(a[1] is None for a in callback_args)

    def test_handles_engine_errors(self, db):
        combos = _make_combos(2)
        progress = run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(error="boom"),
            resume=False,
        )
        assert progress.completed == 2
        assert progress.errors == 2
        assert len(progress.error_log) == 2
        assert "boom" in progress.error_log[0]
        # Runs should be in DB with errors
        assert db.get_run_count() == 2
        assert db.get_successful_run_count() == 0

    def test_resume_skips_existing(self, db):
        combos = _make_combos(3)
        # Run first batch
        run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(),
            resume=False,
        )
        assert db.get_run_count() == 3

        # Run again with resume=True — should skip all
        progress = run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(),
            resume=True,
        )
        assert progress.skipped == 3
        assert progress.completed == 0
        assert db.get_run_count() == 3  # no new runs

    def test_cancel_stops_batch(self, db):
        combos = _make_combos(5)
        cancel = threading.Event()
        runs_completed = []

        def on_complete(run_id, params, outputs, error, progress):
            runs_completed.append(run_id)
            if len(runs_completed) == 2:
                cancel.set()

        progress = run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(),
            on_run_complete=on_complete,
            cancel_event=cancel,
            resume=False,
        )
        assert progress.status == "cancelled"
        # Should have completed 2 runs, then cancelled before 3rd
        assert progress.completed == 2
        assert db.get_run_count() == 2

    def test_elapsed_seconds_tracked(self, db):
        combos = _make_combos(1)
        progress = run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(),
            resume=False,
        )
        assert progress.elapsed_seconds >= 0
        assert progress.status == "completed"

    def test_error_log_trimmed(self, db):
        combos = _make_combos(25)
        progress = run_batch_with_callback(
            combos, db, {},
            engine_factory=lambda: FakeEngine(error="err"),
            resume=False,
        )
        assert len(progress.error_log) <= 20

    def test_mixed_success_and_failure(self, db):
        """Test with some runs succeeding and some failing."""
        call_count = [0]

        def factory():
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return FakeEngine(error="even run fails")
            return FakeEngine()

        combos = _make_combos(4)
        callback_errors = []

        def on_complete(run_id, params, outputs, error, progress):
            callback_errors.append(error)

        progress = run_batch_with_callback(
            combos, db, {},
            engine_factory=factory,
            on_run_complete=on_complete,
            resume=False,
        )
        assert progress.completed == 4
        assert progress.errors == 2
        # Callback should see errors for even runs
        assert callback_errors[1] is not None
        assert callback_errors[0] is None
