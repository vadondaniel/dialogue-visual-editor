from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dialogue_visual_editor.helpers.core.parser import (
    parse_dialogue_data,
    parse_dialogue_file,
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


if __name__ == "__main__":
    unittest.main()
