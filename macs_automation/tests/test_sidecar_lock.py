"""The release sidecar is installed from requirements-sidecar.lock, then frozen.

rc.20's bundle did not contain msal. macs_automation.entra_sign_in imports
msal at startup, so the frozen exe raised ModuleNotFoundError and never
answered /healthz. These checks keep that pin, the PyInstaller collection,
and the rc.19 publish behaviour (an -rc tag is published and marked Latest,
with latest.json) from drifting apart.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Versions resolved with pip's win32 cp310 --only-binary constraint, which is
# how the release installs this lock. cryptography 48.0.1 is the newest build
# that still publishes a win32 wheel under msal 1.39's cryptography<51 bound.
MSAL_LOCK_PINS = {
    "msal": "1.39.0",
    "requests": "2.34.2",
    "PyJWT": "2.15.1",
    "cryptography": "48.0.1",
    "cffi": "2.1.1",
    "pycparser": "3.11",
    "certifi": "2026.10.23",
    "charset-normalizer": "3.5.2",
    "urllib3": "2.8.0",
}


def _lock_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in (ROOT / "requirements-sidecar.lock").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.partition("==")
        if not sep:
            continue
        pins[name] = version.split()[0]
    return pins


def test_sidecar_lock_pins_msal_and_its_dependencies():
    pins = _lock_pins()
    missing = {name: version for name, version in MSAL_LOCK_PINS.items() if pins.get(name) != version}
    assert missing == {}


def test_sidecar_intent_file_includes_msal():
    text = (ROOT / "requirements-sidecar.txt").read_text(encoding="utf-8")
    assert "msal>=" in text


def test_pyinstaller_spec_fails_closed_when_msal_is_absent():
    text = (ROOT / "pyinstaller-server.spec").read_text(encoding="utf-8")
    assert "collect_submodules('msal')" in text
    assert "collect_data_files('certifi')" in text
    assert 'find_spec("msal")' in text
    assert "macs_automation.entra_sign_in" in text


def test_bundle_check_requires_msal_and_a_live_healthz():
    script = (ROOT / "scripts" / "verify-sidecar-bundle.ps1").read_text(encoding="utf-8")
    # msal is pure Python, so it is not a directory under _internal/. The
    # PYZ table of contents lists msal.application only when that module
    # was frozen. The name is not in our own source.
    assert "msal.application" in script
    assert "/healthz" in script
    assert "macs_automation.entra_sign_in" in script
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "verify-sidecar-bundle.ps1" in release
    assert "verify-sidecar-bundle.ps1" in ci
    assert "requirements-sidecar.lock" in ci
    assert "--only-binary=:all:" in ci


def test_rc_tags_are_published_and_marked_latest():
    """rc.19 shipped this way, so an installed copy updates from latest.json.

    An -rc tag left as a draft prerelease is invisible to /releases/latest
    and the updater does not move.
    """
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "latest.json" in text
    assert "--draft=false --latest" in text
    assert "--prerelease" not in text
    assert "draft pre-release" not in text
    assert "isReleaseCandidate" not in text
