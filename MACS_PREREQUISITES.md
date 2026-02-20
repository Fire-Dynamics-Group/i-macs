# MACS+ Prerequisites

This automation tool wraps the **MACS+ FRACOF** calculation engine. It requires a working MACS+ installation on the same Windows machine.

## What is MACS+?

MACS+ (Membrane Action of Composite Structures in Fire) is a structural fire engineering tool that calculates the fire resistance of composite steel-concrete floor systems using membrane action theory (based on the FRACOF method). It's developed by ArcelorMittal and partners.

The tool provides a COM-based calculation engine (`FRACOF`) that this automation project calls programmatically to run batch parameter sweeps.

## Required Software

### MACS+ Installation

- **Version:** MACS+ with the `SCTI11.FRACOF` COM ProgID (current/recent versions)
- **Download:** MACS+ is available from [the ArcelorMittal sections website](https://sections.arcelormittal.com/design-tools/macs)
- **Default install path:** `C:\Program Files (x86)\MACS+\` or `C:\Program Files (x86)\MACS+_304\` (versioned)
- **Platform:** Windows only (32-bit COM component)

### What MACS+ Provides

1. **FRACOF COM Engine** — Registered in the Windows Registry as `SCTI11.FRACOF`. This is the calculation engine that performs the structural fire analysis. It runs as a 32-bit .NET COM object accessed via DllSurrogate.

2. **Data.xml** — Reference database containing:
   - Steel section dimensions (IPE, HE, HL, HD, UB, UC, UBP, W, H families)
   - Deck profiles (trapezoidal and re-entrant types with geometry)
   - Mesh reinforcement types (areas, diameters)
   - Located at: `<MACS+ install dir>\EN\Data\Data.xml`

### Python Dependencies

- **Python 3.10+** (64-bit)
- **pywin32** — For COM interop (`win32com.client`, `pythoncom`)
- All other dependencies listed in `requirements.txt`

## How the Automation Uses MACS+

```
┌────────────────────────┐      COM Dispatch       ┌─────────────────────┐
│  macs-automation       │ ────────────────────────►│  SCTI11.FRACOF      │
│                        │                          │  (MACS+ COM Engine) │
│  1. Parse Data.xml     │      Registry lookup     │                     │
│  2. Set input params   │◄────────────────────────►│  32-bit .NET DLL    │
│  3. Call engine.run()  │                          │  via DllSurrogate   │
│  4. Read outputs       │                          └─────────────────────┘
│  5. Store in SQLite    │
└────────────────────────┘
         ▲
         │ reads
    ┌────┴──────────────────────────────┐
    │  C:\Program Files (x86)\MACS+\    │
    │  └── EN\Data\Data.xml             │
    └───────────────────────────────────┘
```

### Key Files in This Project

| File | Role |
|------|------|
| `macs_automation/engine.py` | COM wrapper — dispatches `SCTI11.FRACOF`, sets inputs, runs analysis, reads outputs |
| `macs_automation/data_loader.py` | Parses `Data.xml` for section/deck/mesh reference data |
| `macs_automation/sweep.py` | Generates parameter combinations for batch runs |
| `macs_automation/app.py` | FastAPI web UI for configuring and running sweeps |
| `macs_automation/main.py` | CLI entry point for batch runs |

## Installation Verification

To verify MACS+ is correctly installed and accessible:

```bash
# Check Data.xml exists (tries MACS+*, then MACS+_304, MACS+)
python -c "from macs_automation.data_loader import _find_macs_data_xml; p = _find_macs_data_xml(); print(f'Data.xml: {p} ({\"FOUND\" if p.exists() else \"NOT FOUND\"})')"

# Check COM engine is registered
# Requires 32-bit Python (COM is 32-bit only)
python -c "import win32com.client; obj = win32com.client.Dispatch('SCTI11.FRACOF'); print('COM engine: OK')"
```

## Non-Default Install Location

If MACS+ is installed to a non-default directory, the **Data.xml path** must be overridden. The COM engine works regardless of install location (it's registry-based).

### CLI

```bash
python -m macs_automation.main --data-path "D:\Custom\MACS+\EN\Data\Data.xml" --config sweep.yaml
```

### Environment Variable

Set `MACS_DATA_PATH` to the full path of your `Data.xml`:

```bash
set MACS_DATA_PATH=D:\Custom\MACS+\EN\Data\Data.xml
```

This is picked up automatically by all code paths (CLI, web app, tests).

## Known Limitations

### Data.xml Path Configuration

The default `Data.xml` path is `C:\Program Files (x86)\MACS+\EN\Data\Data.xml`. This can be overridden in two ways:

- **Environment variable:** Set `MACS_DATA_PATH` (applies to all code paths — CLI, web app, tests)
- **CLI flag:** `--data-path` (applies to list commands only)

### COM ProgID Version

The engine tries `SCTI11.FRACOF` first, then `SCTI9.FRACOF`, so both current and older MACS+ versions work without configuration.

### Windows Only / 32-bit Python Required

The FRACOF COM engine is a Windows-only **32-bit** .NET component. It is registered only in the 32-bit registry (e.g. under `HKLM\SOFTWARE\WOW6432Node\Classes`). **You must use 32-bit Python** to run this automation; 64-bit Python will get "Invalid class string" or "Class not registered" because it cannot see the 32-bit COM registration. This tool cannot run on macOS or Linux.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `FileNotFoundError: ...Data.xml` | MACS+ not installed or installed to non-default path | Install MACS+ or set `--data-path` |
| `pywintypes.com_error: Class not registered` | MACS+ COM engine not registered | Reinstall MACS+ or run `regsvr32` on the DLL |
| `pywintypes.com_error: Invalid class string` | ProgID not found or 32/64-bit mismatch | Use **32-bit Python** (FRACOF is 32-bit); or reinstall MACS+ |
| `pywintypes.com_error: ...RPC...` | DllSurrogate configuration issue | Check DCOM settings in Component Services |
| `AttributeError: module 'win32com' has no attribute 'client'` | pywin32 not installed | `pip install pywin32` |
