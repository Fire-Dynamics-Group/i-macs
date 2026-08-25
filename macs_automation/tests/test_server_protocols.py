"""The sidecar must pin uvicorn's protocol implementations explicitly.

The NSIS updater overlays new files onto the install dir without deleting
removed ones, so a machine that has ever run an older version can have stale
packages (websockets, httptools, watchfiles from the uvicorn[standard] era)
sitting next to the new bundle. uvicorn's "auto" protocol selection does
`try: import websockets` — which *succeeds* against the stale leftovers and
then crashes on version/API mismatch. That took down every updated install
of rc.13 at boot (ImportError: cannot import name '__version__' from
'websockets').

Explicit http="h11" / ws="none" means uvicorn never imports those packages,
whatever debris is on disk. The sidecar serves plain HTTP on localhost; it
has no websocket endpoints.
"""

import macs_automation.app as app_module


def test_uvicorn_runs_with_explicit_protocols(monkeypatch):
    captured = {}
    monkeypatch.delenv("MACS_WORKER", raising=False)

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    app_module.main(["--port", "8123"])

    assert captured["http"] == "h11"
    assert captured["ws"] == "none"
    assert captured["port"] == 8123


def test_worker_flag_starts_headless_worker_not_uvicorn(monkeypatch):
    """`--worker` is the sidecar's headless mode (issue #44)."""
    captured = {}

    def fake_run(*args, **kwargs):
        captured["uvicorn"] = True

    def fake_worker_main():
        captured["worker"] = True

    import uvicorn
    import macs_automation.worker.cli as worker_cli

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(worker_cli, "main", fake_worker_main)
    app_module.main(["--worker"])

    assert captured.get("worker") is True
    assert "uvicorn" not in captured


def test_macs_worker_env_starts_headless_worker_not_uvicorn(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["uvicorn"] = True

    def fake_worker_main():
        captured["worker"] = True

    import uvicorn
    import macs_automation.worker.cli as worker_cli

    monkeypatch.setenv("MACS_WORKER", "1")
    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(worker_cli, "main", fake_worker_main)
    app_module.main(["--port", "8123"])

    assert captured.get("worker") is True
    assert "uvicorn" not in captured
