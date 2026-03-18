from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dialogue_visual_editor.helpers.core.parser import (
    _collect_tyrano_implicit_dialogue_block,
    _extract_tyrano_config_assignment_value,
    _extract_tyrano_script_assignment_string_value,
    _coerce_tyrano_config_lines,
    _coerce_tyrano_script_chunks,
    _extract_tyrano_standalone_dialogue_marker,
    _extract_tyrano_tag_attribute_value,
    _find_matching_bracket_end,
    _group_tyrano_dialogue_text_items,
    _group_tyrano_text_items_by_page_break,
    _has_tyrano_dialogue_marker_near_window,
    is_plugins_js_data,
    _is_tyrano_choice_tag_line,
    _is_tyrano_conditional_dialogue_window,
    _is_tyrano_dialogue_block_end,
    _is_tyrano_dialogue_block_start,
    _is_tyrano_dialogue_text_line,
    _is_tyrano_flow_close_line,
    _is_tyrano_flow_open_line,
    _is_tyrano_iscript_end_line,
    _is_tyrano_iscript_start_line,
    _js_bracket_delta_outside_strings,
    _name_index_spec_for_file,
    _normalize_tyrano_script_string_key,
    _nearest_non_empty_line,
    _parse_plugins_js_source,
    _parse_tyrano_config_source,
    _parse_tyrano_script_source,
    _plugin_command_argument_part_is_non_meaningful,
    _plugin_command_argument_value_is_non_meaningful,
    _read_text_file_with_fallback_encodings,
    _replace_tyrano_attribute_line_breaks_with_newlines,
    _replace_tyrano_inline_line_breaks_with_newlines,
    _should_extract_tyrano_js_script_string,
    _safe_system_field_slug,
    _text_is_translatable_for_misc_extraction,
    _unescape_tyrano_tag_attribute_value,
    _json_path_label,
    split_tyrano_dialogue_line_and_suffix,
    _split_tyrano_inline_line_breaks,
    _split_tyrano_leading_indent,
    _tyrano_body_item_kind_for_line,
    _tyrano_flow_depth_delta,
    _tyrano_speaker_name_from_line,
    is_plugins_js_path,
    is_tyrano_config_data,
    is_tyrano_script_data,
    is_tyrano_config_path,
    is_tyrano_js_path,
    is_tyrano_script_path,
    load_plugins_js_file,
    plugins_js_source_from_data,
)


class ParserInternalCoverageTests(unittest.TestCase):
    def test_name_index_spec_for_file(self) -> None:
        self.assertEqual(_name_index_spec_for_file("actors.json")[0], "actor")
        self.assertEqual(_name_index_spec_for_file("CLASSES.JSON")[0], "class")
        self.assertEqual(_name_index_spec_for_file("items.json")[0], "item")
        self.assertIsNone(_name_index_spec_for_file("random.json"))

    def test_path_predicates(self) -> None:
        self.assertTrue(is_plugins_js_path(Path("plugins.js")))
        self.assertTrue(is_tyrano_script_path(Path("scene.KS")))
        self.assertTrue(is_tyrano_js_path(Path("script.js")))
        self.assertFalse(is_tyrano_js_path(Path("plugins.js")))
        self.assertTrue(is_tyrano_config_path(Path("config.tjs")))

    def test_find_matching_bracket_end_handles_inputs(self) -> None:
        self.assertIsNone(_find_matching_bracket_end("[a", 0))
        self.assertIsNone(_find_matching_bracket_end("[abc", 1))
        self.assertIsNone(_find_matching_bracket_end("abc", 0))
        self.assertEqual(_find_matching_bracket_end("[a[b]c]", 0), 6)
        self.assertEqual(_find_matching_bracket_end('["a[b]"]', 0), 7)

    def test_parse_plugins_js_source_valid_and_invalid(self) -> None:
        source = "var $plugins = [{\"name\": \"Alpha\"}];"
        parsed = _parse_plugins_js_source(source)
        self.assertEqual(parsed["__dve_plugins_js_marker__"], "plugins_js")
        self.assertEqual(parsed["__dve_plugins_js_array__"], [{"name": "Alpha"}])

        with self.assertRaises(ValueError):
            _parse_plugins_js_source("var x = {};")
        with self.assertRaises(ValueError):
            _parse_plugins_js_source("var $plugins = {\"name\": \"x\"};")
        with self.assertRaises(ValueError):
            _parse_plugins_js_source("var $plugins = [1, 2, ;")

    def test_load_and_validate_plugins_js_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plugins.js"
            path.write_text('var $plugins = [{"name": "Alpha"}];', encoding="utf-8")
            data = load_plugins_js_file(path)
        self.assertTrue(is_plugins_js_data(data))
        self.assertIn("[\n  {\n    \"name\": \"Alpha\"\n  }\n]", plugins_js_source_from_data(data))
        self.assertEqual(
            plugins_js_source_from_data(
                {
                    "__dve_plugins_js_marker__": "plugins_js",
                    "__dve_plugins_js_array__": [],
                }
            ),
            'var $plugins =\n[];\n',
        )

    def test_read_text_file_with_fallback_encodings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "legacy.txt"
            path.write_bytes("こんにちは".encode("cp932"))
            self.assertEqual(_read_text_file_with_fallback_encodings(path), "こんにちは")

            invalid = Path(tmpdir) / "invalid.bin"
            invalid.write_bytes(b"\xff")
            with patch.object(
                Path,
                "read_text",
                side_effect=UnicodeDecodeError("cp932", b"\xff", 0, 1, "invalid"),
            ):
                with self.assertRaises(UnicodeDecodeError):
                    _read_text_file_with_fallback_encodings(invalid)

    def test_tyrano_dialogue_line_classification(self) -> None:
        self.assertTrue(_is_tyrano_dialogue_block_start("[tb_start_text mode=1]"))
        self.assertTrue(_is_tyrano_dialogue_block_end("[_tb_end_text]"))
        self.assertTrue(_is_tyrano_dialogue_text_line("[名前]text"))
        self.assertFalse(_is_tyrano_dialogue_text_line("[if cond]"))
        self.assertFalse(_is_tyrano_dialogue_text_line("[p]"))
        self.assertFalse(_is_tyrano_dialogue_text_line("#speaker"))
        self.assertEqual(_tyrano_body_item_kind_for_line("#Hero"), "speaker")
        self.assertEqual(_tyrano_body_item_kind_for_line("本文"), "text")
        self.assertEqual(_tyrano_body_item_kind_for_line("@command"), "raw")
        self.assertEqual(_tyrano_speaker_name_from_line("# Hero "), "Hero")

    def test_tyrano_dialogue_temporary_helpers(self) -> None:
        self.assertEqual(
            split_tyrano_dialogue_line_and_suffix("A[p][r]"),
            ("A", "[p][r]"),
        )
        self.assertEqual(
            _replace_tyrano_inline_line_breaks_with_newlines("A[r]B"),
            "A\nB",
        )
        self.assertEqual(
            _split_tyrano_inline_line_breaks("A[r]B[r]C"),
            (["A", "B", "C"], ["[r]", "[r]", ""]),
        )
        self.assertEqual(
            _replace_tyrano_attribute_line_breaks_with_newlines("A\\nB[r]"),
            "A\nB\n",
        )
        self.assertEqual(_extract_tyrano_standalone_dialogue_marker("[r ]"), "[r ]")
        self.assertEqual(_split_tyrano_leading_indent("   文字"), ("   ", "文字"))

    def test_tyrano_flow_and_dialogue_window_helpers(self) -> None:
        lines = ["line1", "", "  [if a]", "A[p]", "", "[endif]", ""]
        self.assertEqual(_nearest_non_empty_line(lines, 2, -1), "  [if a]")
        self.assertEqual(_nearest_non_empty_line(lines, 1, 1), "  [if a]")
        self.assertTrue(_has_tyrano_dialogue_marker_near_window(lines, 2, 5))
        self.assertTrue(_is_tyrano_flow_open_line("[if cond]"))
        self.assertTrue(_is_tyrano_flow_close_line("[endif]"))
        self.assertFalse(_is_tyrano_iscript_start_line("A"))
        self.assertTrue(_is_tyrano_iscript_start_line("[iscript]"))
        self.assertTrue(_is_tyrano_iscript_end_line("[endscript]"))
        self.assertEqual(_tyrano_flow_depth_delta("[if cond]"), 1)
        self.assertEqual(_tyrano_flow_depth_delta("[else]"), 0)
        self.assertEqual(_tyrano_flow_depth_delta("[endif]"), -1)
        self.assertTrue(_is_tyrano_conditional_dialogue_window(lines, 3, 5))

    def test_tyrano_script_assignment_extraction(self) -> None:
        line = 'name: "Hero"'
        payload = _extract_tyrano_script_assignment_string_value(line)
        self.assertIsNotNone(payload)
        _, _, decoded, _quote, kind, key = payload
        self.assertEqual(kind, "object_property")
        self.assertEqual(key, "name")
        self.assertEqual(decoded, "Hero")

        payload = _extract_tyrano_script_assignment_string_value("f.ending = 'X'")
        self.assertIsNotNone(payload)
        _, _, decoded, _quote, kind, key = payload
        self.assertEqual(kind, "assignment")
        self.assertEqual(key, "f.ending")
        self.assertEqual(decoded, "X")
        self.assertIsNone(_extract_tyrano_script_assignment_string_value(123))

        self.assertTrue(_should_extract_tyrano_js_script_string(
            "object_property", "name", in_end_list_context=False
        ))
        self.assertFalse(_should_extract_tyrano_js_script_string(
            "object_property", "id", in_end_list_context=False
        ))
        self.assertTrue(_should_extract_tyrano_js_script_string(
            "object_property", "id", in_end_list_context=True
        ))
        self.assertFalse(_should_extract_tyrano_js_script_string(
            "assignment", "any", in_end_list_context=False
        ))
        self.assertEqual(_normalize_tyrano_script_string_key('"Nick"'), "nick")

    def test_tyrano_script_delta_and_grouping(self) -> None:
        self.assertEqual(_js_bracket_delta_outside_strings("a + [b]"), 0)
        text_items = [
            {"kind": "text", "line": "A"},
            {"kind": "text", "line": "B[p]"},
            {"kind": "raw", "line": ""},
            {"kind": "text", "line": "C"},
        ]
        self.assertEqual(
            _group_tyrano_dialogue_text_items(text_items),
            [[(0, "A"), (1, "B[p]")], [(3, "C")]],
        )
        self.assertEqual(
            _group_tyrano_text_items_by_page_break([(0, "A"), (1, "B[p]"), (2, "C")]),
            [[(0, "A"), (1, "B[p]")], [(2, "C")]],
        )

    def test_collect_implicit_tyrano_dialogue_block(self) -> None:
        source_lines = ["Hello[p]", "A[p]"]
        body_items, next_index = _collect_tyrano_implicit_dialogue_block(source_lines, 0)
        self.assertEqual(body_items[0], {"kind": "text", "line": "Hello[p]"})
        self.assertEqual(next_index, 2)

        no_marker = _collect_tyrano_implicit_dialogue_block(["[if a]", "B"], 0)
        self.assertIsNone(no_marker)

    def test_parse_tyrano_script_source_and_config_helpers(self) -> None:
        source = "\n".join(
            [
                "[tb_start_text mode=1 ]",
                "#Hero",
                "A[p]",
                "[_tb_end_text]",
                "[mylink text='選択' target='*A']",
            ]
        )
        parsed = _parse_tyrano_script_source(source)
        chunks = parsed["__dve_tyrano_script_chunks__"]
        self.assertEqual(chunks[0]["kind"], "dialogue_block")
        self.assertEqual(chunks[1]["kind"], "raw_line")

        assignment = _extract_tyrano_config_assignment_value('System.title = "World"', "System.title")
        self.assertIsNotNone(assignment)
        _, _, title, quote = assignment
        self.assertEqual(title, "World")
        self.assertEqual(quote, '"')
        tag_attr = _extract_tyrano_tag_attribute_value(
            '[glink text="A"]', "text")
        self.assertIsNotNone(tag_attr)
        self.assertIsNotNone(tag_attr[0])

    def test_parse_tyrano_config_source(self) -> None:
        source = ";debug\nSystem.title = \"Title\"\n;note\n"
        parsed = _parse_tyrano_config_source(source)
        self.assertTrue(parsed["__dve_tyrano_config_has_trailing_newline__"])
        self.assertEqual(parsed["__dve_tyrano_config_title_line_index__"], 1)

    def test_plugin_argument_filters(self) -> None:
        self.assertTrue(_plugin_command_argument_part_is_non_meaningful("true"))
        self.assertTrue(_plugin_command_argument_value_is_non_meaningful("true, false"))
        self.assertFalse(_plugin_command_argument_value_is_non_meaningful("abc, 12"))
        self.assertTrue(_is_tyrano_choice_tag_line("[mylink text='A' target='*A']"))
        self.assertFalse(_is_tyrano_choice_tag_line("[jump label]"))

    def test_plugin_and_script_data_validation_helpers(self) -> None:
        self.assertTrue(is_plugins_js_data(
            {
                "__dve_plugins_js_marker__": "plugins_js",
                "__dve_plugins_js_array__": [{"name": "A"}],
            }
        ))
        self.assertFalse(is_tyrano_script_data({"marker": "tyrano_script"}))
        self.assertTrue(
            is_tyrano_script_data(
                {
                    "__dve_tyrano_script_marker__": "tyrano_script",
                    "__dve_tyrano_script_chunks__": [],
                }
            )
        )
        self.assertFalse(is_tyrano_config_data({"__dve_tyrano_config_marker__": "x"}))
        self.assertTrue(
            is_tyrano_config_data(
                {
                    "__dve_tyrano_config_marker__": "tyrano_config",
                    "__dve_tyrano_config_lines__": [],
                }
            )
        )
        self.assertEqual(
            _coerce_tyrano_config_lines(
                {
                    "__dve_tyrano_config_marker__": "tyrano_config",
                    "__dve_tyrano_config_lines__": [1, "ok"],
                }
            ),
            ["ok"],
        )
        self.assertEqual(
            _coerce_tyrano_script_chunks(
                {
                    "__dve_tyrano_script_marker__": "tyrano_script",
                    "__dve_tyrano_script_chunks__": [{"kind": "raw_line"}, "bad"],
                }
            ),
            [{"kind": "raw_line"}],
        )

    def test_parser_helpers_roundtrip_and_normalization(self) -> None:
        parsed = _parse_tyrano_script_source("A\r\nB\r\n")
        self.assertEqual(parsed["__dve_tyrano_script_has_trailing_newline__"], True)
        self.assertEqual(parsed["__dve_tyrano_script_newline__"], "\r\n")

        parsed_config = _parse_tyrano_config_source("a\nSystem.title = ''\n")
        self.assertEqual(
            parsed_config["__dve_tyrano_config_title_line_index__"], 1
        )
        self.assertEqual(
            parsed_config["__dve_tyrano_config_title_span__"],
            (16, 16),
        )
        self.assertEqual(parsed_config["__dve_tyrano_config_title_quote__"], "'")

    def test_line_and_string_utility_helpers(self) -> None:
        self.assertEqual(_json_path_label(("a", 0, "b")), "a[0].b")
        self.assertEqual(_safe_system_field_slug("  Message/Title!! "), "Message_Title")
        self.assertEqual(_safe_system_field_slug("   "), "field")
        self.assertFalse(_text_is_translatable_for_misc_extraction("abc"))
        self.assertTrue(_text_is_translatable_for_misc_extraction("名前"))

    def test_tag_attribute_and_string_escaping_helpers(self) -> None:
        self.assertEqual(
            _unescape_tyrano_tag_attribute_value(r"\\"), "\\"
        )
        self.assertEqual(
            _replace_tyrano_attribute_line_breaks_with_newlines(r"A[r]B\nC"),
            "A\nB\nC",
        )
        self.assertEqual(
            _unescape_tyrano_tag_attribute_value(r"\\\"\\n"),
            chr(92) + '"' + chr(92) + "n",
        )
        self.assertIsNone(
            _extract_tyrano_tag_attribute_value('[button text=A target=*A]', "text")
        )
        self.assertIsNone(
            _extract_tyrano_tag_attribute_value("name=test", "not-present")
        )


if __name__ == "__main__":
    unittest.main()
