"""Worker mode (issue #44): execute centrally-queued macs-batch jobs.

The backend-independent core. `execute_job` turns a job spec (the exact shape
POST /api/sweeps accepts — one job format, two executors) into COM runs with
resume-from-sample-index semantics; `Worker` is the outbound-polling loop
around a `JobsClient`. `HttpJobsClient` is the outbound HTTP adapter for that protocol (stdlib
urllib, injectable transport — no live network in tests). Live claim/report
endpoints land with backendForNextApp#23.
"""
from macs_automation.worker.client import JobLease, JobsClient
from macs_automation.worker.executor import execute_job, make_com_run_one
from macs_automation.worker.http import HttpJobsClient
from macs_automation.worker.loop import Worker, set_low_priority

__all__ = [
    "HttpJobsClient",
    "JobLease",
    "JobsClient",
    "Worker",
    "execute_job",
    "make_com_run_one",
    "set_low_priority",
]
