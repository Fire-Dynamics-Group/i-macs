# Issue #23 — manual Windows Sandbox E2E checklist

These steps verify the auto-detect + manual-locate flow against a real
packaged i-macs `.exe`. Run them in **Windows Sandbox** (built into Win
11 Pro: Start → "Windows Sandbox") for a clean disposable VM with no
MACS+ residue from previous runs.

Per repo memory, packaged-artefact testing is the required completion
bar for code paths that hit registry / Start Menu / OS dialogs — mock
unit tests can't cover the PyInstaller-frozen sidecar's actual `winreg`
behaviour on a real Windows install.

---

## Prep

1. Build a release `.exe` on your dev box:
   ```powershell
   npm run tauri build
   ```
   The signed NSIS installer lands under
   `src-tauri/target/release/bundle/nsis/MACS+ Automation_*.exe`.
2. Have a copy of `MACS+_304_Setup.exe` (or whichever version is current)
   handy — copy into the sandbox before installing.

## Scenario A — no MACS+ installed

Goal: confirm the native "MACS+ not detected" dialog fires, the
"Locate MACS+" button is wired up, and after locating a fixture
install the picker populates on restart.

1. Open Windows Sandbox. Copy `MACS+ Automation_*.exe` and the
   `MACS+_304_Setup.exe` into the sandbox via clipboard paste.
2. Install i-macs (NSIS installer, double-click).
3. Launch i-macs. **Expect**: native dialog "MACS+ not detected"
   with buttons "Locate MACS+" and "Open download page".
4. Click "Open download page". **Expect**: macs-steel.org opens in
   Edge. Close Edge.
5. Re-launch i-macs (dialog should fire again — no persistence).
6. Install MACS+ via `MACS+_304_Setup.exe`, but pick a non-standard
   install path like `C:\Users\WDAGUtilityAccount\MyMACS\`.
7. Close & re-launch i-macs. **Expect**: the dialog still fires
   (Setup might not have registered SCTI11.FRACOF in the sandbox —
   that's fine; this exercises the locate path).
8. Click "Locate MACS+". **Expect**: native folder picker.
9. Pick `C:\Users\WDAGUtilityAccount\MyMACS\MACS+_304` (the install
   root containing `EN\Data\Data.xml`).
10. **Expect**: "MACS+ install location saved" info dialog. Close
    i-macs.
11. Re-launch i-macs. **Expect**: NO "MACS+ not detected" dialog.
    Navigate to the run-config page. **Expect**: Deck / Mesh /
    Section pickers populated with real values from Data.xml.

## Scenario B — per-user install at %LOCALAPPDATA% (Diana's case)

Goal: confirm the Uninstall registry chain finds a per-user MACS+
install without setting MACS_DATA_PATH.

1. Fresh Windows Sandbox.
2. Install MACS+ with `MACS+_304_Setup.exe`, choosing "install for
   current user only" → ends up at
   `%LOCALAPPDATA%\Programs\MACS+_304\` and adds an HKCU Uninstall
   entry.
3. Install i-macs and launch.
4. **Expect**: NO "MACS+ not detected" dialog. Config page pickers
   are populated immediately.
5. Open `%LOCALAPPDATA%\i-macs\logs\sidecar.log`. Search for
   "HKCU\Uninstall" — should appear under the `attempted_paths`
   the sidecar logged.

## Scenario C — standard %ProgramFiles(x86)% install (regression)

1. Fresh Sandbox, install MACS+ to the default
   `C:\Program Files (x86)\MACS+_304\`.
2. Install i-macs and launch.
3. **Expect**: NO dialog, pickers populated, calculations work.
   This is the rc.5-and-earlier baseline behaviour.

## Scenario D — Data.xml present but FRACOF COM not registered

Harder to reproduce in a clean sandbox — easiest is to:
1. Copy a `MACS+_304` folder into the sandbox (no installer).
2. Install i-macs and launch.
3. **Expect**: Config page shows the "FRACOF COM not registered"
   banner (red, distinct from the "not detected" amber banner) AND
   `/healthz` `com=false`, `data_xml=true`. Calculations will fail —
   that's the diagnostic we want surfaced clearly.

## Diagnostic: /healthz attempted_paths

After any failed scenario, hit `http://127.0.0.1:<port>/healthz` (port
is logged in `sidecar.log` as "[tauri] picked sidecar port"). The
response's `attempted_paths` field lists every detection step tried
with its outcome — paste into a bug report for support.

---

## Acceptance criteria mapping

| AC                                                                | Scenario  |
|-------------------------------------------------------------------|-----------|
| Per-user install at %LOCALAPPDATA%\Programs\MACS+_304\ detected   | B         |
| Standard C:\Program Files (x86)\MACS+_304\ still works            | C         |
| No-MACS+ machine gets dialog with working "Locate MACS+"          | A         |
| After locating + restarting, pickers populate                     | A (step 11)|
| Data.xml present but COM missing surfaces a banner, not silent    | D         |
| /healthz returns attempted_paths for support diagnosis            | All       |
| No Win32_Product WMI calls (grep the codebase)                    | n/a (static)|
| /healthz back-compat: macs_installed + macs_version keys remain   | All       |
