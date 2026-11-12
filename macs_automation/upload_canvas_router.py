"""FastAPI router for upload-canvas MACs link in i-macs."""

from __future__ import annotations

import os
import sys
import urllib.parse
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from macs_automation.db import ResultsDB
from macs_automation.entra_sign_in import (
    REDIRECT_URI,
    SIGN_IN_MESSAGE,
    SignInError,
    clear_session,
    session_view,
    sign_in_session,
    usable_bearer,
)
from macs_automation.upload_canvas import (
    UploadCanvasClient,
    UploadCanvasError,
    get_or_create_imacs_job_id,
    resolve_local_job_id,
    build_macs_run_payload,
    build_macs_batch_payload,
)

router = APIRouter(prefix="/api/imacs", tags=["upload-canvas"])


def _get_db() -> ResultsDB:
    from macs_automation.app import DB_PATH
    return ResultsDB(DB_PATH)


# Production hosts are string literals so PyInstaller freezes them into the
# sidecar. Do not read these through os.environ: a fresh install has no
# override, and a missing env var would leave the loopback fallback in the
# build the same way a bundler drops a non-literal env read.
_PROD_BACKEND_URL = "https://backendfornextapp-production.up.railway.app"
_PROD_WEB_URL = "https://upload-canvas.vercel.app"
_LOCAL_BACKEND_URL = "http://127.0.0.1:8001"
_LOCAL_WEB_URL = "http://localhost:3000"
_LOCAL_DEV_KEY = "dev-imacs-local-key"


def _nonempty(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_loopback(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _packaged_install() -> bool:
    """True when this process is a shipped install.

    The Tauri shell sets ``MACS_PACKAGED=1``. PyInstaller also sets
    ``sys.frozen`` on the sidecar exe, so a fresh install still targets
    production if that env var is missing.
    """
    if os.environ.get("MACS_PACKAGED") == "1":
        return True
    return bool(getattr(sys, "frozen", False))


def resolve_upload_canvas_config(db: ResultsDB) -> tuple[str, str, str]:
    """Settings, then environment, then install defaults.

    A packaged or frozen install with nothing configured uses the production
    Upload Canvas URLs. Dev (not packaged, not frozen) still defaults to
    localhost. A settings value or env var always wins, so either build can
    be pointed at the other environment.

    The app key is never invented for production. It comes from settings or
    ``IMACS_APP_KEY``. The localhost dev key is used only when the resolved
    backend is loopback and no key was configured.
    """
    backend = _nonempty(db.get_setting("backend_base_url")) or _nonempty(
        os.environ.get("IMACS_BACKEND_BASE_URL")
    )
    web = _nonempty(db.get_setting("upload_canvas_base_url")) or _nonempty(
        os.environ.get("UPLOAD_CANVAS_BASE_URL")
    )
    key = _nonempty(db.get_setting("imacs_app_key"))
    if key is None:
        key = _nonempty(os.environ.get("IMACS_APP_KEY"))

    if _packaged_install():
        backend = backend or _PROD_BACKEND_URL
        web = web or _PROD_WEB_URL
    else:
        backend = backend or _LOCAL_BACKEND_URL
        web = web or _LOCAL_WEB_URL
    if not key and _is_loopback(backend):
        key = _LOCAL_DEV_KEY
    return backend, web, key or ""


def _get_client(db: ResultsDB = Depends(_get_db)) -> UploadCanvasClient:
    backend_url, web_url, app_key = resolve_upload_canvas_config(db)
    return UploadCanvasClient(
        backend_url=backend_url,
        upload_canvas_url=web_url,
        app_key=app_key,
        bearer_token=usable_bearer(db),
    )


def _require_upload_canvas_auth(client: UploadCanvasClient) -> None:
    """Stop before chart rendering when the user is not signed in.

    A packaged install has no shared key. Building the chart payload and
    then waiting on the production host is what made Create time out.
    A legacy app key still counts, so an older configured machine keeps
    working until that person signs in.
    """
    if _nonempty(client.bearer_token) or _nonempty(client.app_key):
        return
    raise HTTPException(status_code=401, detail=SIGN_IN_MESSAGE)


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
    # Ignored. Staff sign in with Microsoft; the desktop no longer accepts
    # a pasted app key. Kept so an older client body does not 422.
    imacs_app_key: Optional[str] = None


@router.get("/config")
def get_config(db: ResultsDB = Depends(_get_db)):
    try:
        backend_url, web_url, app_key = resolve_upload_canvas_config(db)
        # Neither the Entra token nor the legacy app key is returned.
        view = session_view(db)
        return {
            "backend_base_url": backend_url,
            "upload_canvas_base_url": web_url,
            "has_app_key": bool(_nonempty(app_key)),
            "signed_in": view["signed_in"],
            "account_email": view["account_email"],
            "account_name": view["account_name"],
            "sign_in_error": sign_in_session.error or "",
        }
    finally:
        db.close()


@router.put("/config")
def set_config(body: ConfigBody, db: ResultsDB = Depends(_get_db)):
    try:
        if body.backend_base_url is not None:
            db.set_setting("backend_base_url", body.backend_base_url.strip())
        if body.upload_canvas_base_url is not None:
            db.set_setting("upload_canvas_base_url", body.upload_canvas_base_url.strip())
        # imacs_app_key is intentionally ignored.
        return {"status": "saved"}
    finally:
        db.close()


@router.post("/auth/sign-in")
def start_sign_in(db: ResultsDB = Depends(_get_db)):
    """Start PKCE sign-in and return the system-browser URL.

    The URL is an authorize link for the existing FD app. It does not
    contain a token. The browser redirect is handled on the loopback port.
    """
    try:
        auth_url = sign_in_session.start(db)
        return {"auth_url": auth_url, "redirect_uri": REDIRECT_URI}
    except SignInError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    finally:
        db.close()


@router.post("/auth/sign-out")
def sign_out(db: ResultsDB = Depends(_get_db)):
    try:
        clear_session(db)
        return {"signed_in": False}
    finally:
        db.close()


@router.get("/jobs/{job_id}/upload-canvas-summary")
def get_job_summary(
    job_id: str,
    db: ResultsDB = Depends(_get_db),
    client: UploadCanvasClient = Depends(_get_client),
):
    try:
        local_id = resolve_local_job_id(db, job_id)
        imacs_job_id = get_or_create_imacs_job_id(db, local_id)
        try:
            summary = client.get_summary(imacs_job_id)
        except UploadCanvasError as e:
            # 401/403/503 (and other backend failures) must reach the card.
            # A not-linked job is get_summary returning None, not this branch.
            raise HTTPException(status_code=e.status_code, detail=str(e))
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
        _require_upload_canvas_auth(client)
        local_id = resolve_local_job_id(db, job_id)
        imacs_job_id = get_or_create_imacs_job_id(db, local_id)
        payload = _resolve_job_payload(db, local_id, imacs_job_id)
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
        _require_upload_canvas_auth(client)
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
        _require_upload_canvas_auth(client)
        local_id = resolve_local_job_id(db, job_id)
        imacs_job_id = get_or_create_imacs_job_id(db, local_id)
        payload = _resolve_job_payload(db, local_id, imacs_job_id)

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
        _require_upload_canvas_auth(client)
        local_id = resolve_local_job_id(db, job_id)
        imacs_job_id = get_or_create_imacs_job_id(db, local_id)
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
        _require_upload_canvas_auth(client)
        local_id = resolve_local_job_id(db, job_id)
        imacs_job_id = get_or_create_imacs_job_id(db, local_id)
        summary = client.get_summary(imacs_job_id)
        if not summary or not summary.get("project_id"):
            raise HTTPException(status_code=400, detail="Job is not linked to any project")

        project_id = summary["project_id"]
        payload = _resolve_job_payload(db, local_id, imacs_job_id)
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
