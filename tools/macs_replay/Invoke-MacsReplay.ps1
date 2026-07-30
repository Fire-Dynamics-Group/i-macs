<#
.SYNOPSIS
Replay a batch through MACS+ itself, producing one genuine vendor PDF per run.

.DESCRIPTION
Drives one running MACS+ instance, re-seeding it per run with LoadJob() and
printing to a file-port printer. Output is indistinguishable from the reference
corpus apart from /Author and the timestamp.

Run Test-ReplayHost.ps1 first. Three host-level settings silently corrupt
output rather than failing: display scaling other than 100% squashes the chart
curves while leaving every number correct, an unregistered AppSupport.dll stops
MACS starting at all, and the wrong default printer sends the batch to paper.

Requires an interactive logged-on session — the Windows print dialog is an
explorer.exe-hosted window that does not exist in a service or SSH session.

.EXAMPLE
.\Invoke-MacsReplay.ps1 -Manifest .\export\manifest.json -OutDir .\pdfs
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Manifest,
    [Parameter(Mandatory)][string]$OutDir,
    [string]$MacsInstall = "C:\Program Files (x86)\MACS+_304",
    [string]$PrinterName = "MACS-PDF",
    [string]$SpoolPath,
    [int]$MaxRestarts = 20
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "MacsDom.ps1")
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$AE = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class ReplayWin {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
}
"@
# NOSIZE | NOZORDER | NOACTIVATE - move without ever taking focus.
$SWP_MOVE_ONLY = 0x0001 -bor 0x0004 -bor 0x0010

# ---------------------------------------------------------------- helpers ---

function Find-PrintDialog {
    $AE::RootElement.FindFirst($TS::Children,
        (New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, "Internet Explorer - Print")))
}

# Any MACS modal blocks execScript indefinitely, so a wedged batch presents as
# a hang with no message. Detect one and say so.
function Find-MacsModal {
    $AE::RootElement.FindFirst($TS::Children,
        (New-Object System.Windows.Automation.PropertyCondition($AE::ClassNameProperty, "#32770")))
}

function Get-ButtonNamed($win, [string]$n) {
    $c = New-Object System.Windows.Automation.AndCondition(
        (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Button)),
        (New-Object System.Windows.Automation.PropertyCondition($AE::NameProperty, $n)))
    return $win.FindFirst($TS::Descendants, $c)
}

function Clear-StaleDialog {
    $stale = Find-PrintDialog
    if ($null -ne $stale) {
        # A dialog left open makes every later Print() return 1 and spool
        # nothing, which reads exactly like consistent failure.
        $b = Get-ButtonNamed $stale "Cancel"
        if ($null -ne $b) { $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
        Start-Sleep -Milliseconds 700
    }
}

# The spooler holds an exclusive handle until it has finished writing. Testing
# for that is near-instant, where polling until the size stops changing costs a
# flat ~1.2 s per run.
function Wait-FileReady([string]$path, [int]$timeoutMs = 60000) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $timeoutMs) {
        try {
            $fs = [System.IO.File]::Open($path, 'Open', 'Read', 'None')
            $len = $fs.Length; $fs.Close()
            if ($len -gt 1000) { return $len }
        } catch { }
        Start-Sleep -Milliseconds 60
    }
    return 0
}

function Start-MacsInstance([string]$seedFrc) {
    Clear-StaleDialog
    Get-Process mshta -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    Start-Process (Join-Path $MacsInstall "MACS+.exe") -ArgumentList "`"$seedFrc`"" `
        -WorkingDirectory $MacsInstall | Out-Null
    Start-Sleep -Seconds 3
    for ($i = 0; $i -lt 100; $i++) {
        Start-Sleep -Milliseconds 400
        try {
            $h = Get-IEServerHwnd "MACS\+"
            $d = Get-Document $h.IE
            if ($d.readyState -eq 'complete' -and $d.location.href -match 'Main\.htm') {
                $pw = $d.parentWindow
                if ($null -ne $pw) {
                    $pw.execScript("document.documentElement.setAttribute('__p','1');", "JScript")
                    if ($d.documentElement.getAttribute('__p') -eq '1') {
                        return @{ Doc = $d; Win = $pw; Frame = $h.Frame }
                    }
                }
            }
        } catch { }
    }
    throw "could not attach to a MACS+ instance"
}

function Invoke-Js($js) { $script:app.Win.execScript($js, "JScript") }
function Get-Attr([string]$n) { $script:app.Doc.documentElement.getAttribute($n) }

function Invoke-Run($entry) {
    $target = Join-Path $OutDir "$($entry.name).pdf"
    $frc = ($entry.frc) -replace '\\', '/'

    Clear-StaleDialog
    if (Test-Path $script:spool) { [System.IO.File]::Delete($script:spool) }

    # LoadJob raises a modal on a bad file, and a modal blocks execScript, so
    # call it via setTimeout and poll for the result rather than blocking.
    Invoke-Js "document.documentElement.setAttribute('__lj','');"
    Invoke-Js "window.setTimeout(function(){var v;try{v=LoadJob('$frc')?'true':'false';}catch(e){v='err:'+e.message;}document.documentElement.setAttribute('__lj',v);},10);"
    $lj = ""
    for ($i = 0; $i -lt 300; $i++) {
        Start-Sleep -Milliseconds 100
        $lj = Get-Attr '__lj'
        if ($lj) { break }
        if ($null -ne (Find-MacsModal)) { throw "MACS raised a modal during LoadJob" }
    }
    if (-not $lj) { throw "LoadJob never returned" }
    if ($lj -ne 'true') { throw "LoadJob failed: $lj" }

    # LoadJob restores the tab saved in the .frc. Landing on Fire & Analysis
    # would let that tab's unload handler overwrite the freshly-loaded values
    # and silently revert the job to the standard ISO curve. export_batch.py
    # rewrites CurrentTab for exactly this reason; verify it took effect.
    Invoke-Js "var s='';try{s=(''+document.frames('MainFrame').location.href).split('/').pop();}catch(e){s='err';}document.documentElement.setAttribute('__t',s);"
    if ((Get-Attr '__t') -match '^TabFire\.htm') {
        throw "loaded onto the Fire & Analysis tab - the job would print as the ISO curve"
    }

    # Assert the values about to be printed are this run's, not the last one's.
    if ($null -ne $entry.expect.qf) {
        Invoke-Js "document.documentElement.setAttribute('__qf', ''+FireValues['qf']);"
        $got = [double](Get-Attr '__qf')
        if ([math]::Abs($got - [double]$entry.expect.qf) -gt 0.001) {
            throw "loaded qf $got but expected $($entry.expect.qf)"
        }
    }

    # LoadJob sets FLR_CALCDIRTY itself. Print() validates, runs the analysis
    # and only prints once CALCSUCCESS is set, so a PDF appearing at all is
    # evidence the calculation succeeded.
    Invoke-Js "window.setTimeout(function(){ Print(105); }, 30);"
    $dlg = $null
    for ($i = 0; $i -lt 600; $i++) {
        Start-Sleep -Milliseconds 100
        $dlg = Find-PrintDialog
        if ($null -ne $dlg) { break }
    }
    if ($null -eq $dlg) { throw "no print dialog" }

    # Park it off the visible desktop before driving it. Proven output-neutral;
    # keeps a 10k batch from flashing a window 10,000 times.
    [ReplayWin]::SetWindowPos([IntPtr]$dlg.Current.NativeWindowHandle, [IntPtr]::Zero,
        -32000, -32000, 0, 0, $SWP_MOVE_ONLY) | Out-Null

    # The Print button is findable within ~5 ms but is not invokable until its
    # content is built - usually ~100 ms, occasionally 2.6-3.5 s. Take the fast
    # path, then retry rather than trusting a flat wait.
    Start-Sleep -Milliseconds 120
    $invoked = $false
    for ($i = 0; $i -lt 100; $i++) {
        $btn = Get-ButtonNamed $dlg "Print"
        if ($null -ne $btn) {
            try {
                $btn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
                $invoked = $true; break
            } catch { }
        }
        Start-Sleep -Milliseconds 40
    }
    if (-not $invoked) { throw "Print button never became invokable" }

    for ($i = 0; $i -lt 400; $i++) {
        Start-Sleep -Milliseconds 100
        if (Test-Path $script:spool) {
            if ((Wait-FileReady $script:spool) -eq 0) { throw "spool never released" }
            # The spooler can hold the handle briefly after the last byte, and
            # a non-terminating Move-Item failure would log this run as "ok"
            # with nothing behind it.
            for ($m = 0; $m -lt 25; $m++) {
                try { Move-Item $script:spool $target -Force -ErrorAction Stop; break }
                catch { Start-Sleep -Milliseconds 200 }
            }
            if (-not (Test-Path $target)) { throw "could not move the spooled file" }
            if ((Get-Item $target).Length -lt 1000) { throw "spooled file is empty" }
            return (Get-Item $target).Length
        }
    }
    throw "no PDF appeared"
}

# ------------------------------------------------------------------- main ---

$mf = Get-Content $Manifest -Raw | ConvertFrom-Json
if (-not $mf.runs) { throw "manifest contains no runs" }
New-Item -ItemType Directory -Force $OutDir | Out-Null

# Pause signal, written by whoever started us. Checked between runs rather than
# acted on immediately: we hold the default printer and a live MACS+ instance,
# and only the `finally` below puts them back.
$stopFile = Join-Path $OutDir "_stop"
Remove-Item $stopFile -ErrorAction SilentlyContinue   # a stale one would stop us at once

if (-not $SpoolPath) {
    $port = (Get-Printer -Name $PrinterName -ErrorAction Stop).PortName
    if ($port -notmatch '\.pdf$') {
        throw "printer '$PrinterName' is on port '$port', which is not a file port. " +
              "Run Test-ReplayHost.ps1 -Fix to create one."
    }
    $SpoolPath = $port
}
$script:spool = $SpoolPath

$logCsv = Join-Path $OutDir "_replay_log.csv"
if (-not (Test-Path $logCsv)) { "name,run_id,seconds,bytes,status" | Set-Content $logCsv }

$prevDefault = (Get-CimInstance Win32_Printer -Filter "Default=True").Name
# A run that was killed before its restore step leaves MACS-PDF as the default.
# Saving that as "previous" would make the mistake permanent across runs.
if ($prevDefault -eq $PrinterName) { $prevDefault = "Microsoft Print to PDF" }
(Get-CimInstance Win32_Printer -Filter "Name='$PrinterName'") |
    Invoke-CimMethod -MethodName SetDefaultPrinter | Out-Null

$seed = $mf.runs[0].frc
$script:app = Start-MacsInstance $seed
Write-Host "MACS+ up; replaying $($mf.runs.Count) runs from batch $($mf.batch_id)"

$done = 0; $failed = 0; $skipped = 0; $restarts = 0; $stopped = $false
$batchSw = [Diagnostics.Stopwatch]::StartNew()

try {
    foreach ($entry in $mf.runs) {
        if (Test-Path $stopFile) {
            Write-Host "stop requested - finishing after $done run(s)"
            $stopped = $true
            break
        }

        $target = Join-Path $OutDir "$($entry.name).pdf"
        # Resume: an 11-hour job will be interrupted at some point.
        if ((Test-Path $target) -and (Get-Item $target).Length -gt 1000) { $skipped++; continue }

        $sw = [Diagnostics.Stopwatch]::StartNew()
        $bytes = 0; $status = "ok"
        try {
            $bytes = Invoke-Run $entry
        } catch {
            $first = $_.Exception.Message
            # One retry on a fresh instance: mshta dying or a wedged dialog is
            # transient, and losing the rest of a 10k batch to it is not.
            if ($restarts -lt $MaxRestarts) {
                $restarts++
                Write-Warning "$($entry.name): $first - restarting MACS+ (restart $restarts/$MaxRestarts)"
                try {
                    $script:app = Start-MacsInstance $seed
                    $bytes = Invoke-Run $entry
                } catch { $status = "FAIL: $first | after restart: $($_.Exception.Message)" }
            } else {
                $status = "FAIL: $first (restart budget exhausted)"
            }
        }

        if ($status -eq "ok") { $done++ } else { $failed++; Write-Warning "$($entry.name) $status" }
        "{0},{1},{2:N2},{3},{4}" -f $entry.name, $entry.run_id, $sw.Elapsed.TotalSeconds, $bytes, $status |
            Add-Content $logCsv
        if ((($done + $failed) % 25) -eq 0) {
            $rate = $batchSw.Elapsed.TotalSeconds / [math]::Max($done, 1)
            $left = ($mf.runs.Count - $done - $failed - $skipped) * $rate / 3600
            Write-Host ("  {0} done, {1} failed, {2:N2} s/run, ~{3:N1} h remaining" -f $done, $failed, $rate, $left)
        }
    }
} finally {
    Remove-Item $stopFile -ErrorAction SilentlyContinue
    if ($prevDefault) {
        (Get-CimInstance Win32_Printer -Filter "Name='$prevDefault'") |
            Invoke-CimMethod -MethodName SetDefaultPrinter | Out-Null
    }
    Get-Process mshta -ErrorAction SilentlyContinue | Stop-Process -Force
}

Write-Host ""
Write-Host ("REPLAY {0}: {1} ok, {2} failed, {3} already present, {4} restarts, {5:N1} min" -f
    $(if ($stopped) { "PAUSED" } else { "DONE" }),
    $done, $failed, $skipped, $restarts, $batchSw.Elapsed.TotalMinutes)
if ($stopped) {
    Write-Host "Resume with the same command - runs already on disk are skipped."
}
Write-Host "Now verify: python tools/macs_replay/verify_replay.py --manifest $Manifest --pdfs $OutDir"
if ($failed -gt 0) { exit 1 }
