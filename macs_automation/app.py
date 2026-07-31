"""FastAPI sidecar for the MACS+ Automation desktop app.

Serves a JSON-only API consumed by the Tauri+React shell. CLI:

    python -m macs_automation.app --port 8123 --log-dir %LOCALAPPDATA%\\i-macs\\logs

There are no HTML/Jinja routes here — the React shell renders all UI.
"""

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from macs_automation.db import ResultsDB
from macs_automation.data_loader import load_data, DEFAULT_DATA_PATH, _find_macs_data_xml
from macs_automation import macs_detect
from macs_automation.batch_setup import derive_setup
from macs_automation.blue_book_sections import get_blue_book_sections
from macs_automation.frc_parser import parse_frc_string
from macs_automation.status import compute_status
from macs_automation.report import (
    _extend_flat,
    _forward_filled_average,
    _sanitise_label,
)
from macs_automation import pdf_evidence
from macs_automation.shear_check import flags_for_run
from macs_automation.sse_broker import Broker
from macs_automation.sweep import DEFAULTS, PARAM_ALIASES, BEAM_SIDE_MAP, resolve_deck, resolve_mesh, generate_combinations
from macs_automation.sampling import FIRE_LOAD_PRESETS
from macs_automation.varying_params import varying_params_from_config


def _attach_status(run: dict) -> dict:
    """Add overall_pass + checks fields to a run row in-place; return for chaining."""
    if run is None:
        return run
    status = compute_status(run)
    run["overall_pass"] = status["overall_pass"]
    run["checks"] = status["checks"]
    return run

APP_DIR = Path(__file__).parent


def _resolve_db_path() -> Path:
    """Pick where SQLite lives.

    Order:
      1. MACS_DB_PATH env (set by main.rs in production; tests can override).
      2. Frozen + no env: fall back to %LOCALAPPDATA%\\i-macs\\results.db.
         This is belt-and-suspenders — main.rs sets MACS_DB_PATH on every
         spawn, but if a future bundling regression unsets it we still land
         somewhere writeable rather than under Program Files (where Windows
         ACLs either virtualize the write into a hidden VirtualStore shadow
         folder or wipe the DB at every launch — the bug we're fixing).
      3. Dev (non-frozen): write to <repo>/results.db so the sidecar uses the
         existing dev database with the user's accumulated history.
    """
    env = os.environ.get("MACS_DB_PATH")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "i-macs" / "results.db"
    return APP_DIR.parent / "results.db"


DB_PATH = _resolve_db_path()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Open + close the DB once at startup so a bad MACS_DB_PATH (unwriteable
    parent, broken bundling, etc.) crashes the sidecar before Tauri's 30s
    /healthz wait succeeds. _get_db() is per-request, so without this probe
    a path issue would only surface on the first user action — too late for
    SidecarErrorScreen to catch."""
    ResultsDB(DB_PATH).close()
    yield


app = FastAPI(title="MACS+ Automation", lifespan=_lifespan)
# The Tauri webview's origin (tauri://localhost in prod, http://localhost:1420
# in dev) is cross-origin to http://127.0.0.1:<port>, so fetch() responses
# come back blocked unless we send the headers. The sidecar binds to 127.0.0.1
# only — allowing any origin is safe; nobody else can reach the port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition is not a CORS-safelisted response header, so without
    # this the webview cannot read it and a downloaded export lands as
    # "macs_both_<32-char-hex>.zip" instead of "macs_data_charts_Batch_1.zip".
    expose_headers=["Content-Disposition"],
)

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


class CustomSectionBody(BaseModel):
    name: str
    h: float
    b: float
    tw: float
    tf: float


class CustomDeckBody(BaseModel):
    name: str
    deck_type: str
    deck_depth: float
    deck_trug: float
    deck_top: float
    deck_bot: float
    deck_stiff_height: float


class CustomMeshBody(BaseModel):
    name: str
    main_area: float
    trans_area: float


def _get_all_sections() -> OrderedDict:
    """Merge custom sections (from DB), Blue Book UB, and Data.xml sections.

    Order: Custom sections first, then Blue Book UB sections (sorted by
    descending depth), then remaining Data.xml sections by family.
    """
    data = _get_ref_data()
    merged = OrderedDict()

    # 1. Custom sections from DB (always first)
    db = _get_db()
    try:
        customs = db.get_custom_sections()
    finally:
        db.close()

    for sec in customs:
        merged[sec["id"]] = {
            "family": "Custom",
            "name": f"{sec['name']} (Custom)",
            "h": sec["h"],
            "b": sec["b"],
            "tw": sec["tw"],
            "tf": sec["tf"],
        }

    # 2. Blue Book UB sections (sorted largest-to-smallest by h)
    bb_sections = get_blue_book_sections()
    for sec_id, sec in sorted(bb_sections.items(), key=lambda x: -x[1]["h"]):
        if sec_id not in merged:
            merged[sec_id] = sec

    # 3. Remaining Data.xml sections
    for sec_id, sec in data["sections"].items():
        if sec_id not in merged:
            merged[sec_id] = sec

    return merged


def _get_all_decks() -> OrderedDict:
    """Merge custom decks (from DB) with Data.xml decks.

    Custom decks appear first. Keys match the format resolve_deck() expects.
    """
    data = _get_ref_data()
    merged = OrderedDict()

    db = _get_db()
    try:
        customs = db.get_custom_decks()
    finally:
        db.close()

    for d in customs:
        merged[d["id"]] = {
            "name": f"{d['name']} (Custom)",
            "deck_type": d["deck_type"],
            "deck_depth": d["deck_depth"],
            "deck_trug": d["deck_trug"],
            "deck_top": d["deck_top"],
            "deck_bot": d["deck_bot"],
            "deck_stiff_height": d["deck_stiff_height"],
        }

    for deck_id, deck in data["decks"].items():
        merged[deck_id] = deck

    return merged


def _get_all_meshes() -> OrderedDict:
    """Merge custom meshes (from DB) with Data.xml meshes.

    Custom meshes appear first. Keys match the format resolve_mesh() expects.
    """
    data = _get_ref_data()
    merged = OrderedDict()

    db = _get_db()
    try:
        customs = db.get_custom_meshes()
    finally:
        db.close()

    for m in customs:
        merged[m["id"]] = {
            "name": f"{m['name']} (Custom)",
            "mainArea": m["main_area"],
            "transArea": m["trans_area"],
        }

    for mesh_id, mesh in data["meshes"].items():
        merged[mesh_id] = mesh

    return merged


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
    "slab_weight": "Slab Weight (kN/m²)",
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

# In-memory SSE pub/sub. The sweep worker thread publishes per-run and
# batch-done events; the /api/sweeps/events endpoint serves them as
# text/event-stream to the React dashboard.
sweep_broker = Broker()


COM_MAX_RETRIES = 3
COM_RETRY_DELAY = 2.0  # seconds between retries
COM_RUN_DELAY = 0.5    # seconds between successive runs


def _run_single_com(params: dict, sections_db: dict) -> dict:
    """Run a single MACS+ COM call with retries on COM errors.

    Uses engine.run_one_com(), which spawns an isolated com_runner subprocess.
    """
    from macs_automation.engine import run_one_com
    from pywintypes import com_error

    last_error = None
    for attempt in range(1, COM_MAX_RETRIES + 1):
        try:
            return run_one_com(params, sections_db)
        except com_error as e:
            last_error = e
            if attempt < COM_MAX_RETRIES:
                time.sleep(COM_RETRY_DELAY * attempt)
        except RuntimeError as e:
            # Bridge or COM failure; retry once in case transient
            last_error = e
            if attempt < COM_MAX_RETRIES:
                time.sleep(COM_RETRY_DELAY * attempt)
        except Exception:
            raise
    raise last_error


def _run_sweep_background(combinations: list[dict], sections_db: dict, mode: str = "sweep"):
    """Run a sweep in a background thread with COM init per run.

    Publishes a `run_completed` event after each insert and a `batch_done`
    event when the loop exits, both via sweep_broker. Run failures are
    inserted with their error string and emitted (the sweep does not abort).
    """
    batch_id = combinations[0].get("_batch_id") if combinations else None
    total = len(combinations)

    with _sweep_lock:
        _sweep_state["active"] = True
        _sweep_state["total"] = total
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
                run_id = db.insert_run(params, outputs=outputs)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                run_id = db.insert_run(params, error=error_msg)
                with _sweep_lock:
                    _sweep_state["errors"] += 1
                    _sweep_state["error_log"].append(error_msg)
                    if len(_sweep_state["error_log"]) > 10:
                        _sweep_state["error_log"] = _sweep_state["error_log"][-10:]

            with _sweep_lock:
                _sweep_state["completed"] += 1
                completed_count = _sweep_state["completed"]
                error_count = _sweep_state["errors"]

            try:
                run_row = db.get_run(run_id)
                _attach_status(run_row)
            except Exception:
                run_row = {"id": run_id, "batch_id": batch_id}
            sweep_broker.publish({
                "type": "run_completed",
                "run": run_row,
                "batch_id": batch_id,
                "total": total,
                "completed": completed_count,
                "errors": error_count,
            })

            time.sleep(COM_RUN_DELAY)
    finally:
        db.close()
        with _sweep_lock:
            _sweep_state["active"] = False
            final_completed = _sweep_state["completed"]
            final_errors = _sweep_state["errors"]
        sweep_broker.publish({
            "type": "batch_done",
            "batch_id": batch_id,
            "total": total,
            "completed": final_completed,
            "errors": final_errors,
        })


# ─── API: Custom sections ────────────────────────────────────────────────────

@app.post("/api/custom-sections")
def api_add_custom_section(body: CustomSectionBody):
    """Create a new custom beam section."""
    db = _get_db()
    sec_id = db.add_custom_section(body.name, body.h, body.b, body.tw, body.tf)
    sec = {"id": sec_id, "name": body.name, "h": body.h, "b": body.b, "tw": body.tw, "tf": body.tf}
    db.close()
    return sec


@app.get("/api/custom-sections")
def api_list_custom_sections():
    """List all custom beam sections."""
    db = _get_db()
    sections = db.get_custom_sections()
    db.close()
    return sections


@app.delete("/api/custom-sections/{sec_id}")
def api_delete_custom_section(sec_id: str):
    """Delete a custom beam section."""
    db = _get_db()
    db.delete_custom_section(sec_id)
    db.close()
    return {"ok": True}


# ─── API: Custom decks ────────────────────────────────────────────────────────

@app.post("/api/custom-decks")
def api_add_custom_deck(body: CustomDeckBody):
    """Create a new custom deck profile."""
    db = _get_db()
    deck_id = db.add_custom_deck(
        body.name, body.deck_type, body.deck_depth, body.deck_trug,
        body.deck_top, body.deck_bot, body.deck_stiff_height,
    )
    result = {
        "id": deck_id, "name": body.name, "deck_type": body.deck_type,
        "deck_depth": body.deck_depth, "deck_trug": body.deck_trug,
        "deck_top": body.deck_top, "deck_bot": body.deck_bot,
        "deck_stiff_height": body.deck_stiff_height,
    }
    db.close()
    return result


@app.get("/api/custom-decks")
def api_list_custom_decks():
    """List all custom deck profiles."""
    db = _get_db()
    decks = db.get_custom_decks()
    db.close()
    return decks


@app.delete("/api/custom-decks/{deck_id}")
def api_delete_custom_deck(deck_id: str):
    """Delete a custom deck profile."""
    db = _get_db()
    db.delete_custom_deck(deck_id)
    db.close()
    return {"ok": True}


# ─── API: Custom meshes ───────────────────────────────────────────────────────

@app.post("/api/custom-meshes")
def api_add_custom_mesh(body: CustomMeshBody):
    """Create a new custom mesh."""
    db = _get_db()
    mesh_id = db.add_custom_mesh(body.name, body.main_area, body.trans_area)
    result = {
        "id": mesh_id, "name": body.name,
        "main_area": body.main_area, "trans_area": body.trans_area,
    }
    db.close()
    return result


@app.get("/api/custom-meshes")
def api_list_custom_meshes():
    """List all custom meshes."""
    db = _get_db()
    meshes = db.get_custom_meshes()
    db.close()
    return meshes


@app.delete("/api/custom-meshes/{mesh_id}")
def api_delete_custom_mesh(mesh_id: str):
    """Delete a custom mesh."""
    db = _get_db()
    db.delete_custom_mesh(mesh_id)
    db.close()
    return {"ok": True}


# ─── API: Health ─────────────────────────────────────────────────────────────

_MACS_FOLDER_RE = re.compile(r"^MACS\+_?(.+)$")


def _macs_install_info() -> dict:
    """Detect MACS+ install state via the full detection chain.

    Returns a dict with:
      - `data_xml`: bool — whether `Data.xml` was found anywhere.
      - `com`: bool — whether `HKCR\\SCTI11.FRACOF` (or SCTI9) is registered.
      - `version`: str|None — numeric suffix from the `MACS+_NNN` segment.
      - `install_path`: str|None — `data_xml.parent.parent.parent`, or null.
      - `attempted_paths`: list[str] — every mechanism tried (for support diag).

    Re-runs the detection chain only when the cached path went away — the
    chain itself is cached at the `macs_detect` module level.
    """
    result = macs_detect.detect()
    return {
        "data_xml": result.data_xml_path is not None
                    and result.data_xml_path.is_file(),
        "com": result.com_registered,
        "version": result.version,
        "install_path": str(result.install_path) if result.install_path else None,
        "attempted_paths": list(result.attempted_paths),
    }


@app.get("/healthz")
def healthz():
    """Tauri shell hits this after spawning the sidecar to confirm liveness
    and to decide whether to show the MACS+ install dialog.

    Back-compat: `macs_installed` and `macs_version` keys retain their
    rc.5 semantics — `macs_installed` mirrors `data_xml` (Data.xml file
    exists), `macs_version` is the parsed `MACS+_NNN` suffix or null.
    Added in #23: `data_xml`, `com`, `install_path`, `attempted_paths`.
    """
    info = _macs_install_info()
    return {
        "sidecar": "alive",
        "macs_installed": info["data_xml"],
        "macs_version": info["version"],
        "data_xml": info["data_xml"],
        "com": info["com"],
        "install_path": info["install_path"],
        "attempted_paths": info["attempted_paths"],
    }


# ─── API: Install-location override ──────────────────────────────────────────


class InstallLocationBody(BaseModel):
    folder: str


@app.post("/api/install-location")
def api_set_install_location(body: InstallLocationBody):
    """Validate a user-picked MACS+ folder, persist the resolved Data.xml
    path to `settings`, and invalidate the detection cache so the next
    `/healthz` reflects the new location.

    Stores the full file path to `Data.xml` (not the folder) because that
    matches the existing `MACS_DATA_PATH` env-var contract. The Tauri
    shell reads this on startup and injects `MACS_DATA_PATH` when spawning
    the sidecar.
    """
    folder = Path(body.folder)
    ok, validated, err = macs_detect.validate_install_folder(folder)
    if not ok:
        return JSONResponse(
            {"ok": False, "validated_path": None, "error": err},
            status_code=400,
        )

    db = _get_db()
    try:
        db.set_setting("macs_data_path", str(validated))
    finally:
        db.close()

    # Reload reference data so the in-memory cache picks up the new install
    # within this sidecar's lifetime — but env-var propagation to the engine
    # requires a sidecar restart, which the Tauri shell prompts for.
    global _ref_data
    _ref_data = None
    macs_detect.reset_cache()
    # Also flip the in-process default so subsequent `_find_macs_data_xml()`
    # callers see the override without a restart.
    os.environ["MACS_DATA_PATH"] = str(validated)

    return {"ok": True, "validated_path": str(validated), "error": None}


@app.get("/api/install-location")
def api_get_install_location():
    """Return the currently persisted manual override, if any."""
    db = _get_db()
    try:
        value = db.get_setting("macs_data_path")
    finally:
        db.close()
    return {"macs_data_path": value}


# ─── API: Reference data endpoints ───────────────────────────────────────────

@app.get("/api/sections")
def api_sections():
    """All sections grouped by family (includes custom and Blue Book)."""
    all_sections = _get_all_sections()
    grouped = {}
    for sec_id, sec in all_sections.items():
        fam = sec["family"]
        if fam not in grouped:
            grouped[fam] = []
        grouped[fam].append({"id": sec_id, "name": sec["name"], "h": sec["h"], "b": sec["b"]})
    return grouped


@app.get("/api/decks")
def api_decks():
    return _get_all_decks()


@app.get("/api/meshes")
def api_meshes():
    return _get_all_meshes()


@app.get("/api/ref-data")
def api_ref_data():
    """Single roundtrip for the React config form: sections + decks + meshes
    + the occupancy presets used for fire-load distributions."""
    presets = [
        {"name": name, "mean": info["mean"], "type": info["type"], "cov": info["cov"]}
        for name, info in FIRE_LOAD_PRESETS.items()
        if name != "Opening Factor"
    ]
    return {
        "sections": api_sections(),
        "decks": _get_all_decks(),
        "meshes": _get_all_meshes(),
        "defaults": dict(DEFAULTS),
        "occupancy_presets": presets,
    }


# ─── Naming + .frc provenance ────────────────────────────────────────────────

# Keys the config page may send inside the `meta` block. They are labels and
# provenance, never engine inputs, so they travel underscore-prefixed once
# inside a params dict — the same convention as _batch_id / _sample_index.
_META_KEYS = ("name", "project_name", "frc_import_id")


def _pop_meta(request_body: dict) -> dict:
    """Remove and return the `meta` block from a submit payload.

    Mutates `request_body` so the remainder is a clean spec — `meta` must
    never survive into the sweep config or an engine params dict.
    """
    meta = request_body.pop("meta", None)
    if not isinstance(meta, dict):
        return {}
    return {k: meta[k] for k in _META_KEYS if meta.get(k) not in (None, "")}


def _frc_summary(db, frc_id: Optional[str]) -> Optional[dict]:
    """Resolve a stored .frc to `{id, filename, project}` for API responses.

    The XML is deliberately excluded — a batches list would otherwise carry a
    ~6 KB blob per row. Callers that want the file fetch /api/frc-imports/{id}.
    """
    stored = db.get_frc_import(frc_id)
    if stored is None:
        return None
    return {
        "id": stored["id"],
        "filename": stored["filename"],
        "project": stored["project"],
    }


# ─── API: Run endpoints ──────────────────────────────────────────────────────

@app.post("/api/runs")
def api_submit_run(request_body: dict):
    """Submit a single MACS+ run (synchronous). Spawns an isolated com_runner subprocess."""
    all_sections = _get_all_sections()
    all_decks = _get_all_decks()
    all_meshes = _get_all_meshes()
    params = dict(DEFAULTS)

    # A single run has no batch to hang labels off, so its name / project /
    # .frc pointer ride on the run row itself.
    meta = _pop_meta(request_body)

    # Apply user-provided values
    for key, value in request_body.items():
        internal_key = PARAM_ALIASES.get(key, key)
        params[internal_key] = value

    for key, value in meta.items():
        params[f"_{key}"] = value

    # Resolve deck and mesh
    resolve_deck(params, all_decks)
    resolve_mesh(params, all_meshes)

    try:
        outputs = _run_single_com(params, all_sections)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        db = _get_db()
        run_id = db.insert_run(params, error=error_msg)
        db.close()
        return JSONResponse({"id": run_id, "error": error_msg}, status_code=500)

    db = _get_db()
    run_id = db.insert_run(params, outputs=outputs)
    db.close()
    status = compute_status(outputs)
    return {
        "id": run_id,
        "uf_max": outputs["uf_max"],
        "duration_ms": outputs["duration_ms"],
        "overall_pass": status["overall_pass"],
        "checks": status["checks"],
    }


MAX_SWEEP_RUNS = 30000


def _estimate_run_count(config: dict) -> int:
    """Cheap projected-run-count estimate without building the combinations list.

    Used for the 30k hard-cap check before generate_combinations() allocates
    anything. Paired mode: max array length (unequal-length is rejected later
    by generate_combinations with a 400). LHS: n_samples. No sweep: 1.
    """
    if config.get("sampling") == "lhs":
        return int(config.get("n_samples", 0))
    sweep = config.get("sweep") or {}
    if not sweep:
        return 1
    lengths = [len(v) if isinstance(v, list) else 1 for v in sweep.values()]
    return max(lengths) if lengths else 1


@app.post("/api/sweeps")
def api_submit_sweep(request_body: dict):
    """Submit a sweep config (starts background job)."""
    with _sweep_lock:
        if _sweep_state["active"]:
            return JSONResponse({"error": "A sweep is already running"}, status_code=409)

    # Strip the labels/provenance block before anything reads the spec — they
    # belong on the batch row, not in config_json and not in the params dicts.
    meta = _pop_meta(request_body)
    if meta.get("frc_import_id"):
        db = _get_db()
        try:
            known = db.get_frc_import(meta["frc_import_id"]) is not None
        finally:
            db.close()
        if not known:
            return JSONResponse(
                {"error": f"Unknown frc_import_id {meta['frc_import_id']!r}"},
                status_code=400,
            )

    projected = _estimate_run_count(request_body)
    if projected > MAX_SWEEP_RUNS:
        return JSONResponse(
            {"error": f"Too many runs (got {projected}, max {MAX_SWEEP_RUNS})"},
            status_code=400,
        )

    all_sections = _get_all_sections()
    all_decks = _get_all_decks()
    all_meshes = _get_all_meshes()

    # Detect mode from request
    mode = "lhs" if request_body.get("sampling") == "lhs" else "sweep"

    # Dispatch to generate_combinations() which handles paired (default) and LHS.
    # Unequal-length paired arrays surface as ValueError → 400.
    try:
        combinations = generate_combinations(request_body)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    # Generate batch_id and record batch metadata, persisting the full
    # sweep spec so the dashboard can derive varying/fixed params and the
    # *Rerun batch* button (slice 2) can hydrate the form.
    batch_id = uuid.uuid4().hex
    config_json = json.dumps(request_body)
    db = _get_db()
    db.insert_batch(batch_id, mode=mode, total_expected=len(combinations),
                    config_json=config_json,
                    name=meta.get("name"),
                    project_name=meta.get("project_name"),
                    frc_import_id=meta.get("frc_import_id"))
    db.close()

    # Inject batch_id into each combination
    for p in combinations:
        p["_batch_id"] = batch_id

    # Resolve deck/mesh for each
    for p in combinations:
        resolve_deck(p, all_decks)
        resolve_mesh(p, all_meshes)

    # Start background thread
    t = threading.Thread(
        target=_run_sweep_background,
        args=(combinations, all_sections, mode),
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


@app.get("/api/replay/host-check")
def api_replay_host_check():
    """Is this machine fit to produce MACS+ PDF evidence?

    Worth showing before anyone starts: the display-scaling trap yields correct
    numbers with silently squashed charts, so it cannot be left to be noticed.
    """
    return pdf_evidence.host_check()


@app.post("/api/batches/{batch_id}/pdf-evidence")
def api_start_pdf_evidence(batch_id: str, request_body: Optional[dict] = None):
    """Replay a completed batch through MACS+ to produce one real PDF per run."""
    body = request_body or {}
    db = _get_db()
    try:
        runs = db.get_batch_runs(batch_id)
    finally:
        db.close()
    if not runs:
        return JSONResponse({"error": f"Unknown or empty batch {batch_id}"}, status_code=404)

    sample = body.get("sample")
    if sample is not None:
        try:
            sample = int(sample)
        except (TypeError, ValueError):
            return JSONResponse({"error": "sample must be a number"}, status_code=400)
        if sample < 1:
            return JSONResponse({"error": "sample must be at least 1"}, status_code=400)

    result = pdf_evidence.start(batch_id, str(DB_PATH), sample=sample,
                                seed=body.get("seed"), out_dir=body.get("out_dir"))
    if "error" in result:
        return JSONResponse(result, status_code=409)
    return result


@app.post("/api/batches/{batch_id}/pdf-evidence/reset")
def api_reset_pdf_evidence(batch_id: str, request_body: Optional[dict] = None):
    """Forget the job so the batch can start fresh.

    `delete_pdfs` discards the output as well; it defaults to false because
    those PDFs can be hours of work and nothing else replaces them.
    """
    body = request_body or {}
    result = pdf_evidence.reset(batch_id, delete_pdfs=bool(body.get("delete_pdfs")))
    if "error" in result:
        return JSONResponse(result, status_code=409)
    return result


@app.post("/api/batches/{batch_id}/pdf-evidence/stop")
def api_stop_pdf_evidence(batch_id: str):
    """Pause after the current run. Resuming is the same start call again."""
    result = pdf_evidence.stop(batch_id)
    if "error" in result:
        return JSONResponse(result, status_code=409)
    return result


@app.get("/api/batches/{batch_id}/pdf-evidence")
def api_pdf_evidence_status(batch_id: str):
    return pdf_evidence.status(batch_id)


@app.get("/api/runs")
def api_list_runs(limit: int = 50, offset: int = 0, batch_id: Optional[str] = None):
    """List runs with pagination, or all runs in a batch when batch_id is given.

    The batch_id filter is what the dashboard at /batches/:id uses to backfill
    already-completed runs before opening the SSE stream.
    """
    db = _get_db()
    if batch_id is not None:
        runs = db.get_batch_runs(batch_id)
    else:
        runs = db.get_runs(limit=limit, offset=offset)
    stats = db.get_stats()
    db.close()
    for r in runs:
        _attach_status(r)
    return {"runs": runs, "stats": stats}


@app.get("/api/batches")
def api_list_batches(limit: int = 20, offset: int = 0):
    """Paginated batches list with server-side aggregation.

    Each row carries the run/pass/fail/error counts plus `varying_params`
    and `fixed_params` derived from the stored sweep spec — the dashboard
    surfaces these as the per-batch summary.
    """
    db = _get_db()
    try:
        rows = db.get_batches(limit=limit, offset=offset)
        total = db.get_batches_count()
        batches = [_batch_response(db, row) for row in rows]
    finally:
        db.close()
    return {"batches": batches, "total": total}


def _batch_response(db, row: dict) -> dict:
    """Shape one batches row for the API — shared by the list and detail
    endpoints so they can't drift apart."""
    derived = varying_params_from_config(row.get("config_json"))
    successful = row["run_count"] - row["error_count"]
    return {
        "batch_id": row["batch_id"],
        "created_at": row["created_at"],
        "mode": row["mode"],
        "sampling": _config_sampling(row.get("config_json")),
        "name": row.get("name"),
        "project_name": row.get("project_name"),
        "frc": _frc_summary(db, row.get("frc_import_id")),
        "total_expected": row["total_expected"],
        "run_count": row["run_count"],
        "pass_count": row["pass_count"],
        "fail_count": max(successful - row["pass_count"], 0),
        "error_count": row["error_count"],
        "varying_params": derived["varying"],
        "fixed_params": derived["fixed"],
    }


@app.patch("/api/batches/{batch_id}")
def api_rename_batch(batch_id: str, request_body: dict):
    """Relabel a batch. Accepts `name` and/or `project_name`; an omitted field
    is left untouched and a blank one clears back to the short-id fallback.
    Renaming after the fact matters — you rarely know the right name until
    you've seen the results."""
    updates = {
        k: request_body[k]
        for k in ("name", "project_name")
        if k in request_body and isinstance(request_body[k], str)
    }
    db = _get_db()
    try:
        if not db.rename_batch(batch_id, **updates):
            return JSONResponse({"error": "Not found"}, status_code=404)
        row = next(
            (r for r in db.get_batches() if r["batch_id"] == batch_id), None
        )
        return _batch_response(db, row)
    finally:
        db.close()


@app.get("/api/batches/{batch_id}/setup")
def api_batch_setup(batch_id: str):
    """The configuration shared by every run in a batch.

    Derived from the stored run rows rather than the submitted spec, so it
    covers hand-configured batches, .frc-seeded ones, and legacy batches that
    predate config_json alike — and reflects what the engine actually received.
    See batch_setup.derive_setup for why that distinction matters.
    """
    db = _get_db()
    try:
        known = any(b["batch_id"] == batch_id for b in db.get_batches())
        if not known:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return derive_setup(db.get_batch_runs(batch_id))
    finally:
        db.close()


@app.get("/api/projects")
def api_list_projects():
    """Distinct project names across batches and ungrouped runs — feeds the
    config-page autocomplete and the dashboard filter."""
    db = _get_db()
    try:
        return {"projects": db.get_project_names()}
    finally:
        db.close()


@app.get("/api/frc-imports/{frc_id}")
def api_get_frc_import(frc_id: str):
    """Return a stored .frc, XML included, so the UI can offer *view original*
    / *save a copy* from a batch that was seeded from one."""
    db = _get_db()
    try:
        stored = db.get_frc_import(frc_id)
    finally:
        db.close()
    if stored is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return stored


def _config_sampling(config_json: Optional[str]) -> Optional[str]:
    """Return the sampling mode from a stored batch's config_json.

    Returns ``"paired"`` / ``"lhs"`` for new-style batches, or ``None`` for
    historical grid batches (#36). The dashboard uses this to gate the
    *Rerun batch* button — grid batches predate paired-mode and can't be
    re-run without a manual reconfigure.
    """
    if not config_json:
        return None
    try:
        return json.loads(config_json).get("sampling")
    except (json.JSONDecodeError, AttributeError):
        return None


@app.get("/api/batches/{batch_id}")
def api_get_batch(batch_id: str):
    """Single batch summary — same shape as a row in /api/batches. Lets
    the batch detail page decide between live-progress and analytical
    views without re-paging the full list."""
    db = _get_db()
    try:
        row = next(
            (r for r in db.get_batches() if r["batch_id"] == batch_id), None
        )
        if row is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return _batch_response(db, row)
    finally:
        db.close()


@app.get("/api/batches/{batch_id}/shear-check")
def api_batch_shear_check(batch_id: str):
    """List runs in a batch whose degree of shear connection is below the
    EN 1994-1-1 minimum, mirroring the MACS+ beam-check warning.

    This is advisory only — like MACS+ itself, it does NOT affect the run's
    pass/fail verdict (see status.compute_status). Inputs are read from the
    stored run rows, so already-completed batches are covered with no re-run.
    """
    db = _get_db()
    try:
        runs = db.get_batch_runs(batch_id)
    finally:
        db.close()
    sub_limit = [
        {"run_id": r.get("id"), "flags": flags}
        for r in runs
        if (flags := flags_for_run(r))
    ]
    return {"batch_id": batch_id, "checked": len(runs), "sub_limit_runs": sub_limit}


# ─── Distribution endpoint for batch detail page ─────────────────────────────

# Whitelist enforced at the route layer — narrower than db.TIME_SERIES_COLUMNS
# because only these three feed the MACS+ Monte Carlo Summary charts.
_DISTRIBUTION_COLUMNS = frozenset({
    "total_plate_capacity", "lofl_temp", "mesh_temp",
})


@app.get("/api/batches/{batch_id}/distribution")
def api_batch_distribution(
    batch_id: str,
    column: str,
    spaghetti_n: int = 500,
):
    """Return spaghetti + exact server-side average for a batch's column.

    AnalyticalView hits this 3x (one per distribution chart). The shape mirrors
    what `DistributionChart` expects: an `average` curve, up to `spaghetti_n`
    individual run curves (stride-sampled when count > N), and the
    factored_hot min/max for the capacity chart's horizontal indicator.

    `column` is whitelisted to {total_plate_capacity, lofl_temp, mesh_temp}
    so the SQL interpolation in `get_batch_time_series_column` stays safe
    (same pattern as that method's own check, but tighter at the API layer
    so we never push other valid TIME_SERIES_COLUMNS to the client by
    accident).
    """
    if column not in _DISTRIBUTION_COLUMNS:
        return JSONResponse(
            {"error": f"Invalid column: {column!r}. "
                      f"Must be one of {sorted(_DISTRIBUTION_COLUMNS)}."},
            status_code=400,
        )
    if spaghetti_n < 1:
        spaghetti_n = 1

    db = _get_db()
    try:
        rows = db.get_batch_time_series_column(batch_id, column)
        runs = db.get_batch_successful_runs(batch_id)
    finally:
        db.close()

    # Group (run_id, time_min, value) tuples by run.
    by_run: "OrderedDict[int, list[tuple[float, float]]]" = OrderedDict()
    for run_id, time_min, value in rows:
        by_run.setdefault(run_id, []).append((float(time_min), float(value)))

    # Empty-state: no successful runs → 4-chart placeholder branch.
    if not by_run:
        return {
            "average": [],
            "spaghetti": [],
            "factored_hot_min": None,
            "factored_hot_max": None,
        }

    # ── Average: forward-fill each run onto the common time grid, then mean.
    # A fire that ends early is held at its final value, so the curve reflects
    # all runs at every instant (dominated by the many cooled runs) instead of
    # spiking and biasing high where exact timesteps don't coincide. Same
    # forward-fill used by report.py / report_docx so all three charts agree.
    avg_times, avg_vals = _forward_filled_average(by_run)
    average: list[list[float]] = [[t, v] for t, v in zip(avg_times, avg_vals)]
    end_t = avg_times[-1] if avg_times else None

    # ── Spaghetti: stride-sample down to spaghetti_n (visually identical
    # density at 10k scale, per issue rendering strategy).
    run_ids = list(by_run.keys())
    if len(run_ids) > spaghetti_n:
        # Stride pick ~evenly-spaced indices so the sample preserves order.
        stride = len(run_ids) / float(spaghetti_n)
        picked_idx = sorted({int(i * stride) for i in range(spaghetti_n)})
        picked_idx = [i for i in picked_idx if i < len(run_ids)]
        picked = [run_ids[i] for i in picked_idx]
    else:
        picked = run_ids

    spaghetti = []
    for rid in picked:
        pts = sorted(by_run[rid])
        times = [p[0] for p in pts]
        values = [p[1] for p in pts]
        if end_t is not None:
            # Hold each run's last value flat to the common end so the bands run
            # to the axis edge like MACS+ (forward-fill the spaghetti, not just
            # the average).
            times, values = _extend_flat(times, values, end_t)
        spaghetti.append({
            "run_id": rid,
            "points": [[t, v] for t, v in zip(times, values)],
        })

    # ── Factored hot range: only meaningful for the capacity chart.
    if column == "total_plate_capacity":
        factored_values = [r.get("factored_hot") for r in runs
                           if r.get("factored_hot") is not None]
        if factored_values:
            f_min = min(factored_values)
            f_max = max(factored_values)
        else:
            f_min = None
            f_max = None
    else:
        f_min = None
        f_max = None

    return {
        "average": average,
        "spaghetti": spaghetti,
        "factored_hot_min": f_min,
        "factored_hot_max": f_max,
    }


@app.get("/api/runs/ungrouped")
def api_list_ungrouped_runs(limit: int = 50, offset: int = 0):
    """Paginated runs where batch_id IS NULL, newest first."""
    db = _get_db()
    try:
        runs = db.get_ungrouped_runs(limit=limit, offset=offset)
        total = db.get_ungrouped_runs_count()
        for r in runs:
            # Ungrouped by definition — no batch to inherit from, so this only
            # resolves the run's own .frc pointer.
            r["frc"] = _frc_summary(db, r.get("frc_import_id"))
    finally:
        db.close()
    for r in runs:
        _attach_status(r)
    return {"runs": runs, "total": total}


@app.get("/api/stats")
def api_stats():
    """Global summary counts. Split out from /api/runs so the dashboard's
    stat cards can refresh independently of the runs list."""
    db = _get_db()
    try:
        return db.get_stats()
    finally:
        db.close()


async def _format_sse_events(broker: Broker):
    """Format every event from the broker as one SSE record. Returns when a
    batch_done event passes through, so each subscriber owns a single batch's
    lifecycle.

    Extracted from the route handler so it can be unit-tested without the HTTP
    transport (TestClient streams hang on Windows; AsyncClient + ASGITransport
    has its own quirks). Tests drive this generator with a fresh Broker and
    compare its output.
    """
    async for event in broker.subscribe():
        event_type = event.get("type", "message")
        payload = json.dumps(event, default=str)
        yield f"event: {event_type}\ndata: {payload}\n\n"
        if event_type == "batch_done":
            return


@app.get("/api/sweeps/events")
async def api_sweep_events():
    """Server-Sent Events stream of sweep events.

    Each event is one of two types:
      - run_completed: emitted after each run inserts into the DB
      - batch_done:    emitted when the sweep worker exits

    The stream closes itself after batch_done so each batch's dashboard owns
    one connection lifecycle. Subscribers connecting between sweeps see no
    events until the next sweep starts.
    """
    return StreamingResponse(
        _format_sse_events(sweep_broker),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/runs/{run_id}")
def api_get_run(run_id: int):
    """Get single run detail."""
    db = _get_db()
    try:
        run = db.get_run(run_id)
        if run is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        _attach_provenance(db, run)
    finally:
        db.close()
    # Advisory shear-connection warning (EN 1994-1-1 minimum), same as the batch
    # endpoint — does not affect the pass/fail verdict.
    run["shear_flags"] = flags_for_run(run)
    return _attach_status(run)


def _attach_provenance(db, run: dict) -> dict:
    """Resolve a run's effective name / project / .frc for display.

    A run inside a batch stores NULLs and inherits the batch's labels, so a
    rename can't leave the batch and its runs disagreeing. An ungrouped single
    run carries its own. Mutates and returns `run`.
    """
    frc_id = run.get("frc_import_id")
    if run.get("batch_id"):
        batch = next(
            (b for b in db.get_batches() if b["batch_id"] == run["batch_id"]), None
        )
        if batch is not None:
            run["name"] = run.get("name") or batch.get("name")
            run["project_name"] = run.get("project_name") or batch.get("project_name")
            frc_id = frc_id or batch.get("frc_import_id")
    run["frc"] = _frc_summary(db, frc_id)
    return run


@app.get("/api/runs/{run_id}/setup")
def api_run_setup(run_id: int):
    """The inputs a single run was calculated with.

    Same shape as the batch endpoint (a one-run batch varies in nothing), so
    the UI renders both with one component. Works for errored runs too — the
    inputs are recorded before the engine is invoked, which is precisely when
    you want to see them.
    """
    db = _get_db()
    try:
        run = db.get_run(run_id)
        if run is None:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return derive_setup([run])
    finally:
        db.close()


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

    # Store the file verbatim (only once it has parsed — a rejected upload
    # leaves no row). The returned id is what the config page sends back in
    # its `meta` block, tying the resulting batch to this exact file.
    db = _get_db()
    try:
        frc_id = db.record_frc_import(
            file.filename or "imported.frc", xml_string, result.get("project")
        )
    finally:
        db.close()

    return {**result, "frc_import_id": frc_id, "frc_filename": file.filename}


# ─── Report download ─────────────────────────────────────────────────────────

@app.get("/api/report/docx")
def api_report_docx(batch_id: str | None = None):
    """Generate and download a DOCX report, optionally filtered to a batch."""
    import traceback
    from macs_automation.report_docx import generate_batch_docx
    db = _get_db()
    try:
        docx_path = generate_batch_docx(db, batch_id=batch_id)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            {"detail": str(e), "traceback": traceback.format_exc()},
            status_code=500,
        )
    finally:
        db.close()
    filename = f"macs_report_{batch_id}.docx" if batch_id else "macs_report.docx"
    # Use str(path) so FileResponse works reliably on Windows (Path can cause 500)
    return FileResponse(
        str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


# What a download can contain: the CSVs, the rendered charts, or both.
_EXPORT_MODES = {
    "data": (True, False),
    "charts": (False, True),
    "both": (True, True),
}


@app.get("/api/report/zip")
def api_report_zip(batch_id: str | None = None, include: str = "data"):
    """Download a batch's results as a ZIP — data, charts, or both.

    ``include=data`` gives the CSV set plus a runnable plotting script; the CSV
    headers reproduce the old pdfplumber pipeline's exactly, so the matplotlib
    scripts engineers already have keep working on it. ``include=charts`` gives
    the four rendered PNGs for anyone who just wants the pictures, styled
    identically to what the bundled script produces.
    """
    from macs_automation.report import generate_report_zip

    if include not in _EXPORT_MODES:
        return JSONResponse(
            {"error": f"Unknown include={include!r}; "
                      f"expected one of {', '.join(_EXPORT_MODES)}"},
            status_code=400,
        )
    include_data, include_plots = _EXPORT_MODES[include]

    db = _get_db()
    try:
        label = "all_runs"
        if batch_id is not None:
            row = next(
                (r for r in db.get_batches() if r["batch_id"] == batch_id), None
            )
            if row is None:
                return JSONResponse({"error": "Not found"}, status_code=404)
            label = row.get("name") or batch_id[:8]
        zip_path = generate_report_zip(
            db, batch_id=batch_id, label=label,
            include_data=include_data, include_plots=include_plots,
        )
    except Exception as e:
        logging.getLogger(__name__).exception("Data export failed")
        return JSONResponse({"detail": str(e)}, status_code=500)
    finally:
        db.close()

    kind = {"data": "data", "charts": "charts", "both": "data_charts"}[include]
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"macs_{kind}_{_sanitise_label(label)}.zip",
    )


# 1x1 transparent PNG so chart <img> tags don't break when there's no data
_PLACEHOLDER_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@app.get("/api/report/chart/{chart_type}")
def api_report_chart(chart_type: str, batch_id: str | None = None):
    """Serve a PNG chart image for a batch (or all runs).

    chart_type: 'scatter' or 'capacity'
    Returns a placeholder image when there is no data so <img> tags don't break.
    """
    from fastapi.responses import Response
    from macs_automation.report_docx import _render_scatter_chart, _render_timeseries_chart

    db = _get_db()
    png_bytes = None
    try:
        if batch_id:
            runs = db.get_batch_successful_runs(batch_id)
        else:
            runs = db.get_successful_runs()

        if chart_type == "scatter":
            png_bytes = _render_scatter_chart(runs)
        elif chart_type == "capacity":
            factored_hot = runs[0].get("factored_hot") if runs else None
            png_bytes = _render_timeseries_chart(
                db, "total_plate_capacity",
                "Total Slab Capacity (kN/m2)",
                runs, batch_id=batch_id, hline_value=factored_hot,
            )
    except Exception:
        png_bytes = None
    finally:
        db.close()

    if png_bytes is None:
        return Response(content=_PLACEHOLDER_PNG, media_type="image/png")

    return Response(content=png_bytes, media_type="image/png")


def _configure_file_logging(log_dir: str) -> None:
    """Attach a 5MB × 5 RotatingFileHandler to the root logger.

    The Tauri shell points `--log-dir` at %LOCALAPPDATA%\\i-macs\\logs in production;
    operators can point at the resolved sidecar.log when the SidecarErrorScreen
    surfaces a failure (slice 5). Uvicorn loggers propagate to root because
    main() invokes uvicorn.run with log_config=None.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path / "sidecar.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


def main(argv: Optional[list[str]] = None) -> None:
    import sys
    effective_argv = sys.argv[1:] if argv is None else argv
    if effective_argv and effective_argv[0] == "--com-runner":
        # Frozen builds have a single exe entry point. engine.run_one_com()
        # spawns this same exe with `--com-runner` so we re-enter as the COM
        # subprocess instead of starting another FastAPI server.
        from macs_automation import com_runner
        com_runner.main()
        return

    parser = argparse.ArgumentParser(prog="macs_automation", description="MACS+ Automation sidecar")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port to bind")
    parser.add_argument("--log-dir", type=str, default=None, help="Directory for sidecar.log (rotating, 5 MB × 5)")
    args = parser.parse_args(argv)

    if args.log_dir:
        _configure_file_logging(args.log_dir)

    import uvicorn
    # http/ws are pinned, not "auto": auto-selection does `try: import
    # httptools/websockets`, and on an updated install those imports can hit
    # stale packages left behind by the NSIS overlay updater (rc.13 died at
    # boot exactly this way). h11 covers everything the sidecar serves —
    # plain HTTP on localhost, no websocket endpoints.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_config=None,
                http="h11", ws="none")


if __name__ == "__main__":
    main()
