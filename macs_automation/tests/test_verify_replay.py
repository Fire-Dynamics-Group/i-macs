"""Tests for the replay verifier's differential mode.

Silent printing (PrintMaster.Print with the prompt argument false) replaces a
UI-driven print, so the question that matters is not "does this PDF look sane"
but "is it the same report the dialog route produced". These cover the text
comparison that answers it - everything except the printed timestamp must match.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load_module():
    path = REPO / "tools/macs_replay/verify_replay.py"
    spec = importlib.util.spec_from_file_location("verify_replay", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify_replay = _load_module()


STAMPED = "Client company:Winvic Construction Limited Date: 30 July 2026, 19:32"


class TestNormalise:
    def test_masks_the_printed_timestamp(self):
        a = verify_replay.normalise([STAMPED])
        b = verify_replay.normalise(["Client company:Winvic Construction Limited Date: 31 July 2026, 09:01"])
        assert a == b

    def test_keeps_the_rest_of_the_line(self):
        assert "Winvic Construction Limited" in verify_replay.normalise([STAMPED])[0]

    def test_leaves_ordinary_lines_alone(self):
        assert verify_replay.normalise(["Section size: UB 356x127x33"]) == [
            "Section size: UB 356x127x33"
        ]

    def test_ignores_trailing_whitespace(self):
        assert verify_replay.normalise(["Fire load: 570  "]) == verify_replay.normalise(["Fire load: 570"])

    def test_masks_a_single_digit_hour(self):
        a = verify_replay.normalise(["Date: 1 July 2026, 9:01"])
        b = verify_replay.normalise(["Date: 31 December 2026, 23:59"])
        assert a == b


class TestTextDifferences:
    def test_identical_reports_have_none(self):
        lines = ["Fire load: 570", "Section size: UB 356x127x33"]
        assert verify_replay.text_differences(lines, list(lines)) == []

    def test_a_differing_timestamp_is_not_a_difference(self):
        assert verify_replay.text_differences(
            [STAMPED], ["Client company:Winvic Construction Limited Date: 31 July 2026, 09:01"]
        ) == []

    def test_a_dropped_label_is_reported(self):
        # The real regression: MACS hides the "Section size:" label after it
        # calls Print, so a print issued later loses it.
        diff = verify_replay.text_differences(
            ["Section size: UB 356x127x33"], ["UB 356x127x33"]
        )
        assert diff
        assert any("Section size:" in line for line in diff)

    def test_a_changed_number_is_reported(self):
        diff = verify_replay.text_differences(["Fire load: 570"], ["Fire load: 511"])
        assert any("511" in line for line in diff)

    def test_an_extra_line_is_reported(self):
        diff = verify_replay.text_differences(["a", "b"], ["a", "b", "c"])
        assert any(line.startswith("+") and "c" in line for line in diff)

    def test_a_missing_line_is_reported(self):
        diff = verify_replay.text_differences(["a", "b", "c"], ["a", "c"])
        assert any(line.startswith("-") and "b" in line for line in diff)

    def test_difference_output_is_bounded(self):
        # A wholly wrong PDF must not print thousands of lines into a batch log.
        diff = verify_replay.text_differences([f"line {i}" for i in range(500)], [])
        assert len(diff) <= verify_replay.MAX_DIFF_LINES
