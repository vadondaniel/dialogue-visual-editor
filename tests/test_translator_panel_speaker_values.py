from __future__ import annotations

import unittest
from typing import Any, cast

from app import DialogueVisualEditor
from helpers.core.models import DialogueSegment, NO_SPEAKER_KEY


def _segment(speaker: str = "", tl_speaker: str = "") -> DialogueSegment:
    return DialogueSegment(
        uid="Map001.json:L0:0",
        context="Map001 > Event 1",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=["line"],
        original_lines=["line"],
        source_lines=["line"],
        translation_speaker=tl_speaker,
    )


class _Harness:
    def __init__(self) -> None:
        self._speaker_key = NO_SPEAKER_KEY
        self._resolved_name = ""
        self._speaker_en = ""

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        _ = segment
        return self._speaker_key

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = text
        _ = prefer_translated
        _ = unresolved_placeholder
        return self._resolved_name

    def _normalize_speaker_key(self, value: str) -> str:
        return DialogueVisualEditor._normalize_speaker_key(cast(Any, self), value)

    def _speaker_translation_for_key(self, speaker_key: str) -> str:
        _ = speaker_key
        return self._speaker_en


def _panel_values(harness: _Harness, segment: DialogueSegment) -> tuple[str, str]:
    return DialogueVisualEditor._translator_panel_speaker_values(
        cast(Any, harness),
        segment,
    )


class TranslatorPanelSpeakerValuesTests(unittest.TestCase):
    def test_explicit_speaker_prefers_explicit_jp(self) -> None:
        harness = _Harness()
        harness._speaker_key = "Hero"
        harness._resolved_name = "Hero"
        harness._speaker_en = "Aki"
        segment = _segment("Hero")

        jp, en = _panel_values(harness, segment)

        self.assertEqual(jp, "Hero")
        self.assertEqual(en, "Aki")

    def test_inferred_speaker_fills_jp_when_explicit_missing(self) -> None:
        harness = _Harness()
        harness._speaker_key = "Narrator"
        harness._resolved_name = NO_SPEAKER_KEY
        harness._speaker_en = "Narration"
        segment = _segment("")

        jp, en = _panel_values(harness, segment)

        self.assertEqual(jp, "Narrator")
        self.assertEqual(en, "Narration")

    def test_translation_speaker_used_when_map_missing(self) -> None:
        harness = _Harness()
        harness._speaker_key = "Guard"
        harness._resolved_name = NO_SPEAKER_KEY
        harness._speaker_en = ""
        segment = _segment("", tl_speaker="Town Guard")

        jp, en = _panel_values(harness, segment)

        self.assertEqual(jp, "Guard")
        self.assertEqual(en, "Town Guard")

    def test_no_speaker_shows_none_marker(self) -> None:
        harness = _Harness()
        harness._speaker_key = NO_SPEAKER_KEY
        harness._resolved_name = NO_SPEAKER_KEY
        harness._speaker_en = ""
        segment = _segment("")

        jp, en = _panel_values(harness, segment)

        self.assertEqual(jp, NO_SPEAKER_KEY)
        self.assertEqual(en, NO_SPEAKER_KEY)

    def test_non_structural_segment_returns_empty(self) -> None:
        harness = _Harness()
        harness._speaker_key = "Hero"
        harness._resolved_name = "Hero"
        harness._speaker_en = "Aki"
        segment = _segment("Hero")
        segment.segment_kind = "choice"

        jp, en = _panel_values(harness, segment)

        self.assertEqual(jp, "")
        self.assertEqual(en, "")


if __name__ == "__main__":
    unittest.main()
