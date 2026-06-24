"""Report export module — generates CSVs and plots from SQLite data.

Produces the same 9 CSVs + 4 PNG plots that engineers currently get from
the PDF pipeline, but directly from the database.
"""

import csv
import io
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional

from macs_automation.db import ResultsDB


def generate_summary_csv(db: ResultsDB) -> str:
    """Generate the summary CSV with one row per successful run.

    Columns: sim_num, fireload, glazing_breakage, opening_factor,
             max_unity_factor, time_of_max, time_exceed_one
    """
    runs = db.get_successful_runs()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "sim_num", "fireload", "glazing_breakage",
        "max_unity_factor", "time_of_max", "time_exceed_one",
        "factored_hot",
    ])

    for i, run in enumerate(runs, 1):
        time_of_max = db.get_time_of_max_uf(run["id"])
        time_exceed = db.get_time_exceed_one(run["id"])
        writer.writerow([
            i,
            run.get("qf"),
            run.get("window_percent"),
            run.get("uf_max"),
            time_of_max if time_of_max is not None else "",
            time_exceed if time_exceed is not None else "",
            run.get("factored_hot"),
        ])

    return buf.getvalue()


def generate_wide_timeseries_csv(db: ResultsDB, column: str) -> str:
    """Generate a wide-format time-series CSV.

    Pivots from long format (DB) to wide format:
    Time(min) | Run_1 | Run_2 | ... | Run_N

    Used for: lofl_temp, mesh_temp, slabbot_temp, beam_hot_capacity,
              slab_yield, slab_cap, total_plate_capacity
    """
    rows = db.get_all_time_series_column(column)
    if not rows:
        return ""

    # Build pivot dict: {(run_id, time_min): value}
    pivot = {}
    run_ids = []
    times = set()
    seen_runs = set()

    for run_id, time_min, value in rows:
        pivot[(run_id, time_min)] = value
        times.add(time_min)
        if run_id not in seen_runs:
            seen_runs.add(run_id)
            run_ids.append(run_id)

    sorted_times = sorted(times)

    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["Time(min)"] + [f"Run_{rid}" for rid in run_ids]
    writer.writerow(header)

    for t in sorted_times:
        row = [t]
        for rid in run_ids:
            val = pivot.get((rid, t), "")
            row.append(val)
        writer.writerow(row)

    return buf.getvalue()


def generate_prot_beam_csv(db: ResultsDB) -> str:
    """Generate the protected beam temperature CSV.

    Columns: Run, Perimeter_Beam_Temp_A, _B, _C, _D, Fireload, Glazing_Breakage
    """
    runs = db.get_successful_runs()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Run", "Perimeter_Beam_Temp_A", "Perimeter_Beam_Temp_B",
        "Perimeter_Beam_Temp_C", "Perimeter_Beam_Temp_D",
        "Fireload", "Glazing_Breakage",
    ])

    for i, run in enumerate(runs, 1):
        writer.writerow([
            i,
            run.get("side_a_critical_temp"),
            run.get("side_b_critical_temp"),
            run.get("side_c_critical_temp"),
            run.get("side_d_critical_temp"),
            run.get("qf"),
            run.get("window_percent"),
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

    for rid, data in by_run.items():
        data.sort()
        times = [d[0] for d in data]
        values = [d[1] for d in data]
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


# Column names for the 7 wide-format time-series CSVs
WIDE_CSV_COLUMNS = [
    ("lofl_temp", "beam_temperature"),
    ("mesh_temp", "mesh_temperature"),
    ("slabbot_temp", "slab_bottom_temperature"),
    ("beam_hot_capacity", "beam_hot_capacity"),
    ("slab_yield", "slab_yield"),
    ("slab_cap", "slab_capacity"),
    ("total_plate_capacity", "total_plate_capacity"),
]


def generate_report_zip(db: ResultsDB) -> Path:
    """Generate a ZIP file with 9 CSVs + 4 PNGs.

    Returns path to the temporary ZIP file. Caller should clean up.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="macs_report_"))
    zip_path = tmp_dir / "report.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Summary CSV
        zf.writestr("summary.csv", generate_summary_csv(db))

        # 7 wide-format time-series CSVs
        for db_col, csv_name in WIDE_CSV_COLUMNS:
            content = generate_wide_timeseries_csv(db, db_col)
            zf.writestr(f"{csv_name}.csv", content)

        # Protected beam CSV
        zf.writestr("protected_beam_temps.csv", generate_prot_beam_csv(db))

        # 4 plots
        plot_dir = tmp_dir / "plots"
        plot_paths = generate_plots(db, plot_dir)
        for plot_path in plot_paths:
            zf.write(plot_path, plot_path.name)

    return zip_path
