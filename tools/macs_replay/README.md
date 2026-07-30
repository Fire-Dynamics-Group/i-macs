# MACS+ PDF replay

Produce one genuine MACS+ report PDF per run for a finished batch, so a 10,000-run
job has vendor evidence on file. Output is indistinguishable from the reference
corpus apart from `/Author` (the Windows username) and the timestamp.

Roughly **4–5 s per run**, so a full 10k batch is ~11–14 hours and ~4.3 GB. i-macs
itself already produces the numbers in 1.3 s/run; this adds the vendor's
presentation and an independent audit trail, not extra numerical authority.

## Why a dedicated machine

The replay needs an **interactive logged-on Windows session** — the print dialog is
an `explorer.exe`-hosted window that does not exist in a service or SSH session. It
can't be a background service, and it runs for hours. A machine that is free
anytime (TinyBot) beats fitting it around someone's working day.

It does **not** steal focus: the dialog is driven through UI Automation and parked
off-screen, and Windows' foreground lock prevents a background process taking
focus from whatever you are using. It does change the default printer for the
duration, so anything printed meanwhile lands in the spool file.

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
```

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
| `verify_replay.py` | structure, input round-trip, off-by-one, chart geometry. `--self-test <pdf>` for the scaling check alone |
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

Printing goes through MACS's own `Print(105)`, which validates, runs the analysis,
and only prints once `CALCSUCCESS` is set — so a PDF appearing is itself evidence
the calculation succeeded. Output is silent because the printer is bound to a file
port.

No MACS source is copied here; the scripts only call into a licensed local install.
