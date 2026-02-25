from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.audit.audit_core_mixin import AuditCoreMixin
from dialogue_visual_editor.helpers.audit.audit_translation_collision_mixin import (
    AuditTranslationCollisionMixin,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(
    uid: str,
    source_text: str,
    tl_text: str,
    *,
    segment_kind: str = "dialogue",
) -> DialogueSegment:
    source_lines = source_text.split("\n") if source_text else [""]
    tl_lines = tl_text.split("\n") if tl_text else [""]
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(source_lines),
        original_lines=list(source_lines),
        source_lines=list(source_lines),
        segment_kind=segment_kind,
        translation_lines=list(tl_lines),
        original_translation_lines=list(tl_lines),
    )


class _Harness(AuditTranslationCollisionMixin):
    _normalize_audit_translation_lines_for_segment = (
        AuditCoreMixin._normalize_audit_translation_lines_for_segment
    )

    def __init__(self) -> None:
        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}

    def _audit_path_sessions_snapshot(self) -> list[tuple[Path, FileSession]]:
        return list(self.sessions.items())

    @staticmethod
    def _segment_source_lines_for_display(segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    @staticmethod
    def _is_name_index_session(_session: FileSession) -> bool:
        return False

    @staticmethod
    def _name_index_label(_session: FileSession) -> str:
        return "Entry"

    @staticmethod
    def _actor_id_from_uid(_uid: str) -> None:
        return None

    @staticmethod
    def _audit_entry_text_for_segment(
        session: FileSession,
        segment: DialogueSegment,
        index: int,
    ) -> str:
        if segment.segment_kind == "map_display_name":
            return "Map displayName"
        block_index = 0
        for candidate in session.segments:
            if candidate.segment_kind == "map_display_name":
                continue
            block_index += 1
            if candidate.uid == segment.uid:
                return f"Block {block_index}"
        return f"Block {index}"

    @staticmethod
    def _relative_path(path: Path) -> str:
        return str(path)


class AuditTranslationCollisionMixinTests(unittest.TestCase):
    def test_collect_groups_detects_same_translation_with_different_source(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "おはよう", "Good morning"),
                _segment("d2", "こんばんは", "Good morning"),
                _segment("d3", "ありがとう", "Thanks"),
            ],
        )

        groups = harness._collect_audit_translation_collision_groups(
            dialogue_only=True,
            only_translated=True,
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(str(groups[0]["translation_text"]), "Good morning")
        self.assertEqual(int(groups[0]["source_count"]), 2)
        self.assertEqual(int(groups[0]["entry_count"]), 2)

    def test_collect_groups_ignores_same_source_duplicates(self) -> None:
        harness = _Harness()
        path = Path("Map002.json")
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "同じ原文", "Same TL"),
                _segment("d2", "同じ原文", "Same TL"),
            ],
        )

        groups = harness._collect_audit_translation_collision_groups(
            dialogue_only=True,
            only_translated=True,
        )

        self.assertEqual(groups, [])

    def test_collect_groups_respects_only_translated_filter(self) -> None:
        harness = _Harness()
        path = Path("Map003.json")
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "原文A", ""),
                _segment("d2", "原文B", ""),
            ],
        )

        only_translated_groups = harness._collect_audit_translation_collision_groups(
            dialogue_only=True,
            only_translated=True,
        )
        include_empty_groups = harness._collect_audit_translation_collision_groups(
            dialogue_only=True,
            only_translated=False,
        )

        self.assertEqual(only_translated_groups, [])
        self.assertEqual(len(include_empty_groups), 1)
        self.assertEqual(str(include_empty_groups[0]["translation_text"]), "")

    def test_collect_groups_dialogue_only_excludes_non_dialogue_entries(self) -> None:
        harness = _Harness()
        path = Path("Map004.json")
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "台詞A", "Shared TL", segment_kind="dialogue"),
                _segment("n1", "用語B", "Shared TL", segment_kind="name_index"),
            ],
        )

        dialogue_only_groups = harness._collect_audit_translation_collision_groups(
            dialogue_only=True,
            only_translated=True,
        )
        all_groups = harness._collect_audit_translation_collision_groups(
            dialogue_only=False,
            only_translated=True,
        )

        self.assertEqual(dialogue_only_groups, [])
        self.assertEqual(len(all_groups), 1)

    def test_collect_groups_uses_display_numbering_when_map_display_name_exists(self) -> None:
        harness = _Harness()
        path = Path("Map005.json")
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment(
                    "map",
                    "村の名前",
                    "Town",
                    segment_kind="map_display_name",
                ),
                _segment("d1", "説明文", "Town"),
            ],
        )

        groups = harness._collect_audit_translation_collision_groups(
            dialogue_only=False,
            only_translated=True,
        )

        self.assertEqual(len(groups), 1)
        entries = [str(entry["entry"]) for entry in groups[0]["entries"]]
        self.assertIn("Map displayName", entries)
        self.assertIn("Block 1", entries)
        self.assertNotIn("Block 2", entries)


if __name__ == "__main__":
    unittest.main()
