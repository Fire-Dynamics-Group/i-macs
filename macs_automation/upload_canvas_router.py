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
)

router = APIRouter(prefix="/api/imacs", tags=["upload-canvas"])


def _get_db() -> ResultsDB:
    from macs_automation.app import DB_PATH
    return ResultsDB(DB_PATH)


def _get_client(db: ResultsDB = Depends(_get_db)) -> UploadCanvasClient:
    backend_url = db.get_setting("backend_base_url") or "http://127.0.0.1:8001"
    web_url = db.get_setting("upload_canvas_base_url") or "http://localhost:3000"
    app_key = db.get_setting("imacs_app_key")
    return UploadCanvasClient(backend_url=backend_url, upload_canvas_url=web_url, app_key=app_key)


def _get_latest_run_for_job(db: ResultsDB, job_id: str) -> dict:
    # First try batch_id
    runs = db.get_runs_for_batch(job_id)
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
        summary = client.get_summary(imacs_job_id)
        return {
            "job_id": job_id,
            "imacs_job_id": imacs_job_id,
            "summary": summary,
        }
    except UploadCanvasError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
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
        run_row = _get_latest_run_for_job(db, job_id)
        payload = build_macs_run_payload(run_row, imacs_job_id=imacs_job_id)
        handoff = client.create_handoff(payload)
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
        run_row = _get_latest_run_for_job(db, job_id)
        payload = build_macs_run_payload(run_row, imacs_job_id=imacs_job_id)

        # 1. Link job
        client.link_project(imacs_job_id, body.project_id)
        # 2. Push run
        client.push_run(body.project_id, payload)

        return {
            "status": "linked",
            "project_id": body.project_id,
            "url": f"{client.upload_canvas_url}/",
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
        run_row = _get_latest_run_for_job(db, job_id)
        payload = build_macs_run_payload(run_row, imacs_job_id=imacs_job_id)
        client.push_run(project_id, payload)

        return {
            "status": "pushed",
            "project_id": project_id,
            "url": f"{client.upload_canvas_url}/",
        }
    except UploadCanvasError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    finally:
        db.close()
