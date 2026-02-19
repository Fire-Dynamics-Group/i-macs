# MACS+ Automation — Plan

## V1: Desktop App (Local)

A friendly GUI app that runs on the Windows machine with MACS+ installed.
Engineers double-click an exe, browser opens, they configure and run sims.

### User Experience
1. Engineer double-clicks `MACS+ Automation.exe`
2. Small console/splash shows "Starting server..."
3. Default browser opens to `http://localhost:8000`
4. They use the app like any website
5. Close the console window when done

### Tech
- **FastAPI** backend (local, serves UI + API)
- **Jinja2 templates + HTMX + Plotly.js** for frontend (no npm/node needed)
- **SQLite** database (already working)
- **PyInstaller** to bundle into a single `.exe` (no Python install needed)
- Opens in the browser at `http://localhost:8000`

### Pages
- **Config Builder** — dropdowns for sections/decks/meshes, numeric inputs for spans/slab/fck/etc, toggle single run vs sweep (ranges)
- **Run Dashboard** — live progress bar for active sweeps, queue of pending runs, error log
- **Results Browser** — filterable/sortable table of all completed runs, pass/fail highlighting (UF > 1.0 = fail)
- **Result Detail** — summary card + time-series plots for a single run
- **Report Export** — formatted output for engineer reports (TBD — need to see existing report format)

### Key Plots
- Utilization factor vs time
- Temperature profiles (fire, lower flange, mesh, slab top/bottom)
- Deflection vs time
- Slab/beam/total capacity vs time
- Sweep heatmaps (e.g. UF max across span1 vs span2 grid)

### Build Order
1. FastAPI app with API endpoints (sections/decks/meshes lookups, run submission, results query)
2. Background sweep runner with progress tracking
3. Jinja2 frontend pages (config, dashboard, results) with HTMX for interactivity
4. Plots (Plotly.js)
5. Export/report generation
6. PyInstaller exe packaging

---

## V2: Web App (Remote Access)

Upgrade V1 to be accessible online. Frontend moves to Next.js on Vercel,
backend stays on the Windows machine exposed via a tunnel.

### Architecture

```
┌─────────────────────┐         ┌──────────────────────────────┐
│  Vercel              │         │  Windows Remote Desktop      │
│                      │         │                              │
│  Next.js frontend    │  REST   │  FastAPI backend (from V1)   │
│  ├── Config builder  │◄───────►│  ├── /api/runs (CRUD)        │
│  ├── Run dashboard   │         │  ├── /api/sweep (batch jobs)  │
│  ├── Results + plots │         │  ├── /api/sections (lookups)  │
│  └── Report export   │         │  ├── MACS+ COM engine        │
│                      │         │  └── SQLite DB                │
│  (always up)         │         │                              │
└─────────────────────┘         │  Cloudflare Tunnel / Tailscale│
                                │  └── stable URL               │
                                └──────────────────────────────┘
```

### Tunnel Options (Stable URL for Backend)

| Option | URL | Cost |
|---|---|---|
| Cloudflare Tunnel | `macs-api.yourdomain.com` | Free (need domain) |
| Tailscale Funnel | `machine.tail1234.ts.net` | Free |
| ngrok (paid) | `yourname.ngrok.io` | $8/mo |

### V2 Additions
- Next.js frontend on Vercel (replaces V1 simple UI)
- Auth (protect API when exposed externally)
- Pre-seed DB with 10-100k common combinations overnight
- Report templates matching existing engineer output format

---

## Benchmark Results (1,000 runs)

| Metric | Value |
|---|---|
| Avg per run | 1.25 sec |
| Min / Max | 188 ms / 3,029 ms |
| Total (1k runs) | 20.8 min |
| DB size per run | ~2 KB |
| Errors | 0 / 1000 |

### Projected Timescales (single-threaded)

| Runs | Time | DB Size |
|---|---|---|
| 10,000 | ~3.5 hrs | 20 MB |
| 100,000 | ~1.4 days | 200 MB |
| 1,000,000 | ~14 days | 2 GB |
