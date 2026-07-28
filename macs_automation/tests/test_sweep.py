"""Tests for sweep.py — parameter sweep generator."""

import pytest
import yaml

from macs_automation.sweep import (
    DEFAULTS,
    generate_combinations,
    load_config,
    resolve_deck,
    resolve_mesh,
)


class TestWindowPercentFractionGuard:
    """window_percent supplied as fractions (all <= 1) is a unit error.

    The legacy sampler's opening_perc files store fractions in [0, 1]; the old
    GUI clicker converted at type-in with max(g, 0.05) * 100. Feeding the raw
    fractions into a batch gives ~1% openings and near-ambient fires, so the
    config must be rejected at submission."""

    def test_paired_all_fraction_values_rejected(self):
        config = {
            "analysis_method": "parametric",
            "sampling": "paired",
            "sweep": {
                "qf": [249.3, 502.0, 359.6],
                "window_percent": [0.8764, 0.9060, 0.8833],
            },
        }
        with pytest.raises(ValueError, match="fraction"):
            generate_combinations(config)

    def test_error_message_says_multiply_by_100(self):
        config = {
            "analysis_method": "parametric",
            "sweep": {"window_percent": [0.5, 0.9]},
        }
        with pytest.raises(ValueError, match="multiply by 100"):
            generate_combinations(config)

    def test_paired_percent_values_accepted(self):
        config = {
            "analysis_method": "parametric",
            "sweep": {"qf": [300, 500], "window_percent": [50.0, 87.6]},
        }
        combos = generate_combinations(config)
        assert [c["window_percent"] for c in combos] == [50.0, 87.6]

    def test_mixed_array_with_occasional_sub1_values_accepted(self):
        """The opening-factor transform can legitimately emit the odd sub-1%
        row; only an array consisting entirely of values <= 1 is fraction-like."""
        config = {
            "analysis_method": "parametric",
            "sweep": {"window_percent": [0.23, 55.0, 95.0]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 3

    def test_fixed_fraction_scalar_rejected(self):
        config = {
            "analysis_method": "parametric",
            "fixed": {"window_percent": 0.9},
        }
        with pytest.raises(ValueError, match="fraction"):
            generate_combinations(config)

    def test_fixed_percent_scalar_accepted(self):
        config = {
            "analysis_method": "parametric",
            "fixed": {"window_percent": 90},
        }
        combos = generate_combinations(config)
        assert combos[0]["window_percent"] == 90

    def test_lhs_config_with_fixed_fraction_rejected(self):
        """The guard must fire before the LHS dispatch too."""
        config = {
            "analysis_method": "parametric",
            "sampling": "lhs",
            "n_samples": 5,
            "seed": 1,
            "distributions": {"qf": {"preset": "Office"}},
            "fixed": {"window_percent": 0.9},
        }
        with pytest.raises(ValueError, match="fraction"):
            generate_combinations(config)


class TestDefaults:
    def test_default_method_is_parametric(self):
        """The fire analysis method defaults to parametric."""
        assert DEFAULTS["method"] == "parametric"


class TestGenerateCombinations:
    def test_no_sweep_returns_defaults(self):
        config = {"analysis_method": "iso"}
        combos = generate_combinations(config)
        assert len(combos) == 1
        assert combos[0]["span1"] == 9.0
        assert combos[0]["method"] == "iso"

    def test_single_param_sweep(self):
        config = {
            "analysis_method": "iso",
            "sweep": {"span1": [6, 9, 12]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 3
        spans = [c["span1"] for c in combos]
        assert spans == [6, 9, 12]

    def test_fixed_overrides(self):
        config = {
            "analysis_method": "iso",
            "fixed": {"numbeam": 3, "conc_type": "LW"},
        }
        combos = generate_combinations(config)
        assert len(combos) == 1
        assert combos[0]["numbeam"] == 3
        assert combos[0]["conc_type"] == "LW"

    def test_sweep_with_fixed(self):
        config = {
            "analysis_method": "iso",
            "sweep": {"span1": [6, 9]},
            "fixed": {"numbeam": 3},
        }
        combos = generate_combinations(config)
        assert len(combos) == 2
        for c in combos:
            assert c["numbeam"] == 3

    def test_u_sec_size_alias(self):
        config = {
            "analysis_method": "iso",
            "sweep": {"u_sec_size": ["IPE_300", "IPE_500"]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 2
        assert combos[0]["uSecSize"] == "IPE_300"
        assert combos[1]["uSecSize"] == "IPE_500"

    def test_beam_configuration(self):
        config = {
            "analysis_method": "iso",
            "beams": {
                "side_a": {"sec_size": "IPE_300", "fy": 275, "edge": True,
                           "composite": False, "sh_con": 60},
            },
        }
        combos = generate_combinations(config)
        assert combos[0]["SideASecSize"] == "IPE_300"
        assert combos[0]["fy1"] == "275"
        assert combos[0]["SideAEdgeFlag"] == 1
        assert combos[0]["SideACompoFlag"] == 0
        assert combos[0]["SideAsh_con"] == 60

    def test_analysis_method_parametric(self):
        config = {"analysis_method": "parametric"}
        combos = generate_combinations(config)
        assert combos[0]["method"] == "parametric"

    def test_defaults_populated(self):
        config = {"analysis_method": "iso"}
        combos = generate_combinations(config)
        p = combos[0]
        # Check some key defaults from MACS+ Defaults.xml
        assert p["slab_depth"] == 130
        assert p["fck"] == 25
        assert p["mesh_strength"] == 500
        assert p["lead_var_act"] == 5.0
        assert p["ush_con"] == 80


class TestResolveDeck:
    def test_resolves_deck_properties(self):
        decks_db = {
            "T14": {
                "deck_type": "T", "deck_depth": 58.0, "deck_trug": 207.0,
                "deck_top": 106.0, "deck_bot": 62.0, "deck_stiff_height": 0.0,
                "name": "COFRAPLUS 60",
            }
        }
        params = {"DeckId": "T14"}
        resolve_deck(params, decks_db)
        assert params["deck_depth"] == 58.0
        assert params["DeckName"] == "COFRAPLUS 60"

    def test_unknown_deck_no_change(self):
        params = {"DeckId": "UNKNOWN"}
        resolve_deck(params, {})
        assert "deck_depth" not in params


class TestResolveMesh:
    def test_resolves_mesh_areas(self):
        meshes_db = {
            "A393": {"mainArea": 393.0, "transArea": 393.0, "min_mesh_dia": 10.0,
                     "max_mesh_dia": 10.0, "name": "A393"},
        }
        params = {"mesh_type": "A393"}
        resolve_mesh(params, meshes_db)
        assert params["mesh_area_max"] == 393.0
        assert params["mesh_area_min"] == 393.0

    def test_unknown_mesh_no_change(self):
        params = {"mesh_type": "UNKNOWN"}
        resolve_mesh(params, {})
        assert "mesh_area_max" not in params


class TestLoadConfig:
    def test_loads_yaml(self, tmp_path):
        config_file = tmp_path / "test.yaml"
        config_file.write_text(yaml.dump({
            "analysis_method": "iso",
            "sweep": {"span1": [6, 9]},
        }))
        config = load_config(config_file)
        assert config["analysis_method"] == "iso"
        assert config["sweep"]["span1"] == [6, 9]


class TestSamplingDispatch:
    def test_paired_is_default(self):
        """Default (no sampling key) uses paired mode."""
        config = {
            "analysis_method": "iso",
            "sweep": {"span1": [6, 9]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 2
        assert "_sample_index" not in combos[0]

    def test_lhs_mode_dispatches(self):
        """sampling: 'lhs' dispatches to LHS generator."""
        config = {
            "analysis_method": "parametric",
            "sampling": "lhs",
            "n_samples": 10,
            "seed": 42,
            "distributions": {
                "qf": {"preset": "Office"},
            },
        }
        combos = generate_combinations(config)
        assert len(combos) == 10
        assert "_sample_index" in combos[0]
        assert combos[0]["_seed"] == 42


class TestSweepWithFireParams:
    """Verify sweep handles fire/loading params (not just geometry)."""

    def test_sweep_combustion_factor(self):
        config = {
            "analysis_method": "parametric",
            "sweep": {
                "combustion_factor": [0.6, 0.8, 1.0],
            },
        }
        combos = generate_combinations(config)
        assert len(combos) == 3
        cf_values = [c["combustion_factor"] for c in combos]
        assert cf_values == [0.6, 0.8, 1.0]


class TestPairedMode:
    """Paired mode is the default — sweep arrays zip row-wise."""

    def test_zips_two_arrays(self):
        config = {
            "analysis_method": "parametric",
            "sweep": {
                "qf": [300, 500, 700],
                "window_percent": [50, 80, 95],
            },
        }
        combos = generate_combinations(config)
        assert len(combos) == 3
        assert [c["qf"] for c in combos] == [300, 500, 700]
        assert [c["window_percent"] for c in combos] == [50, 80, 95]

    def test_explicit_sampling_key(self):
        config = {
            "analysis_method": "iso",
            "sampling": "paired",
            "sweep": {"qf": [300, 500]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 2

    def test_rejects_unequal_lengths(self):
        config = {
            "analysis_method": "parametric",
            "sweep": {
                "qf": [300, 500, 700],
                "window_percent": [50, 80],
            },
        }
        with pytest.raises(ValueError) as exc:
            generate_combinations(config)
        msg = str(exc.value)
        assert "qf" in msg
        assert "window_percent" in msg
        assert "3" in msg
        assert "2" in msg

    def test_with_fixed(self):
        config = {
            "analysis_method": "iso",
            "sweep": {"qf": [300, 500]},
            "fixed": {"span1": 7.3, "span2": 7.48},
        }
        combos = generate_combinations(config)
        assert len(combos) == 2
        for c in combos:
            assert c["span1"] == 7.3
            assert c["span2"] == 7.48

    def test_three_params(self):
        config = {
            "analysis_method": "parametric",
            "sweep": {
                "qf": [100, 200, 300, 400],
                "window_percent": [10, 20, 30, 40],
                "Bfac": [500, 700, 900, 1100],
            },
        }
        combos = generate_combinations(config)
        assert len(combos) == 4
        assert combos[0]["qf"] == 100
        assert combos[0]["window_percent"] == 10
        assert combos[0]["Bfac"] == 500
        assert combos[3]["qf"] == 400
        assert combos[3]["Bfac"] == 1100

    def test_single_value_per_param(self):
        config = {
            "analysis_method": "iso",
            "sweep": {"qf": [500], "window_percent": [80]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 1
        assert combos[0]["qf"] == 500
        assert combos[0]["window_percent"] == 80
