"""Worker mode (issue #44) — the backend-independent core.

These tests cover the job executor (resume from completed sample indices,
chunked result reporting, per-sample error capture, cooperative stop) and the
polling worker loop against a fake JobsClient. The HTTP client that talks to
the central backend is deliberately absent — it lands with
backendForNextApp#23 — so everything here runs without a live network, per the
issue's acceptance criteria.
"""
import pytest

from macs_automation.worker import (
    HttpJobsClient,
    JobLease,
    Worker,
    execute_job,
    make_com_run_one,
)


# A paired sweep over qf — five deterministic combinations whose order is the
# resume index. Same spec shape POST /api/sweeps accepts ("one job format,
# two executors").
def paired_spec(n: int = 5) -> dict:
    return {
        "analysis_method": "iso",
        "sweep": {"qf": [100 * (i + 1) for i in range(n)]},
        "fixed": {"span1": 9},
    }


def make_run_one(executed: list, fail_on_qf: set | None = None):
    def run_one(params: dict) -> dict:
        qf = params["qf"]
        if fail_on_qf and qf in fail_on_qf:
            raise RuntimeError("COM bridge died")
        executed.append(qf)
        return {"uf_max": qf / 1000.0}

    return run_one


class TestExecuteJob:
    def test_executes_only_the_remaining_sample_indices(self):
        executed: list = []
        reports: list = []
        finished = execute_job(
            paired_spec(),
            completed_indices={0, 2},
            run_one=make_run_one(executed),
            report=reports.append,
        )
        assert finished is True
        assert executed == [200, 400, 500]  # indices 1, 3, 4
        rows = [row for chunk in reports for row in chunk]
        assert [r["sample_index"] for r in rows] == [1, 3, 4]
        assert all("outputs" in r for r in rows)

    def test_reports_in_chunks_and_flushes_the_remainder(self):
        reports: list = []
        execute_job(
            paired_spec(5),
            completed_indices=set(),
            run_one=make_run_one([]),
            report=reports.append,
            chunk_size=2,
        )
        assert [len(chunk) for chunk in reports] == [2, 2, 1]

    def test_records_a_per_sample_error_and_keeps_going(self):
        executed: list = []
        reports: list = []
        finished = execute_job(
            paired_spec(),
            completed_indices=set(),
            run_one=make_run_one(executed, fail_on_qf={300}),
            report=reports.append,
        )
        assert finished is True
        assert 300 not in executed
        rows = [row for chunk in reports for row in chunk]
        errored = [r for r in rows if r.get("error")]
        assert len(errored) == 1
        assert errored[0]["sample_index"] == 2
        assert errored[0]["error"] == "RuntimeError: COM bridge died"
        assert len([r for r in rows if "outputs" in r]) == 4

    def test_result_rows_carry_the_params_that_produced_them(self):
        reports: list = []
        execute_job(
            paired_spec(2),
            completed_indices=set(),
            run_one=make_run_one([]),
            report=reports.append,
        )
        rows = [row for chunk in reports for row in chunk]
        assert rows[0]["params"]["qf"] == 100
        assert rows[1]["params"]["qf"] == 200

    def test_stop_flushes_what_completed_and_reports_unfinished(self):
        reports: list = []
        # Stop after the first chunk has been reported.
        finished = execute_job(
            paired_spec(5),
            completed_indices=set(),
            run_one=make_run_one([]),
            report=reports.append,
            chunk_size=2,
            should_stop=lambda: len(reports) >= 1,
        )
        assert finished is False
        # First chunk reported before the stop took effect; nothing lost.
        rows = [row for chunk in reports for row in chunk]
        assert [r["sample_index"] for r in rows] == [0, 1]

    def test_nothing_left_to_do_completes_without_running(self):
        executed: list = []
        reports: list = []
        finished = execute_job(
            paired_spec(3),
            completed_indices={0, 1, 2},
            run_one=make_run_one(executed),
            report=reports.append,
        )
        assert finished is True
        assert executed == []
        assert reports == []

    def test_invalid_spec_raises(self):
        bad = {"sweep": {"qf": [1, 2], "span1": [9]}}  # unequal paired lengths
        with pytest.raises(ValueError):
            execute_job(
                bad,
                completed_indices=set(),
                run_one=make_run_one([]),
                report=lambda _: None,
            )


class FakeClient:
    """In-memory JobsClient: one queued job, records every interaction."""

    def __init__(self, lease: JobLease | None):
        self.lease = lease
        self.claims = 0
        self.chunks: list = []
        self.completed: list = []
        self.failed: list = []

    def claim_job(self, worker_id: str):
        self.claims += 1
        lease, self.lease = self.lease, None
        return lease

    def report_chunk(self, lease: JobLease, results: list) -> None:
        self.chunks.append((lease.job_id, results))

    def complete_job(self, lease: JobLease) -> None:
        self.completed.append(lease.job_id)

    def fail_job(self, lease: JobLease, error: str) -> None:
        self.failed.append((lease.job_id, error))


def make_lease(spec: dict, completed=frozenset()) -> JobLease:
    return JobLease(
        job_id="job-1",
        lease_token="tok-1",
        spec=spec,
        completed_indices=frozenset(completed),
    )


class TestWorker:
    def test_run_once_claims_executes_reports_and_completes(self):
        client = FakeClient(make_lease(paired_spec(3)))
        worker = Worker(client, make_run_one([]), chunk_size=2)
        assert worker.run_once() is True
        assert client.completed == ["job-1"]
        assert client.failed == []
        rows = [row for _, chunk in client.chunks for row in chunk]
        assert [r["sample_index"] for r in rows] == [0, 1, 2]

    def test_run_once_returns_false_when_no_job_is_available(self):
        client = FakeClient(None)
        worker = Worker(client, make_run_one([]))
        assert worker.run_once() is False
        assert client.claims == 1

    def test_resumes_from_the_lease_completed_indices(self):
        executed: list = []
        client = FakeClient(make_lease(paired_spec(5), completed={0, 1, 2, 3}))
        Worker(client, make_run_one(executed)).run_once()
        assert executed == [500]  # only index 4
        assert client.completed == ["job-1"]

    def test_an_unrunnable_spec_fails_the_job(self):
        bad = {"sweep": {"qf": [1, 2], "span1": [9]}}
        client = FakeClient(make_lease(bad))
        worker = Worker(client, make_run_one([]))
        assert worker.run_once() is True
        assert client.completed == []
        assert len(client.failed) == 1
        assert client.failed[0][0] == "job-1"
        assert "ValueError" in client.failed[0][1]

    def test_a_stopped_job_is_left_incomplete_for_lease_expiry(self):
        client = FakeClient(make_lease(paired_spec(5)))
        worker = Worker(
            client,
            make_run_one([]),
            chunk_size=2,
            should_stop=lambda: len(client.chunks) >= 1,
        )
        worker.run_once()
        # Neither completed nor failed: the lease expires server-side and the
        # job resumes elsewhere from the last reported chunk.
        assert client.completed == []
        assert client.failed == []
        assert len(client.chunks) >= 1

    def test_run_forever_polls_and_sleeps_between_empty_claims(self):
        client = FakeClient(None)
        sleeps: list = []
        polls = iter([False, False, True])
        worker = Worker(
            client,
            make_run_one([]),
            poll_interval=15.0,
            should_stop=lambda: next(polls),
            sleep=sleeps.append,
        )
        worker.run_forever()
        assert client.claims == 2
        assert sleeps == [15.0, 15.0]

    def test_run_forever_does_not_sleep_after_a_claimed_job(self):
        client = FakeClient(make_lease(paired_spec(1)))
        sleeps: list = []
        # Stop after the job is done — should_stop is also consulted mid-job
        # by execute_job, so a two-shot iterator would run out.
        worker = Worker(
            client,
            make_run_one([]),
            should_stop=lambda: bool(client.completed),
            sleep=sleeps.append,
        )
        worker.run_forever()
        assert client.completed == ["job-1"]
        assert sleeps == []

    def test_a_claim_error_is_treated_as_an_empty_poll(self):
        class Boom(FakeClient):
            def claim_job(self, worker_id: str):
                raise RuntimeError("backend down")

        worker = Worker(Boom(None), make_run_one([]))
        assert worker.run_once() is False


class TestMakeComRunOne:
    def _dbs(self):
        decks = {
            "T14": {
                "name": "COFRAPLUS 60",
                "deck_type": "T",
                "deck_depth": 58,
                "deck_trug": 207,
                "deck_top": 106,
                "deck_bot": 62,
                "deck_stiff_height": 0,
            }
        }
        meshes = {"ST15C": {"mainArea": 142, "transArea": 142}}
        sections = {"IPE_500": {"h": 500, "b": 200, "tw": 10.2, "tf": 16}}
        return sections, decks, meshes

    def test_resolves_deck_mesh_and_slab_weight_before_com(self):
        seen: list = []

        def run_com(params, sections_db):
            seen.append(dict(params))
            return {"uf_max": 0.4}

        run_one = make_com_run_one(*self._dbs(), run_com=run_com, sleep=lambda _: None)
        out = run_one({
            "DeckId": "T14",
            "mesh_type": "ST15C",
            "slab_depth": 130,
            "calc_slab_weight": "1",
        })
        assert out == {"uf_max": 0.4}
        assert seen[0]["deck_depth"] == 58
        assert seen[0]["mesh_area_max"] == 142
        assert seen[0]["slab_weight"] > 0

    def test_retries_runtime_error_then_succeeds(self):
        calls = {"n": 0}
        sleeps: list = []

        def run_com(params, sections_db):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("COM bridge died")
            return {"uf_max": 0.2}

        run_one = make_com_run_one(*self._dbs(), run_com=run_com, sleep=sleeps.append)
        assert run_one({"DeckId": "T14", "mesh_type": "ST15C"}) == {"uf_max": 0.2}
        assert calls["n"] == 3
        assert sleeps == [2.0, 4.0]

    def test_non_com_errors_are_not_retried(self):
        calls = {"n": 0}

        def run_com(params, sections_db):
            calls["n"] += 1
            raise ValueError("bad section")

        run_one = make_com_run_one(*self._dbs(), run_com=run_com, sleep=lambda _: None)
        with pytest.raises(ValueError, match="bad section"):
            run_one({"DeckId": "T14", "mesh_type": "ST15C"})
        assert calls["n"] == 1


class TestHttpJobsClient:
    def _client(self, handler):
        calls: list = []

        def transport(method, url, headers, body):
            calls.append((method, url, headers, body))
            return handler(method, url, headers, body)

        client = HttpJobsClient("https://jobs.example/", "secret", transport=transport)
        return client, calls

    def test_claim_returns_none_on_204(self):
        client, calls = self._client(lambda *a: (204, b""))
        assert client.claim_job("box-0") is None
        assert calls[0][0] == "POST"
        assert calls[0][1] == "https://jobs.example/jobs/claim"
        assert calls[0][2]["Authorization"] == "Bearer secret"

    def test_claim_parses_a_lease_and_completed_indices(self):
        payload = {
            "job_id": "job-9",
            "lease_token": "tok-9",
            "spec": {"analysis_method": "iso", "sweep": {"qf": [1]}},
            "completed_indices": [0, 2],
        }
        client, _ = self._client(lambda *a: (200, __import__("json").dumps(payload).encode()))
        lease = client.claim_job("box-0")
        assert lease.job_id == "job-9"
        assert lease.lease_token == "tok-9"
        assert lease.spec["sweep"]["qf"] == [1]
        assert lease.completed_indices == frozenset({0, 2})

    def test_claim_http_error_raises(self):
        client, _ = self._client(lambda *a: (500, b"nope"))
        with pytest.raises(RuntimeError, match="claim_job failed"):
            client.claim_job("box-0")

    def test_report_complete_and_fail_post_the_lease_token(self):
        client, calls = self._client(lambda *a: (200, b"{}"))
        lease = make_lease(paired_spec(1))
        client.report_chunk(lease, [{"sample_index": 0}])
        client.complete_job(lease)
        client.fail_job(lease, "ValueError: bad")
        paths = [c[1] for c in calls]
        assert paths == [
            "https://jobs.example/jobs/job-1/chunks",
            "https://jobs.example/jobs/job-1/complete",
            "https://jobs.example/jobs/job-1/fail",
        ]
        import json
        fail_body = json.loads(calls[2][3])
        assert fail_body["lease_token"] == "tok-1"
        assert fail_body["error"] == "ValueError: bad"


class TestWorkerCli:
    def test_missing_url_and_token_stays_inert(self):
        from macs_automation.worker.cli import build_worker

        with pytest.raises(SystemExit, match="MACS_JOBS_URL"):
            build_worker({})

    def test_build_worker_uses_env_and_sets_low_priority(self, monkeypatch):
        from macs_automation.worker.cli import build_worker

        flags = {"priority": False}

        monkeypatch.setattr(
            "macs_automation.worker.cli.set_low_priority",
            lambda: flags.__setitem__("priority", True) or True,
        )
        monkeypatch.setattr(
            "macs_automation.data_loader.load_data",
            lambda: {"sections": {}, "decks": {}, "meshes": {}},
        )
        worker = build_worker(
            {
                "MACS_JOBS_URL": "https://jobs.example",
                "MACS_JOBS_TOKEN": "t",
                "MACS_WORKER_ID": "dev-0",
                "MACS_WORKER_POLL": "7",
            }
        )
        assert flags["priority"] is True
        assert worker.worker_id == "dev-0"
        assert worker.poll_interval == 7.0
        assert isinstance(worker.client, HttpJobsClient)
        assert worker.client.base_url == "https://jobs.example"

    def test_main_runs_the_injected_worker(self):
        from macs_automation.worker.cli import main

        class Stub:
            def __init__(self):
                self.ran = False

            def run_forever(self):
                self.ran = True

        stub = Stub()
        main({}, _worker=stub)
        assert stub.ran is True
