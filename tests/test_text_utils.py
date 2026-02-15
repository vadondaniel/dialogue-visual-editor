from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.core import text_utils


class TextUtilsTests(unittest.TestCase):
    def test_visible_length_counts_heart_and_ignores_control_codes(self) -> None:
        text = r"\C[2]abc♡\C[0]"
        self.assertEqual(text_utils.visible_length(text), 4)

    def test_normalize_control_code_word_case(self) -> None:
        normalized, replacements = text_utils.normalize_control_code_word_case(
            r"\c[2]x\N[1]\v[3]"
        )
        self.assertEqual(normalized, r"\C[2]x\N[1]\V[3]")
        self.assertEqual(replacements, 2)

    def test_wrap_lines_keep_breaks_splits_on_hyphen(self) -> None:
        wrapped = text_utils.wrap_lines_keep_breaks(["Demon-Lord"], 6)
        self.assertEqual(wrapped, ["Demon-", "Lord"])

    def test_smart_collapse_allows_comma_endings_when_enabled(self) -> None:
        lines = ["Keep going,", "please"]
        default_result = text_utils.smart_collapse_lines(lines, 30)
        comma_allowed = text_utils.smart_collapse_lines(
            lines,
            30,
            allow_comma_endings=True,
        )
        self.assertEqual(default_result, ["Keep going,", "please"])
        self.assertEqual(comma_allowed, ["Keep going, please"])

    def test_smart_collapse_respects_no_punctuation_flag(self) -> None:
        lines = ["No punctuation here", "next line"]
        collapse_default = text_utils.smart_collapse_lines(
            lines,
            60,
            collapse_if_no_punctuation=True,
        )
        keep_break = text_utils.smart_collapse_lines(
            lines,
            60,
            collapse_if_no_punctuation=False,
        )
        self.assertEqual(collapse_default, ["No punctuation here next line"])
        self.assertEqual(keep_break, ["No punctuation here", "next line"])

    def test_smart_collapse_ellipsis_lowercase_continuation(self) -> None:
        first = "This is quite long..."
        second = "and more"
        without_rule = text_utils.smart_collapse_lines(
            [first, second],
            30,
            allow_ellipsis_lowercase_continuation=False,
        )
        with_rule = text_utils.smart_collapse_lines(
            [first, second],
            30,
            allow_ellipsis_lowercase_continuation=True,
        )
        self.assertEqual(without_rule, [first, second])
        self.assertEqual(with_rule, [f"{first} {second}"])


if __name__ == "__main__":
    unittest.main()
