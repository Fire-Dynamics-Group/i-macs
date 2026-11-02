"""Tests for the upload-canvas MACS link integration in i-macs sidecar."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from macs_automation.db import ResultsDB
from macs_automation.upload_canvas import (
    get_or_create_imacs_job_id,
    build_macs_run_payload,
    UploadCanvasClient,
    UploadCanvasError,
)
from macs_automation.app import app


@pytest.fixture
def mem_db():
    db = ResultsDB(":memory:")
    yield db
    db.close()


def test_get_or_create_imacs_job_id(mem_db):
    # Generates a stable UUID per job_id
    id1 = get_or_create_imacs_job_id(mem_db, "batch-123")
    assert len(id1) == 36
    id2 = get_or_create_imacs_job_id(mem_db, "batch-123")
    assert id1 == id2

    # Different job gets a different id
    id3 = get_or_create_imacs_job_id(mem_db, "batch-456")
    assert id3 != id1


def test_build_macs_run_payload():
    run_row = {
        "id": 42,
        "uuid": "run-uuid-42",
        "side_a_critical_temp": 580.0,
        "side_b_critical_temp": 540.0,
        "side_c_critical_temp": 600.0,
        "side_d_critical_temp": 620.0,
        "side_b_sec": "UB 457x191x82",
        "span1": 12.0,
        "span2": 9.0,
    }
    payload = build_macs_run_payload(
        run_row=run_row,
        imacs_job_id="job-uuid-1",
        label="Test Batch",
        version="0.1.0-rc.17",
    )
    assert payload["schema"] == "fd-macs-reliability/1"
    assert payload["critical_temp"] == 540.0
    assert payload["governing_side"] == "B"
    assert payload["section"] == "UB 457x191x82"
    assert payload["exposure"] in ("3-sided", "4-sided")
    assert payload["section_factor"] > 0
    assert payload["imacs_job_id"] == "job-uuid-1"
    assert payload["run_id"] == "run-uuid-42"
    assert payload["label"] == "Test Batch"
    assert payload["client_version"] == "0.1.0-rc.17"
    assert "windows_user" in payload
    assert "machine_name" in payload
    assert "client_timestamp" in payload


def test_client_error_handling_401():
    client = UploadCanvasClient(
        backend_url="http://test-backend",
        upload_canvas_url="http://test-web",
        app_key="dummy-key",
    )
    with patch("urllib.request.urlopen") as mock_open:
        import urllib.error
        mock_open.side_effect = urllib.error.HTTPError(
            url="http://test-backend/imacs/handoffs",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )
        with pytest.raises(UploadCanvasError) as exc_info:
            client.create_handoff({"schema": "fd-macs-reliability/1"})
        assert exc_info.value.status_code == 401
        assert "Missing or invalid IMACS_APP_KEY" in str(exc_info.value)


def test_client_error_handling_503():
    client = UploadCanvasClient(
        backend_url="http://test-backend",
        upload_canvas_url="http://test-web",
        app_key="dummy-key",
    )
    with patch("urllib.request.urlopen") as mock_open:
        import urllib.error
        mock_open.side_effect = urllib.error.HTTPError(
            url="http://test-backend/imacs/handoffs",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=None,
        )
        with pytest.raises(UploadCanvasError) as exc_info:
            client.create_handoff({"schema": "fd-macs-reliability/1"})
        assert exc_info.value.status_code == 503
        assert "Service unavailable" in str(exc_info.value)


def test_sidecar_summary_endpoint():
    api = TestClient(app)
    with patch("macs_automation.upload_canvas.UploadCanvasClient.get_summary") as mock_summary:
        mock_summary.return_value = {
            "project_id": "p-123",
            "project_name": "Warehouse A",
            "last_sent_at": "2026-11-02T12:00:00Z",
            "outcome": {"timeEq": 45, "status": "pass"},
        }
        res = api.get("/api/imacs/jobs/batch-test-1/upload-canvas-summary")
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["project_name"] == "Warehouse A"


def test_sidecar_handoff_and_link_endpoints():
    api = TestClient(app)
    with patch("macs_automation.upload_canvas_router._get_latest_run_for_job") as mock_run, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.create_handoff") as mock_handoff, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.link_project") as mock_link, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.push_run") as mock_push, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.search_projects") as mock_search, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.unlink_project") as mock_unlink:

        mock_run.return_value = {
            "id": 10,
            "side_a_critical_temp": 520.0,
            "side_a_sec": "UB 457x191x82",
            "u_sec_size": "UB 457x191x82",
        }
        mock_handoff.return_value = {
            "handoff_id": "h-abc",
            "url": "http://localhost:3000/?handoff=h-abc",
        }
        mock_link.return_value = {"status": "linked"}
        mock_push.return_value = {"status": "pushed"}
        mock_search.return_value = [{"id": "p-1", "name": "TimeEq Project 1"}]
        mock_unlink.return_value = {"unlinked": True}

        # 1. Handoff
        res_ho = api.post("/api/imacs/jobs/batch-1/upload-canvas-handoff")
        assert res_ho.status_code == 200
        assert res_ho.json()["handoff_id"] == "h-abc"

        # 2. Search projects
        res_srch = api.get("/api/imacs/upload-canvas-projects?q=TimeEq")
        assert res_srch.status_code == 200
        assert len(res_srch.json()["projects"]) == 1

        # 3. Link project
        res_link = api.post("/api/imacs/jobs/batch-1/upload-canvas-link", json={"project_id": "p-1"})
        assert res_link.status_code == 200
        assert res_link.json()["status"] == "linked"

        # 4. Unlink project
        res_unlink = api.delete("/api/imacs/jobs/batch-1/upload-canvas-link")
        assert res_unlink.status_code == 200
        assert res_unlink.json()["status"] == "unlinked"
