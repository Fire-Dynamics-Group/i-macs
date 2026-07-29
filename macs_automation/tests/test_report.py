"""Tests for report.py — CSV + plot export module."""

import csv
import io
import zipfile
from pathlib import Path

import pytest

from macs_automation.db import ResultsDB
from macs_automation.report import (
    HOUSE_CHART_CONFIG,
    HOUSE_DPI,
    LEGEND_BOX,
    LEGEND_CORNERS,
    _least_occupied_corner,
    HOUSE_SCATTER_BLUE,
    HOUSE_SPAGHETTI,
    WIDE_CSV_COLUMNS,
    _extend_flat,
    _factored_hot_range,
    _forward_filled_average,
    _inputs_vary,
    _opening_factor,
    _plot_timeseries,
    _render_house_charts,
    generate_prot_beam_csv,
    generate_plots,
    generate_report_zip,
    generate_summary_csv,
    generate_wide_timeseries_csv,
)


class TestForwardFilledAverage:
    """The spaghetti-chart average must hold each run's last value flat past the
    end of its data (forward-fill onto the common time grid), matching MACS+ — so
    a fire that ends early still counts (at its final temperature) at later times,
    rather than dropping out of the mean and letting the few long runs dominate."""

    def test_holds_last_value_after_run_ends(self):
        by_run = {
            "short": [(0, 0.0), (1, 10.0), (2, 10.0)],            # ends at t=2
            "long": [(0, 0.0), (1, 50.0), (2, 80.0), (3, 90.0), (4, 100.0)],
        }
        times, avg = _forward_filled_average(by_run)
        assert times == [0, 1, 2, 3, 4]
        # at t=3 'short' is held at 10, 'long' is 90 -> mean 50 (old code gave 90)
        assert avg[3] == pytest.approx(50.0)
        assert avg[4] == pytest.approx(55.0)

    def test_single_run_is_itself(self):
        times, avg = _forward_filled_average({"a": [(0, 1.0), (2, 3.0)]})
        assert times == [0, 2]
        assert avg == pytest.approx([1.0, 3.0])

    def test_empty(self):
        assert _forward_filled_average({}) == ([], [])


class TestExtendFlat:
    """Each spaghetti line holds its last value flat to the common end time, so a
    fire that finishes early still shows as a horizontal band to the axis end —
    matching MACS+ (which forward-fills every run, not just the average)."""

    def test_holds_last_value_to_end(self):
        assert _extend_flat([0, 2], [10, 30], 5) == ([0, 2, 5], [10, 30, 30])

    def test_noop_when_already_at_end(self):
        assert _extend_flat([0, 5], [1, 2], 5) == ([0, 5], [1, 2])

    def test_empty(self):
        assert _extend_flat([], [], 5) == ([], [])
from macs_automation.tests.conftest import _insert_populated_run


class TestSummaryCSV:
    def test_header_row(self, populated_db):
        result = generate_summary_csv(populated_db)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "sim_num" in header
        assert "fireload" in header
        assert "max_unity_factor" in header
        assert "time_of_max" in header
        assert "time_exceed_one" in header

    def test_row_count(self, populated_db):
        result = generate_summary_csv(populated_db)
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        # 9 successful runs (8 pass + 1 fail) + 1 header
        assert len(rows) == 10

    def test_sim_numbers_sequential(self, populated_db):
        result = generate_summary_csv(populated_db)
        reader = csv.reader(io.StringIO(result))
        next(reader)  # skip header
        sim_nums = [int(row[0]) for row in reader]
        assert sim_nums == list(range(9))

    def test_fireload_values_present(self, populated_db):
        result = generate_summary_csv(populated_db)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        # First run has qf=400.0
        assert float(rows[0]["fireload"]) == 400.0

    def test_time_exceed_one_for_failing_run(self, populated_db):
        """Run 9 (UF=1.3) should have a time_exceed_one value."""
        result = generate_summary_csv(populated_db)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        # The failing run (index 8, sim_num 9) should have time_exceed_one set
        failing_row = rows[8]
        assert float(failing_row["max_unity_factor"]) == 1.3
        # time_exceed_one should be non-empty for a run with UF > 1.0
        assert failing_row["time_exceed_one"] != ""


class TestWideTimeseriesCSV:
    def test_header_has_runs(self, populated_db):
        result = generate_wide_timeseries_csv(populated_db, "lofl_temp")
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert header[0] == "Time"
        # Should have columns for each successful run
        assert len(header) >= 10  # Time + 9 runs

    def test_time_column_sorted(self, populated_db):
        result = generate_wide_timeseries_csv(populated_db, "mesh_temp")
        reader = csv.reader(io.StringIO(result))
        next(reader), next(reader)  # skip both header rows
        times = [float(row[0]) for row in reader]
        assert times == sorted(times)

    def test_values_present(self, populated_db):
        result = generate_wide_timeseries_csv(populated_db, "total_plate_capacity")
        reader = csv.reader(io.StringIO(result))
        next(reader), next(reader)  # skip both header rows
        rows = list(reader)
        assert len(rows) > 0
        # All data cells should be numeric
        for row in rows:
            for val in row[1:]:  # skip Time column
                if val:
                    float(val)  # should not raise

    def test_invalid_column_raises(self, populated_db):
        with pytest.raises(ValueError):
            generate_wide_timeseries_csv(populated_db, "DROP TABLE runs")

    def test_all_seven_columns(self, populated_db):
        """All 7 column types should produce non-empty CSVs."""
        for db_col, *_ in WIDE_CSV_COLUMNS:
            result = generate_wide_timeseries_csv(populated_db, db_col)
            assert len(result) > 0, f"Empty CSV for {db_col}"


class TestProtBeamCSV:
    def test_header_row(self, populated_db):
        result = generate_prot_beam_csv(populated_db)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert "Perimeter_Beam_Temp_A" in header
        assert "Perimeter_Beam_Temp_D" in header
        assert "Fireload" in header

    def test_row_count(self, populated_db):
        result = generate_prot_beam_csv(populated_db)
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        # 9 successful runs + 1 header
        assert len(rows) == 10

    def test_beam_temps_present(self, populated_db):
        result = generate_prot_beam_csv(populated_db)
        reader = csv.DictReader(io.StringIO(result))
        row = next(reader)
        assert float(row["Perimeter_Beam_Temp_A"]) == 620.0
        assert float(row["Perimeter_Beam_Temp_B"]) == 756.0


class TestGeneratePlots:
    def test_generates_four_plots(self, populated_db, tmp_path):
        paths = generate_plots(populated_db, tmp_path / "plots")
        assert len(paths) == 4

    def test_plot_files_exist(self, populated_db, tmp_path):
        paths = generate_plots(populated_db, tmp_path / "plots")
        for p in paths:
            assert p.exists()
            assert p.stat().st_size > 0

    def test_plot_filenames(self, populated_db, tmp_path):
        paths = generate_plots(populated_db, tmp_path / "plots")
        names = {p.name for p in paths}
        assert "total_capacity.png" in names
        assert "beam_temperature.png" in names
        assert "mesh_temperature.png" in names
        assert "scatter_passfail.png" in names


class TestFactoredHotRange:
    def test_returns_min_max(self):
        runs = [{"factored_hot": 3.0}, {"factored_hot": 5.0}, {"factored_hot": 4.0}]
        assert _factored_hot_range(runs) == (3.0, 5.0)

    def test_constant_returns_same_min_max(self):
        runs = [{"factored_hot": 3.7}, {"factored_hot": 3.7}]
        assert _factored_hot_range(runs) == (3.7, 3.7)

    def test_ignores_none(self):
        runs = [{"factored_hot": 3.7}, {"factored_hot": None}, {"factored_hot": 5.0}]
        assert _factored_hot_range(runs) == (3.7, 5.0)

    def test_empty_returns_none(self):
        assert _factored_hot_range([]) is None

    def test_all_none_returns_none(self):
        assert _factored_hot_range([{"factored_hot": None}]) is None


class TestInputsVary:
    def test_varying_returns_true(self):
        runs = [{"qf": 400}, {"qf": 500}]
        assert _inputs_vary(runs, "qf") is True

    def test_constant_returns_false(self):
        runs = [{"qf": 400}, {"qf": 400}]
        assert _inputs_vary(runs, "qf") is False

    def test_any_field_varies(self):
        runs = [{"qf": 400, "window_percent": 30},
                {"qf": 400, "window_percent": 50}]
        assert _inputs_vary(runs, "qf", "window_percent") is True

    def test_all_fields_constant(self):
        runs = [{"qf": 400, "window_percent": 30},
                {"qf": 400, "window_percent": 30}]
        assert _inputs_vary(runs, "qf", "window_percent") is False

    def test_ignores_none(self):
        runs = [{"qf": 400}, {"qf": None}, {"qf": 400}]
        assert _inputs_vary(runs, "qf") is False


class TestPlotTimeseries:
    def test_constant_factored_hot_renders_dashed_line(self, populated_db, tmp_path):
        import matplotlib.pyplot as plt
        result = _plot_timeseries(
            populated_db, "total_plate_capacity",
            "Total Plate Capacity", "Capacity (kN/m)",
            "test.png", tmp_path,
            hline_band=(3.7, 3.7),
        )
        assert result is not None
        path, fig = result
        ax = fig.axes[0]
        # Constant band → no shaded patch, just a dashed hline
        assert len(ax.patches) == 0
        dashed = [ln for ln in ax.lines if ln.get_linestyle() == "--"]
        assert len(dashed) >= 1
        plt.close(fig)

    def test_varying_factored_hot_renders_shaded_band(self, populated_db, tmp_path):
        import matplotlib.pyplot as plt
        result = _plot_timeseries(
            populated_db, "total_plate_capacity",
            "Total Plate Capacity", "Capacity (kN/m)",
            "test.png", tmp_path,
            hline_band=(3.0, 5.0),
        )
        assert result is not None
        path, fig = result
        ax = fig.axes[0]
        # Varying band → at least one axhspan patch
        assert len(ax.patches) >= 1
        plt.close(fig)

    def test_no_hline_when_band_is_none(self, populated_db, tmp_path):
        import matplotlib.pyplot as plt
        result = _plot_timeseries(
            populated_db, "total_plate_capacity",
            "Total Plate Capacity", "Capacity (kN/m)",
            "test.png", tmp_path,
            hline_band=None,
        )
        assert result is not None
        path, fig = result
        ax = fig.axes[0]
        assert len(ax.patches) == 0
        dashed = [ln for ln in ax.lines if ln.get_linestyle() == "--"]
        assert len(dashed) == 0
        plt.close(fig)


@pytest.fixture
def constant_inputs_db(tmp_path):
    """Database where qf and window_percent are identical across all runs."""
    db_path = tmp_path / "constant.db"
    db = ResultsDB(db_path)
    for i in range(5):
        uf = 0.3 + i * 0.1
        _insert_populated_run(
            db, i, uf_max=round(uf, 2), qf=500.0, window_percent=50.0,
        )
    yield db
    db.close()


class TestScatterDegenerateDrop:
    def test_no_scatter_when_inputs_constant(self, constant_inputs_db, tmp_path):
        paths = generate_plots(constant_inputs_db, tmp_path / "plots")
        names = {p.name for p in paths}
        assert "scatter_passfail.png" not in names
        assert len(paths) == 3

    def test_scatter_present_when_inputs_vary(self, populated_db, tmp_path):
        paths = generate_plots(populated_db, tmp_path / "plots")
        names = {p.name for p in paths}
        assert "scatter_passfail.png" in names


class TestReportZip:
    def test_creates_zip(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

    def test_zip_contains_csvs(self, populated_db):
        zip_path = generate_report_zip(populated_db, label="run")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "summary_data_run.csv" in names
            assert "prot_beam_crit_temp_run.csv" in names
            assert "beam_temp_data_run.csv" in names
            assert "mesh_temp_data_run.csv" in names
            assert "total_cap_data_run.csv" in names

    def test_plots_excluded_by_default(self, populated_db):
        """The data download is for re-plotting elsewhere — rendering 10k-line
        spaghetti PNGs nobody asked for is the slowest part of the export."""
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            assert [n for n in zf.namelist() if n.endswith(".png")] == []

    def test_zip_contains_plots_when_requested(self, populated_db):
        zip_path = generate_report_zip(populated_db, include_plots=True)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            png_files = [n for n in names if n.endswith(".png")]
            assert len(png_files) == 4

    def test_zip_has_nine_csvs(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            csv_files = [n for n in names if n.endswith(".csv")]
            assert len(csv_files) == 9

    def test_zip_scoped_to_batch(self, two_batch_db):
        zip_path = generate_report_zip(two_batch_db, batch_id="batch_b", label="b")
        with zipfile.ZipFile(zip_path) as zf:
            summary = zf.read("summary_data_b.csv").decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(summary)))
        assert [float(r["fireload"]) for r in rows] == [900.0, 930.0]


class TestExportContents:
    """Three shapes of download: the data, just the charts, or both."""

    def _names(self, **kw):
        zip_path = generate_report_zip(**kw)
        with zipfile.ZipFile(zip_path) as zf:
            return zf.namelist()

    def test_data_only_is_the_default(self, populated_db):
        names = self._names(db=populated_db)
        assert len([n for n in names if n.endswith(".csv")]) == 9
        assert [n for n in names if n.endswith(".png")] == []

    def test_charts_only_omits_the_csvs(self, populated_db):
        names = self._names(db=populated_db, include_data=False, include_plots=True)
        assert [n for n in names if n.endswith(".csv")] == []
        assert len([n for n in names if n.endswith(".png")]) == 4

    def test_charts_only_omits_the_plotting_script(self, populated_db):
        """Nothing to re-plot from, so the script would just be noise."""
        assert "plot_charts.py" not in self._names(
            db=populated_db, include_data=False, include_plots=True)

    def test_both_ships_everything(self, populated_db):
        names = self._names(db=populated_db, include_plots=True)
        assert len([n for n in names if n.endswith(".csv")]) == 9
        assert len([n for n in names if n.endswith(".png")]) == 4
        assert "plot_charts.py" in names

    def test_chart_filenames_match_the_script_s(self, populated_db):
        """A chart downloaded from the app and one produced by running the
        bundled script are the same picture, so they carry the same name."""
        names = self._names(db=populated_db, label="run", include_plots=True)
        assert "total_cap_graph_run.png" in names
        assert "beam_temp_graph_run.png" in names
        assert "mesh_temp_graph_run.png" in names
        assert "scatter_fail_pass_run.png" in names

    def test_empty_export_is_rejected(self, populated_db):
        with pytest.raises(ValueError):
            generate_report_zip(populated_db, include_data=False, include_plots=False)


class TestHouseStyleIsSharedWithTheScript:
    """The app-rendered PNGs and the script-rendered PNGs must look the same.
    Both read their colours, figure size and dpi from these constants, so the
    two can't drift apart."""

    def test_script_carries_the_shared_constants(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            src = zf.read("plot_charts.py").decode("utf-8")
        assert HOUSE_SPAGHETTI in src        # '#4798EA33'
        assert HOUSE_SCATTER_BLUE in src     # '#4798EA'
        assert f"DPI = {HOUSE_DPI}" in src
        # and no placeholder survived the injection
        assert "__" not in src.replace("__file__", "").replace("__name__", "").replace(
            "__main__", "")

    def test_figure_size_is_the_house_six_by_four(self):
        assert HOUSE_CHART_CONFIG["figure.figsize"] == [6, 4]

    def test_axis_text_is_the_house_grey(self):
        assert HOUSE_CHART_CONFIG["xtick.color"] == (0.59, 0.56, 0.56)


class TestLegendAvoidsTheData:
    """The legend goes wherever the data isn't. matplotlib's own loc='best'
    does this but costs ~8.5s per chart at 10,000 lines — doubling the export —
    so the corner is chosen from a cheap occupancy count instead."""

    def test_picks_the_empty_corner(self):
        # A rising line: data hugs lower-left and upper-right, so the legend
        # belongs in one of the other two corners.
        x = list(range(100))
        series = [[float(v) for v in range(100)]]
        assert _least_occupied_corner(x, series) in ("upper left", "lower right")

    def test_avoids_a_high_flat_band(self):
        # Capacity-shaped: everything sits along the top, nothing low and late.
        x = list(range(100))
        series = [[30.0] * 100 for _ in range(5)]
        assert _least_occupied_corner(x, series) in ("lower left", "lower right")

    def test_avoids_an_early_peak(self):
        # Temperature-shaped: a peak early, decaying to nothing — the top right
        # is empty, which is where these charts have always put the legend.
        x = list(range(100))
        series = [[1000.0 if i < 25 else 50.0 for i in range(100)]]
        assert _least_occupied_corner(x, series) == "upper right"

    def test_goes_outside_when_every_corner_holds_data(self):
        """A dense 10,000-run mesh chart fills all four corners. Dropping the
        legend in the least-bad one still buries the rising edge, so the caller
        is told to put it outside instead."""
        x = list(range(100))
        # One line hugging the top, one hugging the bottom, across the width.
        series = [[100.0] * 100, [1.0] * 100]
        assert _least_occupied_corner(x, series) is None

    def test_extra_lines_are_never_sampled_away(self):
        """The factored-load line spans the full width low down. It is a single
        line among thousands, so sampling would drop it and the legend would be
        placed straight through it."""
        x = list(range(100))
        # Spaghetti only in the upper half: both lower corners look free...
        spaghetti = [[90.0] * 100 for _ in range(5000)]
        assert _least_occupied_corner(x, spaghetti) in ("lower left", "lower right")
        # ...until the load line at the bottom is counted, which it always is.
        load = [5.0] * 100
        assert _least_occupied_corner(x, spaghetti, [load]) not in (
            "lower left", "lower right",
        )

    def test_defaults_when_there_is_no_data(self):
        assert _least_occupied_corner([], []) == "upper right"

    def test_ignores_missing_values(self):
        x = list(range(10))
        assert _least_occupied_corner(x, [[None] * 10]) == "upper right"

    def test_bundled_script_uses_the_same_geometry(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            src = zf.read("plot_charts.py").decode("utf-8")
        # Same box proportions, or the app and the script disagree on placement.
        assert str(LEGEND_BOX) in src
        for corner in LEGEND_CORNERS:
            assert corner in src


class TestScatterGlazingAxis:
    """Glazing breakage is a percentage of the opening: it runs 0 to 100 and
    cannot sit outside that. The values are stored as a fraction, so the axis
    is 0-1 with ticks labelled as percent."""

    def _scatter_axis(self, db, tmp_path, monkeypatch):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        captured = {}
        real_savefig = plt.savefig

        def spy(*a, **kw):
            if "scatter" in str(a[0]):
                ax = plt.gca()
                captured["ylim"] = ax.get_ylim()
                captured["labels"] = [t.get_text() for t in ax.get_yticklabels()]
            return real_savefig(*a, **kw)

        monkeypatch.setattr(plt, "savefig", spy)
        _render_house_charts(db, None, "run", tmp_path / "charts")
        assert captured, "no scatter rendered"
        return captured

    def test_axis_is_exactly_zero_to_one(self, populated_db, tmp_path, monkeypatch):
        assert self._scatter_axis(populated_db, tmp_path, monkeypatch)["ylim"] == (0.0, 1.0)

    def test_ticks_are_labelled_as_percent(self, populated_db, tmp_path, monkeypatch):
        labels = self._scatter_axis(populated_db, tmp_path, monkeypatch)["labels"]
        assert labels == ["0", "20", "40", "60", "80", "100"]

    def test_bundled_script_matches(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            src = zf.read("plot_charts.py").decode("utf-8")
        assert "GLAZING_TICKS" in src


class TestConcurrentRenderingIsSafe:
    """pyplot keeps its figures in process-global state and the sidecar serves
    chart requests concurrently, so a chart request arriving mid-export used to
    draw onto the export's axes — producing a scatter with the mesh spaghetti
    through it and a merged seven-entry legend."""

    def test_charts_survive_a_competing_renderer(self, populated_db, tmp_path):
        import threading
        from macs_automation.report_docx import _render_scatter_chart

        clean = tmp_path / "clean"
        _render_house_charts(populated_db, None, "x", clean)

        # Read on this thread: sqlite connections are single-thread, and the
        # point here is contention over matplotlib, not over the database.
        runs = populated_db.get_successful_runs()
        stop = threading.Event()

        def compete():
            while not stop.is_set():
                _render_scatter_chart(runs)

        workers = [threading.Thread(target=compete) for _ in range(2)]
        for w in workers:
            w.start()
        try:
            contended = tmp_path / "contended"
            _render_house_charts(populated_db, None, "x", contended)
        finally:
            stop.set()
            for w in workers:
                w.join()

        for produced in sorted(clean.glob("*.png")):
            assert (contended / produced.name).read_bytes() == produced.read_bytes(), (
                f"{produced.name} differs when rendered under contention"
            )


class TestTimeAxisStartsAtZero:
    """Time starts at zero. Left to autoscale, matplotlib pads the axis into
    negative time (-11 min on a real batch), which is meaningless for a fire
    curve and leaves the spaghetti floating off the origin."""

    def test_renderer_pins_the_left_limit(self, populated_db, tmp_path, monkeypatch):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        calls = []
        real_xlim = plt.xlim
        monkeypatch.setattr(
            plt, "xlim", lambda *a, **kw: (calls.append(kw), real_xlim(*a, **kw))[1]
        )

        _render_house_charts(populated_db, None, "run", tmp_path / "charts")
        assert {"left": 0} in calls

    def test_bundled_script_pins_it_too(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            src = zf.read("plot_charts.py").decode("utf-8")
        assert "plt.xlim(left=0)" in src


class TestBundledPlotScript:
    """The ZIP ships a runnable plotting script so nobody has to hand-edit
    hardcoded paths, filenames and a factored load before seeing a chart."""

    def test_zip_includes_script_and_readme(self, populated_db):
        zip_path = generate_report_zip(populated_db, label="run")
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        assert "plot_charts.py" in names
        assert "README.txt" in names

    def test_bundled_script_is_valid_python(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            src = zf.read("plot_charts.py").decode("utf-8")
        compile(src, "plot_charts.py", "exec")

    def test_script_discovers_files_rather_than_hardcoding_a_path(self, populated_db):
        """The old scripts pinned an absolute path on one machine, which is
        exactly what made them un-runnable by anyone else."""
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            src = zf.read("plot_charts.py").decode("utf-8")
        assert "C:\\" not in src
        assert "glob" in src

    def test_readme_names_this_batch_s_files(self, populated_db):
        zip_path = generate_report_zip(populated_db, label="run")
        with zipfile.ZipFile(zip_path) as zf:
            readme = zf.read("README.txt").decode("utf-8")
        assert "summary_data_run.csv" in readme

    def test_csv_count_unaffected_by_the_extras(self, populated_db):
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            csvs = [n for n in zf.namelist() if n.endswith(".csv")]
        assert len(csvs) == 9


class TestOpeningFactor:
    """Reproduces Kevin's calc_op_fac: the opening is scaled by the breakage
    fraction in both area and height (height taken as sqrt of the fraction),
    then O = Av*sqrt(heq)/At clipped to EN 1991-1-2's [0.01, 0.20]."""

    def _run(self, **kw):
        base = {"Lc": 10.0, "Bc": 10.0, "Hc": 3.0, "Lw": 5.0, "Hw": 2.0,
                "window_percent": 50.0}
        base.update(kw)
        return base

    def test_matches_legacy_formula(self):
        # At = 2*100 + 2*(10+10)*3 = 320
        # perc = 0.5 -> av_open = 5*2*0.5 = 5, heq = 2*sqrt(0.5) = 1.41421
        # O = 5 * sqrt(1.41421) / 320 = 0.018581...
        assert _opening_factor(self._run()) == pytest.approx(0.0185813, abs=1e-6)

    def test_clipped_to_upper_bound(self):
        # A huge window in a tiny compartment saturates at 0.2
        assert _opening_factor(
            self._run(Lw=20.0, Hw=8.0, window_percent=100.0, Lc=5.0, Bc=5.0, Hc=3.0)
        ) == pytest.approx(0.2)

    def test_clipped_to_lower_bound(self):
        assert _opening_factor(
            self._run(Lw=0.1, Hw=0.1, window_percent=1.0)
        ) == pytest.approx(0.01)

    def test_missing_geometry_returns_none(self):
        assert _opening_factor(self._run(Lw=None)) is None


class TestLegacyCsvFormat:
    """The export exists so Kevin's existing matplotlib scripts can read it
    unchanged, so the headers must match his files byte-for-byte."""

    def test_summary_header_matches_legacy(self, populated_db):
        """The legacy seven come first and in order; factored_hot is appended.

        The plotting scripts index by column name, so a trailing column is
        invisible to them — but the factored load is a required input to the
        capacity chart and was previously only recoverable from the PDF."""
        header = next(csv.reader(io.StringIO(generate_summary_csv(populated_db))))
        assert header[:7] == [
            "sim_num", "fireload", "glazing_breakage", "opening_factor",
            "max_unity_factor", "time_of_max", "time_exceed_one",
        ]
        assert header[7] == "factored_hot"

    def test_factored_load_is_exported(self, populated_db):
        """Without this the capacity chart's red line has no value to plot."""
        rows = list(csv.DictReader(io.StringIO(generate_summary_csv(populated_db))))
        assert float(rows[0]["factored_hot"]) == 3.7

    def test_glazing_breakage_is_a_fraction(self, populated_db):
        """His CSVs store 0.802 where we store 80.2 — his calc_op_fac and his
        scatter both consume the fraction, despite the '%' axis label."""
        rows = list(csv.DictReader(io.StringIO(generate_summary_csv(populated_db))))
        # first run has window_percent=30.0
        assert float(rows[0]["glazing_breakage"]) == pytest.approx(0.30)

    def test_sim_num_is_zero_based(self, populated_db):
        """His sim_num came from the PDF filename's run number, which is 0-based."""
        rows = list(csv.DictReader(io.StringIO(generate_summary_csv(populated_db))))
        assert [int(r["sim_num"]) for r in rows] == list(range(9))

    @pytest.mark.parametrize("column,qty,unit", [
        ("lofl_temp", "Beam", "°C"),
        ("mesh_temp", "Mesh", "°C"),
        ("slabbot_temp", "Slab bottom", "°C"),
        ("beam_hot_capacity", "Beam capacity", "kN/m²"),
        ("slab_yield", "Slab yield", "kN/m²"),
        ("slab_cap", "Slab capacity", "kN/m²"),
        ("total_plate_capacity", "Total capacity", "kN/m²"),
    ])
    def test_wide_header_is_two_rows(self, populated_db, column, qty, unit):
        """Two header rows — quantity over unit — as pandas reads with
        header=[0,1]. The run index rides on the quantity, matching the files
        the plotting scripts were written against."""
        rows = list(csv.reader(
            io.StringIO(generate_wide_timeseries_csv(populated_db, column))))
        assert rows[0][0] == "Time"
        assert rows[1][0] == "mins"
        assert rows[0][1] == f"{qty}_0"
        assert rows[0][-1] == f"{qty}_8"       # 9 successful runs, 0-based
        assert set(rows[1][1:]) == {unit}

    def test_first_timestep_survives(self, populated_db):
        """A flattened single-row header makes pandas eat the t=0 row as the
        second header level; two rows keeps it."""
        rows = list(csv.reader(
            io.StringIO(generate_wide_timeseries_csv(populated_db, "lofl_temp"))))
        assert float(rows[2][0]) == 0.0

    def test_prot_beam_header_matches_legacy(self, populated_db):
        header = next(csv.reader(io.StringIO(generate_prot_beam_csv(populated_db))))
        assert header == [
            "Run", "Perimeter_Beam_Temp_A", "Perimeter_Beam_Temp_B",
            "Perimeter_Beam_Temp_C", "Perimeter_Beam_Temp_D",
            "Fireload", "Glazing_Breakage",
        ]

    def test_run_indices_align_across_files(self, populated_db):
        """sim_num, the wide-CSV column suffix and prot_beam's Run must all name
        the same run, or joining the files silently mismatches."""
        summary = list(csv.DictReader(io.StringIO(generate_summary_csv(populated_db))))
        prot = list(csv.DictReader(io.StringIO(generate_prot_beam_csv(populated_db))))
        wide = next(csv.reader(
            io.StringIO(generate_wide_timeseries_csv(populated_db, "lofl_temp"))))

        assert [r["sim_num"] for r in summary] == [r["Run"] for r in prot]
        assert [c.rsplit("_", 1)[1] for c in wide[1:]] == [r["sim_num"] for r in summary]

    def test_pandas_reads_it_as_a_multiindex(self, populated_db):
        """The contract the plotting scripts rely on: df[("Time","mins")] and
        df.drop(columns=[("Time","mins")]) both resolve."""
        pd = pytest.importorskip("pandas")
        df = pd.read_csv(
            io.StringIO(generate_wide_timeseries_csv(populated_db, "total_plate_capacity")),
            header=[0, 1],
        )
        assert ("Time", "mins") in df.columns
        assert len(df.drop(columns=[("Time", "mins")]).columns) == 9


class TestBatchScoping:
    def test_summary_only_includes_named_batch(self, two_batch_db):
        rows = list(csv.DictReader(
            io.StringIO(generate_summary_csv(two_batch_db, batch_id="batch_a"))))
        assert [float(r["fireload"]) for r in rows] == [400.0, 430.0, 460.0]

    def test_summary_excludes_errored_runs(self, two_batch_db):
        rows = list(csv.DictReader(
            io.StringIO(generate_summary_csv(two_batch_db, batch_id="batch_a"))))
        assert len(rows) == 3  # the 4th run in batch_a errored

    def test_wide_csv_only_includes_named_batch(self, two_batch_db):
        rows = list(csv.reader(io.StringIO(
            generate_wide_timeseries_csv(two_batch_db, "lofl_temp", batch_id="batch_b"))))
        assert rows[0] == ["Time", "Beam_0", "Beam_1"]
        assert rows[1] == ["mins", "°C", "°C"]

    def test_prot_beam_only_includes_named_batch(self, two_batch_db):
        rows = list(csv.DictReader(
            io.StringIO(generate_prot_beam_csv(two_batch_db, batch_id="batch_b"))))
        assert [float(r["Fireload"]) for r in rows] == [900.0, 930.0]

    def test_unscoped_export_covers_every_batch(self, two_batch_db):
        rows = list(csv.DictReader(io.StringIO(generate_summary_csv(two_batch_db))))
        assert len(rows) == 5  # 3 from A + 2 from B, error run excluded

    def test_unknown_batch_yields_header_only(self, two_batch_db):
        rows = list(csv.DictReader(
            io.StringIO(generate_summary_csv(two_batch_db, batch_id="nope"))))
        assert rows == []
