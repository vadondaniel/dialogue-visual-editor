from __future__ import annotations

import unittest

from helpers.core.actor_name_change_utils import (
    collect_actor_name_change_entries,
)


class ActorNameChangeUtilsTests(unittest.TestCase):
    def test_collects_change_name_commands_with_paths(self) -> None:
        data = {
            "events": [
                {
                    "pages": [
                        {
                            "list": [
                                {
                                    "code": 320,
                                    "indent": 0,
                                    "parameters": [1, "ヒナタ"],
                                },
                                {
                                    "code": 101,
                                    "indent": 0,
                                    "parameters": ["", 0, 0, 2, ""],
                                },
                            ]
                        }
                    ]
                }
            ]
        }

        entries = collect_actor_name_change_entries(data)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.actor_id, 1)
        self.assertEqual(entry.name, "ヒナタ")
        self.assertEqual(
            entry.path_tokens,
            ("events", 0, "pages", 0, "list", 0, "parameters", 1),
        )

    def test_ignores_invalid_change_name_payloads(self) -> None:
        data = {
            "list": [
                {"code": 320, "parameters": [0, "NoActor"]},
                {"code": 320, "parameters": [1]},
                {"code": 320, "parameters": [1, 123]},
                {"code": 320, "parameters": [2, "Valid"]},
            ]
        }

        entries = collect_actor_name_change_entries(data)

        self.assertEqual([(entry.actor_id, entry.name) for entry in entries], [(2, "Valid")])


if __name__ == "__main__":
    unittest.main()
