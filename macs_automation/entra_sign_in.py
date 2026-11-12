"""FD Microsoft sign-in for the desktop helper.

Upload Canvas and Mail Marshal already use this public Entra registration
(client 2b180b8a-7cd3-40b2-83dd-8338103ce41e, tenant
8c535dde-8170-4909-8edc-40bbff4924ba). Those identifiers are not secrets;
they are in every authorize URL.

The desktop opens the system browser for an authorization-code + PKCE
login and catches the redirect on http://127.0.0.1:47831/callback.
That redirect URI is not registered yet. It has to be added on the
existing app under Mobile and desktop applications before a real
sign-in can finish. This module does not create or change the
registration.

Tokens are stored only in the local settings database. They are not
logged and are not returned by the config API.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from msal import PublicClientApplication

from macs_automation.db import ResultsDB

log = logging.getLogger("macs_automation.entra_sign_in")

ENTRA_CLIENT_ID = "2b180b8a-7cd3-40b2-83dd-8338103ce41e"
ENTRA_TENANT_ID = "8c535dde-8170-4909-8edc-40bbff4924ba"
AUTHORITY = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 47831
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback"
# `email` is the only scope we pass. MSAL adds the reserved openid,
# profile, and offline_access scopes so the result has an id token and
# a refresh token. That matches the identity token Upload Canvas sends.
SCOPES = ["email"]

SIGN_IN_MESSAGE = "Sign in to Upload Canvas"
NOT_AUTHORISED_MESSAGE = "Not authorised"

_ID_TOKEN = "entra_id_token"
_REFRESH = "entra_refresh_token"
_EXPIRES = "entra_expires_at"
_EMAIL = "entra_account_email"
_NAME = "entra_account_name"
_SESSION_KEYS = (_ID_TOKEN, _REFRESH, _EXPIRES, _EMAIL, _NAME)

_SUCCESS_PAGE = (
    "<!doctype html><meta charset=utf-8><title>MACs+</title>"
    "<p>Signed in. You can close this window and return to MACs+.</p>"
)
_FAILURE_PAGE = (
    "<!doctype html><meta charset=utf-8><title>MACs+</title>"
    "<p>Microsoft sign-in could not be completed. Return to MACs+ and try again.</p>"
)


class SignInError(Exception):
    """A sign-in step failed. The message is safe to show; it has no token."""


def _nonempty(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_public_client() -> PublicClientApplication:
    return PublicClientApplication(ENTRA_CLIENT_ID, authority=AUTHORITY)


def begin_auth_code_flow() -> dict:
    """Build the authorize URL locally. Does not contact Microsoft."""
    flow = build_public_client().initiate_auth_code_flow(
        SCOPES,
        redirect_uri=REDIRECT_URI,
        response_mode="form_post",
    )
    if "auth_uri" not in flow or "client_secret" in flow.get("auth_uri", ""):
        raise SignInError("Microsoft sign-in could not be started.")
    return flow


def exchange_auth_code(flow: dict, auth_response: dict) -> dict:
    result = build_public_client().acquire_token_by_auth_code_flow(
        flow, auth_response, scopes=SCOPES
    )
    if not isinstance(result, dict) or result.get("error") or not result.get("id_token"):
        raise SignInError("Microsoft sign-in could not be completed.")
    return result


def persist_result(db: ResultsDB, result: dict) -> None:
    """Store the identity token and account. Never log `result`."""
    id_token = _nonempty(result.get("id_token"))
    if not id_token:
        raise SignInError("Microsoft did not return an identity token.")
    claims = result.get("id_token_claims") or {}
    email = str(claims.get("preferred_username") or claims.get("email") or "").strip()
    name = str(claims.get("name") or email).strip()
    db.set_setting(_ID_TOKEN, id_token)
    refresh = _nonempty(result.get("refresh_token"))
    if refresh:
        db.set_setting(_REFRESH, refresh)
    expires_in = result.get("expires_in")
    if expires_in:
        db.set_setting(_EXPIRES, str(int(time.time()) + int(expires_in)))
    if email:
        db.set_setting(_EMAIL, email)
    if name:
        db.set_setting(_NAME, name)


def clear_session(db: ResultsDB) -> None:
    for key in _SESSION_KEYS:
        db.delete_setting(key)


def session_view(db: ResultsDB) -> dict:
    """Account fields only. The token is not included."""
    signed_in = bool(_nonempty(db.get_setting(_ID_TOKEN)))
    return {
        "signed_in": signed_in,
        "account_email": db.get_setting(_EMAIL) or "",
        "account_name": db.get_setting(_NAME) or "",
    }


def usable_bearer(db: ResultsDB) -> str:
    """The identity token to send, or "" when the user has not signed in.

    A still-valid token is returned as stored. An expired token is refreshed
    once. The token itself is not logged.
    """
    token = _nonempty(db.get_setting(_ID_TOKEN))
    if not token:
        return ""
    expires = _nonempty(db.get_setting(_EXPIRES))
    if expires is None or int(expires) > time.time() + 60:
        return token
    refresh = _nonempty(db.get_setting(_REFRESH))
    if not refresh:
        return ""
    try:
        result = build_public_client().acquire_token_by_refresh_token(refresh, SCOPES)
    except Exception:
        log.warning("entra refresh failed")
        return ""
    if not isinstance(result, dict) or not result.get("id_token"):
        log.warning("entra refresh returned no identity token")
        return ""
    persist_result(db, result)
    return result["id_token"]


def _form_values(raw: str) -> dict:
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=False)
    return {key: values[0] for key, values in parsed.items() if values}


class SignInSession:
    """One loopback listener. The PKCE verifier stays in memory."""

    def __init__(self, port: int = REDIRECT_PORT):
        self.port = port
        self.error: Optional[str] = None
        self._lock = threading.Lock()
        self.bound_port = port
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._flow: Optional[dict] = None
        self._db_path: Optional[str] = None

    def start(self, db: ResultsDB) -> str:
        with self._lock:
            self._close_unlocked()
            self.error = None
            self._flow = begin_auth_code_flow()
            self._db_path = db.db_path
            try:
                self._httpd = ThreadingHTTPServer(
                    (REDIRECT_HOST, self.port), self._handler_class()
                )
            except OSError as exc:
                self._flow = None
                raise SignInError(
                    "Sign-in could not listen for the Microsoft redirect."
                ) from exc
            self.bound_port = int(self._httpd.server_address[1])
            self._thread = threading.Thread(
                target=self._httpd.serve_forever, name="entra-redirect", daemon=True
            )
            self._thread.start()
            return self._flow["auth_uri"]

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        httpd = self._httpd
        self._httpd = None
        self._flow = None
        if httpd is not None:
            def _stop() -> None:
                httpd.shutdown()
                httpd.server_close()

            threading.Thread(target=_stop, daemon=True).start()

    def _handler_class(self):
        session = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                query = urllib.parse.urlsplit(self.path).query
                self._finish(_form_values(query))

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
                self._finish(_form_values(raw))

            def _finish(self, auth_response: dict):
                ok = session._complete(auth_response)
                body = (_SUCCESS_PAGE if ok else _FAILURE_PAGE).encode("utf-8")
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def _complete(self, auth_response: dict) -> bool:
        with self._lock:
            flow = self._flow
            db_path = self._db_path
        if not flow or not db_path or not auth_response.get("code"):
            self.error = "Microsoft sign-in could not be completed."
            return False
        try:
            result = exchange_auth_code(flow, auth_response)
            db = ResultsDB(db_path, check_same_thread=False)
            try:
                persist_result(db, result)
            finally:
                db.close()
        except Exception:
            log.warning("entra sign-in could not be completed")
            self.error = "Microsoft sign-in could not be completed."
            return False
        self.error = None
        threading.Thread(target=self.close, daemon=True).start()
        return True


sign_in_session = SignInSession()
