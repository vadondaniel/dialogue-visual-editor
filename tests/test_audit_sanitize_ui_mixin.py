from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem

from dialogue_visual_editor.helpers.audit.audit_constants import SANITIZE_CHAR_RULES
from dialogue_visual_editor.helpers.audit.audit_sanitize_ui_mixin import (
    AuditSanitizeUiMixin,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(uid: str, *, segment_kind: str = "dialogue") -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=["jp"],
        original_lines=["jp"],
        source_lines=["jp"],
        segment_kind=segment_kind,
        translation_lines=["tl"],
        original_translation_lines=["tl"],
    )


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _ComboStub:
    def __init__(self, value: str) -> None:
        self._value = value

    def currentData(self) -> str:
        return self._value


class _ButtonStub:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _TimerStub:
    def __init__(self) -> None:
        self.started_with: list[int] = []

    def start(self, interval_ms: int) -> None:
        self.started_with.append(interval_ms)


class _Harness(AuditSanitizeUiMixin):
    def __init__(self) -> None:
        self.audit_sanitize_scope_combo: Any = None
        self.audit_sanitize_rules_list: Any = None
        self.audit_sanitize_summary_label: Any = None
        self.audit_sanitize_occurrences_list: Any = None
        self.audit_sanitize_goto_btn: Any = None
        self.audit_sanitize_apply_selected_btn: Any = None
        self.audit_sanitize_progress_overlay: object = object()
        self.audit_sanitize_active_view_key: tuple[int, str, str] | None = None
        self.audit_sanitize_ignored_entries_by_rule: dict[str, set[tuple[str, str]]] = {}
        self.audit_sanitize_total_hits = 0
        self.audit_sanitize_rules_with_hits = 0
        self.audit_sanitize_counts_cache_key: tuple[int, str] | None = None
        self.audit_sanitize_counts_cache: dict[str, int] = {}
        self.audit_sanitize_occurrence_cache_key: tuple[int, str, str] | None = None
        self.audit_sanitize_occurrence_cache_payload: dict[str, Any] = {}
        self.audit_sanitize_occurrence_cache_by_key: dict[
            tuple[int, str, str], dict[str, Any]
        ] = {}
        self.audit_sanitize_built_view_keys: set[tuple[int, str, str]] = set()
        self.audit_sanitize_render_records: list[dict[str, Any]] = []
        self.audit_sanitize_render_index = 0
        self.audit_sanitize_render_generation = 0
        self.audit_sanitize_render_scope = "original"
        self.audit_sanitize_render_rule_id = ""
        self.audit_sanitize_render_find_text = ""
        self.audit_sanitize_render_show_field_label = False
        self.audit_sanitize_render_total_hits = 0
        self.audit_sanitize_render_entries = 0
        self.audit_sanitize_render_block_count = 0
        self.audit_sanitize_display_complete = False
        self.audit_sanitize_displayed_key: tuple[int, str, str] | None = None
        self.audit_cache_generation = 1
        self.audit_result_batch_size = 10
        self.audit_render_batch_interval_ms = 7
        self.audit_sanitize_render_timer = _TimerStub()
        self.invalidate_cache_calls = 0
        self.refresh_panel_calls = 0
        self.hide_overlay_calls = 0
        self.stop_render_calls = 0
        self.overlay_messages: list[str] = []
        self.queued_requests: list[dict[str, Any]] = []
        self.apply_rules_calls: list[list[dict[str, str]]] = []
        self.apply_entry_calls: list[tuple[dict[str, str], str, str]] = []
        self.jump_calls: list[tuple[str, str]] = []
        self.path_sessions: list[tuple[Path, FileSession]] = []
        self.status_bar = _StatusBarStub()

    def statusBar(self) -> _StatusBarStub:
        return self.status_bar

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

    @staticmethod
    def _audit_highlight_style() -> str:
        return "background:#ff0;"

    @staticmethod
    def _is_name_index_session(session: FileSession) -> bool:
        return bool(getattr(session, "is_name_index_session", False))

    @staticmethod
    def _name_index_label(session: FileSession | None) -> str:
        if session is None:
            return "Entry"
        value = getattr(session, "name_index_label", "")
        if isinstance(value, str) and value.strip():
            return value
        return "Entry"

    @staticmethod
    def _actor_id_from_uid(uid: str) -> int | None:
        marker = ":A:"
        if marker not in uid:
            return None
        suffix = uid.split(marker, 1)[1]
        raw = suffix.split(":", 1)[0]
        if raw.isdigit():
            return int(raw)
        return None

    def _invalidate_audit_caches(self) -> None:
        self.invalidate_cache_calls += 1

    def _refresh_audit_sanitize_panel(self) -> None:
        self.refresh_panel_calls += 1
        super()._refresh_audit_sanitize_panel()

    def _set_audit_progress_overlay(
        self,
        _list_widget: object,
        _overlay: object,
        message: str,
    ) -> None:
        self.overlay_messages.append(message)

    def _hide_audit_progress_overlay(self, _overlay: object) -> None:
        self.hide_overlay_calls += 1

    def _stop_audit_sanitize_render(self) -> None:
        self.stop_render_calls += 1

    def _audit_path_sessions_snapshot(self) -> list[tuple[Path, FileSession]]:
        return list(self.path_sessions)

    def _queue_audit_sanitize_worker(self, request: dict[str, Any]) -> None:
        self.queued_requests.append(dict(request))

    def _apply_audit_sanitize_rules(self, rules: list[dict[str, str]]) -> None:
        self.apply_rules_calls.append(list(rules))

    def _apply_audit_sanitize_rule_to_entry(
        self,
        rule_payload: dict[str, str],
        path_raw: str,
        uid: str,
    ) -> None:
        self.apply_entry_calls.append((dict(rule_payload), path_raw, uid))

    def _jump_to_audit_location(self, path_raw: str, uid: str) -> None:
        self.jump_calls.append((path_raw, uid))


class _FakeItem:
    def __init__(self, payloads: dict[int, object]) -> None:
        self._payloads = dict(payloads)
        self.hidden = False
        self.text = ""

    def data(self, role: int) -> object:
        return self._payloads.get(role)

    def setText(self, value: str) -> None:
        self.text = value

    def setHidden(self, hidden: bool) -> None:
        self.hidden = bool(hidden)


class _FakeList:
    def __init__(self, items: list[object], current_row: int = -1) -> None:
        self._items = list(items)
        self._current_row = current_row

    def itemAt(self, _pos: object) -> object | None:
        if not self._items:
            return None
        return self._items[0]

    def row(self, item: object) -> int:
        try:
            return self._items.index(item)
        except ValueError:
            return -1

    def currentRow(self) -> int:
        return self._current_row

    def setCurrentRow(self, row: int) -> None:
        self._current_row = int(row)

    def currentItem(self) -> object | None:
        if self._current_row < 0 or self._current_row >= len(self._items):
            return None
        return self._items[self._current_row]

    def viewport(self) -> "_FakeList":
        return self

    def mapToGlobal(self, pos: object) -> object:
        return pos

    def count(self) -> int:
        return len(self._items)

    def item(self, row: int) -> object:
        return self._items[row]


class _FakeMenu:
    choose_label = ""

    def __init__(self, _parent: object) -> None:
        self._actions: dict[str, object] = {}

    def addAction(self, label: str) -> object:
        action = object()
        self._actions[label] = action
        return action

    def addSeparator(self) -> None:
        return

    def exec(self, _pos: object) -> object | None:
        return self._actions.get(self.choose_label)


class AuditSanitizeUiMixinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_display_index_and_entry_text(self) -> None:
        harness = _Harness()
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[
                _segment("Map001.json:map_display_name", segment_kind="map_display_name"),
                _segment("Map001.json:L0:0"),
            ],
        )

        map_name_index = harness._audit_display_index_for_segment(
            session,
            session.segments[0],
            9,
        )
        block_index = harness._audit_display_index_for_segment(
            session,
            session.segments[1],
            9,
        )
        map_entry = harness._audit_entry_text_for_segment(
            session,
            session.segments[0],
            1,
        )
        block_entry = harness._audit_entry_text_for_segment(
            session,
            session.segments[1],
            2,
        )

        name_session = FileSession(
            path=Path("Actors.json"),
            data={},
            bundles=[],
            segments=[_segment("Actors.json:A:3:name", segment_kind="name_index")],
        )
        setattr(name_session, "is_name_index_session", True)
        setattr(name_session, "name_index_label", "Actor")
        name_entry = harness._audit_entry_text_for_segment(
            name_session,
            name_session.segments[0],
            5,
        )

        self.assertEqual(map_name_index, 0)
        self.assertEqual(block_index, 1)
        self.assertEqual(map_entry, "Map displayName")
        self.assertEqual(block_entry, "Block 1")
        self.assertEqual(name_entry, "Actor ID 3")

    def test_highlight_scope_and_rule_payload_helpers(self) -> None:
        harness = _Harness()
        highlighted = harness._highlight_audit_literal_html("A < B\nA", "A")
        empty_highlight = harness._highlight_audit_literal_html("A < B", "")
        default_scope = harness._audit_sanitize_scope()
        harness.audit_sanitize_scope_combo = _ComboStub("both")
        selected_scope = harness._audit_sanitize_scope()

        valid = QListWidgetItem("Rule")
        valid.setData(
            Qt.ItemDataRole.UserRole,
            {
                "rule_id": "r",
                "label": "Rule",
                "find_text": "「",
                "replace_text": '"',
            },
        )
        invalid = QListWidgetItem("Invalid")
        invalid.setData(
            Qt.ItemDataRole.UserRole,
            {"rule_id": "r", "label": "Rule", "find_text": "", "replace_text": '"'},
        )

        payload = harness._audit_sanitize_rule_payload(valid)
        missing_payload = harness._audit_sanitize_rule_payload(invalid)
        by_id = harness._audit_sanitize_rule_payload_by_id(SANITIZE_CHAR_RULES[0][0])
        missing_by_id = harness._audit_sanitize_rule_payload_by_id("missing_rule")

        self.assertIn("<span style=\"background:#ff0;\">A</span>", highlighted)
        self.assertIn("&lt; B", highlighted)
        self.assertIn("<br>", highlighted)
        self.assertEqual(empty_highlight, "A &lt; B")
        self.assertEqual(default_scope, "original")
        self.assertEqual(selected_scope, "both")
        self.assertEqual(payload, {"rule_id": "r", "label": "Rule", "find_text": "「", "replace_text": '"'})
        self.assertIsNone(missing_payload)
        self.assertIsNotNone(by_id)
        self.assertIsNone(missing_by_id)

    def test_ignored_entry_round_trip_updates_cache_and_refresh(self) -> None:
        harness = _Harness()

        self.assertFalse(harness._is_audit_sanitize_entry_ignored("r1", "Map001.json", "u1"))
        harness._set_audit_sanitize_entry_ignored("r1", "Map001.json", "u1", True)
        self.assertTrue(harness._is_audit_sanitize_entry_ignored("r1", "Map001.json", "u1"))
        harness._set_audit_sanitize_entry_ignored("r1", "Map001.json", "u1", False)

        self.assertFalse(harness._is_audit_sanitize_entry_ignored("r1", "Map001.json", "u1"))
        self.assertEqual(harness.invalidate_cache_calls, 2)
        self.assertEqual(harness.refresh_panel_calls, 2)
        self.assertEqual(harness.audit_sanitize_ignored_entries_by_rule, {})

    def test_occurrence_payload_and_view_key_parsing(self) -> None:
        harness = _Harness()
        item = QListWidgetItem("Occurrence")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {"path": "Map001.json", "uid": "u1", "rule_id": "r1"},
        )
        item.setData(Qt.ItemDataRole.UserRole + 1, (3, "both", "r1"))
        parsed_payload = harness._audit_sanitize_occurrence_payload(item)
        parsed_view_key = harness._audit_sanitize_occurrence_view_key_from_item(item)

        invalid = QListWidgetItem("Invalid")
        invalid.setData(Qt.ItemDataRole.UserRole, {"path": "", "uid": "u1", "rule_id": "r1"})
        invalid.setData(Qt.ItemDataRole.UserRole + 1, ("bad", "both", "r1"))

        self.assertEqual(parsed_payload, {"path": "Map001.json", "uid": "u1", "rule_id": "r1"})
        self.assertEqual(parsed_view_key, (3, "both", "r1"))
        self.assertIsNone(harness._audit_sanitize_occurrence_payload(invalid))
        self.assertIsNone(harness._audit_sanitize_occurrence_view_key_from_item(invalid))

    def test_set_occurrence_view_visibility_toggles_rows_and_goto_button(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_goto_btn = _ButtonStub()
        first = QListWidgetItem("first")
        first.setData(Qt.ItemDataRole.UserRole + 1, (1, "original", "r1"))
        second = QListWidgetItem("second")
        second.setData(Qt.ItemDataRole.UserRole + 1, (1, "both", "r2"))
        harness.audit_sanitize_occurrences_list.addItem(first)
        harness.audit_sanitize_occurrences_list.addItem(second)

        harness._set_audit_sanitize_occurrence_view_visibility((1, "both", "r2"))

        self.assertTrue(first.isHidden())
        self.assertFalse(second.isHidden())
        self.assertEqual(harness.audit_sanitize_occurrences_list.currentRow(), 1)
        self.assertTrue(harness.audit_sanitize_goto_btn.enabled)
        self.assertEqual(harness.audit_sanitize_active_view_key, (1, "both", "r2"))

        harness._set_audit_sanitize_occurrence_view_visibility((9, "both", "missing"))
        self.assertEqual(harness.audit_sanitize_occurrences_list.currentRow(), -1)
        self.assertFalse(harness.audit_sanitize_goto_btn.enabled)

    def test_add_occurrence_result_renders_ignored_rows_and_respects_active_view_key(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_active_view_key = (99, "original", "r9")
        harness._add_audit_sanitize_occurrence_result(
            path=Path("Map001.json"),
            uid="u1",
            rule_id="r1",
            entry_text="Block 1",
            occurrences=[
                {
                    "field_label": "Source",
                    "line_index": 1,
                    "hit_count": 2,
                    "line_text": "A「B」A",
                    "ignored": True,
                }
            ],
            find_text="A",
            show_field_label=True,
            view_key=(1, "original", "r1"),
        )

        self.assertEqual(harness.audit_sanitize_occurrences_list.count(), 1)
        item = harness.audit_sanitize_occurrences_list.item(0)
        widget = harness.audit_sanitize_occurrences_list.itemWidget(item)
        self.assertIsInstance(widget, QLabel)
        assert isinstance(widget, QLabel)
        self.assertTrue(item.isHidden())
        self.assertIn("[Ignored]", widget.text())
        self.assertIn("Ignored for selected rule", widget.text())
        self.assertIn("L1 x2", widget.text())

    def test_apply_payload_no_selected_rule_updates_counts_and_clears_view(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_rules_list = QListWidget()
        harness.audit_sanitize_summary_label = QLabel()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_goto_btn = _ButtonStub()

        rule1 = QListWidgetItem("Rule 1")
        rule1.setData(
            Qt.ItemDataRole.UserRole,
            {"rule_id": "r1", "label": "Rule 1", "find_text": "「", "replace_text": '"'},
        )
        rule2 = QListWidgetItem("Rule 2")
        rule2.setData(
            Qt.ItemDataRole.UserRole,
            {"rule_id": "r2", "label": "Rule 2", "find_text": "」", "replace_text": '"'},
        )
        harness.audit_sanitize_rules_list.addItem(rule1)
        harness.audit_sanitize_rules_list.addItem(rule2)
        harness.audit_sanitize_occurrences_list.addItem(QListWidgetItem("existing"))

        harness._apply_audit_sanitize_payload(
            generation=3,
            scope="original",
            selected_rule_id="",
            selected_find_text="",
            payload={"counts": {"r1": 4, "r2": 0}},
        )

        self.assertIn("Rule 1 | hits: 4", rule1.text())
        self.assertIn("Rule 2 | hits: 0", rule2.text())
        self.assertEqual(harness.audit_sanitize_total_hits, 4)
        self.assertEqual(harness.audit_sanitize_rules_with_hits, 1)
        self.assertEqual(harness.audit_sanitize_counts_cache_key, (3, "original"))
        self.assertEqual(harness.audit_sanitize_counts_cache, {"r1": 4, "r2": 0})
        self.assertIn("Potential replacements: 4", harness.audit_sanitize_summary_label.text())
        self.assertTrue(harness.audit_sanitize_display_complete)
        self.assertEqual(harness.audit_sanitize_displayed_key, (3, "original", ""))
        self.assertEqual(harness.hide_overlay_calls, 1)

    def test_apply_payload_selected_rule_handles_empty_and_built_views(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_rules_list = QListWidget()
        harness.audit_sanitize_summary_label = QLabel()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_goto_btn = _ButtonStub()
        rule = QListWidgetItem("Rule")
        rule.setData(
            Qt.ItemDataRole.UserRole,
            {"rule_id": "r1", "label": "Rule", "find_text": "「", "replace_text": '"'},
        )
        harness.audit_sanitize_rules_list.addItem(rule)
        existing = QListWidgetItem("existing")
        existing.setData(Qt.ItemDataRole.UserRole + 1, (4, "both", "r1"))
        harness.audit_sanitize_occurrences_list.addItem(existing)

        harness._apply_audit_sanitize_payload(
            generation=4,
            scope="both",
            selected_rule_id="r1",
            selected_find_text="「",
            payload={"counts": {"r1": 1}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0},
        )
        self.assertIn("Selected rule: 0 hits in 0 lines across 0 blocks", harness.audit_sanitize_summary_label.text())
        self.assertTrue(harness.audit_sanitize_display_complete)

        harness.audit_sanitize_built_view_keys.add((4, "both", "r1"))
        harness._apply_audit_sanitize_payload(
            generation=4,
            scope="both",
            selected_rule_id="r1",
            selected_find_text="「",
            payload={
                "counts": {"r1": 3},
                "records": [{"path": Path("Map001.json"), "uid": "u1", "entry_text": "Block 1", "occurrences": []}],
                "total_hits": 3,
                "entries": 2,
                "block_count": 1,
            },
        )
        self.assertIn("Selected rule: 3 hits in 2 lines across 1 block", harness.audit_sanitize_summary_label.text())
        self.assertTrue(harness.audit_sanitize_display_complete)
        self.assertEqual(harness.audit_sanitize_active_view_key, (4, "both", "r1"))

    def test_apply_payload_starts_render_for_new_view(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_rules_list = QListWidget()
        harness.audit_sanitize_summary_label = QLabel()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_goto_btn = _ButtonStub()
        rule = QListWidgetItem("Rule")
        rule.setData(
            Qt.ItemDataRole.UserRole,
            {"rule_id": "r1", "label": "Rule", "find_text": "「", "replace_text": '"'},
        )
        harness.audit_sanitize_rules_list.addItem(rule)
        render_calls = {"count": 0}

        def _render_stub() -> None:
            render_calls["count"] += 1

        harness._render_next_audit_sanitize_occurrence_batch = _render_stub  # type: ignore[method-assign]
        harness._apply_audit_sanitize_payload(
            generation=5,
            scope="both",
            selected_rule_id="r1",
            selected_find_text="「",
            payload={
                "counts": {"r1": 2},
                "records": [{"path": Path("Map001.json"), "uid": "u1", "entry_text": "Block 1", "occurrences": []}],
                "total_hits": 2,
                "entries": 1,
                "block_count": 1,
            },
        )

        self.assertEqual(render_calls["count"], 1)
        self.assertEqual(harness.audit_sanitize_render_generation, 5)
        self.assertEqual(harness.audit_sanitize_render_scope, "both")
        self.assertEqual(harness.audit_sanitize_render_rule_id, "r1")
        self.assertFalse(harness.audit_sanitize_display_complete)
        self.assertIn("Rendering 0/1", harness.overlay_messages[-1])

    def test_refresh_panel_fast_path_and_cache_paths(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_rules_list = QListWidget()
        harness.audit_sanitize_summary_label = QLabel()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_goto_btn = _ButtonStub()
        harness.audit_sanitize_apply_selected_btn = _ButtonStub()
        rule = QListWidgetItem("Rule")
        rule.setData(
            Qt.ItemDataRole.UserRole,
            {"rule_id": "r1", "label": "Rule", "find_text": "「", "replace_text": '"'},
        )
        harness.audit_sanitize_rules_list.addItem(rule)
        harness.audit_sanitize_rules_list.setCurrentItem(rule)
        harness.audit_sanitize_rules_list.setCurrentRow(0)
        harness.audit_sanitize_scope_combo = _ComboStub("both")
        harness._audit_sanitize_rule_payload = (  # type: ignore[method-assign]
            lambda _item: {
                "rule_id": "r1",
                "label": "Rule",
                "find_text": "「",
                "replace_text": '"',
            }
        )

        requested_key = (harness.audit_cache_generation, "both", "r1")
        harness.audit_sanitize_display_complete = True
        harness.audit_sanitize_displayed_key = requested_key
        harness._refresh_audit_sanitize_panel()
        self.assertTrue(harness.audit_sanitize_apply_selected_btn.enabled)
        self.assertEqual(harness.hide_overlay_calls, 1)
        self.assertEqual(harness.stop_render_calls, 0)

        apply_calls: list[dict[str, Any]] = []

        def _apply_capture(**kwargs: Any) -> None:
            apply_calls.append(dict(kwargs))

        harness._apply_audit_sanitize_payload = _apply_capture  # type: ignore[method-assign]
        harness.audit_sanitize_display_complete = False
        harness.audit_sanitize_displayed_key = None
        harness.audit_sanitize_counts_cache_key = (
            harness.audit_cache_generation,
            "both",
        )
        harness.audit_sanitize_counts_cache = {"r1": 2}
        harness.audit_sanitize_occurrence_cache_by_key = {
            requested_key: {"records": [], "total_hits": 2, "entries": 1, "block_count": 1}
        }
        harness._refresh_audit_sanitize_panel()
        self.assertEqual(len(apply_calls), 1)
        self.assertEqual(harness.queued_requests, [])

    def test_refresh_panel_queues_occurrence_or_full_scans(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_rules_list = QListWidget()
        harness.audit_sanitize_summary_label = QLabel()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_goto_btn = _ButtonStub()
        harness.audit_sanitize_apply_selected_btn = _ButtonStub()
        rule = QListWidgetItem("Rule")
        rule.setData(
            Qt.ItemDataRole.UserRole,
            {"rule_id": "r1", "label": "Rule", "find_text": "「", "replace_text": '"'},
        )
        harness.audit_sanitize_rules_list.addItem(rule)
        harness.audit_sanitize_rules_list.setCurrentItem(rule)
        harness.audit_sanitize_rules_list.setCurrentRow(0)
        harness.audit_sanitize_scope_combo = _ComboStub("original")
        harness._audit_sanitize_rule_payload = (  # type: ignore[method-assign]
            lambda _item: {
                "rule_id": "r1",
                "label": "Rule",
                "find_text": "「",
                "replace_text": '"',
            }
        )
        harness.audit_sanitize_ignored_entries_by_rule = {"r1": {("Map001.json", "u1")}}
        harness.audit_sanitize_counts_cache_key = (
            harness.audit_cache_generation,
            "original",
        )
        harness.audit_sanitize_counts_cache = {"r1": 3}

        harness._refresh_audit_sanitize_panel()
        self.assertEqual(harness.queued_requests[0]["mode"], "occurrences")
        self.assertEqual(harness.queued_requests[0]["selected_ignored"], {("Map001.json", "u1")})
        self.assertEqual(harness.audit_sanitize_summary_label.text(), "Scanning selected rule...")

        harness2 = _Harness()
        harness2.audit_sanitize_rules_list = QListWidget()
        harness2.audit_sanitize_summary_label = QLabel()
        harness2.audit_sanitize_occurrences_list = QListWidget()
        harness2.audit_sanitize_goto_btn = _ButtonStub()
        harness2.audit_sanitize_apply_selected_btn = _ButtonStub()
        harness2.audit_sanitize_scope_combo = _ComboStub("translation")
        harness2.audit_sanitize_ignored_entries_by_rule = {"r2": {("Map002.json", "u2")}}
        harness2._refresh_audit_sanitize_panel()

        self.assertEqual(harness2.queued_requests[0]["mode"], "full")
        self.assertEqual(
            harness2.queued_requests[0]["ignored_entries_by_rule"],
            {"r2": {("Map002.json", "u2")}},
        )
        self.assertEqual(harness2.audit_sanitize_summary_label.text(), "Scanning sanitize results...")

    def test_render_next_batch_partial_completion_and_error_paths(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_occurrences_list = QListWidget()
        harness.audit_sanitize_goto_btn = _ButtonStub()
        harness.audit_sanitize_summary_label = QLabel()
        harness.audit_sanitize_total_hits = 8
        harness.audit_sanitize_rules_with_hits = 2
        harness.audit_sanitize_render_generation = 9
        harness.audit_sanitize_render_scope = "both"
        harness.audit_sanitize_render_rule_id = "r1"
        harness.audit_sanitize_render_find_text = "「"
        harness.audit_sanitize_render_show_field_label = True
        harness.audit_sanitize_render_total_hits = 8
        harness.audit_sanitize_render_entries = 2
        harness.audit_sanitize_render_block_count = 2
        harness.audit_sanitize_render_records = [
            {
                "path": Path("Map001.json"),
                "uid": "u1",
                "entry_text": "Block 1",
                "occurrences": [{"field_label": "Source", "line_index": 1, "hit_count": 1, "line_text": "「A」"}],
            },
            {
                "path": Path("Map001.json"),
                "uid": "u2",
                "entry_text": "Block 2",
                "occurrences": [{"field_label": "Source", "line_index": 2, "hit_count": 1, "line_text": "「B」"}],
            },
        ]
        harness.audit_result_batch_size = 1

        harness._render_next_audit_sanitize_occurrence_batch()
        self.assertEqual(harness.audit_sanitize_render_index, 1)
        self.assertEqual(harness.audit_sanitize_occurrences_list.count(), 1)
        self.assertIn("Rendering 1/2", harness.overlay_messages[-1])
        self.assertEqual(harness.audit_sanitize_render_timer.started_with[-1], harness.audit_render_batch_interval_ms)

        harness._render_next_audit_sanitize_occurrence_batch()
        self.assertEqual(harness.audit_sanitize_render_index, 2)
        self.assertTrue(harness.audit_sanitize_display_complete)
        self.assertIn((9, "both", "r1"), harness.audit_sanitize_built_view_keys)
        self.assertEqual(harness.stop_render_calls, 1)

        failing = _Harness()
        failing.audit_sanitize_occurrences_list = QListWidget()
        failing.audit_sanitize_goto_btn = _ButtonStub()
        failing.audit_sanitize_summary_label = QLabel()
        failing.audit_sanitize_render_records = [
            {
                "path": Path("Map001.json"),
                "uid": "u1",
                "entry_text": "Block 1",
                "occurrences": [],
            }
        ]
        failing._add_audit_sanitize_occurrence_result = (  # type: ignore[method-assign]
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        failing._render_next_audit_sanitize_occurrence_batch()
        self.assertEqual(failing.stop_render_calls, 1)
        self.assertEqual(failing.audit_sanitize_summary_label.text(), "Sanitize render failed: boom")

    def test_go_to_selected_occurrence_validates_payload(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_occurrences_list = QListWidget()
        invalid = QListWidgetItem("Invalid")
        invalid.setData(Qt.ItemDataRole.UserRole, {"path": "", "uid": "u1"})
        harness.audit_sanitize_occurrences_list.addItem(invalid)
        harness.audit_sanitize_occurrences_list.setCurrentItem(invalid)

        harness._go_to_selected_audit_sanitize_occurrence()
        self.assertEqual(harness.jump_calls, [])

        valid = QListWidgetItem("Valid")
        valid.setData(Qt.ItemDataRole.UserRole, {"path": "Map001.json", "uid": "u1"})
        harness.audit_sanitize_occurrences_list.addItem(valid)
        harness.audit_sanitize_occurrences_list.setCurrentItem(valid)
        harness._go_to_selected_audit_sanitize_occurrence()
        self.assertEqual(harness.jump_calls, [("Map001.json", "u1")])

    def test_rules_context_menu_apply_action(self) -> None:
        harness = _Harness()
        item = _FakeItem(
            {
                Qt.ItemDataRole.UserRole: {
                    "rule_id": "r1",
                    "label": "Rule 1",
                    "find_text": "「",
                    "replace_text": '"',
                }
            }
        )
        harness.audit_sanitize_rules_list = _FakeList([item], current_row=-1)
        _FakeMenu.choose_label = "Apply Rule"

        with patch(
            "dialogue_visual_editor.helpers.audit.audit_sanitize_ui_mixin.QMenu",
            _FakeMenu,
        ):
            harness._on_audit_sanitize_rules_context_menu(object())

        self.assertEqual(harness.audit_sanitize_rules_list.currentRow(), 0)
        self.assertEqual(
            harness.apply_rules_calls,
            [[{"rule_id": "r1", "label": "Rule 1", "find_text": "「", "replace_text": '"'}]],
        )

    def test_occurrences_context_menu_branches(self) -> None:
        harness = _Harness()
        rule_id = SANITIZE_CHAR_RULES[0][0]
        item = _FakeItem(
            {
                Qt.ItemDataRole.UserRole: {
                    "path": "Map001.json",
                    "uid": "u1",
                    "rule_id": rule_id,
                }
            }
        )
        harness.audit_sanitize_occurrences_list = _FakeList([item], current_row=-1)

        with patch(
            "dialogue_visual_editor.helpers.audit.audit_sanitize_ui_mixin.QMenu",
            _FakeMenu,
        ):
            _FakeMenu.choose_label = "Go To"
            harness._on_audit_sanitize_occurrences_context_menu(object())
            _FakeMenu.choose_label = "Apply Rule To Entry"
            harness._on_audit_sanitize_occurrences_context_menu(object())
            _FakeMenu.choose_label = "Ignore Entry"
            harness._on_audit_sanitize_occurrences_context_menu(object())

        self.assertEqual(harness.audit_sanitize_occurrences_list.currentRow(), 0)
        self.assertEqual(harness.jump_calls, [("Map001.json", "u1")])
        self.assertEqual(len(harness.apply_entry_calls), 1)
        self.assertTrue(harness._is_audit_sanitize_entry_ignored(rule_id, "Map001.json", "u1"))
        self.assertEqual(harness.status_bar.messages[-1], "Entry ignored.")


if __name__ == "__main__":
    unittest.main()
