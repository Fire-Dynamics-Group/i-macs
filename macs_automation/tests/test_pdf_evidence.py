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


class TestPause:
    """A 10k batch is an 11-hour job on a machine somebody else needs. Stopping
    has to be graceful: the runner owns the default printer and a live MACS+
    instance, and only tidies both up if it exits through its own finally."""

    @pytest.fixture(autouse=True)
    def _evidence_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        return tmp_path

    def test_asks_the_runner_to_stop_after_the_current_run(self):
        _set(active=True, batch_id="alpha", total=200, completed=12)

        result = pdf_evidence.stop("alpha")

        assert result.get("stopping") is True
        assert pdf_evidence.stop_file("alpha").exists()

    def test_reports_that_it_is_stopping(self):
        _set(active=True, batch_id="alpha", total=200, completed=12)
        pdf_evidence.stop("alpha")

        assert pdf_evidence.status("alpha")["stopping"] is True

    def test_will_not_stop_a_job_belonging_to_another_batch(self):
        _set(active=True, batch_id="alpha")

        result = pdf_evidence.stop("beta")

        assert "error" in result
        assert not pdf_evidence.stop_file("alpha").exists()

    def test_nothing_to_stop_when_idle(self):
        assert "error" in pdf_evidence.stop("alpha")

    def test_a_stale_stop_signal_does_not_kill_the_next_run(self):
        """Otherwise resuming after a pause stops again immediately."""
        stop = pdf_evidence.stop_file("alpha")
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("")

        pdf_evidence.clear_stop("alpha")

        assert not stop.exists()


class TestResume:
    def test_remembers_the_sample_so_a_resume_covers_the_same_runs(self):
        """Resuming with a different sample would export a different set of
        runs, and the half-finished PDFs would no longer line up with it."""
        _set(active=False, batch_id="alpha", total=200, completed=12, sample=200)

        assert pdf_evidence.status("alpha")["sample"] == 200

    def test_a_partly_done_job_is_resumable(self):
        _set(active=False, batch_id="alpha", total=200, completed=12,
             finished_at=time.time())

        assert pdf_evidence.status("alpha")["resumable"] is True

    def test_a_finished_job_is_not_resumable(self):
        _set(active=False, batch_id="alpha", total=200, completed=200,
             finished_at=time.time())

        assert pdf_evidence.status("alpha")["resumable"] is False

    def test_another_batch_is_never_resumable_from_this_one(self):
        _set(active=False, batch_id="alpha", total=200, completed=12,
             finished_at=time.time())

        assert pdf_evidence.status("beta")["resumable"] is False


class TestSurvivingARestart:
    """Closing the app kills the runner, and the PDFs already written are the
    only record of how far it got. The job's parameters have to outlive the
    process too, or resuming means re-picking the folder and the seed by hand.
    """

    @pytest.fixture(autouse=True)
    def _evidence_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        return tmp_path

    def _wrote(self, batch_id, n, out_dir=None):
        pdfs = pdf_evidence.resolve_out_dir(batch_id, out_dir) / "pdfs"
        pdfs.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (pdfs / f"run{i}.pdf").write_bytes(b"%PDF" + b"x" * 5000)

    def test_offers_to_resume_a_job_the_process_never_saw(self):
        pdf_evidence.remember_job("alpha", sample=200, out_dir=None, seed=None, total=200)
        self._wrote("alpha", 40)

        st = pdf_evidence.status("alpha")

        assert st["resumable"] is True
        assert st["total"] == 200
        assert st["completed"] == 40

    def test_counts_the_pdfs_rather_than_trusting_the_record(self):
        """The record is written once; the runner keeps going after it."""
        pdf_evidence.remember_job("alpha", sample=200, out_dir=None, seed=None, total=200)
        self._wrote("alpha", 137)

        assert pdf_evidence.status("alpha")["completed"] == 137

    def test_remembers_the_seed_and_folder_so_a_resume_repeats_the_job(self, tmp_path):
        chosen = tmp_path / "Evidence"
        pdf_evidence.remember_job(
            "alpha", sample=200, out_dir=str(chosen), seed=r"D:\jobs\Cal.frc", total=200
        )
        self._wrote("alpha", 12, out_dir=str(chosen))

        st = pdf_evidence.status("alpha")

        assert st["sample"] == 200
        assert st["seed"] == r"D:\jobs\Cal.frc"
        assert st["job_dir"] == str(chosen)

    def test_a_finished_job_is_not_offered_as_resumable(self):
        pdf_evidence.remember_job("alpha", sample=None, out_dir=None, seed=None, total=6)
        self._wrote("alpha", 6)

        assert pdf_evidence.status("alpha")["resumable"] is False

    def test_a_batch_that_never_ran_is_idle(self):
        assert pdf_evidence.status("alpha")["resumable"] is False
        assert pdf_evidence.status("alpha")["total"] == 0

    def test_a_live_job_wins_over_the_record(self):
        pdf_evidence.remember_job("alpha", sample=200, out_dir=None, seed=None, total=200)
        _set(active=True, batch_id="alpha", total=200, completed=99,
             start_time=time.time())

        st = pdf_evidence.status("alpha")

        assert st["active"] is True
        assert st["completed"] == 99


class TestReset:
    """Clearing a job out so the batch can be started fresh. The PDFs are hours
    of work, so discarding them is opt-in and never a side effect."""

    @pytest.fixture(autouse=True)
    def _evidence_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        return tmp_path

    def _job(self, batch_id="alpha", n=3, out_dir=None, total=10):
        pdf_evidence.remember_job(batch_id, sample=None, out_dir=out_dir,
                                  seed=None, total=total)
        pdfs = pdf_evidence.resolve_out_dir(batch_id, out_dir) / "pdfs"
        pdfs.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (pdfs / f"run{i}.pdf").write_bytes(b"%PDF" + b"x" * 5000)
        return pdfs

    def test_forgets_the_job_so_the_batch_starts_fresh(self):
        self._job()

        pdf_evidence.reset("alpha")

        st = pdf_evidence.status("alpha")
        assert st["resumable"] is False
        assert st["total"] == 0

    def test_keeps_the_pdfs_by_default(self):
        pdfs = self._job(n=3)

        pdf_evidence.reset("alpha")

        assert len(list(pdfs.glob("*.pdf"))) == 3

    def test_discards_the_pdfs_when_asked(self):
        pdfs = self._job(n=3)

        result = pdf_evidence.reset("alpha", delete_pdfs=True)

        assert result["deleted"] == 3
        assert list(pdfs.glob("*.pdf")) == []

    def test_only_ever_deletes_pdfs(self):
        """The output folder can be one the user chose, so nothing else in it
        is ours to remove - and the folder itself stays put."""
        pdfs = self._job(n=1)
        (pdfs / "notes.txt").write_text("keep me")
        (pdfs / "_replay_log.csv").write_text("name,run_id")

        pdf_evidence.reset("alpha", delete_pdfs=True)

        assert (pdfs / "notes.txt").exists()
        assert (pdfs / "_replay_log.csv").exists()
        assert pdfs.exists()

    def test_finds_pdfs_in_a_chosen_folder(self, tmp_path):
        chosen = tmp_path / "Evidence"
        pdfs = self._job(out_dir=str(chosen), n=2)

        assert pdf_evidence.reset("alpha", delete_pdfs=True)["deleted"] == 2
        assert list(pdfs.glob("*.pdf")) == []

    def test_refuses_while_the_job_is_still_running(self):
        pdfs = self._job(n=3)
        _set(active=True, batch_id="alpha")

        result = pdf_evidence.reset("alpha", delete_pdfs=True)

        assert "error" in result
        assert len(list(pdfs.glob("*.pdf"))) == 3

    def test_does_not_disturb_a_job_running_for_another_batch(self):
        self._job("alpha")
        _set(active=True, batch_id="beta")

        assert pdf_evidence.reset("alpha").get("reset") is True

    def test_resetting_something_that_never_ran_is_harmless(self):
        assert pdf_evidence.reset("alpha").get("reset") is True

    def test_clears_leftover_in_memory_state_too(self):
        self._job()
        _set(active=False, batch_id="alpha", total=10, completed=3,
             finished_at=time.time())

        pdf_evidence.reset("alpha")

        assert pdf_evidence.status("alpha")["total"] == 0


class TestFinishMessage:
    """What the panel is told when the runner exits."""

    def test_a_clean_finish_says_nothing(self):
        assert pdf_evidence._finish_message(0, False, 10, 10, "") is None

    # Regression: pausing showed "replay exited 1 (755/10000 done)" in red.
    # Stopping on request is the feature working, not a failure.
    def test_a_requested_stop_is_not_a_failure(self):
        assert pdf_evidence._finish_message(1, True, 755, 10000, "") is None

    def test_a_real_failure_says_how_far_it_got(self):
        msg = pdf_evidence._finish_message(1, False, 40, 200, "")
        assert msg is not None
        assert "40/200" in msg

    def test_prefers_what_the_runner_actually_said(self):
        msg = pdf_evidence._finish_message(1, False, 0, 10, "printer 'MACS-PDF' not found")
        assert "MACS-PDF" in msg


class TestEtaAfterTheJobEnds:
    def test_no_countdown_once_the_job_is_over(self):
        """A finished job kept reporting ~17 h remaining."""
        _set(active=False, batch_id="alpha", total=10000, completed=755,
             start_time=time.time() - 5000, finished_at=time.time())

        assert pdf_evidence.status("alpha")["eta_s"] is None

    def test_still_counts_down_while_running(self):
        _set(active=True, batch_id="alpha", total=100, completed=10,
             start_time=time.time() - 20)

        assert pdf_evidence.status("alpha")["eta_s"] == pytest.approx(180, abs=5)


class TestOutputLocation:
    """10k runs is ~4.2 GB, which often wants a different drive from C:."""

    def test_defaults_to_localappdata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

        assert pdf_evidence.resolve_out_dir("alpha") == (
            tmp_path / "i-macs" / "pdf_evidence" / "alpha"
        )

    def test_uses_a_chosen_folder(self, tmp_path):
        chosen = tmp_path / "Evidence"

        assert pdf_evidence.resolve_out_dir("alpha", str(chosen)) == chosen

    def test_the_stop_signal_follows_the_chosen_folder(self, tmp_path):
        chosen = tmp_path / "Evidence"
        _set(active=True, batch_id="alpha", job_dir=str(chosen))

        assert pdf_evidence.stop_file("alpha") == chosen / "pdfs" / "_stop"


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

    def test_counts_a_large_directory(self, tmp_path):
        for i in range(300):
            (tmp_path / f"run{i}.pdf").write_bytes(b"%PDF" + b"x" * 2000)

        assert pdf_evidence._count_pdfs(tmp_path) == 300

    def test_missing_directory_is_zero_not_an_error(self, tmp_path):
        assert pdf_evidence._count_pdfs(tmp_path / "nope") == 0


class TestProgressPolling:
    """Counting is a progress bar, not the job. Re-listing the output every two
    seconds costs more as the batch grows, and that disk traffic competes with
    the single-threaded print spooler that is doing the actual work."""

    def test_polls_briskly_at_the_start(self):
        assert pdf_evidence._poll_interval(0) == 2.0

    def test_backs_off_as_the_directory_fills(self):
        assert pdf_evidence._poll_interval(5000) > pdf_evidence._poll_interval(100)

    def test_never_backs_off_so_far_that_progress_looks_stuck(self):
        assert pdf_evidence._poll_interval(10_000_000) <= 15.0
