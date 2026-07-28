"""End-to-end tests that run the real COM engine when available (32-bit Python + MACS+).

These tests are skipped with a clear reason when COM or Data.xml is not available
(e.g. 64-bit Python, MACS+ not installed). Run with:

  pytest macs_automation/tests/test_e2e_real.py -v
  pytest -m e2e -v

To validate your setup end-to-end, use 32-bit Python and ensure MACS+ is installed;
then these tests will run one real calculation and assert on outputs.
"""

import pytest

from macs_automation.tests.conftest import com_and_data_available


def _one_combo(real_data):
    """Build one valid parameter combo from defaults + real Data.xml."""
    from macs_automation.sweep import DEFAULTS, resolve_deck, resolve_mesh

    params = dict(DEFAULTS)
    resolve_deck(params, real_data["decks"])
    resolve_mesh(params, real_data["meshes"])
    return params, real_data["sections"]


@pytest.mark.e2e
@pytest.mark.com
class TestE2ERealRuns:
    """Real COM runs: skipped with clear reason if 64-bit or MACS+ not available."""

    @pytest.fixture
    def real_data(self):
        from macs_automation.data_loader import load_data, DEFAULT_DATA_PATH

        ok, reason = com_and_data_available()
        if not ok:
            pytest.skip(reason)
        return load_data(DEFAULT_DATA_PATH)

    def test_real_single_run(self, real_data):
        """One real _run_single_com call; asserts outputs shape and keys."""
        from macs_automation.app import _run_single_com

        params, sections_db = _one_combo(real_data)
        outputs = _run_single_com(params, sections_db)

        assert "comp_failure" in outputs
        assert "uf_max" in outputs
        assert "time_series" in outputs
        assert "duration_ms" in outputs
        assert len(outputs["time_series"]) > 0
        assert outputs["uf_max"] >= 0
        assert outputs["duration_ms"] > 0

    def test_custom_section_dimensions_drive_the_engine(self, real_data):
        """A custom section is just another sections_db entry, so:

          - one carrying dimensions identical to a catalogue section must give
            an identical result (the custom path is wired through), and
          - one carrying different dimensions must give a different result (the
            dimensions are actually consumed, not silently defaulted).

        Guards the CUSTOM_* path against regressing to a fallback profile —
        _set_beam_data() indexes sections_db directly, so a merge regression
        would surface here rather than as quietly wrong utilisation figures.
        """
        from macs_automation.app import _run_single_com

        params, catalogue_db = _one_combo(real_data)
        reference_id = "UB_457x191x89"
        ref = catalogue_db[reference_id]

        sections_db = dict(catalogue_db)
        sections_db["CUSTOM_TWIN"] = {
            "family": "Custom", "name": "twin (Custom)",
            "h": ref["h"], "b": ref["b"], "tw": ref["tw"], "tf": ref["tf"],
        }
        sections_db["CUSTOM_DISTINCT"] = {
            "family": "Custom", "name": "distinct (Custom)",
            "h": 900.0, "b": 300.0, "tw": 20.0, "tf": 35.0,
        }

        def uf_for(sec_id):
            run_params = dict(params)
            run_params["uSecSize"] = sec_id
            return _run_single_com(run_params, sections_db)["uf_max"]

        catalogue_uf = uf_for(reference_id)
        twin_uf = uf_for("CUSTOM_TWIN")
        distinct_uf = uf_for("CUSTOM_DISTINCT")

        assert twin_uf == pytest.approx(catalogue_uf, rel=1e-12), (
            "custom section with identical dimensions diverged from the catalogue"
        )
        assert distinct_uf != pytest.approx(catalogue_uf, rel=1e-6), (
            "custom dimensions had no effect — engine may be using a default profile"
        )

    def test_sweep_uses_the_custom_section_on_every_run(self, real_data):
        """A batch resolves sections_db once and shares it across every run
        (app.py:745), and section choices stay fixed for the batch. So the whole
        sweep must track a custom section — not just its first run.

        Sweeps span1 rather than qf deliberately: under the ISO 834 curve the
        fire load has no effect, so a qf sweep returns identical results for
        every run and the pairing below would hold even if the section were
        being ignored.
        """
        from macs_automation.app import _run_single_com
        from macs_automation.sweep import (
            generate_combinations, resolve_deck, resolve_mesh,
        )

        _, catalogue_db = _one_combo(real_data)
        reference_id = "UB_457x191x89"
        ref = catalogue_db[reference_id]
        sections_db = dict(catalogue_db)
        sections_db["CUSTOM_TWIN"] = {
            "family": "Custom", "name": "twin (Custom)",
            "h": ref["h"], "b": ref["b"], "tw": ref["tw"], "tf": ref["tf"],
        }

        def sweep_ufs(sec_id):
            combos = generate_combinations({
                "analysis_method": "iso",
                "sweep": {"span1": [7, 8, 9]},
                "fixed": {"span2": 9, "u_sec_size": sec_id},
            })
            results = {}
            for params in combos:
                # The friendly key must survive aliasing to the engine key,
                # otherwise every run would silently fall back to IPE_500.
                assert params["uSecSize"] == sec_id
                resolve_deck(params, real_data["decks"])
                resolve_mesh(params, real_data["meshes"])
                results[params["span1"]] = _run_single_com(params, sections_db)["uf_max"]
            return results

        catalogue = sweep_ufs(reference_id)
        custom = sweep_ufs("CUSTOM_TWIN")

        assert len(set(catalogue.values())) > 1, (
            "sweep produced identical results for every run — the pairing below "
            "would pass even with the section ignored"
        )
        assert custom == catalogue

    def test_real_batch_one_run(self, real_data, tmp_path):
        """One real run through run_batch_with_callback; asserts DB and progress."""
        from macs_automation.runner import run_batch_with_callback
        from macs_automation.db import ResultsDB

        params, sections_db = _one_combo(real_data)
        db_path = tmp_path / "e2e.db"
        db = ResultsDB(db_path)

        progress = run_batch_with_callback(
            [params],
            db,
            sections_db=sections_db,
            batch_id="e2e-one",
            resume=False,
        )

        db.close()

        assert progress.status == "completed"
        assert progress.completed == 1
        assert progress.errors == 0
        assert progress.total == 1

        db2 = ResultsDB(db_path)
        assert db2.get_run_count() == 1
        assert db2.get_successful_run_count() == 1
        rows = db2.get_runs(limit=10)
        db2.close()
        assert len(rows) == 1
        run = rows[0]
        assert run.get("error") is None
        assert run.get("uf_max") is not None
