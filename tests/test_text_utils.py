from __future__ import annotations

import unittest
from typing import Callable, cast

from helpers.core import text_utils


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

    def test_sentence_boundary_row_budget_split_prefers_sentence_end(self) -> None:
        lines = [
            r"\C[2]Speaker\C[0]",
            r"In the end, it's just a \C[14]trick\C[0] from a \C[27]girl\C[0].",
            r"How \C[27]cute\C[0] can it really be?",
            "Honestly, I'm looking forward to seeing",
            "what she'll do.",
        ]

        kept, moved = text_utils.split_lines_by_sentence_boundary_row_budget(
            lines,
            4.0,
            preserve_first_line=True,
        )

        self.assertEqual(kept, lines[:3])
        self.assertEqual(moved, lines[3:])

    def test_sentence_boundary_row_budget_split_falls_back_without_boundary(self) -> None:
        lines = ["Speaker", "No ending", "still continuing", "overflow"]

        kept, moved = text_utils.split_lines_by_sentence_boundary_row_budget(
            lines,
            3.0,
            preserve_first_line=True,
        )

        self.assertEqual(kept, lines[:3])
        self.assertEqual(moved, lines[3:])

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

    def test_visible_helpers_ignore_wait_dot_control_code(self) -> None:
        self.assertEqual(text_utils.strip_control_tokens(r"Wait\."), "Wait")
        self.assertEqual(text_utils.visible_length(r"\."), 0)
        self.assertFalse(text_utils._has_visible_nonspace_characters(r"\."))
        self.assertEqual(text_utils._last_visible_nonspace_character(r"Done\."), "e")

    def test_normalize_control_code_word_case(self) -> None:
        normalized, replacements = text_utils.normalize_control_code_word_case(
            r"\c[2]x\N[1]\v[3]"
        )
        self.assertEqual(normalized, r"\C[2]x\N[1]\V[3]")
        self.assertEqual(replacements, 2)

    def test_normalize_smart_quotes_converts_double_and_apostrophe(self) -> None:
        normalized, replacements = text_utils.normalize_smart_quotes(
            "\"Hello\", don't panic."
        )
        self.assertEqual(normalized, "\u201CHello\u201D, don\u2019t panic.")
        self.assertEqual(replacements, 3)

    def test_normalize_smart_quotes_handles_nested_quotes(self) -> None:
        normalized, replacements = text_utils.normalize_smart_quotes(
            "\"She said 'go'.\""
        )
        self.assertEqual(
            normalized,
            "\u201CShe said \u2018go\u2019.\u201D",
        )
        self.assertEqual(replacements, 4)

    def test_normalize_smart_quotes_uses_closing_context_for_punctuation(self) -> None:
        normalized, replacements = text_utils.normalize_smart_quotes(
            "He called it 'done'."
        )
        self.assertEqual(
            normalized,
            "He called it \u2018done\u2019.",
        )
        self.assertEqual(replacements, 2)

    def test_normalize_smart_quotes_preserves_control_token_spans(self) -> None:
        normalized, replacements = text_utils.normalize_smart_quotes(
            r"Say \N[1] says \"Hi\" and \C[2]don't\C[0] end"
        )
        self.assertEqual(
            normalized,
            "Say \\N[1] says \\\"Hi\\\" and \\C[2]don\u2019t\\C[0] end",
        )
        self.assertEqual(replacements, 1)

    def test_normalize_smart_quotes_noop_when_no_straight_quotes(self) -> None:
        normalized, replacements = text_utils.normalize_smart_quotes("No changes here.")
        self.assertEqual(normalized, "No changes here.")
        self.assertEqual(replacements, 0)

    def test_normalize_smart_quotes_keeps_single_quote_depth_when_apostrophe_inside(self) -> None:
        normalized, replacements = text_utils.normalize_smart_quotes("'I don't.'")
        self.assertEqual(normalized, "\u2018I don\u2019t.\u2019")
        self.assertEqual(replacements, 3)

    def test_normalize_smart_quotes_closes_single_quote_in_multiline_dialogue(self) -> None:
        normalized, replacements = text_utils.normalize_smart_quotes(
            "\"Heh. 'I ran into someone I didn't want to\n"
            "see first thing in the morning.'\n"
            "That is written all over your face.\""
        )
        self.assertEqual(
            normalized,
            "\u201CHeh. \u2018I ran into someone I didn\u2019t want to\n"
            "see first thing in the morning.\u2019\n"
            "That is written all over your face.\u201D",
        )
        self.assertEqual(replacements, 5)

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

    def test_trim_extra_ellipsis_runs_ignores_wait_dot_token_dot(self) -> None:
        updated, replacements = text_utils.trim_extra_ellipsis_runs(r"Wait\.....")
        self.assertEqual(updated, r"Wait\....")
        self.assertEqual(replacements, 1)

    def test_misc_private_coverage_paths(self) -> None:
        original_font_size = text_utils._DEFAULT_FONT_SIZE
        original_capital_policy = text_utils.CAPITAL_START_FORCE_BREAK
        text_utils._DEFAULT_FONT_SIZE = 0
        try:
            self.assertEqual(text_utils.message_font_scale_for_size(28), 1.0)
            self.assertEqual(text_utils._clamp_font_size(-5), text_utils._MIN_FONT_SIZE)
        finally:
            text_utils._DEFAULT_FONT_SIZE = original_font_size

        self.assertFalse(text_utils.looks_like_name_line(""))
        self.assertTrue(text_utils.looks_like_name_line(r"\N[1]"))
        self.assertFalse(text_utils.looks_like_name_line("abc"))
        self.assertFalse(text_utils.looks_like_name_line("This line has too many words for a name"))

        self.assertEqual(text_utils.trim_extra_ellipsis_runs("abc"), ("abc", 0))
        self.assertEqual(text_utils.preview_text("x" * 70, 66), "x" * 63 + "...")
        self.assertEqual(text_utils._unit_visible_value({"visible": "bad"}), 0.0)
        self.assertTrue(text_utils._unit_is_space({"text": " ", "visible": 1.0}))
        self.assertFalse(text_utils._unit_is_space({"text": " ", "visible": -1.0}))
        self.assertEqual(text_utils._find_last_visible_space_idx([]), None)
        self.assertEqual(
            text_utils._find_last_visible_space_idx(
                [
                    {"text": "A", "visible": 1.0, "is_newline": False},
                    {"text": " ", "visible": 1.0, "is_newline": False},
                    {"text": "B", "visible": 1.0, "is_newline": False},
                    {"text": "\t", "visible": 1.0, "is_newline": False},
                ],
            ),
            4,
        )

        self.assertTrue(text_utils._starts_with_capital_visible_letter("Abc"))
        self.assertFalse(text_utils._starts_with_capital_visible_letter("abc"))
        self.assertTrue(text_utils._starts_with_noncapital_visible_letter("abc"))
        self.assertFalse(text_utils._starts_with_noncapital_visible_letter("Abc"))

        self.assertTrue(text_utils._should_force_break_after_line("", 12, next_line="next"))
        self.assertFalse(
            text_utils._should_force_break_after_line(
                "Hello,",
                20,
                next_line="World",
                ending_policy="allow_comma",
            )
        )
        self.assertFalse(
            text_utils._should_force_break_after_line(
                "No punctuation yet",
                20,
                next_line="Next",
                ending_policy="no_punctuation_only",
            )
        )
        self.assertTrue(
            text_utils._should_force_break_after_line(
                "This;",
                20,
                next_line="next",
                ending_policy="default",
            )
        )
        self.assertFalse(
            text_utils._should_force_break_after_line(
                "and continue...",
                30,
                next_line="then",
                allow_ellipsis_lowercase_continuation=True,
            )
        )

        self.assertFalse(text_utils._should_force_break_after_line("A", 30, next_line="x"))

        text_utils.CAPITAL_START_FORCE_BREAK = True
        try:
            collapsed = text_utils._build_smart_collapse_body_text(
                ["Hello", "World"],
                120,
                ending_policy="default",
            )
            self.assertIn("\n", collapsed)
            self.assertEqual(collapsed, "Hello\nWorld")
        finally:
            text_utils.CAPITAL_START_FORCE_BREAK = original_capital_policy

    def test_wrap_text_word_aware_fallback_reprocessing_paths(self) -> None:
        original_parse_units_for_measure = text_utils.parse_units_for_measure

        text_utils.parse_units_for_measure = (
            lambda _text: [{"text": "Long", "visible": 10.0, "is_newline": False}]
        )
        try:
            self.assertEqual(
                text_utils.wrap_text_word_aware("ignored", 3),
                ["Long"],
            )
        finally:
            text_utils.parse_units_for_measure = original_parse_units_for_measure

        text_utils.parse_units_for_measure = (
            lambda _text: [
                {"text": "A", "visible": 1.0, "is_newline": False},
                {"text": " ", "visible": 1.0, "is_newline": False},
                {"text": "b", "visible": 1.0, "is_newline": False},
                {"text": "LongToken", "visible": 10.0, "is_newline": False},
            ]
        )
        try:
            self.assertEqual(
                text_utils.wrap_text_word_aware("ignored", 2),
                ["A", "b", "LongToken"],
            )
        finally:
            text_utils.parse_units_for_measure = original_parse_units_for_measure

    def test_additional_name_line_and_visible_length_edges(self) -> None:
        self.assertEqual(text_utils.visible_length("A\nB"), 2)
        self.assertFalse(text_utils.looks_like_name_line("   "))
        self.assertFalse(text_utils.looks_like_name_line(":"))
        self.assertFalse(text_utils.looks_like_name_line("A" * 41))
        self.assertFalse(text_utils.looks_like_name_line("Hero!"))
        self.assertFalse(text_utils.looks_like_name_line("1234"))
        self.assertTrue(text_utils.looks_like_name_line("A '"))
        self.assertFalse(text_utils.looks_like_name_line("A " + ("B" * 21)))
        self.assertTrue(text_utils.looks_like_name_line("King of Hearts"))
        self.assertFalse(text_utils.looks_like_name_line("Na@me"))

    def test_additional_overflow_and_unit_skip_paths(self) -> None:
        original_parse_units_for_measure = text_utils.parse_units_for_measure
        text_utils.parse_units_for_measure = (
            lambda _text: [{"text": "\n", "visible": 1.0, "is_newline": True}]
        )
        try:
            self.assertIsNone(text_utils.first_overflow_char_index("ignored", 1))
        finally:
            text_utils.parse_units_for_measure = original_parse_units_for_measure

        text_utils.parse_units_for_measure = (
            lambda _text: [{"text": "A", "visible": "bad", "is_newline": False}]
        )
        try:
            self.assertIsNone(text_utils.first_overflow_char_index("ignored", 1))
        finally:
            text_utils.parse_units_for_measure = original_parse_units_for_measure

    def test_additional_split_and_wrap_edge_paths(self) -> None:
        self.assertEqual(text_utils.normalize_control_code_word_case(""), ("", 0))
        self.assertEqual(text_utils.trim_extra_ellipsis_runs(""), ("", 0))
        self.assertEqual(text_utils.chunk_lines([], 2), [[""]])

        kept, moved = text_utils.split_lines_by_row_budget(["A", "B"], 0.5)
        self.assertEqual(kept, ["A"])
        self.assertEqual(moved, ["B"])

        row_chunks = text_utils.chunk_lines_by_row_budget(["A", "B", "C"], 1.0)
        self.assertEqual(row_chunks, [["A"], ["B"], ["C"]])

        self.assertEqual(text_utils.wrap_lines_hard_break([], 10), [""])
        self.assertEqual(text_utils.collapse_lines_join_paragraphs([], 10), [""])
        self.assertEqual(text_utils.smart_collapse_lines([], 10), [""])

    def test_additional_private_visible_character_helpers(self) -> None:
        self.assertTrue(text_utils._has_visible_nonspace_characters("\n \\C[1]A"))
        self.assertIsNone(text_utils._last_visible_nonspace_character(r"\C[1] \n"))
        self.assertFalse(text_utils._starts_with_capital_visible_letter("\nA"))
        self.assertTrue(text_utils._starts_with_capital_visible_letter(r"\C[1] A"))
        self.assertFalse(text_utils._starts_with_noncapital_visible_letter("\na"))
        self.assertTrue(text_utils._starts_with_noncapital_visible_letter(r"\C[1] a"))

    def test_additional_force_break_and_wrap_hard_break_paths(self) -> None:
        self.assertFalse(
            text_utils._should_force_break_after_line(
                "Wait...",
                30,
                next_line="next",
                allow_colon_triplet_endings=True,
            )
        )
        self.assertTrue(
            text_utils._should_force_break_after_line(
                "End)",
                30,
                next_line="next",
            )
        )

        original_has_visible = text_utils._has_visible_nonspace_characters
        original_last_visible = text_utils._last_visible_nonspace_character
        text_utils._has_visible_nonspace_characters = lambda _text: True
        text_utils._last_visible_nonspace_character = lambda _text: None
        try:
            self.assertFalse(
                text_utils._should_force_break_after_line(
                    "x",
                    30,
                    next_line="next",
                )
            )
        finally:
            text_utils._has_visible_nonspace_characters = original_has_visible
            text_utils._last_visible_nonspace_character = original_last_visible

        self.assertEqual(
            text_utils._wrap_text_hard_break("A\nB", 2),
            ["A", "B"],
        )

    def test_additional_defensive_parsing_and_split_fallback_paths(self) -> None:
        class _FakeMatch:
            def __init__(self, value: str) -> None:
                self._value = value

            def group(self, _index: int) -> str:
                return self._value

        class _FakeRegex:
            def __init__(self, value: str) -> None:
                self._value = value

            def match(self, _token: str) -> _FakeMatch:
                return _FakeMatch(self._value)

        original_font_regex = text_utils._FONT_SIZE_SET_TOKEN_RE
        original_variable_regex = text_utils._VARIABLE_TOKEN_RE
        original_name_regex = text_utils._NAME_TOKEN_RE
        original_line_display_row_costs = text_utils.line_display_row_costs

        try:
            text_utils._FONT_SIZE_SET_TOKEN_RE = cast(object, _FakeRegex("bad-int"))
            self.assertEqual(text_utils.next_message_font_size_for_token(r"\FS[1]", 22), 22)

            text_utils._VARIABLE_TOKEN_RE = cast(object, _FakeRegex("bad-id"))
            self.assertEqual(text_utils._variable_visible_units_for_token(r"\V[1]", 28), 0.0)

            text_utils._NAME_TOKEN_RE = cast(object, _FakeRegex("bad-id"))
            self.assertEqual(text_utils._name_visible_units_for_token(r"\N[1]", 28), 0.0)

            class _BrokenSplitString(str):
                def replace(self, _old: str, _new: str) -> "_BrokenSplitString":
                    return self

                def split(self, _sep: str | None = None, _maxsplit: int = -1) -> list[str]:
                    return []

            self.assertEqual(text_utils.split_lines_preserve_empty(_BrokenSplitString("x")), [""])

            class _TruthyEmptyIterable:
                def __bool__(self) -> bool:
                    return True

                def __iter__(self):
                    return iter(())

            kept, moved = text_utils.split_lines_by_row_budget(
                cast(list[str], _TruthyEmptyIterable()),
                2.0,
            )
            self.assertEqual(kept, [""])
            self.assertEqual(moved, [])

            text_utils.line_display_row_costs = lambda _lines: []
            kept, moved = text_utils.split_lines_by_row_budget(["A", "B"], 10.0)
            self.assertEqual(kept, ["A"])
            self.assertEqual(moved, ["B"])
        finally:
            text_utils._FONT_SIZE_SET_TOKEN_RE = original_font_regex
            text_utils._VARIABLE_TOKEN_RE = original_variable_regex
            text_utils._NAME_TOKEN_RE = original_name_regex
            text_utils.line_display_row_costs = original_line_display_row_costs

    def test_additional_wrap_and_last_visible_character_branches(self) -> None:
        original_parse_units_for_measure = text_utils.parse_units_for_measure
        original_unit_is_space = text_utils._unit_is_space

        try:
            text_utils.parse_units_for_measure = (
                lambda _text: [
                    {"text": "A", "visible": 1.0, "is_newline": False},
                    {"text": "\n", "visible": 1.0, "is_newline": True},
                ]
            )
            self.assertEqual(text_utils._last_visible_nonspace_character("ignored"), "A")

            text_utils.parse_units_for_measure = (
                lambda _text: [{"text": " ", "visible": 2.0, "is_newline": False}]
            )
            self.assertEqual(text_utils.wrap_text_word_aware("ignored", 1), [""])

            text_utils.parse_units_for_measure = (
                lambda _text: [
                    {"text": "A", "visible": 1.0, "is_newline": False},
                    {"text": "B", "visible": 1.0, "is_newline": False},
                    {"text": "C", "visible": 1.0, "is_newline": False},
                    {"text": "LONG", "visible": 5.0, "is_newline": False},
                ]
            )
            call_counts_word: dict[str, int] = {}

            def _fake_word_space(unit: dict[str, object]) -> bool:
                token = unit.get("text", "")
                if not isinstance(token, str):
                    return False
                call_counts_word[token] = call_counts_word.get(token, 0) + 1
                if token == "B":
                    return True
                if token == "C":
                    return call_counts_word[token] >= 2
                return False

            text_utils._unit_is_space = _fake_word_space
            wrapped = text_utils.wrap_text_word_aware("ignored", 3)
            self.assertTrue(len(wrapped) >= 2)
        finally:
            text_utils.parse_units_for_measure = original_parse_units_for_measure
            text_utils._unit_is_space = original_unit_is_space

        self.assertEqual(text_utils._wrap_text_hard_break(" A", 10), ["A"])
        self.assertEqual(text_utils._wrap_text_hard_break("A ", 1), ["A"])
        self.assertEqual(text_utils._wrap_text_hard_break("A- ", 2), ["A-"])

        try:
            text_utils.parse_units_for_measure = (
                lambda _text: [
                    {"text": "A", "visible": 1.0, "is_newline": False},
                    {"text": "B", "visible": 1.0, "is_newline": False},
                    {"text": "C", "visible": 1.0, "is_newline": False},
                    {"text": "LONG", "visible": 5.0, "is_newline": False},
                ]
            )
            call_counts_hard: dict[str, int] = {}

            def _fake_hard_space(unit: dict[str, object]) -> bool:
                token = unit.get("text", "")
                if not isinstance(token, str):
                    return False
                call_counts_hard[token] = call_counts_hard.get(token, 0) + 1
                if token == "B":
                    return True
                if token == "C":
                    return call_counts_hard[token] >= 3
                return False

            text_utils._unit_is_space = _fake_hard_space
            broken = text_utils._wrap_text_hard_break("ignored", 3)
            self.assertTrue(len(broken) >= 1)
        finally:
            text_utils.parse_units_for_measure = original_parse_units_for_measure
            text_utils._unit_is_space = original_unit_is_space

    def test_smart_collapse_handles_truthy_empty_iterable_input(self) -> None:
        class _TruthyEmptyLines:
            def __bool__(self) -> bool:
                return True

            def __iter__(self):
                return iter(())

        self.assertEqual(
            text_utils.smart_collapse_lines(
                cast(list[str], _TruthyEmptyLines()),
                20,
                infer_name_from_first_line=True,
            ),
            [""],
        )

    def test_wrap_text_hard_break_recomputes_break_index_for_remainder(self) -> None:
        original_parse_units_for_measure = text_utils.parse_units_for_measure
        original_unit_is_space = text_utils._unit_is_space
        try:
            text_utils.parse_units_for_measure = (
                lambda _text: [
                    {"text": "A", "visible": 1.0, "is_newline": False},
                    {"text": " ", "visible": 1.0, "is_newline": False},
                    {"text": "X", "visible": 1.0, "is_newline": False},
                    {"text": "B", "visible": 1.0, "is_newline": False},
                    {"text": "C", "visible": 1.0, "is_newline": False},
                ]
            )
            b_calls = 0

            def _fake_space(unit: dict[str, object]) -> bool:
                nonlocal b_calls
                token = unit.get("text", "")
                if token == " ":
                    return True
                if token == "B":
                    b_calls += 1
                    return b_calls >= 2
                return False

            text_utils._unit_is_space = _fake_space
            self.assertEqual(text_utils._wrap_text_hard_break("ignored", 4), ["A", "XBC"])
        finally:
            text_utils.parse_units_for_measure = original_parse_units_for_measure
            text_utils._unit_is_space = original_unit_is_space


if __name__ == "__main__":
    unittest.main()
