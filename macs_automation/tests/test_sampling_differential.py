"""Differential tests: the i-macs sampler vs the legacy TMA script.

The oracle is macs_automation/tests/legacy_tma_reference.py — a frozen verbatim
copy of the team's sampler (see its docstring for provenance). Both sides are fed
the same uniform matrix, so any divergence is in the transforms, not the RNG.

Key fact these tests pin down: the legacy script's Gumbel branch was dead code
(``str.split`` truncated the CSV label before an ``== "Gumbel type 1"`` check),
so every legacy batch — including the 10k Atlantic Park / Daedalus Office runs —
was sampled from the LOGNORMAL branch. i-macs dispatches on the preset's labelled
type, so:

- lognormal-labelled presets (8): i-macs matches actual legacy output exactly;
- gumbel-labelled presets (6): i-macs matches the formula the legacy script
  *intended* (its dead branch), and intentionally diverges from what the legacy
  script actually produced.

Also covered here (gaps noted in the validation-strategy handoff): the LHS
stratification property, and the opening-factor transform seam (x100 scaling,
no 5% floor in the sampler — FRACOF floors internally, see
test_sweep_path_oracle.py::test_sub5pct_opening_floored_like_macs).
"""

import csv
import io

import numpy as np
import pytest

from macs_automation.sampling import (
    FIRE_LOAD_PRESETS,
    generate_lhs_samples,
    gumbel_ppf,
    lognormal_ppf,
    opening_factor_transform,
)
from macs_automation.tests import legacy_tma_reference as legacy

GUMBEL_PRESETS = [n for n, s in FIRE_LOAD_PRESETS.items() if s["type"] == "gumbel"]
LOGNORMAL_PRESETS = [n for n, s in FIRE_LOAD_PRESETS.items() if s["type"] == "lognormal"]

# mean * cov -> std_dev -> std_dev / mean does not round-trip bitwise for this
# preset (9920 * 0.86), so the legacy lognormal branch sees a cov one ulp off
# and exact equality is unattainable there.
NON_ROUNDTRIP_PRESETS = {"Manufacturing and storage of combustible goods (>150 kg/m2)"}


@pytest.fixture
def u():
    """A shared uniform matrix, dense in both tails."""
    rng = np.random.default_rng(20260728)
    body = rng.uniform(1e-6, 1 - 1e-6, size=5000)
    tails = np.array([1e-6, 1e-4, 1e-3, 0.5, 1 - 1e-3, 1 - 1e-4, 1 - 1e-6])
    return np.concatenate([body, tails])


def _assert_equal(result, expected, preset_name):
    if preset_name in NON_ROUNDTRIP_PRESETS:
        np.testing.assert_allclose(result, expected, rtol=1e-12, atol=0)
    else:
        np.testing.assert_array_equal(result, expected)


def _legacy_csv_rows():
    return list(csv.DictReader(io.StringIO(legacy.FIRE_LOAD_DENSITY_CSV)))


class TestPresetTableMatchesLegacyCsv:
    def test_same_occupancy_set(self):
        csv_names = [r["Occupancy"] for r in _legacy_csv_rows()]
        assert sorted(csv_names) == sorted(FIRE_LOAD_PRESETS)
        assert len(csv_names) == 14

    def test_mean_cov_and_labelled_type_match(self):
        """i-macs preset types must match the CSV's full label (not the
        truncated one the legacy dispatch actually compared against)."""
        label_map = {"Gumbel type 1": "gumbel", "Log-normal": "lognormal"}
        for row in _legacy_csv_rows():
            preset = FIRE_LOAD_PRESETS[row["Occupancy"]]
            assert preset["mean"] == float(row["Mean Fire Density"]), row["Occupancy"]
            assert preset["cov"] == float(row["Coefficient of Variation"]), row["Occupancy"]
            assert preset["type"] == label_map[row["Distribution"].strip()], row["Occupancy"]


class TestFormulaDifferential:
    """i-macs transforms vs the legacy formulas, same uniforms in."""

    @pytest.mark.parametrize("name", LOGNORMAL_PRESETS)
    def test_lognormal_presets_match_legacy_behaviour(self, u, name):
        """For lognormal-labelled presets the legacy dispatch lands in the
        lognormal branch, so this is equality with actual legacy output."""
        spec = FIRE_LOAD_PRESETS[name]
        result = lognormal_ppf(u, spec["mean"], spec["cov"])
        expected = legacy.get_distribution(u, name)
        _assert_equal(result, expected, name)

    @pytest.mark.parametrize("name", GUMBEL_PRESETS)
    def test_gumbel_presets_match_legacy_intended_formula(self, u, name):
        """i-macs gumbel_ppf must equal the legacy script's (dead) Gumbel branch."""
        spec = FIRE_LOAD_PRESETS[name]
        result = gumbel_ppf(u, spec["mean"], spec["cov"])
        expected = legacy.legacy_gumbel_formula(u, spec["mean"], spec["mean"] * spec["cov"])
        _assert_equal(result, expected, name)


class TestLegacyDispatchBug:
    """Pin down what the legacy script actually did, so nobody 'revalidates'
    i-macs against the 10k corpora expecting Gumbel fire loads."""

    @pytest.mark.parametrize("name", GUMBEL_PRESETS)
    def test_legacy_sampled_gumbel_occupancies_from_lognormal_branch(self, u, name):
        _, mean, std_dev = legacy.read_fld_data(name)
        actual = legacy.get_distribution(u, name)
        np.testing.assert_array_equal(actual, legacy.legacy_lognormal_formula(u, mean, std_dev))
        assert not np.allclose(actual, legacy.legacy_gumbel_formula(u, mean, std_dev), rtol=1e-3)

    @pytest.mark.parametrize("name", GUMBEL_PRESETS)
    def test_imacs_intentionally_diverges_from_actual_legacy_output(self, u, name):
        spec = FIRE_LOAD_PRESETS[name]
        result = gumbel_ppf(u, spec["mean"], spec["cov"])
        legacy_actual = legacy.get_distribution(u, name)
        assert not np.allclose(result, legacy_actual, rtol=1e-3)


class TestOpeningFactorDifferential:
    def test_non_resampled_entries_exact(self):
        """For raw values <= 1 (no resampling) i-macs must equal legacy x 100.

        The x100 seam: the legacy sampler returned fractions; the GUI clicker
        scaled at type-in (exe_script.py: ``max(g, 0.05) * 100``). i-macs bakes
        the x100 into the transform.
        """
        raw = lognormal_ppf(np.linspace(0.001, 0.999, 500), mean=0.2, cov=1.0)
        raw = raw[raw <= 1]
        assert len(raw) > 400  # sanity: most Opening Factor draws are <= 1
        rng = np.random.default_rng(7)
        result = opening_factor_transform(raw.copy(), rng)
        expected = legacy.factorise_opening_percentage(raw.copy()) * 100
        np.testing.assert_array_equal(result, expected)

    def test_resampled_entries_with_shared_rng(self, monkeypatch):
        """Inject the same RNG stream into both implementations so the
        uniform(0,1) resampling of values > 1 is comparable point-for-point."""
        raw = np.array([0.5, 1.5, 0.2, 2.0, 0.9, 3.7, 1.0001])
        result = opening_factor_transform(raw.copy(), np.random.default_rng(11))
        monkeypatch.setattr(np.random, "uniform", np.random.default_rng(11).uniform)
        expected = legacy.factorise_opening_percentage(raw.copy()) * 100
        np.testing.assert_array_equal(result, expected)

    def test_no_five_percent_floor_in_sampler(self):
        """The legacy clicker floored glazing at 5% when typing into the GUI.
        The i-macs sampler deliberately does not — FRACOF applies the floor
        internally (test_sweep_path_oracle.py proves the low side)."""
        rng = np.random.default_rng(3)
        result = opening_factor_transform(np.array([0.999]), rng)
        assert result[0] == pytest.approx(0.1, rel=1e-9)
        assert result[0] < 5


class TestLhsStratification:
    def test_one_sample_per_stratum_per_dimension(self):
        """The defining LHS property: n samples -> exactly one per 1/n stratum
        in every sampled dimension. Recovered by mapping outputs back through
        the appropriate CDF (transforms are monotonic)."""
        from scipy.stats import gumbel_l, lognorm

        n = 200
        config = {
            "analysis_method": "parametric",
            "sampling": "lhs",
            "n_samples": n,
            "seed": 99,
            "distributions": {
                "qf": {"preset": "Office"},
                "span1": {"type": "lognormal", "mean": 9.0, "cov": 0.2},
            },
        }
        samples = generate_lhs_samples(config)

        qf = np.array([s["qf"] for s in samples])
        mean, cov = 420, 0.3
        scale = mean * cov * np.sqrt(6) / np.pi
        loc = mean + np.euler_gamma * scale
        u_qf = gumbel_l.cdf(qf, loc, scale)

        span1 = np.array([s["span1"] for s in samples])
        sln = np.sqrt(np.log(1 + 0.2**2))
        mln = np.log(9.0) - 0.5 * sln**2
        u_span1 = lognorm.cdf(span1, sln, 0, np.exp(mln))

        for u_back, label in [(u_qf, "qf"), (u_span1, "span1")]:
            counts, _ = np.histogram(u_back, bins=n, range=(0.0, 1.0))
            assert (counts == 1).all(), f"{label}: LHS stratification violated"
