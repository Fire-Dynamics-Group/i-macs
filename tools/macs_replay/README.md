# MACS+ PDF replay

Produce one genuine MACS+ report PDF per run for a finished batch, so a 10,000-run
job has vendor evidence on file. Output is indistinguishable from the reference
corpus apart from `/Author` (the Windows username) and the timestamp.

Roughly **3.5 s per run**, so a full 10k batch is ~10 hours and ~4.2 GB. i-macs
itself already produces the numbers in 1.3 s/run; this adds the vendor's
presentation and an independent audit trail, not extra numerical authority.

## It does not take the keyboard

No print dialog is ever raised. MACS's print page ends with

```js
PrintMasterTag.Print ( template, /*preview*/ ..., /*prompt*/ true )
```

and that hardcoded `true` is the dialog. The runner reaches the same call with
`false`, which prints straight to the default printer — nothing appears, and
nothing is taken from whoever is using the machine. Getting there means doing
the two things MACS's own `Print()` does on the way: run the analysis, then load
the print page *without* `?Print=1` (which asks PrintMaster for a preview, and a
preview with no host window is silent).

`-UseDialog` restores the old route, which is slower and takes focus once per
run. It is kept because the existing corpus was printed that way, so the two can
be compared — see `--compare-to` below.

The replay still wants a machine that is free for hours, and it changes the
default printer for the duration, so anything printed meanwhile lands in the
spool file. Whether it now also runs in a non-interactive session is untested;
the dialog was the only thing that provably required one.

## Usage

```powershell
# 1. Check the host. Do this once per machine, and after any Windows update.
.\tools\macs_replay\Test-ReplayHost.ps1          # -Fix to create the printer / register COM

# 2. Export the batch as per-run .frc files
python tools\macs_replay\export_batch.py --batch-id <id> --out export\
#    --sample 200   auditable sample instead of all 10k
#    --seed <f.frc> when the batch has no stored seed (checked against the run rows)

# 3. Replay. Resumable - just run it again after an interruption.
.\tools\macs_replay\Invoke-MacsReplay.ps1 -Manifest export\manifest.json -OutDir pdfs\

# 4. Verify before anyone relies on it
python tools\macs_replay\verify_replay.py --manifest export\manifest.json --pdfs pdfs\

# 5. And, when a route changes, against PDFs printed the old way
python tools\macs_replay\verify_replay.py --manifest export\manifest.json --pdfs pdfs\ ^
       --compare-to old_pdfs\
```

`--compare-to` diffs the report text run by run, ignoring only the printed
timestamp. It is how the silent route was accepted: over 120 consecutive runs,
119 came out identical to the same runs printed through the dialog, and the one
that differed was the *old* PDF being truncated.

### Pausing

Drop a file called `_stop` in the output directory. The replay finishes the run
it is holding, then exits through its own cleanup — which is what puts your
default printer back and closes MACS+. Killing the process skips both.

```powershell
New-Item pdfs\_stop -ItemType File
```

Resume by running step 3 again: runs whose PDF is already on disk are skipped.
Re-export first only if you changed the sample size, and note that a different
`--sample` covers a different set of runs.

## Read this before trusting output

Every trap below produces confident, well-formed, **wrong** output and none of them
announces itself. They are why `verify_replay.py` exists and why it should be run
every time, not just the first time.

**Display scaling must be 100%.** The chart curves are VML. At 150% MACS computes
correctly, renders correctly on screen, and emits a correct path — but *prints* the
curves at ~0.59 horizontal scale against an axis that is still right. Every number
in the PDF is correct while the graphs are wrong. `Test-ReplayHost.ps1` checks the
system DPI; `verify_replay.py` measures the drawn curves (~0.998 when correct,
~0.59 when not).

**The job must not land on the Fire & Analysis tab.** MACS stores the active tab in
the `.frc` and `LoadJob` restores it. That tab's *unload* handler writes its form
back over the freshly-loaded values, and its fire-model combo never initialises from
the loaded job — so `Method` flips from parametric to standard and the report
silently becomes the ISO curve. Symptom: every PDF the same size, `uf_max` 0.94, and
**no "Fire load:" line**. `export_batch.py` rewrites `CurrentTab`; the runner asserts
it took effect; the verifier fails any PDF missing that line.

**The seed .frc must be the batch's own.** A seed from a different job reproduces
every *non-varying* input wrongly while the varying ones still look right.
`export_batch.py` compares the seed's fixed inputs against the run rows and refuses
to export on a mismatch. This is not hypothetical — the fixture in this repo differs
from the stored 10k batch on 21 fixed inputs.

**An unmapped varying parameter is fatal, not skippable.** If a batch varies
something with no matching property in the seed, `export_batch.py` stops. Add the
correct MACS property name to `COLUMN_ALIASES` — never drop it, or the PDFs will
silently not reflect it.

**The print page edits itself after it calls Print.** `OnInitPrintPage` hides the
`Section size:` label (`Unprdim`) and reveals the cellular-beam rows *after*
handing the page to PrintMaster. The dialog route never shows those edits,
because the page is captured when Print is called; a print issued any later
does. Symptom: a report identical to the corpus except for one missing field
label. The runner puts those five elements back the way the HTML declares them
before printing. `--compare-to` is what catches it.

**The first print of a MACS+ process is not trustworthy.** It arrives late, or
not at all, or carries the page as it was before those elements were fixed. The
runner spends it deliberately and bins the output, once per instance, which
costs a second or two. Without that you get one quietly wrong PDF per instance —
and with recycling that is one per 60 runs.

**The old dialog route truncated a PDF at every wedge point.** 8 of the first 755
PDFs printed that way are 1 or 3 pages instead of 4, at runs 94, 181, 268, 355,
502, 589, 676 and 762 — ~87 apart, which is the interval at which an instance
wedges. They were logged `ok` because a file appeared and was over 1 kB. Only
`verify_replay.py` catches this, which is why it is step 4 and not optional.
Silent printing does not wedge: 120 consecutive runs in one instance, no
recycling, no failures.

**`AppSupport.dll` must be registered.** The installer's `RegisterDLL.exe` only runs
RegAsm on FRACOF, so on some installs MACS+ exits 0 with no window and no error
because it cannot create `ECSuite.EnvCOM`. `Test-ReplayHost.ps1 -Fix` registers it
(run elevated).

## Pieces

| File | Does |
| --- | --- |
| `Test-ReplayHost.ps1` | host preflight: session, install, COM registration, DPI, printer, disk |
| `export_batch.py` | batch → per-run `.frc` + `manifest.json`, with the seed and parameter checks |
| `Invoke-MacsReplay.ps1` | drives MACS+: `LoadJob` → `Print` → parked dialog → PDF. Resumable, restarts a dead instance |
| `verify_replay.py` | structure, input round-trip, off-by-one, chart geometry. `--self-test <pdf>` for the scaling check alone, `--compare-to <dir>` to diff against PDFs printed another way |
| `MacsDom.ps1` | cross-process DOM attach helpers |

`build_replay_frc` lives in `macs_automation/replay_frc.py` (tested in
`macs_automation/tests/test_replay_frc.py`) because getting it wrong is the most
expensive mistake available here.

## How it works

`MACS+.exe` is a launcher; the application is an **HTA** running under
`SysWOW64\mshta.exe`. Its DOM is reachable from another process via
`WM_HTML_GETOBJECT` + `ObjectFromLresult`, and `execScript` then runs in the app's
real global scope. The replay calls MACS's own `LoadJob(path)` to re-seed a running
instance per run — so every input comes from the file and any varying parameter is
covered without mapping parameters onto form controls.

`-UseDialog` prints through MACS's own `Print(105)`, which validates, runs the
analysis, and only prints once `CALCSUCCESS` is set — so a PDF appearing is itself
evidence the calculation succeeded. The default route does those steps separately
— MACS's `Calc.htm`, then the print page, then `PrintMaster.Print` — so it asserts
`CALCSUCCESS` outright rather than inferring it. Output lands in a file because
the printer is bound to a file port.

No MACS source is copied here; the scripts only call into a licensed local install.
