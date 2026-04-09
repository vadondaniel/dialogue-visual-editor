from __future__ import annotations

import unittest
from unittest.mock import patch

from helpers.core.import_utils import (
    _uid_group,
    align_source_translated_segments,
    segment_alignment_key,
)
from helpers.core.models import DialogueSegment


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
    def test_uid_group_keeps_plain_uid(self) -> None:
        self.assertEqual(_uid_group("Map001"), "Map001")

    def test_segment_alignment_key_filters_non_string_script_roles(self) -> None:
        segment = _segment("Map001.json:L0:0", "ctx")
        segment.script_entry_roles = ["speaker", "line", 10]  # type: ignore[list-item]
        key = segment_alignment_key(segment)
        self.assertEqual(key[-1], ("speaker", "line"))

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

    def test_align_handles_duplicate_translated_uids(self) -> None:
        source = [
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:1", "ctx_b"),
        ]
        translated = [
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:0", "ctx_b_duplicate_uid"),
        ]

        mapped, inserts = align_source_translated_segments(source, translated)

        self.assertEqual(mapped, [(0, 0), (1, 1)])
        self.assertEqual(inserts, {})

    def test_align_falls_back_when_direct_uid_match_breaks(self) -> None:
        source = [
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:1", "ctx_b"),
        ]
        translated = [
            _segment("Map001.json:L0:0", "ctx_a"),
            _segment("Map001.json:L0:99", "ctx_c"),
        ]

        mapped, inserts = align_source_translated_segments(source, translated)

        self.assertEqual(mapped, [(0, 0), (1, 1)])
        self.assertEqual(inserts, {})

    def test_align_replace_records_extra_translated_items_as_insertions(self) -> None:
        source = [
            _segment("Map001.json:L0:0", "ctx_source_a"),
            _segment("Map001.json:L0:1", "ctx_source_b"),
        ]
        translated = [
            _segment("Map001.json:L0:10", "ctx_translated_a"),
            _segment("Map001.json:L0:11", "ctx_translated_b"),
            _segment("Map001.json:L0:12", "ctx_translated_extra"),
        ]

        mapped, inserts = align_source_translated_segments(source, translated)

        self.assertEqual(mapped, [(0, 0), (1, 1)])
        self.assertEqual(inserts, {1: [2]})

    def test_align_with_no_opcodes_uses_fallback_mapping(self) -> None:
        source = [_segment("Map001.json:L0:0", "ctx_a")]
        translated = [
            _segment("Map001.json:L0:10", "ctx_t0"),
            _segment("Map001.json:L0:11", "ctx_t1"),
        ]

        class _NoOpcodeMatcher:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def get_opcodes(self) -> list[tuple[str, int, int, int, int]]:
                return []

        with patch(
            "helpers.core.import_utils.SequenceMatcher",
            _NoOpcodeMatcher,
        ):
            mapped, inserts = align_source_translated_segments(source, translated)

        self.assertEqual(mapped, [(0, 0)])
        self.assertEqual(inserts, {0: [0, 1, 1]})


if __name__ == "__main__":
    unittest.main()
