from __future__ import annotations

import os
from pathlib import Path
import unittest
from typing import Any
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem, QMessageBox

from dialogue_visual_editor.helpers.audit.audit_search_mixin import AuditSearchMixin
from dialogue_visual_editor.helpers.core.models import FileSession


class _LineEditStub:
    def __init__(self, value: str) -> None:
        self._value = value

    def text(self) -> str:
        return self._value

    def setText(self, value: str) -> None:
        self._value = value


class _CheckStub:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        self._checked = checked


class _ComboStub:
    def __init__(self, value: str) -> None:
        self._value = value

    def currentData(self) -> str:
        return self._value


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _ButtonStub:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _WorkerTimerStub:
    def __init__(self) -> None:
        self.started: list[int] = []

    def start(self, interval_ms: int) -> None:
        self.started.append(int(interval_ms))


class _WorkerFutureStub:
    def __init__(self, *, done: bool, payload: Any = None, error: Exception | None = None) -> None:
        self._done = done
        self._payload = payload
        self._error = error

    def done(self) -> bool:
        return self._done

    def result(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._payload


class _WorkerExecutorStub:
    def __init__(self, future: _WorkerFutureStub | None = None, error: Exception | None = None) -> None:
        self.future = future or _WorkerFutureStub(done=False)
        self.error = error
        self.submit_calls = 0

    def submit(self, _fn: Any, *_args: Any) -> _WorkerFutureStub:
        self.submit_calls += 1
        if self.error is not None:
            raise self.error
        return self.future


class _Harness(AuditSearchMixin):
    def __init__(self) -> None:
        self.audit_search_results_list = QListWidget()
        self.audit_search_query_edit = _LineEditStub("")
        self.audit_search_replace_edit = _LineEditStub("")
        self.audit_search_scope_combo = _ComboStub("both")
        self.audit_search_case_sensitive_check = _CheckStub(False)
        self.audit_search_status_label = QLabel()
        self.audit_search_goto_btn = _ButtonStub()
        self.audit_search_replace_selected_btn = _ButtonStub()
        self.audit_search_replace_all_btn = _ButtonStub()
        self.audit_search_display_complete = True
        self.audit_search_timer = None

        self.current_path: Path | None = None
        self.sessions: dict[Path, FileSession] = {}
        self.selected_segment_uid = "uid-current"

        self._status_bar = _StatusBarStub()
        self.jump_calls: list[tuple[str, str]] = []
        self.replace_outcomes: dict[tuple[str, str, str], tuple[bool, int]] = {}
        self.replace_calls: list[tuple[str, str, str]] = []
        self.invalidate_calls = 0
        self.refresh_sanitize_calls = 0
        self.refresh_control_calls = 0
        self.refresh_collision_calls = 0
        self.refresh_name_calls = 0
        self.render_session_calls = 0
        self.refresh_translator_calls = 0
        self.run_search_calls = 0

    def statusBar(self) -> _StatusBarStub:
        return self._status_bar

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

    @staticmethod
    def _audit_highlight_style() -> str:
        return "background:#ff0;"

    def _jump_to_audit_location(self, path_raw: str, uid_raw: str) -> None:
        self.jump_calls.append((path_raw, uid_raw))

    def _replace_in_session_entry(
        self,
        path_raw: str,
        uid: str,
        find_text: str,
        replace_text: str,
        matched_scope: str,
        case_sensitive: bool,
    ) -> tuple[bool, int]:
        _ = find_text, replace_text, case_sensitive
        key = (path_raw, uid, matched_scope)
        self.replace_calls.append(key)
        return self.replace_outcomes.get(key, (False, 0))

    def _invalidate_audit_caches(self) -> None:
        self.invalidate_calls += 1

    def _refresh_audit_sanitize_panel(self) -> None:
        self.refresh_sanitize_calls += 1

    def _refresh_audit_control_mismatch_panel(self) -> None:
        self.refresh_control_calls += 1

    def _refresh_audit_translation_collision_panel(self) -> None:
        self.refresh_collision_calls += 1

    def _refresh_audit_name_consistency_panel(self) -> None:
        self.refresh_name_calls += 1

    def _render_session(self, _session: FileSession, *, focus_uid: str, preserve_scroll: bool) -> None:
        _ = focus_uid, preserve_scroll
        self.render_session_calls += 1

    def _refresh_translator_detail_panel(self) -> None:
        self.refresh_translator_calls += 1

    def _run_audit_search(self) -> None:
        self.run_search_calls += 1


class _WorkerHarness(AuditSearchMixin):
    def __init__(self) -> None:
        self.audit_cache_generation = 1
        self.audit_search_worker_future: Any = None
        self.audit_search_worker_running_request: Any = None
        self.audit_search_worker_pending_request: Any = None
        self.audit_search_worker_timer = _WorkerTimerStub()
        self.audit_worker_executor: Any = _WorkerExecutorStub()

        self.audit_search_query_edit: Any = _LineEditStub("alpha")
        self.audit_search_scope_combo: Any = _ComboStub("both")
        self.audit_search_case_sensitive_check: Any = _CheckStub(False)
        self.audit_search_results_list: Any = QListWidget()
        self.audit_search_status_label: Any = QLabel()
        self.audit_search_goto_btn: Any = _ButtonStub()
        self.audit_search_replace_selected_btn: Any = _ButtonStub()
        self.audit_search_replace_all_btn: Any = _ButtonStub()
        self.audit_search_progress_overlay: Any = object()

        self.audit_search_cache_key: Any = None
        self.audit_search_cache_records: list[dict[str, Any]] = []
        self.audit_search_render_records: list[dict[str, Any]] = []
        self.audit_search_render_index = 0
        self.audit_search_render_generation = 0
        self.audit_search_render_query = ""
        self.audit_search_render_needle = ""
        self.audit_search_render_natural_mode = False
        self.audit_search_render_case_sensitive = False
        self.audit_search_render_scope = "both"
        self.audit_search_render_timer = _WorkerTimerStub()
        self.audit_render_batch_interval_ms = 7
        self.audit_search_displayed_key: Any = None
        self.audit_search_display_complete = False
        self.overlay_messages: list[str] = []

    @staticmethod
    def _search_request_key(request: dict[str, Any] | None) -> tuple[Any, ...]:
        if not isinstance(request, dict):
            return ()
        return (
            request.get("generation"),
            request.get("scope"),
            request.get("needle"),
            request.get("case_sensitive"),
            request.get("natural_mode"),
        )

    def _set_audit_progress_overlay(
        self,
        _target_widget: Any,
        _overlay: Any,
        text: str,
    ) -> None:
        self.overlay_messages.append(str(text))


def _add_result_item(
    harness: _Harness,
    *,
    path: str = "Map001.json",
    uid: str = "u1",
    matched_scope: str = "both",
) -> QListWidgetItem:
    item = QListWidgetItem("item")
    item.setData(
        Qt.ItemDataRole.UserRole,
        {
            "path": path,
            "uid": uid,
            "matched_scope": matched_scope,
            "entry_text": "Block 1",
            "matched_field": "Original",
            "matched_text": "alpha beta",
        },
    )
    harness.audit_search_results_list.addItem(item)
    return item


class AuditSearchUiUtilsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_search_mode_helpers_and_natural_spans(self) -> None:
        harness = _Harness()

        self.assertTrue(harness._is_control_code_search_query(r"\C[2]"))
        self.assertFalse(harness._is_control_code_search_query("plain"))
        self.assertTrue(harness._audit_search_uses_natural_mode("魔王"))
        self.assertFalse(harness._audit_search_uses_natural_mode("魔 王"))
        self.assertFalse(harness._audit_search_uses_natural_mode(r"\N[2]魔王"))
        self.assertEqual(
            harness._normalize_text_for_natural_search(r" A \C[2]  B ", case_sensitive=False),
            "ab",
        )
        spans = harness._natural_match_spans(r"A \C[2] B C", "abc", case_sensitive=False)
        self.assertEqual(spans, [(0, 11)])

    def test_highlight_add_result_and_preview(self) -> None:
        harness = _Harness()
        no_query = harness._highlight_audit_match_html("A<B", "", "", False, False)
        literal = harness._highlight_audit_match_html("alpha beta", "alpha", "alpha", False, True)
        natural = harness._highlight_audit_match_html(r"A \C[2] B", "AB", "ab", True, False)

        self.assertEqual(no_query, "A&lt;B")
        self.assertIn("background:#ff0;", literal)
        self.assertIn("background:#ff0;", natural)

        harness._add_audit_search_result(
            path=Path("Map001.json"),
            uid="u1",
            entry_text="Block 1",
            matched_field="Original",
            matched_text="alpha beta",
            query="alpha",
            needle="alpha",
            natural_mode=False,
            case_sensitive=True,
        )
        self.assertEqual(harness.audit_search_results_list.count(), 1)
        item = harness.audit_search_results_list.item(0)
        widget = harness.audit_search_results_list.itemWidget(item)
        self.assertIsInstance(widget, QLabel)
        assert isinstance(widget, QLabel)
        self.assertIn("Map001.json | Block 1 | Original", widget.text())

        harness.audit_search_query_edit.setText("alpha")
        harness.audit_search_replace_edit.setText("omega")
        harness._refresh_audit_search_replace_preview()
        updated_widget = harness.audit_search_results_list.itemWidget(item)
        self.assertIsInstance(updated_widget, QLabel)
        assert isinstance(updated_widget, QLabel)
        self.assertIn("line-through", updated_widget.text())

    def test_selected_payload_scope_and_go_to(self) -> None:
        harness = _Harness()
        item = _add_result_item(harness, matched_scope="translation")
        harness.audit_search_results_list.setCurrentItem(item)

        payload = harness._selected_audit_search_payload()
        self.assertEqual(payload, {"path": "Map001.json", "uid": "u1", "scope": "translation"})
        self.assertEqual(harness._scope_from_matched_field("Translation"), "translation")
        self.assertEqual(harness._scope_from_matched_field("Original"), "original")
        self.assertEqual(harness._scope_from_matched_field("x"), "both")

        harness._go_to_selected_audit_result()
        self.assertEqual(harness.jump_calls, [("Map001.json", "u1")])

    def test_selected_payload_and_go_to_guard_paths(self) -> None:
        harness = _Harness()
        harness.audit_search_results_list = None
        self.assertIsNone(harness._selected_audit_search_payload())
        harness._go_to_selected_audit_result()
        self.assertEqual(harness.jump_calls, [])

        harness.audit_search_results_list = QListWidget()
        self.assertIsNone(harness._selected_audit_search_payload())
        harness._go_to_selected_audit_result()
        self.assertEqual(harness.jump_calls, [])

        non_dict = QListWidgetItem("bad")
        non_dict.setData(Qt.ItemDataRole.UserRole, "bad")
        harness.audit_search_results_list.addItem(non_dict)
        harness.audit_search_results_list.setCurrentItem(non_dict)
        self.assertIsNone(harness._selected_audit_search_payload())
        harness._go_to_selected_audit_result()

        missing_path = QListWidgetItem("missing path")
        missing_path.setData(Qt.ItemDataRole.UserRole, {"uid": "u1"})
        harness.audit_search_results_list.addItem(missing_path)
        harness.audit_search_results_list.setCurrentItem(missing_path)
        self.assertIsNone(harness._selected_audit_search_payload())
        harness._go_to_selected_audit_result()

        missing_uid = QListWidgetItem("missing uid")
        missing_uid.setData(Qt.ItemDataRole.UserRole, {"path": "Map001.json"})
        harness.audit_search_results_list.addItem(missing_uid)
        harness.audit_search_results_list.setCurrentItem(missing_uid)
        self.assertIsNone(harness._selected_audit_search_payload())
        harness._go_to_selected_audit_result()
        self.assertEqual(harness.jump_calls, [])

    def test_replace_regex_and_inline_diff(self) -> None:
        harness = _Harness()
        regex = harness._replace_regex_for_case("alpha", case_sensitive=False)
        html_diff, count = harness._inline_replace_diff_html(
            "Alpha alpha",
            "alpha",
            "omega",
            case_sensitive=False,
        )
        no_find_html, no_find_count = harness._inline_replace_diff_html(
            "text",
            "",
            "x",
            case_sensitive=True,
        )

        self.assertTrue(regex.search("ALPHA"))
        self.assertEqual(count, 2)
        self.assertIn("line-through", html_diff)
        self.assertEqual(no_find_html, "text")
        self.assertEqual(no_find_count, 0)

    def test_refresh_replace_preview_guard_paths(self) -> None:
        harness = _Harness()
        harness.audit_search_results_list = None
        harness._refresh_audit_search_replace_preview()

        harness.audit_search_results_list = QListWidget()
        harness.audit_search_query_edit = None
        harness._refresh_audit_search_replace_preview()

        harness.audit_search_query_edit = _LineEditStub("alpha")
        harness.audit_search_replace_edit = _LineEditStub("beta")
        bad_payload = QListWidgetItem("bad")
        bad_payload.setData(Qt.ItemDataRole.UserRole, "bad")
        bad_path = QListWidgetItem("bad path")
        bad_path.setData(
            Qt.ItemDataRole.UserRole,
            {
                "path": "",
                "uid": "u1",
                "entry_text": 3,
                "matched_field": None,
                "matched_text": None,
            },
        )
        harness.audit_search_results_list.addItem(bad_payload)
        harness.audit_search_results_list.addItem(bad_path)
        harness._refresh_audit_search_replace_preview()

    def test_replace_selected_result_branches_and_success(self) -> None:
        harness = _Harness()

        harness._replace_selected_audit_search_result()
        self.assertEqual(harness.statusBar().messages[-1], "Select a search result first.")

        item = _add_result_item(harness)
        harness.audit_search_results_list.setCurrentItem(item)
        harness.audit_search_query_edit.setText("")
        harness._replace_selected_audit_search_result()
        self.assertEqual(harness.statusBar().messages[-1], "Enter text in Find first.")

        harness.audit_search_query_edit.setText("alpha")
        harness.audit_search_replace_edit.setText("omega")
        harness._replace_selected_audit_search_result()
        self.assertEqual(
            harness.statusBar().messages[-1],
            "No replacements applied for selected result.",
        )

        outcome_key = ("Map001.json", "u1", "both")
        harness.replace_outcomes[outcome_key] = (True, 2)
        harness._replace_selected_audit_search_result()
        self.assertEqual(harness.invalidate_calls, 1)
        self.assertEqual(harness.refresh_sanitize_calls, 1)
        self.assertEqual(harness.refresh_control_calls, 1)
        self.assertEqual(harness.refresh_collision_calls, 1)
        self.assertEqual(harness.refresh_name_calls, 1)
        self.assertEqual(harness.refresh_translator_calls, 1)
        self.assertEqual(harness.run_search_calls, 1)
        self.assertEqual(
            harness.statusBar().messages[-1],
            "Replaced 2 matches in selected result.",
        )

    def test_replace_all_branches_and_success(self) -> None:
        harness = _Harness()
        harness.audit_search_display_complete = False
        harness._replace_all_audit_search_results()
        self.assertEqual(
            harness.statusBar().messages[-1],
            "Wait for search to finish before Replace All.",
        )

        harness.audit_search_display_complete = True
        harness.audit_search_query_edit.setText("")
        harness._replace_all_audit_search_results()
        self.assertEqual(harness.statusBar().messages[-1], "Enter text in Find first.")

        harness.audit_search_query_edit.setText("alpha")
        harness._replace_all_audit_search_results()
        self.assertEqual(harness.statusBar().messages[-1], "No search results to replace.")

        item_a = _add_result_item(harness, path="Map001.json", uid="u1", matched_scope="original")
        item_b = _add_result_item(harness, path="Map001.json", uid="u1", matched_scope="original")
        item_c = _add_result_item(harness, path="Map001.json", uid="u2", matched_scope="translation")
        harness.audit_search_results_list.setCurrentItem(item_a)
        _ = item_b, item_c
        harness.audit_search_replace_edit.setText("omega")

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            harness._replace_all_audit_search_results()
        self.assertEqual(harness.replace_calls, [])

        session_path = Path("Map001.json")
        harness.current_path = session_path
        harness.sessions[session_path] = FileSession(
            path=session_path,
            data={},
            bundles=[],
            segments=[],
        )
        harness.replace_outcomes[("Map001.json", "u1", "original")] = (True, 2)
        harness.replace_outcomes[("Map001.json", "u2", "translation")] = (False, 0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            harness._replace_all_audit_search_results()

        self.assertEqual(harness.invalidate_calls, 1)
        self.assertEqual(harness.refresh_sanitize_calls, 1)
        self.assertEqual(harness.refresh_control_calls, 1)
        self.assertEqual(harness.refresh_collision_calls, 1)
        self.assertEqual(harness.refresh_name_calls, 1)
        self.assertEqual(harness.render_session_calls, 1)
        self.assertEqual(harness.run_search_calls, 1)
        self.assertEqual(
            harness.statusBar().messages[-1],
            "Replaced 2 matches in 1 result entry.",
        )

    def test_replace_all_required_widget_and_invalid_payload_paths(self) -> None:
        harness = _Harness()
        harness.audit_search_scope_combo = None
        harness._replace_all_audit_search_results()
        self.assertEqual(harness.statusBar().messages, [])

        harness = _Harness()
        harness.audit_search_display_complete = True
        harness.audit_search_query_edit.setText("alpha")
        bad = QListWidgetItem("bad")
        bad.setData(Qt.ItemDataRole.UserRole, "bad")
        missing_path = QListWidgetItem("missing path")
        missing_path.setData(Qt.ItemDataRole.UserRole, {"uid": "u1", "matched_scope": "both"})
        missing_uid = QListWidgetItem("missing uid")
        missing_uid.setData(Qt.ItemDataRole.UserRole, {"path": "Map001.json", "matched_scope": "both"})
        harness.audit_search_results_list.addItem(bad)
        harness.audit_search_results_list.addItem(missing_path)
        harness.audit_search_results_list.addItem(missing_uid)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            harness._replace_all_audit_search_results()
        self.assertEqual(harness.statusBar().messages[-1], "No replacements applied.")

    def test_replace_all_success_refreshes_translator_when_current_not_touched(self) -> None:
        harness = _Harness()
        harness.audit_search_display_complete = True
        harness.audit_search_query_edit.setText("alpha")
        harness.audit_search_replace_edit.setText("omega")
        harness.current_path = Path("Map999.json")
        _add_result_item(harness, path="Map001.json", uid="u1", matched_scope="both")
        harness.replace_outcomes[("Map001.json", "u1", "both")] = (True, 1)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            harness._replace_all_audit_search_results()

        self.assertEqual(harness.refresh_translator_calls, 1)
        self.assertEqual(harness.render_session_calls, 0)
        self.assertEqual(harness.statusBar().messages[-1], "Replaced 1 match in 1 result entry.")

    def test_worker_queue_start_and_poll_branches(self) -> None:
        harness = _WorkerHarness()
        request = {
            "generation": 1,
            "query": "alpha",
            "scope": "both",
            "needle": "alpha",
            "case_sensitive": False,
            "natural_mode": True,
            "path_sessions": [],
        }

        harness.audit_search_worker_running_request = dict(request)
        harness._queue_audit_search_worker(dict(request))
        self.assertIsNone(harness.audit_search_worker_pending_request)

        harness.audit_search_worker_running_request = None
        harness.audit_search_worker_pending_request = dict(request)
        harness._queue_audit_search_worker(dict(request))
        self.assertEqual(harness.audit_search_worker_pending_request, request)

        start_calls = {"count": 0}
        harness.audit_search_worker_pending_request = None
        harness._start_next_audit_search_worker()
        harness.audit_search_worker_pending_request = dict(request)
        harness.audit_worker_executor = _WorkerExecutorStub(error=RuntimeError("boom"))
        harness._start_next_audit_search_worker()
        self.assertIn("Search scan failed: boom", harness.audit_search_status_label.text())

        harness = _WorkerHarness()
        harness.audit_search_worker_pending_request = dict(request)
        harness._start_next_audit_search_worker = lambda: start_calls.__setitem__("count", start_calls["count"] + 1)  # type: ignore[method-assign]
        harness._poll_audit_search_worker()
        self.assertEqual(start_calls["count"], 1)

        harness = _WorkerHarness()
        harness.audit_search_worker_future = _WorkerFutureStub(done=False)
        harness._poll_audit_search_worker()
        self.assertEqual(harness.audit_search_worker_timer.started, [18])

        harness = _WorkerHarness()
        start_calls = {"count": 0}
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, error=RuntimeError("x"))
        harness.audit_search_worker_running_request = dict(request)
        harness.audit_search_worker_pending_request = dict(request)
        harness._start_next_audit_search_worker = lambda: start_calls.__setitem__("count", start_calls["count"] + 1)  # type: ignore[method-assign]
        harness._poll_audit_search_worker()
        self.assertEqual(start_calls["count"], 1)

        harness = _WorkerHarness()
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, error=RuntimeError("x"))
        harness.audit_search_worker_running_request = dict(request)
        harness._poll_audit_search_worker()
        self.assertIn("Search scan failed: x", harness.audit_search_status_label.text())

    def test_worker_poll_result_guards_and_success_paths(self) -> None:
        request = {
            "generation": 1,
            "query": "alpha",
            "scope": "both",
            "needle": "alpha",
            "case_sensitive": False,
            "natural_mode": True,
            "path_sessions": [],
        }

        harness = _WorkerHarness()
        start_calls = {"count": 0}
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, payload=[])
        harness.audit_search_worker_running_request = dict(request)
        harness.audit_search_worker_pending_request = {"generation": 2}
        harness._start_next_audit_search_worker = lambda: start_calls.__setitem__("count", start_calls["count"] + 1)  # type: ignore[method-assign]
        harness._poll_audit_search_worker()
        self.assertEqual(start_calls["count"], 1)

        harness = _WorkerHarness()
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, payload=[])
        harness.audit_search_worker_running_request = "bad"
        harness._poll_audit_search_worker()

        harness = _WorkerHarness()
        mismatch_request = dict(request)
        mismatch_request["generation"] = 0
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, payload=[])
        harness.audit_search_worker_running_request = mismatch_request
        harness._poll_audit_search_worker()

        harness = _WorkerHarness()
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, payload=[])
        harness.audit_search_worker_running_request = dict(request)
        harness.audit_search_results_list = None
        harness._poll_audit_search_worker()

        harness = _WorkerHarness()
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, payload=[])
        harness.audit_search_worker_running_request = dict(request)
        harness.audit_search_query_edit.setText("beta")
        harness._poll_audit_search_worker()

        harness = _WorkerHarness()
        harness.audit_search_worker_future = _WorkerFutureStub(done=True, payload=[])
        harness.audit_search_worker_running_request = dict(request)
        harness._poll_audit_search_worker()
        self.assertIn("No matches for 'alpha' in both.", harness.audit_search_status_label.text())
        self.assertFalse(harness.audit_search_replace_selected_btn.enabled)
        self.assertFalse(harness.audit_search_replace_all_btn.enabled)
        self.assertEqual(harness.audit_search_displayed_key, (1, "both", "alpha", False, True))
        self.assertTrue(harness.audit_search_display_complete)

        harness = _WorkerHarness()
        harness.audit_search_worker_future = _WorkerFutureStub(
            done=True,
            payload=[
                {
                    "path": Path("Map001.json"),
                    "uid": "u1",
                    "entry_text": "Block 1",
                    "matched_field": "Original",
                    "matched_text": "alpha",
                }
            ],
        )
        harness.audit_search_worker_running_request = dict(request)
        harness._poll_audit_search_worker()
        self.assertIn("Found 1 match for 'alpha' in both.", harness.audit_search_status_label.text())
        self.assertEqual(harness.overlay_messages[-1], "Rendering 0/1")
        self.assertEqual(harness.audit_search_render_timer.started, [7])
        self.assertEqual(len(harness.audit_search_render_records), 1)
        self.assertFalse(harness.audit_search_display_complete)


if __name__ == "__main__":
    unittest.main()
