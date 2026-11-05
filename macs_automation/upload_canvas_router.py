"""FastAPI router for upload-canvas MACs link in i-macs."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from macs_automation.db import ResultsDB
from macs_automation.upload_canvas import (
    UploadCanvasClient,
    UploadCanvasError,
    get_or_create_imacs_job_id,
    build_macs_run_payload,
    build_macs_batch_payload,
)

router = APIRouter(prefix="/api/imacs", tags=["upload-canvas"])


def _get_db() -> ResultsDB:
    from macs_automation.app import DB_PATH
    return ResultsDB(DB_PATH)


def _get_client(db: ResultsDB = Depends(_get_db)) -> UploadCanvasClient:
    backend_url = db.get_setting("backend_base_url") or "http://127.0.0.1:8001"
    web_url = db.get_setting("upload_canvas_base_url") or "http://localhost:3000"
    app_key = db.get_setting("imacs_app_key")
    if not app_key and ("127.0.0.1" in backend_url or "localhost" in backend_url):
        app_key = "dev-imacs-local-key"
    return UploadCanvasClient(backend_url=backend_url, upload_canvas_url=web_url, app_key=app_key)


def _safe_open_browser(url: str) -> None:
    """Best-effort launch of the default OS browser from the local sidecar."""
    if not url:
        return
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception as e:
        print(f"Warning: could not open browser for {url}: {e}")


def _get_latest_run_for_job(db: ResultsDB, job_id: str) -> dict:
    # First try batch_id
    if hasattr(db, "get_batch_runs"):
        runs = db.get_batch_runs(job_id)
    elif hasattr(db, "get_runs_for_batch"):
        runs = db.get_runs_for_batch(job_id)
    else:
        runs = []
    if runs:
        # Get the latest completed run without error, or simply the last run
        completed = [r for r in runs if not r.get("error")]
        return completed[-1] if completed else runs[-1]

    # Try single run id
    if job_id.isdigit():
        run = db.get_run(int(job_id))
        if run:
            return run

    raise HTTPException(status_code=404, detail=f"No runs found for job {job_id}")


def _resolve_job_payload(db: ResultsDB, job_id: str, imacs_job_id: str) -> dict:
    """Build a validated MACS run payload that inherits project name and batch metadata."""
    run_row = _get_latest_run_for_job(db, job_id)
    batch = None
    if hasattr(db, "get_batches"):
        batch = next((b for b in db.get_batches() if str(b.get("batch_id")) == str(job_id)), None)
        if not batch and run_row.get("batch_id"):
            batch = next((b for b in db.get_batches() if str(b.get("batch_id")) == str(run_row["batch_id"])), None)

    project_name = (batch.get("project_name") or "").strip() if batch else ""
    batch_name = (batch.get("name") or "").strip() if batch else ""
    label = project_name or batch_name or run_row.get("name") or None

    payload = build_macs_run_payload(run_row, imacs_job_id=imacs_job_id, label=label, db=db)
    if project_name:
        payload["project_name"] = project_name

    batch_payload = build_macs_batch_payload(db, job_id)
    if not batch_payload and run_row.get("batch_id"):
        batch_payload = build_macs_batch_payload(db, str(run_row["batch_id"]))
    if batch_payload:
        payload["macs_batch"] = batch_payload

    return payload


class LinkProjectBody(BaseModel):
    project_id: str


class ConfigBody(BaseModel):
    backend_base_url: Optional[str] = None
    upload_canvas_base_url: Optional[str] = None
    imacs_app_key: Optional[str] = None


@router.get("/config")
def get_config(db: ResultsDB = Depends(_get_db)):
    try:
        return {
            "backend_base_url": db.get_setting("backend_base_url") or "http://127.0.0.1:8001",
            "upload_canvas_base_url": db.get_setting("upload_canvas_base_url") or "http://localhost:3000",
            "has_app_key": bool(db.get_setting("imacs_app_key")),
        }
    finally:
        db.close()


@router.put("/config")
def set_config(body: ConfigBody, db: ResultsDB = Depends(_get_db)):
    try:
        if body.backend_base_url is not None:
            db.set_setting("backend_base_url", body.backend_base_url)
        if body.upload_canvas_base_url is not None:
            db.set_setting("upload_canvas_base_url", body.upload_canvas_base_url)
        if body.imacs_app_key is not None:
            db.set_setting("imacs_app_key", body.imacs_app_key)
        return {"status": "saved"}
    finally:
        db.close()


@router.get("/jobs/{job_id}/upload-canvas-summary")
def get_job_summary(
    job_id: str,
    db: ResultsDB = Depends(_get_db),
    client: UploadCanvasClient = Depends(_get_client),
):
    try:
        imacs_job_id = get_or_create_imacs_job_id(db, job_id)
        try:
            summary = client.get_summary(imacs_job_id)
        except UploadCanvasError:
            # Backend not reachable or not yet configured: treat job as unlinked
            # rather than failing with 401/500 and polluting the card UI.
            summary = None
        return {
            "job_id": job_id,
            "imacs_job_id": imacs_job_id,
            "summary": summary,
        }
    finally:
        db.close()


@router.post("/jobs/{job_id}/upload-canvas-handoff")
def create_job_handoff(
    job_id: str,
    db: ResultsDB = Depends(_get_db),
    client: UploadCanvasClient = Depends(_get_client),
):
    try:
        imacs_job_id = get_or_create_imacs_job_id(db, job_id)
        payload = _resolve_job_payload(db, job_id, imacs_job_id)
        handoff = client.create_handoff(payload)
        if handoff and handoff.get("url"):
            _safe_open_browser(handoff["url"])
        return handoff
    except UploadCanvasError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    finally:
        db.close()


@router.get("/upload-canvas-projects")
def search_projects(
    q: str = "",
    client: UploadCanvasClient = Depends(_get_client),
    db: ResultsDB = Depends(_get_db),
):
    try:
        projects = client.search_projects(q)
        return {"projects": projects}
    except UploadCanvasError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    finally:
        db.close()


@router.post("/jobs/{job_id}/upload-canvas-link")
def link_project(
    job_id: str,
    body: LinkProjectBody,
    db: ResultsDB = Depends(_get_db),
    client: UploadCanvasClient = Depends(_get_client),
):
    try:
        imacs_job_id = get_or_create_imacs_job_id(db, job_id)
        payload = _resolve_job_payload(db, job_id, imacs_job_id)

        # 1. Link job
        client.link_project(imacs_job_id, body.project_id)
        # 2. Push run
        client.push_run(body.project_id, payload)

        url = f"{client.upload_canvas_url}/structural-fire?project={body.project_id}"
        _safe_open_browser(url)
        return {
            "status": "linked",
            "project_id": body.project_id,
            "url": url,
        }
    except UploadCanvasError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    finally:
        db.close()


@router.delete("/jobs/{job_id}/upload-canvas-link")
def unlink_project(
    job_id: str,
    db: ResultsDB = Depends(_get_db),
    client: UploadCanvasClient = Depends(_get_client),
):
    try:
        imacs_job_id = get_or_create_imacs_job_id(db, job_id)
        res = client.unlink_project(imacs_job_id)
        return {"status": "unlinked", "result": res}
    except UploadCanvasError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    finally:
        db.close()


@router.post("/jobs/{job_id}/upload-canvas-push")
def push_run(
    job_id: str,
    db: ResultsDB = Depends(_get_db),
    client: UploadCanvasClient = Depends(_get_client),
):
    try:
        imacs_job_id = get_or_create_imacs_job_id(db, job_id)
        summary = client.get_summary(imacs_job_id)
        if not summary or not summary.get("project_id"):
            raise HTTPException(status_code=400, detail="Job is not linked to any project")

        project_id = summary["project_id"]
        payload = _resolve_job_payload(db, job_id, imacs_job_id)
        client.push_run(project_id, payload)

        url = f"{client.upload_canvas_url}/structural-fire?project={project_id}"
        _safe_open_browser(url)
        return {
            "status": "pushed",
            "project_id": project_id,
            "url": url,
        }
    except UploadCanvasError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    finally:
        db.close()
