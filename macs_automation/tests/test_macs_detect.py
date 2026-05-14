"""Tests for the MACS+ detection chain.

Each detection step is mocked in isolation. Together they exercise the
chain order, the .NET COM mscoree.dll fallback, the missing-hive guard,
and the InstallLocation → DisplayIcon → UninstallString priority.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from macs_automation import macs_detect


@pytest.fixture
def real_data_xml(tmp_path):
    """Create a real MACS+_NNN tree at tmp_path and return the install folder."""
    install = tmp_path / "MACS+_304"
    data_dir = install / "EN" / "Data"
    data_dir.mkdir(parents=True)
    (data_dir / "Data.xml").write_text(
        "<?xml version='1.0'?><Root><Signature>FRACOFParameters</Signature></Root>",
        encoding="utf-8",
    )
    return install


@pytest.fixture(autouse=True)
def reset_cache():
    macs_detect.reset_cache()
    yield
    macs_detect.reset_cache()


@pytest.fixture
def clean_env(monkeypatch):
    """Remove MACS_DATA_PATH so it doesn't short-circuit the chain."""
    monkeypatch.delenv("MACS_DATA_PATH", raising=False)


@pytest.fixture
def stub_winreg(monkeypatch):
    """Default: every winreg lookup raises FileNotFoundError. Tests opt-in
    by overriding individual lookups via the returned helper.
    """
    # Map: (hive, subkey) -> dict of values OR list[str] of child key names
    keys: dict = {}

    class FakeKey:
        def __init__(self, ident):
            self.ident = ident

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open_key(hive, subkey, *args, **kwargs):
        ident = (hive, subkey.replace("/", "\\"))
        if ident not in keys:
            raise FileNotFoundError(f"no such key: {ident}")
        return FakeKey(ident)

    def fake_query_value_ex(handle, name):
        entry = keys[handle.ident]
        values = entry.get("values", {})
        if name not in values:
            raise FileNotFoundError(f"no such value: {handle.ident}/{name}")
        return (values[name], 1)

    def fake_enum_key(handle, index):
        entry = keys[handle.ident]
        children = entry.get("children", [])
        if index >= len(children):
            raise OSError("end of enum")
        return children[index]

    monkeypatch.setattr(macs_detect.winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(macs_detect.winreg, "QueryValueEx", fake_query_value_ex)
    monkeypatch.setattr(macs_detect.winreg, "EnumKey", fake_enum_key)

    return keys


# ─── Detection chain ──────────────────────────────────────────────────────────


class TestEnvOverride:
    def test_macs_data_path_env_wins(self, real_data_xml, monkeypatch):
        target = real_data_xml / "EN" / "Data" / "Data.xml"
        monkeypatch.setenv("MACS_DATA_PATH", str(target))
        result = macs_detect.detect()
        assert result.data_xml_path == target
        assert "MACS_DATA_PATH env" in result.attempted_paths[0]

    def test_env_pointing_at_missing_file_falls_through(
        self, tmp_path, real_data_xml, monkeypatch, stub_winreg, clean_env
    ):
        # Env set but file doesn't exist — chain should continue.
        monkeypatch.setenv("MACS_DATA_PATH", str(tmp_path / "nope.xml"))
        # Provide a filesystem hit so something else resolves.
        # Reuse real_data_xml by monkeypatching the FS search roots.
        monkeypatch.setattr(
            macs_detect,
            "_filesystem_glob_roots",
            lambda: [real_data_xml.parent],
        )
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"


class TestFracofClsidChain:
    def test_resolves_via_scti11(
        self, real_data_xml, clean_env, stub_winreg
    ):
        dll = real_data_xml / "EN" / "FRACOF.dll"
        dll.parent.mkdir(parents=True, exist_ok=True)
        dll.write_bytes(b"")
        clsid = "{ABC-123}"
        import winreg as _wr
        stub_winreg[(_wr.HKEY_CLASSES_ROOT, "SCTI11.FRACOF\\CLSID")] = {
            "values": {"": clsid},
        }
        stub_winreg[(_wr.HKEY_CLASSES_ROOT, f"CLSID\\{clsid}\\InprocServer32")] = {
            "values": {"": str(dll)},
        }
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"
        assert result.com_registered is True

    def test_scti9_fallback_when_scti11_missing(
        self, real_data_xml, clean_env, stub_winreg
    ):
        dll = real_data_xml / "engine" / "FRACOF.dll"
        dll.parent.mkdir(parents=True, exist_ok=True)
        dll.write_bytes(b"")
        clsid = "{XYZ-789}"
        import winreg as _wr
        stub_winreg[(_wr.HKEY_CLASSES_ROOT, "SCTI9.FRACOF\\CLSID")] = {
            "values": {"": clsid},
        }
        stub_winreg[(_wr.HKEY_CLASSES_ROOT, f"CLSID\\{clsid}\\InprocServer32")] = {
            "values": {"": str(dll)},
        }
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"

    def test_mscoree_uses_codebase_for_dotnet_com(
        self, real_data_xml, clean_env, stub_winreg
    ):
        real_dll = real_data_xml / "FRACOF.dll"
        real_dll.write_bytes(b"")
        clsid = "{NET-COM}"
        import winreg as _wr
        stub_winreg[(_wr.HKEY_CLASSES_ROOT, "SCTI11.FRACOF\\CLSID")] = {
            "values": {"": clsid},
        }
        stub_winreg[(_wr.HKEY_CLASSES_ROOT, f"CLSID\\{clsid}\\InprocServer32")] = {
            "values": {
                "": r"C:\Windows\SysWOW64\mscoree.dll",
                "CodeBase": real_dll.as_uri(),
            },
        }
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"


class TestUninstallRegistry:
    def test_hkcu_per_user_install(self, real_data_xml, clean_env, stub_winreg):
        """Diana's case: per-user install under HKCU, no HKLM entry."""
        import winreg as _wr
        # HKCU Uninstall has one child key: MACS+_304
        uninstall_root = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        stub_winreg[(_wr.HKEY_CURRENT_USER, uninstall_root)] = {
            "children": ["MACS+_304"],
        }
        stub_winreg[(_wr.HKEY_CURRENT_USER, f"{uninstall_root}\\MACS+_304")] = {
            "values": {
                "DisplayName": "MACS+_304",
                "InstallLocation": str(real_data_xml),
            },
        }
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"

    def test_filters_non_macs_entries(self, real_data_xml, clean_env, stub_winreg):
        import winreg as _wr
        uninstall_root = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, uninstall_root)] = {
            "children": ["NotMacs", "MACS+_304", "AlsoNotMacs"],
        }
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\NotMacs")] = {
            "values": {"DisplayName": "Some Other App"},
        }
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\MACS+_304")] = {
            "values": {
                "DisplayName": "MACS+_304",
                "InstallLocation": str(real_data_xml),
            },
        }
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\AlsoNotMacs")] = {
            "values": {"DisplayName": "Microsoft Office"},
        }
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"

    def test_prefers_higher_version(self, tmp_path, clean_env, stub_winreg):
        """MACS+_304 wins over MACS+_303 and MACS+."""
        v304 = tmp_path / "MACS+_304"
        (v304 / "EN" / "Data").mkdir(parents=True)
        (v304 / "EN" / "Data" / "Data.xml").write_text("<r/>")
        v303 = tmp_path / "MACS+_303"
        (v303 / "EN" / "Data").mkdir(parents=True)
        (v303 / "EN" / "Data" / "Data.xml").write_text("<r/>")
        v_plain = tmp_path / "MACS+"
        (v_plain / "EN" / "Data").mkdir(parents=True)
        (v_plain / "EN" / "Data" / "Data.xml").write_text("<r/>")

        import winreg as _wr
        uninstall_root = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, uninstall_root)] = {
            "children": ["MACS+", "MACS+_303", "MACS+_304"],
        }
        for ver, p in [("MACS+", v_plain), ("MACS+_303", v303), ("MACS+_304", v304)]:
            stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\{ver}")] = {
                "values": {"DisplayName": ver, "InstallLocation": str(p)},
            }
        result = macs_detect.detect()
        assert v304 in result.data_xml_path.parents

    def test_display_icon_fallback_when_install_location_empty(
        self, real_data_xml, clean_env, stub_winreg
    ):
        import winreg as _wr
        uninstall_root = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, uninstall_root)] = {
            "children": ["MACS+_304"],
        }
        # DisplayIcon points at an exe inside the install folder; strip ,0 suffix
        icon = real_data_xml / "MACS+.exe"
        icon.write_bytes(b"")
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\MACS+_304")] = {
            "values": {
                "DisplayName": "MACS+_304",
                "InstallLocation": "",
                "DisplayIcon": f"{icon},0",
            },
        }
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"

    def test_uninstall_string_parent_as_last_field_resort(
        self, real_data_xml, clean_env, stub_winreg
    ):
        import winreg as _wr
        uninstall_root = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, uninstall_root)] = {
            "children": ["MACS+_304"],
        }
        uninst_exe = real_data_xml / "uninstall.exe"
        uninst_exe.write_bytes(b"")
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\MACS+_304")] = {
            "values": {
                "DisplayName": "MACS+_304",
                "UninstallString": f'"{uninst_exe}" /S',
            },
        }
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"

    def test_missing_hkcu_wow6432_does_not_raise(self, real_data_xml, clean_env, stub_winreg):
        """HKCU\\WOW6432Node\\...\\Uninstall doesn't exist on most machines —
        the chain must tolerate FileNotFoundError on that open, not bail."""
        # Only register HKLM Uninstall with a hit, leave HKCU/WOW6432 unset.
        import winreg as _wr
        uninstall_root = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, uninstall_root)] = {
            "children": ["MACS+_304"],
        }
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\MACS+_304")] = {
            "values": {
                "DisplayName": "MACS+_304",
                "InstallLocation": str(real_data_xml),
            },
        }
        result = macs_detect.detect()  # must not raise
        assert result.data_xml_path is not None


class TestStartMenu:
    def test_walks_up_from_lnk_target(
        self, tmp_path, real_data_xml, clean_env, stub_winreg, monkeypatch
    ):
        # Place a fake .lnk under the Start Menu glob; target is a launcher exe
        # in a SIBLING dir of the install root — so target.parent is NOT the
        # install root, we have to walk UP.
        nested = real_data_xml / "bin" / "launcher.exe"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_bytes(b"")

        appdata = tmp_path / "AppDataRoaming"
        sm = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "MACS+_304"
        sm.mkdir(parents=True)
        lnk = sm / "MACS+.lnk"
        lnk.write_bytes(b"")

        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.delenv("ProgramData", raising=False)
        monkeypatch.setattr(
            macs_detect, "_resolve_shortcut", lambda p: str(nested)
        )

        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"

    def test_no_start_menu_entries(self, tmp_path, clean_env, stub_winreg, monkeypatch):
        appdata = tmp_path / "AppDataRoaming"
        appdata.mkdir()
        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.delenv("ProgramData", raising=False)
        monkeypatch.setattr(macs_detect, "_filesystem_glob_roots", lambda: [])
        result = macs_detect.detect()
        assert result.data_xml_path is None


class TestAppPaths:
    def test_app_paths_registry(
        self, real_data_xml, clean_env, stub_winreg
    ):
        import winreg as _wr
        exe = real_data_xml / "MACS+.exe"
        exe.write_bytes(b"")
        stub_winreg[(
            _wr.HKEY_LOCAL_MACHINE,
            "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\MACS+.exe",
        )] = {"values": {"": str(exe)}}
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"


class TestFilesystemGlob:
    def test_localappdata_programs(
        self, tmp_path, real_data_xml, clean_env, stub_winreg, monkeypatch
    ):
        monkeypatch.setattr(
            macs_detect,
            "_filesystem_glob_roots",
            lambda: [real_data_xml.parent],
        )
        result = macs_detect.detect()
        assert result.data_xml_path == real_data_xml / "EN" / "Data" / "Data.xml"


class TestNothingFound:
    def test_returns_none_with_attempted_paths(
        self, tmp_path, clean_env, stub_winreg, monkeypatch
    ):
        monkeypatch.setattr(macs_detect, "_filesystem_glob_roots", lambda: [])
        monkeypatch.setenv("APPDATA", str(tmp_path / "no-appdata"))
        monkeypatch.delenv("ProgramData", raising=False)
        result = macs_detect.detect()
        assert result.data_xml_path is None
        assert len(result.attempted_paths) > 0
        # Every chain step should have left a breadcrumb.
        joined = "\n".join(result.attempted_paths)
        assert "CLSID" in joined
        assert "Uninstall" in joined
        assert "Start Menu" in joined
        assert "App Paths" in joined
        assert "filesystem" in joined.lower()


class TestComProbe:
    def test_com_registered_when_prog_id_present(self, real_data_xml, clean_env, stub_winreg):
        import winreg as _wr
        stub_winreg[(_wr.HKEY_CLASSES_ROOT, "SCTI11.FRACOF")] = {"values": {}}
        # Also need Data.xml resolution to succeed via something so the chain finishes
        # — but com_registered is independent. Provide nothing else; data_xml_path
        # will be None but com_registered must still reflect the registry probe.
        result = macs_detect.detect()
        assert result.com_registered is True

    def test_com_not_registered(self, tmp_path, clean_env, stub_winreg, monkeypatch):
        monkeypatch.setattr(macs_detect, "_filesystem_glob_roots", lambda: [])
        result = macs_detect.detect()
        assert result.com_registered is False


class TestCache:
    def test_caches_until_path_invalid(self, real_data_xml, clean_env, stub_winreg, monkeypatch):
        # Quiet the real filesystem so the cache invalidation test isn't
        # rescued by a real MACS+ install on the dev box.
        monkeypatch.setattr(macs_detect, "_filesystem_glob_roots", lambda: [])
        monkeypatch.setenv("APPDATA", str(real_data_xml.parent / "no-appdata"))
        monkeypatch.delenv("ProgramData", raising=False)

        import winreg as _wr
        uninstall_root = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, uninstall_root)] = {
            "children": ["MACS+_304"],
        }
        stub_winreg[(_wr.HKEY_LOCAL_MACHINE, f"{uninstall_root}\\MACS+_304")] = {
            "values": {"DisplayName": "MACS+_304", "InstallLocation": str(real_data_xml)},
        }
        r1 = macs_detect.detect()
        assert r1.data_xml_path is not None

        # Mutate stub so a fresh run would find nothing.
        stub_winreg.clear()
        r2 = macs_detect.detect()
        # Cached — same answer.
        assert r2.data_xml_path == r1.data_xml_path

        # Now delete the file so the cached path no longer resolves.
        r1.data_xml_path.unlink()
        r3 = macs_detect.detect()
        assert r3.data_xml_path is None
