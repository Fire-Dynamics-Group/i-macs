"""Routes for the MACS+ live dashboard — pages, API, SSE, batch control, report."""

import asyncio
import threading
import uuid
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from macs_automation.web.sse import broadcaster

router = APIRouter()

# ─── Batch state (in-memory) ─────────────────────────────────────────────────
_batch_thread: Optional[threading.Thread] = None
_cancel_event: Optional[threading.Event] = None
_batch_lock = threading.Lock()


# ─── Page routes ──────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def page_index(request: Request):
    db = request.app.state.db
    stats = db.get_stats()
    return request.app.state.templates.TemplateResponse(request, "index.html", {
        "stats": stats,
    })


@router.get("/dashboard", response_class=HTMLResponse)
def page_dashboard(request: Request):
    return request.app.state.templates.TemplateResponse(request, "dashboard.html")


# ─── API: Database queries ────────────────────────────────────────────────────

@router.get("/api/stats")
def api_stats(request: Request):
    db = request.app.state.db
    return db.get_stats()


@router.get("/api/runs")
def api_runs(request: Request, limit: int = 50, offset: int = 0):
    db = request.app.state.db
    runs = db.get_runs(limit=limit, offset=offset)
    stats = db.get_stats()
    return {"runs": runs, "stats": stats}


@router.get("/api/runs/{run_id}")
def api_run(request: Request, run_id: int):
    db = request.app.state.db
    run = db.get_run(run_id)
    if run is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Not found"}, status_code=404)
    return run


@router.get("/api/runs/{run_id}/time-series")
def api_time_series(request: Request, run_id: int):
    db = request.app.state.db
    return db.get_time_series(run_id)


# ─── SSE: Event stream ───────────────────────────────────────────────────────

@router.get("/api/events")
async def api_events():
    """SSE endpoint — streams run_complete and batch_complete events."""
    queue = await broadcaster.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield message
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Batch control ───────────────────────────────────────────────────────────

@router.post("/api/batch/start")
async def api_batch_start(request: Request):
    """Start a batch run from a config file.

    Expects JSON body: {"config_path": "path/to/config.yaml", "db_path": "optional"}
    Spawns a background thread with COM initialization.
    """
    global _batch_thread, _cancel_event
    from fastapi.responses import JSONResponse

    with _batch_lock:
        if _batch_thread and _batch_thread.is_alive():
            return JSONResponse({"error": "A batch is already running"}, status_code=409)

    body = await request.json()
    config_path = body.get("config_path")
    if not config_path:
        return JSONResponse({"error": "config_path required"}, status_code=400)

    _cancel_event = threading.Event()
    loop = asyncio.get_event_loop()

    def _run_in_thread():
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass

        try:
            from macs_automation.data_loader import load_data
            from macs_automation.sweep import (
                generate_combinations, load_config, resolve_deck, resolve_mesh,
            )
            from macs_automation.runner import run_batch_with_callback

            data = load_data()
            config = load_config(config_path)
            combinations = generate_combinations(config)

            for params in combinations:
                resolve_deck(params, data["decks"])
                resolve_mesh(params, data["meshes"])

            db = request.app.state.db

            # Generate batch_id and record batch metadata
            mode = config.get("sampling", "sweep")
            batch_id = uuid.uuid4().hex
            db.insert_batch(batch_id, mode=mode, total_expected=len(combinations))
            for params in combinations:
                params["_batch_id"] = batch_id

            def on_complete(run_id, params, outputs, error, progress):
                # Build SSE payload
                event_data = {
                    "run_id": run_id,
                    "qf": params.get("qf"),
                    "window_percent": params.get("window_percent"),
                    "error": error,
                    "progress": {
                        "completed": progress.completed,
                        "total": progress.total,
                        "errors": progress.errors,
                        "elapsed_seconds": round(progress.elapsed_seconds, 1),
                    },
                }
                if outputs:
                    event_data.update({
                        "uf_max": outputs.get("uf_max"),
                        "factored_hot": outputs.get("factored_hot"),
                        "pass": (outputs.get("uf_max") or 0) <= 1.0,
                        "side_a_critical_temp": outputs.get("side_a_critical_temp"),
                        "side_b_critical_temp": outputs.get("side_b_critical_temp"),
                        "side_c_critical_temp": outputs.get("side_c_critical_temp"),
                        "side_d_critical_temp": outputs.get("side_d_critical_temp"),
                    })
                    # Include time series data for live chart updates
                    ts = outputs.get("time_series", [])
                    if ts:
                        event_data["time_series"] = {
                            "time_min": [s["time_min"] for s in ts],
                            "total_plate_capacity": [s["total_plate_capacity"] for s in ts],
                            "lofl_temp": [s["lofl_temp"] for s in ts],
                            "mesh_temp": [s["mesh_temp"] for s in ts],
                        }

                broadcaster.broadcast_threadsafe("run_complete", event_data, loop)

            result = run_batch_with_callback(
                combinations, db, data["sections"],
                on_run_complete=on_complete,
                cancel_event=_cancel_event,
            )

            broadcaster.broadcast_threadsafe("batch_complete", {
                "status": result.status,
                "completed": result.completed,
                "errors": result.errors,
                "elapsed_seconds": round(result.elapsed_seconds, 1),
            }, loop)

        except Exception as e:
            broadcaster.broadcast_threadsafe("batch_error", {
                "error": f"{type(e).__name__}: {e}",
            }, loop)
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    _batch_thread = threading.Thread(target=_run_in_thread, daemon=True)
    _batch_thread.start()

    return {"message": "Batch started"}


@router.post("/api/batch/cancel")
def api_batch_cancel():
    """Cancel the running batch."""
    from fastapi.responses import JSONResponse
    if _cancel_event:
        _cancel_event.set()
        return {"message": "Cancel requested"}
    return JSONResponse({"error": "No batch running"}, status_code=404)


# ─── Report download ─────────────────────────────────────────────────────────

@router.get("/api/report")
def api_report(request: Request):
    """Generate and download the report ZIP."""
    from macs_automation.report import generate_report_zip
    db = request.app.state.db
    zip_path = generate_report_zip(db)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename="macs_report.zip",
    )
