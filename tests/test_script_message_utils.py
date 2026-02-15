from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.core.script_message_utils import (
    build_game_message_call,
    parse_game_message_call,
)


class ScriptMessageUtilsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
