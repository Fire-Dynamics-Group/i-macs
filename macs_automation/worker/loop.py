"""The polling worker loop: claim → execute → report → complete."""
import logging
import platform
import time
from typing import Callable, Optional

from macs_automation.worker.client import JobsClient
from macs_automation.worker.executor import execute_job

logger = logging.getLogger(__name__)


def set_low_priority() -> bool:
    """Drop this process to BELOW_NORMAL so batch grinding never starves the
    box's other services. Child processes (the 32-bit com_runner) inherit the
    priority class on Windows. Best-effort: returns False off-Windows or when
    pywin32 is unavailable."""
    try:
        import win32api
        import win32process

        win32process.SetPriorityClass(
            win32api.GetCurrentProcess(),
            win32process.BELOW_NORMAL_PRIORITY_CLASS,
        )
        return True
    except Exception:
        return False


class Worker:
    """Outbound-only polling worker.

    Each `claim_job` poll doubles as the heartbeat — the backend stamps
    `last_seen` on every poll, so "online" is simply "polled recently" and no
    inbound network path ever exists. A job interrupted by `should_stop` is
    left neither completed nor failed: its lease expires server-side and the
    next claim resumes from the last reported sample index.
    """

    def __init__(
        self,
        client: JobsClient,
        run_one: Callable[[dict], dict],
        *,
        worker_id: Optional[str] = None,
        poll_interval: float = 15.0,
        chunk_size: int = 10,
        should_stop: Optional[Callable[[], bool]] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.run_one = run_one
        self.worker_id = worker_id or platform.node()
        self.poll_interval = poll_interval
        self.chunk_size = chunk_size
        self.should_stop = should_stop
        self.sleep = sleep

    def run_once(self) -> bool:
        """One poll. Returns True when a job was claimed (and worked on)."""
        try:
            lease = self.client.claim_job(self.worker_id)
        except Exception:
            # Backend unreachable — treat as an empty poll and retry after sleep.
            logger.exception("claim failed")
            return False
        if lease is None:
            return False
        logger.info("claimed job %s (%d samples already done)",
                    lease.job_id, len(lease.completed_indices))
        try:
            finished = execute_job(
                lease.spec,
                lease.completed_indices,
                self.run_one,
                lambda results: self.client.report_chunk(lease, results),
                chunk_size=self.chunk_size,
                should_stop=self.should_stop,
            )
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            logger.exception("job %s failed: %s", lease.job_id, error)
            try:
                self.client.fail_job(lease, error)
            except Exception:
                # Backend unreachable — the lease expires on its own.
                logger.exception("could not report failure for job %s", lease.job_id)
            return True
        if finished:
            self.client.complete_job(lease)
            logger.info("completed job %s", lease.job_id)
        else:
            logger.info("job %s interrupted; leaving lease to expire", lease.job_id)
        return True

    def run_forever(self) -> None:
        """Poll until `should_stop`. Sleeps only between empty polls — a
        claimed job goes straight back to polling for the next one."""
        while True:
            if self.should_stop is not None and self.should_stop():
                return
            claimed = self.run_once()
            if claimed:
                continue
            self.sleep(self.poll_interval)
