from __future__ import annotations

import unittest
from typing import Callable, cast

from dialogue_visual_editor.helpers.core import text_utils


class TextUtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._default_font_size = text_utils._DEFAULT_FONT_SIZE
        self._base_line_height = text_utils._BASE_LINE_HEIGHT
        self._default_variable_visible_length = text_utils._DEFAULT_VARIABLE_VISIBLE_LENGTH
        self._variable_visible_length_resolver = text_utils._VARIABLE_VISIBLE_LENGTH_RESOLVER
        self._default_name_visible_length = text_utils._DEFAULT_NAME_VISIBLE_LENGTH
        self._name_visible_length_resolver = text_utils._NAME_VISIBLE_LENGTH_RESOLVER
        self._capital_start_force_break = text_utils.CAPITAL_START_FORCE_BREAK

    def tearDown(self) -> None:
        text_utils._DEFAULT_FONT_SIZE = self._default_font_size
        text_utils._BASE_LINE_HEIGHT = self._base_line_height
        text_utils._DEFAULT_VARIABLE_VISIBLE_LENGTH = self._default_variable_visible_length
        text_utils._VARIABLE_VISIBLE_LENGTH_RESOLVER = self._variable_visible_length_resolver
        text_utils._DEFAULT_NAME_VISIBLE_LENGTH = self._default_name_visible_length
        text_utils._NAME_VISIBLE_LENGTH_RESOLVER = self._name_visible_length_resolver
        text_utils.CAPITAL_START_FORCE_BREAK = self._capital_start_force_break

    def test_next_message_font_size_for_token_paths(self) -> None:
        self.assertEqual(text_utils.next_message_font_size_for_token(r"\{", 90), 102)
        self.assertEqual(text_utils.next_message_font_size_for_token(r"\{", 120), 120)
        self.assertEqual(text_utils.next_message_font_size_for_token(r"\}", 30), 18)
        self.assertEqual(text_utils.next_message_font_size_for_token(r"\}", 10), 10)
        self.assertEqual(text_utils.next_message_font_size_for_token(r"\FS[44]", 10), 44)
        self.assertEqual(text_utils.next_message_font_size_for_token(r"\FS[abc]", 10), 10)

    def test_message_metrics_configuration_and_scaling(self) -> None:
        configured = text_utils.configure_message_text_metrics(0)
        self.assertEqual(configured, 1)
        self.assertEqual(text_utils.message_default_font_size(), 1)
        self.assertAlmostEqual(text_utils.message_font_scale_for_size(2), 2.0)
        self.assertEqual(text_utils.clamp_message_font_size(999), text_utils._MAX_FONT_SIZE)

    def test_variable_and_name_resolvers_handle_invalid_values(self) -> None:
        def _variable_raises(_variable_id: int) -> int:
            raise RuntimeError("fail")

        def _name_raises(_actor_id: int) -> int:
            raise RuntimeError("fail")

        text_utils.configure_variable_text_metrics(
            default_visible_length=3,
            resolver=cast(Callable[[int], int], lambda _id: "7"),
        )
        self.assertEqual(text_utils._variable_visible_length_for_id(1), 7)
        text_utils.configure_variable_text_metrics(default_visible_length=3, resolver=lambda _id: True)
        self.assertEqual(text_utils._variable_visible_length_for_id(1), 3)
        text_utils.configure_variable_text_metrics(
            default_visible_length=3,
            resolver=cast(Callable[[int], int], lambda _id: "bad"),
        )
        self.assertEqual(text_utils._variable_visible_length_for_id(1), 3)
        text_utils.configure_variable_text_metrics(default_visible_length=3, resolver=_variable_raises)
        self.assertEqual(text_utils._variable_visible_length_for_id(1), 3)

        text_utils.configure_name_text_metrics(
            default_visible_length=4,
            resolver=cast(Callable[[int], int], lambda _id: "6"),
        )
        self.assertEqual(text_utils._name_visible_length_for_id(1), 6)
        text_utils.configure_name_text_metrics(default_visible_length=4, resolver=lambda _id: True)
        self.assertEqual(text_utils._name_visible_length_for_id(1), 4)
        text_utils.configure_name_text_metrics(
            default_visible_length=4,
            resolver=cast(Callable[[int], int], lambda _id: "bad"),
        )
        self.assertEqual(text_utils._name_visible_length_for_id(1), 4)
        text_utils.configure_name_text_metrics(default_visible_length=4, resolver=_name_raises)
        self.assertEqual(text_utils._name_visible_length_for_id(1), 4)

    def test_visible_length_counts_token_visible_units(self) -> None:
        text_utils.configure_variable_text_metrics(default_visible_length=6)
        text_utils.configure_name_text_metrics(default_visible_length=9)
        self.assertEqual(text_utils.visible_length(r"\V[1]\I[2]\P[3]\G\N[4]"), 27)

    def test_first_overflow_char_index_handles_zero_width(self) -> None:
        self.assertIsNone(text_utils.first_overflow_char_index("", 0))
        self.assertEqual(text_utils.first_overflow_char_index("abc", 0), 0)

    def test_small_utility_helpers(self) -> None:
        self.assertEqual(text_utils.natural_sort_key("Map12A3"), ["map", 12, "a", 3, ""])
        self.assertEqual(text_utils.strip_control_tokens(""), "")
        self.assertEqual(text_utils.unique_preserve_order(["a", "b", "a"]), ["a", "b"])
        self.assertEqual(text_utils.split_lines_preserve_empty("A\r\nB\rC"), ["A", "B", "C"])
        self.assertEqual(text_utils.chunk_lines([], 0), [[""]])
        self.assertEqual(text_utils.chunk_lines(["a", "b"], 0), [["a", "b"]])
        self.assertEqual(text_utils.chunk_lines(["a", "b", "c"], 2), [["a", "b"], ["c"]])
        self.assertTrue(text_utils.is_command_entry({"code": 401, "parameters": ["x"]}))
        self.assertFalse(text_utils.is_command_entry({"code": 401}))
        self.assertEqual(text_utils.first_parameter_text({"parameters": ["x"]}), "x")
        self.assertEqual(text_utils.first_parameter_text({"parameters": [1]}, default="?"), "?")

    def test_row_budget_helpers(self) -> None:
        rows = text_utils.line_display_row_costs([r"\FS[40]Hello", "World"])
        self.assertGreaterEqual(rows[0], 1.0)
        kept, moved = text_utils.split_lines_by_row_budget(["A", "B"], 0.0)
        self.assertEqual(kept, ["A"])
        self.assertEqual(moved, ["B"])
        self.assertEqual(text_utils.chunk_lines_by_row_budget([], 2.0), [[""]])

    def test_wrapper_aliases_and_iso_timestamp(self) -> None:
        self.assertEqual(
            text_utils.wrap_text_to_width("A B C", 3),
            text_utils.wrap_text_word_aware("A B C", 3),
        )
        self.assertEqual(text_utils.collapse_lines_force(["A", "", "B"], 20), ["A", "", "B"])
        self.assertEqual(
            text_utils.smart_collapse_lines_space_efficient(["Name", "Line"], 20),
            text_utils.smart_collapse_lines(["Name", "Line"], 20),
        )
        timestamp = text_utils.now_utc_iso()
        self.assertIn("T", timestamp)

    def test_visible_length_counts_heart_and_ignores_control_codes(self) -> None:
        text = r"\C[2]abc♡\C[0]"
        self.assertEqual(text_utils.visible_length(text), 4)

    def test_normalize_control_code_word_case(self) -> None:
        normalized, replacements = text_utils.normalize_control_code_word_case(
            r"\c[2]x\N[1]\v[3]"
        )
        self.assertEqual(normalized, r"\C[2]x\N[1]\V[3]")
        self.assertEqual(replacements, 2)

    def test_visible_length_variable_token_allows_extra_args(self) -> None:
        base_length = text_utils.visible_length(r"\V[5]x")
        self.assertEqual(text_utils.visible_length(r"\V[5,4]x"), base_length)

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

    def test_wrap_lines_keep_breaks_handles_hungarian_accents(self) -> None:
        wrapped = text_utils.wrap_lines_keep_breaks(["árvíztűrő tükörfúrógép"], 12)
        self.assertEqual(wrapped, ["árvíztűrő", "tükörfúrógép"])

    def test_smart_collapse_ellipsis_lowercase_with_hungarian_accent(self) -> None:
        first = "Ez a mondat elég hosszú..."
        second = "és menjünk tovább"
        without_rule = text_utils.smart_collapse_lines(
            [first, second],
            46,
            allow_ellipsis_lowercase_continuation=False,
        )
        with_rule = text_utils.smart_collapse_lines(
            [first, second],
            46,
            allow_ellipsis_lowercase_continuation=True,
        )
        self.assertEqual(without_rule, [first, second])
        self.assertEqual(with_rule, [f"{first} {second}"])

    def test_trim_extra_ellipsis_runs_inside_text(self) -> None:
        updated, replacements = text_utils.trim_extra_ellipsis_runs(
            "Wait......... what.... now..."
        )
        self.assertEqual(updated, "Wait... what... now...")
        self.assertEqual(replacements, 2)

    def test_trim_extra_ellipsis_runs_preserves_pause_only_line(self) -> None:
        updated, replacements = text_utils.trim_extra_ellipsis_runs(".........")
        self.assertEqual(updated, ".........")
        self.assertEqual(replacements, 0)

    def test_trim_extra_ellipsis_runs_preserves_pause_only_with_control_codes(self) -> None:
        updated, replacements = text_utils.trim_extra_ellipsis_runs(r"\! ......... \C[2]")
        self.assertEqual(updated, r"\! ......... \C[2]")
        self.assertEqual(replacements, 0)


if __name__ == "__main__":
    unittest.main()
