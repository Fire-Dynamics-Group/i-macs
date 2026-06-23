# MACS+ Batch Automation

Automated parameter sweep runner for the [MACS+](https://www.macs-steel.org/) / FRACOF fire engineering calculation engine. Run hundreds or thousands of composite floor slab analyses via CLI or live web dashboard, with results stored in SQLite for reporting.

## Original project

This automation builds on the original MACS project:

- **Repository:** [https://github.com/Fire-Dynamics-Group/macs.git](https://github.com/Fire-Dynamics-Group/macs.git)

That project automated button clicks for the MACS software and handled data processing, including Latin Hypercube Sampling (LHS) and related workflows. This repo extends that work with the batch runner, dashboard, and SQLite-backed reporting.

---

## How to run the dashboard (quick start)

From the project folder in PowerShell or Command Prompt:

```bash
python run_dashboard.py
```

- Starts the server at **http://localhost:8000**
- Opens that URL in your default browser
- If you use 64-bit Python, the script sets **PYTHON32** automatically when it finds 32-bit Python (so COM calculations work)

To stop the server: press **Ctrl+C** in the terminal. If you get “port 8000 already in use”, another instance is still running — close that terminal or run `taskkill /PID <pid> /F` after finding the PID with `netstat -ano | findstr :8000`.

---

## First-time setup

1. **Clone and install (main Python — 64-bit or 32-bit):**
   ```bash
   git clone https://github.com/<your-org>/macs-automation.git
   cd macs-automation
   pip install -e .
   ```

2. **If you use 64-bit Python** — install 32-bit Python and this project into it (needed for COM):
   - Install [32-bit Python](https://www.python.org/downloads/) (e.g. “Windows installer (32-bit)”).
   - From the project folder, run (use your actual 32-bit path):
     ```bash
     path\to\python32\python.exe -m pip install -e . --no-deps
     path\to\python32\python.exe -m pip install "pywin32>=306"
     ```
   - Optional: set **PYTHON32** so the dashboard finds it (e.g. in PowerShell):
     ```powershell
     $env:PYTHON32 = "C:\Users\YOU\AppData\Local\Programs\Python\Python313-32\python.exe"
     ```
     If you don’t set it, `run_dashboard.py` will try to use `py -3-32` when available.

3. **MACS+ 3.0.4** must be installed (e.g. `C:\Program Files (x86)\MACS+_304\`) for real calculations. Without it, the dashboard still runs but runs will fail with a COM error. **Use 3.0.4, not an older build** — see [MACS+ engine version](#macs-engine-version) below.

---

## MACS+ engine version

i-macs calls the FRACOF COM engine that ships **inside** MACS+; it does not compute results itself. The engine version therefore determines the numbers exactly.

- **Required: MACS+ 3.0.4**, which registers `SCTI11.FRACOF` **v2.0.0.2** (Jan 2018). This is the build our reference reports were generated with, so i-macs reproduces them to the degree.
- **Older builds** — notably the 2013 "Beta 2.06" MACS+, which registers `SCTI9.FRACOF` **v2.0.0.1** — use an earlier perimeter-beam critical-temperature routine that reads up to **~3 °C high** at mid utilisation (e.g. edge beam 634 vs 631 °C). `uf_max` and factored load are unaffected, but critical temps won't match 3.0.4 references. `MACSEngine` logs a warning if it resolves an engine older than v2.0.0.2.

i-macs tries `SCTI11.FRACOF` (3.0.4) first and falls back to `SCTI9.FRACOF`, so installing 3.0.4 is picked up automatically — no code change.

### Download (official source)

Get it from **ArcelorMittal Sections** (no registration):

- Page: <https://sections.arcelormittal.com/design_aid/design_software/EN> → "Setup MACS+ version 3.0.4"
- Direct: <https://sections.arcelormittal.com/repo/Sections/4_18_Setup_MACS_plus.zip>

Extract and run `Install MACS+ v3_0_4.exe` **as administrator** (COM registration needs admin).

> ⚠️ Do **not** use `macsfire.eu` — it still serves the old Beta 2.06 (v2.0.0.1). `cesdb.com` only lists the software; it is not a download source.

---

## Running the dashboard (all options)

| What you want | Command |
|---------------|--------|
| **Easiest** — start server + open browser, auto-detect 32-bit Python | `python run_dashboard.py` |
| **Manual** — start server only (then open http://localhost:8000 yourself) | `python -m uvicorn macs_automation.app:app --host localhost --port 8000` |
| **With reload** (code changes restart server) | `python -m uvicorn macs_automation.app:app --host localhost --port 8000 --reload` |

If you use 64-bit Python and have set **PYTHON32**, start the server in the same terminal (or the same environment) so it sees the variable. Or use `run_dashboard.py`, which sets it for you when possible.

---

## Prerequisites

- **Windows** (required — the FRACOF engine is a Windows COM server)
- **Python 3.10+** (32-bit or 64-bit)
- **MACS+ 3.0.4 installed** (e.g. `C:\Program Files (x86)\MACS+_304\`) for real calculations; the dashboard runs without it but runs will error until MACS+ is installed. Use 3.0.4 (FRACOF v2.0.0.2) — see [MACS+ engine version](#macs-engine-version) for why and the official download.

The FRACOF COM engine is 32-bit only: use 32-bit Python, or 64-bit Python with 32-bit Python also installed and the setup above.

---

## Verify installation

```bash
python -m pytest macs_automation/tests/
```

All tests should pass without MACS+ installed (COM calls are mocked).

### End-to-end tests (real COM)

```bash
python -m pytest macs_automation/tests/test_e2e_real.py macs_automation/tests/test_engine.py -m e2e -v
```

- With 32-bit Python + MACS+, or 64-bit + 32-bit + MACS+: runs one real calculation.
- Otherwise: tests skip with a clear reason.

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `PYTHON32` | Path to 32-bit Python (e.g. `C:\...\Python313-32\python.exe`). Only needed if you use 64-bit Python; `run_dashboard.py` can auto-detect via `py -3-32`. |
| `MACS_DATA_PATH` | Override path to Data.xml (default: auto-detected under `MACS+*` / `MACS+_304`). |
| `MACS_DB_PATH` | SQLite database path (default: `results.db`). |

---

## Usage

### CLI — Batch sweep

```bash
python -m macs_automation.main --config config_example.yaml --db results.db
```

Runs are resumable by default. Use `--no-resume` to force re-run.

**Options:** `--config`, `--db`, `--no-resume`, `--list-sections`, `--list-decks`, `--list-meshes`, `--data-path`.

### Web dashboard (already described above)

Use `python run_dashboard.py` or the uvicorn commands above. The dashboard provides:

- Config page (grid sweep or LHS), run single or batch
- Real-time progress (SSE), charts, stop button
- Results and report download (ZIP)

## Sweep Configuration

Two sampling modes are supported:

### Grid sweep (`config_example.yaml`)

Every combination of the listed parameter values is run (full factorial):

```yaml
analysis_method: "iso"

sweep:
  span1: [6, 9, 12]
  span2: [6, 9, 12]
  slab_depth: [130, 150, 180]
  fck: [25, 30, 40]

fixed:
  numbeam: 2
  deck_id: "T14"
  mesh_type: "A393"

beams:
  side_a: { sec_size: "IPE_500", fy: 355, edge: true, composite: false, sh_con: 80 }
  # ... sides b, c, d
```

### Latin Hypercube Sampling (`config_example_lhs.yaml`)

Probabilistic fire analysis — sample from statistical distributions (Gumbel, lognormal) or EN 1991-1-2 occupancy presets:

```yaml
analysis_method: "parametric"
sampling: "lhs"
n_samples: 1000
seed: 42

distributions:
  qf:
    preset: "Office"   # EN 1991-1-2 Table E.4
  window_percent:
    preset: "Opening Factor"
    transform: "opening_factor"

fixed:
  span1: 9
  span2: 9
  # ...
```

## Report Output

Download a ZIP report from the web dashboard (`/report/download`) or generate programmatically. Contents:

| File | Description |
|---|---|
| `summary.csv` | One row per run: fire load, glazing, max unity factor, time of max |
| `beam_temperature.csv` | Wide-format beam temps vs time for all runs |
| `mesh_temperature.csv` | Wide-format mesh temps vs time |
| `slab_bottom_temperature.csv` | Wide-format slab bottom temps vs time |
| `beam_hot_capacity.csv` | Beam capacity at elevated temperature vs time |
| `slab_yield.csv` | Slab yield line capacity vs time |
| `slab_capacity.csv` | Slab capacity vs time |
| `total_plate_capacity.csv` | Total plate capacity vs time |
| `protected_beam_temps.csv` | Perimeter beam temperatures (sides A–D) |
| `total_capacity.png` | Capacity vs time plot with factored load line |
| `beam_temperature.png` | Beam temperature vs time (all runs + average) |
| `mesh_temperature.png` | Mesh temperature vs time (all runs + average) |
| `scatter_passfail.png` | Fire load vs glazing breakage, colored by pass/fail |

## Project Structure

```
macs_automation/
  main.py           CLI entry point
  app.py            Desktop GUI (Tkinter)
  engine.py         COM wrapper for FRACOF
  runner.py         Batch execution with callbacks
  sweep.py          Parameter combination generation
  sampling.py       LHS / statistical distribution sampling
  db.py             SQLite storage (runs + time series)
  report.py         CSV + PNG export from database
  data_loader.py    MACS+ Data.xml parser (sections, decks, meshes)
  frc_parser.py     .frc job file parser
  web/
    app.py          FastAPI application factory
    routes.py       API routes, SSE, batch control
    sse.py          Server-Sent Events broadcaster
    static/         JS (Plotly dashboard), CSS
    templates/      Jinja2 HTML templates
  tests/            195+ tests (pytest)
```

## Running Tests

```bash
python -m pytest macs_automation/tests/
```

Tests marked with `@pytest.mark.com` require MACS+ to be installed. They are skipped by default; to include them:

```bash
python -m pytest macs_automation/tests/ -m com
```
