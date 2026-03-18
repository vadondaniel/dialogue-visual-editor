from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.core.models import (
    NO_SPEAKER_KEY,
    DialogueSegment,
)


class ModelsTests(unittest.TestCase):
    def test_segment_defaults(self) -> None:
        segment = DialogueSegment(
            uid="seg-1",
            context="ctx",
            code101={"code": 101, "parameters": ["face", "bad", "bg"]},
            lines=["Line 1", "Line 2"],
            original_lines=["Original 1"],
        )

        self.assertEqual(segment.face_name, "face")
        self.assertEqual(segment.face_index, 0)
        self.assertEqual(segment.background, "bg")
        self.assertEqual(segment.position, "-")
        self.assertEqual(segment.speaker_name, NO_SPEAKER_KEY)
        self.assertEqual(segment.original_text_joined(), "Original 1")
        self.assertEqual(segment.source_text_joined(), "Original 1")
        self.assertEqual(segment.translation_text_joined(), "")
        self.assertEqual(segment.text_joined(), "Line 1\nLine 2")

    def test_segment_source_and_trimmed_speaker(self) -> None:
        segment = DialogueSegment(
            uid="seg-2",
            context="ctx",
            code101={"code": 101, "parameters": ["", 2, "bg", "left", "  Hero  "]},
            lines=["Line"],
            original_lines=["Original"],
            source_lines=["Source", "Block"],
            translation_lines=["TL 1", "TL 2"],
            segment_kind="script_message",
        )

        self.assertEqual(segment.face_index, 2)
        self.assertEqual(segment.position, "left")
        self.assertEqual(segment.speaker_name, "Hero")
        self.assertEqual(segment.has_face, False)
        self.assertTrue(segment.is_structural_dialogue)
        self.assertEqual(segment.source_text_joined(), "Source\nBlock")
        self.assertEqual(segment.translation_text_joined(), "TL 1\nTL 2")
