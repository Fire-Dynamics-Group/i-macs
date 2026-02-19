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

    def test_two_param_sweep(self):
        config = {
            "analysis_method": "iso",
            "sweep": {"span1": [6, 9], "span2": [6, 9]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 4  # 2 x 2

    def test_three_param_sweep(self):
        config = {
            "analysis_method": "iso",
            "sweep": {
                "span1": [6, 9, 12],
                "slab_depth": [130, 150],
                "fck": [25, 30],
            },
        }
        combos = generate_combinations(config)
        assert len(combos) == 12  # 3 x 2 x 2

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

    def test_large_sweep(self):
        config = {
            "analysis_method": "iso",
            "sweep": {
                "span1": [6, 9, 12],
                "span2": [6, 9, 12],
                "slab_depth": [130, 150, 180],
                "fck": [25, 30, 40],
                "u_sec_size": ["IPE_300", "IPE_400", "IPE_500"],
                "time_limit": [60, 90, 120],
            },
        }
        combos = generate_combinations(config)
        assert len(combos) == 3 * 3 * 3 * 3 * 3 * 3  # 729

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
    def test_grid_mode_default(self):
        """Default (no sampling key) uses grid mode."""
        config = {
            "analysis_method": "iso",
            "sweep": {"span1": [6, 9]},
        }
        combos = generate_combinations(config)
        assert len(combos) == 2
        # Grid mode: no _sample_index
        assert "_sample_index" not in combos[0]

    def test_grid_mode_explicit(self):
        """Explicit sampling: 'grid' uses grid mode."""
        config = {
            "analysis_method": "iso",
            "sampling": "grid",
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
