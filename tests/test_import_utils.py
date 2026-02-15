from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.core.import_utils import (
    align_source_translated_segments,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment


def _segment(
    uid: str,
    context: str,
    *,
    speaker: str = "",
    kind: str = "dialogue",
) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context=context,
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=["line"],
        original_lines=["line"],
        source_lines=["line"],
        segment_kind=kind,
    )


class ImportUtilsTests(unittest.TestCase):
    def test_align_direct_uid_match(self) -> None:
        source = [
            _segment("Map001.json:L0:0", "Map001.json > events[0]"),
            _segment("Map001.json:L0:1", "Map001.json > events[1]"),
        ]
        translated = [
            _segment("Map001.json:L0:0", "Map001.json > events[0]"),
            _segment("Map001.json:L0:1", "Map001.json > events[1]"),
        ]

        mapped, inserts = align_source_translated_segments(source, translated)

        self.assertEqual(mapped, [(0, 0), (1, 1)])
        self.assertEqual(inserts, {})

    def test_align_detects_middle_insertions(self) -> None:
        source = [
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:1", "ctx_b"),
            _segment("Map001.json:L0:2", "ctx_c"),
        ]
        translated = [
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:900", "ctx_inserted"),
            _segment("Map001.json:L0:1", "ctx_b"),
            _segment("Map001.json:L0:2", "ctx_c"),
        ]

        mapped, inserts = align_source_translated_segments(source, translated)

        self.assertEqual(mapped, [(0, 0), (1, 2), (2, 3)])
        self.assertEqual(inserts, {0: [1]})

    def test_align_detects_leading_insertions(self) -> None:
        source = [
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:1", "ctx_b"),
        ]
        translated = [
            _segment("Map001.json:L0:900", "ctx_inserted"),
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:1", "ctx_b"),
        ]

        mapped, inserts = align_source_translated_segments(source, translated)

        self.assertEqual(mapped, [(0, 1), (1, 2)])
        self.assertEqual(inserts, {-1: [0]})

    def test_align_handles_empty_inputs(self) -> None:
        mapped, inserts = align_source_translated_segments([], [])
        self.assertEqual(mapped, [])
        self.assertEqual(inserts, {})


if __name__ == "__main__":
    unittest.main()
