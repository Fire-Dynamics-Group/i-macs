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
