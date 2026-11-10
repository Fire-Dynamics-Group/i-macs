"""Tests for the upload-canvas MACS link integration in i-macs sidecar."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from macs_automation.db import ResultsDB
from macs_automation.upload_canvas import (
    get_or_create_imacs_job_id,
    build_macs_run_payload,
    build_macs_batch_payload,
    compute_section_factor,
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
        "exposure": "4-sided",
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
    assert payload["exposure"] == "4-sided"
    assert payload["section_factor"] == 159.4
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


def test_section_factor_uses_blue_book_not_140():
    """UB_SECTIONS keys are lowercase. Both spellings are the same real factor."""
    assert compute_section_factor("UB 457x191x82", "3-sided") == 138.1
    assert compute_section_factor("457x191x82", "3-sided") == 138.1
    assert compute_section_factor("ub 457x191x82", "4-sided") == 159.4


def test_unknown_section_does_not_invent_section_factor_140():
    with pytest.raises(UploadCanvasError) as exc:
        compute_section_factor("NOT-A-SECTION", "3-sided")
    assert "140" in str(exc.value)


def test_payload_fails_when_critical_temp_section_or_exposure_is_missing():
    base = {
        "id": 7,
        "uuid": "run-7",
        "side_a_critical_temp": 620.0,
        "side_a_sec": "UB 305x165x40",
        "exposure": "3-sided",
        "max_temperature": 800.0,
    }
    missing_temp = {k: v for k, v in base.items() if k != "side_a_critical_temp"}
    with pytest.raises(UploadCanvasError) as exc:
        build_macs_run_payload(missing_temp, "job", version="0.1.0-rc.19")
    assert "550" in str(exc.value)

    missing_section = {k: v for k, v in base.items() if k != "side_a_sec"}
    with pytest.raises(UploadCanvasError) as exc:
        build_macs_run_payload(missing_section, "job", version="0.1.0-rc.19")
    assert "UB 457x191x82" in str(exc.value)

    missing_exposure = {k: v for k, v in base.items() if k != "exposure"}
    with pytest.raises(UploadCanvasError) as exc:
        build_macs_run_payload(missing_exposure, "job", version="0.1.0-rc.19")
    assert "3-sided" in str(exc.value)


def test_client_version_comes_from_macs_app_version(monkeypatch):
    monkeypatch.setenv("MACS_APP_VERSION", "9.9.9-test")
    payload = build_macs_run_payload(
        {
            "id": 7,
            "uuid": "run-7",
            "side_b_critical_temp": 540.0,
            "side_b_sec": "UB 457x191x82",
            "exposure": "3-sided",
        },
        "job-uuid-1",
    )
    assert payload["schema"] == "fd-macs-reliability/2"
    assert payload["client_version"] == "9.9.9-test"
    assert payload["client_version"] != "0.1.0-rc.19"
    assert payload["section_factor"] == 138.1


def test_client_version_fails_when_unset(monkeypatch):
    monkeypatch.delenv("MACS_APP_VERSION", raising=False)
    with pytest.raises(UploadCanvasError) as exc:
        build_macs_run_payload(
            {
                "side_a_critical_temp": 500.0,
                "side_a_sec": "UB 457x191x82",
                "exposure": "3-sided",
            },
            "job",
        )
    assert "MACS_APP_VERSION" in str(exc.value)


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


def test_sidecar_handoff_and_link_endpoints(monkeypatch):
    monkeypatch.setenv("MACS_APP_VERSION", "0.1.0-rc.19")
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
            "exposure": "3-sided",
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
    # The seeded runs have a real section and critical temperature, and no
    # exposure. The factor must not fall back to 140 or an assumed 3-sided.
    assert payload["governing_section"] == "UB 457x191x82"
    assert payload["critical_temp"] == 540.0
    assert payload["section_factor"] is None

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


def test_endpoints_attach_macs_batch(mem_db, monkeypatch):
    monkeypatch.setenv("MACS_APP_VERSION", "0.1.0-rc.19")
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
            "exposure": "3-sided",
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



@pytest.mark.parametrize(
    "code,detail",
    [
        (401, "Missing or invalid IMACS_APP_KEY"),
        (403, "IMACS_APP_KEY is rejected (wrong key)"),
        (503, "Service unavailable (backend IMACS_APP_KEY unset or offline)."),
    ],
)
def test_summary_401_403_503_are_not_an_unlinked_job(code, detail):
    api = TestClient(app)
    with patch("macs_automation.upload_canvas.UploadCanvasClient.get_summary") as mock_summary:
        mock_summary.side_effect = UploadCanvasError(detail, code)
        res = api.get("/api/imacs/jobs/batch-test-unauth/upload-canvas-summary")
    assert res.status_code == code
    assert res.json().get("summary") is not None or "summary" not in res.json()
    assert detail in res.json()["detail"]


def _http_error(code: int):
    import urllib.error
    return urllib.error.HTTPError(
        url="http://127.0.0.1:8001/imacs/x",
        code=code,
        msg="error",
        hdrs={},
        fp=None,
    )


def test_client_error_handling_403():
    client = UploadCanvasClient(
        backend_url="http://test-backend",
        upload_canvas_url="http://test-web",
        app_key="dummy-key",
    )
    with patch("urllib.request.urlopen", side_effect=_http_error(403)):
        with pytest.raises(UploadCanvasError) as exc_info:
            client.create_handoff({"schema": "fd-macs-reliability/2"})
    assert exc_info.value.status_code == 403
    assert "wrong key" in str(exc_info.value)


def test_summary_404_stays_unlinked():
    client = UploadCanvasClient(
        backend_url="http://test-backend",
        upload_canvas_url="http://test-web",
        app_key="dummy-key",
    )
    with patch("urllib.request.urlopen", side_effect=_http_error(404)):
        assert client.get_summary("job-missing") is None


def test_link_404_is_not_success_and_does_not_open_browser():
    api = TestClient(app)
    with patch(
        "macs_automation.upload_canvas_router._get_latest_run_for_job",
        return_value={
            "id": 10,
            "side_a_critical_temp": 520.0,
            "side_a_sec": "UB 457x191x82",
        },
    ), patch("macs_automation.upload_canvas_router._safe_open_browser") as mock_open, patch(
        "urllib.request.urlopen", side_effect=_http_error(404)
    ):
        res = api.post(
            "/api/imacs/jobs/batch-404/upload-canvas-link",
            json={"project_id": "missing-project"},
        )
    assert res.status_code == 404
    assert res.json().get("status") != "linked"
    mock_open.assert_not_called()


def test_push_404_is_not_success_and_does_not_open_browser():
    class _Ok:
        status = 200

        def read(self):
            return (
                b'{"project_id":"p-1","project_name":"Site Plan Time Eq",'
                b'"last_sent_at":null,"outcome":null}'
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(req, timeout=30):
        if getattr(req, "method", "GET") == "GET":
            return _Ok()
        raise _http_error(404)

    api = TestClient(app)
    with patch(
        "macs_automation.upload_canvas_router._get_latest_run_for_job",
        return_value={
            "id": 10,
            "side_a_critical_temp": 520.0,
            "side_a_sec": "UB 457x191x82",
        },
    ), patch("macs_automation.upload_canvas_router._safe_open_browser") as mock_open, patch(
        "urllib.request.urlopen", side_effect=urlopen
    ):
        res = api.post("/api/imacs/jobs/batch-404/upload-canvas-push")
    assert res.status_code == 404
    assert res.json().get("status") != "pushed"
    mock_open.assert_not_called()


def _clear_upload_canvas_env(monkeypatch):
    for name in (
        "MACS_PACKAGED",
        "IMACS_APP_KEY",
        "IMACS_BACKEND_BASE_URL",
        "UPLOAD_CANVAS_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_get_client_defaults_dev_key_for_localhost(tmp_path, monkeypatch):
    """Local dev with nothing configured still talks to localhost with the dev key."""
    _clear_upload_canvas_env(monkeypatch)
    from macs_automation.upload_canvas_router import _get_client
    db = ResultsDB(tmp_path / "fresh.db")
    client = _get_client(db)
    assert client.backend_url == "http://127.0.0.1:8001"
    assert client.upload_canvas_url == "http://localhost:3000"
    assert client.app_key == "dev-imacs-local-key"
    db.close()


def test_localhost_fallback_does_not_override_a_set_key(tmp_path, monkeypatch):
    """A key in the environment or in settings wins over the localhost dev key."""
    _clear_upload_canvas_env(monkeypatch)
    monkeypatch.setenv("IMACS_APP_KEY", "env-key-from-test")
    from macs_automation.upload_canvas_router import _get_client

    db = ResultsDB(tmp_path / "env-key.db")
    client = _get_client(db)
    assert client.app_key == "env-key-from-test"
    assert client.app_key != "dev-imacs-local-key"

    db.set_setting("imacs_app_key", "settings-key-from-test")
    monkeypatch.setenv("IMACS_APP_KEY", "env-key-from-test")
    client = _get_client(db)
    assert client.app_key == "settings-key-from-test"
    db.close()


def test_configured_env_urls_are_used(tmp_path, monkeypatch):
    _clear_upload_canvas_env(monkeypatch)
    monkeypatch.setenv("IMACS_BACKEND_BASE_URL", "https://api.example.test")
    monkeypatch.setenv("UPLOAD_CANVAS_BASE_URL", "https://canvas.example.test/")
    monkeypatch.setenv("IMACS_APP_KEY", "env-key-from-test")
    from macs_automation.upload_canvas_router import _get_client

    db = ResultsDB(tmp_path / "env-urls.db")
    client = _get_client(db)
    assert client.backend_url == "https://api.example.test"
    assert client.upload_canvas_url == "https://canvas.example.test"
    assert client.app_key == "env-key-from-test"
    db.close()


def test_packaged_unset_urls_say_link_is_not_configured(tmp_path, monkeypatch):
    _clear_upload_canvas_env(monkeypatch)
    monkeypatch.setenv("MACS_PACKAGED", "1")
    from fastapi import HTTPException
    from macs_automation.upload_canvas_router import _get_client, get_config

    db = ResultsDB(tmp_path / "packaged.db")
    with pytest.raises(HTTPException) as exc:
        _get_client(db)
    assert exc.value.status_code == 503
    assert "not configured" in str(exc.value.detail).lower()

    with pytest.raises(HTTPException) as config_exc:
        get_config(db)
    assert config_exc.value.status_code == 503
    assert "not configured" in str(config_exc.value.detail).lower()


def test_settings_urls_and_key_win_over_env(tmp_path, monkeypatch):
    _clear_upload_canvas_env(monkeypatch)
    monkeypatch.setenv("IMACS_BACKEND_BASE_URL", "https://env.example.test")
    monkeypatch.setenv("UPLOAD_CANVAS_BASE_URL", "https://env-canvas.example.test")
    monkeypatch.setenv("IMACS_APP_KEY", "env-key-from-test")
    from macs_automation.upload_canvas_router import _get_client

    db = ResultsDB(tmp_path / "settings-win.db")
    db.set_setting("backend_base_url", "https://settings.example.test")
    db.set_setting("upload_canvas_base_url", "https://settings-canvas.example.test/")
    db.set_setting("imacs_app_key", "settings-key-from-test")
    client = _get_client(db)
    assert client.backend_url == "https://settings.example.test"
    assert client.upload_canvas_url == "https://settings-canvas.example.test"
    assert client.app_key == "settings-key-from-test"
    db.close()


def test_packaged_app_uses_env_urls_and_key(tmp_path, monkeypatch):
    _clear_upload_canvas_env(monkeypatch)
    monkeypatch.setenv("MACS_PACKAGED", "1")
    monkeypatch.setenv("IMACS_BACKEND_BASE_URL", "http://127.0.0.1:8001")
    monkeypatch.setenv("UPLOAD_CANVAS_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("IMACS_APP_KEY", "env-key-from-test")
    from macs_automation.upload_canvas_router import _get_client

    db = ResultsDB(tmp_path / "packaged-env.db")
    client = _get_client(db)
    assert client.backend_url == "http://127.0.0.1:8001"
    assert client.upload_canvas_url == "http://localhost:3000"
    assert client.app_key == "env-key-from-test"
    db.close()
