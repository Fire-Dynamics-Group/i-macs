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
    "elapsed_s": 0.0,
    "eta_s": None,
}


def status(batch_id: Optional[str] = None) -> dict:
    """Progress of the job for `batch_id`, or of whatever is current if omitted.

    Only one replay can run at a time (one machine, one MACS+), so the state is
    global - but each batch page asks about its own batch, and must not be shown
    another batch's progress, output directory or failure as if it were its own.
    """
    with _lock:
        st = dict(_state)
    if batch_id is not None and st["batch_id"] != batch_id:
        return dict(_IDLE)
    eta = None
    elapsed = 0.0
    if st["start_time"]:
        elapsed = time.time() - st["start_time"]
        if st["completed"] > 0 and st["total"]:
            per = elapsed / st["completed"]
            eta = round(per * (st["total"] - st["completed"]), 1)
    st["elapsed_s"] = round(elapsed, 1)
    st["eta_s"] = eta
    return st


def _count_pdfs(out: Path) -> int:
    return sum(1 for p in out.glob("*.pdf") if p.stat().st_size > 1000)


def _worker(batch_id: str, db_path: str, sample: Optional[int], seed: Optional[str]):
    out_dir = evidence_root() / batch_id
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
        import json

        entries = json.loads(manifest.read_text(encoding="utf-8"))["runs"]
        with _lock:
            _state["total"] = len(entries)
            _state["output_dir"] = str(pdf_dir)

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
          seed: Optional[str] = None) -> dict:
    with _lock:
        if _state["active"]:
            return {"error": "PDF evidence generation is already running",
                    "batch_id": _state["batch_id"]}
        _state.update(
            active=True, batch_id=batch_id, total=0, completed=0,
            start_time=time.time(), output_dir=None, error=None, finished_at=None,
        )
    threading.Thread(
        target=_worker, args=(batch_id, db_path, sample, seed), daemon=True
    ).start()
    return {"started": True, "batch_id": batch_id}
