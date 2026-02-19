"""Tests for the web/ package — FastAPI app, routes, SSE."""

import asyncio
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from macs_automation.db import ResultsDB
from macs_automation.web.app import create_app
from macs_automation.web.sse import SSEBroadcaster


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def app(tmp_path, monkeypatch):
    """Create a test app with a temporary database."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("MACS_DB_PATH", db_path)
    app = create_app()
    return app


@pytest.fixture
def client(app):
    """TestClient for the web app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_app(populated_db, monkeypatch):
    """Create a test app with the populated_db fixture data."""
    monkeypatch.setenv("MACS_DB_PATH", populated_db.db_path)
    app = create_app()
    return app


@pytest.fixture
def seeded_client(seeded_app):
    with TestClient(seeded_app) as c:
        yield c


# ─── Page routes ──────────────────────────────────────────────────────────────

class TestPageRoutes:
    def test_index_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "MACS+" in resp.text

    def test_dashboard_page(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "Live Dashboard" in resp.text
        assert "chart-scatter" in resp.text

    def test_index_shows_stats(self, seeded_client):
        resp = seeded_client.get("/")
        assert resp.status_code == 200
        # Should show total runs count
        assert "10" in resp.text


# ─── API routes ───────────────────────────────────────────────────────────────

class TestAPIRoutes:
    def test_stats_empty(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_stats_with_data(self, seeded_client):
        resp = seeded_client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert data["successful"] == 9
        assert data["errors"] == 1

    def test_runs_list(self, seeded_client):
        resp = seeded_client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 10

    def test_runs_pagination(self, seeded_client):
        resp = seeded_client.get("/api/runs?limit=3&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 3

    def test_single_run(self, seeded_client):
        resp = seeded_client.get("/api/runs/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["span1"] == 9.0

    def test_run_not_found(self, client):
        resp = client.get("/api/runs/999")
        assert resp.status_code == 404

    def test_time_series(self, seeded_client):
        resp = seeded_client.get("/api/runs/1/time-series")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 12  # conftest creates 12 time steps


# ─── Report download ─────────────────────────────────────────────────────────

class TestReportDownload:
    def test_report_download(self, seeded_client):
        resp = seeded_client.get("/api/report")
        assert resp.status_code == 200
        assert "application/zip" in resp.headers.get("content-type", "")

    def test_report_is_valid_zip(self, seeded_client):
        resp = seeded_client.get("/api/report")
        import io
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "summary.csv" in names
        csv_files = [n for n in names if n.endswith(".csv")]
        assert len(csv_files) == 9
        png_files = [n for n in names if n.endswith(".png")]
        assert len(png_files) == 4


# ─── SSE broadcaster ─────────────────────────────────────────────────────────

class TestSSEBroadcaster:
    @pytest.mark.asyncio
    async def test_subscribe_and_broadcast(self):
        b = SSEBroadcaster()
        queue = await b.subscribe()
        await b.broadcast("test_event", {"key": "value"})
        msg = await asyncio.wait_for(queue.get(), timeout=1)
        assert "event: test_event" in msg
        assert '"key": "value"' in msg

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        b = SSEBroadcaster()
        queue = await b.subscribe()
        await b.unsubscribe(queue)
        await b.broadcast("test", {"x": 1})
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        b = SSEBroadcaster()
        q1 = await b.subscribe()
        q2 = await b.subscribe()
        await b.broadcast("evt", {"n": 1})
        msg1 = await asyncio.wait_for(q1.get(), timeout=1)
        msg2 = await asyncio.wait_for(q2.get(), timeout=1)
        assert msg1 == msg2


# ─── Batch control ────────────────────────────────────────────────────────────

class TestBatchControl:
    def test_cancel_no_batch(self, client):
        resp = client.post("/api/batch/cancel")
        # Should return 404 when no batch is running
        assert resp.status_code == 404

    def test_start_requires_config(self, client):
        resp = client.post("/api/batch/start", json={})
        assert resp.status_code == 400


# ─── Production readiness ────────────────────────────────────────────────────

class TestProductionReadiness:
    def test_no_hardcoded_localhost_in_templates(self):
        """Templates should not hardcode localhost URLs."""
        from pathlib import Path
        template_dir = Path(__file__).parent.parent / "web" / "templates"
        for tmpl in template_dir.glob("*.html"):
            content = tmpl.read_text()
            assert "localhost" not in content, f"Found localhost in {tmpl.name}"

    def test_no_hardcoded_localhost_in_js(self):
        """JS files should not hardcode localhost URLs."""
        from pathlib import Path
        static_dir = Path(__file__).parent.parent / "web" / "static"
        for js_file in static_dir.glob("*.js"):
            content = js_file.read_text()
            assert "localhost" not in content, f"Found localhost in {js_file.name}"

    def test_env_var_for_db_path(self, monkeypatch, tmp_path):
        """App should respect MACS_DB_PATH environment variable."""
        db_path = str(tmp_path / "custom.db")
        monkeypatch.setenv("MACS_DB_PATH", db_path)
        app = create_app()
        with TestClient(app):
            pass  # just verify it starts without error
