"""Tests for building per-run .frc files for MACS+ PDF replay."""

import re

import pytest

from macs_automation.replay_frc import (
    FIRE_TAB,
    UnknownParameterError,
    build_replay_frc,
)
from macs_automation.frc_parser import parse_frc_string

FIXTURE = "macs_automation/tests/fixtures/atlantic_park_run00000.frc"


@pytest.fixture
def seed():
    with open(FIXTURE, encoding="utf-8-sig") as fh:
        return fh.read()


def _prop(xml, name):
    m = re.search(rf'Name="{re.escape(name)}"\s+Value="([^"]*)"', xml)
    return m.group(1) if m else None


class TestOverrides:
    def test_substitutes_a_varying_parameter(self, seed):
        out = build_replay_frc(seed, {"qf": 313.6648650498})
        assert _prop(out, "qf") == "313.6648650498"

    def test_substitutes_several(self, seed):
        out = build_replay_frc(seed, {"qf": 100.5, "window_percent": 42.0})
        assert _prop(out, "qf") == "100.5"
        # SQLite returns REAL for columns MACS wrote as integers; writing
        # "42.0" where MACS had "42" would also reach the printed report.
        assert _prop(out, "window_percent") == "42"

    def test_leaves_other_properties_untouched(self, seed):
        out = build_replay_frc(seed, {"qf": 1.0})
        assert _prop(out, "Bfac") == _prop(seed, "Bfac")
        assert _prop(out, "span1") == _prop(seed, "span1")
        assert _prop(out, "Method") == _prop(seed, "Method")

    def test_only_the_named_properties_and_the_landing_tab_change(self, seed):
        out = build_replay_frc(seed, {"qf": 1.0})
        changed = {
            n
            for n in re.findall(r'Name="([^"]+)"', seed)
            if _prop(out, n) != _prop(seed, n)
        }
        assert changed == {"qf", "CurrentTab"}

    def test_unknown_parameter_is_an_error(self, seed):
        # Silently doing nothing is the failure mode that produces 10,000
        # confident, identical, wrong PDFs.
        with pytest.raises(UnknownParameterError, match="not_a_real_param"):
            build_replay_frc(seed, {"not_a_real_param": 1})

    def test_empty_overrides_is_allowed(self, seed):
        out = build_replay_frc(seed, {})
        assert _prop(out, "qf") == _prop(seed, "qf")


class TestLandingTab:
    def test_rewrites_current_tab_away_from_fire(self, seed):
        assert _prop(seed, "CurrentTab") == str(FIRE_TAB)
        out = build_replay_frc(seed, {})
        assert _prop(out, "CurrentTab") == "1"
        assert _prop(out, "CurrentGroup") == "1"

    def test_refuses_to_land_on_the_fire_tab(self, seed):
        # Loading onto Fire & Analysis silently reverts the job to the ISO
        # curve via that tab's unload handler.
        with pytest.raises(ValueError, match="Fire"):
            build_replay_frc(seed, {}, landing_tab=FIRE_TAB)


class TestValueFormatting:
    def test_floats_round_trip_without_noise(self, seed):
        # A naive repr can emit 76.35204374199999, which MACS then prints
        # verbatim into the report.
        out = build_replay_frc(seed, {"window_percent": 76.352043742})
        assert _prop(out, "window_percent") == "76.352043742"

    def test_integers_do_not_gain_a_decimal_point(self, seed):
        out = build_replay_frc(seed, {"numbeam": 2})
        assert _prop(out, "numbeam") == "2"

    def test_percent_encodes_like_macs_does(self, seed):
        # MACS stores Value attributes URL-encoded (CurrentTabs is "0%7C7%7C8%7C1"),
        # so a raw & or " would corrupt the file rather than merely look odd.
        out = build_replay_frc(seed, {"ProjectName": 'A & B "x" <y>'})
        raw = _prop(out, "ProjectName")
        assert "&" not in raw and '"' not in raw and "<" not in raw
        assert parse_frc_string(out)["project"]["ProjectName"] == 'A & B "x" <y>'


class TestValidation:
    def test_rejects_a_non_frc_document(self):
        with pytest.raises(ValueError, match="signature"):
            build_replay_frc("<Root><Signature>NOPE</Signature></Root>", {})

    def test_result_still_parses_as_a_job_file(self, seed):
        out = build_replay_frc(seed, {"qf": 250.0, "window_percent": 30.0})
        parsed = parse_frc_string(out)
        assert parsed["params"]["qf"] == 250.0
        assert parsed["params"]["window_percent"] == 30.0
        # the fire model must survive - it is what the ISO-revert bug destroys
        assert parsed["params"]["method"] == "parametric"
