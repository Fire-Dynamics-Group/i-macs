"""Generate genuine MACS+ report PDFs for a completed batch, from the app.

Wraps `tools/macs_replay` so the batch page can offer it as a click. The heavy
lifting stays in those scripts — this module resolves where they live (dev tree
vs frozen bundle), runs them on a background thread, and reports progress.

Only meaningful in an interactive logged-on session: the Windows print dialog
is an explorer.exe-hosted window that does not exist otherwise. The sidecar is
spawned by Tauri inside the user's session, so this holds when the desktop app
is running, and would break if the sidecar ever became a service.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

_lock = threading.Lock()
_state: dict = {
    "active": False,
    "batch_id": None,
    "total": 0,
    "completed": 0,
    "start_time": None,
    "output_dir": None,
    "error": None,
    "finished_at": None,
    # Remembered so a resume covers the same runs, and so pausing can find the
    # job's directory even when the user chose one.
    "sample": None,
    "seed": None,
    "job_dir": None,
    "stopping": False,
}


def tool_dir() -> Path:
    """Where the replay scripts live: bundled beside the frozen sidecar, or the repo."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "macs_replay"
    return Path(__file__).resolve().parents[1] / "tools" / "macs_replay"


def evidence_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) / "i-macs" if local else Path.cwd()
    return base / "pdf_evidence"


def resolve_out_dir(batch_id: str, out_dir: Optional[str] = None) -> Path:
    """Where this batch's evidence goes: the chosen folder, or ours.

    10k runs is roughly 4.2 GB, which frequently wants a drive other than C:.
    """
    return Path(out_dir) if out_dir else evidence_root() / batch_id


def _job_file(batch_id: str) -> Path:
    """Kept under our own root even when the PDFs go elsewhere, so a job can be
    found again without already knowing where the user sent it."""
    return evidence_root() / "_jobs" / f"{batch_id}.json"


def remember_job(batch_id: str, *, sample: Optional[int], out_dir: Optional[str],
                 seed: Optional[str], total: int) -> None:
    """Record what a job was started with so it outlives the process.

    Closing the app kills the runner mid-batch; without this, resuming means
    re-picking the output folder and the seed .frc by hand.
    """
    path = _job_file(batch_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"sample": sample, "out_dir": out_dir, "seed": seed,
                        "total": total}),
            encoding="utf-8",
        )
    except OSError:
        pass  # a job that cannot be remembered still runs


def recall_job(batch_id: str) -> Optional[dict]:
    try:
        return json.loads(_job_file(batch_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stop_file(batch_id: str) -> Path:
    """Sentinel the runner watches for between runs.

    A file rather than a signal because the runner is a separate PowerShell
    process: it must finish the run it is holding and leave through its own
    `finally`, which is what puts the default printer back and closes MACS+.
    Killing it outright skips both.
    """
    with _lock:
        job_dir = _state["job_dir"] if _state["batch_id"] == batch_id else None
    return resolve_out_dir(batch_id, job_dir) / "pdfs" / "_stop"


def clear_stop(batch_id: str) -> None:
    """Drop a leftover signal, or a resume would stop again immediately."""
    try:
        stop_file(batch_id).unlink()
    except (FileNotFoundError, OSError):
        pass


def stop(batch_id: str) -> dict:
    with _lock:
        if not _state["active"] or _state["batch_id"] != batch_id:
            return {"error": f"no PDF evidence job is running for batch {batch_id}"}
    path = stop_file(batch_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stop", encoding="utf-8")
    except OSError as exc:
        return {"error": f"could not signal the runner: {exc}"}
    with _lock:
        _state["stopping"] = True
    return {"stopping": True, "batch_id": batch_id}


def reset(batch_id: str, delete_pdfs: bool = False) -> dict:
    """Forget a job so the batch can be started fresh.

    The PDFs are hours of work, so they are kept unless `delete_pdfs` is asked
    for explicitly. Even then only `*.pdf` inside the job's own `pdfs` folder
    goes: the parent can be a directory the user chose, and nothing else in it
    is ours to remove.
    """
    with _lock:
        if _state["active"] and _state["batch_id"] == batch_id:
            return {"error": "stop the job before resetting it"}
    job = recall_job(batch_id) or {}

    deleted = 0
    if delete_pdfs:
        pdf_dir = resolve_out_dir(batch_id, job.get("out_dir")) / "pdfs"
        if pdf_dir.is_dir():
            for pdf in pdf_dir.glob("*.pdf"):
                try:
                    pdf.unlink()
                    deleted += 1
                except OSError:
                    pass

    try:
        _job_file(batch_id).unlink()
    except (FileNotFoundError, OSError):
        pass

    with _lock:
        if _state["batch_id"] == batch_id:
            _state.update(
                active=False, batch_id=None, total=0, completed=0,
                start_time=None, output_dir=None, error=None, finished_at=None,
                sample=None, seed=None, job_dir=None, stopping=False,
            )
    return {"reset": True, "deleted": deleted}


def _powershell(script: Path, args: list[str], timeout: Optional[int] = None):
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def host_check() -> dict:
    """Run the preflight and return its lines plus a pass/fail.

    Surfacing this in the UI is the point: the display-scaling trap produces
    correct numbers with silently wrong charts, so it must be visible before
    someone commits to an 11-hour run rather than buried in a terminal.
    """
    script = tool_dir() / "Test-ReplayHost.ps1"
    if not script.exists():
        return {"ok": False, "lines": [], "error": f"missing {script}"}
    try:
        proc = _powershell(script, [], timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "lines": [], "error": str(exc)}
    lines = [ln.rstrip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    return {
        "ok": proc.returncode == 0,
        "lines": lines,
        "error": (proc.stderr or "").strip() or None,
    }


def _load_export_module():
    path = tool_dir() / "export_batch.py"
    spec = importlib.util.spec_from_file_location("macs_replay_export", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_IDLE = {
    "active": False,
    "batch_id": None,
    "total": 0,
    "completed": 0,
    "start_time": None,
    "output_dir": None,
    "error": None,
    "finished_at": None,
    "sample": None,
    "seed": None,
    "job_dir": None,
    "stopping": False,
    "elapsed_s": 0.0,
    "eta_s": None,
    "resumable": False,
}


def _recalled_status(batch_id: str) -> dict:
    """Rebuild a job's state from disk for a process that never ran it.

    The PDFs are counted rather than read back from the record: the record is
    written once, and the runner keeps going after it.
    """
    st = dict(_IDLE)
    job = recall_job(batch_id)
    if not job:
        return st
    pdf_dir = resolve_out_dir(batch_id, job.get("out_dir")) / "pdfs"
    completed = _count_pdfs(pdf_dir) if pdf_dir.exists() else 0
    total = job.get("total") or 0
    st.update(
        batch_id=batch_id, total=total, completed=completed,
        sample=job.get("sample"), seed=job.get("seed"),
        job_dir=job.get("out_dir"), output_dir=str(pdf_dir),
        resumable=total > 0 and completed < total,
    )
    return st


def status(batch_id: Optional[str] = None) -> dict:
    """Progress of the job for `batch_id`, or of whatever is current if omitted.

    Only one replay can run at a time (one machine, one MACS+), so the state is
    global - but each batch page asks about its own batch, and must not be shown
    another batch's progress, output directory or failure as if it were its own.
    """
    with _lock:
        st = dict(_state)
    if batch_id is not None and st["batch_id"] != batch_id:
        return _recalled_status(batch_id)
    eta = None
    elapsed = 0.0
    if st["start_time"]:
        elapsed = time.time() - st["start_time"]
        if st["completed"] > 0 and st["total"]:
            per = elapsed / st["completed"]
            eta = round(per * (st["total"] - st["completed"]), 1)
    st["elapsed_s"] = round(elapsed, 1)
    st["eta_s"] = eta
    # Runs already on disk are skipped, so picking up where a pause left off is
    # just starting again with the same parameters.
    st["resumable"] = (
        not st["active"] and st["total"] > 0 and st["completed"] < st["total"]
    )
    return st


def _count_pdfs(out: Path) -> int:
    return sum(1 for p in out.glob("*.pdf") if p.stat().st_size > 1000)


def _worker(batch_id: str, db_path: str, sample: Optional[int], seed: Optional[str],
            out_dir_arg: Optional[str] = None):
    out_dir = resolve_out_dir(batch_id, out_dir_arg)
    pdf_dir = out_dir / "pdfs"
    try:
        export = _load_export_module()
        argv = ["export_batch.py", "--db", db_path, "--batch-id", batch_id, "--out", str(out_dir)]
        if sample:
            argv += ["--sample", str(sample)]
        if seed:
            argv += ["--seed", seed]

        old_argv = sys.argv
        sys.argv = argv
        try:
            export.main()
        finally:
            sys.argv = old_argv

        manifest = out_dir / "manifest.json"
        entries = json.loads(manifest.read_text(encoding="utf-8"))["runs"]
        with _lock:
            _state["total"] = len(entries)
            _state["output_dir"] = str(pdf_dir)
            stopping = _state["stopping"]
        # Written before the runner starts, so a job survives the app closing.
        remember_job(batch_id, sample=sample, out_dir=out_dir_arg, seed=seed,
                     total=len(entries))
        # Exporting a 10k batch takes a while; a pause during it should not be
        # answered by launching MACS+ anyway.
        if stopping:
            return

        runner = tool_dir() / "Invoke-MacsReplay.ps1"
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner),
             "-Manifest", str(manifest), "-OutDir", str(pdf_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Progress from the output directory rather than by parsing stdout: the
        # runner is resumable, so files on disk are the truth either way.
        while proc.poll() is None:
            with _lock:
                _state["completed"] = _count_pdfs(pdf_dir) if pdf_dir.exists() else 0
            time.sleep(2)
        with _lock:
            _state["completed"] = _count_pdfs(pdf_dir) if pdf_dir.exists() else 0
            if proc.returncode != 0:
                _state["error"] = (proc.stderr.read() if proc.stderr else "") or \
                    f"replay exited {proc.returncode} ({_state['completed']}/{_state['total']} done)"
    except SystemExit as exc:
        # export_batch refuses rather than writing wrong files - surface why
        with _lock:
            _state["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            _state["active"] = False
            _state["finished_at"] = time.time()


def start(batch_id: str, db_path: str, sample: Optional[int] = None,
          seed: Optional[str] = None, out_dir: Optional[str] = None) -> dict:
    """Start (or resume) a job. Runs already on disk are skipped by the runner,
    so resuming after a pause is the same call with the same parameters."""
    with _lock:
        if _state["active"]:
            return {"error": "PDF evidence generation is already running",
                    "batch_id": _state["batch_id"]}
        _state.update(
            active=True, batch_id=batch_id, total=0, completed=0,
            start_time=time.time(), output_dir=None, error=None, finished_at=None,
            sample=sample, seed=seed, job_dir=out_dir, stopping=False,
        )
    clear_stop(batch_id)
    threading.Thread(
        target=_worker, args=(batch_id, db_path, sample, seed, out_dir), daemon=True
    ).start()
    return {"started": True, "batch_id": batch_id}
