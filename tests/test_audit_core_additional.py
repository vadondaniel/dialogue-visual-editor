from __future__ import annotations

import os
from pathlib import Path
import unittest
from typing import Any
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from dialogue_visual_editor.helpers.audit.audit_core_mixin import AuditCoreMixin
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(uid: str, *, kind: str = "dialogue") -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        segment_kind=kind,
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=["jp"],
        original_lines=["jp"],
        source_lines=["jp"],
        translation_lines=["tl"],
        original_translation_lines=["tl"],
    )


class _TimerStub:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _OverlayStub:
    def __init__(self, visible: bool = True) -> None:
        self.visible = visible
        self.hide_calls = 0

    def isVisible(self) -> bool:
        return self.visible

    def hide(self) -> None:
        self.visible = False
        self.hide_calls += 1


class _ClearStub:
    def __init__(self) -> None:
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _FileListStub:
    def __init__(self) -> None:
        self.rows: dict[object, int] = {}
        self.current_row = -1
        self.blocked: list[bool] = []

    def row(self, item: object) -> int:
        return self.rows.get(item, -1)

    def setCurrentRow(self, row: int) -> None:
        self.current_row = row

    def blockSignals(self, blocked: bool) -> None:
        self.blocked.append(bool(blocked))


class _FlashWidget:
    def __init__(self) -> None:
        self.flash_calls = 0

    def flash_highlight(self) -> None:
        self.flash_calls += 1


class _Harness(AuditCoreMixin):
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.file_paths: list[Path] = []
        self.file_items: dict[Path, object] = {}
        self.file_items_scoped: dict[tuple[Path, str], object] = {}
        self.file_list = _FileListStub()
        self.pending_audit_flash_uid: str | None = None
        self.audit_pinned_uid: str | None = None
        self.block_widgets: dict[str, object] = {}
        self._status = _StatusBarStub()
        self.rebuilt_paths: list[Path] = []
        self.open_calls: list[tuple[Path, str | None, str | None]] = []
        self.refresh_visual_state_calls = 0

        self.audit_search_render_timer = _TimerStub()
        self.audit_sanitize_render_timer = _TimerStub()
        self.audit_control_mismatch_render_timer = _TimerStub()
        self.audit_term_render_timer = _TimerStub()
        self.audit_term_hits_render_timer = _TimerStub()
        self.audit_search_progress_overlay = _OverlayStub()
        self.audit_sanitize_progress_overlay = _OverlayStub()
        self.audit_control_mismatch_progress_overlay = _OverlayStub()
        self.audit_term_variants_progress_overlay = _OverlayStub()
        self.audit_term_hits_progress_overlay = _OverlayStub()

        self.audit_search_render_records = ["x"]
        self.audit_search_render_index = 4
        self.audit_search_render_query = "abc"
        self.audit_search_render_scope = "translation"
        self.audit_search_render_generation = 77

        self.audit_sanitize_render_records = ["x"]
        self.audit_sanitize_render_index = 2
        self.audit_sanitize_render_rule_id = "r"
        self.audit_sanitize_render_find_text = "a"
        self.audit_sanitize_render_show_field_label = True
        self.audit_sanitize_render_generation = 88
        self.audit_sanitize_render_scope = "both"
        self.audit_sanitize_render_total_hits = 9
        self.audit_sanitize_render_entries = 5
        self.audit_sanitize_render_block_count = 3

        self.audit_control_mismatch_render_records = ["x"]
        self.audit_control_mismatch_render_index = 9
        self.audit_control_mismatch_render_scanned_blocks = 6
        self.audit_control_mismatch_render_only_translated = False
        self.audit_control_mismatch_render_generation = 99

        self.audit_term_render_groups = ["x"]
        self.audit_term_render_index = 5
        self.audit_term_render_generation = 10
        self.audit_term_render_term = "term"
        self.audit_term_render_candidates = "cand"
        self.audit_term_render_dialogue_only = False
        self.audit_term_hits_render_entries = ["x"]
        self.audit_term_hits_render_index = 3
        self.audit_term_hits_render_group_key = "k"
        self._audit_term_hits_render_candidates = ["x"]

        self.audit_cache_generation = 5
        self.audit_search_cache_key = ("old",)
        self.audit_search_cache_records = ["old"]
        self.audit_sanitize_counts_cache_key = ("old",)
        self.audit_sanitize_counts_cache = {"x": 1}
        self.audit_sanitize_occurrence_cache_key = ("old",)
        self.audit_sanitize_occurrence_cache_payload = {"x": 1}
        self.audit_sanitize_occurrence_cache_by_key = {"x": {"y": 2}}
        self.audit_control_mismatch_cache_key = ("old",)
        self.audit_control_mismatch_cache_records = ["old"]
        self.audit_control_mismatch_cache_scanned_blocks = 9
        self.audit_search_displayed_key = ("x",)
        self.audit_search_display_complete = True
        self.audit_sanitize_displayed_key = ("x",)
        self.audit_sanitize_display_complete = True
        self.audit_sanitize_built_view_keys = {"x"}
        self.audit_sanitize_active_view_key = ("x",)
        self.audit_control_mismatch_displayed_key = ("x",)
        self.audit_control_mismatch_display_complete = True
        self.audit_term_cache_key = ("x",)
        self.audit_term_cache_groups = ["x"]
        self.audit_term_displayed_key = ("x",)
        self.audit_term_display_complete = True
        self.audit_sanitize_occurrences_list = _ClearStub()
        self.audit_search_worker_pending_request = {"x": 1}
        self.audit_sanitize_worker_pending_request = {"x": 1}
        self.audit_control_worker_pending_request = {"x": 1}
        self.audit_term_worker_pending_request = {"x": 1}

    def statusBar(self) -> _StatusBarStub:
        return self._status

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

    @staticmethod
    def _is_misc_segment_kind_for_scope(segment: DialogueSegment) -> bool:
        return segment.segment_kind == "note_text"

    def _rebuild_file_list(self, preferred_path: Path | None = None) -> None:
        if preferred_path is not None:
            self.rebuilt_paths.append(preferred_path)

    def _open_file(
        self,
        path: Path,
        force_reload: bool = False,
        focus_uid: str | None = None,
        view_scope: str | None = None,
    ) -> None:
        _ = force_reload
        self.open_calls.append((path, focus_uid, view_scope))

    def _refresh_block_visual_states(self) -> None:
        self.refresh_visual_state_calls += 1


class _ViewportHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._viewport = QWidget(self)

    def viewport(self) -> QWidget:
        return self._viewport


class AuditCoreAdditionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_scope_and_pin_helpers(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        harness.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("u1", kind="note_text"), _segment("u2", kind="dialogue")],
        )

        scope_misc = harness._scope_for_audit_target_uid(path, "u1")
        scope_dialogue = harness._scope_for_audit_target_uid(path, "u2")
        missing_scope = harness._scope_for_audit_target_uid(path, "missing")
        unloaded_scope = harness._scope_for_audit_target_uid(Path("Missing.json"), "u1")
        harness._set_audit_pinned_uid("u2")

        self.assertEqual(scope_misc, "misc")
        self.assertEqual(scope_dialogue, "dialogue")
        self.assertIsNone(missing_scope)
        self.assertIsNone(unloaded_scope)
        self.assertEqual(harness.audit_pinned_uid, "u2")
        self.assertEqual(harness.refresh_visual_state_calls, 1)

    def test_overlay_creation_setting_and_hiding(self) -> None:
        harness = _Harness()
        host = _ViewportHost()
        host.resize(160, 80)
        host.viewport().resize(160, 80)
        host.show()
        QApplication.processEvents()
        overlay = harness._create_audit_progress_overlay(host)

        self.assertFalse(overlay.isVisible())
        self.assertIs(harness._overlay_host_widget(host), host.viewport())

        harness._set_audit_progress_overlay(host, overlay, "Scanning...")
        self.assertTrue(overlay.isVisible())
        self.assertEqual(overlay.text(), "Scanning...")

        harness._hide_audit_progress_overlay(overlay)
        self.assertFalse(overlay.isVisible())
        host.hide()

    def test_path_snapshot_and_request_keys(self) -> None:
        harness = _Harness()
        p1 = Path("a.json")
        p2 = Path("b.json")
        harness.file_paths = [p1, p2]
        harness.sessions[p1] = FileSession(path=p1, data={}, bundles=[], segments=[])
        snapshot = harness._audit_path_sessions_snapshot()
        search_key = harness._search_request_key({"generation": 1, "scope": "original", "needle": "x", "case_sensitive": True, "natural_mode": False})
        sanitize_key = harness._sanitize_request_key({"mode": "full", "generation": 2, "scope": "both", "selected_rule_id": "r", "selected_find_text": "a"})
        control_key = harness._control_request_key({"generation": 3, "only_translated": True})

        self.assertEqual(snapshot, [(p1, harness.sessions[p1])])
        self.assertEqual(search_key, (1, "original", "x", True, False))
        self.assertEqual(sanitize_key, ("full", 2, "both", "r", "a"))
        self.assertEqual(control_key, (3, True))
        self.assertEqual(harness._search_request_key(None), ())
        self.assertEqual(harness._sanitize_request_key(None), ())
        self.assertEqual(harness._control_request_key(None), ())

    def test_stop_render_helpers_reset_state(self) -> None:
        harness = _Harness()

        harness._stop_audit_search_render()
        harness._stop_audit_sanitize_render()
        harness._stop_audit_control_mismatch_render()
        harness._stop_audit_term_render()

        self.assertEqual(harness.audit_search_render_timer.stop_calls, 1)
        self.assertEqual(harness.audit_sanitize_render_timer.stop_calls, 1)
        self.assertEqual(harness.audit_control_mismatch_render_timer.stop_calls, 1)
        self.assertEqual(harness.audit_term_render_timer.stop_calls, 1)
        self.assertEqual(harness.audit_term_hits_render_timer.stop_calls, 1)
        self.assertEqual(harness.audit_search_render_records, [])
        self.assertEqual(harness.audit_sanitize_render_records, [])
        self.assertEqual(harness.audit_control_mismatch_render_records, [])
        self.assertEqual(harness.audit_term_render_groups, [])
        self.assertEqual(harness.audit_term_hits_render_entries, [])

    def test_invalidate_audit_caches_resets_caches_and_pending_requests(self) -> None:
        harness = _Harness()

        harness._invalidate_audit_caches()

        self.assertEqual(harness.audit_cache_generation, 6)
        self.assertIsNone(harness.audit_search_cache_key)
        self.assertEqual(harness.audit_search_cache_records, [])
        self.assertIsNone(harness.audit_sanitize_counts_cache_key)
        self.assertEqual(harness.audit_sanitize_counts_cache, {})
        self.assertIsNone(harness.audit_sanitize_occurrence_cache_key)
        self.assertIsNone(harness.audit_sanitize_occurrence_cache_payload)
        self.assertEqual(harness.audit_control_mismatch_cache_records, [])
        self.assertEqual(harness.audit_term_cache_groups, [])
        self.assertIsNone(harness.audit_search_worker_pending_request)
        self.assertIsNone(harness.audit_sanitize_worker_pending_request)
        self.assertIsNone(harness.audit_control_worker_pending_request)
        self.assertIsNone(harness.audit_term_worker_pending_request)
        self.assertEqual(harness.audit_sanitize_occurrences_list.clear_calls, 1)

    def test_audit_highlight_style_light_and_dark(self) -> None:
        harness = _Harness()
        with patch(
            "dialogue_visual_editor.helpers.audit.audit_core_mixin.is_dark_palette",
            return_value=True,
        ):
            dark = harness._audit_highlight_style()
        with patch(
            "dialogue_visual_editor.helpers.audit.audit_core_mixin.is_dark_palette",
            return_value=False,
        ):
            light = harness._audit_highlight_style()

        self.assertIn("#facc15", dark)
        self.assertIn("#fde047", light)

    def test_schedule_flash_and_flash_target(self) -> None:
        harness = _Harness()
        flash_widget = _FlashWidget()
        harness.block_widgets["u1"] = flash_widget
        harness.pending_audit_flash_uid = "u1"
        delays: list[int] = []

        def _single_shot(delay_ms: int, callback: Any) -> None:
            delays.append(int(delay_ms))
            callback()

        with patch.object(QTimer, "singleShot", side_effect=_single_shot):
            harness._schedule_audit_target_flash("u1")

        self.assertEqual(delays, [0, 90, 220])
        self.assertEqual(flash_widget.flash_calls, 1)
        self.assertIsNone(harness.pending_audit_flash_uid)
        self.assertEqual(harness.audit_pinned_uid, "u1")

    def test_jump_location_rebuilds_when_file_item_missing(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        harness.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("u1", kind="dialogue")],
        )

        jumped = harness._jump_to_audit_location(str(path), "u1")

        self.assertTrue(jumped)
        self.assertEqual(harness.rebuilt_paths, [path])
        self.assertEqual(harness.open_calls, [(path, "u1", "dialogue")])
        self.assertIn("Jumped to Map001.json (u1).", harness.statusBar().messages[-1])


if __name__ == "__main__":
    unittest.main()
