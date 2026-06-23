# Upgrade a device to the new FRACOF engine (MACS+ 3.0.4 / v2.0.0.2)

**Goal:** make `SCTI11.FRACOF` v2.0.0.2 the engine i-macs uses. The old 2013
build (`SCTI9.FRACOF` v2.0.0.1, MACS+ "Beta 2.06") reports perimeter-beam
critical temperatures up to ~3 °C high at mid utilisation and will not reproduce
reference reports generated with 3.0.4.

Everything below needs **admin** for the install + COM registration, and the
test must use **32-bit Python** (FRACOF is x86-only).

## 1. Download MACS+ 3.0.4 (official source)
- Page: <https://sections.arcelormittal.com/design_aid/design_software/EN> → "Setup MACS+ version 3.0.4"
- Or direct zip: <https://sections.arcelormittal.com/repo/Sections/4_18_Setup_MACS_plus.zip>
- ⚠️ Do **NOT** use `macsfire.eu` (serves the old Beta 2.06 / v2.0.0.1) or `cesdb.com` (a directory, not a download).

```powershell
Invoke-WebRequest "https://sections.arcelormittal.com/repo/Sections/4_18_Setup_MACS_plus.zip" -OutFile "$env:USERPROFILE\Downloads\MACS_3.0.4.zip"
Expand-Archive "$env:USERPROFILE\Downloads\MACS_3.0.4.zip" "$env:USERPROFILE\Downloads\MACS_3.0.4" -Force
```

## 2. Install it (as admin)
Run **`Install MACS+ v3_0_4.exe`** → **right-click → Run as administrator** (it
needs admin to write to Program Files and register COM). Keep the default
directory **`C:\Program Files (x86)\MACS+_304`**.

Confirm the engine binary landed:
```powershell
Get-Item "C:\Program Files (x86)\MACS+_304\Objects\FRACOF.dll" | % { $_.VersionInfo.FileVersion }   # -> 2.0.0.2
```

## 3. Test first — it may already work
```powershell
# 32-bit python (the project's venv-32, or any 32-bit Python 3.10)
.\venv-32\Scripts\python.exe -c "import win32com.client; print(win32com.client.Dispatch('SCTI11.FRACOF').GetVersion)"
```
- Prints **`2.0.0.2`** → **done**, skip to step 5.
- Error **"Invalid class string"** → not registered → do **3a**.
- Error **`0x80131700`** → registered but wrong CLR runtime → do **3b**.

### 3a. Register the new engine ("the reggie thing") — elevated terminal
```powershell
C:\Windows\Microsoft.NET\Framework\v4.0.30319\RegAsm.exe /codebase "C:\Program Files (x86)\MACS+_304\Objects\FRACOF.dll"
```
This registers `SCTI11.FRACOF` → a new CLSID for v2.0.0.2. Re-run the step-3
test. If it now throws `0x80131700`, do **3b**.

### 3b. Fix the CLR runtime (installer registers it for CLR 2.0, usually not enabled)
Look up the CLSID dynamically (don't hardcode — though on our machine it was
`{B5EB0FEB-5F91-3DE7-A21F-65187615F102}`), then point it at CLR 4 — **elevated**:
```powershell
$clsid = (Get-Item "Registry::HKEY_CLASSES_ROOT\SCTI11.FRACOF\CLSID").GetValue('')
$base  = "HKLM\SOFTWARE\Classes\WOW6432Node\CLSID\$clsid\InprocServer32"
reg add "$base" /v RuntimeVersion /t REG_SZ /d v4.0.30319 /f
reg add "$base\2.0.0.2" /v RuntimeVersion /t REG_SZ /d v4.0.30319 /f
```
CLR 4 runs this CLR-2 assembly fine — same as the old engine does.

## 4. Re-test the COM binding
```powershell
.\venv-32\Scripts\python.exe -c "import win32com.client; print(win32com.client.Dispatch('SCTI11.FRACOF').GetVersion)"   # -> 2.0.0.2
```

## 5. Confirm i-macs picks it up + it actually computes
i-macs tries `SCTI11.FRACOF` first, so no code change is needed.
```powershell
$env:PYTHONPATH = (Get-Location)
.\venv-32\Scripts\python.exe -c "from macs_automation.engine import MACSEngine; m=MACSEngine(); print(m.prog_id, m.engine_version)"
# -> SCTI11.FRACOF 2.0.0.2   (and NO 'engine predates 2.0.0.2' warning)
```
Definitive check — reproduce the reference reports exactly:
```powershell
.\venv-32\Scripts\python.exe -m pytest macs_automation/tests/test_e2e_macs_sweep_oracle.py -m e2e -q   # -> 20 passed
```

## Key facts
- Two builds share assembly name **FRACOF** but different versions → different
  auto-CLSID and ProgID: **old `SCTI9.FRACOF` v2.0.0.1**, **new `SCTI11.FRACOF` v2.0.0.2**.
- `GetVersion` is a **property**, not a method: `Dispatch(...).GetVersion`, no `()`.
- COM server is `mscoree.dll` (it's a .NET assembly). The `RuntimeVersion`
  registry value selects the CLR — must be `v4.0.30319` if .NET 3.5/CLR 2.0 isn't enabled.
- Must be driven from **32-bit Python** (x86 engine).
