from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.core.script_message_utils import (
    _GAME_MESSAGE_BACKGROUND_PREFIX_RE,
    _decode_js_string_term,
    _decode_js_string_literal,
    _encode_js_string_literal,
    _has_top_level_comma,
    _parse_game_message_arguments,
    _split_top_level_plus_expression,
    build_game_message_call,
    build_game_message_templated_call,
    parse_game_message_call,
    parse_game_message_templated_call,
    parse_game_message_set_background_call,
    parse_game_message_set_face_image_call,
    parse_game_message_set_position_type_call,
)


class ScriptMessageUtilsTests(unittest.TestCase):
    def test_decode_js_string_literal_supports_common_escape_sequences(self) -> None:
        decoded = _decode_js_string_literal(r"\r\t\b\f\v\0\x41\u3042\/\'\"")
        self.assertEqual(decoded, "\r\t\b\f\v\0Aあ/'\"")

    def test_decode_js_string_literal_keeps_trailing_backslash(self) -> None:
        self.assertEqual(_decode_js_string_literal("abc\\"), "abc\\")

    def test_decode_js_string_literal_falls_back_for_unknown_escape(self) -> None:
        self.assertEqual(_decode_js_string_literal(r"\q"), "q")
        self.assertEqual(_decode_js_string_literal(r"\x1"), "x1")

    def test_encode_js_string_literal_escapes_control_chars_and_quote(self) -> None:
        encoded = _encode_js_string_literal("\"\n\r\t\b\f\v\0\x01\\", '"')
        self.assertEqual(encoded, "\\\"\\n\\r\\t\\b\\f\\v\\0\\u0001\\\\")

    def test_parse_add_call_with_escaped_characters(self) -> None:
        parsed = parse_game_message_call(
            '$gameMessage.add("Line\\nTwo \\"Q\\"");'
        )
        self.assertEqual(parsed, ("add", 'Line\nTwo "Q"', '"'))

    def test_parse_set_speaker_name_single_quote(self) -> None:
        parsed = parse_game_message_call("$gameMessage.setSpeakerName('Hero');")
        self.assertEqual(parsed, ("setSpeakerName", "Hero", "'"))

    def test_parse_rejects_trailing_content(self) -> None:
        parsed = parse_game_message_call('$gameMessage.add("Line"); extra')
        self.assertIsNone(parsed)

    def test_parse_rejects_missing_quote_and_unterminated_escape(self) -> None:
        self.assertIsNone(parse_game_message_call("$gameMessage.add(123);"))
        self.assertIsNone(parse_game_message_call('$gameMessage.add("abc\\'))

    def test_parse_rejects_missing_closing_parenthesis(self) -> None:
        self.assertIsNone(parse_game_message_call('$gameMessage.add("Line";'))

    def test_parse_call_handles_whitespace_and_unterminated_literal(self) -> None:
        self.assertIsNone(parse_game_message_call("$gameMessage.add(   "))
        self.assertIsNone(parse_game_message_call('$gameMessage.add("abc'))
        self.assertEqual(
            parse_game_message_call('$gameMessage.add("x")   ;   '),
            ("add", "x", '"'),
        )

    def test_build_round_trip(self) -> None:
        built = build_game_message_call(
            "setSpeakerName",
            "O'Reilly",
            quote_char="'",
        )
        parsed = parse_game_message_call(built)
        self.assertEqual(parsed, ("setSpeakerName", "O'Reilly", "'"))

    def test_build_defaults_to_add_for_unknown_kind(self) -> None:
        built = build_game_message_call("unknown", "Hello")
        parsed = parse_game_message_call(built)
        self.assertEqual(parsed, ("add", "Hello", '"'))

    def test_parse_set_face_image_with_variable_args(self) -> None:
        parsed = parse_game_message_set_face_image_call(
            "$gameMessage.setFaceImage(face,$gameVariables.value(37));"
        )
        self.assertEqual(parsed, ("face", "$gameVariables.value(37)"))

    def test_parse_set_face_image_with_string_face(self) -> None:
        parsed = parse_game_message_set_face_image_call(
            '$gameMessage.setFaceImage("Actor1", 3);'
        )
        self.assertEqual(parsed, ("Actor1", "3"))

    def test_parse_set_face_image_handles_escaped_quotes_and_nested_parentheses(self) -> None:
        parsed = parse_game_message_set_face_image_call(
            '$gameMessage.setFaceImage("A\\\\\\"B", fn(1,(2)));'
        )
        self.assertEqual(parsed, ('A\\"B', "fn(1,(2))"))

    def test_parse_set_face_image_rejects_invalid_argument_forms(self) -> None:
        self.assertIsNone(
            parse_game_message_set_face_image_call('$gameMessage.setFaceImage("Actor1");')
        )
        self.assertIsNone(
            parse_game_message_set_face_image_call("$gameMessage.setFaceImage(,3);")
        )
        self.assertIsNone(
            parse_game_message_set_face_image_call('$gameMessage.setFaceImage("Actor1", );')
        )

    def test_parse_set_background_with_numeric_arg(self) -> None:
        parsed = parse_game_message_set_background_call(
            "$gameMessage.setBackground(1);"
        )
        self.assertEqual(parsed, "1")

    def test_parse_set_position_type_with_numeric_arg(self) -> None:
        parsed = parse_game_message_set_position_type_call(
            "$gameMessage.setPositionType(2);"
        )
        self.assertEqual(parsed, "2")

    def test_parse_background_and_position_reject_top_level_comma(self) -> None:
        self.assertIsNone(
            parse_game_message_set_background_call("$gameMessage.setBackground(1,2);")
        )
        self.assertIsNone(
            parse_game_message_set_position_type_call("$gameMessage.setPositionType(1,2);")
        )

    def test_parse_game_message_templated_add_call(self) -> None:
        parsed = parse_game_message_templated_call(
            '$gameMessage.add("\\\\C[2]\\\\n[3]\\\\C[0]は\\\\C[2]" + m + "\\\\C[0]の勧誘に成功した！");'
        )
        self.assertEqual(
            parsed,
            ("add", "\\C[2]\\n[3]\\C[0]は\\C[2]{{EXPR1}}\\C[0]の勧誘に成功した！", '"', ["m"]),
        )

    def test_build_game_message_templated_call_reuses_expression_terms(self) -> None:
        built = build_game_message_templated_call(
            "add",
            "A{{EXPR1}}B",
            '"',
            expression_terms=["m"],
        )
        self.assertEqual(built, '$gameMessage.add("A" + m + "B");')

    def test_build_game_message_templated_call_preserves_missing_placeholders(self) -> None:
        built = build_game_message_templated_call(
            "add",
            "Only text",
            '"',
            expression_terms=["m"],
        )
        self.assertEqual(built, '$gameMessage.add("Only text" + m);')

    def test_parse_game_message_templated_call_rejects_non_templated_or_comma_args(self) -> None:
        self.assertIsNone(
            parse_game_message_templated_call('$gameMessage.add("Only text");')
        )
        self.assertIsNone(parse_game_message_templated_call('$gameMessage.add("A", "B");'))

    def test_parse_game_message_templated_call_rejects_no_args_or_no_expression(self) -> None:
        self.assertIsNone(parse_game_message_templated_call("$gameMessage.add();"))
        self.assertIsNone(parse_game_message_templated_call('$gameMessage.add("A" + "B");'))
        self.assertIsNone(parse_game_message_templated_call("$gameMessage.add(foo + bar);"))

    def test_split_expression_and_argument_helpers_handle_nested_structures(self) -> None:
        terms = _split_top_level_plus_expression(
            '"A" + fn(1 + 2, arr[3]) + "B" + obj["k{1}"]'
        )
        self.assertEqual(terms, ['"A"', "fn(1 + 2, arr[3])", '"B"', 'obj["k{1}"]'])
        self.assertFalse(_has_top_level_comma('fn(1, 2)'))
        self.assertTrue(_has_top_level_comma('"A", "B"'))

    def test_split_expression_helper_handles_brace_depth(self) -> None:
        terms = _split_top_level_plus_expression('"A" + {k: 1} + "B"')
        self.assertEqual(terms, ['"A"', "{k: 1}", '"B"'])

    def test_decode_string_term_rejects_non_string_or_unbalanced_quote(self) -> None:
        self.assertIsNone(_decode_js_string_term("ab"))
        self.assertIsNone(_decode_js_string_term('"ab\''))

    def test_parse_arguments_helper_handles_nested_calls_and_trailing_text(self) -> None:
        args = _parse_game_message_arguments(
            "$gameMessage.setBackground(fn(1, 2));",
            _GAME_MESSAGE_BACKGROUND_PREFIX_RE,  # type: ignore[name-defined]
        )
        self.assertEqual(args, "fn(1, 2)")
        args_with_trailing = _parse_game_message_arguments(
            "$gameMessage.setBackground(1); trailing",
            _GAME_MESSAGE_BACKGROUND_PREFIX_RE,  # type: ignore[name-defined]
        )
        self.assertIsNone(args_with_trailing)

    def test_parse_arguments_helper_rejects_unclosed_and_handles_post_close_whitespace(self) -> None:
        self.assertIsNone(
            _parse_game_message_arguments(
                "$gameMessage.setBackground(fn(1,2);",
                _GAME_MESSAGE_BACKGROUND_PREFIX_RE,  # type: ignore[name-defined]
            )
        )
        self.assertEqual(
            _parse_game_message_arguments(
                "$gameMessage.setBackground(1)   ",
                _GAME_MESSAGE_BACKGROUND_PREFIX_RE,  # type: ignore[name-defined]
            ),
            "1",
        )

    def test_build_game_message_templated_call_handles_unknown_placeholder_index(self) -> None:
        built = build_game_message_templated_call(
            "unknown",
            "{{EXPR9}}",
            quote_char="x",
            expression_terms=["actualExpr"],
        )
        self.assertEqual(built, '$gameMessage.add("{{EXPR9}}" + actualExpr);')

    def test_build_game_message_templated_call_without_expression_terms_uses_plain_builder(self) -> None:
        built = build_game_message_templated_call(
            "setSpeakerName",
            "Hero",
            '"',
            expression_terms=[],
        )
        self.assertEqual(built, '$gameMessage.setSpeakerName("Hero");')


if __name__ == "__main__":
    unittest.main()
