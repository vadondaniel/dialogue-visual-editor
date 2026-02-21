from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession
from dialogue_visual_editor.helpers.mixins.presentation_mixins import PresentationHelpersMixin


def _actor_segment(uid: str, text: str, *, alias: bool = False) -> DialogueSegment:
    segment = DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, text]},
        lines=[text],
        original_lines=[text],
        source_lines=[text],
        segment_kind="actor_name_alias" if alias else "name_index",
    )
    if alias:
        setattr(segment, "is_actor_name_alias", True)
    return segment


class _Harness(PresentationHelpersMixin):
    def __init__(self, segments: list[DialogueSegment]) -> None:
        self.sessions = {
            Path("Actors.json"): FileSession(
                path=Path("Actors.json"),
                data=[],
                bundles=[],
                segments=segments,
            )
        }
        self.speaker_translation_map: dict[str, str] = {}

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [item if isinstance(item, str) else "" for item in value] or [""]
        if isinstance(value, str):
            return [value]
        return [""]

    def _normalize_speaker_key(self, value: str) -> str:
        return value.strip()

    def _speaker_translation_for_key(self, speaker_key: str) -> str:
        return self.speaker_translation_map.get(speaker_key, "")


class PresentationActorNameMapsTests(unittest.TestCase):
    def test_actor_name_maps_ignore_alias_segments(self) -> None:
        main = _actor_segment("Actors.json:A:1", "Harold")
        alias = _actor_segment("Actors.json:A:1:alt_1", "ヒナタ", alias=True)
        harness = _Harness([main, alias])
        session = harness.sessions[Path("Actors.json")]
        setattr(session, "is_actor_index_session", True)
        setattr(session, "name_index_kind", "actor")

        jp_by_id, _en_by_id = harness._actor_name_maps()

        self.assertEqual(jp_by_id.get(1), "Harold")


if __name__ == "__main__":
    unittest.main()
