# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the FastAPI sidecar that the Tauri shell launches.

Build (from project root, with the 32-bit venv active):
    pyinstaller --clean --noconfirm pyinstaller-server.spec

Output (Windows, onedir layout):
    dist/i-macs-sidecar/i-macs-sidecar.exe
    dist/i-macs-sidecar/_internal/   <-- data files + 32-bit Python runtime

`scripts/build-sidecar.ps1` then copies the whole dist/i-macs-sidecar/ tree
into src-tauri/binaries/i-macs-sidecar-x86_64-pc-windows-msvc/, where Tauri
picks it up via bundle.resources. The x86_64 triple is preserved by Tauri
convention even for a 32-bit sidecar — the triple refers to the Tauri shell.
"""
import importlib.util

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# entra_sign_in imports msal while the process is starting. collect_submodules
# only warns and returns [] when the package is missing, which is how the
# v0.1.0-rc.20 bundle built and then died with ModuleNotFoundError. Fail here.
if importlib.util.find_spec("msal") is None:
    raise SystemExit(
        "msal is not installed in this interpreter. The frozen sidecar "
        "imports macs_automation.entra_sign_in at startup, and that module "
        "imports msal. Install requirements-sidecar.lock before building."
    )

# Modules pulled in dynamically that the static analyser can't see.
# pythoncom / win32com / pywintypes are the COM bridge for FRACOF; uvicorn
# lifecycle hooks miss without explicit picks.
hidden_imports = (
    collect_submodules('uvicorn')
    + collect_submodules('fastapi')
    + collect_submodules('pydantic')
    + [
        'pythoncom',
        'win32com.client',
        'pywintypes',
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        # Per-calc subprocess module — engine.run_one_com() spawns it via
        # `python -m macs_automation.com_runner`. PyInstaller's static
        # analyser doesn't see the dynamic spawn, so include it explicitly.
        'macs_automation.com_runner',
    ]
    + collect_submodules('msal')
)

# Data files — none from our side (Data.xml lives in the MACS+ install,
# not bundled with us). matplotlib still ships a small mpl-data tree at
# runtime; the report_docx code path isn't exercised in v1 but the dep
# stays in requirements, so collect its data to keep imports clean.
datas = []
datas += collect_data_files('matplotlib')
# requests (via msal) reads certifi's CA bundle. The file is not a module, so
# name it here or a frozen sign-in fails TLS with a missing cacert.pem.
datas += collect_data_files('certifi')
# MACS+ PDF replay scripts, driven by macs_automation/pdf_evidence.py. They are
# data rather than code, so they need naming explicitly or the batch page's
# "MACS+ PDF evidence" action finds nothing in a packaged build.
datas += [('tools/macs_replay', 'macs_replay')]

a = Analysis(
    ['macs_automation/app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='i-macs-sidecar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # No flashing console window in production. Tauri inherits stdout/stderr
    # and --log-dir mirrors them to sidecar.log for post-mortem.
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='i-macs-sidecar',
)
