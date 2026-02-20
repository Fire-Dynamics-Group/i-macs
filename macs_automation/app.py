"""FastAPI web application for MACS+ Automation desktop UI."""

import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from macs_automation.db import ResultsDB
from macs_automation.data_loader import load_data, DEFAULT_DATA_PATH
from macs_automation.frc_parser import parse_frc_string
from macs_automation.sweep import DEFAULTS, PARAM_ALIASES, BEAM_SIDE_MAP, resolve_deck, resolve_mesh, generate_combinations
from macs_automation.sampling import FIRE_LOAD_PRESETS

APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR.parent / "results.db"

app = FastAPI(title="MACS+ Automation")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

# ─── Reference data (loaded once at startup) ─────────────────────────────────
_ref_data: Optional[dict] = None


def _get_ref_data() -> dict:
    global _ref_data
    if _ref_data is None:
        try:
            _ref_data = load_data()
        except FileNotFoundError:
            _ref_data = {"sections": {}, "decks": {}, "meshes": {}}
    return _ref_data


def _get_db() -> ResultsDB:
    return ResultsDB(DB_PATH)


# ─── Display columns for batch results ────────────────────────────────────────
_DISPLAY_COLUMNS = {
    "span1": "Span 1 (m)",
    "span2": "Span 2 (m)",
    "numbeam": "No. Beams",
    "slab_depth": "Slab Depth (mm)",
    "fck": "fck (MPa)",
    "u_sec_size": "UB Section",
    "method": "Method",
    "time_limit": "Time Limit (min)",
    "qf": "Fire Load (MJ/m²)",
    "window_percent": "Window %",
    "Lc": "Lc (m)",
    "Bc": "Bc (m)",
    "Hc": "Hc (m)",
    "Hw": "Hw (m)",
    "Lw": "Lw (m)",
    "Bfac": "B Factor",
    "combustion_factor": "Combustion Factor",
    "growth_rate": "Growth Rate",
    "lead_var_act": "Lead Variable Action",
    "othr_var_act": "Other Variable Action",
    "cold_perm": "Cold Permanent",
    "mesh_type": "Mesh Type",
    "conc_type": "Concrete Type",
    "deck_name": "Deck",
}


def _detect_varying_columns(runs: list[dict]) -> tuple[list[str], list[tuple[str, str]]]:
    """Detect which display columns vary across runs.

    Returns (varying_col_names, fixed_params) where:
      - varying_col_names: list of DB column names that differ across runs
      - fixed_params: list of (column_name, value) for columns that are constant
    """
    if not runs:
        return [], []

    varying = []
    fixed = []
    for col, label in _DISPLAY_COLUMNS.items():
        values = {r.get(col) for r in runs}
        # Exclude columns where all values are None
        non_none = {v for v in values if v is not None}
        if not non_none:
            continue
        if len(values) > 1:
            varying.append(col)
        else:
            fixed.append((col, label, next(iter(non_none))))

    return varying, fixed


# ─── Sweep state (in-memory, shared across threads) ──────────────────────────
_sweep_state = {
    "active": False,
    "total": 0,
    "completed": 0,
    "errors": 0,
    "error_log": [],
    "start_time": None,
    "mode": None,
}
_sweep_lock = threading.Lock()


COM_MAX_RETRIES = 3
COM_RETRY_DELAY = 2.0  # seconds between retries
COM_RUN_DELAY = 0.5    # seconds between successive runs


def _run_single_com(params: dict, sections_db: dict) -> dict:
    """Run a single MACS+ COM call with retries on COM errors."""
    import pythoncom
    from pywintypes import com_error

    last_error = None
    for attempt in range(1, COM_MAX_RETRIES + 1):
        try:
            pythoncom.CoInitialize()
            try:
                from macs_automation.engine import MACSEngine
                eng = MACSEngine()
                eng.set_inputs(params, sections_db)
                return eng.run(method=params.get("method", "iso"))
            finally:
                pythoncom.CoUninitialize()
        except com_error as e:
            last_error = e
            if attempt < COM_MAX_RETRIES:
                time.sleep(COM_RETRY_DELAY * attempt)
        except Exception:
            raise
    raise last_error


def _run_sweep_background(combinations: list[dict], sections_db: dict, mode: str = "sweep"):
    """Run a sweep in a background thread with COM init per run."""
    with _sweep_lock:
        _sweep_state["active"] = True
        _sweep_state["total"] = len(combinations)
        _sweep_state["completed"] = 0
        _sweep_state["errors"] = 0
        _sweep_state["error_log"] = []
        _sweep_state["start_time"] = time.time()
        _sweep_state["mode"] = mode

    db = _get_db()
    try:
        for params in combinations:
            try:
                outputs = _run_single_com(params, sections_db)
                db.insert_run(params, outputs=outputs)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                db.insert_run(params, error=error_msg)
                with _sweep_lock:
                    _sweep_state["errors"] += 1
                    _sweep_state["error_log"].append(error_msg)
                    if len(_sweep_state["error_log"]) > 10:
                        _sweep_state["error_log"] = _sweep_state["error_log"][-10:]

            with _sweep_lock:
                _sweep_state["completed"] += 1

            time.sleep(COM_RUN_DELAY)
    finally:
        db.close()
        with _sweep_lock:
            _sweep_state["active"] = False


# ─── API: Reference data endpoints ───────────────────────────────────────────

@app.get("/api/sections")
def api_sections():
    """All sections grouped by family."""
    data = _get_ref_data()
    grouped = {}
    for sec_id, sec in data["sections"].items():
        fam = sec["family"]
        if fam not in grouped:
            grouped[fam] = []
        grouped[fam].append({"id": sec_id, "name": sec["name"], "h": sec["h"], "b": sec["b"]})
    return grouped


@app.get("/api/decks")
def api_decks():
    return _get_ref_data()["decks"]


@app.get("/api/meshes")
def api_meshes():
    return _get_ref_data()["meshes"]


# ─── API: Run endpoints ──────────────────────────────────────────────────────

@app.post("/api/runs")
def api_submit_run(request_body: dict):
    """Submit a single MACS+ run (synchronous)."""
    import pythoncom

    data = _get_ref_data()
    params = dict(DEFAULTS)

    # Apply user-provided values
    for key, value in request_body.items():
        internal_key = PARAM_ALIASES.get(key, key)
        params[internal_key] = value

    # Resolve deck and mesh
    resolve_deck(params, data["decks"])
    resolve_mesh(params, data["meshes"])

    try:
        pythoncom.CoInitialize()
        try:
            from macs_automation.engine import MACSEngine
            engine = MACSEngine()
            engine.set_inputs(params, data["sections"])
            outputs = engine.run(method=params.get("method", "iso"))
        finally:
            pythoncom.CoUninitialize()
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        db = _get_db()
        run_id = db.insert_run(params, error=error_msg)
        db.close()
        return JSONResponse({"id": run_id, "error": error_msg}, status_code=500)

    db = _get_db()
    run_id = db.insert_run(params, outputs=outputs)
    db.close()
    return {"id": run_id, "uf_max": outputs["uf_max"], "duration_ms": outputs["duration_ms"]}


@app.post("/api/sweeps")
def api_submit_sweep(request_body: dict):
    """Submit a sweep config (starts background job)."""
    with _sweep_lock:
        if _sweep_state["active"]:
            return JSONResponse({"error": "A sweep is already running"}, status_code=409)

    data = _get_ref_data()

    # Detect mode from request
    mode = "lhs" if request_body.get("sampling") == "lhs" else "sweep"

    # Dispatch to generate_combinations() which handles both grid sweep and LHS
    combinations = generate_combinations(request_body)

    # Generate batch_id and record batch metadata
    batch_id = uuid.uuid4().hex
    db = _get_db()
    db.insert_batch(batch_id, mode=mode, total_expected=len(combinations))
    db.close()

    # Inject batch_id into each combination
    for p in combinations:
        p["_batch_id"] = batch_id

    # Resolve deck/mesh for each
    for p in combinations:
        resolve_deck(p, data["decks"])
        resolve_mesh(p, data["meshes"])

    # Start background thread
    t = threading.Thread(
        target=_run_sweep_background,
        args=(combinations, data["sections"], mode),
        daemon=True,
    )
    t.start()

    return {"total": len(combinations), "message": "Sweep started", "batch_id": batch_id}


@app.get("/api/sweeps/status")
def api_sweep_status():
    """Return current sweep progress."""
    with _sweep_lock:
        state = dict(_sweep_state)
    elapsed = 0
    eta = None
    if state["start_time"] and state["completed"] > 0:
        elapsed = time.time() - state["start_time"]
        avg_per_run = elapsed / state["completed"]
        remaining = state["total"] - state["completed"]
        eta = round(avg_per_run * remaining, 1)
    return {
        "active": state["active"],
        "total": state["total"],
        "completed": state["completed"],
        "errors": state["errors"],
        "error_log": state["error_log"],
        "elapsed_s": round(elapsed, 1),
        "eta_s": eta,
        "mode": state["mode"],
    }


@app.get("/api/runs")
def api_list_runs(limit: int = 50, offset: int = 0):
    """List runs with pagination."""
    db = _get_db()
    runs = db.get_runs(limit=limit, offset=offset)
    stats = db.get_stats()
    db.close()
    return {"runs": runs, "stats": stats}


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: int):
    """Get single run detail."""
    db = _get_db()
    run = db.get_run(run_id)
    db.close()
    if run is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return run


@app.get("/api/runs/{run_id}/timeseries")
def api_get_timeseries(run_id: int):
    """Get time series data for a run (for plots)."""
    db = _get_db()
    ts = db.get_time_series(run_id)
    db.close()
    return ts


# ─── API: FRC file import ────────────────────────────────────────────────────

@app.post("/api/import-frc")
async def api_import_frc(file: UploadFile):
    """Parse an uploaded .frc file and return params for form pre-population."""
    content = await file.read()
    try:
        xml_string = content.decode("utf-8")
    except UnicodeDecodeError:
        xml_string = content.decode("utf-8-sig")

    try:
        result = parse_frc_string(xml_string)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Failed to parse .frc file: {e}"}, status_code=400)

    return result


# ─── Page routes (serve templates) ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def page_config(request: Request):
    data = _get_ref_data()
    # Occupancy presets with distribution info (exclude "Opening Factor" — used internally)
    occupancy_presets = [
        {"name": name, "mean": info["mean"], "type": info["type"], "cov": info["cov"]}
        for name, info in FIRE_LOAD_PRESETS.items()
        if name != "Opening Factor"
    ]
    return templates.TemplateResponse(request, "config.html", {
        "defaults": DEFAULTS,
        "sections": data["sections"],
        "decks": data["decks"],
        "meshes": data["meshes"],
        "occupancy_presets": occupancy_presets,
    })


@app.get("/dashboard", response_class=HTMLResponse)
def page_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/results", response_class=HTMLResponse)
def page_results(request: Request):
    db = _get_db()
    stats = db.get_stats()

    # Build batch groups
    batches = db.get_batches()
    batch_groups = []
    for b in batches:
        runs = db.get_batch_runs(b["batch_id"])
        varying_cols, fixed_params = _detect_varying_columns(runs)
        batch_groups.append({
            **b,
            "runs": runs,
            "varying_cols": varying_cols,
            "fixed_params": fixed_params,
        })

    ungrouped_runs = db.get_ungrouped_runs(limit=100)
    db.close()

    return templates.TemplateResponse(request, "results.html", {
        "stats": stats,
        "batch_groups": batch_groups,
        "ungrouped_runs": ungrouped_runs,
        "display_columns": _DISPLAY_COLUMNS,
    })


@app.get("/results/{run_id}", response_class=HTMLResponse)
def page_detail(request: Request, run_id: int):
    db = _get_db()
    run = db.get_run(run_id)
    ts = db.get_time_series(run_id)
    db.close()
    if run is None:
        return RedirectResponse("/results")
    return templates.TemplateResponse(request, "detail.html", {
        "run": run,
        "time_series": ts,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("macs_automation.app:app", host="localhost", port=8000, reload=True)
