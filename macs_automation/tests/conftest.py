"""Shared test fixtures for MACS+ automation tests."""

import sys

import pytest

from macs_automation.db import ResultsDB


def com_and_data_available():
    """Check if real COM engine and Data.xml are available.

    On 32-bit Python: requires MACS+ (Data.xml + COM registered).
    On 64-bit Python: requires Data.xml + 32-bit Python for the bridge (set PYTHON32 or use py -3-32).

    Returns:
        (available: bool, skip_reason: str | None)
        If available is False, skip_reason is a message for pytest.skip().
    """
    try:
        from macs_automation.data_loader import DEFAULT_DATA_PATH, load_data
        if not DEFAULT_DATA_PATH.exists():
            return False, (
                f"Data.xml not found at {DEFAULT_DATA_PATH}. "
                "Install MACS+ or set MACS_DATA_PATH."
            )
        load_data(DEFAULT_DATA_PATH)
    except Exception as e:
        return False, f"Data.xml load failed: {e}"

    if sys.maxsize <= 2**32:
        try:
            from macs_automation.engine import MACSEngine
            MACSEngine()
        except RuntimeError as e:
            return False, (
                f"COM engine not available: {e}. "
                "Install MACS+ (or use 32-bit Python if already installed)."
            )
        except Exception as e:
            return False, f"COM engine init failed: {type(e).__name__}: {e}"
        return True, None

    # 64-bit: need 32-bit Python for the bridge
    from macs_automation.engine import _find_python32
    if not _find_python32():
        return False, (
            "FRACOF COM is 32-bit only. On 64-bit Python, install 32-bit Python and set "
            "PYTHON32 to its path, or use the py launcher (e.g. py -3-32)."
        )
    return True, None


def _make_time_series(n_steps=12, uf_peak=0.85, capacity_base=700.0):
    """Generate synthetic time series data for a run.

    Returns list of dicts with n_steps entries spanning 0 to (n_steps-1)*5 minutes.
    UF ramps up to uf_peak at midpoint then declines. Temperatures ramp linearly.
    """
    ts = []
    mid = n_steps // 2
    for i in range(n_steps):
        t = i * 5.0  # 5-minute intervals
        # UF rises to peak at midpoint, then declines
        if i <= mid:
            uf = uf_peak * (i / mid) if mid > 0 else uf_peak
        else:
            uf = uf_peak * (1 - (i - mid) / (n_steps - mid))
        uf = max(uf, 0.01)

        frac = i / max(n_steps - 1, 1)
        ts.append({
            "time_step": i + 1,
            "time_min": t,
            "fire_temp": 20.0 + 980.0 * frac,
            "lofl_temp": 20.0 + 680.0 * frac,
            "mesh_temp": 20.0 + 480.0 * frac,
            "slabtop_temp": 20.0 + 180.0 * frac,
            "slabbot_temp": 20.0 + 380.0 * frac,
            "beam_hot_capacity": capacity_base * (1 - 0.6 * frac),
            "deflection": 5.0 + 115.0 * frac,
            "slab_yield": 2.0 + 8.0 * frac,
            "enhancement": 1.0 + 0.5 * frac,
            "slab_cap": 400.0 - 100.0 * frac,
            "total_plate_capacity": capacity_base * (1 - 0.5 * frac),
            "utilization_factor": round(uf, 4),
        })
    return ts


def _insert_populated_run(db, run_index, uf_max=0.6, error=None,
                          qf=500.0, window_percent=50.0):
    """Insert a single run with full params, outputs, and time series."""
    params = {
        "span1": 9.0, "span2": 9.0, "numbeam": 2,
        "SteelDeck": 1, "DeckName": "COFRAPLUS 60", "deck_type": "T",
        "deck_depth": 58.0, "deck_trug": 207.0, "deck_top": 106.0,
        "deck_bot": 62.0, "deck_stiff_height": 0.0,
        "conc_type": "NW", "conc_lambda": 1.0, "fck": 25.0, "slab_depth": 130.0,
        "mesh_type": "ST15C", "mesh_area_max": 142.0, "mesh_area_min": 142.0,
        "mesh_axis": 38.0, "mesh_strength": 500.0,
        "uSecSize": "IPE_500", "fy5": 355,
        "ush_con": 80.0,
        "SideASecSize": "IPE_500", "fy1": 355, "SideAEdgeFlag": 0,
        "SideACompoFlag": 1, "SideAsh_con": 80.0,
        "SideBSecSize": "IPE_500", "fy2": 355, "SideBEdgeFlag": 0,
        "SideBCompoFlag": 1, "SideBsh_con": 80.0,
        "SideCSecSize": "IPE_500", "fy3": 355, "SideCEdgeFlag": 0,
        "SideCCompoFlag": 1, "SideCsh_con": 80.0,
        "SideDSecSize": "IPE_500", "fy4": 355, "SideDEdgeFlag": 0,
        "SideDCompoFlag": 1, "SideDsh_con": 80.0,
        "lead_var_act": 5.0, "othr_var_act": 0.0, "cold_perm": 1.2,
        "slab_weight": 2.47, "lead_var_fac": 0.5, "othr_var_fac": 0.3,
        "method": "parametric", "time_limit": 60,
        "Lc": 10.0, "Bc": 10.0, "Hc": 3.0, "Hw": 2.0, "Lw": 5.0,
        "window_percent": window_percent, "qf": qf,
        "Bfac": 1500.0, "combustion_factor": 0.8, "growth_rate": 0.0117,
    }

    if error:
        return db.insert_run(params, error=error)

    time_series = _make_time_series(n_steps=12, uf_peak=uf_max)
    outputs = {
        "comp_failure": 0,
        "mb1_reqd": 100.0 + run_index * 5.0,
        "mb2_reqd": 200.0 + run_index * 3.0,
        "factored_hot": 3.7,
        "uf_max": uf_max,
        "max_temperature": 900.0 + run_index * 10.0,
        "max_deflection": 120.0 + run_index * 5.0,
        "max_slab_cap": 500.0,
        "max_beam_cap": 300.0,
        "max_total_cap": 800.0,
        "side_a_load_ratio": 0.30, "side_a_critical_temp": 620.0,
        "side_b_load_ratio": 0.40, "side_b_critical_temp": 756.0,
        "side_c_load_ratio": 0.35, "side_c_critical_temp": 620.0,
        "side_d_load_ratio": 0.32, "side_d_critical_temp": 623.0,
        "duration_ms": 1200.0 + run_index * 50.0,
        "time_series": time_series,
    }
    return db.insert_run(params, outputs=outputs)


@pytest.fixture
def populated_db(tmp_path):
    """Database with 10 runs: 8 pass (UF < 1.0), 1 fail (UF > 1.0), 1 error.

    Runs 1-8: successful, varying qf and window_percent, UF 0.3-0.9
    Run 9: fail (UF = 1.3)
    Run 10: error (COM error)
    """
    db_path = tmp_path / "populated.db"
    db = ResultsDB(db_path)

    # 8 passing runs with varying parameters
    for i in range(8):
        uf = 0.3 + i * 0.08  # 0.30, 0.38, 0.46, ..., 0.86
        qf = 400.0 + i * 30.0  # 400, 430, 460, ..., 610
        wp = 30.0 + i * 10.0  # 30, 40, 50, ..., 100
        _insert_populated_run(db, i, uf_max=round(uf, 2), qf=qf, window_percent=wp)

    # 1 failing run (UF > 1.0)
    _insert_populated_run(db, 8, uf_max=1.3, qf=800.0, window_percent=95.0)

    # 1 error run
    _insert_populated_run(db, 9, error="COMError: engine crashed")

    yield db
    db.close()
