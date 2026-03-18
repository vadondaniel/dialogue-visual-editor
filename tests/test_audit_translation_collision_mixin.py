from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

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


class _ListStub:
    def __init__(self, current_item: Any = None) -> None:
        self.items: list[Any] = []
        self.current_row = -1
        self._current_item = current_item

    def currentItem(self) -> Any:
        if self._current_item is not None:
            return self._current_item
        if 0 <= self.current_row < len(self.items):
            return self.items[self.current_row]
        return None

    def clear(self) -> None:
        self.items = []
        self.current_row = -1
        self._current_item = None

    def addItem(self, item: Any) -> None:
        self.items.append(item)

    def count(self) -> int:
        return len(self.items)

    def setCurrentRow(self, row: int) -> None:
        self.current_row = row


class _BoolCheckStub:
    def __init__(self, checked: bool) -> None:
        self.checked = checked

    def isChecked(self) -> bool:
        return self.checked


class _ButtonStub:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, value: bool) -> None:
        self.enabled = bool(value)


class _LabelStub:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, value: str) -> None:
        self.text = value


class _UIHarness(_Harness):
    def __init__(self) -> None:
        super().__init__()
        self.audit_translation_collision_groups_list: Any = _ListStub()
        self.audit_translation_collision_entries_list: Any = _ListStub()
        self.audit_translation_collision_goto_btn: Any = _ButtonStub()
        self.audit_translation_collision_dialogue_only_check: Any = _BoolCheckStub(True)
        self.audit_translation_collision_only_translated_check: Any = _BoolCheckStub(True)
        self.audit_translation_collision_status_label: Any = _LabelStub()
        self.jump_calls: list[tuple[str, str]] = []

    def _jump_to_audit_location(self, path_raw: str, uid_raw: str) -> None:
        self.jump_calls.append((path_raw, uid_raw))


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

    def test_entry_payload_and_name_index_label_branches(self) -> None:
        harness = _Harness()
        self.assertIsNone(harness._audit_translation_collision_entry_payload(None))

        class _NameIndexHarness(_Harness):
            @staticmethod
            def _is_name_index_session(_session: FileSession) -> bool:
                return True

            @staticmethod
            def _actor_id_from_uid(_uid: str) -> int:
                return 7

        name_harness = _NameIndexHarness()
        name_harness._audit_entry_text_for_segment = None
        session = FileSession(path=Path("Actors.json"), data=[], bundles=[], segments=[])
        segment = _segment("Actors.json:1", "src", "tl", segment_kind="name_index")
        self.assertEqual(
            name_harness._translation_collision_entry_label(session, segment, 3),
            "Entry ID 7",
        )

    def test_collect_groups_skips_empty_source_and_uses_translation_normalization_fallbacks(self) -> None:
        path = Path("Map006.json")

        raising_harness = _Harness()
        raising_harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "", "Shared"),
                _segment("d2", "原文A", "Shared"),
                _segment("d3", "原文B", "Shared"),
            ],
        )

        def _raise_normalize(_segment: DialogueSegment, _value: Any) -> list[str]:
            raise RuntimeError("normalize failed")

        raising_harness._normalize_audit_translation_lines_for_segment = _raise_normalize
        raising_groups = raising_harness._collect_audit_translation_collision_groups(
            dialogue_only=True,
            only_translated=True,
        )
        self.assertEqual(len(raising_groups), 1)
        self.assertEqual(int(raising_groups[0]["entry_count"]), 2)

        plain_harness = _Harness()
        plain_harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d4", "原文C", "Same"),
                _segment("d5", "原文D", "Same"),
            ],
        )
        plain_harness._normalize_audit_translation_lines_for_segment = None
        plain_groups = plain_harness._collect_audit_translation_collision_groups(
            dialogue_only=True,
            only_translated=True,
        )
        self.assertEqual(len(plain_groups), 1)
        self.assertEqual(str(plain_groups[0]["translation_text"]), "Same")

    def test_refresh_entries_handles_invalid_payload_shapes_and_defaults(self) -> None:
        harness = _UIHarness()
        harness.audit_translation_collision_groups_list = None
        harness._refresh_audit_translation_collision_entries()

        group_item = QListWidgetItem("group")
        group_item.setData(Qt.ItemDataRole.UserRole, {"entries": "bad"})
        harness.audit_translation_collision_groups_list = _ListStub(current_item=group_item)
        harness.audit_translation_collision_entries_list = _ListStub()
        harness.audit_translation_collision_goto_btn = _ButtonStub()
        harness._refresh_audit_translation_collision_entries()
        self.assertEqual(harness.audit_translation_collision_entries_list.count(), 0)

        valid_group_item = QListWidgetItem("group")
        valid_group_item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "entries": [
                    "skip",
                    {"path": "Map001.json", "entry": "Block 1", "source_text": "x"},
                    {"path": "Map001.json", "uid": "", "entry": "Block 1", "source_text": "x"},
                    {"path": "Map001.json", "uid": "u1", "entry": 5, "source_text": None},
                ]
            },
        )
        harness.audit_translation_collision_groups_list = _ListStub(
            current_item=valid_group_item
        )
        harness.audit_translation_collision_entries_list = _ListStub()
        harness.audit_translation_collision_goto_btn = _ButtonStub()
        harness._refresh_audit_translation_collision_entries()

        self.assertEqual(harness.audit_translation_collision_entries_list.count(), 1)
        entry_item = harness.audit_translation_collision_entries_list.items[0]
        self.assertIn("Entry", entry_item.text())
        self.assertIn("(empty source)", entry_item.text())
        self.assertTrue(harness.audit_translation_collision_goto_btn.enabled)

    def test_refresh_panel_handles_missing_widgets_selection_and_empty_state_messages(self) -> None:
        harness = _UIHarness()
        harness.audit_translation_collision_status_label = None
        harness._refresh_audit_translation_collision_panel()

        preselected = QListWidgetItem("selected")
        preselected.setData(Qt.ItemDataRole.UserRole, {"translation_text": "Shared TL"})
        harness = _UIHarness()
        harness.audit_translation_collision_groups_list = _ListStub(current_item=preselected)
        harness._collect_audit_translation_collision_groups = (
            lambda dialogue_only, only_translated: [
                {
                    "translation_text": "Other TL",
                    "entries": [{"path": "Map001.json", "uid": "u1", "entry": "Block 1", "source_text": "A"}],
                    "entry_count": 1,
                    "source_count": 1,
                },
                {
                    "translation_text": "Shared TL",
                    "entries": [{"path": "Map002.json", "uid": "u2", "entry": "Block 2", "source_text": "B"}],
                    "entry_count": 1,
                    "source_count": 1,
                },
            ]
        )
        harness._refresh_audit_translation_collision_panel()
        self.assertEqual(harness.audit_translation_collision_groups_list.current_row, 1)

        empty_harness = _UIHarness()
        empty_harness.audit_translation_collision_only_translated_check = _BoolCheckStub(
            True
        )
        empty_harness._refresh_audit_translation_collision_panel()
        self.assertEqual(
            empty_harness.audit_translation_collision_status_label.text,
            "No translation collisions found (translated entries only).",
        )

    def test_go_to_selected_entry_defensive_paths(self) -> None:
        harness = _UIHarness()
        harness.audit_translation_collision_entries_list = None
        harness._go_to_selected_audit_translation_collision_entry()
        self.assertEqual(harness.jump_calls, [])

        harness.audit_translation_collision_entries_list = _ListStub()
        harness._go_to_selected_audit_translation_collision_entry()
        self.assertEqual(harness.jump_calls, [])

        invalid_uid_item = QListWidgetItem("invalid")
        invalid_uid_item.setData(
            Qt.ItemDataRole.UserRole,
            {"path": "Map001.json", "uid": ""},
        )
        harness.audit_translation_collision_entries_list = _ListStub(
            current_item=invalid_uid_item
        )
        harness._go_to_selected_audit_translation_collision_entry()
        self.assertEqual(harness.jump_calls, [])


if __name__ == "__main__":
    unittest.main()
