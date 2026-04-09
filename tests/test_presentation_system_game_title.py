from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from helpers.core.models import DialogueSegment, FileSession
from helpers.mixins.presentation_mixins import (
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


def _config_title_segment(
    source_title: str,
    translated_title: str = "",
) -> DialogueSegment:
    segment = DialogueSegment(
        uid="Config.tjs:Y:1:gameTitle",
        context="Config.tjs > System.title",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[source_title],
        original_lines=[source_title],
        source_lines=[source_title],
        segment_kind="system_text",
    )
    segment.translation_lines = [translated_title] if translated_title else [""]
    setattr(segment, "system_text_path", ("gameTitle",))
    setattr(segment, "tyrano_config_key", "System.title")
    return segment


class _Harness(PresentationHelpersMixin):
    def __init__(self, segments: list[DialogueSegment], *, path: Path | None = None) -> None:
        target_path = path if path is not None else Path("System.json")
        self.sessions = {
            target_path: FileSession(
                path=target_path,
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

    def test_game_title_from_tyrano_config_session(self) -> None:
        harness = _Harness(
            [_config_title_segment("せんていトランス")],
            path=Path("Config.tjs"),
        )

        self.assertEqual(
            harness._system_game_title_from_session(translated=False),
            "せんていトランス",
        )


if __name__ == "__main__":
    unittest.main()
