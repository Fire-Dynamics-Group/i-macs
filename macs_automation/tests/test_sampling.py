"""Tests for sampling.py — LHS sampling module."""

import math

import numpy as np
import pytest
from scipy.stats import gumbel_l, lognorm

from macs_automation.sampling import (
    FIRE_LOAD_PRESETS,
    generate_lhs_samples,
    gumbel_ppf,
    lognormal_ppf,
    opening_factor_transform,
    resolve_distribution,
)


class TestGumbelPPF:
    def test_output_shape(self):
        u = np.linspace(0.01, 0.99, 100)
        result = gumbel_ppf(u, mean=420, cov=0.3)
        assert result.shape == (100,)

    def test_known_values_match_scipy(self):
        """Verify our ppf matches direct scipy gumbel_l computation."""
        mean, cov = 420, 0.3
        std = mean * cov
        scale = std * math.sqrt(6) / math.pi
        loc = mean + np.euler_gamma * scale

        u = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
        expected = gumbel_l.ppf(u, loc, scale)
        result = gumbel_ppf(u, mean, cov)
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_mean_cov_recovery(self):
        """Large sample from uniform -> gumbel should recover mean and cov."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0.001, 0.999, size=100_000)
        samples = gumbel_ppf(u, mean=420, cov=0.3)
        assert abs(samples.mean() - 420) < 10  # within ~2%
        assert abs(samples.std() / samples.mean() - 0.3) < 0.05

    def test_all_positive_for_positive_mean(self):
        """With typical fire load params, virtually all values should be positive."""
        u = np.linspace(0.01, 0.99, 1000)
        result = gumbel_ppf(u, mean=780, cov=0.3)
        assert (result > 0).sum() > 990  # almost all positive


class TestLognormalPPF:
    def test_output_shape(self):
        u = np.linspace(0.01, 0.99, 100)
        result = lognormal_ppf(u, mean=526, cov=0.61)
        assert result.shape == (100,)

    def test_known_values_match_scipy(self):
        """Verify our ppf matches direct scipy lognorm computation."""
        mean, cov = 526, 0.61
        sln = np.sqrt(np.log(1 + cov**2))
        mln = np.log(mean) - 0.5 * sln**2
        scale = np.exp(mln)

        u = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
        expected = lognorm.ppf(u, sln, 0, scale)
        result = lognormal_ppf(u, mean, cov)
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_all_positive(self):
        """Lognormal outputs should always be positive."""
        u = np.linspace(0.01, 0.99, 1000)
        result = lognormal_ppf(u, mean=526, cov=0.61)
        assert np.all(result > 0)

    def test_mean_cov_recovery(self):
        """Large sample should recover mean and cov."""
        rng = np.random.default_rng(42)
        u = rng.uniform(0.001, 0.999, size=100_000)
        samples = lognormal_ppf(u, mean=526, cov=0.61)
        assert abs(samples.mean() - 526) < 30
        assert abs(samples.std() / samples.mean() - 0.61) < 0.1


class TestOpeningFactorTransform:
    def test_output_range(self):
        """All output values should be in [0, 100]."""
        rng = np.random.default_rng(42)
        # Generate some raw lognormal opening factor values (some > 1)
        raw = lognormal_ppf(np.linspace(0.01, 0.99, 200), mean=0.2, cov=1.0)
        result = opening_factor_transform(raw, rng)
        assert np.all(result >= 0)
        assert np.all(result <= 100)

    def test_inversion(self):
        """Values near 0 in raw should become near 100 in result (after *100)."""
        values = np.array([0.01, 0.05, 0.1])
        rng = np.random.default_rng(42)
        result = opening_factor_transform(values, rng)
        # 1 - 0.01 = 0.99, *100 = 99
        assert result[0] > 90

    def test_deterministic_with_seed(self):
        """Same seed should produce same result for values > 1."""
        raw = np.array([0.5, 1.5, 2.0, 0.3])  # some > 1
        r1 = opening_factor_transform(raw.copy(), np.random.default_rng(99))
        r2 = opening_factor_transform(raw.copy(), np.random.default_rng(99))
        np.testing.assert_array_equal(r1, r2)

    def test_values_above_one_replaced(self):
        """Values > 1 should be replaced with uniform(0,1) then inverted."""
        raw = np.array([2.0, 3.0, 5.0])
        rng = np.random.default_rng(42)
        result = opening_factor_transform(raw, rng)
        # After replacement and transform, all should be in [0, 100]
        assert np.all(result >= 0)
        assert np.all(result <= 100)


class TestResolveDistribution:
    def test_explicit_gumbel(self):
        spec = {"type": "gumbel", "mean": 420, "cov": 0.3}
        result = resolve_distribution(spec)
        assert result["type"] == "gumbel"
        assert result["mean"] == 420
        assert result["cov"] == 0.3

    def test_explicit_lognormal(self):
        spec = {"type": "lognormal", "mean": 526, "cov": 0.61}
        result = resolve_distribution(spec)
        assert result["type"] == "lognormal"
        assert result["mean"] == 526
        assert result["cov"] == 0.61

    def test_preset_office(self):
        spec = {"preset": "Office"}
        result = resolve_distribution(spec)
        assert result["type"] == "gumbel"
        assert result["mean"] == 420
        assert result["cov"] == 0.3

    def test_preset_fast_food(self):
        spec = {"preset": "Fast food outlet"}
        result = resolve_distribution(spec)
        assert result["type"] == "lognormal"
        assert result["mean"] == 526
        assert result["cov"] == 0.61

    def test_preset_opening_factor(self):
        spec = {"preset": "Opening Factor"}
        result = resolve_distribution(spec)
        assert result["type"] == "lognormal"
        assert result["mean"] == 0.2
        assert result["cov"] == 1.0

    def test_unknown_preset_raises(self):
        spec = {"preset": "NonexistentOccupancy"}
        with pytest.raises(ValueError, match="Unknown preset"):
            resolve_distribution(spec)

    def test_all_presets_in_csv_data(self):
        """Verify all expected occupancy presets exist."""
        expected = [
            "Dwelling", "Hospital", "Hotel room", "Library", "Office", "School",
            "Fast food outlet", "Clothing store", "Restaurant", "Kitchen",
            "Retail unit storage area", "Opening Factor",
        ]
        for name in expected:
            assert name in FIRE_LOAD_PRESETS, f"Missing preset: {name}"


class TestGenerateLhsSamples:
    def _make_config(self, n_samples=50, seed=42):
        return {
            "analysis_method": "parametric",
            "sampling": "lhs",
            "n_samples": n_samples,
            "seed": seed,
            "distributions": {
                "qf": {"preset": "Office"},
                "window_percent": {
                    "preset": "Opening Factor",
                    "transform": "opening_factor",
                },
            },
            "fixed": {"span1": 9, "numbeam": 2},
            "beams": {
                "side_a": {"sec_size": "IPE_500", "fy": 355, "edge": True,
                           "composite": False, "sh_con": 80},
            },
        }

    def test_correct_count(self):
        config = self._make_config(n_samples=100)
        samples = generate_lhs_samples(config)
        assert len(samples) == 100

    def test_fixed_params_present(self):
        config = self._make_config()
        samples = generate_lhs_samples(config)
        for s in samples:
            assert s["span1"] == 9
            assert s["numbeam"] == 2

    def test_beam_config_applied(self):
        config = self._make_config()
        samples = generate_lhs_samples(config)
        for s in samples:
            assert s["SideASecSize"] == "IPE_500"
            assert s["fy1"] == "355"
            assert s["SideAEdgeFlag"] == 1

    def test_seed_reproducibility(self):
        config = self._make_config(seed=42)
        s1 = generate_lhs_samples(config)
        s2 = generate_lhs_samples(config)
        for a, b in zip(s1, s2):
            assert a["qf"] == b["qf"]
            assert a["window_percent"] == b["window_percent"]

    def test_different_seeds_differ(self):
        c1 = self._make_config(seed=42)
        c2 = self._make_config(seed=99)
        s1 = generate_lhs_samples(c1)
        s2 = generate_lhs_samples(c2)
        qf1 = [s["qf"] for s in s1]
        qf2 = [s["qf"] for s in s2]
        assert qf1 != qf2

    def test_sample_index_attached(self):
        config = self._make_config(n_samples=10)
        samples = generate_lhs_samples(config)
        for i, s in enumerate(samples):
            assert s["_sample_index"] == i

    def test_seed_metadata_attached(self):
        config = self._make_config(seed=42)
        samples = generate_lhs_samples(config)
        for s in samples:
            assert s["_seed"] == 42

    def test_defaults_populated(self):
        config = self._make_config()
        samples = generate_lhs_samples(config)
        for s in samples:
            # Defaults should be present for non-sampled params
            assert s["slab_depth"] == 130
            assert s["fck"] == 25
            assert s["method"] == "parametric"

    def test_qf_values_reasonable(self):
        """Fire load values should mostly be positive and in a reasonable range."""
        config = self._make_config(n_samples=200)
        samples = generate_lhs_samples(config)
        qf_values = [s["qf"] for s in samples]
        # Gumbel can produce negative values in extreme tails, but vast majority positive
        assert sum(v > 0 for v in qf_values) > 190
        assert max(qf_values) < 2000  # very unlikely above 2000 for Office

    def test_window_percent_range(self):
        """Window percent should be in [0, 100] after opening factor transform."""
        config = self._make_config(n_samples=200)
        samples = generate_lhs_samples(config)
        wp_values = [s["window_percent"] for s in samples]
        assert all(0 <= v <= 100 for v in wp_values)

    def test_no_seed_uses_none(self):
        """Config without seed should still work (non-reproducible)."""
        config = self._make_config()
        del config["seed"]
        samples = generate_lhs_samples(config)
        assert len(samples) == 50
        for s in samples:
            assert s["_seed"] is None

    def test_geometry_distributions(self):
        """LHS should handle arbitrary geometry params like span1 and slab_depth."""
        config = {
            "analysis_method": "parametric",
            "sampling": "lhs",
            "n_samples": 20,
            "seed": 42,
            "distributions": {
                "span1": {"type": "lognormal", "mean": 9.0, "cov": 0.2},
                "slab_depth": {"type": "lognormal", "mean": 130, "cov": 0.15},
            },
            "fixed": {"span2": 9, "fck": 25},
        }
        samples = generate_lhs_samples(config)
        assert len(samples) == 20
        # span1 should vary
        span1_values = [s["span1"] for s in samples]
        assert len(set(span1_values)) > 1
        # slab_depth should vary
        sd_values = [s["slab_depth"] for s in samples]
        assert len(set(sd_values)) > 1
        # Fixed params preserved
        assert all(s["span2"] == 9 for s in samples)
        assert all(s["fck"] == 25 for s in samples)

    def test_single_distribution(self):
        """LHS should work with just one distribution."""
        config = {
            "analysis_method": "parametric",
            "sampling": "lhs",
            "n_samples": 10,
            "seed": 42,
            "distributions": {
                "Lc": {"type": "lognormal", "mean": 27, "cov": 0.3},
            },
        }
        samples = generate_lhs_samples(config)
        assert len(samples) == 10
        lc_values = [s["Lc"] for s in samples]
        assert len(set(lc_values)) > 1
        assert all(v > 0 for v in lc_values)

    def test_three_plus_distributions(self):
        """LHS should handle 3+ simultaneous distributions."""
        config = {
            "analysis_method": "parametric",
            "sampling": "lhs",
            "n_samples": 30,
            "seed": 42,
            "distributions": {
                "qf": {"preset": "Office"},
                "window_percent": {"preset": "Opening Factor", "transform": "opening_factor"},
                "span1": {"type": "lognormal", "mean": 9.0, "cov": 0.2},
                "slab_depth": {"type": "lognormal", "mean": 130, "cov": 0.15},
            },
            "fixed": {"span2": 9},
        }
        samples = generate_lhs_samples(config)
        assert len(samples) == 30
        # All four should vary
        for param in ["qf", "window_percent", "span1", "slab_depth"]:
            values = [s[param] for s in samples]
            assert len(set(values)) > 1, f"{param} should vary"
        # Fixed preserved
        assert all(s["span2"] == 9 for s in samples)
