"""SQLite database schema and helpers for storing MACS+ batch results."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    -- Metadata
    error TEXT, duration_ms REAL
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
"""


class ResultsDB:
    """SQLite database for storing batch run results."""

    def __init__(self, db_path: str | Path, check_same_thread: bool = True):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=check_same_thread)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA_SQL)
        self._ensure_schema()
        self.conn.commit()

    def _ensure_schema(self):
        """Add columns that may be missing in older databases."""
        cursor = self.conn.execute("PRAGMA table_info(runs)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col, col_type in [("sample_index", "INTEGER"), ("seed", "INTEGER")]:
            if col not in existing_cols:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {col_type}")

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
            "SELECT COUNT(*) FROM runs WHERE error IS NULL AND uf_max <= 1.0"
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

    def get_successful_runs(self) -> list[dict]:
        """Return all successful runs as list of dicts."""
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.execute(
            "SELECT * FROM runs WHERE error IS NULL ORDER BY id"
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.row_factory = None
        return rows
