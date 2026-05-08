<#
.SYNOPSIS
    Build the FastAPI sidecar with PyInstaller and stage it for Tauri.

.DESCRIPTION
    1. Activates the 32-bit project venv (venv-32\).
    2. Runs `pyinstaller --clean --noconfirm pyinstaller-server.spec`,
       producing dist/i-macs-sidecar/ (onedir layout).
    3. Replaces src-tauri/binaries/i-macs-sidecar-x86_64-pc-windows-msvc/
       with the freshly built tree, where Tauri's bundle.resources picks
       it up at `npm run tauri build` time.

    Run this BEFORE `npm run tauri build`. The x86_64 triple is preserved
    by Tauri convention even though the sidecar is 32-bit — it refers to
    the Tauri shell's arch, not the sidecar's.

.NOTES
    Windows-only. The sidecar interpreter must be 32-bit Python 3.10
    because FRACOF COM is 32-bit only — the spec file's pyi-bootstrap
    will pick up whichever python created the venv.
#>

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $repoRoot

$venvActivate = Join-Path $repoRoot 'venv-32\Scripts\Activate.ps1'
if (-not (Test-Path $venvActivate)) {
    Write-Error @"
32-bit venv not found at $venvActivate. Create it with:
    py -3.10-32 -m venv venv-32
    venv-32\Scripts\pip install -r requirements-sidecar.txt -e . pyinstaller
"@
    exit 1
}
& $venvActivate

# Hard fail if the active interpreter isn't 32-bit — FRACOF COM is 32-bit only.
$bits = & python -c "import struct; print(struct.calcsize('P')*8)"
if ($bits -ne '32') {
    Write-Error "Active Python is $bits-bit. The sidecar must be built with 32-bit Python 3.10 (FRACOF COM constraint)."
    exit 1
}

Write-Host '==> Running PyInstaller (this takes ~60-120s) ...' -ForegroundColor Cyan
pyinstaller --clean --noconfirm pyinstaller-server.spec
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

$distDir = Join-Path $repoRoot 'dist\i-macs-sidecar'
$exePath = Join-Path $distDir 'i-macs-sidecar.exe'
if (-not (Test-Path $exePath)) {
    Write-Error "Expected sidecar exe not found at $exePath"
    exit 1
}

# Tauri target-triple naming — kept consistent with externalBin / sidecar
# examples even though we ship the directory via bundle.resources.
$targetTriple = 'x86_64-pc-windows-msvc'
$stagingDir = Join-Path $repoRoot "src-tauri\binaries\i-macs-sidecar-$targetTriple"

Write-Host "==> Staging build artefacts to $stagingDir ..." -ForegroundColor Cyan
if (Test-Path $stagingDir) {
    Remove-Item -Recurse -Force $stagingDir -Confirm:$false
}
New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null
Copy-Item -Recurse -Path (Join-Path $distDir '*') -Destination $stagingDir -Force
if (-not $?) {
    Write-Error "Failed to stage sidecar build artefacts"
    exit 1
}

Write-Host "==> Sidecar staged. Next: npm run tauri build" -ForegroundColor Green
