from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.audit.audit_consistency_mixin import (
    AuditConsistencyMixin,
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


class _Harness(AuditConsistencyMixin):
    def __init__(self) -> None:
        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}

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


class AuditConsistencyMixinTests(unittest.TestCase):
    def test_dialogue_only_excludes_non_dialogue_sources(self) -> None:
        harness = _Harness()
        path = Path("Mixed.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "重複語", "Alpha", segment_kind="dialogue"),
                _segment("d2", "重複語", "Beta", segment_kind="dialogue"),
                _segment("n1", "重複語", "Gamma", segment_kind="name_index"),
            ],
        )

        groups_dialogue_only = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=True,
            sort_mode="source_order",
        )
        groups_all = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups_dialogue_only), 1)
        self.assertEqual(int(groups_dialogue_only[0]["entry_count"]), 2)
        self.assertEqual(len(groups_all), 1)
        self.assertEqual(int(groups_all[0]["entry_count"]), 3)

    def test_dialogue_only_can_hide_non_dialogue_only_duplicates(self) -> None:
        harness = _Harness()
        path = Path("System.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("s1", "通貨単位", "Gold", segment_kind="system_text"),
                _segment("s2", "通貨単位", "Coin", segment_kind="system_text"),
            ],
        )

        groups_dialogue_only = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=True,
            sort_mode="source_order",
        )
        groups_all = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(groups_dialogue_only, [])
        self.assertEqual(len(groups_all), 1)


if __name__ == "__main__":
    unittest.main()
