"""Report export module — generates CSVs and plots from SQLite data.

Produces the same 9 CSVs + 4 PNG plots that engineers currently get from
the PDF pipeline, but directly from the database.

The CSV headers deliberately reproduce the pre-i-macs pdfplumber pipeline's
output byte-for-byte (``Time_mins``, ``Total capacity_kN/m²_0``, glazing as a
0–1 fraction, 0-based ``sim_num``). The point of the export is that the existing
matplotlib scripts keep working on it unmodified, so this format is a contract
with those scripts, not an internal choice — see docs/data-export.md.
"""

import csv
import io
import tempfile
import threading
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

from macs_automation.db import ResultsDB

# matplotlib's pyplot keeps its figures in process-global state, and the sidecar
# serves chart requests concurrently — the batch page's <img> chart endpoints
# fire while a ZIP export is rendering. Without this every renderer in the
# process must take the lock, or two charts land on the same axes and you get a
# scatter with the mesh spaghetti drawn through it.
#
# Reentrant because generate_plots() takes it and then calls _plot_timeseries(),
# which takes it too.
MPL_LOCK = threading.RLock()


def _runs_for(db: ResultsDB, batch_id: Optional[str]) -> list[dict]:
    """Successful runs, scoped to one batch when ``batch_id`` is given."""
    if batch_id is None:
        return db.get_successful_runs()
    return db.get_batch_successful_runs(batch_id)


def _timeseries_for(db: ResultsDB, column: str, batch_id: Optional[str]) -> list[tuple]:
    if batch_id is None:
        return db.get_all_time_series_column(column)
    return db.get_batch_time_series_column(batch_id, column)


def _opening_factor(run: dict) -> Optional[float]:
    """Opening factor O = Av·√heq / At, with the glazing breakage applied to both
    the opening area and its height.

    Ported from the legacy pipeline's ``calc_op_fac`` so the exported column
    matches what the existing scripts expect. The height of the broken portion is
    taken as ``Hw·√fraction`` (i.e. the opening is assumed to scale squarely),
    and the result is clipped to EN 1991-1-2's [0.01, 0.20] range.

    Returns None when the compartment or window geometry is incomplete.
    """
    Lc, Bc, Hc = run.get("Lc"), run.get("Bc"), run.get("Hc")
    Lw, Hw = run.get("Lw"), run.get("Hw")
    window_percent = run.get("window_percent")
    if None in (Lc, Bc, Hc, Lw, Hw, window_percent):
        return None

    total_area = 2 * Lc * Bc + 2 * (Lc + Bc) * Hc
    if total_area <= 0:
        return None

    fraction = window_percent / 100.0
    av_open = Lw * Hw * fraction
    heq_open = Hw * fraction ** 0.5
    op_fac = av_open * heq_open ** 0.5 / total_area
    return min(max(op_fac, 0.01), 0.20)


def _glazing_fraction(run: dict) -> Optional[float]:
    """window_percent is stored as a percent; the legacy CSVs carry a fraction."""
    wp = run.get("window_percent")
    return None if wp is None else wp / 100.0


def generate_summary_csv(db: ResultsDB, batch_id: Optional[str] = None) -> str:
    """Generate the summary CSV with one row per successful run.

    Columns: sim_num, fireload, glazing_breakage, opening_factor,
             max_unity_factor, time_of_max, time_exceed_one, factored_hot

    The first seven are the legacy set, in order. ``factored_hot`` is appended
    because the capacity chart needs it to draw its load line, and the old
    pipeline could only get it by scraping the PDF. Downstream scripts index by
    column name, so a trailing column costs them nothing.
    """
    runs = _runs_for(db, batch_id)
    uf_times = db.get_uf_times(batch_id=batch_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "sim_num", "fireload", "glazing_breakage", "opening_factor",
        "max_unity_factor", "time_of_max", "time_exceed_one", "factored_hot",
    ])

    for i, run in enumerate(runs):
        time_of_max, time_exceed = uf_times.get(run["id"], (None, None))
        writer.writerow([
            i,
            run.get("qf"),
            _glazing_fraction(run),
            _opening_factor(run),
            run.get("uf_max"),
            time_of_max if time_of_max is not None else "",
            time_exceed if time_exceed is not None else "",
            run.get("factored_hot"),
        ])

    return buf.getvalue()


def generate_wide_timeseries_csv(db: ResultsDB, column: str,
                                 batch_id: Optional[str] = None) -> str:
    """Generate a wide-format time-series CSV.

    Pivots from long format (DB) to the wide format, keeping the MACS+ table's
    own two header rows so ``pd.read_csv(..., header=[0, 1])`` yields a real
    MultiIndex:

        Time | <Quantity>_0 | <Quantity>_1 | ... | <Quantity>_N-1
        mins | <unit>       | <unit>       | ... | <unit>

    Two rows rather than one flattened row is load-bearing. With a single header
    row, ``header=[0, 1]`` consumes the first *data* row as the second header
    level, silently dropping t=0 from every chart drawn off the file.

    Column order follows the run order used by the summary CSV, so the ``_N``
    suffix is the same run as ``sim_num`` N — a run that produced no time-series
    rows still gets its (empty) column rather than shifting every run after it.

    Used for: lofl_temp, mesh_temp, slabbot_temp, beam_hot_capacity,
              slab_yield, slab_cap, total_plate_capacity
    """
    rows = _timeseries_for(db, column, batch_id)
    if not rows:
        return ""

    quantity, unit = LEGACY_HEADERS.get(column, (column, ""))
    run_ids = [r["id"] for r in _runs_for(db, batch_id)]

    # Build pivot dict: {(run_id, time_min): value}
    pivot = {}
    times = set()
    for run_id, time_min, value in rows:
        pivot[(run_id, time_min)] = value
        times.add(time_min)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Time"] + [f"{quantity}_{i}" for i in range(len(run_ids))])
    writer.writerow(["mins"] + [unit] * len(run_ids))

    for t in sorted(times):
        writer.writerow([t] + [pivot.get((rid, t), "") for rid in run_ids])

    return buf.getvalue()


def generate_prot_beam_csv(db: ResultsDB, batch_id: Optional[str] = None) -> str:
    """Generate the protected beam temperature CSV.

    Columns: Run, Perimeter_Beam_Temp_A, _B, _C, _D, Fireload, Glazing_Breakage
    """
    runs = _runs_for(db, batch_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Run", "Perimeter_Beam_Temp_A", "Perimeter_Beam_Temp_B",
        "Perimeter_Beam_Temp_C", "Perimeter_Beam_Temp_D",
        "Fireload", "Glazing_Breakage",
    ])

    for i, run in enumerate(runs):
        writer.writerow([
            i,
            run.get("side_a_critical_temp"),
            run.get("side_b_critical_temp"),
            run.get("side_c_critical_temp"),
            run.get("side_d_critical_temp"),
            run.get("qf"),
            _glazing_fraction(run),
        ])

    return buf.getvalue()


def _factored_hot_range(runs) -> Optional[tuple[float, float]]:
    """Return (min, max) of factored_hot across runs, or None if no values."""
    values = [r.get("factored_hot") for r in runs if r.get("factored_hot") is not None]
    if not values:
        return None
    return (min(values), max(values))


def _inputs_vary(runs, *fields: str) -> bool:
    """True if any of ``fields`` has more than one distinct non-None value across runs."""
    for field in fields:
        values = {r.get(field) for r in runs if r.get(field) is not None}
        if len(values) > 1:
            return True
    return False


def _extend_flat(times: list, values: list, end_t: float) -> tuple[list, list]:
    """Forward-fill a single series: hold its last value flat out to ``end_t``.

    MACS+ draws every run's line to the end of the time axis (a fire that ends at
    45 min shows as a horizontal band to 300 min), not just up to its own last
    data point. Applying this to each spaghetti line reproduces those bands.
    """
    if times and times[-1] < end_t:
        return times + [end_t], values + [values[-1]]
    return times, values


def _forward_filled_average(by_run: dict) -> tuple[list, list]:
    """Average a per-run time series onto the common time grid, holding each run's
    last value flat past the end of its data (forward-fill).

    MACS+ plots it this way: a fire that ends early is held at its final value, so
    the mean reflects all runs at every instant — dominated by the many cooled
    runs rather than the few still-hot ones. Averaging only runs with an *exact*
    data point at each time (the prior behaviour) made the line spiky and biased
    high at late times, where only long fires still had points.

    Returns ``(sorted_times, avg_values)``.
    """
    import bisect

    series = []
    all_times: set = set()
    for data in by_run.values():
        pts = sorted((t, v) for t, v in data if v is not None)
        if not pts:
            continue
        series.append(([p[0] for p in pts], [p[1] for p in pts]))
        all_times.update(p[0] for p in pts)

    sorted_times = sorted(all_times)
    avg_values = []
    for t in sorted_times:
        total, n = 0.0, 0
        for times, values in series:
            if t < times[0]:
                continue  # run hasn't started yet
            total += values[bisect.bisect_right(times, t) - 1]  # last value <= t
            n += 1
        avg_values.append(total / n if n else 0.0)
    return sorted_times, avg_values


def _plot_timeseries(
    db: ResultsDB,
    column: str,
    title: str,
    ylabel: str,
    filename: str,
    output_dir: Path,
    hline_band: Optional[tuple[float, float]] = None,
):
    """Serialised on the shared matplotlib lock — pyplot state is global."""
    with MPL_LOCK:
        return _plot_timeseries_locked(
            db, column, title, ylabel, filename, output_dir, hline_band
        )


def _plot_timeseries_locked(
    db: ResultsDB,
    column: str,
    title: str,
    ylabel: str,
    filename: str,
    output_dir: Path,
    hline_band: Optional[tuple[float, float]] = None,
):
    """Plot time series for all runs + average; save to PNG.

    ``hline_band`` is ``(min, max)``: equal values render as a dashed line,
    unequal values render as a shaded band between them.

    Returns ``(path, fig)`` or ``None`` if no data. Caller closes ``fig``.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 6))

    rows = db.get_all_time_series_column(column)
    if not rows:
        plt.close(fig)
        return None

    by_run = defaultdict(list)
    for run_id, time_min, value in rows:
        by_run[run_id].append((time_min, value))

    end_t = max((d[-1][0] for d in by_run.values() if d), default=None)
    for rid, data in by_run.items():
        data.sort()
        pts = [(t, v) for t, v in data if v is not None]
        if not pts:
            continue
        times = [p[0] for p in pts]
        values = [p[1] for p in pts]
        if end_t is not None:
            times, values = _extend_flat(times, values, end_t)
        ax.plot(times, values, color="lightsteelblue", linewidth=0.5, alpha=0.6)

    sorted_times, avg_values = _forward_filled_average(by_run)
    if sorted_times:
        ax.plot(sorted_times, avg_values, color="coral", linewidth=2,
                label="Average")

    if hline_band is not None:
        lo, hi = hline_band
        if abs(hi - lo) < 1e-9:
            ax.axhline(y=lo, color="red", linewidth=1.5,
                       linestyle="--", label=f"Factored load = {lo:.1f}")
        else:
            ax.axhspan(lo, hi, color="red", alpha=0.2,
                       label=f"Factored load ({lo:.1f}–{hi:.1f})")

    ax.set_xlabel("Time (min)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)

    path = output_dir / filename
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return path, fig


def generate_plots(db: ResultsDB, output_dir: Path) -> list[Path]:
    """Serialised on the shared matplotlib lock — pyplot state is global."""
    with MPL_LOCK:
        return generate_plots_locked(db=db, output_dir=output_dir)


def generate_plots_locked(db: ResultsDB, output_dir: Path) -> list[Path]:
    """Generate up to 4 PNG plots and return their paths.

    1. Total capacity vs time — spaghetti + average + factored band/line
    2. Beam temperature vs time — spaghetti + average
    3. Mesh temperature vs time — spaghetti + average
    4. Scatter — fireload vs glazing_breakage; omitted when neither varies
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    runs = db.get_successful_runs()
    factored_band = _factored_hot_range(runs)

    plot_specs = [
        ("total_plate_capacity", "Total Plate Capacity vs Time",
         "Capacity (kN/m)", "total_capacity.png", factored_band),
        ("lofl_temp", "Beam Temperature vs Time",
         "Temperature (°C)", "beam_temperature.png", None),
        ("mesh_temp", "Mesh Temperature vs Time",
         "Temperature (°C)", "mesh_temperature.png", None),
    ]

    for column, title, ylabel, filename, band in plot_specs:
        result = _plot_timeseries(
            db, column, title, ylabel, filename, output_dir,
            hline_band=band,
        )
        if result:
            path, fig = result
            plt.close(fig)
            paths.append(path)

    # Scatter — only when at least one of qf / window_percent actually varies
    if runs and _inputs_vary(runs, "qf", "window_percent"):
        fig, ax = plt.subplots(figsize=(10, 6))
        pass_qf, pass_wp = [], []
        fail_qf, fail_wp = [], []

        for run in runs:
            qf = run.get("qf")
            wp = run.get("window_percent")
            uf = run.get("uf_max")
            if qf is not None and wp is not None:
                if uf is not None and uf <= 1.0:
                    pass_qf.append(qf)
                    pass_wp.append(wp)
                else:
                    fail_qf.append(qf)
                    fail_wp.append(wp)

        if pass_qf:
            ax.scatter(pass_qf, pass_wp, color="steelblue", alpha=0.7,
                       label=f"Pass ({len(pass_qf)})", s=30)
        if fail_qf:
            ax.scatter(fail_qf, fail_wp, color="coral", alpha=0.7,
                       label=f"Fail ({len(fail_qf)})", s=30)

        ax.set_xlabel("Fire Load (MJ/m²)")
        ax.set_ylabel("Glazing Breakage (%)")
        ax.set_title("Fire Load vs Glazing Breakage")
        ax.legend()
        ax.grid(True, alpha=0.3)

        path = output_dir / "scatter_passfail.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)

    return paths


# The 7 wide-format time-series CSVs, as (db column, file stem, quantity, unit).
# Quantity and unit are the two header rows of the MACS+ output table itself.
WIDE_CSV_COLUMNS = [
    ("lofl_temp", "beam_temp_data", "Beam", "°C"),
    ("mesh_temp", "mesh_temp_data", "Mesh", "°C"),
    ("slabbot_temp", "slabbot_temp_data", "Slab bottom", "°C"),
    ("beam_hot_capacity", "beam_cap_data", "Beam capacity", "kN/m²"),
    ("slab_yield", "slab_yield_data", "Slab yield", "kN/m²"),
    ("slab_cap", "slab_cap_data", "Slab capacity", "kN/m²"),
    ("total_plate_capacity", "total_cap_data", "Total capacity", "kN/m²"),
]

LEGACY_HEADERS = {col: (qty, unit) for col, _, qty, unit in WIDE_CSV_COLUMNS}


# ─── House chart style ───────────────────────────────────────────────────────
# The single source of truth for how a MACS+ chart looks. Both renderers read
# from here: the one in this module (used for the PNGs in the ZIP) and the
# bundled plot_charts.py, which has these values injected rather than copied —
# so a chart downloaded from the app and one produced by running the script
# cannot drift apart.
HOUSE_LIGHT_TEXT = (0.59, 0.56, 0.56)
HOUSE_CHART_CONFIG = {
    "font.family": "Segoe UI",
    "xtick.color": HOUSE_LIGHT_TEXT,
    "ytick.color": HOUSE_LIGHT_TEXT,
    "axes.titlecolor": HOUSE_LIGHT_TEXT,
    "axes.labelcolor": HOUSE_LIGHT_TEXT,
    "axes.edgecolor": HOUSE_LIGHT_TEXT,
    "legend.labelcolor": HOUSE_LIGHT_TEXT,
    "figure.figsize": [6, 4],
    "axes.grid": True,
    "grid.linewidth": "0.05",
    "grid.color": HOUSE_LIGHT_TEXT,
}
HOUSE_SPAGHETTI = "#4798EA33"     # mid blue at 20% alpha
HOUSE_SCATTER_BLUE = "#4798EA"
HOUSE_CORAL = "coral"
HOUSE_DPI = 300

# Roughly how much of the axes a three-entry legend occupies, as a fraction of
# width and height. Used to score the four corners for how much data they'd hide.
LEGEND_BOX = (0.42, 0.34)
# Scored in this order, so a tie falls back to the conventional upper right.
LEGEND_CORNERS = ("upper right", "lower right", "upper left", "lower left")

# Glazing breakage is a share of the opening, stored as a 0-1 fraction but
# labelled "%". Fix the axis to its full range and label the ticks as percent,
# so the chart can't imply negative breakage or more than a fully broken window.
GLAZING_TICKS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
GLAZING_TICK_LABELS = ["0", "20", "40", "60", "80", "100"]
# Share of sampled points a corner may hold and still count as clear. A few
# stray curves are fine to sit behind; a populated corner sends the legend out.
LEGEND_TOLERANCE = 0.0


def _least_occupied_corner(x: list, series: list[list],
                           extra: Optional[list[list]] = None,
                           box: tuple = LEGEND_BOX,
                           max_series: int = 300) -> Optional[str]:
    """Pick a legend corner that is genuinely clear of data, or None.

    Returns None when every corner holds data — on a dense 10,000-run mesh
    chart the curves fill all four, and dropping the legend in the "least bad"
    one still buries the rising edge. The caller puts it outside the axes
    instead, which is the only placement that cannot hide anything.

    matplotlib's ``loc="best"`` does the same job properly, but it measures
    against every artist on the axes — ~8.5s per chart once there are 10,000
    spaghetti lines, which would double the time to build an export. Counting
    sampled points inside four candidate boxes costs milliseconds.
    """
    if not x or not series:
        return LEGEND_CORNERS[0]

    series = series + list(extra or ())
    finite = [v for s in series for v in s if v is not None]
    if not finite:
        return LEGEND_CORNERS[0]

    # The axes are pinned to the origin, so the visible box is [0, max].
    x_max, y_max = max(x), max(finite)
    if x_max <= 0 or y_max <= 0:
        return LEGEND_CORNERS[0]

    bw, bh = box
    x_left, x_right = x_max * bw, x_max * (1 - bw)
    y_low, y_high = y_max * bh, y_max * (1 - bh)

    spaghetti = series[:len(series) - len(extra or ())]
    step = max(1, len(spaghetti) // max_series)
    sampled = spaghetti[::step] + list(extra or ())
    counts = dict.fromkeys(LEGEND_CORNERS, 0)
    for s in sampled:
        for xi, yi in zip(x, s):
            if yi is None:
                continue
            right, left = xi >= x_right, xi <= x_left
            upper, lower = yi >= y_high, yi <= y_low
            if right and upper:
                counts["upper right"] += 1
            if right and lower:
                counts["lower right"] += 1
            if left and upper:
                counts["upper left"] += 1
            if left and lower:
                counts["lower left"] += 1

    best = min(LEGEND_CORNERS, key=lambda c: counts[c])
    # A handful of stray points is fine; a populated corner is not. The budget
    # scales with the sample so it means the same thing at 3 runs and 10,000.
    budget = LEGEND_TOLERANCE * len(sampled) * len(x)
    return best if counts[best] <= budget else None


def _place_legend(plt, corner: Optional[str]) -> None:
    """Draw the legend in ``corner``, or above the axes when nothing is clear."""
    if corner is not None:
        plt.legend(loc=corner)
    else:
        # Nowhere inside is free, so put it outside — a strip above the plot,
        # which covers nothing and keeps the axes full width.
        plt.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3)


# The four charts, as (file stem, db column, y-axis label, draws a load line).
HOUSE_CHARTS = [
    ("total_cap_graph", "total_plate_capacity", "Total Slab Capacity (kN/m2)", True),
    ("beam_temp_graph", "lofl_temp", "Temperature (C)", False),
    ("mesh_temp_graph", "mesh_temp", "Temperature (C)", False),
]


# Shipped inside the ZIP so the export is runnable as delivered. Embedded as a
# string rather than a data file because the sidecar is PyInstaller-frozen, and
# a string constant needs no .spec change to survive the freeze.
#
# The chart styling reproduces the house style the PDF pipeline used (Segoe UI,
# #4798EA spaghetti at 20% alpha, coral mean), so charts drawn from this export
# match the ones the team already has in their reports.
_PLOT_SCRIPT = '''"""Regenerate the standard MACS+ charts from the CSVs in this folder.

Usage:  python plot_charts.py
Needs:  pandas, matplotlib   (pip install pandas matplotlib)

Everything is discovered from this folder - no paths to edit. The factored load
is read from the summary CSV rather than typed in by hand.
"""
import glob
import os

import matplotlib.pyplot as plt
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

# House style, matching the charts produced by the original PDF pipeline.
# These values are injected by the exporter so this script and the app's own
# chart renderer stay in step.
CHART_CONFIG = __CHART_CONFIG__
MID_BLUE_20ALPHA = "__SPAGHETTI__"
MID_BLUE = "__SCATTER_BLUE__"
CORAL = "__CORAL__"
DPI = __DPI__

TIME = ("Time", "mins")
GLAZING_TICKS = __GLAZING_TICKS__
GLAZING_TICK_LABELS = __GLAZING_TICK_LABELS__
LEGEND_BOX = __LEGEND_BOX__
LEGEND_CORNERS = __LEGEND_CORNERS__
LEGEND_TOLERANCE = __LEGEND_TOLERANCE__


def least_occupied_corner(x, series, extra=None, box=LEGEND_BOX, max_series=300):
    """Put the legend where the data isn't.

    Mirrors the exporter's own placement so a chart regenerated here sits in
    the same corner as the one the app produced. matplotlib's loc="best" does
    this properly but costs ~8.5s per chart at 10,000 lines.
    """
    if len(x) == 0 or not series:
        return LEGEND_CORNERS[0]
    series = series + list(extra or ())
    finite = [v for s in series for v in s if v == v and v is not None]
    if not finite:
        return LEGEND_CORNERS[0]

    x_max, y_max = max(x), max(finite)
    if x_max <= 0 or y_max <= 0:
        return LEGEND_CORNERS[0]

    bw, bh = LEGEND_BOX
    x_left, x_right = x_max * bw, x_max * (1 - bw)
    y_low, y_high = y_max * bh, y_max * (1 - bh)

    spaghetti = series[:len(series) - len(extra or ())]
    step = max(1, len(spaghetti) // max_series)
    sampled = spaghetti[::step] + list(extra or ())
    counts = dict.fromkeys(LEGEND_CORNERS, 0)
    for s in sampled:
        for xi, yi in zip(x, s):
            if yi != yi or yi is None:
                continue
            right, left = xi >= x_right, xi <= x_left
            upper, lower = yi >= y_high, yi <= y_low
            if right and upper:
                counts["upper right"] += 1
            if right and lower:
                counts["lower right"] += 1
            if left and upper:
                counts["upper left"] += 1
            if left and lower:
                counts["lower left"] += 1
    best = min(LEGEND_CORNERS, key=lambda c: counts[c])
    budget = LEGEND_TOLERANCE * len(sampled) * len(x)
    return best if counts[best] <= budget else None


def place_legend(corner):
    """Legend in a clear corner, or outside above the plot if there isn't one."""
    if corner is not None:
        plt.legend(loc=corner)
    else:
        plt.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3)


def label():
    """Recover the batch label from the summary filename."""
    matches = glob.glob(os.path.join(HERE, "summary_data_*.csv"))
    if not matches:
        raise SystemExit("No summary_data_*.csv here - run this inside the unzipped export.")
    name = os.path.basename(matches[0])
    return name[len("summary_data_"):-len(".csv")]


def make_plot(stem, kind, ylabel, out_png, factored_load, tag):
    path = os.path.join(HERE, "%s_%s.csv" % (stem, tag))
    if not os.path.exists(path):
        print("skipped (missing): %s" % os.path.basename(path))
        return

    df = pd.read_csv(path, header=[0, 1])
    # Interpolate against time, not row position. Runs sample on different time
    # steps, so the grid is uneven (0, 4, 5, ...) and pandas' "linear" — which
    # ignores the index and treats rows as equally spaced — would bend the
    # curves. method="index" uses the actual minutes; bfill covers a run whose
    # first sample lands after t=0.
    df = df.set_index(TIME).interpolate(method="index").bfill().reset_index()
    runs = df.drop(columns=[TIME])

    with plt.rc_context(CHART_CONFIG):
        x = df[TIME]
        for column in runs:
            plt.plot(x, runs[column], color=MID_BLUE_20ALPHA)
        # one more, purely so the spaghetti gets a single legend entry
        plt.plot(x, runs[column], color=MID_BLUE_20ALPHA, label="Recorded Temperature")
        mean = runs.mean(axis=1)
        plt.plot(x, mean, color=CORAL, label="Average Value")

        # Every drawn line counts when placing the legend — the load line spans
        # the full width low down, so ignoring it puts the legend through it.
        extra = [list(mean)]
        if kind == "capacity" and factored_load is not None:
            load = [factored_load] * len(x)
            plt.plot(x, load, color="red", label="Factored Load")
            extra.append(load)

        place_legend(
            least_occupied_corner(list(x), [list(runs[c]) for c in runs], extra)
        )

        plt.ylabel(ylabel)
        plt.xlabel("Time (minutes)")
        plt.ylim(bottom=0)
        # Time starts at zero; autoscale would pad into negative minutes.
        plt.xlim(left=0)
        plt.grid(True)
        plt.savefig(os.path.join(HERE, out_png), dpi=DPI, bbox_inches="tight")
        plt.close()
    print("wrote %s" % out_png)


def make_scatter(summary, out_png):
    df = summary.copy()
    df["max_unity_factor"] = df["max_unity_factor"].astype(float)
    ok = df[df["max_unity_factor"] <= 1.0]
    bad = df[df["max_unity_factor"] > 1.0]

    with plt.rc_context(CHART_CONFIG):
        plt.scatter(ok["fireload"], ok["glazing_breakage"], c=MID_BLUE,
                    label="Unity factor < 1.0", s=5)
        plt.scatter(bad["fireload"], bad["glazing_breakage"], c=CORAL,
                    label="Unity factor >=1.0", s=5)
        plt.xlabel("Fireload (MJ/m2)")
        plt.ylabel("Glazing Breakage (%)")
        # A share of the opening: 0 to 100, never outside it.
        plt.ylim(0.0, 1.0)
        plt.yticks(GLAZING_TICKS, GLAZING_TICK_LABELS)
        plt.legend()
        plt.savefig(os.path.join(HERE, out_png), dpi=DPI, bbox_inches="tight")
        plt.close()
    print("wrote %s  (%d pass / %d fail)" % (out_png, len(ok), len(bad)))


def main():
    tag = label()
    summary = pd.read_csv(os.path.join(HERE, "summary_data_%s.csv" % tag))

    factored_load = None
    if "factored_hot" in summary.columns and len(summary):
        factored_load = float(summary["factored_hot"].iloc[0])
        print("factored load: %s kN/m2" % factored_load)

    make_plot("total_cap_data", "capacity", "Total Slab Capacity (kN/m2)",
              "total_cap_graph_%s.png" % tag, factored_load, tag)
    make_plot("beam_temp_data", "temp", "Temperature (C)",
              "beam_temp_graph_%s.png" % tag, factored_load, tag)
    make_plot("mesh_temp_data", "temp", "Temperature (C)",
              "mesh_temp_graph_%s.png" % tag, factored_load, tag)
    make_scatter(summary, "scatter_fail_pass_%s.png" % tag)


if __name__ == "__main__":
    main()
'''


_README = """MACS+ batch export - {label}

{n_runs} runs. Nine CSVs, one row per timestep, one column per run.

TO MAKE THE CHARTS
------------------
    pip install pandas matplotlib
    python plot_charts.py

Run it in this folder. It finds the CSVs itself and reads the factored load
from the summary, then writes four PNGs beside them.

THE FILES
---------
  summary_data_{label}.csv          one row per run: fire load, glazing,
                                    opening factor, peak unity factor, the
                                    time it peaked, the time it first passed
                                    1.0 (blank if never), and factored load
  prot_beam_crit_temp_{label}.csv   perimeter beam temperatures, sides A-D
  total_cap_data_{label}.csv        total slab capacity vs time
  slab_cap_data_{label}.csv         slab capacity vs time
  beam_cap_data_{label}.csv         beam capacity vs time
  slab_yield_data_{label}.csv       slab yield vs time
  beam_temp_data_{label}.csv        beam temperature vs time
  mesh_temp_data_{label}.csv        mesh temperature vs time
  slabbot_temp_data_{label}.csv     slab bottom temperature vs time

READING THEM YOURSELF
---------------------
The time-series files carry two header rows - quantity over unit - so load
them with:

    df = pd.read_csv("total_cap_data_{label}.csv", header=[0, 1])
    time = df[("Time", "mins")]

A run's number is the suffix on its column ("Total capacity_7"), and it is the
same number as sim_num in the summary, so the files line up.

Note glazing_breakage is a fraction (0.80 = 80%), matching the convention the
existing analysis scripts expect.
"""


def _sanitise_label(label: Optional[str]) -> str:
    """Reduce a batch name to something safe for a filename.

    Batch names are free text ("Unit 7 — 2nd floor / rev B"), and they end up
    both in ZIP entry names and in the download filename.
    """
    if not label:
        return "export"
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in label)
    cleaned = "_".join(cleaned.split())
    return cleaned[:60] or "export"


def _plot_script_source() -> str:
    """The bundled script with the house style injected.

    Injected rather than duplicated so the script and ``_render_house_charts``
    can't drift into producing differently-styled charts.
    """
    return (
        _PLOT_SCRIPT
        .replace("__CHART_CONFIG__", repr(HOUSE_CHART_CONFIG))
        .replace("__SPAGHETTI__", HOUSE_SPAGHETTI)
        .replace("__SCATTER_BLUE__", HOUSE_SCATTER_BLUE)
        .replace("__CORAL__", HOUSE_CORAL)
        .replace("__DPI__", str(HOUSE_DPI))
        .replace("__LEGEND_BOX__", repr(LEGEND_BOX))
        .replace("__LEGEND_CORNERS__", repr(LEGEND_CORNERS))
        .replace("__LEGEND_TOLERANCE__", repr(LEGEND_TOLERANCE))
        .replace("__GLAZING_TICKS__", repr(GLAZING_TICKS))
        .replace("__GLAZING_TICK_LABELS__", repr(GLAZING_TICK_LABELS))
    )


def _render_house_charts(db: ResultsDB, batch_id: Optional[str],
                         suffix: str, output_dir: Path) -> list[Path]:
    """Render the four house-style charts, matching the bundled script.

    Same style constants, same filenames, same content as running
    ``plot_charts.py`` on the exported CSVs — so whichever way a chart is
    obtained, it's the same picture.

    Serialised on MPL_LOCK: pyplot's figures are process-global, so a chart
    request arriving mid-render would otherwise draw onto this one's axes.
    """
    with MPL_LOCK:
        return _render_house_charts_locked(db, batch_id, suffix, output_dir)


def _render_house_charts_locked(db: ResultsDB, batch_id: Optional[str],
                                suffix: str, output_dir: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    runs = _runs_for(db, batch_id)
    if not runs:
        return []

    run_ids = [r["id"] for r in runs]
    factored = next((r.get("factored_hot") for r in runs
                     if r.get("factored_hot") is not None), None)
    paths: list[Path] = []

    for stem, column, ylabel, draws_load in HOUSE_CHARTS:
        rows = _timeseries_for(db, column, batch_id)
        if not rows:
            continue

        by_run: dict = defaultdict(dict)
        times: set = set()
        for run_id, t, value in rows:
            if value is not None:
                by_run[run_id][t] = value
                times.add(t)
        grid = sorted(times)
        if not grid:
            continue

        series = [_on_grid(by_run[rid], grid) for rid in run_ids if by_run.get(rid)]
        if not series:
            continue

        with plt.rc_context(HOUSE_CHART_CONFIG):
            for values in series:
                plt.plot(grid, values, color=HOUSE_SPAGHETTI)
            # one more, purely so the spaghetti gets a single legend entry
            plt.plot(grid, series[-1], color=HOUSE_SPAGHETTI,
                     label="Recorded Temperature")
            mean = _mean_across(series)
            plt.plot(grid, mean, color=HOUSE_CORAL, label="Average Value")

            # Every drawn line counts when deciding where the legend goes —
            # the load line spans the full width low down, so ignoring it puts
            # the legend straight through it.
            extra = [mean]
            if draws_load and factored is not None:
                load = [factored] * len(grid)
                plt.plot(grid, load, color="red", label="Factored Load")
                extra.append(load)

            _place_legend(plt, _least_occupied_corner(grid, series, extra))

            plt.ylabel(ylabel)
            plt.xlabel("Time (minutes)")
            plt.ylim(bottom=0)
            # Time starts at zero. Autoscale pads into negative time, which is
            # meaningless here and detaches the curves from the origin.
            plt.xlim(left=0)
            plt.grid(True)
            path = output_dir / f"{stem}_{suffix}.png"
            plt.savefig(path, dpi=HOUSE_DPI, bbox_inches="tight")
            plt.close()
            paths.append(path)

    # Scatter — fire load vs glazing, coloured by pass/fail on unity factor
    pass_x, pass_y, fail_x, fail_y = [], [], [], []
    for run in runs:
        qf, wp, uf = run.get("qf"), run.get("window_percent"), run.get("uf_max")
        if qf is None or wp is None:
            continue
        if uf is not None and uf <= 1.0:
            pass_x.append(qf); pass_y.append(wp / 100.0)
        else:
            fail_x.append(qf); fail_y.append(wp / 100.0)

    if pass_x or fail_x:
        with plt.rc_context(HOUSE_CHART_CONFIG):
            plt.scatter(pass_x, pass_y, c=HOUSE_SCATTER_BLUE,
                        label="Unity factor < 1.0", s=5)
            plt.scatter(fail_x, fail_y, c=HOUSE_CORAL,
                        label="Unity factor >=1.0", s=5)
            plt.xlabel("Fireload (MJ/m2)")
            plt.ylabel("Glazing Breakage (%)")
            # A share of the opening: 0 to 100, never outside it.
            plt.ylim(0.0, 1.0)
            plt.yticks(GLAZING_TICKS, GLAZING_TICK_LABELS)
            plt.legend()
            path = output_dir / f"scatter_fail_pass_{suffix}.png"
            plt.savefig(path, dpi=HOUSE_DPI, bbox_inches="tight")
            plt.close()
            paths.append(path)

    return paths


def _on_grid(points: dict, grid: list) -> list:
    """Put one run's samples onto the common time grid.

    Interior gaps are interpolated linearly and the tail is held flat past the
    run's last sample — matching what pandas' ``interpolate(method="linear")``
    does to the exported CSV, so the app's charts and the script's agree.
    """
    known = sorted(points)
    out, j = [], 0
    for t in grid:
        if t <= known[0]:
            out.append(points[known[0]])
            continue
        if t >= known[-1]:
            out.append(points[known[-1]])
            continue
        while known[j + 1] < t:
            j += 1
        t0, t1 = known[j], known[j + 1]
        v0, v1 = points[t0], points[t1]
        out.append(v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0))
    return out


def _mean_across(series: list[list]) -> list:
    return [sum(col) / len(col) for col in zip(*series)]


def generate_report_zip(db: ResultsDB, batch_id: Optional[str] = None,
                        label: Optional[str] = None,
                        include_data: bool = True,
                        include_plots: bool = False) -> Path:
    """Generate a ZIP of the batch's results — data, charts, or both.

    ``batch_id`` scopes the export to one batch; None exports every successful
    run in the database. ``label`` is folded into each filename the way the
    legacy pipeline folded in its PDF folder name.

    ``include_data`` writes the 9 CSVs plus the runnable plotting script;
    ``include_plots`` writes the 4 house-style PNGs. Charts are off by default
    because rendering 10,000-line spaghetti is by far the slowest part of
    building the ZIP.

    Returns path to the temporary ZIP file. Caller should clean up.
    """
    if not (include_data or include_plots):
        raise ValueError("Nothing to export: enable include_data or include_plots")

    tmp_dir = Path(tempfile.mkdtemp(prefix="macs_report_"))
    zip_path = tmp_dir / "report.zip"
    suffix = _sanitise_label(label)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_data:
            # Summary CSV
            zf.writestr(f"summary_data_{suffix}.csv",
                        generate_summary_csv(db, batch_id=batch_id))

            # 7 wide-format time-series CSVs
            for db_col, csv_name, _qty, _unit in WIDE_CSV_COLUMNS:
                content = generate_wide_timeseries_csv(db, db_col, batch_id=batch_id)
                zf.writestr(f"{csv_name}_{suffix}.csv", content)

            # Protected beam CSV
            zf.writestr(f"prot_beam_crit_temp_{suffix}.csv",
                        generate_prot_beam_csv(db, batch_id=batch_id))

            # Make the export runnable as delivered rather than a pile of CSVs.
            zf.writestr("plot_charts.py", _plot_script_source())

        zf.writestr("README.txt", _README.format(
            label=suffix, n_runs=len(_runs_for(db, batch_id)),
        ))

        if include_plots:
            for plot_path in _render_house_charts(
                db, batch_id, suffix, tmp_dir / "plots"
            ):
                zf.write(plot_path, plot_path.name)

    return zip_path
