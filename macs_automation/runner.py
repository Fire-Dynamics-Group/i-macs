"""Batch runner with callback support for MACS+ calculations.

Extracts the run loop from main.py into a reusable function that supports
callbacks (for CLI progress bars, web SSE broadcasting, etc.) and
cancellation via threading.Event.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from macs_automation.db import ResultsDB


@dataclass
class BatchProgress:
    """Tracks progress of a batch run."""
    status: str = "pending"  # pending, running, completed, cancelled, error
    total: int = 0
    completed: int = 0
    errors: int = 0
    skipped: int = 0
    elapsed_seconds: float = 0.0
    error_log: list[str] = field(default_factory=list)


def run_batch_with_callback(
    combinations: list[dict],
    db: ResultsDB,
    sections_db: dict,
    batch_id: str = "default",
    resume: bool = True,
    on_run_complete: Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
    engine_factory: Optional[Callable] = None,
) -> BatchProgress:
    """Run a batch of MACS+ calculations with per-run callbacks.

    Args:
        combinations: List of parameter dicts to run.
        db: Open ResultsDB instance (caller manages lifecycle).
        sections_db: Section database from data_loader for beam lookups.
        batch_id: Identifier for this batch (for logging/tracking).
        resume: If True, skip runs already in the database.
        on_run_complete: Callback(run_id, params, outputs, error, progress)
            called after each run completes.
        cancel_event: threading.Event — if set, stops the batch loop.
        engine_factory: Optional factory function that returns an engine
            instance. Defaults to MACSEngine(). Used for testing.

    Returns:
        BatchProgress with final status.
    """
    progress = BatchProgress(
        status="running",
        total=len(combinations),
    )
    start_time = time.monotonic()

    # Count skipped runs
    if resume:
        for params in combinations:
            if db.run_exists(params):
                progress.skipped += 1

    for params in combinations:
        # Check for cancellation
        if cancel_event and cancel_event.is_set():
            progress.status = "cancelled"
            progress.elapsed_seconds = time.monotonic() - start_time
            return progress

        # Skip already-completed runs
        if resume and db.run_exists(params):
            continue

        run_id = None
        outputs = None
        error = None

        try:
            if engine_factory:
                engine = engine_factory()
                engine.set_inputs(params, sections_db)
                outputs = engine.run(method=params.get("method", "iso"))
            else:
                from macs_automation.engine import run_one_com
                outputs = run_one_com(params, sections_db)
            run_id = db.insert_run(params, outputs=outputs)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            run_id = db.insert_run(params, error=error)
            progress.errors += 1
            progress.error_log.append(error)
            # Keep last 20 errors
            if len(progress.error_log) > 20:
                progress.error_log = progress.error_log[-20:]

        progress.completed += 1
        progress.elapsed_seconds = time.monotonic() - start_time

        if on_run_complete:
            on_run_complete(run_id, params, outputs, error, progress)

    progress.status = "completed"
    progress.elapsed_seconds = time.monotonic() - start_time
    return progress
