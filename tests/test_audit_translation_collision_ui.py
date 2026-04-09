from __future__ import annotations

import os
from pathlib import Path
import unittest
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem

from helpers.audit.audit_core_mixin import AuditCoreMixin
from helpers.audit.audit_translation_collision_mixin import (
    AuditTranslationCollisionMixin,
)
from helpers.core.models import DialogueSegment, FileSession


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


class _CheckStub:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        self._checked = checked


class _ButtonStub:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _Harness(AuditTranslationCollisionMixin):
    _normalize_audit_translation_lines_for_segment = (
        AuditCoreMixin._normalize_audit_translation_lines_for_segment
    )

    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.audit_translation_collision_groups_list: Any = None
        self.audit_translation_collision_entries_list: Any = None
        self.audit_translation_collision_goto_btn: Any = None
        self.audit_translation_collision_status_label: Any = None
        self.audit_translation_collision_dialogue_only_check: Any = None
        self.audit_translation_collision_only_translated_check: Any = None
        self.jump_calls: list[tuple[str, str]] = []
        self.force_name_index = False

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

    def _is_name_index_session(self, _session: FileSession) -> bool:
        return self.force_name_index

    @staticmethod
    def _name_index_label(_session: FileSession) -> str:
        return "Entry"

    @staticmethod
    def _actor_id_from_uid(uid: str) -> int | None:
        parts = uid.split(":")
        for part in parts:
            if part.isdigit():
                return int(part)
        return None

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

    def _jump_to_audit_location(self, path_raw: str, uid_raw: str) -> None:
        self.jump_calls.append((path_raw, uid_raw))


class AuditTranslationCollisionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_payload_helpers_and_locator(self) -> None:
        harness = _Harness()
        item = QListWidgetItem("group")
        item.setData(Qt.ItemDataRole.UserRole, {"k": "v"})
        bad = QListWidgetItem("bad")
        bad.setData(Qt.ItemDataRole.UserRole, "x")

        self.assertEqual(harness._audit_translation_collision_group_payload(item), {"k": "v"})
        self.assertIsNone(harness._audit_translation_collision_group_payload(bad))
        self.assertEqual(harness._audit_translation_collision_entry_payload(item), {"k": "v"})
        self.assertIsNone(harness._audit_translation_collision_entry_payload(bad))
        self.assertEqual(harness._translation_collision_entry_locator("Map001.json", "Block 12"), "Map001:12")
        self.assertEqual(harness._translation_collision_entry_locator("Map001.json", "Entry"), "Map001:Entry")

    def test_entry_label_fallbacks(self) -> None:
        harness = _Harness()
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[_segment("map", "A", "T", segment_kind="map_display_name"), _segment("d1", "B", "T")],
        )

        map_label = harness._translation_collision_entry_label(session, session.segments[0], 1)
        block_label = harness._translation_collision_entry_label(session, session.segments[1], 2)
        harness.force_name_index = True
        name_label = harness._translation_collision_entry_label(session, session.segments[1], 3)

        self.assertEqual(map_label, "Map displayName")
        self.assertEqual(block_label, "Block 2")
        self.assertEqual(name_label, "Entry 3")

    def test_refresh_entries_populates_and_enables_goto(self) -> None:
        harness = _Harness()
        harness.audit_translation_collision_groups_list = QListWidget()
        harness.audit_translation_collision_entries_list = QListWidget()
        harness.audit_translation_collision_goto_btn = _ButtonStub()

        payload = {
            "entries": [
                {"path": "Map001.json", "uid": "u1", "entry": "Block 1", "source_text": "src one"},
                {"path": "Map001.json", "uid": "u2", "entry": "Block 2", "source_text": "src\ntwo"},
                {"path": "", "uid": "skip", "entry": "Block 3", "source_text": "x"},
            ]
        }
        group_item = QListWidgetItem("Group")
        group_item.setData(Qt.ItemDataRole.UserRole, payload)
        harness.audit_translation_collision_groups_list.addItem(group_item)
        harness.audit_translation_collision_groups_list.setCurrentItem(group_item)

        harness._refresh_audit_translation_collision_entries()

        self.assertEqual(harness.audit_translation_collision_entries_list.count(), 2)
        self.assertEqual(harness.audit_translation_collision_entries_list.currentRow(), 0)
        self.assertTrue(harness.audit_translation_collision_goto_btn.enabled)
        first_text = harness.audit_translation_collision_entries_list.item(0).text()
        self.assertIn("Map001:1", first_text)

    def test_refresh_panel_populates_groups_and_status(self) -> None:
        harness = _Harness()
        harness.audit_translation_collision_dialogue_only_check = _CheckStub(False)
        harness.audit_translation_collision_only_translated_check = _CheckStub(True)
        harness.audit_translation_collision_groups_list = QListWidget()
        harness.audit_translation_collision_entries_list = QListWidget()
        harness.audit_translation_collision_goto_btn = _ButtonStub()
        harness.audit_translation_collision_status_label = QLabel()

        path = Path("Map001.json")
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "原文A", "Shared"),
                _segment("d2", "原文B", "Shared"),
            ],
        )

        harness._refresh_audit_translation_collision_panel()

        self.assertEqual(harness.audit_translation_collision_groups_list.count(), 1)
        self.assertIn("Collision groups: 1", harness.audit_translation_collision_status_label.text())
        self.assertEqual(harness.audit_translation_collision_entries_list.count(), 2)

        harness.audit_translation_collision_only_translated_check.setChecked(False)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[_segment("d1", "原文A", "Unique")],
        )
        harness._refresh_audit_translation_collision_panel()
        self.assertEqual(
            harness.audit_translation_collision_status_label.text(),
            "No translation collisions found.",
        )

    def test_go_to_selected_entry_uses_valid_payload_only(self) -> None:
        harness = _Harness()
        harness.audit_translation_collision_entries_list = QListWidget()

        invalid = QListWidgetItem("Invalid")
        invalid.setData(Qt.ItemDataRole.UserRole, {"path": "", "uid": "u1"})
        harness.audit_translation_collision_entries_list.addItem(invalid)
        harness.audit_translation_collision_entries_list.setCurrentItem(invalid)
        harness._go_to_selected_audit_translation_collision_entry()
        self.assertEqual(harness.jump_calls, [])

        valid = QListWidgetItem("Valid")
        valid.setData(Qt.ItemDataRole.UserRole, {"path": "Map001.json", "uid": "u1"})
        harness.audit_translation_collision_entries_list.addItem(valid)
        harness.audit_translation_collision_entries_list.setCurrentItem(valid)
        harness._go_to_selected_audit_translation_collision_entry()
        self.assertEqual(harness.jump_calls, [("Map001.json", "u1")])


if __name__ == "__main__":
    unittest.main()
