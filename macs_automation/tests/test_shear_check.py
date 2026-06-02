"""Tests for shear_check — degree-of-shear-connection check mirroring MACS+.

Reference: MACS+ CheckBeam (TABs.js:571) and its callers in TABs.js CheckBeams
and PrintP.js. A beam is flagged only when it is *internal* (edge flag 0) and,
for perimeter sides, *composite*, and its degree of shear connection falls below

    eta_min = 1 - (355 / fy) * (0.75 - 0.03 * span)

MACS+ uses this bare formula: NO 0.40 floor and NO span>25m cap. The check is
advisory — it does not change the pass/fail verdict.
"""

import sqlite3

import pytest

from macs_automation.shear_check import (
    check_beam,
    eta_min,
    flags_for_run,
    is_below_min,
    scan_db,
)


def _row(**overrides):
    """A run row mirroring real data: every beam internal+composite at 80%.

    Defaults produce NO flags (matches every batch in the real DBs). Spans
    differ (span1=9.0, span2=8.5) so tests can pin which span each side uses.
    """
    base = {
        "id": 1,
        "batch_id": "b1",
        "ush_con": 80.0, "u_sec_fy": 355, "span1": 9.0, "span2": 8.5,
        "side_a_sh_con": 80.0, "side_a_fy": 355, "side_a_edge": 0, "side_a_composite": 1,
        "side_b_sh_con": 80.0, "side_b_fy": 355, "side_b_edge": 0, "side_b_composite": 1,
        "side_c_sh_con": 80.0, "side_c_fy": 355, "side_c_edge": 0, "side_c_composite": 1,
        "side_d_sh_con": 80.0, "side_d_fy": 355, "side_d_edge": 0, "side_d_composite": 1,
    }
    base.update(overrides)
    return base


class TestEtaMin:
    def test_span_9_fy_355(self):
        # 1 - 1*(0.75 - 0.27) = 0.52
        assert eta_min(355, 9.0) == pytest.approx(0.52)

    def test_span_8_fy_355(self):
        # 1 - 1*(0.75 - 0.24) = 0.49
        assert eta_min(355, 8.0) == pytest.approx(0.49)

    def test_no_040_floor(self):
        """MACS+ does not clamp to 0.40 — span 4m gives 0.37, not 0.40."""
        assert eta_min(355, 4.0) == pytest.approx(0.37)

    def test_floor_value_is_just_the_formula(self):
        """span 5m happens to give exactly 0.40 — explains the colleague's '40%'."""
        assert eta_min(355, 5.0) == pytest.approx(0.40)

    def test_higher_grade_raises_limit(self):
        # 1 - (355/460)*(0.75 - 0.24)
        assert eta_min(460, 8.0) == pytest.approx(1 - (355 / 460) * 0.51)


class TestCheckBeam:
    def test_internal_below_limit_flagged(self):
        assert check_beam(0, 30.0, 355, 9.0) is True  # 0.30 < 0.52

    def test_internal_above_limit_not_flagged(self):
        assert check_beam(0, 80.0, 355, 9.0) is False  # 0.80 < 0.52 is False

    def test_edge_beam_never_flagged(self):
        """Edge beams (flag != 0) are exempt even far below the limit."""
        assert check_beam(1, 10.0, 355, 9.0) is False

    def test_string_flags_accepted(self):
        # MACS+ stores flags as strings ('0'/'1'); ours may be int or str.
        assert check_beam("0", 30.0, 355, 9.0) is True
        assert check_beam("1", 30.0, 355, 9.0) is False

    def test_boundary_is_strict_less_than(self):
        """sh_con exactly equal to the limit is NOT below it (MACS+ uses <)."""
        assert check_beam(0, 40.0, 355, 5.0) is False  # eta_min = 0.40


class TestIsBelowMin:
    def test_below(self):
        assert is_below_min(30.0, 355, 9.0) is True

    def test_above(self):
        assert is_below_min(80.0, 355, 9.0) is False


class TestFlagsForRun:
    def test_all_80_percent_no_flags(self):
        assert flags_for_run(_row()) == []

    def test_unprotected_below_flagged(self):
        flags = flags_for_run(_row(ush_con=30.0))
        names = [f["beam"] for f in flags]
        assert names == ["Unprotected"]
        assert flags[0]["sh_con"] == 30.0
        assert flags[0]["eta_min_pct"] == pytest.approx(52.0)

    def test_internal_composite_side_flagged(self):
        flags = flags_for_run(_row(side_b_sh_con=20.0))
        assert [f["beam"] for f in flags] == ["Side B"]

    def test_edge_side_not_flagged(self):
        """An edge perimeter beam below the limit is exempt (MACS+ CheckBeam)."""
        assert flags_for_run(_row(side_a_edge=1, side_a_sh_con=10.0)) == []

    def test_non_composite_side_not_flagged(self):
        """A non-composite internal side is not checked (CheckBeams gates on composite)."""
        assert flags_for_run(
            _row(side_c_composite=0, side_c_sh_con=10.0)
        ) == []

    def test_side_a_uses_span1_side_b_uses_span2(self):
        """Pin per-side span: A/C->span1, B/D->span2 (PrintP.js/CheckBeams)."""
        # span1=9 -> eta 0.52; span2=5 -> eta 0.40. sh_con 45% is below A's
        # limit (uses span1) but above B's limit (uses span2).
        row = _row(span1=9.0, span2=5.0,
                   side_a_sh_con=45.0, side_b_sh_con=45.0)
        names = [f["beam"] for f in flags_for_run(row)]
        assert "Side A" in names
        assert "Side B" not in names

    def test_multiple_beams_flagged(self):
        flags = flags_for_run(_row(ush_con=30.0, side_d_sh_con=15.0))
        assert sorted(f["beam"] for f in flags) == ["Side D", "Unprotected"]

    def test_missing_values_skipped_no_crash(self):
        assert flags_for_run(_row(ush_con=None)) == []
        assert flags_for_run(_row(span1=None, ush_con=30.0)) == []


class TestScanDb:
    def _make_db(self, path):
        conn = sqlite3.connect(path)
        cols = (
            "id INTEGER PRIMARY KEY, batch_id TEXT, "
            "ush_con REAL, u_sec_fy INTEGER, span1 REAL, span2 REAL, "
            "side_a_sh_con REAL, side_a_fy INTEGER, side_a_edge INTEGER, side_a_composite INTEGER, "
            "side_b_sh_con REAL, side_b_fy INTEGER, side_b_edge INTEGER, side_b_composite INTEGER, "
            "side_c_sh_con REAL, side_c_fy INTEGER, side_c_edge INTEGER, side_c_composite INTEGER, "
            "side_d_sh_con REAL, side_d_fy INTEGER, side_d_edge INTEGER, side_d_composite INTEGER"
        )
        conn.execute(f"CREATE TABLE runs ({cols})")
        return conn

    def _insert(self, conn, **row):
        full = _row(**row)
        keys = list(full.keys())
        conn.execute(
            f"INSERT INTO runs ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
            [full[k] for k in keys],
        )
        conn.commit()

    def test_clean_db_returns_nothing(self, tmp_path):
        p = tmp_path / "clean.db"
        conn = self._make_db(p)
        self._insert(conn, id=1)
        self._insert(conn, id=2)
        conn.close()
        assert scan_db(p) == []

    def test_flags_sublimit_run(self, tmp_path):
        p = tmp_path / "dirty.db"
        conn = self._make_db(p)
        self._insert(conn, id=1)                 # clean, 80%
        self._insert(conn, id=2, ush_con=20.0)   # sub-limit unprotected
        conn.close()
        results = scan_db(p)
        assert len(results) == 1
        assert results[0]["run_id"] == 2
        assert [f["beam"] for f in results[0]["flags"]] == ["Unprotected"]

    def test_filter_by_batch(self, tmp_path):
        p = tmp_path / "batched.db"
        conn = self._make_db(p)
        self._insert(conn, id=1, batch_id="x", ush_con=20.0)
        self._insert(conn, id=2, batch_id="y", ush_con=20.0)
        conn.close()
        results = scan_db(p, batch_id="y")
        assert [r["run_id"] for r in results] == [2]
