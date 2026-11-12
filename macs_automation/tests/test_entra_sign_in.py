"""FD Microsoft sign-in for the desktop helper.

The authorize URL must use the Entra app Upload Canvas and Mail Marshal
already use. The identity token stays in the local database and is sent
as a bearer token. It is not returned by the config API and not logged.
"""
from __future__ import annotations

import time
import urllib.parse
import urllib.request

import pytest
from fastapi.testclient import TestClient

from macs_automation.app import app
from macs_automation.db import ResultsDB
from macs_automation.entra_sign_in import (
    ENTRA_CLIENT_ID,
    ENTRA_TENANT_ID,
    REDIRECT_URI,
    SignInSession,
    begin_auth_code_flow,
)


def _use_db(path):
    from macs_automation.upload_canvas_router import _get_db

    def open_db():
        return ResultsDB(path, check_same_thread=False)

    app.dependency_overrides[_get_db] = open_db
    return _get_db


def _clear_env(monkeypatch):
    for name in (
        "MACS_PACKAGED",
        "IMACS_APP_KEY",
        "IMACS_BACKEND_BASE_URL",
        "UPLOAD_CANVAS_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_authorize_url_uses_the_existing_fd_app():
    flow = begin_auth_code_flow()
    uri = flow["auth_uri"]
    parsed = urllib.parse.urlparse(uri)
    query = urllib.parse.parse_qs(parsed.query)
    assert ENTRA_TENANT_ID in parsed.path
    assert query["client_id"] == [ENTRA_CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]
    assert "client_secret" not in uri
    assert "code_verifier" not in uri


def test_loopback_stores_the_session_without_echoing_the_code(tmp_path, monkeypatch):
    code = "auth-code-not-a-token"
    id_token = "id-token-not-for-logs"
    monkeypatch.setattr(
        "macs_automation.entra_sign_in.exchange_auth_code",
        lambda flow, auth_response: {
            "id_token": id_token,
            "refresh_token": "refresh-token-value",
            "expires_in": 3600,
            "id_token_claims": {
                "preferred_username": "sam@firedynamicsgroup.com",
                "name": "Sam Bennett",
            },
        },
    )
    db = ResultsDB(tmp_path / "sign-in.db", check_same_thread=False)
    session = SignInSession(port=0)
    try:
        session.start(db)
        body = urllib.parse.urlencode(
            {"code": code, "state": "state-from-microsoft"}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{session.bound_port}/callback",
            data=body,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            page = resp.read().decode("utf-8")
        assert code not in page
        assert id_token not in page
        assert "Signed in" in page
        view = ResultsDB(tmp_path / "sign-in.db", check_same_thread=False)
        assert view.get_setting("entra_account_email") == "sam@firedynamicsgroup.com"
        assert view.get_setting("entra_id_token") == id_token
        view.close()
    finally:
        session.close()
        db.close()


def test_config_reports_sign_in_without_returning_the_token(tmp_path, monkeypatch, capsys):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MACS_PACKAGED", "1")
    path = tmp_path / "session.db"
    db = ResultsDB(path)
    db.set_setting("entra_id_token", "id-token-not-for-logs")
    db.set_setting("entra_account_email", "sam@firedynamicsgroup.com")
    db.set_setting("entra_account_name", "Sam Bennett")
    db.set_setting("entra_expires_at", str(int(time.time()) + 3600))
    db.close()
    token = _use_db(path)
    api = TestClient(app)
    try:
        shown = api.get("/api/imacs/config")
        assert shown.status_code == 200
        body = shown.json()
        assert body["signed_in"] is True
        assert body["account_email"] == "sam@firedynamicsgroup.com"
        assert body["account_name"] == "Sam Bennett"
        assert "id-token-not-for-logs" not in shown.text
        signed_out = api.post("/api/imacs/auth/sign-out")
        assert signed_out.status_code == 200
        after = api.get("/api/imacs/config").json()
        assert after["signed_in"] is False
    finally:
        app.dependency_overrides.pop(token, None)
    captured = capsys.readouterr()
    assert "id-token-not-for-logs" not in captured.out
    assert "id-token-not-for-logs" not in captured.err


def test_signed_in_search_sends_the_bearer_and_skips_the_sign_in_block(
    tmp_path, monkeypatch
):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MACS_PACKAGED", "1")
    path = tmp_path / "bearer.db"
    db = ResultsDB(path)
    db.set_setting("entra_id_token", "id-token-not-for-logs")
    db.set_setting("entra_expires_at", str(int(time.time()) + 3600))
    db.close()
    token = _use_db(path)
    captured = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"projects":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _urlopen(req, timeout=30):
        captured["authorization"] = req.get_header("Authorization")
        captured["app_key"] = req.get_header("X-imacs-app-key")
        return _Resp()

    api = TestClient(app)
    try:
        with monkeypatch.context() as ctx:
            ctx.setattr("urllib.request.urlopen", _urlopen)
            res = api.get("/api/imacs/upload-canvas-projects?q=TimeEq")
    finally:
        app.dependency_overrides.pop(token, None)
    assert res.status_code == 200
    assert captured["authorization"] == "Bearer id-token-not-for-logs"
    assert captured["app_key"] is None
    assert "id-token-not-for-logs" not in res.text
