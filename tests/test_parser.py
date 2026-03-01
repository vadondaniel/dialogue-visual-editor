from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dialogue_visual_editor.helpers.core.models import NO_SPEAKER_KEY
from dialogue_visual_editor.helpers.core.parser import (
    parse_dialogue_data,
    parse_dialogue_file,
    tyrano_config_source_from_data,
    tyrano_script_source_from_data,
)


class ParserTests(unittest.TestCase):
    def test_parse_regular_dialogue_block(self) -> None:
        data = {
            "events": [
                {
                    "pages": [
                        {
                            "list": [
                                {
                                    "code": 101,
                                    "indent": 0,
                                    "parameters": ["", 0, 0, 2, "Hero"],
                                },
                                {"code": 401, "indent": 0, "parameters": ["Line A"]},
                                {"code": 401, "indent": 0, "parameters": ["Line B"]},
                            ]
                        }
                    ]
                }
            ]
        }
        session = parse_dialogue_data(Path("Map001.json"), data)
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.lines, ["Line A", "Line B"])
        self.assertEqual(segment.speaker_name, "Hero")
        self.assertIn("Map001.json", segment.context)

    def test_parse_choice_block(self) -> None:
        data = [
            {"code": 102, "indent": 0, "parameters": [["Yes", "No"], 0, 0, 2, 0]},
            {"code": 402, "indent": 0, "parameters": [0, "Yes"]},
            {"code": 402, "indent": 0, "parameters": [1, "No"]},
            {"code": 404, "indent": 0, "parameters": []},
        ]
        session = parse_dialogue_data(Path("Map002.json"), data)
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.segment_kind, "choice")
        self.assertEqual(segment.lines, ["Yes", "No"])
        self.assertEqual(segment.line_entry_code, 402)
        self.assertEqual(len(segment.choice_branch_entries), 2)

    def test_parse_script_message_block(self) -> None:
        data = [
            {
                "code": 355,
                "indent": 0,
                "parameters": ['$gameMessage.setSpeakerName("Narrator");'],
            },
            {"code": 655, "indent": 0, "parameters": ['$gameMessage.add("One");']},
            {"code": 655, "indent": 0, "parameters": ['$gameMessage.add("Two");']},
        ]
        session = parse_dialogue_data(Path("Map003.json"), data)
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.segment_kind, "script_message")
        self.assertEqual(segment.lines, ["One", "Two"])
        self.assertEqual(segment.speaker_name, "Narrator")

    def test_parse_script_message_block_reads_face_from_set_face_image(self) -> None:
        data = [
            {
                "code": 355,
                "indent": 0,
                "parameters": ['$gameMessage.setSpeakerName("Narrator");'],
            },
            {
                "code": 655,
                "indent": 0,
                "parameters": ['$gameMessage.setFaceImage(face,$gameVariables.value(37));'],
            },
            {"code": 655, "indent": 0, "parameters": ['$gameMessage.add("One");']},
        ]
        session = parse_dialogue_data(Path("Map004.json"), data)
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.segment_kind, "script_message")
        self.assertEqual(segment.face_name, "face")
        self.assertTrue(segment.has_face)

    def test_parse_script_message_block_reads_background_and_position(self) -> None:
        data = [
            {
                "code": 355,
                "indent": 5,
                "parameters": ['$gameMessage.setFaceImage(face,$gameVariables.value(37));'],
            },
            {
                "code": 655,
                "indent": 5,
                "parameters": ["$gameMessage.setBackground(1);"],
            },
            {
                "code": 655,
                "indent": 5,
                "parameters": ["$gameMessage.setPositionType(0);"],
            },
            {
                "code": 655,
                "indent": 5,
                "parameters": ['$gameMessage.setSpeakerName("\\\\C[2]\\\\N[1]\\\\C[0]");'],
            },
            {
                "code": 655,
                "indent": 5,
                "parameters": ['$gameMessage.add("One");'],
            },
        ]
        session = parse_dialogue_data(Path("Map005.json"), data)
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.segment_kind, "script_message")
        self.assertEqual(segment.face_name, "face")
        self.assertEqual(segment.background, 1)
        self.assertEqual(segment.position, 0)

    def test_parse_script_message_block_with_templated_add_expression(self) -> None:
        data = [
            {
                "code": 355,
                "indent": 0,
                "parameters": ["var n = 1;"],
            },
            {
                "code": 655,
                "indent": 0,
                "parameters": ['$gameMessage.add("A" + m + "B");'],
            },
        ]
        session = parse_dialogue_data(Path("Map006.json"), data)
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.segment_kind, "script_message")
        self.assertEqual(segment.lines, ["A{{EXPR1}}B"])
        self.assertEqual(len(segment.script_entry_expression_templates), 2)
        template_payload = segment.script_entry_expression_templates[1]
        self.assertIsInstance(template_payload, dict)
        assert isinstance(template_payload, dict)
        self.assertEqual(template_payload.get("kind"), "add")
        self.assertEqual(template_payload.get("expr_terms"), ["m"])

    def test_map_display_name_segment_is_inserted(self) -> None:
        data = {"displayName": "Town Square"}
        session = parse_dialogue_data(Path("Map010.json"), data)
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.segment_kind, "map_display_name")
        self.assertEqual(segment.lines, ["Town Square"])
        self.assertEqual(segment.uid, "Map010.json:map_display_name")

    def test_system_json_builds_name_index_segments(self) -> None:
        data = {
            "gameTitle": "Project",
            "currencyUnit": "Gold",
            "elements": ["", "Fire"],
            "terms": {"messages": {"actionFailure": "Failed"}},
        }
        session = parse_dialogue_data(Path("System.json"), data)
        self.assertTrue(getattr(session, "is_name_index_session", False))
        self.assertEqual(getattr(session, "name_index_kind", ""), "system")
        contexts = {segment.context for segment in session.segments}
        self.assertIn("System.json > system.gameTitle", contexts)
        self.assertIn("System.json > system.currencyUnit", contexts)
        self.assertIn("System.json > system.elements[1]", contexts)
        self.assertIn("System.json > system.terms.messages.actionFailure", contexts)
        self.assertTrue(all(segment.segment_kind == "system_text" for segment in session.segments))

    def test_name_index_file_has_stable_uids(self) -> None:
        data = [
            None,
            {
                "id": 1,
                "name": "Poison",
                "message1": "A",
                "message2": "",
                "message3": "C",
                "message4": "D",
            },
        ]
        session = parse_dialogue_data(Path("States.json"), data)
        self.assertTrue(getattr(session, "is_name_index_session", False))
        uids = {segment.uid for segment in session.segments}
        self.assertIn("States.json:S:1", uids)
        self.assertIn("States.json:S:1:message1", uids)
        self.assertIn("States.json:S:1:message2", uids)
        self.assertIn("States.json:S:1:message3", uids)
        self.assertIn("States.json:S:1:message4", uids)
        self.assertTrue(all(segment.segment_kind == "name_index" for segment in session.segments))

    def test_parse_plugins_js_file(self) -> None:
        plugins_source = (
            "var $plugins =\n"
            "[\n"
            "  {\n"
            '    "name": "MyPlugin",\n'
            '    "status": true,\n'
            '    "description": "Plugin description",\n'
            '    "parameters": {"mode": "Fast"}\n'
            "  }\n"
            "];\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plugins.js"
            path.write_text(plugins_source, encoding="utf-8")
            session = parse_dialogue_file(path)

        self.assertTrue(getattr(session, "is_name_index_session", False))
        self.assertEqual(getattr(session, "name_index_kind", ""), "plugin")
        contexts = [segment.context for segment in session.segments]
        self.assertIn("plugins.js > plugin[1].description", contexts)
        self.assertIn("plugins.js > plugin[1].parameters.mode", contexts)
        self.assertTrue(all(segment.segment_kind == "plugin_text" for segment in session.segments))

    def test_parse_troops_keeps_dialogue_and_name_index_segments(self) -> None:
        data = [
            None,
            {
                "id": 1,
                "name": "Troop A",
                "pages": [
                    {
                        "list": [
                            {
                                "code": 101,
                                "indent": 0,
                                "parameters": ["", 0, 0, 2, "Narrator"],
                            },
                            {"code": 401, "indent": 0, "parameters": ["Hello from troop event"]},
                        ]
                    }
                ],
            },
        ]
        session = parse_dialogue_data(Path("Troops.json"), data)

        kinds = [segment.segment_kind for segment in session.segments]
        self.assertIn("dialogue", kinds)
        self.assertIn("name_index", kinds)
        self.assertFalse(bool(getattr(session, "is_name_index_session", False)))
        self.assertTrue(bool(getattr(session, "has_mixed_dialogue_misc_segments", False)))

    def test_parse_plugin_command_argument_text_segments_from_code357(self) -> None:
        data = {
            "events": [
                {
                    "pages": [
                        {
                            "list": [
                                {
                                    "code": 357,
                                    "indent": 0,
                                    "parameters": [
                                        "DTextPicture",
                                        "dText",
                                        "文字列ピクチャ準備",
                                        {
                                            "text": "\\i[7]\\C[27]メイドレベル\\C[0]",
                                            "fontSize": "24",
                                            "align": "left",
                                            "windowColor": "#ff99ff",
                                            "bold": "true",
                                        },
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        session = parse_dialogue_data(Path("Map099.json"), data)
        plugin_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "plugin_command_text"
        ]

        self.assertEqual(len(plugin_segments), 1)
        by_path = {
            getattr(segment, "plugin_command_text_path", ()): segment
            for segment in plugin_segments
        }
        text_path = ("events", 0, "pages", 0, "list", 0, "parameters", 3, "text")
        self.assertIn(text_path, by_path)
        self.assertEqual(by_path[text_path].lines, ["\\i[7]\\C[27]メイドレベル\\C[0]"])

    def test_parse_map_event_note_text_segments(self) -> None:
        data = {
            "events": [
                None,
                {
                    "id": 3,
                    "name": "EV003",
                    "note": "<LB:\\i[150]あずみさん>",
                    "pages": [],
                },
            ]
        }
        session = parse_dialogue_data(Path("Map001.json"), data)
        note_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "note_text"
        ]

        self.assertEqual(len(note_segments), 1)
        note_segment = note_segments[0]
        self.assertEqual(note_segment.lines, ["<LB:\\i[150]あずみさん>"])
        self.assertEqual(
            getattr(note_segment, "json_text_path", ()),
            ("events", 1, "note"),
        )

    def test_parse_actors_includes_profile_and_note_text_segments(self) -> None:
        data = [
            None,
            {
                "id": 34,
                "name": "キヨヒコ",
                "nickname": "",
                "note": "<SAC道具封印スイッチ:148>\n<SACItemSwitch:148>",
                "profile": "両手が変化し、ハーピーの羽のそれに変化した。",
            },
        ]
        session = parse_dialogue_data(Path("Actors.json"), data)
        self.assertTrue(bool(getattr(session, "is_name_index_session", False)))
        self.assertEqual(getattr(session, "name_index_kind", ""), "actor")
        uid_set = {segment.uid for segment in session.segments}
        self.assertIn("Actors.json:A:34", uid_set)
        self.assertIn("Actors.json:A:34:profile", uid_set)

        note_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "note_text"
        ]
        self.assertEqual(len(note_segments), 1)
        self.assertEqual(
            getattr(note_segments[0], "json_text_path", ()),
            (1, "note"),
        )

    def test_parse_tyrano_script_file_extracts_dialogue_choice_and_tag_text(self) -> None:
        source = (
            "[tb_start_text mode=1 ]\n"
            "#NPC\n"
            "こんにちは[p]\n"
            "[_tb_end_text]\n"
            "[glink text=\"選択肢\" target=\"*A\"]\n"
            "[button text=\"補助テキスト\" target=\"*B\"]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene1.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        ]
        choice_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        ]
        tag_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
        ]
        self.assertEqual(len(dialogue_segments), 1)
        self.assertEqual(dialogue_segments[0].speaker_name, "NPC")
        self.assertEqual(dialogue_segments[0].lines, ["こんにちは"])
        self.assertEqual(
            getattr(dialogue_segments[0], "tyrano_line_suffixes", ()),
            ("[p]",),
        )
        self.assertEqual(len(choice_segments), 1)
        self.assertEqual(choice_segments[0].lines, ["選択肢"])
        self.assertEqual(len(tag_segments), 1)
        self.assertEqual(tag_segments[0].lines, ["補助テキスト"])

    def test_parse_tyrano_script_file_extracts_plain_hash_speaker_dialogue(self) -> None:
        source = (
            "#妹\n"
            "こんにちは[r]\n"
            "よろしくね[p]\n"
            "@jump target=\"*NEXT\"\n"
            "地の文です[r]\n"
            "続きです[p]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_plain.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        ]
        self.assertEqual(len(dialogue_segments), 2)

        self.assertEqual(dialogue_segments[0].speaker_name, "妹")
        self.assertEqual(dialogue_segments[0].lines, ["こんにちは", "よろしくね"])
        self.assertEqual(
            getattr(dialogue_segments[0], "tyrano_line_suffixes", ()),
            ("[r]", "[p]"),
        )

        self.assertEqual(dialogue_segments[1].speaker_name, NO_SPEAKER_KEY)
        self.assertEqual(dialogue_segments[1].lines, ["地の文です", "続きです"])
        self.assertEqual(
            getattr(dialogue_segments[1], "tyrano_line_suffixes", ()),
            ("[r]", "[p]"),
        )

    def test_tyrano_script_source_from_data_round_trip_plain_hash_speaker_dialogue(self) -> None:
        source = (
            "#妹\n"
            "こんにちは[r]\n"
            "よろしくね[p]\n"
            "@jump target=\"*NEXT\"\n"
            "地の文です[r]\n"
            "続きです[p]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_plain_roundtrip.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        rebuilt_source = tyrano_script_source_from_data(session.data)
        self.assertEqual(rebuilt_source, source)

    def test_parse_tyrano_script_file_ignores_plain_code_without_dialogue_markers(self) -> None:
        source = (
            "tf.page = 0;\n"
            "tf.selected = \"\";\n"
            "if(flag) {\n"
            "    doWork();\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_code.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        ]
        self.assertEqual(dialogue_segments, [])

    def test_parse_tyrano_script_file_ignores_hash_speaker_without_dialogue_markers(self) -> None:
        source = (
            "#function_like\n"
            "const value = 1;\n"
            "return value;\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_hash_code.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        ]
        self.assertEqual(dialogue_segments, [])

    def test_parse_tyrano_script_file_splits_dialogue_by_page_break(self) -> None:
        source = (
            "[tb_start_text mode=3 ]\n"
            "#NPC\n"
            "「前半」[r]\n"
            "「後半」[p][r]\n"
            "「次のページ」[p][r]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_split.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        ]
        self.assertEqual(len(dialogue_segments), 2)
        self.assertEqual(dialogue_segments[0].speaker_name, "NPC")
        self.assertEqual(
            dialogue_segments[0].lines,
            ["「前半」", "「後半」"],
        )
        self.assertEqual(
            getattr(dialogue_segments[0], "tyrano_line_suffixes", ()),
            ("[r]", "[p][r]"),
        )
        self.assertEqual(dialogue_segments[1].speaker_name, "NPC")
        self.assertEqual(dialogue_segments[1].lines, ["「次のページ」"])
        self.assertEqual(
            getattr(dialogue_segments[1], "tyrano_line_suffixes", ()),
            ("[p][r]",),
        )

    def test_parse_tyrano_dialogue_inline_r_becomes_newline(self) -> None:
        source = (
            "[tb_start_text mode=3 ]\n"
            "#NPC\n"
            "A[r]B[p][r]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_inline_r.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        self.assertEqual(dialogue_segment.lines, ["A", "B"])
        self.assertEqual(
            getattr(dialogue_segment, "tyrano_line_suffixes", ()),
            ("[r]", "[p][r]"),
        )

    def test_parse_tyrano_glink_text_inline_r_becomes_newline_in_choice(self) -> None:
        source = '[glink text="A[r]B" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_choice_inline_r.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        self.assertEqual(choice_segment.lines, ["A\nB"])

    def test_parse_tyrano_choice_converts_nbsp_to_spaces_for_editor(self) -> None:
        source = '[glink text="A\u00A0\u00A0B" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_choice_nbsp.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        self.assertEqual(choice_segment.lines, ["A  B"])

    def test_parse_tyrano_choice_converts_narrow_nbsp_to_spaces_for_editor(self) -> None:
        source = '[glink text="A\u202F\u202FB" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_choice_nnbsp.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        self.assertEqual(choice_segment.lines, ["A  B"])

    def test_parse_tyrano_choice_escaped_newline_becomes_newline_in_editor(self) -> None:
        source = '[glink text="A\\nB" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_choice_escaped_newline.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        self.assertEqual(choice_segment.lines, ["A\nB"])

    def test_parse_tyrano_tag_text_inline_r_becomes_newline(self) -> None:
        source = '[button text="補助[r]ラベル" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_tag_inline_r.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        tag_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
        )
        self.assertEqual(tag_segment.lines, ["補助", "ラベル"])

    def test_parse_tyrano_tag_text_escaped_newline_becomes_newline(self) -> None:
        source = '[button text="補助\\nラベル" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_tag_escaped_newline.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        tag_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
        )
        self.assertEqual(tag_segment.lines, ["補助", "ラベル"])

    def test_parse_tyrano_script_blank_speaker_marker_is_no_speaker(self) -> None:
        source = (
            "[tb_start_text mode=1 ]\n"
            "#\n"
            "地の文[p]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_no_speaker.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        self.assertEqual(dialogue_segment.speaker_name, NO_SPEAKER_KEY)
        self.assertEqual(dialogue_segment.lines, ["地の文"])
        self.assertEqual(
            getattr(dialogue_segment, "tyrano_line_suffixes", ()),
            ("[p]",),
        )

    def test_tyrano_script_source_from_data_round_trip(self) -> None:
        source = (
            ";comment\n"
            "[tb_start_text mode=1 ]\n"
            "「一行目」[p]\n"
            "「二行目」[p]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene2.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        rebuilt_source = tyrano_script_source_from_data(session.data)
        self.assertEqual(rebuilt_source, source)

    def test_parse_tyrano_config_file_extracts_system_title(self) -> None:
        source = (
            ";debugMenu.visible=false\n"
            ";System.title=せんていトランス\n"
            ";game_version=0.0\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "Config.tjs"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        self.assertTrue(bool(getattr(session, "is_name_index_session", False)))
        self.assertEqual(getattr(session, "name_index_kind", ""), "system")
        self.assertEqual(len(session.segments), 1)
        segment = session.segments[0]
        self.assertEqual(segment.segment_kind, "system_text")
        self.assertEqual(segment.lines, ["せんていトランス"])
        self.assertEqual(getattr(segment, "system_text_path", ()), ("gameTitle",))

        rebuilt_source = tyrano_config_source_from_data(session.data)
        self.assertEqual(rebuilt_source, source)

if __name__ == "__main__":
    unittest.main()
