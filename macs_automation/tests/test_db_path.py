"""Tests for DB_PATH resolution in app.py.

The installed app previously resolved the SQLite path relative to __file__
inside the PyInstaller bundle, which lands under Program Files and gets either
ACL-denied or virtualized — runs vanished between launches. These tests pin
the resolution order:

    1. MACS_DB_PATH env wins always.
    2. Frozen + no env => %LOCALAPPDATA%\\i-macs\\results.db.
    3. Non-frozen (dev) => <repo>/results.db.
"""

import importlib
import sys
from pathlib import Path

import pytest


def _reload_app(monkeypatch):
    """Reload macs_automation.app under the current env so the module-level
    DB_PATH re-evaluates. Returns the freshly loaded module."""
    import macs_automation.app as app_module
    return importlib.reload(app_module)


@pytest.fixture(autouse=True)
def restore_app(monkeypatch):
    """Restore the module after each test so other tests don't see our
    patched DB_PATH / frozen state."""
    yield
    monkeypatch.delenv("MACS_DB_PATH", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    import macs_automation.app as app_module
    importlib.reload(app_module)


def test_env_override_wins_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    custom = tmp_path / "custom_results.db"
    monkeypatch.setenv("MACS_DB_PATH", str(custom))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    app_module = _reload_app(monkeypatch)
    assert Path(app_module.DB_PATH) == custom


def test_frozen_no_env_falls_back_to_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("MACS_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_module = _reload_app(monkeypatch)
    expected = tmp_path / "i-macs" / "results.db"
    assert Path(app_module.DB_PATH) == expected


def test_env_override_wins_when_not_frozen(monkeypatch, tmp_path):
    """Dev workflow with MACS_DB_PATH set still honors the override."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    custom = tmp_path / "dev_override.db"
    monkeypatch.setenv("MACS_DB_PATH", str(custom))
    app_module = _reload_app(monkeypatch)
    assert Path(app_module.DB_PATH) == custom


def test_resultsdb_creates_missing_parent_dirs(tmp_path):
    """sqlite3.connect does not mkdir, so on a pristine machine the frozen
    fallback %LOCALAPPDATA%\\i-macs\\ doesn't exist and the sidecar died at
    boot with 'unable to open database file' (caught by the rc.13 release
    verify step — it only worked on machines where an earlier run had
    created the folder)."""
    from macs_automation.db import ResultsDB

    db_file = tmp_path / "i-macs" / "results.db"
    assert not db_file.parent.exists()
    ResultsDB(db_file).close()
    assert db_file.exists()


def test_dev_default_is_repo_results_db(monkeypatch):
    """Dev path unchanged: sidecar continues writing to <repo>/results.db."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("MACS_DB_PATH", raising=False)
    app_module = _reload_app(monkeypatch)
    expected = Path(app_module.__file__).resolve().parent.parent / "results.db"
    assert Path(app_module.DB_PATH).resolve() == expected.resolve()
