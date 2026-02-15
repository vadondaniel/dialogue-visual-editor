from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession, NO_SPEAKER_KEY
from dialogue_visual_editor.helpers.mixins.translation_state_mixin import (
    TranslationStateMixin,
)


def _segment(uid: str, text: str, speaker: str = "") -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=[text],
        original_lines=[text],
        source_lines=[text],
    )


class _Harness(TranslationStateMixin):
    def __init__(self) -> None:
        self.translation_state: dict[str, Any] = {"version": 1, "uid_counter": 0, "speaker_map": {}, "files": {}}
        self.speaker_translation_map: dict[str, str] = {}
        self.translation_uid_counter = 0

    def _relative_path(self, path: Path) -> str:
        return path.name

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        return segment.speaker_name


class TranslationStateMixinTests(unittest.TestCase):
    def test_apply_state_name_index_prefers_source_uid_mapping(self) -> None:
        harness = _Harness()
        seg_a = _segment("States.json:S:1:message1", "JP A")
        seg_b = _segment("States.json:S:1:message2", "JP B")
        session = FileSession(
            path=Path("States.json"),
            data=[],
            bundles=[],
            segments=[seg_a, seg_b],
        )
        setattr(session, "is_name_index_session", True)

        harness.translation_state["files"] = {
            "States.json": {
                "order": ["T_B", "T_A"],
                "entries": {
                    "T_A": {
                        "source_uid": "States.json:S:1:message1",
                        "source_hash": "old-a",
                        "translation_lines": ["TL A"],
                    },
                    "T_B": {
                        "source_uid": "States.json:S:1:message2",
                        "source_hash": "old-b",
                        "translation_lines": ["TL B"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["TL A"])
        self.assertEqual(session.segments[1].translation_lines, ["TL B"])
        self.assertEqual(session.segments[0].translation_speaker, "")
        self.assertEqual(session.segments[1].translation_speaker, "")
        self.assertEqual([seg.uid for seg in session.segments], [seg_a.uid, seg_b.uid])

    def test_apply_state_inserts_translation_only_segments_in_saved_order(self) -> None:
        harness = _Harness()
        seg_1 = _segment("Map001.json:L0:0", "JP 1", "Hero")
        seg_2 = _segment("Map001.json:L0:1", "JP 2", "Hero")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[seg_1, seg_2],
        )
        hash_1 = harness._segment_source_hash(seg_1)
        hash_2 = harness._segment_source_hash(seg_2)
        harness.translation_state["files"] = {
            "Map001.json": {
                "order": ["T1", "T_INSERT", "T2"],
                "entries": {
                    "T1": {
                        "source_uid": seg_1.uid,
                        "source_hash": hash_1,
                        "translation_lines": ["TL 1"],
                    },
                    "T_INSERT": {
                        "source_uid": "",
                        "source_hash": "",
                        "translation_only": True,
                        "translation_lines": ["TL insert"],
                        "source_lines": [""],
                        "original_lines": [""],
                    },
                    "T2": {
                        "source_uid": seg_2.uid,
                        "source_hash": hash_2,
                        "translation_lines": ["TL 2"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(len(session.segments), 3)
        self.assertFalse(session.segments[0].translation_only)
        self.assertTrue(session.segments[1].translation_only)
        self.assertFalse(session.segments[2].translation_only)
        self.assertEqual(session.segments[1].translation_lines, ["TL insert"])
        original_order = getattr(session, "_original_tl_order", [])
        self.assertEqual(len(original_order), 3)

    def test_translation_state_for_name_index_clears_speaker_fields(self) -> None:
        harness = _Harness()
        segment = _segment("System.json:Y:1:gameTitle", "JP title", r"\C[2]\N[1]\C[0]")
        segment.translation_lines = ["EN title"]
        segment.translation_speaker = "Should Not Persist"
        session = FileSession(
            path=Path("System.json"),
            data={},
            bundles=[],
            segments=[segment],
        )
        setattr(session, "is_name_index_session", True)

        state = harness._translation_state_for_session(session)
        self.assertEqual(len(state["order"]), 1)
        entry = state["entries"][state["order"][0]]
        self.assertEqual(entry["speaker_jp"], NO_SPEAKER_KEY)
        self.assertEqual(entry["speaker_en"], "")


if __name__ == "__main__":
    unittest.main()
