<#
.SYNOPSIS
Replay a batch through MACS+ itself, producing one genuine vendor PDF per run.

.DESCRIPTION
Drives one running MACS+ instance, re-seeding it per run with LoadJob() and
printing to a file-port printer. Output is indistinguishable from the reference
corpus apart from /Author and the timestamp.

Prints by calling MACS's own PrintMaster with its prompt argument false, so no
print dialog is ever raised and the batch never takes the keyboard. -UseDialog
restores the old route. Prove the two agree with
verify_replay.py --compare-to.

Run Test-ReplayHost.ps1 first. Three host-level settings silently corrupt
output rather than failing: display scaling other than 100% squashes the chart
curves while leaving every number correct, an unregistered AppSupport.dll stops
MACS starting at all, and the wrong default printer sends the batch to paper.

-UseDialog requires an interactive logged-on session, because the Windows print
dialog is an explorer.exe-hosted window that does not exist in a service or SSH
session. The silent path raises no dialog; whether it also lifts that
requirement has not been tested.

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
    [int]$MaxRestarts = 20,
    # Restart MACS+ every N runs. An instance wedges after ~87 prints and the
    # runner only discovers that by waiting out a 60 s timeout, so recycling
    # well before then trades ~95 s of stall for a few planned seconds.
    # 0 disables it.
    [int]$RecycleEvery = 60,
    # Print through MACS's print dialog instead of PrintMaster directly. Slower
    # (~5.2 s/run against ~2 s) and it takes the keyboard once per run, but it
    # is the route the existing corpus was printed by. Kept as a fallback.
    [switch]$UseDialog
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
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint from, uint to, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
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

# Wait for the spooled PDF and claim it. Deliberately touches nothing but the
# filesystem: PrintMaster blocks the script engine until the spooler has the
# document, and any DOM call made meanwhile would block with it.
function Complete-Print([string]$target) {
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

# Wait for a print we intend to throw away, and remove it. The spooler writes a
# local file port in a second or two, so a print still absent after ten was lost
# rather than delayed - which is what the first print of a process usually does.
function Clear-Spool([int]$waits = 100) {
    for ($i = 0; $i -lt $waits; $i++) {
        Start-Sleep -Milliseconds 100
        if (Test-Path $script:spool) {
            Wait-FileReady $script:spool | Out-Null
            for ($m = 0; $m -lt 25; $m++) {
                try { [System.IO.File]::Delete($script:spool); break } catch { Start-Sleep -Milliseconds 200 }
            }
            return $true
        }
    }
    return $false
}

# Launching MACS+ activates its window, which is the one thing in the whole
# batch that steals the keyboard: the print dialog is parked off-screen and only
# takes focus if MACS already had it. Handing focus back afterwards is what
# makes an all-day batch survivable on a machine somebody is working at.
#
# Windows only lets the foreground thread hand focus around, so borrow its input
# queue for the call. Best-effort throughout - failing to restore focus must
# never take the batch down with it.
function Restore-Foreground([IntPtr]$hwnd) {
    if ($hwnd -eq [IntPtr]::Zero -or -not [ReplayWin]::IsWindow($hwnd)) { return }
    try {
        $fg = [ReplayWin]::GetForegroundWindow()
        if ($fg -eq $hwnd) { return }
        $fgThread = [ReplayWin]::GetWindowThreadProcessId($fg, [IntPtr]::Zero)
        $mine = [ReplayWin]::GetCurrentThreadId()
        $attached = $false
        if ($fgThread -ne 0 -and $fgThread -ne $mine) {
            $attached = [ReplayWin]::AttachThreadInput($mine, $fgThread, $true)
        }
        [ReplayWin]::SetForegroundWindow($hwnd) | Out-Null
        if ($attached) { [ReplayWin]::AttachThreadInput($mine, $fgThread, $false) | Out-Null }
    } catch { }
}

function Start-MacsInstance([string]$seedFrc) {
    # Whatever the user is typing into, captured before we take it away.
    $userWindow = [ReplayWin]::GetForegroundWindow()
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
                        # Launching MACS+ activates its window too, so the same
                        # courtesy applies on every restart and recycle.
                        Restore-Foreground $userWindow
                        return @{ Doc = $d; Win = $pw; Frame = $h.Frame }
                    }
                }
            }
        } catch { }
    }
    Restore-Foreground $userWindow
    throw "could not attach to a MACS+ instance"
}

# MACS recycles its document object while it navigates - the calculation bounces
# MainFrame through Calc.htm - and calls on the stale one fail with a null
# pointer rather than anything you could read. The window and document are
# cheap to re-acquire, so do that and retry once instead.
function Sync-App {
    $h = Get-IEServerHwnd "MACS\+"
    $d = Get-Document $h.IE
    $script:app = @{ Doc = $d; Win = $d.parentWindow; Frame = $h.Frame }
}
function Invoke-Js($js) {
    try { $script:app.Win.execScript($js, "JScript") | Out-Null }
    catch { Sync-App; $script:app.Win.execScript($js, "JScript") | Out-Null }
}
function Get-Attr([string]$n) {
    for ($try = 0; $try -lt 2; $try++) {
        try { return $script:app.Doc.documentElement.getAttribute($n) }
        catch {
            # An attribute that is not set comes back as a null BSTR, which
            # PowerShell reports as a null-pointer error instead of $null. MACS
            # reloads its top document during the calculation, so anything we
            # stashed on it before then is legitimately gone: read that as unset.
            if ($_.Exception -is [ArgumentNullException] -or
                $_.Exception.InnerException -is [ArgumentNullException]) { return $null }
            if ($try -eq 1) { throw }
            Sync-App
        }
    }
}

# --------------------------------------------------------- silent printing ---
#
# MACS's print page ends with
#     PrintMasterTag.Print ( template, /*preview*/ ..., /*prompt*/ true )
# and that hardcoded `true` is the print dialog. Calling the same method with
# `false` prints straight to the default printer: no dialog, no window, and
# nothing taken from whoever is using the machine.
#
# Reaching that call ourselves means doing the two things MACS's own Print()
# does on the way there - run the analysis, then build the report page - which
# is why this is three steps rather than one.

# Step 1. Analysis. MACS runs it by bouncing MainFrame through Calc.htm and
# back to the tab it names, so send it back to the tab we are already on: a
# different destination would mean the next LoadJob unloads a different form.
# Printing used to imply this ran; now it is asserted.
function Invoke-Calc {
    Invoke-Js "document.documentElement.setAttribute('__calc','');"
    Invoke-Js @"
window.setTimeout(function(){
  try { ShowTAB ( TAB_LASTACTIVE, TAB_ALLINACTIVE,
                  'Calc.htm?GroupIndex=' + CurrentGroup + '&TabIndex=' + CurrentTabs [CurrentGroup] ); }
  catch(e) { document.documentElement.setAttribute('__calc','err:'+e.message); }
}, 10);
"@
    for ($i = 0; $i -lt 600; $i++) {
        Start-Sleep -Milliseconds 50
        Invoke-Js @"
var f = 'dirty';
try { f = ((RuntimeFlags & FLR_CALCDIRTY) ? 'dirty' : 'clean') +
          (((RuntimeFlags & FLR_CALCSUCCESS) == FLR_CALCSUCCESS) ? '+ok' : '+no'); } catch(e) { f = 'err'; }
document.documentElement.setAttribute('__rf', f);
"@
        if ((Get-Attr '__rf') -eq 'clean+ok') { return }
        $err = Get-Attr '__calc'
        if ($err) { throw "calculate failed: $err" }
        # A modal blocks execScript outright, so a wedge would otherwise present
        # as a silent hang. Checking it is a UI Automation call, so do it once a
        # second rather than every pass.
        if (($i % 20) -eq 19 -and $null -ne (Find-MacsModal)) {
            throw "MACS raised a modal during the calculation"
        }
    }
    throw "the calculation did not finish (flags: $(Get-Attr '__rf'))"
}

# Step 2. Build the report. Loading the print page WITHOUT ?Print=1 makes MACS
# ask PrintMaster for a preview rather than a print, and a preview with no host
# window is silent - measured: no dialog, no new window, no focus change. What
# it leaves behind is a fully rendered report.
function Show-PrintPage {
    # Everything MACS's own StartPrint does on the way to this page except the
    # ?Print=1. The settings it pushes are what PrintMaster reads when it prints,
    # and without them the first print of a process reports success and spools
    # nothing. Take the language from the same place it does, too.
    Invoke-Js "document.documentElement.setAttribute('__pp','');"
    Invoke-Js @"
EnvCOM.SetParam ( 'Print', 'PrnFlags', PrnFlags );
EnvCOM.SetParam ( 'Settings', 'Flags', Flags );
var Lang = EnvCOM.GetParam ( 'Print', 'Lang', '0' );
if ( Lang == '0' ) { Lang = EnvCOM.GetParam ( 'Settings', 'Lang', 'EN' ); }
document.frames('PrintBody').navigate ( GetAbsPath ( Lang + '\\Support\\PrintP.htm' ));
"@
    for ($i = 0; $i -lt 600; $i++) {
        Start-Sleep -Milliseconds 50
        # An empty frame reports readyState 'complete' too, so check the URL as
        # well - otherwise the first poll always passes. And the print element
        # existing is not the same as its COM behaviour being attached, which
        # lags on the first print of a process: ask it something. Skipping this
        # loses exactly one run per MACS+ instance, silently.
        Invoke-Js @"
var s = '';
try {
  var f = document.frames('PrintBody');
  var ready = 'notag';
  try { ready = f.document.all.PrintMasterTag.GetVersion() ? 'live' : 'notag'; } catch(e2) { ready = 'attaching'; }
  s = ('' + f.document.location) + '|' + f.document.readyState + '|' + ready;
} catch(e) { s = 'err:' + e.message; }
document.documentElement.setAttribute('__pp', s);
"@
        if ((Get-Attr '__pp') -match 'PrintP\.htm.*\|complete\|live') { return }
    }
    throw "the print page never finished rendering ($(Get-Attr '__pp'))"
}

# Step 3. Print it.
function Invoke-SilentPrint {
    # MACS's print page edits itself immediately *after* it calls Print - it
    # hides the "Section size:" label and reveals the cellular-beam rows. The
    # dialog route never shows those edits, because the page is captured at the
    # moment Print is called. A print issued afterwards does show them, and the
    # visible symptom is a report missing a field label. Put the page back the
    # way its HTML declares it so both routes produce the same document.
    Invoke-Js @"
document.documentElement.setAttribute('__fix','');
try {
  var pd = document.frames('PrintBody').document;
  if (!pd.all.Unprdim) { throw new Error('Unprdim missing - MACS version changed?'); }
  pd.all.Unprdim.style.display = '';
  var hide = ['UCellDiam','UTopT','UBotT','UBotDim'];
  for (var i = 0; i < hide.length; i++) {
    if (pd.all [hide[i]]) { pd.all [hide[i]].style.display = 'none'; }
  }
  // Reading the text forces the layout those style changes invalidated. The
  // frame is hidden, so its height is always 0 - the text is the signal that
  // there is a report here at all.
  document.documentElement.setAttribute('__fix','ok:' + pd.body.innerText.length);
} catch(e) { document.documentElement.setAttribute('__fix','err:' + e.message); }
"@
    $fix = Get-Attr '__fix'
    if ($fix -notmatch '^ok:[1-9]\d*$') { throw "the report has no text to print: $fix" }

    # Ask PrintMaster which printer it is about to use. Worth asserting on its
    # own - the wrong answer means a batch going to paper - and it is also what
    # binds the device: without this read, the first print in a process reports
    # success and spools nothing, costing one run per MACS+ instance.
    Invoke-Js @"
var s = '';
try {
  var pm = document.frames('PrintBody').document.all.PrintMaster;
  s = '' + pm.GetVersion() + '|' + pm.DefaultPrinter;
} catch(e) { s = 'err:' + e.message; }
document.documentElement.setAttribute('__pr', s);
"@
    $pm = Get-Attr '__pr'
    if ($pm -notmatch '^(?<ver>[^|]+)\|(?<printer>.*)$') {
        throw "PrintMaster did not answer: $pm"
    }
    if ($Matches.printer -ne $PrinterName) {
        throw "PrintMaster would print to '$($Matches.printer)', not '$PrinterName'"
    }

    # Same template and preview flag MACS passes; only the prompt differs.
    # Deferred through setTimeout because Print blocks the script engine until
    # the spooler has the document, and a blocked engine blocks execScript too.
    Invoke-Js @"
document.documentElement.setAttribute('__sp','');
window.setTimeout(function(){
  try {
    var pf  = document.frames('PrintBody');
    var tpl = (( pf.TopWin.PrnFlags & pf.PRN_MSIETEMPLATE ) ? '' : pf.TopWin.GetAbsPath ( 'Support\\PrintPreview.htm ' ));
    document.documentElement.setAttribute('__sp', 'ret=' + pf.document.all.PrintMasterTag.Print ( tpl, false, false ));
  } catch(e) { document.documentElement.setAttribute('__sp','err:' + e.message); }
}, 10);
"@
}

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

    if (-not $UseDialog) {
        # No dialog on this path, so nothing to park and no focus to give back.
        Invoke-Calc
        Show-PrintPage

        # The first print of a MACS+ process is not trustworthy: it arrives late
        # or not at all, and when it does arrive it carries the page as it was
        # before the layout was put back - a report quietly missing a field
        # label. Spend it on purpose and bin the output. Costs ~1.5 s per
        # instance; not doing it costs one wrong PDF per instance.
        if (-not $script:warm) {
            Invoke-SilentPrint
            Clear-Spool | Out-Null
            $script:warm = $true
        }

        if (Test-Path $script:spool) { [System.IO.File]::Delete($script:spool) }
        Invoke-SilentPrint
        # Deliberately not reporting what Print returned on failure: reading it
        # back would block for as long as a wedged print does, turning a run
        # that fails in 40 s into a batch that hangs.
        return (Complete-Print $target)
    }

    # Whatever the user is typing into, captured before the print dialog exists.
    $userWindow = [ReplayWin]::GetForegroundWindow()

    # LoadJob sets FLR_CALCDIRTY itself. Print() validates, runs the analysis
    # and only prints once CALCSUCCESS is set, so a PDF appearing at all is
    # evidence the calculation succeeded.
    Invoke-Js "window.setTimeout(function(){ Print(105); }, 30);"
    # Poll hard for the dialog. Every millisecond between it appearing and the
    # park-and-restore below is a millisecond of the user's keystrokes going to
    # a window they cannot see; at 100 ms that measured ~0.25 s per run, which
    # is plenty to notice while typing. Same 60 s ceiling.
    $dlg = $null
    for ($i = 0; $i -lt 2400; $i++) {
        Start-Sleep -Milliseconds 25
        $dlg = Find-PrintDialog
        if ($null -ne $dlg) { break }
    }
    if ($null -eq $dlg) { throw "no print dialog" }

    # Park it off the visible desktop before driving it. Proven output-neutral;
    # keeps a 10k batch from flashing a window 10,000 times.
    [ReplayWin]::SetWindowPos([IntPtr]$dlg.Current.NativeWindowHandle, [IntPtr]::Zero,
        -32000, -32000, 0, 0, $SWP_MOVE_ONLY) | Out-Null

    # Parking moves the dialog but does not give the keyboard back - it took
    # focus when it was created, once per run, which is what eats a letter out
    # of whatever you were typing. Hand focus back now rather than after the
    # print: the button below can take up to 3.5 s to become invokable, and
    # that is 3.5 s of lost keystrokes every single run.
    #
    # UI Automation drives the button through InvokePattern, which does not
    # require the dialog to be active, and the retry loop below re-finds the
    # element each pass, so a wrong guess here fails loudly rather than
    # silently printing the wrong thing.
    Restore-Foreground $userWindow

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

    # Invoking can re-activate the dialog, and it activates again as it closes.
    Restore-Foreground $userWindow

    return (Complete-Print $target)
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
$script:app = Start-MacsInstance $seed; $script:warm = $false
Write-Host "MACS+ up; replaying $($mf.runs.Count) runs from batch $($mf.batch_id)"

$done = 0; $failed = 0; $skipped = 0; $restarts = 0; $stopped = $false
$sinceStart = 0; $recycles = 0
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

        # A MACS+ instance wedges after ~87 prints: the print dialog stops
        # appearing, and the runner only finds out by waiting out its 60 s
        # timeout, then restarting and retrying - about 95 s, measured every
        # 87th run on a 10k batch, four intervals of exactly 87 while the wall
        # clock between them ranged over 400-630 s. So it is prints, not time.
        # Recycling early turns that into a planned few seconds.
        if ($RecycleEvery -gt 0 -and $sinceStart -ge $RecycleEvery) {
            Write-Host "  recycling MACS+ after $sinceStart runs"
            $script:app = Start-MacsInstance $seed; $script:warm = $false
            $sinceStart = 0
            $recycles++
        }

        $sw = [Diagnostics.Stopwatch]::StartNew()
        $bytes = 0; $status = "ok"
        try {
            $bytes = Invoke-Run $entry
            $sinceStart++
        } catch {
            $first = $_.Exception.Message
            # One retry on a fresh instance: mshta dying or a wedged dialog is
            # transient, and losing the rest of a 10k batch to it is not.
            if ($restarts -lt $MaxRestarts) {
                $restarts++
                Write-Warning "$($entry.name): $first - restarting MACS+ (restart $restarts/$MaxRestarts)"
                try {
                    $script:app = Start-MacsInstance $seed; $script:warm = $false
                    $sinceStart = 0
                    $bytes = Invoke-Run $entry
                    $sinceStart++
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
Write-Host ("  {0} planned recycles" -f $recycles)
if ($stopped) {
    Write-Host "Resume with the same command - runs already on disk are skipped."
}
Write-Host "Now verify: python tools/macs_replay/verify_replay.py --manifest $Manifest --pdfs $OutDir"
if ($failed -gt 0) { exit 1 }
