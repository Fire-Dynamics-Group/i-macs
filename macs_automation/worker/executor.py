"""Execute a macs-batch job spec with resume semantics."""
import time
from typing import Callable, Collection, Optional

from macs_automation.sweep import (
    generate_combinations,
    resolve_deck,
    resolve_mesh,
    resolve_slab_weight,
)

COM_MAX_RETRIES = 3
COM_RETRY_DELAY = 2.0


def make_com_run_one(
    sections_db: dict,
    decks_db: dict,
    meshes_db: dict,
    *,
    run_com: Optional[Callable] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[dict], dict]:
    """Adapter that makes a COM call look like execute_job's run_one.

    Mirrors the local POST /api/sweeps path: resolve deck/mesh/slab weight,
    then run. Transient COM/bridge failures retry the same way the sidecar
    does, so a blip does not become a permanent error row (which resume
    would then skip).
    """
    if run_com is None:
        from macs_automation.engine import run_one_com
        run_com = run_one_com

    def _retryable(exc: BaseException) -> bool:
        return isinstance(exc, RuntimeError) or type(exc).__name__ == "com_error"

    def run_one(params: dict) -> dict:
        resolve_deck(params, decks_db)
        resolve_mesh(params, meshes_db)
        resolve_slab_weight(params)
        last_error: Optional[BaseException] = None
        for attempt in range(1, COM_MAX_RETRIES + 1):
            try:
                return run_com(params, sections_db)
            except Exception as e:
                if not _retryable(e):
                    raise
                last_error = e
                if attempt < COM_MAX_RETRIES:
                    sleep(COM_RETRY_DELAY * attempt)
        raise last_error  # type: ignore[misc]

    return run_one


def execute_job(
    spec: dict,
    completed_indices: Collection,
    run_one: Callable[[dict], dict],
    report: Callable[[list], None],
    *,
    chunk_size: int = 10,
    should_stop: Optional[Callable[[], bool]] = None,
) -> bool:
    """Run every not-yet-completed sample of a job spec, reporting in chunks.

    The combinations are regenerated deterministically from the spec (LHS is
    seeded; paired sweeps are position-ordered), so the enumeration index IS
    the resume key: indices in `completed_indices` are skipped entirely and
    never re-run. A sample whose COM call raises is reported as an error row
    and the job keeps going — mirroring the local sweep runner.

    Returns True when everything remaining was executed and reported, False
    when `should_stop` interrupted the job (already-reported chunks stand;
    the caller must then leave the job incomplete so its lease expires and a
    re-claim resumes from the last reported index).

    Raises on an unrunnable spec (invalid combinations) or a failing
    `report` — those are job-level failures for the caller to handle.
    """
    combinations = generate_combinations(spec)
    completed = set(completed_indices)

    buffer: list = []

    def flush() -> None:
        if buffer:
            report(list(buffer))
            buffer.clear()

    for index, params in enumerate(combinations):
        if index in completed:
            continue
        if should_stop is not None and should_stop():
            flush()
            return False
        row = {"sample_index": index, "params": params}
        try:
            row["outputs"] = run_one(params)
        except Exception as e:  # per-sample failure — record, keep going
            row["error"] = f"{type(e).__name__}: {e}"
        buffer.append(row)
        if len(buffer) >= chunk_size:
            flush()

    flush()
    return True
