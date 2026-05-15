"""Tests for report.py — CSV + plot export module."""

import csv
import io
import zipfile
from pathlib import Path

import pytest

from macs_automation.db import ResultsDB
from macs_automation.report import (
    WIDE_CSV_COLUMNS,
    _factored_hot_range,
    _inputs_vary,
    _plot_timeseries,
    generate_prot_beam_csv,
    generate_plots,
    generate_report_zip,
    generate_summary_csv,
    generate_wide_timeseries_csv,
)
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
        assert sim_nums == list(range(1, 10))

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
        assert header[0] == "Time(min)"
        # Should have columns for each successful run
        assert len(header) >= 10  # Time + 9 runs

    def test_time_column_sorted(self, populated_db):
        result = generate_wide_timeseries_csv(populated_db, "mesh_temp")
        reader = csv.reader(io.StringIO(result))
        next(reader)  # skip header
        times = [float(row[0]) for row in reader]
        assert times == sorted(times)

    def test_values_present(self, populated_db):
        result = generate_wide_timeseries_csv(populated_db, "total_plate_capacity")
        reader = csv.reader(io.StringIO(result))
        next(reader)  # skip header
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
        for db_col, _ in WIDE_CSV_COLUMNS:
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
        zip_path = generate_report_zip(populated_db)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "summary.csv" in names
            assert "protected_beam_temps.csv" in names
            assert "beam_temperature.csv" in names
            assert "mesh_temperature.csv" in names
            assert "total_plate_capacity.csv" in names

    def test_zip_contains_plots(self, populated_db):
        zip_path = generate_report_zip(populated_db)
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
