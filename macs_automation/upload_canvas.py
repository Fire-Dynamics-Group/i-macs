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


_EXPOSURES = {"3-sided", "4-sided"}


def _catalog_key(section_name: str) -> str:
    """Blue Book keys are lowercase serial sizes, without a UB prefix."""
    text = section_name.strip().lower()
    if text.startswith("ub"):
        text = text[2:]
    return text.replace(" ", "")


def compute_section_factor(section_name: str, exposure: str) -> float:
    """Section factor Ap/V (1/m) from Blue Book dimensions and a real exposure.

    Unknown sections raise. The old 140 fallback was what the canvas stored
    for UB 457x191x82, because the lookup uppercased a lowercase key.
    """
    if exposure not in _EXPOSURES:
        raise UploadCanvasError(
            "Exposure must be 3-sided or 4-sided. Refusing to invent 3-sided.",
            status_code=422,
        )
    if not isinstance(section_name, str) or not section_name.strip():
        raise UploadCanvasError(
            "Run has no section. Refusing to invent UB 457x191x82.",
            status_code=422,
        )
    info = UB_SECTIONS.get(_catalog_key(section_name))
    if not info:
        raise UploadCanvasError(
            f"No Blue Book dimensions for section {section_name!r}. "
            "Refusing to invent section factor 140.",
            status_code=422,
        )

    h = info["h"] / 1000.0
    b = info["b"] / 1000.0
    tw = info["tw"] / 1000.0
    tf = info["tf"] / 1000.0
    area = info["mass_per_m"] / 7850.0

    if exposure == "3-sided":
        hp = 3 * b + 2 * h - 2 * tw - 2 * tf
    else:
        hp = 4 * b + 2 * h - 2 * tw

    if area <= 0 or hp <= 0:
        raise UploadCanvasError(
            f"Section factor for {section_name!r} could not be calculated. "
            "Refusing to invent section factor 140.",
            status_code=422,
        )
    return round(hp / area, 1)


def _governing_beam(run_row: dict[str, Any]) -> tuple[str, float]:
    """Lowest positive perimeter-beam critical temperature. Ties keep A→D order."""
    candidates: list[tuple[str, float]] = []
    for side in ("a", "b", "c", "d"):
        val = run_row.get(f"side_{side}_critical_temp")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        if val > 0:
            candidates.append((side, float(val)))
    if not candidates:
        raise UploadCanvasError(
            "Run has no positive perimeter-beam critical temperature. "
            "Refusing to invent 550.",
            status_code=422,
        )
    return min(candidates, key=lambda item: (item[1], item[0]))


def _section_name(run_row: dict[str, Any], side: str) -> str:
    for key in (f"side_{side}_sec", "u_sec_size", "section"):
        raw = run_row.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    raise UploadCanvasError(
        "Run has no section. Refusing to invent UB 457x191x82.",
        status_code=422,
    )


def _exposure_name(run_row: dict[str, Any], side: str) -> str:
    for key in ("exposure", f"side_{side}_exposure"):
        raw = run_row.get(key)
        if isinstance(raw, str) and raw.strip().lower() in _EXPOSURES:
            return raw.strip().lower()
    raise UploadCanvasError(
        "Run has no exposure. Refusing to invent 3-sided.",
        status_code=422,
    )


def build_macs_run_payload(
    run_row: dict[str, Any],
    imacs_job_id: str,
    label: Optional[str] = None,
    version: Optional[str] = None,
    db: Optional[ResultsDB] = None,
) -> dict[str, Any]:
    """Build a validated fd-macs-reliability/2 dictionary from a local run row."""
    governing_side, critical_temp = _governing_beam(run_row)
    governing_side_upper = governing_side.upper()
    section = _section_name(run_row, governing_side)
    exposure = _exposure_name(run_row, governing_side)
    sec_factor = compute_section_factor(section, exposure)
    resolved_version = str(version or os.environ.get("MACS_APP_VERSION") or "").strip()
    if not resolved_version:
        raise UploadCanvasError(
            "MACS_APP_VERSION is not set.",
            status_code=422,
        )

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
        if k not in ("time_series", "checks", "outputs") and v is not None and isinstance(v, (int, float, str, bool))
    }

    # Summary outputs and perimeter beam results
    outputs = {
        "comp_failure": run_row.get("comp_failure"),
        "mb1_reqd": run_row.get("mb1_reqd"),
        "mb2_reqd": run_row.get("mb2_reqd"),
        "factored_hot": run_row.get("factored_hot"),
        "uf_max": run_row.get("uf_max"),
        "max_temperature": run_row.get("max_temperature"),
        "max_deflection": run_row.get("max_deflection"),
        "max_slab_cap": run_row.get("max_slab_cap"),
        "max_beam_cap": run_row.get("max_beam_cap"),
        "max_total_cap": run_row.get("max_total_cap"),
        "side_a_load_ratio": run_row.get("side_a_load_ratio"),
        "side_a_critical_temp": run_row.get("side_a_critical_temp"),
        "side_b_load_ratio": run_row.get("side_b_load_ratio"),
        "side_b_critical_temp": run_row.get("side_b_critical_temp"),
        "side_c_load_ratio": run_row.get("side_c_load_ratio"),
        "side_c_critical_temp": run_row.get("side_c_critical_temp"),
        "side_d_load_ratio": run_row.get("side_d_load_ratio"),
        "side_d_critical_temp": run_row.get("side_d_critical_temp"),
        "duration_ms": run_row.get("duration_ms"),
        "engine_version": run_row.get("engine_version"),
    }
    if isinstance(run_row.get("outputs"), dict):
        outputs.update(run_row["outputs"])

    # Checks
    checks = run_row.get("checks")
    if not checks:
        try:
            from macs_automation.status import compute_status
            st = compute_status(run_row)
            checks = st.get("checks") or []
        except Exception:
            checks = []

    # Time series
    time_series = run_row.get("time_series") or []
    if not time_series and db and run_row.get("id"):
        try:
            time_series = db.get_time_series(int(run_row["id"]))
        except Exception:
            time_series = []

    return {
        "schema": "fd-macs-reliability/2",
        "critical_temp": float(critical_temp),
        "section_factor": float(sec_factor),
        "governing_side": governing_side_upper,
        "section": str(section),
        "exposure": exposure,
        "windows_user": str(user),
        "machine_name": str(machine),
        "client_timestamp": now_iso,
        "client_version": resolved_version,
        "run_id": str(run_row.get("uuid") or run_row.get("id") or uuid.uuid4()),
        "label": label or run_row.get("name") or "MACS Run",
        "inputs": inputs,
        "outputs": outputs,
        "checks": checks,
        "time_series": time_series,
        "imacs_job_id": str(imacs_job_id),
    }


def build_macs_batch_payload(db: ResultsDB, batch_id: str) -> Optional[dict[str, Any]]:
    """Build a validated macs_batch payload containing summary, setup, shear check, and 4 charts."""
    batches = db.get_batches()
    batch = next((b for b in batches if str(b.get("batch_id")) == str(batch_id)), None)
    if not batch:
        return None

    runs = db.get_batch_runs(batch_id)
    if not runs:
        return None

    run_count = len(runs)
    stats = db.get_batch_stats(batch_id) if hasattr(db, "get_batch_stats") else {}
    pass_count = stats.get("pass_count", batch.get("pass_count", 0))
    error_count = stats.get("errors", batch.get("error_count", 0))
    fail_count = stats.get("fail_count", max(0, run_count - pass_count - error_count))
    reliability_percent = round((pass_count / run_count) * 100.0, 2) if run_count > 0 else 0.0

    from macs_automation.batch_setup import derive_setup
    setup = derive_setup(runs)

    from macs_automation.shear_check import flags_for_run
    sub_limit = [
        {"run_id": r.get("id"), "flags": flags}
        for r in runs
        if (flags := flags_for_run(r))
    ]
    shear_check = {
        "batch_id": str(batch_id),
        "checked": run_count,
        "sub_limit_runs": sub_limit,
    }

    import base64
    import tempfile
    from pathlib import Path
    from macs_automation.report import _render_house_charts

    charts: dict[str, Optional[str]] = {
        "scatter": None,
        "totalCapacity": None,
        "beamTemp": None,
        "meshTemp": None,
    }

    try:
        db_path_val = getattr(db, "db_path", None)
        if db_path_val:
            cache_dir = Path(db_path_val).resolve().parent / "cache_charts" / str(batch_id)
        else:
            cache_dir = Path(tempfile.gettempdir()) / "macs_cache_charts" / str(batch_id)
        cache_dir.mkdir(parents=True, exist_ok=True)

        chart_files = {
            "scatter": cache_dir / "scatter_fail_pass_report.png",
            "totalCapacity": cache_dir / "total_cap_graph_report.png",
            "beamTemp": cache_dir / "beam_temp_graph_report.png",
            "meshTemp": cache_dir / "mesh_temp_graph_report.png",
        }
        all_exist = all(p.exists() and p.stat().st_size > 0 for p in chart_files.values())
        if not all_exist:
            _render_house_charts(db, batch_id, suffix="report", output_dir=cache_dir)

        for k, p in chart_files.items():
            if p.exists() and p.stat().st_size > 0:
                charts[k] = base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception as e:
        print(f"Warning: failed to render batch charts: {e}")

    summary = {
        "total_runs": run_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "reliability_percent": reliability_percent,
    }

    # Real governing values only. A missing piece stays null rather than
    # 550, UB 457x191x82, 3-sided, or section factor 140.
    governing_section = None
    critical_temp = None
    section_factor = None

    if runs:
        def _sort_temp(r: dict) -> float:
            try:
                return _governing_beam(r)[1]
            except UploadCanvasError:
                return 9999.0

        gov_run = min(runs, key=_sort_temp)
        try:
            gov_side, critical_temp = _governing_beam(gov_run)
        except UploadCanvasError:
            gov_side = None
            critical_temp = None
        if gov_side:
            try:
                governing_section = _section_name(gov_run, gov_side)
            except UploadCanvasError:
                governing_section = None
            try:
                exposure = _exposure_name(gov_run, gov_side)
                if governing_section:
                    section_factor = compute_section_factor(governing_section, exposure)
            except UploadCanvasError:
                section_factor = None

    return {
        "batch_id": str(batch_id),
        "name": batch.get("name") or f"Batch {str(batch_id)[:8]}",
        "project_name": batch.get("project_name"),
        "governing_section": governing_section,
        "critical_temp": critical_temp,
        "section_factor": section_factor,
        "run_count": run_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "reliability_percent": reliability_percent,
        "summary": summary,
        "setup": setup,
        "shear_check": shear_check,
        "charts": charts,
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
        # None means "read IMACS_APP_KEY". An explicit string, including "",
        # is the caller's decision — the localhost dev key must not be
        # substituted again here and hide a key the router already resolved.
        if app_key is None:
            app_key = os.environ.get("IMACS_APP_KEY", "")
        self.app_key = app_key

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        url = f"{self.backend_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "X-IMACS-App-Key": self.app_key,
        }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
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
                raise UploadCanvasError(
                    detail_msg or "Upload Canvas resource was not found.",
                    status_code=404,
                )
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
            "url": f"{self.upload_canvas_url}/structural-fire?handoff={handoff_id}",
            "expires_at": data.get("expires_at"),
        }

    def get_summary(self, imacs_job_id: str) -> Optional[dict[str, Any]]:
        """GET /imacs/jobs/{imacs_job_id}/summary -> returns summary or None.

        404 means the job is not linked yet. Auth and availability errors propagate.
        """
        try:
            return self._request("GET", f"/imacs/jobs/{urllib.parse.quote(imacs_job_id)}/summary")
        except UploadCanvasError as exc:
            if exc.status_code == 404:
                return None
            raise

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
