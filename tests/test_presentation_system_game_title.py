from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession
from dialogue_visual_editor.helpers.mixins.presentation_mixins import (
    PresentationHelpersMixin,
)


def _system_segment(
    source_title: str,
    translated_title: str = "",
) -> DialogueSegment:
    segment = DialogueSegment(
        uid="System.json:Y:1:gameTitle",
        context="System.json > system.gameTitle",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[source_title],
        original_lines=[source_title],
        source_lines=[source_title],
        segment_kind="system_text",
    )
    segment.translation_lines = [translated_title] if translated_title else [""]
    setattr(segment, "system_text_path", ("gameTitle",))
    return segment


class _Harness(PresentationHelpersMixin):
    def __init__(self, segments: list[DialogueSegment]) -> None:
        self.sessions = {
            Path("System.json"): FileSession(
                path=Path("System.json"),
                data={},
                bundles=[],
                segments=segments,
            )
        }

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, str):
                    lines.append(item)
                elif item is None:
                    lines.append("")
                else:
                    lines.append(str(item))
            return lines or [""]
        if isinstance(value, str):
            return [value]
        return [""]


class PresentationSystemGameTitleTests(unittest.TestCase):
    def test_source_game_title_from_system_session(self) -> None:
        harness = _Harness([_system_segment("JP Title")])

        self.assertEqual(
            harness._system_game_title_from_session(translated=False),
            "JP Title",
        )

    def test_translated_game_title_from_system_session(self) -> None:
        harness = _Harness([_system_segment("JP Title", translated_title="EN Title")])

        self.assertEqual(
            harness._system_game_title_from_session(
                translated=True,
                translated_fallback_to_source=False,
            ),
            "EN Title",
        )

    def test_translated_game_title_falls_back_to_source(self) -> None:
        harness = _Harness([_system_segment("JP Title")])

        self.assertEqual(
            harness._system_game_title_from_session(
                translated=True,
                translated_fallback_to_source=True,
            ),
            "JP Title",
        )
        self.assertEqual(
            harness._system_game_title_from_session(
                translated=True,
                translated_fallback_to_source=False,
            ),
            "",
        )


if __name__ == "__main__":
    unittest.main()
