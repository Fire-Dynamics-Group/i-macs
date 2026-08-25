"""HTTP JobsClient against the central jobs backend (backendForNextApp#23).

The transport is injectable so claim/report/complete/fail are unit-tested
without a live network. The URL shape is the worker side of the #23
contract:

    POST {base}/jobs/claim              -> 200 JobLease JSON, or 204 empty
    POST {base}/jobs/{id}/chunks        -> 2xx
    POST {base}/jobs/{id}/complete      -> 2xx
    POST {base}/jobs/{id}/fail          -> 2xx

Auth is the shared bearer token (#32 / #23). Stdlib urllib — no extra
dependency that needs a 32-bit Windows wheel.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import urljoin

from macs_automation.worker.client import JobLease

# method, url, headers, body -> (status_code, response_body)
Transport = Callable[[str, str, dict, Optional[bytes]], tuple[int, bytes]]


def urllib_transport(
    method: str, url: str, headers: dict, body: Optional[bytes]
) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class HttpJobsClient:
    """Outbound-only jobs client. Claiming doubles as the heartbeat."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: Transport = urllib_transport,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> tuple[int, bytes]:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        return self.transport(method, url, self._headers(), body)

    def claim_job(self, worker_id: str) -> Optional[JobLease]:
        status, body = self._request("POST", "jobs/claim", {"worker_id": worker_id})
        if status == 204 or not body.strip() or body.strip() == b"null":
            return None
        if status != 200:
            raise RuntimeError(f"claim_job failed: HTTP {status}: {body[:300]!r}")
        data = json.loads(body)
        if not data:
            return None
        return JobLease(
            job_id=str(data["job_id"]),
            lease_token=str(data["lease_token"]),
            spec=data["spec"],
            completed_indices=frozenset(data.get("completed_indices") or ()),
        )

    def report_chunk(self, lease: JobLease, results: list) -> None:
        status, body = self._request(
            "POST",
            f"jobs/{lease.job_id}/chunks",
            {"lease_token": lease.lease_token, "results": results},
        )
        if status < 200 or status >= 300:
            raise RuntimeError(f"report_chunk failed: HTTP {status}: {body[:300]!r}")

    def complete_job(self, lease: JobLease) -> None:
        status, body = self._request(
            "POST",
            f"jobs/{lease.job_id}/complete",
            {"lease_token": lease.lease_token},
        )
        if status < 200 or status >= 300:
            raise RuntimeError(f"complete_job failed: HTTP {status}: {body[:300]!r}")

    def fail_job(self, lease: JobLease, error: str) -> None:
        status, body = self._request(
            "POST",
            f"jobs/{lease.job_id}/fail",
            {"lease_token": lease.lease_token, "error": error},
        )
        if status < 200 or status >= 300:
            raise RuntimeError(f"fail_job failed: HTTP {status}: {body[:300]!r}")
