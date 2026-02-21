from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.audit.audit_core_mixin import AuditCoreMixin
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(uid: str, *, kind: str) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        segment_kind=kind,
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=["jp line"],
        original_lines=["jp line"],
        source_lines=["jp line"],
    )


class _StatusBarHarness:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _FileListHarness:
    def __init__(self) -> None:
        self.rows: dict[object, int] = {}
        self.current_row = -1
        self.blocked_values: list[bool] = []

    def row(self, item: object) -> int:
        return self.rows.get(item, -1)

    def setCurrentRow(self, row: int) -> None:
        self.current_row = row

    def blockSignals(self, blocked: bool) -> None:
        self.blocked_values.append(bool(blocked))


class _Harness(AuditCoreMixin):
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.file_items: dict[Path, object] = {}
        self.file_items_scoped: dict[tuple[Path, str], object] = {}
        self.file_list = _FileListHarness()
        self.pending_audit_flash_uid: str | None = None
        self.audit_pinned_uid: str | None = None
        self._status = _StatusBarHarness()
        self.open_calls: list[tuple[Path, str | None, str | None]] = []
        self.flash_targets: list[str] = []
        self.rebuilt_paths: list[Path] = []

    def statusBar(self) -> _StatusBarHarness:
        return self._status

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

    def _rebuild_file_list(self, preferred_path: Path | None = None) -> None:
        if preferred_path is not None:
            self.rebuilt_paths.append(preferred_path)

    def _set_audit_pinned_uid(self, uid: str | None) -> None:
        self.audit_pinned_uid = uid

    def _open_file(
        self,
        path: Path,
        force_reload: bool = False,
        focus_uid: str | None = None,
        view_scope: str | None = None,
    ) -> None:
        _ = force_reload
        self.open_calls.append((path, focus_uid, view_scope))

    def _schedule_audit_target_flash(self, uid: str) -> None:
        self.flash_targets.append(uid)

    @staticmethod
    def _is_misc_segment_kind_for_scope(segment: DialogueSegment) -> bool:
        return segment.segment_kind in {
            "name_index",
            "system_text",
            "plugin_text",
            "plugin_command_text",
            "note_text",
            "actor_name_alias",
        }


class AuditCoreMixinTests(unittest.TestCase):
    def test_jump_to_audit_location_uses_misc_scope_for_misc_uid(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        dialogue_item = object()
        misc_item = object()
        harness.file_items[path] = dialogue_item
        harness.file_items_scoped[(path, "misc")] = misc_item
        harness.file_list.rows[dialogue_item] = 2
        harness.file_list.rows[misc_item] = 5
        harness.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("Map001.json:N:1", kind="note_text")],
        )

        jumped = harness._jump_to_audit_location(str(path), "Map001.json:N:1")

        self.assertTrue(jumped)
        self.assertEqual(harness.file_list.current_row, 5)
        self.assertEqual(
            harness.open_calls,
            [(path, "Map001.json:N:1", "misc")],
        )

    def test_jump_to_audit_location_uses_dialogue_scope_for_dialogue_uid(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        dialogue_item = object()
        harness.file_items[path] = dialogue_item
        harness.file_list.rows[dialogue_item] = 3
        harness.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("Map001.json:1", kind="dialogue")],
        )

        jumped = harness._jump_to_audit_location(str(path), "Map001.json:1")

        self.assertTrue(jumped)
        self.assertEqual(
            harness.open_calls,
            [(path, "Map001.json:1", "dialogue")],
        )

    def test_jump_to_audit_location_handles_missing_uid_scope_as_none(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        dialogue_item = object()
        harness.file_items[path] = dialogue_item
        harness.file_list.rows[dialogue_item] = 1
        harness.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("Map001.json:1", kind="dialogue")],
        )

        jumped = harness._jump_to_audit_location(str(path), "Map001.json:does-not-exist")

        self.assertTrue(jumped)
        self.assertEqual(
            harness.open_calls,
            [(path, "Map001.json:does-not-exist", None)],
        )

    def test_jump_to_audit_location_reports_unloaded_file(self) -> None:
        harness = _Harness()

        jumped = harness._jump_to_audit_location("Map001.json", "Map001.json:1")

        self.assertFalse(jumped)
        self.assertEqual(
            harness.statusBar().messages,
            ["Cannot jump: Map001.json is not loaded."],
        )
        self.assertEqual(harness.open_calls, [])


if __name__ == "__main__":
    unittest.main()
