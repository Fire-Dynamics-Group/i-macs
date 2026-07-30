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

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    app_module.main(["--port", "8123"])

    assert captured["http"] == "h11"
    assert captured["ws"] == "none"
    assert captured["port"] == 8123
