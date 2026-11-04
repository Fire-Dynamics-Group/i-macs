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


def test_uvicorn_runs_with_reload_flag(monkeypatch):
    captured = {}
    target_app = []

    def fake_run(app_target, **kwargs):
        target_app.append(app_target)
        captured.update(kwargs)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    app_module.main(["--port", "8123", "--reload"])

    assert target_app[0] == "macs_automation.app:app"
    assert captured["reload"] is True
    assert captured["http"] == "h11"
    assert captured["ws"] == "none"
    assert captured["port"] == 8123
    assert captured["reload_dirs"] == [str(app_module.APP_DIR)]
