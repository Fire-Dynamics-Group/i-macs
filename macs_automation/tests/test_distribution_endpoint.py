"""Tests for GET /api/batches/{batch_id}/distribution.

The endpoint feeds the AnalyticalView's three distribution charts (Total
Capacity, Unprotected Beam Temperature, Reinforcement Bar Temperature).

Contract:
  - `column` is whitelisted to {total_plate_capacity, lofl_temp, mesh_temp}.
  - `average` is computed across ALL successful runs (the source of truth).
  - `spaghetti` is downsampled to at most `spaghetti_n` runs (stride sample).
  - `factored_hot_min/max` are populated only for total_plate_capacity; the
    other columns get null/null.
"""

import json

import pytest
from fastapi.testclient import TestClient

from macs_automation.app import app
from macs_automation.db import ResultsDB


@pytest.fixture(autouse=True)
def mock_ref_data():
    """Provide fake reference data so tests don't need Data.xml."""
    import macs_automation.app as app_module
    app_module._ref_data = {
        "sections": {},
        "decks": {},
        "meshes": {},
    }
    yield
    app_module._ref_data = None


@pytest.fixture
def use_tmp_db(tmp_path, monkeypatch):
    import macs_automation.app as app_module
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    return tmp_path / "test.db"


@pytest.fixture
def client(use_tmp_db):
    return TestClient(app)


def _make_ts(n_steps=4, *, capacity_base=700.0, lofl_base=200.0, mesh_base=100.0):
    """Synthetic time series — 4 steps spanning 0..15 minutes."""
    rows = []
    for i in range(n_steps):
        t = float(i) * 5.0
        frac = i / max(n_steps - 1, 1)
        rows.append({
            "time_step": i + 1,
            "time_min": t,
            "fire_temp": 20.0 + 800.0 * frac,
            "lofl_temp": lofl_base + 400.0 * frac,
            "mesh_temp": mesh_base + 300.0 * frac,
            "slabtop_temp": 50.0 + 100.0 * frac,
            "slabbot_temp": 50.0 + 250.0 * frac,
            "beam_hot_capacity": 250.0 * (1 - 0.5 * frac),
            "deflection": 5.0 + 80.0 * frac,
            "slab_yield": 2.0 + 6.0 * frac,
            "enhancement": 1.0 + 0.4 * frac,
            "slab_cap": 400.0 - 80.0 * frac,
            "total_plate_capacity": capacity_base * (1 - 0.5 * frac),
            "utilization_factor": 0.3 + 0.3 * frac,
        })
    return rows


def _seed_batch_with_runs(
    db_path,
    batch_id="b1",
    *,
    n_runs=2,
    factored_hot_values=None,
    capacity_offsets=None,
    add_errored=False,
):
    """Insert a batch with `n_runs` successful runs + optional error rows."""
    if factored_hot_values is None:
        factored_hot_values = [5.6] * n_runs
    if capacity_offsets is None:
        capacity_offsets = [0.0] * n_runs

    db = ResultsDB(db_path)
    try:
        db.insert_batch(batch_id, mode="lhs", total_expected=n_runs,
                        config_json=json.dumps({}))
        base_params = {
            "_batch_id": batch_id,
            "span1": 9.0, "span2": 9.0, "numbeam": 2,
            "method": "parametric", "fck": 25, "slab_depth": 130,
            "uSecSize": "IPE_500", "time_limit": 60,
        }
        for i in range(n_runs):
            outputs = {
                "comp_failure": 0,
                "mb1_reqd": 100.0, "mb2_reqd": 200.0,
                "factored_hot": factored_hot_values[i],
                "uf_max": 0.5,
                "max_temperature": 900.0, "max_deflection": 100.0,
                "max_slab_cap": 500.0, "max_beam_cap": 300.0, "max_total_cap": 800.0,
                "side_a_load_ratio": 0.3, "side_b_load_ratio": 0.4,
                "side_c_load_ratio": 0.35, "side_d_load_ratio": 0.32,
                "side_a_critical_temp": 600.0, "side_b_critical_temp": 620.0,
                "side_c_critical_temp": 640.0, "side_d_critical_temp": 645.0,
                "duration_ms": 100.0,
                "time_series": _make_ts(
                    capacity_base=700.0 + capacity_offsets[i],
                ),
            }
            db.insert_run(base_params, outputs=outputs)
        if add_errored:
            db.insert_run(
                {**base_params}, error="COM error: thermal instability",
            )
    finally:
        db.close()


class TestDistributionEndpointShape:
    def test_returns_average_spaghetti_and_factored_keys(self, client, use_tmp_db):
        _seed_batch_with_runs(use_tmp_db, n_runs=2)
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "average" in body
        assert "spaghetti" in body
        assert "factored_hot_min" in body
        assert "factored_hot_max" in body

    def test_average_is_list_of_time_value_pairs(self, client, use_tmp_db):
        _seed_batch_with_runs(use_tmp_db, n_runs=2)
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        body = resp.json()
        assert isinstance(body["average"], list)
        for entry in body["average"]:
            assert len(entry) == 2
            assert isinstance(entry[0], (int, float))
            assert isinstance(entry[1], (int, float))

    def test_spaghetti_contains_run_id_and_points(self, client, use_tmp_db):
        _seed_batch_with_runs(use_tmp_db, n_runs=2)
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        body = resp.json()
        for entry in body["spaghetti"]:
            assert "run_id" in entry
            assert "points" in entry
            assert isinstance(entry["points"], list)
            for pt in entry["points"]:
                assert len(pt) == 2


class TestDistributionAverage:
    def test_average_is_arithmetic_mean_across_all_successful_runs(self, client, use_tmp_db):
        # Two runs with offsets: capacity_base=700.0 and 900.0 → average curve
        # at time=0 is (700+900)/2 = 800.
        _seed_batch_with_runs(
            use_tmp_db, n_runs=2, capacity_offsets=[0.0, 200.0],
        )
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        body = resp.json()
        # avg at t=0 → (700 + 900) / 2 = 800
        assert body["average"][0][0] == 0.0
        assert body["average"][0][1] == pytest.approx(800.0)

    def test_average_excludes_errored_runs(self, client, use_tmp_db):
        _seed_batch_with_runs(
            use_tmp_db, n_runs=1, capacity_offsets=[0.0], add_errored=True,
        )
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        body = resp.json()
        # Only the one successful run feeds the average — the error run has
        # no time series anyway, so the curve equals the run's curve.
        assert body["average"][0][1] == pytest.approx(700.0)


class TestDistributionSpaghettiDownsample:
    def test_returns_all_runs_when_count_below_n(self, client, use_tmp_db):
        _seed_batch_with_runs(use_tmp_db, n_runs=3)
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity", "spaghetti_n": 500},
        )
        body = resp.json()
        assert len(body["spaghetti"]) == 3

    def test_stride_samples_when_count_above_n(self, client, use_tmp_db):
        _seed_batch_with_runs(use_tmp_db, n_runs=20)
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity", "spaghetti_n": 5},
        )
        body = resp.json()
        assert len(body["spaghetti"]) <= 5
        # Average is still computed from all 20.
        # capacity_base=700 across all, so mean stays 700 at t=0.
        assert body["average"][0][1] == pytest.approx(700.0)


class TestDistributionFactoredHot:
    def test_single_value_when_all_runs_share_factored_hot(self, client, use_tmp_db):
        _seed_batch_with_runs(
            use_tmp_db, n_runs=3, factored_hot_values=[5.6, 5.6, 5.6],
        )
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        body = resp.json()
        assert body["factored_hot_min"] == pytest.approx(5.6)
        assert body["factored_hot_max"] == pytest.approx(5.6)

    def test_range_when_runs_differ(self, client, use_tmp_db):
        _seed_batch_with_runs(
            use_tmp_db, n_runs=3, factored_hot_values=[4.0, 5.0, 6.0],
        )
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        body = resp.json()
        assert body["factored_hot_min"] == pytest.approx(4.0)
        assert body["factored_hot_max"] == pytest.approx(6.0)

    def test_null_for_non_capacity_columns(self, client, use_tmp_db):
        _seed_batch_with_runs(use_tmp_db, n_runs=2)
        for col in ("lofl_temp", "mesh_temp"):
            resp = client.get(
                "/api/batches/b1/distribution",
                params={"column": col},
            )
            body = resp.json()
            assert body["factored_hot_min"] is None
            assert body["factored_hot_max"] is None


class TestDistributionWhitelist:
    @pytest.fixture(autouse=True)
    def _seed(self, use_tmp_db):
        _seed_batch_with_runs(use_tmp_db, n_runs=2)

    def test_total_plate_capacity_allowed(self, client):
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "total_plate_capacity"},
        )
        assert resp.status_code == 200

    def test_lofl_temp_allowed(self, client):
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "lofl_temp"},
        )
        assert resp.status_code == 200

    def test_mesh_temp_allowed(self, client):
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "mesh_temp"},
        )
        assert resp.status_code == 200

    def test_non_whitelisted_column_rejected(self, client):
        # `fire_temp` exists in the broader TIME_SERIES_COLUMNS set but is
        # NOT in the AnalyticalView whitelist for this endpoint.
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "fire_temp"},
        )
        assert resp.status_code == 400

    def test_sql_injection_attempt_rejected(self, client):
        resp = client.get(
            "/api/batches/b1/distribution",
            params={"column": "1; DROP TABLE runs"},
        )
        assert resp.status_code == 400


class TestDistributionEmptyState:
    def test_zero_successful_runs_returns_empty_arrays(self, client, use_tmp_db):
        # Batch with only errored runs.
        db = ResultsDB(use_tmp_db)
        try:
            db.insert_batch("empty_b", mode="lhs", total_expected=1,
                            config_json=json.dumps({}))
            db.insert_run(
                {
                    "_batch_id": "empty_b", "span1": 9.0, "method": "iso",
                    "uSecSize": "IPE_500", "time_limit": 60,
                },
                error="COM error",
            )
        finally:
            db.close()
        resp = client.get(
            "/api/batches/empty_b/distribution",
            params={"column": "total_plate_capacity"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["average"] == []
        assert body["spaghetti"] == []
        assert body["factored_hot_min"] is None
        assert body["factored_hot_max"] is None
