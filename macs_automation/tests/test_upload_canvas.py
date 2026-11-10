"""Tests for the upload-canvas MACS link integration in i-macs sidecar."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from macs_automation.db import ResultsDB
from macs_automation.upload_canvas import (
    get_or_create_imacs_job_id,
    build_macs_run_payload,
    build_macs_batch_payload,
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
        version="0.1.0-rc.19",
    )
    assert payload["schema"] == "fd-macs-reliability/2"
    assert payload["critical_temp"] == 540.0
    assert payload["governing_side"] == "B"
    assert payload["section"] == "UB 457x191x82"
    assert payload["exposure"] in ("3-sided", "4-sided")
    assert payload["section_factor"] > 0
    assert payload["imacs_job_id"] == "job-uuid-1"
    assert payload["run_id"] == "run-uuid-42"
    assert payload["label"] == "Test Batch"
    assert payload["client_version"] == "0.1.0-rc.19"
    assert "windows_user" in payload
    assert "machine_name" in payload
    assert "client_timestamp" in payload
    assert "outputs" in payload
    assert "checks" in payload
    assert "time_series" in payload


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
        assert res_link.json()["url"] == "http://localhost:3000/structural-fire?project=p-1"

        # 4. Push run
        with patch("macs_automation.upload_canvas.UploadCanvasClient.get_summary") as mock_summary:
            mock_summary.return_value = {
                "project_id": "p-1",
                "project_name": "TimeEq Project 1",
                "last_sent_at": None,
                "outcome": None,
            }
            res_push = api.post("/api/imacs/jobs/batch-1/upload-canvas-push")
            assert res_push.status_code == 200
            assert res_push.json()["status"] == "pushed"
            assert res_push.json()["url"] == "http://localhost:3000/structural-fire?project=p-1"

        # 5. Unlink project
        res_unlink = api.delete("/api/imacs/jobs/batch-1/upload-canvas-link")
        assert res_unlink.status_code == 200
        assert res_unlink.json()["status"] == "unlinked"


def test_build_macs_batch_payload_not_found(mem_db):
    assert build_macs_batch_payload(mem_db, "nonexistent-batch") is None


def test_build_macs_batch_payload_success(mem_db):
    import base64
    batch_id = "test-batch-uuid-1"
    mem_db.insert_batch(batch_id=batch_id, mode="mc", total_expected=2, name="Test Batch 1")

    # Insert two runs
    ts_data_1 = [
        {"time_step": 0, "time_min": 0, "lofl_temp": 20.0, "mesh_temp": 20.0, "slabtop_temp": 20.0, "slabbot_temp": 20.0,
         "beam_hot_capacity": 50.0, "deflection": 0.0, "slab_yield": 40.0, "enhancement": 1.0,
         "slab_cap": 30.0, "total_plate_capacity": 80.0, "utilization_factor": 0.1},
        {"time_step": 1, "time_min": 30, "lofl_temp": 500.0, "mesh_temp": 450.0, "slabtop_temp": 300.0, "slabbot_temp": 400.0,
         "beam_hot_capacity": 30.0, "deflection": 15.0, "slab_yield": 25.0, "enhancement": 1.2,
         "slab_cap": 20.0, "total_plate_capacity": 50.0, "utilization_factor": 0.8},
    ]
    ts_data_2 = [
        {"time_step": 0, "time_min": 0, "lofl_temp": 20.0, "mesh_temp": 20.0, "slabtop_temp": 20.0, "slabbot_temp": 20.0,
         "beam_hot_capacity": 50.0, "deflection": 0.0, "slab_yield": 40.0, "enhancement": 1.0,
         "slab_cap": 30.0, "total_plate_capacity": 80.0, "utilization_factor": 0.1},
        {"time_step": 1, "time_min": 30, "lofl_temp": 550.0, "mesh_temp": 480.0, "slabtop_temp": 320.0, "slabbot_temp": 420.0,
         "beam_hot_capacity": 25.0, "deflection": 20.0, "slab_yield": 20.0, "enhancement": 1.1,
         "slab_cap": 18.0, "total_plate_capacity": 43.0, "utilization_factor": 0.9},
    ]

    mem_db.insert_run(
        params={
            "_batch_id": batch_id,
            "span1": 12.0, "span2": 9.0, "numbeam": 2,
            "uSecSize": "UB 457x191x82", "fy5": 355, "ush_con": 80,
            "qf": 400, "window_percent": 40,
            "SideASecSize": "UB 457x191x82", "fy1": 355,
        },
        outputs={
            "uf_max": 0.8,
            "factored_hot": 4.5,
            "side_a_critical_temp": 550.0,
            "time_series": ts_data_1,
        }
    )
    mem_db.insert_run(
        params={
            "_batch_id": batch_id,
            "span1": 12.0, "span2": 9.0, "numbeam": 2,
            "uSecSize": "UB 457x191x82", "fy5": 355, "ush_con": 80,
            "qf": 600, "window_percent": 60,
            "SideASecSize": "UB 457x191x82", "fy1": 355,
        },
        outputs={
            "uf_max": 0.9,
            "factored_hot": 4.5,
            "side_a_critical_temp": 540.0,
            "time_series": ts_data_2,
        }
    )

    payload = build_macs_batch_payload(mem_db, batch_id)
    assert payload is not None
    assert payload["batch_id"] == batch_id
    assert payload["name"] == "Test Batch 1"
    assert payload["run_count"] == 2
    assert payload["pass_count"] == 2
    assert payload["fail_count"] == 0
    assert payload["error_count"] == 0
    assert payload["reliability_percent"] == 100.0
    assert "setup" in payload
    assert "groups" in payload["setup"]
    assert "shear_check" in payload
    assert payload["shear_check"]["batch_id"] == batch_id
    assert payload["shear_check"]["checked"] == 2
    assert isinstance(payload["shear_check"]["sub_limit_runs"], list)

    charts = payload["charts"]
    assert "scatter" in charts
    assert "totalCapacity" in charts
    assert "beamTemp" in charts
    assert "meshTemp" in charts

    png_magic = b"\x89PNG\r\n\x1a\n"
    for key in ("scatter", "totalCapacity", "beamTemp", "meshTemp"):
        chart_b64 = charts[key]
        assert isinstance(chart_b64, str)
        raw = base64.b64decode(chart_b64)
        assert raw.startswith(png_magic)


def test_client_request_timeout():
    client = UploadCanvasClient()
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.status = 200
        mock_open.return_value.__enter__.return_value.read.return_value = b'{"ok": true}'
        client._request("GET", "/test")
        assert mock_open.call_args[1].get("timeout") == 30


def test_endpoints_attach_macs_batch(mem_db):
    api = TestClient(app)
    with patch("macs_automation.upload_canvas_router._get_db", return_value=mem_db), \
         patch("macs_automation.upload_canvas_router._get_latest_run_for_job") as mock_run, \
         patch("macs_automation.upload_canvas_router.build_macs_batch_payload") as mock_batch, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.create_handoff") as mock_handoff, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.link_project") as mock_link, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.push_run") as mock_push, \
         patch("macs_automation.upload_canvas.UploadCanvasClient.get_summary") as mock_summary:

        mock_run.return_value = {
            "id": 10,
            "side_a_critical_temp": 520.0,
            "side_a_sec": "UB 457x191x82",
            "u_sec_size": "UB 457x191x82",
        }
        mock_batch.return_value = {"batch_id": "b-1", "name": "Batch 1", "run_count": 100}
        mock_handoff.return_value = {"handoff_id": "h-1", "url": "http://localhost:3000/?handoff=h-1"}
        mock_summary.return_value = {"project_id": "p-1"}

        # Handoff
        res_ho = api.post("/api/imacs/jobs/b-1/upload-canvas-handoff")
        assert res_ho.status_code == 200
        sent_payload = mock_handoff.call_args[0][0]
        assert "macs_batch" in sent_payload
        assert sent_payload["macs_batch"]["batch_id"] == "b-1"

        # Link
        res_link = api.post("/api/imacs/jobs/b-1/upload-canvas-link", json={"project_id": "p-1"})
        assert res_link.status_code == 200
        sent_push = mock_push.call_args[0][1]
        assert "macs_batch" in sent_push
        assert sent_push["macs_batch"]["batch_id"] == "b-1"

        # Push
        res_push = api.post("/api/imacs/jobs/b-1/upload-canvas-push")
        assert res_push.status_code == 200
        sent_push_again = mock_push.call_args[0][1]
        assert "macs_batch" in sent_push_again



def test_sidecar_summary_endpoint_handles_unauthorized_gracefully():
    api = TestClient(app)
    with patch("macs_automation.upload_canvas.UploadCanvasClient.get_summary") as mock_summary:
        mock_summary.side_effect = UploadCanvasError("Missing or invalid IMACS_APP_KEY", 401)
        res = api.get("/api/imacs/jobs/batch-test-unauth/upload-canvas-summary")
        assert res.status_code == 200
        data = res.json()
        assert data["summary"] is None


def test_run_in_a_batch_shares_that_batch_imacs_job_id(tmp_path):
    path = tmp_path / "share.db"
    db = ResultsDB(path, check_same_thread=False)
    batch_id = "batch-share-1"
    db.insert_batch(batch_id=batch_id, mode="single", total_expected=2)
    first = db.insert_run(
        {"_batch_id": batch_id, "span1": 9.0, "span2": 9.0, "numbeam": 2},
        {"comp_failure": 0, "time_series": []},
    )
    second = db.insert_run(
        {"_batch_id": batch_id, "span1": 9.0, "span2": 9.0, "numbeam": 2},
        {"comp_failure": 0, "time_series": []},
    )
    db.close()

    from macs_automation.upload_canvas_router import _get_db

    app.dependency_overrides[_get_db] = lambda: ResultsDB(path, check_same_thread=False)
    api = TestClient(app)
    try:
        with patch("macs_automation.upload_canvas.UploadCanvasClient.get_summary", return_value=None):
            by_first = api.get(f"/api/imacs/jobs/{first}/upload-canvas-summary")
            by_second = api.get(f"/api/imacs/jobs/{second}/upload-canvas-summary")
            by_batch = api.get(f"/api/imacs/jobs/{batch_id}/upload-canvas-summary")
    finally:
        app.dependency_overrides.pop(_get_db, None)

    assert by_first.status_code == 200
    assert by_second.status_code == 200
    assert by_batch.status_code == 200
    shared = by_batch.json()["imacs_job_id"]
    assert by_first.json()["imacs_job_id"] == shared
    assert by_second.json()["imacs_job_id"] == shared


def test_standalone_run_keeps_its_own_imacs_job_id(tmp_path):
    path = tmp_path / "solo.db"
    db = ResultsDB(path, check_same_thread=False)
    run_id = db.insert_run(
        {"span1": 9.0, "span2": 9.0, "numbeam": 2},
        {"comp_failure": 0, "time_series": []},
    )
    db.close()

    from macs_automation.upload_canvas_router import _get_db

    app.dependency_overrides[_get_db] = lambda: ResultsDB(path, check_same_thread=False)
    api = TestClient(app)
    try:
        with patch("macs_automation.upload_canvas.UploadCanvasClient.get_summary", return_value=None):
            by_run = api.get(f"/api/imacs/jobs/{run_id}/upload-canvas-summary")
            by_other = api.get("/api/imacs/jobs/other-batch/upload-canvas-summary")
    finally:
        app.dependency_overrides.pop(_get_db, None)

    assert by_run.json()["imacs_job_id"] != by_other.json()["imacs_job_id"]


def test_pre_49_sqlite_opens_and_first_call_creates_local_job_links(tmp_path):
    import sqlite3

    legacy = tmp_path / "pre49.db"
    conn = sqlite3.connect(legacy)
    conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, uuid TEXT, batch_id TEXT)")
    conn.execute("INSERT INTO runs (id, uuid, batch_id) VALUES (1, 'run-kept', NULL)")
    conn.commit()
    conn.close()

    db = ResultsDB(legacy)
    tables_after_open = {
        row[0]
        for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "local_job_links" not in tables_after_open
    assert db.conn.execute("SELECT id, uuid FROM runs WHERE id = 1").fetchone() == (1, "run-kept")
    run_cols = {row[1] for row in db.conn.execute("PRAGMA table_info(runs)")}
    assert "imacs_job_id" not in run_cols

    job_id = get_or_create_imacs_job_id(db, "batch-legacy")
    assert len(job_id) == 36
    tables_after_call = {
        row[0]
        for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "local_job_links" in tables_after_call
    assert db.conn.execute("SELECT id, uuid FROM runs WHERE id = 1").fetchone() == (1, "run-kept")
    db.close()


def test_payload_does_not_upload_the_database_file(tmp_path):
    import base64
    import json

    db_path = tmp_path / "results.db"
    db = ResultsDB(db_path)
    run_id = db.insert_run(
        {"span1": 9.0, "span2": 9.0, "numbeam": 2, "uSecSize": "UB 457x191x82"},
        {"comp_failure": 0, "side_a_critical_temp": 620.0, "time_series": []},
    )
    run = db.get_run(run_id)
    payload = build_macs_run_payload(run, "job-1", version="0.1.0-rc.19", db=db)
    blob = json.dumps(payload)
    raw = db_path.read_bytes()
    db.close()

    assert b"SQLite format 3" not in blob.encode("utf-8")
    assert base64.b64encode(raw).decode("ascii") not in blob
    assert "results.db" not in blob
    assert "database" not in payload
    assert "sqlite" not in payload


def test_get_client_defaults_dev_key_for_localhost(tmp_path):
    from macs_automation.upload_canvas_router import _get_client
    db = ResultsDB(tmp_path / "fresh.db")
    client = _get_client(db)
    assert client.app_key == "dev-imacs-local-key"
