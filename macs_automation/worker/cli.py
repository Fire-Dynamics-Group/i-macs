"""Headless worker entry: `python -m macs_automation.app --worker`.

Dev builds stay inert without MACS_JOBS_URL + MACS_JOBS_TOKEN (same injection
model as central run sync, i-macs#32). An always-on box exports those and
starts the sidecar with `--worker` (or MACS_WORKER=1).
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Optional

from macs_automation.worker.executor import make_com_run_one
from macs_automation.worker.http import HttpJobsClient
from macs_automation.worker.loop import Worker, set_low_priority


def build_worker(environ: Mapping[str, str]) -> Worker:
    url = (environ.get("MACS_JOBS_URL") or "").strip().rstrip("/")
    token = (environ.get("MACS_JOBS_TOKEN") or "").strip()
    if not url or not token:
        raise SystemExit(
            "worker mode requires MACS_JOBS_URL and MACS_JOBS_TOKEN "
            "(dev builds stay inert without them)"
        )
    set_low_priority()
    from macs_automation.data_loader import load_data

    data = load_data()
    run_one = make_com_run_one(data["sections"], data["decks"], data["meshes"])
    client = HttpJobsClient(url, token)
    poll = environ.get("MACS_WORKER_POLL")
    return Worker(
        client,
        run_one,
        worker_id=environ.get("MACS_WORKER_ID") or None,
        poll_interval=float(poll) if poll else 15.0,
    )


def main(environ: Optional[Mapping[str, str]] = None, *, _worker: Optional[Worker] = None) -> None:
    worker = _worker or build_worker(environ if environ is not None else os.environ)
    worker.run_forever()
