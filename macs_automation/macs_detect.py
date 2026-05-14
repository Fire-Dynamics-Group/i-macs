"""Auto-detect MACS+ install regardless of where the user put it.

Detection chain (each step returns the first hit; subsequent steps are skipped):

  1. `MACS_DATA_PATH` env var — explicit override.
  2. FRACOF CLSID walk via `HKCR\\SCTI11.FRACOF` / `HKCR\\SCTI9.FRACOF` —
     the registration the engine itself depends on, so picker + engine stay
     in agreement on which install is "live".
  3. Uninstall registry keys, all four hives (HKLM + HKCU, both with and
     without WOW6432Node). `HKCU\\WOW6432Node\\...\\Uninstall` doesn't exist
     on most boxes — every open is wrapped in try/except FileNotFoundError.
  4. Start Menu `.lnk` shortcuts — walks up the `.lnk` target until a
     directory containing `EN\\Data\\Data.xml` is found.
  5. `HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\MACS+.exe`.
  6. Filesystem glob over the common install roots
     (`Program Files (x86)`, `%LOCALAPPDATA%\\Programs`, `Program Files`).

`detect()` also probes `HKCR\\SCTI11.FRACOF` via `winreg` (NOT
`win32com.Dispatch`, which would actually instantiate the COM object) and
returns whether the FRACOF COM ProgID is registered. This is the field
that lets the UI distinguish "Data.xml present but COM not registered"
from "MACS+ totally absent".

The result is cached at module level. We only re-run when the cached
`data_xml_path` no longer resolves on disk — covers the "user clicks
Locate, restart picks up the new path" flow without re-scanning the
registry on every /healthz hit.

Stdlib `winreg` + already-installed `pywin32` only. No `Win32_Product`
WMI — that triggers MSI self-repair across every machine in the org.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import unquote, urlparse

try:
    import winreg  # type: ignore[attr-defined]
except ImportError:  # non-Windows dev environments
    winreg = None  # type: ignore[assignment]


# Match `MACS+_304`, `MACS+`, etc. Group 1 is the numeric suffix or "".
_MACS_NAME_RE = re.compile(r"^MACS\+(?:_(\d+))?$", re.IGNORECASE)
# Looser match (used over arbitrary text like DisplayName).
_MACS_DISPLAYNAME_RE = re.compile(r"^MACS\+", re.IGNORECASE)

_FRACOF_PROG_IDS = ("SCTI11.FRACOF", "SCTI9.FRACOF")
_UNINSTALL_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_UNINSTALL_WOW = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\MACS+.exe"


@dataclass
class DetectResult:
    """Outcome of one detection-chain run.

    `data_xml_path` is the resolved absolute path to `Data.xml`, or None
    if no detection step hit. `com_registered` reflects the FRACOF COM
    registry probe — orthogonal to data_xml_path so the UI can show a
    clear "Data.xml found but COM missing" banner.
    """
    data_xml_path: Optional[Path] = None
    install_path: Optional[Path] = None
    version: Optional[str] = None
    com_registered: bool = False
    attempted_paths: list[str] = field(default_factory=list)


# ─── Module-level cache ────────────────────────────────────────────────────────

_cache: Optional[DetectResult] = None


def reset_cache() -> None:
    """Clear the cached detection result. Called from tests and from the
    settings endpoint after the user picks a new install location."""
    global _cache
    _cache = None


def detect() -> DetectResult:
    """Run the detection chain (cached). Re-runs only when the cached path
    no longer resolves on disk."""
    global _cache
    if _cache is not None and _cache.data_xml_path is not None:
        if _cache.data_xml_path.is_file():
            return _cache
        # Cached path went away — re-detect.
        _cache = None
    _cache = _detect_uncached()
    return _cache


def _detect_uncached() -> DetectResult:
    result = DetectResult()

    # The COM probe is independent of where Data.xml is — run it once up
    # front and reuse the answer.
    result.com_registered = _probe_com_registered()

    for step in (
        _step_env_var,
        _step_fracof_clsid,
        _step_uninstall_registry,
        _step_start_menu,
        _step_app_paths,
        _step_filesystem_glob,
    ):
        hit = step(result)
        if hit is not None:
            result.data_xml_path = hit
            result.install_path = _install_root_for(hit)
            result.version = _parse_version(hit)
            break
    return result


# ─── Step 1: env var ──────────────────────────────────────────────────────────


def _step_env_var(result: DetectResult) -> Optional[Path]:
    env = os.environ.get("MACS_DATA_PATH")
    if not env:
        return None
    p = Path(env)
    result.attempted_paths.append(f"MACS_DATA_PATH env: {p}")
    if p.is_file():
        return p
    return None


# ─── Step 2: FRACOF CLSID walk ─────────────────────────────────────────────────


def _step_fracof_clsid(result: DetectResult) -> Optional[Path]:
    if winreg is None:
        return None
    for prog_id in _FRACOF_PROG_IDS:
        clsid_key = f"{prog_id}\\CLSID"
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, clsid_key) as key:
                clsid, _ = winreg.QueryValueEx(key, "")
        except FileNotFoundError:
            result.attempted_paths.append(f"HKCR\\{clsid_key}: not present")
            continue
        except OSError as e:
            result.attempted_paths.append(f"HKCR\\{clsid_key}: {e}")
            continue

        inproc_key = f"CLSID\\{clsid}\\InprocServer32"
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, inproc_key) as key:
                dll_path, _ = winreg.QueryValueEx(key, "")
                # .NET COM gotcha: when the registered server is `mscoree.dll`
                # (the CLR shim), the real assembly path is in `CodeBase` as
                # a `file:///` URL.
                if Path(dll_path).name.lower() == "mscoree.dll":
                    try:
                        code_base, _ = winreg.QueryValueEx(key, "CodeBase")
                        dll_path = _url_to_path(code_base)
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            result.attempted_paths.append(
                f"HKCR\\{inproc_key}: not present"
            )
            continue
        except OSError as e:
            result.attempted_paths.append(f"HKCR\\{inproc_key}: {e}")
            continue

        result.attempted_paths.append(
            f"HKCR\\{prog_id} CLSID -> InprocServer32 -> {dll_path}"
        )
        hit = _walk_up_for_data_xml(Path(dll_path))
        if hit is not None:
            return hit
    return None


def _url_to_path(url: str) -> str:
    """Convert a file:/// URL (Windows-style) back to a normal path string."""
    parsed = urlparse(url)
    p = unquote(parsed.path)
    # `file:///C:/foo` -> path is `/C:/foo`; strip the leading slash on Windows.
    if re.match(r"^/[A-Za-z]:/", p):
        p = p[1:]
    return p.replace("/", "\\")


# ─── Step 3: Uninstall registry ────────────────────────────────────────────────


def _step_uninstall_registry(result: DetectResult) -> Optional[Path]:
    if winreg is None:
        return None
    # All four hives. HKCU\WOW6432Node\...\Uninstall may not exist — wrap each.
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_PATH, "HKLM"),
        (winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_WOW, "HKLM\\WOW6432Node"),
        (winreg.HKEY_CURRENT_USER, _UNINSTALL_PATH, "HKCU"),
        (winreg.HKEY_CURRENT_USER, _UNINSTALL_WOW, "HKCU\\WOW6432Node"),
    ]

    candidates: list[tuple[int, str, dict, str]] = []  # (version_num, name, values, hive_label)

    for hive, subkey, label in hives:
        try:
            root = winreg.OpenKey(hive, subkey)
        except FileNotFoundError:
            result.attempted_paths.append(f"{label}\\Uninstall: not present")
            continue
        except OSError as e:
            result.attempted_paths.append(f"{label}\\Uninstall: {e}")
            continue
        try:
            with root:
                i = 0
                while True:
                    try:
                        child_name = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    values = _read_all_values(hive, f"{subkey}\\{child_name}")
                    display_name = str(values.get("DisplayName", "")).strip()
                    if not _MACS_DISPLAYNAME_RE.match(display_name):
                        continue
                    version_num = _version_from_name(display_name)
                    candidates.append(
                        (version_num, display_name, values, label)
                    )
        finally:
            pass

    # Sort highest version first; missing suffix treated as 0.
    candidates.sort(key=lambda t: t[0], reverse=True)
    for version_num, display_name, values, label in candidates:
        path_str = _resolve_install_field(values)
        result.attempted_paths.append(
            f"{label}\\Uninstall\\{display_name}: {path_str or '<unresolvable>'}"
        )
        if not path_str:
            continue
        candidate_root = Path(path_str)
        data_xml = candidate_root / "EN" / "Data" / "Data.xml"
        if data_xml.is_file():
            return data_xml
        # If the install location pointed at a sub-folder, walk up too.
        hit = _walk_up_for_data_xml(candidate_root)
        if hit is not None:
            return hit
    return None


def _read_all_values(hive: int, subkey: str) -> dict:
    """Read every named value under `subkey` into a dict. Tolerant of
    FileNotFoundError on the open or on individual value queries."""
    if winreg is None:
        return {}
    try:
        with winreg.OpenKey(hive, subkey) as key:
            out: dict = {}
            for name in ("DisplayName", "InstallLocation", "DisplayIcon",
                         "UninstallString", "DisplayVersion"):
                try:
                    v, _ = winreg.QueryValueEx(key, name)
                    out[name] = v
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            return out
    except FileNotFoundError:
        return {}
    except OSError:
        return {}


def _resolve_install_field(values: dict) -> Optional[str]:
    """Priority: InstallLocation -> DisplayIcon (strip `,N` and parent) ->
    UninstallString parent (strip quotes + args). Empty strings count as
    missing — the v1 NSIS installer leaves InstallLocation blank for some
    versions, so DisplayIcon and UninstallString are the load-bearing
    fallbacks."""
    loc = str(values.get("InstallLocation", "")).strip().strip('"')
    if loc:
        return loc
    icon = str(values.get("DisplayIcon", "")).strip().strip('"')
    if icon:
        # `C:\foo\bar.exe,0` — drop the resource index.
        m = re.match(r"^(.+?),(-?\d+)$", icon)
        if m:
            icon = m.group(1)
        return str(Path(icon).parent)
    uninst = str(values.get("UninstallString", "")).strip()
    if uninst:
        # `"C:\foo\uninst.exe" /S` -> extract first quoted arg or first token.
        m = re.match(r'^"([^"]+)"', uninst)
        if m:
            exe = m.group(1)
        else:
            exe = uninst.split(None, 1)[0]
        return str(Path(exe).parent)
    return None


def _version_from_name(name: str) -> int:
    """Extract numeric suffix from `MACS+_304` etc. Missing suffix -> 0."""
    m = re.match(r"^MACS\+(?:_(\d+))?", name, re.IGNORECASE)
    if not m or not m.group(1):
        return 0
    return int(m.group(1))


# ─── Step 4: Start Menu shortcuts ──────────────────────────────────────────────


def _step_start_menu(result: DetectResult) -> Optional[Path]:
    roots = []
    appdata = os.environ.get("APPDATA")
    program_data = os.environ.get("ProgramData")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if program_data:
        roots.append(Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs")

    for root in roots:
        if not root.is_dir():
            result.attempted_paths.append(f"Start Menu {root}: missing")
            continue
        for lnk in root.glob("MACS+*/*.lnk"):
            target = _resolve_shortcut(str(lnk))
            result.attempted_paths.append(f"Start Menu {lnk}: target={target}")
            if not target:
                continue
            hit = _walk_up_for_data_xml(Path(target))
            if hit is not None:
                return hit
    if not roots:
        result.attempted_paths.append("Start Menu: no APPDATA/ProgramData")
    return None


def _resolve_shortcut(lnk_path: str) -> Optional[str]:
    """Resolve a `.lnk` to its `TargetPath`. Returns None on failure (no
    pywin32, COM error, lnk corrupt, etc.)."""
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return None
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk_path)
        target = shortcut.TargetPath
        return str(target) if target else None
    except Exception:
        return None


# ─── Step 5: App Paths ────────────────────────────────────────────────────────


def _step_app_paths(result: DetectResult) -> Optional[Path]:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _APP_PATHS) as key:
            exe_path, _ = winreg.QueryValueEx(key, "")
    except FileNotFoundError:
        result.attempted_paths.append(f"HKLM\\{_APP_PATHS}: not present")
        return None
    except OSError as e:
        result.attempted_paths.append(f"HKLM\\{_APP_PATHS}: {e}")
        return None
    result.attempted_paths.append(f"HKLM\\{_APP_PATHS} -> {exe_path}")
    return _walk_up_for_data_xml(Path(exe_path))


# ─── Step 6: Filesystem glob ──────────────────────────────────────────────────


def _filesystem_glob_roots() -> list[Path]:
    """Override-points (also patched by tests). The order matters — newer
    per-user installs at %LOCALAPPDATA% can shadow older system installs,
    but in practice the version sort below handles that anyway."""
    roots = [
        Path(r"C:\Program Files (x86)"),
        Path(r"C:\Program Files"),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "Programs")
    return roots


def _step_filesystem_glob(result: DetectResult) -> Optional[Path]:
    candidates: list[tuple[int, Path]] = []
    roots = _filesystem_glob_roots()
    if not roots:
        result.attempted_paths.append("filesystem: no roots configured")
        return None
    for root in roots:
        if not root.is_dir():
            result.attempted_paths.append(f"filesystem {root}: missing")
            continue
        for match in root.glob("MACS+*"):
            if not match.is_dir():
                continue
            data_xml = match / "EN" / "Data" / "Data.xml"
            result.attempted_paths.append(
                f"filesystem {match}: data_xml={'present' if data_xml.is_file() else 'absent'}"
            )
            if data_xml.is_file():
                candidates.append((_version_from_name(match.name), data_xml))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _walk_up_for_data_xml(start: Path) -> Optional[Path]:
    """Walk `start` and each of its parents until `EN/Data/Data.xml` exists."""
    if start.is_file():
        ancestors = [start.parent]
    else:
        ancestors = [start]
    ancestors.extend(start.parents)
    for anc in ancestors:
        data_xml = anc / "EN" / "Data" / "Data.xml"
        if data_xml.is_file():
            return data_xml
    return None


def _install_root_for(data_xml: Path) -> Optional[Path]:
    """Given `.../MACS+_NNN/EN/Data/Data.xml`, return `.../MACS+_NNN`."""
    try:
        return data_xml.parent.parent.parent
    except Exception:
        return None


def _parse_version(data_xml: Path) -> Optional[str]:
    """Pull the numeric suffix off the `MACS+_NNN` folder segment."""
    for part in data_xml.parts:
        m = _MACS_NAME_RE.match(part)
        if m:
            return m.group(1)  # may be None for bare `MACS+` folder
    return None


def _probe_com_registered() -> bool:
    """Just check if `HKCR\\SCTI11.FRACOF` or `HKCR\\SCTI9.FRACOF` is registered.
    Does NOT instantiate the COM object — that would be slow, leak processes,
    and trigger side effects. The ProgID and its `CLSID` subkey are both
    accepted because the test fakes some configurations with only the CLSID
    leaf in place; production installs register both.
    """
    if winreg is None:
        return False
    for prog_id in _FRACOF_PROG_IDS:
        for subkey in (prog_id, f"{prog_id}\\CLSID"):
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, subkey):
                    return True
            except FileNotFoundError:
                continue
            except OSError:
                continue
    return False


def validate_install_folder(folder: Path) -> tuple[bool, Optional[Path], Optional[str]]:
    """User picked a folder via the Tauri folder picker. Verify it's a
    MACS+ install:

      1. `<folder>/EN/Data/Data.xml` exists.
      2. The XML parses.

    Returns `(ok, validated_data_xml_path, error_msg)`.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return False, None, f"Not a folder: {folder}"
    data_xml = folder / "EN" / "Data" / "Data.xml"
    if not data_xml.is_file():
        return False, None, (
            f"No EN\\Data\\Data.xml under {folder} — pick the MACS+ "
            "install folder (e.g. MACS+_304)."
        )
    try:
        ET.parse(data_xml)
    except ET.ParseError as e:
        return False, None, f"Data.xml at {data_xml} doesn't parse: {e}"
    return True, data_xml, None
