# MACS+ Batch Automation

Automated parameter sweep runner for the [MACS+](https://www.macs-steel.org/) / FRACOF fire engineering calculation engine. Run hundreds or thousands of composite floor slab analyses via CLI or live web dashboard, with results stored in SQLite for reporting.

## Prerequisites

- **Windows** (required — the FRACOF engine is a Windows COM server)
- **Python 3.10+**
- **MACS+ installed** — the installer registers the `SCTI11.FRACOF` COM object that this tool drives. Without it, real calculations cannot run (tests still pass via mocks).

## Setup

```bash
git clone https://github.com/<your-org>/macs-automation.git
cd macs-automation
pip install -r requirements.txt
```

### Verify installation

```bash
python -m pytest macs_automation/tests/
```

All tests should pass without MACS+ installed — COM calls are mocked.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MACS_DATA_PATH` | `C:\Program Files (x86)\MACS+\EN\Data\Data.xml` | Path to the MACS+ reference data XML (sections, decks, meshes) |
| `MACS_DB_PATH` | `results.db` | SQLite database path (used by the web dashboard) |

If MACS+ is installed in the default location, no environment variables are needed.

## Usage

### CLI — Batch Sweep

Create a YAML config defining the parameter space, then run:

```bash
python -m macs_automation.main --config config_example.yaml --db results.db
```

Runs are resumable by default — re-running the same command skips already-completed cases. Use `--no-resume` to force re-run.

#### CLI Options

```
--config CONFIG    Path to sweep configuration YAML (required for batch runs)
--db DB            Path to SQLite results database (default: results.db)
--no-resume        Don't skip already-completed runs
--list-sections    List all available steel sections
--list-decks       List all available deck types
--list-meshes      List all available mesh types
--data-path PATH   Override path to Data.xml
```

### Web Dashboard

Launch the live dashboard to monitor runs and download reports:

```bash
uvicorn macs_automation.web.app:create_app --factory --reload
```

Then open http://localhost:8000. The dashboard shows:

- Real-time progress via Server-Sent Events (SSE)
- Interactive Plotly.js charts (temperatures, capacities, pass/fail scatter)
- Batch control (start/stop runs from the browser)
- Report download (ZIP with 9 CSVs + 4 PNG plots)

### Desktop GUI

A Tkinter-based desktop interface for configuring and launching single analyses or sweeps:

```bash
python -m macs_automation.app
```

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
