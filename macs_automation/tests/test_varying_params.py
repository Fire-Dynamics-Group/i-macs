"""Tests for varying_params.varying_params_from_config — pure module.

Derives `{fixed: {...}, varying: {...}}` from the sweep spec stored in
`batches.config_json`. Used by:
  - `/api/batches` to populate the batches list with what varied per run
  - `/batches/:id` analytical view chart axes
  - slice 2's *Rerun batch* prefill
Single source of truth: the same shape is consumed by both backend and
frontend, so the contract here is load-bearing.
"""

import json

import pytest

from macs_automation.varying_params import varying_params_from_config


class TestNullAndMalformed:
    def test_none_returns_empty(self):
        assert varying_params_from_config(None) == {"fixed": {}, "varying": {}}

    def test_empty_string_returns_empty(self):
        assert varying_params_from_config("") == {"fixed": {}, "varying": {}}

    def test_malformed_json_returns_empty(self):
        # Don't raise — the dashboard must keep working when an old batch was
        # written with a bad serializer or a partially-written row.
        assert varying_params_from_config("{not json") == {"fixed": {}, "varying": {}}

    def test_non_dict_top_level_returns_empty(self):
        assert varying_params_from_config(json.dumps([1, 2, 3])) == {"fixed": {}, "varying": {}}


class TestGridSweep:
    def test_single_varying_param(self):
        spec = {
            "analysis_method": "iso",
            "sweep": {"qf": [400, 500, 600]},
            "fixed": {"span1": 9, "fck": 25},
        }
        result = varying_params_from_config(json.dumps(spec))
        assert result["varying"] == {"qf": [400, 500, 600]}
        assert result["fixed"] == {"span1": 9, "fck": 25}

    def test_multi_varying(self):
        spec = {
            "sweep": {"qf": [400, 500], "window_percent": [30, 50, 80]},
            "fixed": {"span1": 9},
        }
        result = varying_params_from_config(json.dumps(spec))
        assert set(result["varying"].keys()) == {"qf", "window_percent"}
        assert result["varying"]["qf"] == [400, 500]
        assert result["varying"]["window_percent"] == [30, 50, 80]
        assert result["fixed"] == {"span1": 9}

    def test_scalar_in_sweep_treated_as_single_value(self):
        # generate_combinations allows scalar values in the sweep map; treat
        # them as single-value varying so the contract stays predictable.
        spec = {"sweep": {"qf": 500}, "fixed": {"span1": 9}}
        result = varying_params_from_config(json.dumps(spec))
        assert result["varying"] == {"qf": [500]}
        assert result["fixed"] == {"span1": 9}

    def test_empty_sweep_means_all_fixed(self):
        spec = {"sweep": {}, "fixed": {"span1": 9, "fck": 25}}
        result = varying_params_from_config(json.dumps(spec))
        assert result["varying"] == {}
        assert result["fixed"] == {"span1": 9, "fck": 25}


class TestLhs:
    def test_lhs_distributions_are_varying(self):
        spec = {
            "sampling": "lhs",
            "analysis_method": "parametric",
            "n_samples": 5,
            "distributions": {
                "qf": {"preset": "Office", "mean": 420, "type": "gumbel", "cov": 0.3},
                "window_percent": {"preset": "Opening Factor"},
            },
            "fixed": {"span1": 9, "span2": 9},
        }
        result = varying_params_from_config(json.dumps(spec))
        assert set(result["varying"].keys()) == {"qf", "window_percent"}
        # The dashboard needs a stable shape; LHS values are summarised by
        # the distribution descriptor since the actual draws aren't a list.
        assert "preset" in result["varying"]["qf"] or "type" in result["varying"]["qf"]
        assert result["fixed"] == {"span1": 9, "span2": 9}

    def test_lhs_without_distributions_returns_all_fixed(self):
        spec = {"sampling": "lhs", "fixed": {"span1": 9}}
        result = varying_params_from_config(json.dumps(spec))
        assert result["varying"] == {}
        assert result["fixed"] == {"span1": 9}


class TestShape:
    def test_always_returns_both_keys(self):
        # Any well-formed-ish input must always come back with both keys
        # populated as dicts, never missing or None.
        for inp in [None, "", "{}", '{"sweep":{}}', '{"fixed":{}}']:
            result = varying_params_from_config(inp)
            assert "fixed" in result
            assert "varying" in result
            assert isinstance(result["fixed"], dict)
            assert isinstance(result["varying"], dict)
