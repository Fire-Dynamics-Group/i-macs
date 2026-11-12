<#
.SYNOPSIS
    Boot a frozen sidecar and confirm it can answer /healthz.

.DESCRIPTION
    PyInstaller does not fail the build when a lazily imported package is
    missing. v0.1.0-rc.20 built cleanly and then raised
    ModuleNotFoundError: No module named 'msal' from
    macs_automation.entra_sign_in, which app.py imports before /healthz
    exists. This script is the check for that: the package has to be in
    the bundle, and the frozen exe has to stay up and answer /healthz.
#>

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
Set-Location $repoRoot

$bundle = "src-tauri/binaries/i-macs-sidecar-x86_64-pc-windows-msvc"
$port = 8199

foreach ($pkg in 'matplotlib', 'numpy', 'docx') {
    if (-not (Test-Path "$bundle/_internal/$pkg")) {
        Write-Error "$pkg is missing from the frozen bundle — charts and reports would 500 at runtime."
        exit 1
    }
    Write-Host "  ok  $pkg present"
}

# msal is pure Python. PyInstaller packs it into the PYZ inside the exe,
# not as _internal/msal (that directory check is what matplotlib/numpy/docx
# need, and it false-fails for msal). The archive table of contents stores
# msal.application uncompressed. Our own source never names that module.
# macs_automation.entra_sign_in imports msal at startup; the /healthz boot
# below is what proves that import succeeds.
$needle = "msal.application"
$foundMsal = $false
$searchPaths = @((Resolve-Path "$bundle/i-macs-sidecar.exe").Path)
$searchPaths += @(Get-ChildItem -Recurse -File $bundle | Where-Object { $_.Extension -in '.pyz', '.pkg' } | ForEach-Object { $_.FullName })
foreach ($path in $searchPaths) {
    $text = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($path))
    if ($text.Contains($needle)) { $foundMsal = $true; break }
}
if (-not $foundMsal) {
    Write-Error "msal was not frozen into the sidecar. macs_automation.entra_sign_in would raise ModuleNotFoundError."
    exit 1
}
Write-Host "  ok  msal frozen into the sidecar"

# Longest path in the bundle + a generous install-prefix budget must
# clear MAX_PATH (260): the app installs per-user under a path like
# C:\Users\<name>\AppData\Local\MACS+ Automation\binaries\<triple>\,
# and a dep that starts shipping deeper trees would otherwise only
# fail on a user's machine at install time.
$prefixBudget = 130
$longest = Get-ChildItem -Recurse -File $bundle |
    ForEach-Object { $_.FullName.Substring((Resolve-Path $bundle).Path.Length + 1) } |
    Sort-Object Length -Descending | Select-Object -First 1
if ($prefixBudget + $longest.Length -gt 260) {
    Write-Error "Bundle path too deep for MAX_PATH: '$longest' is $($longest.Length) chars; with a $prefixBudget-char install prefix that exceeds 260."
    exit 1
}
Write-Host "  ok  longest bundle path is $($longest.Length) chars (budget $(260 - $prefixBudget))"

$exe = Resolve-Path "$bundle/i-macs-sidecar.exe"
$stdoutLog = Join-Path $repoRoot "sidecar-stdout.log"
$stderrLog = Join-Path $repoRoot "sidecar-stderr.log"
$proc = Start-Process -FilePath $exe -ArgumentList '--port', "$port" -PassThru `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
try {
    $alive = $false
    foreach ($attempt in 1..90) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2
            if ($r.sidecar -eq 'alive') { $alive = $true; break }
        } catch { }
        if ($proc.HasExited) { break }
    }
    if (-not $alive) {
        Write-Host "process exited: $($proc.HasExited) (code $($proc.ExitCode))"
        Write-Host '== sidecar stdout =='
        Get-Content $stdoutLog -ErrorAction SilentlyContinue
        Write-Host '== sidecar stderr =='
        Get-Content $stderrLog -ErrorAction SilentlyContinue
        Write-Error "Frozen sidecar did not answer /healthz — macs_automation.entra_sign_in (msal) or another startup import failed."
        exit 1
    }
    Write-Host "  ok  frozen sidecar imported macs_automation.entra_sign_in and answered /healthz"
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
}
