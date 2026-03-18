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


if __name__ == "__main__":
    unittest.main()
