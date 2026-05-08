"""Tests for compute_status — combined slab/beam/composite pass-fail logic."""

from macs_automation.status import compute_status


def _row(**overrides):
    """Build a run row with sensible all-passing defaults; override per test."""
    base = {
        "error": None,
        "uf_max": 0.5,
        "comp_failure": 0,
        "side_a_load_ratio": 0.3,
        "side_b_load_ratio": 0.4,
        "side_c_load_ratio": 0.35,
        "side_d_load_ratio": 0.32,
    }
    base.update(overrides)
    return base


class TestOverallPass:
    def test_all_pass(self):
        s = compute_status(_row())
        assert s["overall_pass"] is True

    def test_slab_uf_fails(self):
        s = compute_status(_row(uf_max=1.05))
        assert s["overall_pass"] is False

    def test_slab_uf_at_limit_passes(self):
        s = compute_status(_row(uf_max=1.0))
        assert s["overall_pass"] is True

    def test_side_a_load_ratio_fails(self):
        s = compute_status(_row(side_a_load_ratio=1.4))
        assert s["overall_pass"] is False

    def test_side_b_load_ratio_fails(self):
        s = compute_status(_row(side_b_load_ratio=1.01))
        assert s["overall_pass"] is False

    def test_side_c_load_ratio_fails(self):
        s = compute_status(_row(side_c_load_ratio=2.0))
        assert s["overall_pass"] is False

    def test_side_d_load_ratio_fails(self):
        s = compute_status(_row(side_d_load_ratio=1.5))
        assert s["overall_pass"] is False

    def test_comp_failure_one_fails(self):
        s = compute_status(_row(comp_failure=1))
        assert s["overall_pass"] is False

    def test_comp_failure_zero_passes(self):
        s = compute_status(_row(comp_failure=0))
        assert s["overall_pass"] is True

    def test_null_side_ratios_skipped(self):
        """A side that wasn't analyzed (NULL ratio) shouldn't drag the run to FAIL."""
        s = compute_status(_row(
            side_a_load_ratio=None, side_b_load_ratio=None,
            side_c_load_ratio=None, side_d_load_ratio=None,
        ))
        assert s["overall_pass"] is True

    def test_error_row_returns_none(self):
        """An error run has no meaningful pass/fail — overall_pass is None."""
        s = compute_status(_row(error="COMError: engine crashed"))
        assert s["overall_pass"] is None

    def test_missing_uf_max_returns_none(self):
        """If we don't have uf_max we can't say either way."""
        s = compute_status(_row(uf_max=None))
        assert s["overall_pass"] is None


class TestChecksList:
    def test_slab_check_present(self):
        s = compute_status(_row())
        names = [c["name"] for c in s["checks"]]
        assert "Slab UF" in names

    def test_composite_check_present(self):
        s = compute_status(_row())
        names = [c["name"] for c in s["checks"]]
        assert "Composite section" in names

    def test_all_four_sides_present_when_defined(self):
        s = compute_status(_row())
        names = [c["name"] for c in s["checks"]]
        for side in ("A", "B", "C", "D"):
            assert f"Side {side} beam load" in names

    def test_null_side_omitted_from_checks(self):
        s = compute_status(_row(side_a_load_ratio=None))
        names = [c["name"] for c in s["checks"]]
        assert "Side A beam load" not in names
        assert "Side B beam load" in names

    def test_failing_check_marked_pass_false(self):
        s = compute_status(_row(side_a_load_ratio=1.5))
        side_a = next(c for c in s["checks"] if c["name"] == "Side A beam load")
        assert side_a["pass"] is False
        assert side_a["value"] == 1.5

    def test_passing_check_marked_pass_true(self):
        s = compute_status(_row())
        slab = next(c for c in s["checks"] if c["name"] == "Slab UF")
        assert slab["pass"] is True

    def test_error_row_has_empty_checks(self):
        s = compute_status(_row(error="boom"))
        assert s["checks"] == []
