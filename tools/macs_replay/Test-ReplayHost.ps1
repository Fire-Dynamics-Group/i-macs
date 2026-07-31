<#
.SYNOPSIS
Check (and optionally fix) a machine before using it to generate MACS+ PDF evidence.

.DESCRIPTION
Every check here corresponds to a way a batch has silently produced wrong or
missing output rather than failing visibly. Run this on any new evidence box.

The display-scaling check is the one that matters most: at anything other than
100%, MACS computes correctly, renders correctly on screen, and prints the
chart curves at roughly 0.59 horizontal scale against a correct axis. Every
number in the PDF is right while the charts are wrong.

.EXAMPLE
.\Test-ReplayHost.ps1
.\Test-ReplayHost.ps1 -Fix        # register COM DLLs and create the printer (run elevated)
#>
[CmdletBinding()]
param(
    [string]$MacsInstall = "C:\Program Files (x86)\MACS+_304",
    [string]$PrinterName = "MACS-PDF",
    [string]$SpoolPath = "$env:LOCALAPPDATA\i-macs\macs_replay_spool.pdf",
    [switch]$Fix
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Dpi { [DllImport("user32.dll")] public static extern uint GetDpiForSystem(); }
"@

$problems = @()
$fixes = @()
function Ok   ($m) { Write-Host "  [ ok ] $m" -ForegroundColor Green }
function Bad  ($m, $fix) { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:problems += $m; if ($fix) { $script:fixes += $fix } }
function Warn ($m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }

Write-Host "`nMACS+ replay host check`n"

# --- interactive session -----------------------------------------------------
# The Windows print dialog is an explorer.exe-hosted window that only exists in
# a real logged-on session. A service or plain SSH session cannot drive it.
if ([Environment]::UserInteractive) { Ok "interactive session" }
else { Bad "not an interactive session - the print dialog will never appear" $null }

# --- MACS+ install -----------------------------------------------------------
if (Test-Path (Join-Path $MacsInstall "MACS+.exe")) {
    Ok "MACS+ found at $MacsInstall"
} else {
    Bad "no MACS+.exe under $MacsInstall (use -MacsInstall to point elsewhere)" $null
}

# --- COM registration --------------------------------------------------------
# The installer's RegisterDLL.exe only runs RegAsm on FRACOF. Without
# ECSuite.EnvCOM the application exits 0 with no window and no error.
$comChecks = @(
    @{ Name = "ECSuite.EnvCOM (AppSupport.dll)";       Clsid = "{D2930860-A0B5-4B21-97A3-F09817B49F35}"; Dll = "Objects\AppSupport.dll" },
    @{ Name = "PrintMaster.PrintWrapper (PrintMaster.dll)"; Clsid = "{97E037B8-98F0-44A6-8FB1-616EE52F07BD}"; Dll = "Objects\PrintMaster.dll" }
)
foreach ($c in $comChecks) {
    # 32-bit COM on a 64-bit OS lives under Wow6432Node
    $paths = @("HKLM:\SOFTWARE\Classes\WOW6432Node\CLSID\$($c.Clsid)",
               "HKLM:\SOFTWARE\Classes\CLSID\$($c.Clsid)",
               "HKLM:\SOFTWARE\WOW6432Node\Classes\CLSID\$($c.Clsid)")
    if ($paths | Where-Object { Test-Path $_ }) {
        Ok "$($c.Name) registered"
    } else {
        $dll = Join-Path $MacsInstall $c.Dll
        Bad "$($c.Name) is NOT registered - MACS+ will not start" "regsvr32 /s `"$dll`""
    }
}

# --- display scaling ---------------------------------------------------------
$dpi = [Dpi]::GetDpiForSystem()
$scale = [math]::Round($dpi / 96 * 100)
if ($dpi -eq 96) {
    Ok "display scaling 100% (system DPI 96)"
} else {
    Bad ("display scaling is {0}% (system DPI {1}) - printed chart curves will be squashed while every number stays correct" -f $scale, $dpi) `
        "Settings > System > Display > Scale = 100%, then sign out and back in"
}

# --- printer on a file port --------------------------------------------------
$printer = Get-Printer -Name $PrinterName -ErrorAction SilentlyContinue
if ($printer -and $printer.PortName -match '\.pdf$') {
    Ok "printer '$PrinterName' on file port $($printer.PortName)"
} elseif ($printer) {
    Bad "printer '$PrinterName' is on port '$($printer.PortName)', not a file port - output will not be silent" $null
} else {
    if ($Fix) {
        New-Item -ItemType Directory -Force (Split-Path $SpoolPath) | Out-Null
        if (-not (Get-PrinterPort -Name $SpoolPath -ErrorAction SilentlyContinue)) {
            Add-PrinterPort -Name $SpoolPath
        }
        Add-Printer -Name $PrinterName -DriverName "Microsoft Print To PDF" -PortName $SpoolPath
        Ok "created printer '$PrinterName' on $SpoolPath"
    } else {
        Bad "printer '$PrinterName' does not exist" "re-run with -Fix to create it on $SpoolPath"
    }
}

# --- disk headroom -----------------------------------------------------------
# Measured mean 443 KB/PDF, so a full 10k batch needs roughly 4.2 GB.
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($free -gt 10) { Ok "$free GB free on C: (a 10k batch needs ~4.2 GB)" }
else { Warn "$free GB free on C: - a full 10k batch needs ~4.2 GB" }

# --- optional fixes ----------------------------------------------------------
if ($Fix -and $fixes.Count) {
    Write-Host "`nApplying fixes..."
    foreach ($f in $fixes) {
        if ($f -like "regsvr32*") {
            Write-Host "  $f"
            cmd /c $f
            if ($LASTEXITCODE -eq 0) { Ok "registered" } else { Bad "regsvr32 failed - run this shell as administrator" $null }
        } else {
            Write-Host "  (manual) $f"
        }
    }
}

Write-Host ""
if ($problems.Count -eq 0) {
    Write-Host "Host looks good." -ForegroundColor Green
    Write-Host "Confirm end-to-end before trusting a batch: replay one known run and check"
    Write-Host "its temperature curve peaks at 20.0 min (verify_replay.py --self-test)."
    exit 0
}
Write-Host "$($problems.Count) problem(s) found." -ForegroundColor Red
foreach ($f in $fixes) { Write-Host "  fix: $f" }
exit 1
