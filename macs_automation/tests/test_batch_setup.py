"""Tests for batch_setup.py — deriving a batch's shared setup from its runs."""

from macs_automation.batch_setup import INPUT_GROUPS, derive_setup


def _run(**overrides) -> dict:
    """A runs-table row with the handful of columns these tests care about."""
    row = {
        "id": 1,
        "span1": 9.0, "span2": 9.0, "numbeam": 2,
        "fck": 25.0, "slab_depth": 130.0,
        "u_sec_size": "IPE_500",
        "method": "iso", "time_limit": 60, "qf": 511.0,
        # Outputs + metadata — must never appear in the setup.
        "uf_max": 0.42, "max_deflection": 210.0, "duration_ms": 1234.0,
        "run_timestamp": "2026-07-01T10:00:00Z", "batch_id": "b1",
        "error": None, "uuid": "deadbeef", "engine_version": "2.0.0.2",
    }
    row.update(overrides)
    return row


def _fields(setup: dict) -> dict:
    """Flatten the grouped response to {key: field} for easy assertions."""
    return {
        f["key"]: f
        for group in setup["groups"]
        for f in group["fields"]
    }


class TestSharedFields:
    def test_reports_a_value_shared_by_every_run(self):
        setup = derive_setup([_run(), _run(id=2)])
        span2 = _fields(setup)["span2"]
        assert span2["varies"] is False
        assert span2["value"] == 9.0

    def test_run_count(self):
        assert derive_setup([_run(), _run(id=2), _run(id=3)])["run_count"] == 3

    def test_single_run_batch_is_all_shared(self):
        setup = derive_setup([_run()])
        assert all(not f["varies"] for f in _fields(setup).values())

    def test_no_runs_yields_no_fields(self):
        setup = derive_setup([])
        assert setup["run_count"] == 0
        assert setup["groups"] == []


class TestVaryingFields:
    def test_numeric_spread_reports_range_and_distinct_count(self):
        runs = [_run(span1=9.0), _run(id=2, span1=12.0), _run(id=3, span1=9.0)]
        span1 = _fields(derive_setup(runs))["span1"]
        assert span1["varies"] is True
        assert span1["distinct"] == 2
        assert span1["min"] == 9.0
        assert span1["max"] == 12.0
        # A varying field has no single value to show.
        assert "value" not in span1

    def test_non_numeric_spread_lists_the_values_instead_of_a_range(self):
        runs = [_run(u_sec_size="IPE_500"), _run(id=2, u_sec_size="IPE_300")]
        sec = _fields(derive_setup(runs))["u_sec_size"]
        assert sec["varies"] is True
        assert sorted(sec["values"]) == ["IPE_300", "IPE_500"]
        assert "min" not in sec

    def test_long_value_lists_are_capped_but_counted(self):
        """A 500-run LHS batch must not ship 500 strings per field."""
        runs = [_run(id=i, u_sec_size=f"SEC_{i}") for i in range(30)]
        sec = _fields(derive_setup(runs))["u_sec_size"]
        assert sec["distinct"] == 30
        assert len(sec["values"]) <= 10

    def test_a_null_in_some_runs_counts_as_variation(self):
        """Not every run having a value is itself worth surfacing — it means
        the batch isn't as uniform as a single value would imply."""
        runs = [_run(qf=511.0), _run(id=2, qf=None)]
        assert _fields(derive_setup(runs))["qf"]["varies"] is True


class TestColumnSelection:
    def test_outputs_are_excluded(self):
        keys = _fields(derive_setup([_run(), _run(id=2, uf_max=0.9)]))
        for out in ("uf_max", "max_deflection", "duration_ms"):
            assert out not in keys

    def test_metadata_is_excluded(self):
        keys = _fields(derive_setup([_run()]))
        for meta in ("id", "uuid", "batch_id", "run_timestamp", "error",
                     "engine_version"):
            assert meta not in keys

    def test_columns_null_in_every_run_are_omitted(self):
        """Legacy rows have whole groups of NULLs — showing 20 empty fields
        would bury the ones that matter."""
        keys = _fields(derive_setup([_run(deck_name=None), _run(id=2, deck_name=None)]))
        assert "deck_name" not in keys

    def test_a_column_missing_from_the_rows_entirely_is_omitted(self):
        """A pre-migration DB simply won't have some columns."""
        row = {"span1": 9.0, "uf_max": 0.5}
        assert "fck" not in _fields(derive_setup([row]))


class TestGrouping:
    def test_groups_follow_the_config_form_order(self):
        setup = derive_setup([_run()])
        titles = [g["title"] for g in setup["groups"]]
        assert titles == [
            t for t, _ in INPUT_GROUPS if t in titles
        ]
        assert "Geometry" in titles

    def test_empty_groups_are_dropped(self):
        setup = derive_setup([{"span1": 9.0}])
        assert [g["title"] for g in setup["groups"]] == ["Geometry"]

    def test_fields_carry_a_human_label_and_unit(self):
        span1 = _fields(derive_setup([_run()]))["span1"]
        assert span1["label"] == "Span 1"
        assert span1["unit"] == "m"

    def test_every_grouped_field_has_a_label(self):
        """Guard against adding a column to INPUT_GROUPS without labelling it."""
        for _title, fields in INPUT_GROUPS:
            for key, label, _unit in fields:
                assert label, f"{key} has no label"
