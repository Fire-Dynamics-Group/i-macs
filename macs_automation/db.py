"""SQLite database schema and helpers for storing MACS+ batch results."""

import hashlib
import json
import os
import socket
import sqlite3
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT,
    device_name TEXT,
    app_version TEXT,
    synced_at TEXT,
    run_timestamp TEXT,
    -- Input: Geometry
    span1 REAL, span2 REAL, numbeam INTEGER,
    -- Input: Deck
    steel_deck INTEGER, deck_name TEXT, deck_type TEXT,
    deck_depth REAL, deck_trug REAL, deck_top REAL, deck_bot REAL, deck_stiff_height REAL,
    -- Input: Slab
    conc_type TEXT, conc_lambda REAL, fck REAL, slab_depth REAL,
    mesh_type TEXT, mesh_area_max REAL, mesh_area_min REAL, mesh_axis REAL, mesh_strength REAL,
    -- Input: Beams (unprotected + 4 sides)
    u_sec_size TEXT, u_sec_fy INTEGER, ush_con REAL,
    side_a_sec TEXT, side_a_fy INTEGER, side_a_edge INTEGER, side_a_composite INTEGER, side_a_sh_con REAL,
    side_b_sec TEXT, side_b_fy INTEGER, side_b_edge INTEGER, side_b_composite INTEGER, side_b_sh_con REAL,
    side_c_sec TEXT, side_c_fy INTEGER, side_c_edge INTEGER, side_c_composite INTEGER, side_c_sh_con REAL,
    side_d_sec TEXT, side_d_fy INTEGER, side_d_edge INTEGER, side_d_composite INTEGER, side_d_sh_con REAL,
    -- Input: Loading
    lead_var_act REAL, othr_var_act REAL, cold_perm REAL, slab_weight REAL,
    lead_var_fac REAL, othr_var_fac REAL,
    -- Input: Fire
    method TEXT, time_limit INTEGER,
    Lc REAL, Bc REAL, Hc REAL, Hw REAL, Lw REAL,
    window_percent REAL, qf REAL, Bfac REAL, combustion_factor REAL, growth_rate REAL,
    -- Output: Summary
    comp_failure INTEGER,
    mb1_reqd REAL, mb2_reqd REAL, factored_hot REAL,
    uf_max REAL,
    max_temperature REAL, max_deflection REAL, max_slab_cap REAL, max_beam_cap REAL, max_total_cap REAL,
    -- Output: Perimeter beams
    side_a_load_ratio REAL, side_a_critical_temp REAL,
    side_b_load_ratio REAL, side_b_critical_temp REAL,
    side_c_load_ratio REAL, side_c_critical_temp REAL,
    side_d_load_ratio REAL, side_d_critical_temp REAL,
    -- LHS metadata
    sample_index INTEGER, seed INTEGER,
    -- Batch grouping
    batch_id TEXT,
    -- Naming + provenance. Populated for *ungrouped* single runs, which have
    -- no batch to hang a name off; runs inside a batch leave these NULL and
    -- inherit from batches (one mutable source of truth, so a rename can't
    -- leave 30k rows disagreeing with their parent).
    name TEXT, project_name TEXT, frc_import_id TEXT,
    -- Metadata
    error TEXT, duration_ms REAL,
    -- Provenance: FRACOF engine version that produced this run (e.g. "2.0.0.2")
    engine_version TEXT
);

CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    created_at TEXT,
    mode TEXT,
    total_expected INTEGER,
    config_json TEXT,
    -- Human-friendly labels so the dashboard shows something better than a
    -- 32-char hex id, plus a pointer to the .frc this batch was seeded from.
    name TEXT,
    project_name TEXT,
    frc_import_id TEXT,
    device_name TEXT,
    app_version TEXT,
    synced_at TEXT
);

-- Imported .frc files, stored verbatim so a batch is traceable back to the
-- exact file that seeded it (and can be re-opened or diffed later). The
-- primary key is the sha256 of the XML: repeat imports of the same file
-- collapse to one row, and the identity stays stable across devices — an
-- autoincrement id would collide once cloud sync (#11) merges two machines.
CREATE TABLE IF NOT EXISTS frc_imports (
    id TEXT PRIMARY KEY,
    filename TEXT,
    xml TEXT,
    project_json TEXT,
    imported_at TEXT,
    device_name TEXT,
    app_version TEXT,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS time_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id),
    time_step INTEGER,
    time_min REAL,
    fire_temp REAL,
    lofl_temp REAL, mesh_temp REAL,
    slabtop_temp REAL, slabbot_temp REAL,
    beam_hot_capacity REAL, deflection REAL,
    slab_yield REAL, enhancement REAL,
    slab_cap REAL, total_plate_capacity REAL,
    utilization_factor REAL
);

CREATE INDEX IF NOT EXISTS idx_time_series_run_id ON time_series(run_id);

CREATE TABLE IF NOT EXISTS custom_sections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    h REAL NOT NULL,
    b REAL NOT NULL,
    tw REAL NOT NULL,
    tf REAL NOT NULL,
    created_at TEXT,
    uuid TEXT,
    device_name TEXT,
    app_version TEXT,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS custom_decks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    deck_type TEXT NOT NULL,
    deck_depth REAL NOT NULL,
    deck_trug REAL NOT NULL,
    deck_top REAL NOT NULL,
    deck_bot REAL NOT NULL,
    deck_stiff_height REAL NOT NULL,
    created_at TEXT,
    uuid TEXT,
    device_name TEXT,
    app_version TEXT,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS custom_meshes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    main_area REAL NOT NULL,
    trans_area REAL NOT NULL,
    created_at TEXT,
    uuid TEXT,
    device_name TEXT,
    app_version TEXT,
    synced_at TEXT
);

-- Key/value store for app-level settings. v1 holds the user-picked
-- MACS_DATA_PATH override (#23). Intentionally NOT in cloud sync — install
-- location is per-machine.
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Tables that grow a uuid + device_name + app_version + synced_at quartet for
# multi-desktop cloud sync (#11). batches already has a TEXT primary key, so
# it doesn't need its own uuid — only the provenance columns.
_SYNC_PROVENANCE_TABLES_WITH_UUID = ("runs", "custom_sections", "custom_decks", "custom_meshes")
# frc_imports keys on a content hash, which is already device-stable, so like
# batches it needs the provenance stamps but not a synthetic uuid.
_SYNC_PROVENANCE_TABLES_NO_UUID = ("batches", "frc_imports")

# Combined pass predicate — must mirror compute_status() in status.py.
# A run passes only when the slab UF stays strictly below MACS+'s 1.001
# threshold (PrintP.js:388: `UF1Max < 1.001 ? 'strAdequate' : ...`) and every
# defined perimeter beam load ratio stays within its limit. NULL side ratios
# (sides that weren't analyzed) are treated as 0 so they don't block.
# COMPFAILURE is a MACS+ failure-mode *label*, not a pass/fail gate, so it is
# deliberately not part of this predicate.
def _blank_to_none(value: Optional[str]) -> Optional[str]:
    """Normalise user-typed labels: whitespace-only means "no name", so the
    UI falls back to the short batch id instead of rendering an empty cell."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _pass_where(table: str = "") -> str:
    p = f"{table}." if table else ""
    return (
        f"{p}error IS NULL "
        f"AND {p}uf_max < 1.001 "
        f"AND COALESCE({p}side_a_load_ratio, 0) <= 1.0 "
        f"AND COALESCE({p}side_b_load_ratio, 0) <= 1.0 "
        f"AND COALESCE({p}side_c_load_ratio, 0) <= 1.0 "
        f"AND COALESCE({p}side_d_load_ratio, 0) <= 1.0"
    )


class ResultsDB:
    """SQLite database for storing batch run results."""

    def __init__(self, db_path: str | Path, check_same_thread: bool = True):
        self.db_path = str(db_path)
        # Provenance stamps read once per ResultsDB instance. MACS_APP_VERSION
        # is set by main.rs from app.package_info().version on every spawn;
        # MACS_DEVICE_NAME is an optional override for the friendly-name UI
        # that the cloud-sync slice will ship.
        self._device_name = os.environ.get("MACS_DEVICE_NAME") or socket.gethostname()
        self._app_version = os.environ.get("MACS_APP_VERSION")
        # sqlite3.connect does not create directories, and on a pristine
        # machine the frozen fallback %LOCALAPPDATA%\i-macs\ doesn't exist
        # yet — without this the sidecar dies at boot on first install.
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=check_same_thread)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA_SQL)
        self._ensure_schema()
        self.conn.commit()

    def _ensure_schema(self):
        """Add columns/tables that may be missing in older databases."""
        cursor = self.conn.execute("PRAGMA table_info(runs)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        # Columns referenced by _pass_where must exist for stats queries to work
        # against legacy DBs that pre-date the per-side outputs.
        for col, col_type in [
            ("sample_index", "INTEGER"),
            ("seed", "INTEGER"),
            ("batch_id", "TEXT"),
            ("comp_failure", "INTEGER"),
            ("side_a_load_ratio", "REAL"),
            ("side_b_load_ratio", "REAL"),
            ("side_c_load_ratio", "REAL"),
            ("side_d_load_ratio", "REAL"),
            ("engine_version", "TEXT"),
            ("name", "TEXT"),
            ("project_name", "TEXT"),
            ("frc_import_id", "TEXT"),
        ]:
            if col not in existing_cols:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_type}")
        # Ensure batch_id index exists
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runs_batch_id ON runs(batch_id)"
        )
        # Upgrade legacy batches table to include config_json (PRD slice 1).
        batches_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(batches)")
        }
        if "config_json" not in batches_cols:
            self.conn.execute("ALTER TABLE batches ADD COLUMN config_json TEXT")
        # Naming + .frc provenance. Legacy batches keep NULLs; the API falls
        # back to the short batch_id for display.
        for col in ("name", "project_name", "frc_import_id"):
            if col not in batches_cols:
                self.conn.execute(f"ALTER TABLE batches ADD COLUMN {col} TEXT")
        # Sync-provenance columns (#11). Order matters: add uuid as plain TEXT,
        # backfill, then create the unique index — SQLite's ALTER TABLE can't
        # carry UNIQUE inline, and a unique index over NULLs collides.
        self._migrate_sync_provenance()

    def _migrate_sync_provenance(self):
        """Add uuid/device_name/app_version/synced_at where missing, backfill
        existing rows, then create unique indexes on uuid.

        Backfill policy: device_name is filled with the current hostname
        (best guess — if a colleague's DB was hand-copied the stamp is wrong
        but in practice only the dev machine has pre-existing history).
        app_version + synced_at are left NULL; stamping the current version
        would lie about rows that were created earlier.
        """
        host = self._device_name
        for table in _SYNC_PROVENANCE_TABLES_WITH_UUID:
            cols = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if "uuid" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN uuid TEXT")
            if "device_name" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN device_name TEXT")
            if "app_version" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN app_version TEXT")
            if "synced_at" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN synced_at TEXT")
            # Backfill uuid for any rows that don't have one yet.
            missing = self.conn.execute(
                f"SELECT rowid FROM {table} WHERE uuid IS NULL"
            ).fetchall()
            for (rowid,) in missing:
                self.conn.execute(
                    f"UPDATE {table} SET uuid = ? WHERE rowid = ?",
                    (_uuid.uuid4().hex, rowid),
                )
            self.conn.execute(
                f"UPDATE {table} SET device_name = ? WHERE device_name IS NULL",
                (host,),
            )
            self.conn.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uuid ON {table}(uuid)"
            )

        for table in _SYNC_PROVENANCE_TABLES_NO_UUID:
            cols = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if "device_name" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN device_name TEXT")
            if "app_version" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN app_version TEXT")
            if "synced_at" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN synced_at TEXT")
            self.conn.execute(
                f"UPDATE {table} SET device_name = ? WHERE device_name IS NULL",
                (host,),
            )

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def insert_run(self, params: dict, outputs: Optional[dict] = None,
                   error: Optional[str] = None) -> int:
        """Insert a completed run (inputs + outputs) and return the run ID."""
        now = datetime.now(timezone.utc).isoformat()

        row = {
            "uuid": _uuid.uuid4().hex,
            "device_name": self._device_name,
            "app_version": self._app_version,
            "synced_at": None,
            "run_timestamp": now,
            # Geometry
            "span1": params.get("span1"),
            "span2": params.get("span2"),
            "numbeam": params.get("numbeam"),
            # Deck
            "steel_deck": params.get("SteelDeck", 1),
            "deck_name": params.get("DeckName"),
            "deck_type": params.get("deck_type"),
            "deck_depth": params.get("deck_depth"),
            "deck_trug": params.get("deck_trug"),
            "deck_top": params.get("deck_top"),
            "deck_bot": params.get("deck_bot"),
            "deck_stiff_height": params.get("deck_stiff_height"),
            # Slab
            "conc_type": params.get("conc_type"),
            "conc_lambda": params.get("conc_lambda"),
            "fck": params.get("fck"),
            "slab_depth": params.get("slab_depth"),
            "mesh_type": params.get("mesh_type"),
            "mesh_area_max": params.get("mesh_area_max"),
            "mesh_area_min": params.get("mesh_area_min"),
            "mesh_axis": params.get("mesh_axis"),
            "mesh_strength": params.get("mesh_strength"),
            # Beams
            "u_sec_size": params.get("uSecSize"),
            "u_sec_fy": params.get("fy5"),
            "ush_con": params.get("ush_con"),
            "side_a_sec": params.get("SideASecSize"),
            "side_a_fy": params.get("fy1"),
            "side_a_edge": params.get("SideAEdgeFlag"),
            "side_a_composite": params.get("SideACompoFlag"),
            "side_a_sh_con": params.get("SideAsh_con"),
            "side_b_sec": params.get("SideBSecSize"),
            "side_b_fy": params.get("fy2"),
            "side_b_edge": params.get("SideBEdgeFlag"),
            "side_b_composite": params.get("SideBCompoFlag"),
            "side_b_sh_con": params.get("SideBsh_con"),
            "side_c_sec": params.get("SideCSecSize"),
            "side_c_fy": params.get("fy3"),
            "side_c_edge": params.get("SideCEdgeFlag"),
            "side_c_composite": params.get("SideCCompoFlag"),
            "side_c_sh_con": params.get("SideCsh_con"),
            "side_d_sec": params.get("SideDSecSize"),
            "side_d_fy": params.get("fy4"),
            "side_d_edge": params.get("SideDEdgeFlag"),
            "side_d_composite": params.get("SideDCompoFlag"),
            "side_d_sh_con": params.get("SideDsh_con"),
            # Loading
            "lead_var_act": params.get("lead_var_act"),
            "othr_var_act": params.get("othr_var_act"),
            "cold_perm": params.get("cold_perm"),
            "slab_weight": params.get("slab_weight"),
            "lead_var_fac": params.get("lead_var_fac"),
            "othr_var_fac": params.get("othr_var_fac"),
            # Fire
            "method": params.get("method"),
            "time_limit": params.get("time_limit"),
            "Lc": params.get("Lc"),
            "Bc": params.get("Bc"),
            "Hc": params.get("Hc"),
            "Hw": params.get("Hw"),
            "Lw": params.get("Lw"),
            "window_percent": params.get("window_percent"),
            "qf": params.get("qf"),
            "Bfac": params.get("Bfac"),
            "combustion_factor": params.get("combustion_factor"),
            "growth_rate": params.get("growth_rate"),
            # LHS metadata
            "sample_index": params.get("_sample_index"),
            "seed": params.get("_seed"),
            # Batch grouping
            "batch_id": params.get("_batch_id"),
            # Naming + .frc provenance (single runs only — see schema comment)
            "name": params.get("_name"),
            "project_name": params.get("_project_name"),
            "frc_import_id": params.get("_frc_import_id"),
            # Error
            "error": error,
        }

        if outputs and not error:
            row.update({
                "comp_failure": outputs.get("comp_failure"),
                "mb1_reqd": outputs.get("mb1_reqd"),
                "mb2_reqd": outputs.get("mb2_reqd"),
                "factored_hot": outputs.get("factored_hot"),
                "uf_max": outputs.get("uf_max"),
                "max_temperature": outputs.get("max_temperature"),
                "max_deflection": outputs.get("max_deflection"),
                "max_slab_cap": outputs.get("max_slab_cap"),
                "max_beam_cap": outputs.get("max_beam_cap"),
                "max_total_cap": outputs.get("max_total_cap"),
                "side_a_load_ratio": outputs.get("side_a_load_ratio"),
                "side_a_critical_temp": outputs.get("side_a_critical_temp"),
                "side_b_load_ratio": outputs.get("side_b_load_ratio"),
                "side_b_critical_temp": outputs.get("side_b_critical_temp"),
                "side_c_load_ratio": outputs.get("side_c_load_ratio"),
                "side_c_critical_temp": outputs.get("side_c_critical_temp"),
                "side_d_load_ratio": outputs.get("side_d_load_ratio"),
                "side_d_critical_temp": outputs.get("side_d_critical_temp"),
                "duration_ms": outputs.get("duration_ms"),
                "engine_version": outputs.get("engine_version"),
            })

        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_str = ", ".join(columns)
        values = [row[c] for c in columns]

        cursor = self.conn.execute(
            f"INSERT INTO runs ({col_str}) VALUES ({placeholders})", values
        )
        run_id = cursor.lastrowid

        # Insert time series if available
        if outputs and "time_series" in outputs:
            self._insert_time_series(run_id, outputs["time_series"])

        self.conn.commit()
        return run_id

    def _insert_time_series(self, run_id: int, time_series: list[dict]):
        """Insert all time series rows for a run."""
        rows = []
        for ts in time_series:
            rows.append((
                run_id,
                ts["time_step"],
                ts["time_min"],
                ts.get("fire_temp"),
                ts["lofl_temp"],
                ts["mesh_temp"],
                ts["slabtop_temp"],
                ts["slabbot_temp"],
                ts["beam_hot_capacity"],
                ts["deflection"],
                ts["slab_yield"],
                ts["enhancement"],
                ts["slab_cap"],
                ts["total_plate_capacity"],
                ts["utilization_factor"],
            ))
        self.conn.executemany(
            """INSERT INTO time_series
               (run_id, time_step, time_min, fire_temp,
                lofl_temp, mesh_temp, slabtop_temp, slabbot_temp,
                beam_hot_capacity, deflection, slab_yield, enhancement,
                slab_cap, total_plate_capacity, utilization_factor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    def run_exists(self, params: dict) -> bool:
        """Check if a run with matching key input parameters already exists.

        Used for resume capability — skip runs already completed.
        For LHS runs (with _sample_index and _seed), matches on those instead.
        """
        if params.get("_sample_index") is not None and params.get("_seed") is not None:
            key_cols = [
                ("sample_index", params["_sample_index"]),
                ("seed", params["_seed"]),
            ]
        else:
            key_cols = [
                ("span1", params.get("span1")),
                ("span2", params.get("span2")),
                ("numbeam", params.get("numbeam")),
                ("slab_depth", params.get("slab_depth")),
                ("fck", params.get("fck")),
                ("u_sec_size", params.get("uSecSize")),
                ("time_limit", params.get("time_limit")),
                ("method", params.get("method")),
            ]
        where_parts = []
        values = []
        for col, val in key_cols:
            if val is not None:
                where_parts.append(f"{col} = ?")
                values.append(val)
            else:
                where_parts.append(f"{col} IS NULL")

        where_clause = " AND ".join(where_parts)
        cursor = self.conn.execute(
            f"SELECT COUNT(*) FROM runs WHERE error IS NULL AND {where_clause}",
            values,
        )
        return cursor.fetchone()[0] > 0

    def get_run_count(self) -> int:
        """Return total number of runs in the database."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM runs")
        return cursor.fetchone()[0]

    def get_successful_run_count(self) -> int:
        """Return number of successful runs (no error)."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM runs WHERE error IS NULL")
        return cursor.fetchone()[0]

    def get_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return paginated list of runs, newest first."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def get_run(self, run_id: int) -> Optional[dict]:
        """Return a single run by ID, or None if not found."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        self.conn.row_factory = None
        if row is None:
            return None
        return dict(row)

    def get_time_series(self, run_id: int) -> list[dict]:
        """Return time series data for a run, ordered by time_step."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM time_series WHERE run_id = ? ORDER BY time_step",
            (run_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def get_stats(self) -> dict:
        """Return summary statistics: total, successful, errors, pass/fail counts."""
        total = self.get_run_count()
        successful = self.get_successful_run_count()
        errors = total - successful
        pass_cursor = self.conn.execute(
            f"SELECT COUNT(*) FROM runs WHERE {_pass_where()}"
        )
        pass_count = pass_cursor.fetchone()[0]
        fail_count = successful - pass_count
        return {
            "total": total,
            "successful": successful,
            "errors": errors,
            "pass_count": pass_count,
            "fail_count": fail_count,
        }

    # ─── Batch query methods ─────────────────────────────────────────────

    def insert_batch(self, batch_id: str, mode: str, total_expected: int,
                     config_json: Optional[str] = None,
                     name: Optional[str] = None,
                     project_name: Optional[str] = None,
                     frc_import_id: Optional[str] = None):
        """Record batch metadata. config_json holds the full sweep spec JSON
        used by the dashboard to (a) derive varying/fixed params for display
        and (b) hydrate the form for *Rerun batch* (slice 2).

        name/project_name are the human-friendly labels; frc_import_id points
        at the frc_imports row this batch was seeded from, if any."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO batches (batch_id, created_at, mode, total_expected, "
            "config_json, name, project_name, frc_import_id, "
            "device_name, app_version, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (batch_id, now, mode, total_expected, config_json,
             _blank_to_none(name), _blank_to_none(project_name), frc_import_id,
             self._device_name, self._app_version, None),
        )
        self.conn.commit()

    def rename_batch(self, batch_id: str, name: Optional[str] = None,
                     project_name: Optional[str] = None) -> bool:
        """Update a batch's human-friendly labels. Omitted arguments are left
        untouched; an empty string clears the field back to NULL so the UI can
        fall back to the short batch id. Returns False if no such batch."""
        set_parts = []
        values: list = []
        if name is not None:
            set_parts.append("name = ?")
            values.append(_blank_to_none(name))
        if project_name is not None:
            set_parts.append("project_name = ?")
            values.append(_blank_to_none(project_name))
        if not set_parts:
            # Nothing to change — still report whether the batch exists.
            return self.conn.execute(
                "SELECT 1 FROM batches WHERE batch_id = ?", (batch_id,)
            ).fetchone() is not None
        values.append(batch_id)
        cursor = self.conn.execute(
            f"UPDATE batches SET {', '.join(set_parts)} WHERE batch_id = ?",
            values,
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_project_names(self) -> list[str]:
        """Distinct project names across batches and ungrouped runs, sorted.

        Feeds the config-page autocomplete and the dashboard filter, so both
        sources matter — a project may so far only have single runs."""
        cursor = self.conn.execute(
            "SELECT project_name FROM batches "
            "WHERE project_name IS NOT NULL AND project_name != '' "
            "UNION "
            "SELECT project_name FROM runs "
            "WHERE project_name IS NOT NULL AND project_name != '' "
            "ORDER BY project_name"
        )
        return [row[0] for row in cursor.fetchall()]

    # ─── Imported .frc files ─────────────────────────────────────────────

    def record_frc_import(self, filename: str, xml: str,
                          project: Optional[dict] = None) -> str:
        """Store an imported .frc verbatim; return its content-hash id.

        Re-importing identical bytes is a no-op that returns the existing id —
        including its original filename, so batches already pointing at the row
        don't have their recorded history rewritten by a later copy.
        """
        frc_id = hashlib.sha256(xml.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO frc_imports "
            "(id, filename, xml, project_json, imported_at, "
            "device_name, app_version, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (frc_id, filename, xml, json.dumps(project or {}), now,
             self._device_name, self._app_version, None),
        )
        self.conn.commit()
        return frc_id

    def get_frc_import(self, frc_id: Optional[str]) -> Optional[dict]:
        """Return a stored .frc as `{id, filename, xml, project, imported_at}`,
        or None if `frc_id` is NULL/unknown. A malformed project_json degrades
        to `{}` rather than raising — a half-written row must not take down the
        batch list."""
        if not frc_id:
            return None
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM frc_imports WHERE id = ?", (frc_id,)
        )
        row = cursor.fetchone()
        self.conn.row_factory = None
        if row is None:
            return None
        row = dict(row)
        try:
            project = json.loads(row.get("project_json") or "{}")
        except (ValueError, TypeError):
            project = {}
        if not isinstance(project, dict):
            project = {}
        return {
            "id": row["id"],
            "filename": row["filename"],
            "xml": row["xml"],
            "project": project,
            "imported_at": row["imported_at"],
        }

    def get_batches(self, limit: Optional[int] = None,
                    offset: int = 0) -> list[dict]:
        """Return batches with aggregated run stats, newest first.

        Aggregations:
          - run_count: total inserts against this batch
          - pass_count: rows satisfying the shared _pass_where predicate
          - error_count: rows with error IS NOT NULL
          - fail_count: derived in the caller (successful - pass)

        Yields config_json verbatim so the caller can derive varying/fixed
        params with `varying_params_from_config`.
        """
        query = f"""
            SELECT b.batch_id, b.created_at, b.mode, b.total_expected, b.config_json,
                   b.name, b.project_name, b.frc_import_id,
                   COUNT(r.id) AS run_count,
                   SUM(CASE WHEN {_pass_where('r')} THEN 1 ELSE 0 END) AS pass_count,
                   SUM(CASE WHEN r.error IS NOT NULL THEN 1 ELSE 0 END) AS error_count
            FROM batches b
            LEFT JOIN runs r ON r.batch_id = b.batch_id
            GROUP BY b.batch_id
            ORDER BY b.created_at DESC
        """
        params: tuple = ()
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params = (limit, offset)
        cursor = self.conn.execute(query, params)
        return [
            {
                "batch_id": row[0],
                "created_at": row[1],
                "mode": row[2],
                "total_expected": row[3],
                "config_json": row[4],
                "name": row[5],
                "project_name": row[6],
                "frc_import_id": row[7],
                "run_count": row[8] or 0,
                "pass_count": row[9] or 0,
                "error_count": row[10] or 0,
            }
            for row in cursor.fetchall()
        ]

    def get_batches_count(self) -> int:
        """Total batches — for paginated response 'total' field."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM batches")
        return cursor.fetchone()[0]

    def get_ungrouped_runs_count(self) -> int:
        """Total runs where batch_id IS NULL — for paginated response."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE batch_id IS NULL"
        )
        return cursor.fetchone()[0]

    def get_batch_runs(self, batch_id: str) -> list[dict]:
        """Return all runs for a batch, ordered by id."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM runs WHERE batch_id = ? ORDER BY id",
            (batch_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def get_ungrouped_runs(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Return runs where batch_id IS NULL, newest first."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM runs WHERE batch_id IS NULL ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    # ─── Report query methods ──────────────────────────────────────────────

    # Whitelist of valid time_series column names for safe SQL interpolation
    TIME_SERIES_COLUMNS = frozenset({
        "fire_temp", "lofl_temp", "mesh_temp", "slabtop_temp", "slabbot_temp",
        "beam_hot_capacity", "deflection", "slab_yield", "enhancement",
        "slab_cap", "total_plate_capacity", "utilization_factor",
    })

    def get_successful_run_ids(self) -> list[int]:
        """Return list of run IDs for successful runs (no error), ordered by id."""
        cursor = self.conn.execute(
            "SELECT id FROM runs WHERE error IS NULL ORDER BY id"
        )
        return [row[0] for row in cursor.fetchall()]

    def get_all_time_series_column(self, column: str) -> list[tuple]:
        """Return (run_id, time_min, value) tuples for a column across all successful runs.

        Column name is validated against a whitelist to prevent SQL injection.
        """
        if column not in self.TIME_SERIES_COLUMNS:
            raise ValueError(f"Invalid time_series column: {column!r}")
        cursor = self.conn.execute(
            f"""SELECT ts.run_id, ts.time_min, ts.{column}
                FROM time_series ts
                JOIN runs r ON r.id = ts.run_id
                WHERE r.error IS NULL
                ORDER BY ts.run_id, ts.time_min""",
        )
        return cursor.fetchall()

    def get_time_grid(self, run_id: int) -> list[float]:
        """Return sorted list of time_min values for a run."""
        cursor = self.conn.execute(
            "SELECT time_min FROM time_series WHERE run_id = ? ORDER BY time_min",
            (run_id,),
        )
        return [row[0] for row in cursor.fetchall()]

    def get_time_of_max_uf(self, run_id: int) -> Optional[float]:
        """Return the time_min at which utilization_factor is maximum for a run."""
        cursor = self.conn.execute(
            """SELECT time_min FROM time_series
               WHERE run_id = ?
               ORDER BY utilization_factor DESC, time_min ASC
               LIMIT 1""",
            (run_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_time_exceed_one(self, run_id: int) -> Optional[float]:
        """Return the first time_min where utilization_factor >= 1.0, or None."""
        cursor = self.conn.execute(
            """SELECT time_min FROM time_series
               WHERE run_id = ? AND utilization_factor >= 1.0
               ORDER BY time_min ASC
               LIMIT 1""",
            (run_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_uf_times(self, batch_id: Optional[str] = None) -> dict:
        """Return ``{run_id: (time_of_max_uf, time_first_uf_ge_1)}`` in two queries.

        The per-run equivalents (get_time_of_max_uf / get_time_exceed_one) are
        fine for a handful of runs but cost two round trips each — 20,000 of them
        for a 10,000-run export. Scoped to one batch when ``batch_id`` is given.
        """
        where = "r.error IS NULL" + (" AND r.batch_id = ?" if batch_id else "")
        args = (batch_id,) if batch_id else ()

        # Time at which each run's utilization_factor peaks. Ties resolve to the
        # earliest time, matching get_time_of_max_uf's ORDER BY.
        peak = {}
        for run_id, time_min in self.conn.execute(
            f"""SELECT ts.run_id, ts.time_min
                FROM time_series ts
                JOIN runs r ON r.id = ts.run_id
                WHERE {where} AND ts.utilization_factor IS NOT NULL
                ORDER BY ts.run_id, ts.utilization_factor DESC, ts.time_min ASC""",
            args,
        ):
            peak.setdefault(run_id, time_min)

        # First time each run crosses UF >= 1.0, if it ever does.
        exceed = {}
        for run_id, time_min in self.conn.execute(
            f"""SELECT ts.run_id, MIN(ts.time_min)
                FROM time_series ts
                JOIN runs r ON r.id = ts.run_id
                WHERE {where} AND ts.utilization_factor >= 1.0
                GROUP BY ts.run_id""",
            args,
        ):
            exceed[run_id] = time_min

        return {rid: (t, exceed.get(rid)) for rid, t in peak.items()}

    def get_successful_runs(self) -> list[dict]:
        """Return all successful runs as list of dicts."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM runs WHERE error IS NULL ORDER BY id"
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    # ─── Batch-scoped report methods ──────────────────────────────────────

    def get_batch_successful_runs(self, batch_id: str) -> list[dict]:
        """Return successful runs for a specific batch."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM runs WHERE error IS NULL AND batch_id = ? ORDER BY id",
            (batch_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def get_batch_time_series_column(self, batch_id: str, column: str) -> list[tuple]:
        """Return (run_id, time_min, value) for a column across successful runs in a batch."""
        if column not in self.TIME_SERIES_COLUMNS:
            raise ValueError(f"Invalid time_series column: {column!r}")
        cursor = self.conn.execute(
            f"""SELECT ts.run_id, ts.time_min, ts.{column}
                FROM time_series ts
                JOIN runs r ON r.id = ts.run_id
                WHERE r.error IS NULL AND r.batch_id = ?
                ORDER BY ts.run_id, ts.time_min""",
            (batch_id,),
        )
        return cursor.fetchall()

    # ─── Custom sections CRUD ─────────────────────────────────────────────

    def add_custom_section(self, name: str, h: float, b: float,
                           tw: float, tf: float) -> str:
        """Add a custom beam section and return its generated ID (e.g. CUSTOM_1)."""
        # Find next available number
        cursor = self.conn.execute(
            "SELECT id FROM custom_sections ORDER BY id"
        )
        existing_ids = [row[0] for row in cursor.fetchall()]
        next_num = 1
        for eid in existing_ids:
            try:
                num = int(eid.split("_", 1)[1])
                if num >= next_num:
                    next_num = num + 1
            except (IndexError, ValueError):
                pass
        sec_id = f"CUSTOM_{next_num}"
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO custom_sections (id, name, h, b, tw, tf, created_at, "
            "uuid, device_name, app_version, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sec_id, name, h, b, tw, tf, now,
             _uuid.uuid4().hex, self._device_name, self._app_version, None),
        )
        self.conn.commit()
        return sec_id

    def get_custom_sections(self) -> list[dict]:
        """Return all custom sections ordered by name."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM custom_sections ORDER BY name"
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def delete_custom_section(self, sec_id: str):
        """Delete a custom section by ID. No error if not found."""
        self.conn.execute("DELETE FROM custom_sections WHERE id = ?", (sec_id,))
        self.conn.commit()

    # ─── Custom decks CRUD ───────────────────────────────────────────────

    def add_custom_deck(self, name: str, deck_type: str, deck_depth: float,
                        deck_trug: float, deck_top: float, deck_bot: float,
                        deck_stiff_height: float) -> str:
        """Add a custom deck profile and return its generated ID (e.g. CDECK_1)."""
        cursor = self.conn.execute(
            "SELECT id FROM custom_decks ORDER BY id"
        )
        existing_ids = [row[0] for row in cursor.fetchall()]
        next_num = 1
        for eid in existing_ids:
            try:
                num = int(eid.split("_", 1)[1])
                if num >= next_num:
                    next_num = num + 1
            except (IndexError, ValueError):
                pass
        deck_id = f"CDECK_{next_num}"
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO custom_decks (id, name, deck_type, deck_depth, deck_trug, "
            "deck_top, deck_bot, deck_stiff_height, created_at, "
            "uuid, device_name, app_version, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (deck_id, name, deck_type, deck_depth, deck_trug, deck_top, deck_bot,
             deck_stiff_height, now,
             _uuid.uuid4().hex, self._device_name, self._app_version, None),
        )
        self.conn.commit()
        return deck_id

    def get_custom_decks(self) -> list[dict]:
        """Return all custom decks ordered by name."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM custom_decks ORDER BY name"
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def delete_custom_deck(self, deck_id: str):
        """Delete a custom deck by ID. No error if not found."""
        self.conn.execute("DELETE FROM custom_decks WHERE id = ?", (deck_id,))
        self.conn.commit()

    # ─── Custom meshes CRUD ──────────────────────────────────────────────

    def add_custom_mesh(self, name: str, main_area: float,
                        trans_area: float) -> str:
        """Add a custom mesh and return its generated ID (e.g. CMESH_1)."""
        cursor = self.conn.execute(
            "SELECT id FROM custom_meshes ORDER BY id"
        )
        existing_ids = [row[0] for row in cursor.fetchall()]
        next_num = 1
        for eid in existing_ids:
            try:
                num = int(eid.split("_", 1)[1])
                if num >= next_num:
                    next_num = num + 1
            except (IndexError, ValueError):
                pass
        mesh_id = f"CMESH_{next_num}"
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO custom_meshes (id, name, main_area, trans_area, created_at, "
            "uuid, device_name, app_version, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mesh_id, name, main_area, trans_area, now,
             _uuid.uuid4().hex, self._device_name, self._app_version, None),
        )
        self.conn.commit()
        return mesh_id

    def get_custom_meshes(self) -> list[dict]:
        """Return all custom meshes ordered by name."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM custom_meshes ORDER BY name"
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows

    def delete_custom_mesh(self, mesh_id: str):
        """Delete a custom mesh by ID. No error if not found."""
        self.conn.execute("DELETE FROM custom_meshes WHERE id = ?", (mesh_id,))
        self.conn.commit()

    # ─── Settings (key/value) ────────────────────────────────────────────

    def get_setting(self, key: str) -> Optional[str]:
        """Return the stored value for `key`, or None if missing."""
        cursor = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Insert-or-replace a setting. Used for the manual MACS_DATA_PATH
        override (#23); Tauri reads `macs_data_path` at spawn time and
        injects it as the env var the sidecar's data_loader picks up."""
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def delete_setting(self, key: str) -> None:
        """Remove a setting. No error if not present."""
        self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        self.conn.commit()

    # ─── Batch-scoped report methods ──────────────────────────────────────

    def get_batch_stats(self, batch_id: str) -> dict:
        """Return summary statistics for a specific batch."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE batch_id = ?", (batch_id,)
        )
        total = cursor.fetchone()[0]
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM runs WHERE batch_id = ? AND error IS NULL",
            (batch_id,),
        )
        successful = cursor.fetchone()[0]
        errors = total - successful
        cursor = self.conn.execute(
            f"SELECT COUNT(*) FROM runs WHERE batch_id = ? AND {_pass_where()}",
            (batch_id,),
        )
        pass_count = cursor.fetchone()[0]
        fail_count = successful - pass_count
        return {
            "total": total,
            "successful": successful,
            "errors": errors,
            "pass_count": pass_count,
            "fail_count": fail_count,
        }

    # DB column name -> param key for run_row_to_params (only where they differ)
    _RUN_ROW_PARAM_MAP = {
        "steel_deck": "SteelDeck",
        "deck_name": "DeckName",
        "u_sec_size": "uSecSize",
        "u_sec_fy": "fy5",
        "side_a_sec": "SideASecSize",
        "side_a_fy": "fy1",
        "side_a_edge": "SideAEdgeFlag",
        "side_a_composite": "SideACompoFlag",
        "side_a_sh_con": "SideAsh_con",
        "side_b_sec": "SideBSecSize",
        "side_b_fy": "fy2",
        "side_b_edge": "SideBEdgeFlag",
        "side_b_composite": "SideBCompoFlag",
        "side_b_sh_con": "SideBsh_con",
        "side_c_sec": "SideCSecSize",
        "side_c_fy": "fy3",
        "side_c_edge": "SideCEdgeFlag",
        "side_c_composite": "SideCCompoFlag",
        "side_c_sh_con": "SideCsh_con",
        "side_d_sec": "SideDSecSize",
        "side_d_fy": "fy4",
        "side_d_edge": "SideDEdgeFlag",
        "side_d_composite": "SideDCompoFlag",
        "side_d_sh_con": "SideDsh_con",
        "sample_index": "_sample_index",
        "seed": "_seed",
        "batch_id": "_batch_id",
        # Underscore-prefixed so a retry carries provenance forward without
        # the engine ever seeing these as input parameters.
        "name": "_name",
        "project_name": "_project_name",
        "frc_import_id": "_frc_import_id",
    }

    def run_row_to_params(self, run_row: dict) -> dict:
        """Build an engine params dict from a runs table row (for re-running a failed run)."""
        params = {}
        for col, val in run_row.items():
            if col in ("id", "run_timestamp", "error",
                       "uuid", "device_name", "app_version", "synced_at"):
                continue
            if col in (
                "comp_failure", "mb1_reqd", "mb2_reqd", "factored_hot",
                "uf_max", "max_temperature", "max_deflection",
                "max_slab_cap", "max_beam_cap", "max_total_cap",
                "side_a_load_ratio", "side_a_critical_temp",
                "side_b_load_ratio", "side_b_critical_temp",
                "side_c_load_ratio", "side_c_critical_temp",
                "side_d_load_ratio", "side_d_critical_temp",
                "duration_ms",
            ):
                continue
            key = self._RUN_ROW_PARAM_MAP.get(col, col)
            if val is not None:
                params[key] = val
        return params

    def update_run_from_outputs(self, run_id: int, params: dict, outputs: dict) -> None:
        """Replace a run's error/outputs with new results (e.g. after retry with clamped qf)."""
        self.conn.execute("DELETE FROM time_series WHERE run_id = ?", (run_id,))
        set_parts = ["error = NULL"]
        values = []
        for col, key in [("qf", "qf"), ("window_percent", "window_percent")]:
            if key in params:
                set_parts.append(f"{col} = ?")
                values.append(params[key])
        out_cols = [
            "comp_failure", "mb1_reqd", "mb2_reqd", "factored_hot", "uf_max",
            "max_temperature", "max_deflection", "max_slab_cap", "max_beam_cap", "max_total_cap",
            "side_a_load_ratio", "side_a_critical_temp", "side_b_load_ratio", "side_b_critical_temp",
            "side_c_load_ratio", "side_c_critical_temp", "side_d_load_ratio", "side_d_critical_temp",
            "duration_ms",
        ]
        for c in out_cols:
            set_parts.append(f"{c} = ?")
            values.append(outputs.get(c))
        values.append(run_id)
        self.conn.execute(
            f"UPDATE runs SET {', '.join(set_parts)} WHERE id = ?",
            values,
        )
        if outputs.get("time_series"):
            self._insert_time_series(run_id, outputs["time_series"])
        self.conn.commit()
