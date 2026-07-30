"""Tests for the PDF-evidence job wrapper.

The heavy lifting lives in tools/macs_replay and is exercised by its own tests;
what matters here is the bookkeeping the batch page reads: whose job is running,
how far along it is, and that one batch's job is never reported as another's.
"""

import time

import pytest

from macs_automation import pdf_evidence


@pytest.fixture(autouse=True)
def reset_state():
    """Module state is global by design (one machine, one MACS+ at a time)."""
    before = dict(pdf_evidence._state)
    yield
    with pdf_evidence._lock:
        pdf_evidence._state.clear()
        pdf_evidence._state.update(before)


def _set(**kw):
    with pdf_evidence._lock:
        pdf_evidence._state.update(kw)


class TestStatusIsScopedToItsBatch:
    """Regression: the endpoint takes a batch_id but the state is global, so
    every batch page showed whichever job ran last - including its output
    directory and its errors."""

    def test_reports_progress_to_the_batch_that_owns_the_job(self):
        _set(active=True, batch_id="alpha", total=200, completed=50,
             start_time=time.time(), output_dir=r"C:\evidence\alpha")

        st = pdf_evidence.status("alpha")

        assert st["active"] is True
        assert st["completed"] == 50
        assert st["output_dir"] == r"C:\evidence\alpha"

    def test_hides_another_batch_job_from_this_batch(self):
        _set(active=True, batch_id="alpha", total=200, completed=50,
             start_time=time.time(), output_dir=r"C:\evidence\alpha")

        st = pdf_evidence.status("beta")

        assert st["active"] is False
        assert st["completed"] == 0
        assert st["total"] == 0
        assert st["output_dir"] is None

    def test_does_not_pin_another_batch_failure_on_this_one(self):
        _set(active=False, batch_id="alpha", error="seed .frc is unknown",
             completed=0, finished_at=time.time())

        assert pdf_evidence.status("beta")["error"] is None
        assert pdf_evidence.status("alpha")["error"] == "seed .frc is unknown"

    def test_finished_results_stay_visible_to_their_own_batch(self):
        _set(active=False, batch_id="alpha", total=6, completed=6,
             start_time=time.time() - 30, output_dir=r"C:\evidence\alpha",
             finished_at=time.time())

        st = pdf_evidence.status("alpha")

        assert st["completed"] == 6
        assert st["output_dir"] == r"C:\evidence\alpha"

    def test_idle_when_nothing_has_ever_run(self):
        st = pdf_evidence.status("alpha")
        assert st["active"] is False
        assert st["completed"] == 0
        assert st["error"] is None


class TestEta:
    def test_extrapolates_from_completed_runs(self):
        _set(active=True, batch_id="alpha", total=100, completed=10,
             start_time=time.time() - 20)

        st = pdf_evidence.status("alpha")

        # 20s bought 10 runs, so the remaining 90 want ~180s.
        assert st["eta_s"] == pytest.approx(180, abs=5)

    def test_no_estimate_before_the_first_pdf_lands(self):
        _set(active=True, batch_id="alpha", total=100, completed=0,
             start_time=time.time() - 5)

        assert pdf_evidence.status("alpha")["eta_s"] is None


class TestStart:
    def test_refuses_a_second_job_while_one_is_running(self):
        _set(active=True, batch_id="alpha")

        result = pdf_evidence.start("beta", "db.sqlite")

        assert "error" in result
        assert result["batch_id"] == "alpha"


class TestPaths:
    def test_tool_dir_points_at_the_replay_scripts(self):
        assert (pdf_evidence.tool_dir() / "Invoke-MacsReplay.ps1").exists()
        assert (pdf_evidence.tool_dir() / "export_batch.py").exists()

    def test_evidence_root_lives_under_localappdata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert pdf_evidence.evidence_root() == tmp_path / "i-macs" / "pdf_evidence"


class TestPdfCounting:
    def test_ignores_stubs_left_by_a_print_that_never_finished(self, tmp_path):
        (tmp_path / "run-1.pdf").write_bytes(b"%PDF-1.4" + b"x" * 5000)
        (tmp_path / "run-2.pdf").write_bytes(b"%PDF-1.4")  # spooler stub
        (tmp_path / "manifest.json").write_text("{}")

        assert pdf_evidence._count_pdfs(tmp_path) == 1
