"""COM engine wrapper for the FRACOF calculation engine.

Uses explicit IDispatch.Invoke calls to work reliably through the
DllSurrogate (32-bit .NET COM in-proc server).

run_one_com() always spawns a per-calculation subprocess (com_runner) using
the parent interpreter (sys.executable). Same arch as parent — both 32-bit
in v1 — so a FRACOF crash kills only the runner, not the FastAPI sidecar.
"""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pythoncom

logger = logging.getLogger(__name__)

# Grade string to numeric fy mapping (from Calc.js Get_fy)
GRADE_TO_FY = {
    "235": 235, "275": 275, "355": 355, "35H": 355, "460": 460, "46H": 460,
}

# FRACOF engine version shipped with MACS+ 3.0.4 (Jan 2018), registered as
# SCTI11.FRACOF. This is the build our reference reports were generated with
# (the Atlantic Park Monte Carlo sweep, folder "MACS+_304").
#
# Older builds — notably 2.0.0.1 from the 2013 "Beta 2.06" MACS+ (registered as
# SCTI9.FRACOF) — use an earlier perimeter-beam critical-temperature routine that
# reads up to ~3 C HIGHER at mid utilisation (e.g. edge beam 634 vs 631 C). uf_max
# and factored load are unaffected, but critical temps will not match references
# generated with 3.0.4.
#
# Source note: the legacy EU site macsfire.eu still serves only the old Beta 2.06
# (v2.0.0.1) — do NOT use it. MACS+ 3.0.4 with v2.0.0.2 comes via ArcelorMittal
# Constructalia (free, registration) or the internal Monte Carlo bundle the
# reference reports were generated with (".../08. Monte Carlo TMA/MACS+_304").
RECOMMENDED_ENGINE_VERSION = (2, 0, 0, 2)


def _parse_engine_version(raw) -> Optional[tuple]:
    """Parse a dotted FRACOF version string (e.g. '2.0.0.1') into a tuple."""
    try:
        return tuple(int(p) for p in str(raw).strip().split("."))
    except (ValueError, AttributeError):
        return None


class COMProxy:
    """Thin wrapper that uses IDispatch.Invoke for all property/method access.

    This is needed because the FRACOF COM object runs through a DllSurrogate
    (32-bit .NET in-proc server accessed from 64-bit Python), which breaks
    win32com's late-binding attribute resolution.
    """

    def __init__(self, dispatch):
        object.__setattr__(self, "_disp", dispatch._oleobj_)
        object.__setattr__(self, "_cache", {})

    def _dispid(self, name: str) -> int:
        cache = object.__getattribute__(self, "_cache")
        if name not in cache:
            disp = object.__getattribute__(self, "_disp")
            try:
                cache[name] = disp.GetIDsOfNames(0, name)
            except Exception as e:
                raise RuntimeError(f"Unknown COM name {name!r}: {e}") from e
        return cache[name]

    def __setattr__(self, name: str, value):
        disp = object.__getattribute__(self, "_disp")
        dispid = self._dispid(name)
        disp.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, value)

    def __getattr__(self, name: str):
        disp = object.__getattribute__(self, "_disp")
        dispid = self._dispid(name)
        return disp.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYGET, 1)

    def call(self, name: str, *args):
        """Call a method by name."""
        disp = object.__getattribute__(self, "_disp")
        dispid = self._dispid(name)
        return disp.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, 0, *args)

    def call_indexed(self, name: str, index: int):
        """Call an indexed property/method like engine.uf(i)."""
        disp = object.__getattribute__(self, "_disp")
        dispid = self._dispid(name)
        return disp.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD | pythoncom.DISPATCH_PROPERTYGET, 1, index)


class MACSEngine:
    """Wrapper around the FRACOF COM object."""

    # ProgIDs for the FRACOF COM engine. Try SCTI11 (newer) first, then SCTI9 (older MACS+).
    PROG_IDS = ("SCTI11.FRACOF", "SCTI9.FRACOF")

    def __init__(self):
        import win32com.client
        from pywintypes import com_error
        raw = None
        last_error = None
        # -2147221164 = REGDB_E_CLASSNOTREG "Class not registered"
        # -2147221005 = CO_E_INVALID_OBJECT "Invalid class string" (ProgID not found / 32-bit vs 64-bit)
        retryable_codes = (-2147221164, -2147221005)
        for prog_id in self.PROG_IDS:
            try:
                raw = win32com.client.Dispatch(prog_id)
                break
            except com_error as e:
                if e.args[0] in retryable_codes:
                    last_error = e
                    continue
                raise
        if raw is None:
            raise RuntimeError(
                "FRACOF COM engine not available (Class not registered / Invalid class string). "
                "MACS+ must be installed; the installer registers SCTI11.FRACOF or SCTI9.FRACOF. "
                "If you see this with MACS+ installed, try 32-bit Python (the COM engine is 32-bit). "
                "Check: python -c \"import win32com.client; win32com.client.Dispatch('SCTI11.FRACOF')\""
            ) from last_error
        self.engine = COMProxy(raw)
        self.prog_id = prog_id
        self.engine_version = None
        self._warn_if_engine_outdated()

    def _warn_if_engine_outdated(self):
        """Log a warning if the resolved FRACOF engine predates v2.0.0.2.

        Older engines silently produce ~3 C-high perimeter-beam critical
        temperatures, so reports won't match references built with MACS+ 3.0.4.
        Non-fatal — the engine still runs.
        """
        try:
            self.engine_version = str(self.engine.GetVersion)
        except Exception:
            return  # version unavailable on this build; skip the check
        parsed = _parse_engine_version(self.engine_version)
        if parsed is not None and parsed < RECOMMENDED_ENGINE_VERSION:
            logger.warning(
                "FRACOF engine %s (via %s) predates the recommended %s shipped "
                "with MACS+ 3.0.4. Older builds report perimeter-beam critical "
                "temperatures up to ~3 C high at mid utilisation and will not "
                "reproduce reference reports generated with 3.0.4. Install MACS+ "
                "3.0.4 (registers SCTI11.FRACOF v2.0.0.2) via ArcelorMittal "
                "Constructalia or the internal MACS+_304 bundle - NOT macsfire.eu, "
                "which still serves the old Beta 2.06.",
                self.engine_version,
                self.prog_id,
                ".".join(map(str, RECOMMENDED_ENGINE_VERSION)),
            )

    def set_inputs(self, params: dict, sections_db: dict):
        """Set all input properties on the COM engine.

        Args:
            params: Dict of input parameters matching MACS+ naming.
            sections_db: Section database from data_loader for beam lookups.
        """
        eng = self.engine

        # Shear connection values: divide by 100 before setting (Calc.js lines 164-168)
        eng.ush_con = float(params.get("ush_con", 80)) / 100.0
        eng.SideAsh_con = float(params.get("SideAsh_con", 80)) / 100.0
        eng.SideBsh_con = float(params.get("SideBsh_con", 80)) / 100.0
        eng.SideCsh_con = float(params.get("SideCsh_con", 80)) / 100.0
        eng.SideDsh_con = float(params.get("SideDsh_con", 80)) / 100.0

        # Direct numeric properties (Calc.js lines 170-174)
        # Fire load qf: clamp to >= 1.0 MJ/m² — FRACOF thermal analysis is unstable for negative/zero.
        direct_props = [
            "numbeam", "time_limit",
            "SideAEdgeFlag", "SideBEdgeFlag", "SideCEdgeFlag", "SideDEdgeFlag",
            "SideACompoFlag", "SideBCompoFlag", "SideCCompoFlag", "SideDCompoFlag",
            "span1", "span2",
            "slab_depth", "fck",
            "deck_depth", "deck_trug", "deck_top", "deck_bot", "deck_stiff_height",
            "mesh_axis", "slab_weight",
            "mesh_area_max", "mesh_area_min", "mesh_strength",
            "lead_var_act", "lead_var_fac", "cold_perm", "othr_var_act", "othr_var_fac",
            "Lc", "Bc", "Hc", "Hw", "Lw",
            "window_percent", "qf", "Bfac", "combustion_factor", "growth_rate",
        ]
        for prop in direct_props:
            if prop in params:
                val = _to_numeric(params[prop])
                if prop == "qf":
                    val = max(1.0, float(val))  # avoid FRACOF thermal instability
                setattr(eng, prop, val)

        # If no steel deck, set deck_depth = 0 (Calc.js lines 181-184)
        if str(params.get("SteelDeck", "1")) == "0":
            eng.deck_depth = 0

        # Steel grade fy values (Calc.js lines 186-190)
        eng.SideA_fy = _get_fy(params.get("fy1", "355"))
        eng.SideB_fy = _get_fy(params.get("fy2", "355"))
        eng.SideC_fy = _get_fy(params.get("fy3", "355"))
        eng.SideD_fy = _get_fy(params.get("fy4", "355"))
        eng.USection_fy = _get_fy(params.get("fy5", "355"))

        # Concrete type: 0=NW, 1=LW (Calc.js line 192)
        conc_type_str = params.get("conc_type", "NW")
        eng.conc_type = 0 if conc_type_str == "NW" else 1

        # Concrete thermal conductivity (Calc.js line 194)
        eng.conc_lambda = _to_numeric(params.get("conc_lambda", 1))

        # Deck type: 0=Trapezoidal, 1=Re-entrant (Calc.js line 196)
        deck_type_str = params.get("deck_type", "T")
        eng.deck_type = 0 if deck_type_str == "T" else 1

        # Unprotected beam section dimensions (Calc.js line 197)
        _set_beam_data(
            eng, sections_db, params.get("uSecSize", "IPE_500"),
            "USectionDepth", "USectionWidth", "UWebThickness", "UFlangeThickness",
        )

        # Cellular beam data (Calc.js lines 199-200)
        _set_cell_beam_data(
            eng, sections_db, params,
            params.get("uSec1Size", "IPE_500"),
            "uSec1Depth", "uSec1Width", "uSec1WebThickness", "uSec1FlangeThickness",
        )
        _set_cell_beam_data(
            eng, sections_db, params,
            params.get("uSec2Size", "IPE_500"),
            "uSec2Depth", "uSec2Width", "uSec2WebThickness", "uSec2FlangeThickness",
        )

        # Cell diameter (Calc.js lines 201-210)
        if str(params.get("USecTypeFlag", "1")) == "1":
            eng.uSecDiam = 0
        else:
            eng.uSecDiam = _to_numeric(params.get("uSecDiam", 200))

        # Perimeter beam sections (Calc.js lines 211-214)
        _set_beam_data(
            eng, sections_db, params.get("SideASecSize", "IPE_500"),
            "SideASectionDepth", "SideASectionWidth", "SideAWebThickness", "SideAFlangeThickness",
        )
        _set_beam_data(
            eng, sections_db, params.get("SideBSecSize", "IPE_500"),
            "SideBSectionDepth", "SideBSectionWidth", "SideBWebThickness", "SideBFlangeThickness",
        )
        _set_beam_data(
            eng, sections_db, params.get("SideCSecSize", "IPE_500"),
            "SideCSectionDepth", "SideCSectionWidth", "SideCWebThickness", "SideCFlangeThickness",
        )
        _set_beam_data(
            eng, sections_db, params.get("SideDSecSize", "IPE_500"),
            "SideDSectionDepth", "SideDSectionWidth", "SideDWebThickness", "SideDFlangeThickness",
        )

    def run(self, method: str = "iso", udf_path: Optional[str] = None) -> dict:
        """Run the calculation.

        Args:
            method: 'parametric', 'iso', or 'udf'.
            udf_path: Path to UDF fire curve file (required if method='udf').

        Returns:
            Dict with all output values.
        """
        t0 = time.perf_counter()
        if method == "parametric":
            self.engine.call("AnalyseUsingParametricFire")
        elif method == "iso":
            self.engine.call("AnalyseISOFire")
        elif method == "udf":
            if not udf_path:
                raise ValueError("udf_path required for UDF analysis")
            self.engine.call("AnalyseUDF", udf_path)
        else:
            raise ValueError(f"Unknown method: {method}")

        duration_ms = (time.perf_counter() - t0) * 1000
        outputs = self._read_outputs()
        outputs["duration_ms"] = duration_ms
        return outputs

    def _get_output(self, *com_names: str, default: float = 0.0):
        """Try reading a COM property with several name variants (MACS+ version differences)."""
        eng = self.engine
        for name in com_names:
            try:
                return float(getattr(eng, name))
            except (RuntimeError, TypeError, AttributeError):
                continue
        return default

    def _read_outputs(self) -> dict:
        """Read all output values from the engine after a calculation."""
        eng = self.engine
        result = {}

        # Summary outputs (Calc.js lines 343-349); try name variants for MACS+ version differences
        result["comp_failure"] = int(eng.COMPFAILURE)
        result["mb1_reqd"] = self._get_output("Mb1_Reqd", "Mb1Reqd", "mb1_reqd")
        result["mb2_reqd"] = self._get_output("Mb2_Reqd", "Mb2Reqd", "mb2_reqd")
        result["factored_hot"] = self._get_output("factored_hot", "Factored_hot")

        # Perimeter beam results (Calc.js lines 407-414)
        result["side_a_load_ratio"] = float(eng.SideALoadRatio)
        result["side_a_critical_temp"] = float(eng.SideACriticalTemp)
        result["side_b_load_ratio"] = float(eng.SideBLoadRatio)
        result["side_b_critical_temp"] = float(eng.SideBCriticalTemp)
        result["side_c_load_ratio"] = float(eng.SideCLoadRatio)
        result["side_c_critical_temp"] = float(eng.SideCCriticalTemp)
        result["side_d_load_ratio"] = float(eng.SideDLoadRatio)
        result["side_d_critical_temp"] = float(eng.SideDCriticalTemp)

        # Time series data (Calc.js lines 388-402, 452-476)
        n = int(eng.time_intervals_count)
        time_series = []

        uf_max = -float("inf")
        max_temp = -float("inf")
        max_defl = -float("inf")
        max_slab_cap = -float("inf")
        max_beam_cap = -float("inf")
        max_total_cap = -float("inf")

        for i in range(1, n + 1):
            row = {
                "time_step": i,
                "time_min": float(eng.call_indexed("time_interval", i)),
                "fire_temp": float(eng.call_indexed("fire_temps", i)),
                "lofl_temp": float(eng.call_indexed("lofl_temp", i)),
                "mesh_temp": float(eng.call_indexed("mesh_temp", i)),
                "slabtop_temp": float(eng.call_indexed("slabtop_temp", i)),
                "slabbot_temp": float(eng.call_indexed("slabbot_temp", i)),
                "beam_hot_capacity": float(eng.call_indexed("beam_hot_capacity", i)),
                "deflection": float(eng.call_indexed("cgb_w", i)),
                "slab_yield": float(eng.call_indexed("slab_yield", i)),
                "enhancement": float(eng.call_indexed("enhancement", i)),
                "slab_cap": float(eng.call_indexed("slabcap", i)),
                "total_plate_capacity": float(eng.call_indexed("total_plate_capacity", i)),
                "utilization_factor": float(eng.call_indexed("uf", i)),
            }
            time_series.append(row)

            # Track extremes (CalcExtremes in Calc.js lines 453-476)
            uf_max = max(uf_max, row["utilization_factor"])
            for temp_key in ("lofl_temp", "mesh_temp", "slabtop_temp", "slabbot_temp", "fire_temp"):
                max_temp = max(max_temp, row[temp_key])
            max_defl = max(max_defl, row["deflection"])
            max_slab_cap = max(max_slab_cap, row["slab_cap"])
            max_beam_cap = max(max_beam_cap, row["beam_hot_capacity"])
            max_total_cap = max(max_total_cap, row["total_plate_capacity"])

        result["time_series"] = time_series
        result["uf_max"] = uf_max if uf_max > -float("inf") else 0.0
        result["max_temperature"] = max_temp if max_temp > -float("inf") else 0.0
        result["max_deflection"] = max_defl if max_defl > -float("inf") else 0.0
        result["max_slab_cap"] = max_slab_cap if max_slab_cap > -float("inf") else 0.0
        result["max_beam_cap"] = max_beam_cap if max_beam_cap > -float("inf") else 0.0
        result["max_total_cap"] = max_total_cap if max_total_cap > -float("inf") else 0.0

        return result


def _to_numeric(val):
    """Convert a value to float, handling strings."""
    if isinstance(val, (int, float)):
        return val
    try:
        return int(val)
    except (ValueError, TypeError):
        pass
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0


def _get_fy(grade) -> int:
    """Convert grade string to numeric fy value (Calc.js Get_fy)."""
    grade_str = str(grade)
    if grade_str in GRADE_TO_FY:
        return GRADE_TO_FY[grade_str]
    try:
        return int(grade_str)
    except ValueError:
        return 355


def _set_beam_data(eng, sections_db: dict, sec_size: str,
                   depth_prop: str, width_prop: str, web_prop: str, flange_prop: str):
    """Look up section dimensions and set on engine (Calc.js SetBeamData)."""
    sec = sections_db[sec_size]
    setattr(eng, depth_prop, sec["h"])
    setattr(eng, width_prop, sec["b"])
    setattr(eng, web_prop, sec["tw"])
    setattr(eng, flange_prop, sec["tf"])


def _set_cell_beam_data(eng, sections_db: dict, params: dict, sec_size: str,
                        depth_prop: str, width_prop: str, web_prop: str, flange_prop: str):
    """Set cellular beam data (Calc.js SetCellBeamData).

    For cellular beams, the depth comes from params (user-specified member depth),
    while width/web/flange come from the section database.
    """
    sec = sections_db[sec_size]
    depth_val = _to_numeric(params.get(depth_prop, sec["h"]))
    setattr(eng, depth_prop, depth_val)
    setattr(eng, width_prop, sec["b"])
    setattr(eng, web_prop, sec["tw"])
    setattr(eng, flange_prop, sec["tf"])


def run_one_com(params: dict, sections_db: dict) -> dict:
    """Run one FRACOF calculation in an isolated subprocess.

    Always spawns macs_automation.com_runner under the current interpreter
    (sys.executable). Same arch as parent — both 32-bit in v1 — so a FRACOF
    crash kills only the runner.

    Returns:
        Output dict from the engine (comp_failure, uf_max, time_series, etc.).

    Raises:
        RuntimeError: If the runner times out, returns no output, or signals
            an error in its JSON payload.
    """
    pkg_dir = Path(__file__).resolve().parent
    payload = json.dumps({"params": params, "sections_db": sections_db})
    # PyInstaller-frozen exes don't honour `-m module`; the bootloader passes
    # those args straight through to the app's argparse. In frozen builds,
    # spawn the same exe with `--com-runner` so app.main() dispatches into
    # com_runner.main() before argparse runs.
    if getattr(sys, "frozen", False):
        runner_argv = [sys.executable, "--com-runner"]
    else:
        runner_argv = [sys.executable, "-m", "macs_automation.com_runner"]
    try:
        proc = subprocess.run(
            runner_argv,
            input=payload,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=pkg_dir.parent,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("COM runner timed out")
    out_line = (proc.stdout or "").strip()
    if not out_line:
        err = (proc.stderr or "").strip() or "No output from COM runner"
        raise RuntimeError(f"COM runner failed: {err}")
    try:
        result = json.loads(out_line)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"COM runner invalid output: {e}")
    if "error" in result:
        raise RuntimeError(result["error"])
    return result
