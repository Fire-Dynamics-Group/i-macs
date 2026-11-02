"""Upload Canvas MACs link client and payload builder for i-macs."""

from __future__ import annotations

import json
import os
import platform
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from macs_automation.blue_book_sections import UB_SECTIONS
from macs_automation.db import ResultsDB


class UploadCanvasError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


def get_or_create_imacs_job_id(db: ResultsDB, local_job_id: str) -> str:
    """Return the stable client-generated imacs_job_id for a local job/batch, creating if missing."""
    db.conn.execute(
        """
        CREATE TABLE IF NOT EXISTS local_job_links (
            local_job_id TEXT PRIMARY KEY,
            imacs_job_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor = db.conn.execute(
        "SELECT imacs_job_id FROM local_job_links WHERE local_job_id = ?",
        (str(local_job_id),),
    )
    row = cursor.fetchone()
    if row and row[0]:
        return str(row[0])

    new_job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.conn.execute(
        "INSERT INTO local_job_links (local_job_id, imacs_job_id, created_at) VALUES (?, ?, ?)",
        (str(local_job_id), new_job_id, now),
    )
    db.conn.commit()
    return new_job_id


def compute_section_factor(section_name: str, exposure: str = "3-sided") -> float:
    """Calculate section factor Ap/V (1/m) for a UB section."""
    clean = section_name.strip().upper().replace("UB", "").replace(" ", "")
    info = UB_SECTIONS.get(clean)
    if not info:
        for k, v in UB_SECTIONS.items():
            if k in clean or clean in k:
                info = v
                break

    if not info:
        return 140.0  # sensible default Ap/V for typical mid-range UB

    h = info["h"] / 1000.0
    b = info["b"] / 1000.0
    tw = info["tw"] / 1000.0
    tf = info["tf"] / 1000.0
    mass_per_m = info["mass_per_m"]

    # Area A = mass / density steel (7850 kg/m3)
    area = mass_per_m / 7850.0

    # Heated perimeter Hp
    if exposure == "3-sided":
        hp = 3 * b + 2 * h - 2 * tw - 2 * tf
    else:
        hp = 4 * b + 2 * h - 2 * tw

    if area > 0:
        return round(hp / area, 1)
    return 140.0


def build_macs_run_payload(
    run_row: dict[str, Any],
    imacs_job_id: str,
    label: Optional[str] = None,
    version: Optional[str] = None,
) -> dict[str, Any]:
    """Build a validated fd-macs-reliability/1 dictionary from a local run row."""
    # Find governing perimeter beam side (lowest positive critical temp)
    sides = ["a", "b", "c", "d"]
    candidates = []
    for s in sides:
        val = run_row.get(f"side_{s}_critical_temp")
        if val is not None and isinstance(val, (int, float)) and val > 0:
            candidates.append((s, float(val)))

    if candidates:
        governing_side, critical_temp = min(candidates, key=lambda x: x[1])
        governing_side_upper = governing_side.upper()
        section = (
            run_row.get(f"side_{governing_side}_sec")
            or run_row.get("u_sec_size")
            or "UB 457x191x82"
        )
    else:
        governing_side_upper = "A"
        critical_temp = float(run_row.get("max_temperature") or 550.0)
        section = run_row.get("u_sec_size") or "UB 457x191x82"

    exposure = "3-sided"
    sec_factor = compute_section_factor(section, exposure)

    try:
        user = os.getlogin()
    except Exception:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"

    machine = platform.node() or "unknown"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Inputs dictionary without complex nested objects
    inputs = {
        str(k): v
        for k, v in run_row.items()
        if k not in ("time_series", "checks") and v is not None and isinstance(v, (int, float, str, bool))
    }

    return {
        "schema": "fd-macs-reliability/1",
        "critical_temp": float(critical_temp),
        "section_factor": float(sec_factor),
        "governing_side": governing_side_upper,
        "section": str(section),
        "exposure": exposure,
        "windows_user": str(user),
        "machine_name": str(machine),
        "client_timestamp": now_iso,
        "client_version": str(version or "0.1.0-rc.17"),
        "run_id": str(run_row.get("uuid") or run_row.get("id") or uuid.uuid4()),
        "label": label or run_row.get("name") or "MACS Run",
        "inputs": inputs,
        "imacs_job_id": str(imacs_job_id),
    }


class UploadCanvasClient:
    def __init__(
        self,
        backend_url: str = "http://127.0.0.1:8001",
        upload_canvas_url: str = "http://localhost:3000",
        app_key: Optional[str] = None,
    ):
        self.backend_url = backend_url.rstrip("/")
        self.upload_canvas_url = upload_canvas_url.rstrip("/")
        self.app_key = app_key or os.environ.get("IMACS_APP_KEY", "")

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        url = f"{self.backend_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "X-IMACS-App-Key": self.app_key,
        }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                if status == 204:
                    return None
                resp_bytes = resp.read()
                if not resp_bytes:
                    return None
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            code = e.code
            detail_msg = ""
            try:
                err_body = e.read().decode("utf-8")
                err_json = json.loads(err_body)
                detail_msg = err_json.get("detail", "")
            except Exception:
                pass

            if code == 401:
                raise UploadCanvasError(
                    "Missing or invalid IMACS_APP_KEY header. Please configure the app key.",
                    status_code=401,
                )
            elif code == 403:
                raise UploadCanvasError(
                    "IMACS_APP_KEY is rejected (wrong key). Check your settings.",
                    status_code=403,
                )
            elif code == 503:
                raise UploadCanvasError(
                    "Service unavailable (backend IMACS_APP_KEY unset or offline).",
                    status_code=503,
                )
            elif code == 404:
                return None
            else:
                raise UploadCanvasError(
                    detail_msg or f"Backend request failed with status {code}",
                    status_code=code,
                )
        except Exception as e:
            raise UploadCanvasError(f"Network error connecting to backend: {e}", status_code=502)

    def create_handoff(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /imacs/handoffs -> returns { handoff_id, url }."""
        data = self._request("POST", "/imacs/handoffs", payload)
        if not data:
            raise UploadCanvasError("Empty response from /imacs/handoffs")
        handoff_id = data.get("handoff_id")
        return {
            "handoff_id": handoff_id,
            "url": f"{self.upload_canvas_url}/?handoff={handoff_id}",
            "expires_at": data.get("expires_at"),
        }

    def get_summary(self, imacs_job_id: str) -> Optional[dict[str, Any]]:
        """GET /imacs/jobs/{imacs_job_id}/summary -> returns summary or None."""
        return self._request("GET", f"/imacs/jobs/{urllib.parse.quote(imacs_job_id)}/summary")

    def search_projects(self, q: str = "") -> list[dict[str, Any]]:
        """GET /imacs/projects?mode=timeEq&q={q}."""
        query = urllib.parse.urlencode({"mode": "timeEq", "q": q})
        res = self._request("GET", f"/imacs/projects?{query}")
        return res if isinstance(res, list) else []

    def link_project(self, imacs_job_id: str, project_id: str) -> dict[str, Any]:
        """POST /imacs/jobs/{imacs_job_id}/link."""
        return self._request(
            "POST",
            f"/imacs/jobs/{urllib.parse.quote(imacs_job_id)}/link",
            {"project_id": str(project_id)},
        )

    def unlink_project(self, imacs_job_id: str) -> dict[str, Any]:
        """DELETE /imacs/jobs/{imacs_job_id}/link."""
        return self._request("DELETE", f"/imacs/jobs/{urllib.parse.quote(imacs_job_id)}/link")

    def push_run(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /imacs/projects/{project_id}/macs-runs."""
        return self._request(
            "POST",
            f"/imacs/projects/{urllib.parse.quote(str(project_id))}/macs-runs",
            payload,
        )
