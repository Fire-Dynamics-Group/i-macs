"""The contract between a worker and the central jobs backend.

Only the interface lives here. The HTTP implementation is written against
backendForNextApp#23 once its endpoints exist; the worker loop and executor
are tested against fakes, so nothing in this package needs a live network.
"""
from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class JobLease:
    """A claimed macs-batch job.

    `spec` is the same dict shape POST /api/sweeps accepts, so local runs and
    worker runs execute identical inputs. `completed_indices` are the sample
    indices the backend has already received results for — a re-claimed job
    (previous worker died, lease expired) resumes from there with no
    duplicate COM runs.
    """

    job_id: str
    lease_token: str
    spec: dict
    completed_indices: frozenset = field(default_factory=frozenset)


class JobsClient(Protocol):
    """Outbound-only: claiming doubles as the heartbeat (`last_seen`), and
    per-chunk reporting keeps the lease alive while a job executes."""

    def claim_job(self, worker_id: str) -> Optional[JobLease]:
        """Poll for work. Returns a lease, or None when the queue is empty."""
        ...

    def report_chunk(self, lease: JobLease, results: list) -> None:
        """Deliver a chunk of per-sample results (keyed by sample_index)."""
        ...

    def complete_job(self, lease: JobLease) -> None:
        """Mark the job done — every remaining sample has been reported."""
        ...

    def fail_job(self, lease: JobLease, error: str) -> None:
        """Mark the job unrunnable (e.g. invalid spec). Per-sample COM
        failures are NOT job failures — they travel as result rows."""
        ...
