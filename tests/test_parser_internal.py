from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers.core.parser import (
    _append_tyrano_standalone_marker_to_previous_text,
    _collect_tyrano_implicit_dialogue_block,
    _collect_choice_branch_entries,
    _collect_script_block_entries,
    _build_json_text_segment,
    _build_map_display_name_segment,
    _build_note_text_segments,
    _build_plugin_command_text_segments_for_entry,
    _build_plugins_text_segments,
    _build_tyrano_choice_segments,
    _build_tyrano_dialogue_segments,
    _choice_lines_from_code102,
    _extract_tyrano_config_assignment_value,
    _extract_tyrano_script_assignment_string_value,
    _coerce_tyrano_config_lines,
    _coerce_tyrano_script_chunks,
    _build_tyrano_script_string_segments,
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
    _build_tyrano_tag_text_segments,
    _build_system_text_segments,
    _name_index_spec_for_file,
    _normalize_tyrano_choice_text_for_editor,
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
    parse_dialogue_data,
    parse_dialogue_file,
    tyrano_config_source_from_data,
    tyrano_config_title_from_data,
    tyrano_script_source_from_data,
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

    def test_build_tyrano_script_string_segments_javascript_owner_and_end_list(self) -> None:
        path = Path("scene.js")
        chunks = [
            {"kind": "raw_line", "line": "CHARA = {"},
            {"kind": "raw_line", "line": "name: 'Rin'"},
            {"kind": "raw_line", "line": "end_list = ["},
            {"kind": "raw_line", "line": "  { id: '双子', name: 'Mio' },"},
            {"kind": "raw_line", "line": "]"},
            {"kind": "raw_line", "line": "fullName: 'Luna'"},
            {"kind": "raw_line", "line": "};"},
            {"kind": "raw_line", "line": "id: 'ignore'"},
        ]
        data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": chunks,
            "__dve_tyrano_script_newline__": "\n",
            "__dve_tyrano_script_has_trailing_newline__": True,
        }

        segments = _build_tyrano_script_string_segments(path, data)
        self.assertEqual(len(segments), 3)
        self.assertEqual([segment.lines for segment in segments], [["Rin"], ["双子"], ["Luna"]])
        self.assertEqual(
            [getattr(segment, "tyrano_tag_text_join_mode", "") for segment in segments],
            ["script_string", "script_string_end_id", "script_string"],
        )
        self.assertIn("CHARA.name", segments[0].context)
        self.assertIn("END_LIST[1].id", segments[1].context)

        filtered = _build_tyrano_script_string_segments(
            path=path,
            data=data,
            excluded_chunk_indexes={5},
        )
        self.assertEqual(len(filtered), 2)
        self.assertEqual([segment.lines for segment in filtered], [["Rin"], ["双子"]])

    def test_build_tyrano_script_string_segments_collects_iscript_assignments(self) -> None:
        path = Path("scene.ks")
        data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": [
                {"kind": "raw_line", "line": "[iscript]"},
                {"kind": "raw_line", "line": "mp.name = 'タイトル'"},
                {"kind": "raw_line", "line": "f.ending = '双子'"},
                {"kind": "raw_line", "line": "[endscript]"},
                {"kind": "raw_line", "line": "f.ending = '外側の行'"},
            ],
            "__dve_tyrano_script_newline__": "\n",
            "__dve_tyrano_script_has_trailing_newline__": True,
        }

        segments = _build_tyrano_script_string_segments(path, data)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].lines, ["タイトル"])
        self.assertEqual(segments[1].lines, ["双子"])
        self.assertEqual(
            [segment.tyrano_tag_text_join_mode for segment in segments],
            ["script_string", "script_string_end_id_ref"],
        )
        self.assertIn("f.ending -> END_LIST.id", segments[1].context)

    def test_tyrano_choice_and_tag_builder_indexes(self) -> None:
        path = Path("scene.ks")
        chunks = [
            {"kind": "raw_line", "line": '[glink text="Choice 1" target="*A"]'},
            {"kind": "raw_line", "line": '[mylink text="Choice 2" target="*B"]'},
            {"kind": "raw_line", "line": '[jump target="*C"]'},
            {"kind": "raw_line", "line": '[button text="Support" target="*D"]'},
        ]
        data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": chunks,
            "__dve_tyrano_script_newline__": "\n",
            "__dve_tyrano_script_has_trailing_newline__": True,
        }

        choice_segments, choice_chunk_indexes = _build_tyrano_choice_segments(path, data)
        self.assertEqual(len(choice_segments), 1)
        self.assertEqual(choice_segments[0].lines, ["Choice 1", "Choice 2"])
        self.assertEqual(choice_chunk_indexes, {0, 1})

        tag_segments = _build_tyrano_tag_text_segments(
            path=path,
            data=data,
            excluded_chunk_indexes=choice_chunk_indexes,
        )
        self.assertEqual(len(tag_segments), 1)
        self.assertEqual(tag_segments[0].lines, ["Support"])

    def test_parse_dialogue_data_parses_generic_command_and_plugin_lists(self) -> None:
        path = Path("Random.json")
        data = [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Hero"]},
            {"code": 401, "indent": 0, "parameters": ["First line"]},
            {"code": 102, "indent": 0, "parameters": [["A", "B"], 0, 0, 2, 0]},
            {"code": 402, "indent": 0, "parameters": [0, "A"]},
            {"code": 402, "indent": 0, "parameters": [1, "B"]},
            {"code": 404, "indent": 0, "parameters": []},
            {
                "code": 357,
                "indent": 0,
                "parameters": [
                    "DTextPicture",
                    "dText",
                    "文字列",
                    {
                        "text": "\\i[7]\\C[27]テキスト\\C[0]",
                        "flag": "false",
                        "align": "left",
                        "windowColor": "#ff99ff",
                        "num": "12",
                        "payload": "補助テキスト",
                    },
                ],
            },
            {
                "code": 355,
                "indent": 0,
                "parameters": [
                    "$gameMessage.setSpeakerName(\"Narr\")"
                ],
            },
            {"code": 655, "indent": 0, "parameters": ['$gameMessage.add("Line")']},
            {"code": 655, "indent": 0, "parameters": ["$gameMessage.setSpeakerName(\"Narr\")"]},
            {"code": 655, "indent": 0, "parameters": ["$gameMessage.setFaceImage('顔', 2)"]},
            {"code": 655, "indent": 0, "parameters": ["$gameMessage.setBackground(1)"]},
            {"code": 655, "indent": 0, "parameters": ["$gameMessage.setPositionType(3)"]},
        ]

        session = parse_dialogue_data(path, data)
        kinds = [segment.segment_kind for segment in session.segments]
        self.assertEqual(
            kinds,
            ["dialogue", "choice", "plugin_command_text", "plugin_command_text", "script_message"],
        )

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "dialogue"
        )
        self.assertEqual(dialogue_segment.lines, ["First line"])

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        self.assertEqual(choice_segment.lines, ["A", "B"])

        plugin_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "plugin_command_text"
        ]
        self.assertEqual(len(plugin_segments), 2)
        self.assertEqual(
            {getattr(segment, "plugin_command_text_path", ()) for segment in plugin_segments},
            {(6, "parameters", 3, "text"), (6, "parameters", 3, "payload")},
        )

        script_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "script_message"
        )
        self.assertEqual(script_segment.lines, ["Line"])
        self.assertEqual(script_segment.speaker_name, "Narr")
        self.assertEqual(script_segment.face_name, "顔")
        self.assertEqual(script_segment.face_index, 2)
        self.assertEqual(script_segment.background, 1)
        self.assertEqual(script_segment.position, 3)

    def test_parse_dialogue_data_branches_without_payload_lines(self) -> None:
        config_data = {
            "__dve_tyrano_config_marker__": "tyrano_config",
            "__dve_tyrano_config_newline__": "\n",
            "__dve_tyrano_config_has_trailing_newline__": True,
            "__dve_tyrano_config_lines__": [";comment", "System.title = "],
        }
        config_session = parse_dialogue_data(Path("config.tjs"), config_data)
        self.assertEqual(config_session.segments, [])
        self.assertTrue(getattr(config_session, "is_name_index_session", False))

        plugin_data = {
            "__dve_plugins_js_marker__": "plugins_js",
            "__dve_plugins_js_array__": [],
            "__dve_plugins_js_prefix__": "",
            "__dve_plugins_js_suffix__": "",
        }
        plugin_session = parse_dialogue_data(Path("plugins.js"), plugin_data)
        self.assertEqual(plugin_session.segments, [])
        self.assertTrue(getattr(plugin_session, "is_name_index_session", False))

        tyrano_data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": [{"kind": "raw_line", "line": "const x = 1;"}],
            "__dve_tyrano_script_newline__": "\n",
            "__dve_tyrano_script_has_trailing_newline__": True,
        }
        tyrano_session = parse_dialogue_data(Path("scene.ks"), tyrano_data)
        self.assertEqual(tyrano_session.segments, [])

    def test_additional_text_helper_and_file_spec_branches(self) -> None:
        self.assertEqual(_name_index_spec_for_file("armors.json")[0], "armor")
        self.assertEqual(_name_index_spec_for_file("enemies.json")[0], "enemy")
        self.assertEqual(_name_index_spec_for_file("weapons.json")[0], "weapon")
        self.assertEqual(_name_index_spec_for_file("mapinfos.json")[0], "mapinfo")
        self.assertEqual(_name_index_spec_for_file("skills.json")[0], "skill")
        self.assertEqual(_name_index_spec_for_file("states.json")[0], "state")
        self.assertEqual(_name_index_spec_for_file("tilesets.json")[0], "tileset")
        self.assertEqual(_name_index_spec_for_file("troops.json")[0], "troop")

        self.assertFalse(_is_tyrano_dialogue_text_line(""))
        self.assertFalse(_is_tyrano_dialogue_text_line("["))
        self.assertFalse(_is_tyrano_dialogue_text_line("[ ]tail"))
        self.assertTrue(_is_tyrano_dialogue_text_line("[abc]tail"))
        self.assertEqual(_tyrano_speaker_name_from_line("plain"), "")

        self.assertEqual(split_tyrano_dialogue_line_and_suffix(123), ("", ""))
        self.assertEqual(split_tyrano_dialogue_line_and_suffix("plain"), ("plain", ""))
        self.assertEqual(_split_tyrano_inline_line_breaks(""), ([""], [""]))
        self.assertEqual(_replace_tyrano_inline_line_breaks_with_newlines(""), "")
        self.assertEqual(_replace_tyrano_attribute_line_breaks_with_newlines(""), "")
        self.assertEqual(_extract_tyrano_standalone_dialogue_marker(""), "")
        self.assertEqual(_split_tyrano_leading_indent(""), ("", ""))

    def test_bracket_and_plugins_source_error_branches(self) -> None:
        escaped_source = r'["a\"b"]'
        self.assertEqual(_find_matching_bracket_end(escaped_source, 0), len(escaped_source) - 1)

        with patch("helpers.core.parser.json.loads", return_value={"x": 1}):
            with self.assertRaises(ValueError):
                _parse_plugins_js_source("var $plugins = [1];")

        with self.assertRaises(ValueError):
            plugins_js_source_from_data({})

    def test_additional_flow_grouping_and_implicit_block_paths(self) -> None:
        self.assertEqual(_tyrano_flow_depth_delta(""), 0)
        self.assertEqual(_tyrano_flow_depth_delta("[macro]"), 0)
        self.assertFalse(_has_tyrano_dialogue_marker_near_window(["A", "B"], 0, 2))
        self.assertFalse(_is_tyrano_conditional_dialogue_window(["A", "B"], 1, 1))

        grouped = _group_tyrano_dialogue_text_items(
            [
                {"kind": "text", "line": "A"},
                {"kind": "raw", "line": "[if cond]"},
                {"kind": "text", "line": "B"},
                {"kind": "raw", "line": "X"},
                123,
            ]
        )
        self.assertEqual(grouped, [[(0, "A")], [(2, "B")]])

        self.assertIsNone(_collect_tyrano_implicit_dialogue_block(["A"], -1))
        self.assertIsNone(_collect_tyrano_implicit_dialogue_block(["   "], 0))
        self.assertIsNone(
            _collect_tyrano_implicit_dialogue_block(["#Hero", "[if cond]", "[endif]"], 0)
        )

        block = _collect_tyrano_implicit_dialogue_block(
            ["Hello", "[if cond]", "[r]", "[endif]"],
            0,
        )
        self.assertIsNotNone(block)
        assert block is not None
        body_items, next_index = block
        self.assertEqual(next_index, 4)
        self.assertEqual(body_items[0], {"kind": "text", "line": "Hello"})

        parsed = _parse_tyrano_script_source("[tb_start_text mode=1]\nA\n")
        self.assertEqual(parsed["__dve_tyrano_script_chunks__"][0], {"kind": "raw_line", "line": "[tb_start_text mode=1]"})

    def test_config_title_and_tag_attribute_edge_paths(self) -> None:
        self.assertIsNone(_extract_tyrano_config_assignment_value("x", ""))
        self.assertIsNone(_extract_tyrano_config_assignment_value("System.title", "System.title"))
        self.assertEqual(
            _extract_tyrano_config_assignment_value("System.title =   A   ", "System.title"),
            (17, 18, "A", ""),
        )

        self.assertEqual(_unescape_tyrano_tag_attribute_value(r"\q"), r"\q")
        self.assertIsNone(_extract_tyrano_tag_attribute_value("line", ""))
        self.assertIsNone(
            _extract_tyrano_tag_attribute_value('[data-text="x" text = ]', "text")
        )
        self.assertIsNone(
            _extract_tyrano_tag_attribute_value('[text value="x"]', "text")
        )

    def test_source_builders_and_data_validation_error_paths(self) -> None:
        self.assertFalse(is_tyrano_script_data([]))
        self.assertFalse(is_tyrano_config_data([]))
        self.assertEqual(_coerce_tyrano_config_lines([]), [])
        self.assertEqual(_coerce_tyrano_script_chunks([]), [])

        with self.assertRaises(ValueError):
            tyrano_script_source_from_data({})
        with self.assertRaises(ValueError):
            tyrano_config_source_from_data({})
        self.assertEqual(tyrano_config_title_from_data({}), "")
        self.assertEqual(
            tyrano_config_title_from_data(
                {
                    "__dve_tyrano_config_marker__": "tyrano_config",
                    "__dve_tyrano_config_lines__": ["System.title = 'X'"],
                    "__dve_tyrano_config_title_line_index__": "0",
                }
            ),
            "",
        )
        self.assertEqual(
            tyrano_config_title_from_data(
                {
                    "__dve_tyrano_config_marker__": "tyrano_config",
                    "__dve_tyrano_config_lines__": ["no title line"],
                    "__dve_tyrano_config_title_line_index__": 0,
                }
            ),
            "",
        )

    def test_segment_builder_edge_paths_and_note_helpers(self) -> None:
        self.assertEqual(_build_plugins_text_segments(Path("plugins.js"), {}), [])

        segment = _build_json_text_segment(
            path=Path("Map001.json"),
            uid="Map001.json:N:raw",
            context="Map001.json > events[1].note",
            text="A\nB",
            path_tokens=("events", 1, "note"),
            speaker="Narrator",
            segment_kind="note_text",
        )
        self.assertEqual(segment.lines, ["A", "B"])
        self.assertEqual(getattr(segment, "json_text_path", ()), ("events", 1, "note"))
        self.assertEqual(segment.speaker_name, "Narrator")

        notes = _build_note_text_segments(
            Path("Map001.json"),
            {"events": [{"note": "abc"}, {"note": "日本語"}, {"note": ""}]},
        )
        self.assertEqual(len(notes), 1)
        self.assertEqual(getattr(notes[0], "note_text_path", ()), ("events", 1, "note"))

        system_segments = _build_system_text_segments(
            Path("System.json"),
            {
                "terms": {
                    "basic": ["", "攻撃"],
                    "commands": ["", "実行"],
                    "params": ["", "最大HP"],
                    "messages": {"victory": "勝利", "blank": "   "},
                }
            },
        )
        contexts = {segment.context for segment in system_segments}
        self.assertIn("System.json > system.terms.basic[1]", contexts)
        self.assertIn("System.json > system.terms.commands[1]", contexts)
        self.assertIn("System.json > system.terms.params[1]", contexts)
        self.assertIn("System.json > system.terms.messages.victory", contexts)

    def test_tyrano_segment_builder_edge_branches(self) -> None:
        dialogue_data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": [
                {"kind": "dialogue_block", "body_items": "bad"},
                {"kind": "dialogue_block", "body_items": [{"kind": "raw", "line": "X"}]},
                {"kind": "dialogue_block", "body_items": [{"kind": "speaker", "line": "#A"}]},
                {"kind": "dialogue_block", "body_items": [123, {"kind": "speaker", "line": "#B"}, {"kind": "text", "line": " line"}]},
            ],
        }
        dialogue_segments = _build_tyrano_dialogue_segments(Path("scene.ks"), dialogue_data)
        self.assertEqual(len(dialogue_segments), 2)
        self.assertEqual(dialogue_segments[0].lines, [""])
        self.assertEqual(dialogue_segments[1].lines, ["line"])

        choice_data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": [
                {"kind": "dialogue_block", "body_items": []},
                {"kind": "raw_line", "line": "[glink target='*A']"},
                {"kind": "raw_line", "line": "[glink text='One' target='*A']"},
                {"kind": "dialogue_block", "body_items": []},
                {"kind": "raw_line", "line": "[mylink text='Two' target='*B']"},
                {"kind": "raw_line", "line": "[mylink target='*B']"},
            ],
        }
        choice_segments, used = _build_tyrano_choice_segments(Path("scene.ks"), choice_data)
        self.assertEqual([segment.lines for segment in choice_segments], [["One"], ["Two"]])
        self.assertEqual(used, {2, 4})

        js_data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": [
                {"kind": "raw_line", "line": "end_list = ["},
                {"kind": "raw_line", "line": "]]"},
                {"kind": "raw_line", "line": "name: '   '"},
                {"kind": "raw_line", "line": "end_list = [ { id: 'A']]"},
            ],
        }
        js_segments = _build_tyrano_script_string_segments(Path("scene.js"), js_data)
        self.assertEqual(len(js_segments), 1)
        self.assertEqual(js_segments[0].lines, ["A"])
        self.assertEqual(getattr(js_segments[0], "tyrano_tag_text_join_mode", ""), "script_string_end_id")

        ks_data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": [
                {"kind": "raw_line", "line": "[iscript]"},
                {"kind": "raw_line", "line": "' ' : '和文'"},
            ],
        }
        ks_segments = _build_tyrano_script_string_segments(Path("scene.ks"), ks_data)
        self.assertEqual(len(ks_segments), 1)
        self.assertIn("(script_text)", ks_segments[0].context)

    def test_parse_dialogue_data_additional_command_and_index_paths(self) -> None:
        command_data = [
            {"code": 102, "indent": "bad", "parameters": [["Only"], 0, 0, 2, 0]},
            {"code": 355, "indent": 0, "parameters": ["tmpl_speaker"]},
            {"code": 655, "indent": 0, "parameters": ['$gameMessage.add("Line");']},
            {"code": 655, "indent": 0, "parameters": ["$gameMessage.setBackground(foo);"]},
            {"code": 655, "indent": 0, "parameters": ["$gameMessage.setPositionType(bar);"]},
            "raw-token",
        ]
        with patch(
            "helpers.core.parser.parse_game_message_templated_call",
            side_effect=lambda text: ("setSpeakerName", "Temp {{EXPR1}}", '"', ["x"]) if text == "tmpl_speaker" else None,
        ):
            command_session = parse_dialogue_data(Path("Map999.json"), command_data)

        choice_segment = next(
            segment
            for segment in command_session.segments
            if segment.segment_kind == "choice"
        )
        self.assertEqual(choice_segment.lines, ["Only"])
        self.assertEqual(choice_segment.code401_template["parameters"], [0, ""])

        script_segment = next(
            segment
            for segment in command_session.segments
            if segment.segment_kind == "script_message"
        )
        self.assertEqual(script_segment.speaker_name, "Temp {{EXPR1}}")
        self.assertEqual(script_segment.lines, ["Line"])
        self.assertEqual(script_segment.background, 0)
        self.assertEqual(script_segment.position, 2)

        item_session = parse_dialogue_data(
            Path("Items.json"),
            [
                "skip",
                {"id": 0, "name": "Ignored", "description": "Ignored"},
                {"id": 1, "name": "Potion", "description": "Line1\nLine2"},
            ],
        )
        self.assertEqual(len(item_session.segments), 1)
        item_segment = item_session.segments[0]
        self.assertEqual(item_segment.lines, ["Potion", "", "Line1", "Line2"])
        self.assertEqual(getattr(item_segment, "name_index_combined_fields", ()), ("name", "description"))

    def test_parse_dialogue_file_json_fallback_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "Random.json"
            path.write_text(
                '[{"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Narr"]}, "raw"]',
                encoding="utf-8",
            )
            session = parse_dialogue_file(path)

        self.assertEqual(len(session.segments), 1)
        self.assertEqual(session.segments[0].lines, [""])

    def test_assignment_and_helper_branch_edges(self) -> None:
        self.assertIsNone(_extract_tyrano_script_assignment_string_value("name:"))
        self.assertIsNone(_extract_tyrano_script_assignment_string_value("f.ending ="))

        property_payload = _extract_tyrano_script_assignment_string_value(r'name: "A\"B"')
        self.assertIsNotNone(property_payload)
        assert property_payload is not None
        self.assertEqual(property_payload[2], 'A"B')

        assignment_payload = _extract_tyrano_script_assignment_string_value(r'f.ending = "C\"D"')
        self.assertIsNotNone(assignment_payload)
        assert assignment_payload is not None
        self.assertEqual(assignment_payload[2], 'C"D')

        self.assertFalse(
            _should_extract_tyrano_js_script_string("assignment", "", in_end_list_context=False)
        )
        self.assertFalse(
            _should_extract_tyrano_js_script_string("unknown", "name", in_end_list_context=False)
        )
        self.assertEqual(_js_bracket_delta_outside_strings(r'"A\["'), 0)

        self.assertFalse(_append_tyrano_standalone_marker_to_previous_text([], ""))
        text_items = [{"kind": "text", "line": "A"}]
        self.assertTrue(_append_tyrano_standalone_marker_to_previous_text(text_items, "[r]"))
        self.assertEqual(text_items[0]["line"], "A[r]")
        self.assertFalse(
            _append_tyrano_standalone_marker_to_previous_text(
                [{"kind": "speaker", "line": ""}],
                "[r]",
            )
        )
        self.assertFalse(
            _append_tyrano_standalone_marker_to_previous_text(
                [{"kind": "raw", "line": "x"}],
                "[r]",
            )
        )
        self.assertFalse(
            _append_tyrano_standalone_marker_to_previous_text(
                [{"kind": "raw", "line": "   "}],
                "[r]",
            )
        )

        self.assertIsNone(_collect_tyrano_implicit_dialogue_block(["[r]"], 0))

        self.assertEqual(
            _coerce_tyrano_config_lines(
                {
                    "__dve_tyrano_config_marker__": "tyrano_config",
                    "__dve_tyrano_config_lines__": "invalid",
                }
            ),
            [],
        )
        self.assertEqual(
            _coerce_tyrano_script_chunks(
                {
                    "__dve_tyrano_script_marker__": "tyrano_script",
                    "__dve_tyrano_script_chunks__": "invalid",
                }
            ),
            [],
        )

        self.assertIsNone(_extract_tyrano_tag_attribute_value("[glink text=", "text"))
        self.assertIsNone(_extract_tyrano_tag_attribute_value('[glink text="abc]', "text"))

        self.assertEqual(_choice_lines_from_code102({"parameters": []}), [""])
        self.assertEqual(_choice_lines_from_code102({"parameters": ["bad"]}), [""])
        self.assertEqual(
            _choice_lines_from_code102({"parameters": [["A", None, 5]]}),
            ["A", "", "5"],
        )

        self.assertEqual(_collect_choice_branch_entries([123], 0), [])

        script_entries, next_index = _collect_script_block_entries(
            [{"code": 401, "indent": 0, "parameters": ["x"]}],
            0,
        )
        self.assertEqual(script_entries, [])
        self.assertEqual(next_index, 0)

        script_entries, next_index = _collect_script_block_entries(
            [
                {"code": 355, "indent": 0, "parameters": ["x"]},
                {"code": 401, "indent": 0, "parameters": ["stop"]},
            ],
            0,
        )
        self.assertEqual(len(script_entries), 1)
        self.assertEqual(next_index, 1)

        self.assertTrue(_plugin_command_argument_part_is_non_meaningful("   "))
        self.assertTrue(_plugin_command_argument_part_is_non_meaningful("rgb(1,2,3)"))
        self.assertTrue(_plugin_command_argument_value_is_non_meaningful("   "))
        self.assertTrue(_plugin_command_argument_value_is_non_meaningful("[1, 2, 3]"))
        self.assertFalse(_plugin_command_argument_value_is_non_meaningful("[1,,2]"))

        choice_segments, used_indexes = _build_tyrano_choice_segments(
            Path("scene.ks"),
            {
                "__dve_tyrano_script_marker__": "tyrano_script",
                "__dve_tyrano_script_chunks__": [
                    {"kind": "raw_line", "line": "[jump target='*A']"},
                ],
            },
        )
        self.assertEqual(choice_segments, [])
        self.assertEqual(used_indexes, set())

    def test_plugin_map_rebuild_and_name_index_edges(self) -> None:
        self.assertEqual(
            _build_plugins_text_segments(
                Path("plugins.js"),
                {
                    "__dve_plugins_js_marker__": "plugins_js",
                    "__dve_plugins_js_array__": "invalid",
                },
            ),
            [],
        )

        plugin_segments = _build_plugins_text_segments(
            Path("plugins.js"),
            {
                "__dve_plugins_js_marker__": "plugins_js",
                "__dve_plugins_js_array__": [
                    7,
                    {"name": "Alpha", "description": "Desc", "parameters": "invalid"},
                    {
                        "name": "Beta",
                        "parameters": {
                            "blank": "   ",
                            3: "x",
                            "num": 5,
                            "dialog": "Hello",
                        },
                    },
                ],
            },
        )
        self.assertEqual(len(plugin_segments), 2)
        contexts = {segment.context for segment in plugin_segments}
        self.assertIn("plugins.js > plugin[2].description", contexts)
        self.assertIn("plugins.js > plugin[3].parameters.dialog", contexts)

        self.assertIsNone(
            _build_map_display_name_segment(
                Path("Actors.json"),
                {"displayName": "Town"},
            )
        )

        self.assertEqual(
            _build_plugin_command_text_segments_for_entry(
                path=Path("Map001.json"),
                context="Map001.json > event[1]",
                list_id="events",
                list_path_tokens=["events", 1],
                command_index=5,
                command_entry={"parameters": ["Plugin", "", "Command"]},
            ),
            [],
        )
        self.assertEqual(
            _build_plugin_command_text_segments_for_entry(
                path=Path("Map001.json"),
                context="Map001.json > event[1]",
                list_id="events",
                list_path_tokens=["events", 1],
                command_index=5,
                command_entry={"parameters": ["Plugin", "", "Command", "invalid"]},
            ),
            [],
        )

        command_segments = _build_plugin_command_text_segments_for_entry(
            path=Path("Map001.json"),
            context="Map001.json > event[1]",
            list_id="events",
            list_path_tokens=["events", 1],
            command_index=5,
            command_entry={
                "indent": 2,
                "parameters": [
                    "Plugin",
                    "",
                    "Command",
                    {
                        1: "skip-key",
                        "not_str_value": 123,
                        "blank": "   ",
                        "text": "Line",
                    },
                ],
            },
        )
        self.assertEqual(len(command_segments), 1)
        self.assertEqual(command_segments[0].lines, ["Line"])

        rebuilt = tyrano_script_source_from_data(
            {
                "__dve_tyrano_script_marker__": "tyrano_script",
                "__dve_tyrano_script_newline__": "\n",
                "__dve_tyrano_script_has_trailing_newline__": False,
                "__dve_tyrano_script_chunks__": [
                    {
                        "kind": "dialogue_block",
                        "body_items": [
                            123,
                            {"line": "A"},
                        ],
                    }
                ],
            }
        )
        self.assertEqual(rebuilt, "A")

        dialogue_data = {
            "__dve_tyrano_script_marker__": "tyrano_script",
            "__dve_tyrano_script_chunks__": [
                {
                    "kind": "dialogue_block",
                    "body_items": [{"kind": "text", "line": "A"}],
                }
            ],
        }
        with patch(
            "helpers.core.parser._split_tyrano_inline_line_breaks",
            return_value=([], []),
        ):
            dialogue_segments = _build_tyrano_dialogue_segments(Path("scene.ks"), dialogue_data)
        self.assertEqual(len(dialogue_segments), 1)
        self.assertEqual(dialogue_segments[0].lines, [""])

        actor_session = parse_dialogue_data(
            Path("Actors.json"),
            [{"id": 1, "name": "Hero"}],
        )
        self.assertEqual(len(actor_session.segments), 1)
        self.assertEqual(actor_session.segments[0].lines, ["Hero"])

    def test_remaining_parser_defensive_branches(self) -> None:
        self.assertIsNone(_collect_tyrano_implicit_dialogue_block(["#Hero", "[r]"], 0))
        self.assertEqual(_normalize_tyrano_choice_text_for_editor(""), "")

        with patch(
            "helpers.core.parser.is_tyrano_config_data",
            return_value=True,
        ):
            self.assertEqual(
                _coerce_tyrano_config_lines({"__dve_tyrano_config_lines__": "bad"}),
                [],
            )
        with patch(
            "helpers.core.parser.is_tyrano_script_data",
            return_value=True,
        ):
            self.assertEqual(
                _coerce_tyrano_script_chunks({"__dve_tyrano_script_chunks__": "bad"}),
                [],
            )

        with patch(
            "helpers.core.parser.is_plugins_js_data",
            return_value=True,
        ):
            self.assertEqual(
                _build_plugins_text_segments(
                    Path("plugins.js"),
                    {"__dve_plugins_js_array__": "bad"},
                ),
                [],
            )

        with patch(
            "helpers.core.parser.is_command_entry",
            return_value=True,
        ):
            self.assertEqual(
                _collect_choice_branch_entries(
                    [
                        {"code": 102, "indent": 0, "parameters": [[]]},
                        123,
                        {"code": 404, "indent": 0, "parameters": []},
                    ],
                    0,
                ),
                [],
            )

        choice_segments, used = _build_tyrano_choice_segments(
            Path("scene.ks"),
            {
                "__dve_tyrano_script_marker__": "tyrano_script",
                "__dve_tyrano_script_chunks__": [
                    {"kind": "raw_line", "line": "[glink target='*A']"},
                ],
            },
        )
        self.assertEqual(choice_segments, [])
        self.assertEqual(used, set())

        with patch(
            "helpers.core.parser.copy.deepcopy",
            return_value={},
        ):
            session = parse_dialogue_data(
                Path("Map001.json"),
                [
                    {
                        "code": 355,
                        "indent": "bad",
                        "parameters": ['$gameMessage.add("Line");'],
                    }
                ],
            )
        self.assertEqual(len(session.segments), 1)
        self.assertEqual(session.segments[0].segment_kind, "script_message")
        self.assertEqual(session.segments[0].lines, ["Line"])

    def test_remaining_parser_uncovered_control_flow_paths(self) -> None:
        self.assertIsNone(_collect_tyrano_implicit_dialogue_block(["#Hero"], 0))
        with patch(
            "helpers.core.parser._is_tyrano_dialogue_text_line",
            side_effect=[True, False],
        ):
            self.assertIsNone(_collect_tyrano_implicit_dialogue_block(["plain"], 0))

        with patch(
            "helpers.core.parser._extract_tyrano_tag_attribute_value",
            side_effect=[
                (0, 1, "A", '"'),
                None,
            ],
        ):
            segments, used_indexes = _build_tyrano_choice_segments(
                Path("scene.ks"),
                {
                    "__dve_tyrano_script_marker__": "tyrano_script",
                    "__dve_tyrano_script_chunks__": [
                        {"kind": "raw_line", "line": "[glink text='A' target='*A']"},
                    ],
                },
            )
        self.assertEqual(segments, [])
        self.assertEqual(used_indexes, set())

        class _WeirdAssignLine(str):
            def find(self, sub: str, start: int = 0, end: int | None = None) -> int:
                if sub == "=":
                    return len(self) + 1
                if end is None:
                    return super().find(sub, start)
                return super().find(sub, start, end)

        payload = _extract_tyrano_config_assignment_value(
            _WeirdAssignLine("System.title = abc"),
            "System.title",
        )
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload[0], payload[1])
        self.assertEqual(payload[2], "")



if __name__ == "__main__":
    unittest.main()
