from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidgetItem, QTabWidget, QWidget
from dialogue_visual_editor.helpers.audit.audit_window_mixin import AuditWindowMixin


class _Harness(AuditWindowMixin):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.hidden_overlays: list[object] = []
        self.audit_search_progress_overlay = "search_overlay"
        self.audit_sanitize_progress_overlay = "sanitize_overlay"
        self.audit_control_mismatch_progress_overlay = "control_overlay"
        self.audit_term_variants_progress_overlay = "term_variants_overlay"
        self.audit_term_hits_progress_overlay = "term_hits_overlay"

    def _run_audit_search(self) -> None:
        self.calls.append("search")

    def _refresh_audit_search_replace_preview(self) -> None:
        self.calls.append("search_preview")

    def _refresh_audit_sanitize_panel(self) -> None:
        self.calls.append("sanitize")

    def _refresh_audit_control_mismatch_panel(self) -> None:
        self.calls.append("control")

    def _refresh_audit_consistency_panel(self) -> None:
        self.calls.append("consistency")

    def _refresh_audit_term_panel(self) -> None:
        self.calls.append("term")

    def _refresh_audit_term_suggestions_panel(self) -> None:
        self.calls.append("term_suggestions")

    def _refresh_audit_translation_collision_panel(self) -> None:
        self.calls.append("translation_collision")

    def _refresh_audit_name_consistency_panel(self) -> None:
        self.calls.append("name_consistency")

    def _hide_audit_progress_overlay(self, overlay: object) -> None:
        self.hidden_overlays.append(overlay)


class _QtHarness(QWidget, AuditWindowMixin):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def __getattr__(self, _name: str) -> Any:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop

    @staticmethod
    def _color_for_rpgm_code(_code: int) -> str:
        return "#ffffff"

    def _confirm_and_apply_audit_consistency_target_to_group(self) -> None:
        self.calls.append("confirm_apply")

    def _go_to_selected_audit_consistency_entry(self) -> None:
        self.calls.append("goto_entry")

    def _refresh_audit_consistency_neighbors_preview(self) -> None:
        self.calls.append("neighbors_preview")


class _ComboStub:
    def __init__(self, lookup: dict[str, int]) -> None:
        self.lookup = lookup
        self.selected_index: int | None = None

    def findData(self, value: str) -> int:
        return int(self.lookup.get(value, -1))

    def setCurrentIndex(self, index: int) -> None:
        self.selected_index = int(index)


class _WindowStub:
    def __init__(self) -> None:
        self.show_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0

    def show(self) -> None:
        self.show_calls += 1

    def raise_(self) -> None:
        self.raise_calls += 1

    def activateWindow(self) -> None:
        self.activate_calls += 1


class _FocusStub:
    def __init__(self) -> None:
        self.focus_calls = 0

    def setFocus(self) -> None:
        self.focus_calls += 1


class _OpenWindowHarness(AuditWindowMixin):
    def __init__(self, *, create_window: bool) -> None:
        self.create_window = create_window
        self.audit_window: _WindowStub | None = None
        self.audit_search_scope_combo: _ComboStub | None = None
        self.audit_sanitize_scope_combo: _ComboStub | None = None
        self.audit_search_query_edit: _FocusStub | None = None
        self.build_calls = 0
        self.refreshed_tabs: list[int] = []
        self.translator_mode = True
        self.current_tab_index = 4

    def _is_translator_mode(self) -> bool:
        return self.translator_mode

    def _build_audit_window(self) -> None:
        self.build_calls += 1
        self.audit_search_scope_combo = _ComboStub({"translation": 1})
        self.audit_sanitize_scope_combo = _ComboStub({"translation": 2})
        self.audit_search_query_edit = _FocusStub()
        if self.create_window:
            self.audit_window = _WindowStub()

    def _refresh_audit_tab(self, tab_index: int) -> None:
        self.refreshed_tabs.append(int(tab_index))

    def _current_audit_tab_index(self) -> int:
        return self.current_tab_index


class AuditWindowMixinTests(unittest.TestCase):
    def test_refresh_audit_tab_dispatches_search(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_SEARCH)

        self.assertEqual(harness.calls, ["search", "search_preview"])

    def test_refresh_audit_tab_dispatches_control_panel(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_CONTROL_MISMATCH)

        self.assertEqual(harness.calls, ["control"])

    def test_refresh_audit_tab_dispatches_sanitize_and_consistency(self) -> None:
        harness = _Harness()
        harness._refresh_audit_tab(harness._AUDIT_TAB_SANITIZE)
        harness._refresh_audit_tab(harness._AUDIT_TAB_CONSISTENCY)
        self.assertEqual(harness.calls, ["sanitize", "consistency"])

    def test_refresh_audit_tab_dispatches_term_panel(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_TERM_USAGE)

        self.assertEqual(harness.calls, ["term", "term_suggestions"])

    def test_refresh_audit_tab_dispatches_name_consistency_panel(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_NAME_CONSISTENCY)

        self.assertEqual(harness.calls, ["name_consistency"])

    def test_refresh_audit_tab_dispatches_translation_collision_panel(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_TRANSLATION_COLLISION)

        self.assertEqual(harness.calls, ["translation_collision"])

    def test_tab_change_hides_overlays_and_refreshes_target_tab(self) -> None:
        harness = _Harness()

        harness._on_audit_tab_changed(harness._AUDIT_TAB_CONTROL_MISMATCH)

        self.assertEqual(
            harness.hidden_overlays,
            [
                "search_overlay",
                "sanitize_overlay",
                "control_overlay",
                "term_variants_overlay",
                "term_hits_overlay",
            ],
        )
        self.assertEqual(harness.calls, ["control"])

    def test_open_audit_window_returns_when_build_did_not_create_window(self) -> None:
        harness = _OpenWindowHarness(create_window=False)
        harness._open_audit_window()
        self.assertEqual(harness.build_calls, 1)
        self.assertEqual(harness.refreshed_tabs, [])

    def test_open_audit_window_applies_scopes_refreshes_and_focuses(self) -> None:
        harness = _OpenWindowHarness(create_window=True)
        harness._open_audit_window()
        assert harness.audit_search_scope_combo is not None
        assert harness.audit_sanitize_scope_combo is not None
        assert harness.audit_search_query_edit is not None
        assert harness.audit_window is not None
        self.assertEqual(harness.audit_search_scope_combo.selected_index, 1)
        self.assertEqual(harness.audit_sanitize_scope_combo.selected_index, 2)
        self.assertEqual(harness.refreshed_tabs, [4])
        self.assertEqual(harness.audit_window.show_calls, 1)
        self.assertEqual(harness.audit_window.raise_calls, 1)
        self.assertEqual(harness.audit_window.activate_calls, 1)
        self.assertEqual(harness.audit_search_query_edit.focus_calls, 1)


class AuditWindowMixinQtSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_consistency_entries_item_double_click_triggers_go_to_entry(self) -> None:
        harness = _QtHarness()
        harness._build_audit_window()
        entries_list = harness.audit_consistency_entries_list
        self.assertIsNotNone(entries_list)
        assert entries_list is not None

        item = QListWidgetItem("Entry")
        entries_list.addItem(item)
        entries_list.setCurrentItem(item)

        entries_list.itemDoubleClicked.emit(item)

        self.assertIn("goto_entry", harness.calls)
        self.assertNotIn("confirm_apply", harness.calls)
        if harness.audit_window is not None:
            harness.audit_window.close()
            harness.audit_window.deleteLater()
        harness.deleteLater()

    def test_consistency_entries_enter_shortcut_triggers_confirm_apply(self) -> None:
        harness = _QtHarness()
        harness._build_audit_window()
        shortcuts = getattr(harness, "_audit_consistency_entries_apply_shortcuts", None)
        self.assertIsNotNone(shortcuts)
        assert isinstance(shortcuts, list)
        self.assertGreaterEqual(len(shortcuts), 2)

        shortcut = shortcuts[0]
        shortcut.activated.emit()

        self.assertIn("confirm_apply", harness.calls)
        self.assertNotIn("goto_entry", harness.calls)
        if harness.audit_window is not None:
            harness.audit_window.close()
            harness.audit_window.deleteLater()
        harness.deleteLater()

    def test_case_toggle_icon_dark_palette_branch_and_tab_index_helpers(self) -> None:
        harness = _QtHarness()
        with patch(
            "dialogue_visual_editor.helpers.audit.audit_window_mixin.is_dark_palette",
            return_value=True,
        ):
            icon_checked = harness._audit_case_toggle_icon(True)
            icon_unchecked = harness._audit_case_toggle_icon(False)
        self.assertFalse(icon_checked.isNull())
        self.assertFalse(icon_unchecked.isNull())

        self.assertEqual(harness._current_audit_tab_index(), harness._AUDIT_TAB_SEARCH)
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "A")
        tabs.addTab(QWidget(), "B")
        tabs.setCurrentIndex(1)
        harness.audit_tabs = tabs
        self.assertEqual(harness._current_audit_tab_index(), 1)
        tabs.deleteLater()

    def test_consistency_context_toggle_triggers_splitter_resize_and_preview(self) -> None:
        harness = _QtHarness()
        harness._build_audit_window()
        check = harness.audit_consistency_neighbors_check
        self.assertIsNotNone(check)
        assert check is not None

        with patch(
            "dialogue_visual_editor.helpers.audit.audit_window_mixin.QTimer.singleShot",
            side_effect=lambda _ms, callback: callback(),
        ) as single_shot:
            check.setChecked(True)

        self.assertGreaterEqual(harness.calls.count("neighbors_preview"), 1)
        self.assertEqual(single_shot.call_count, 1)
        if harness.audit_window is not None:
            harness.audit_window.close()
            harness.audit_window.deleteLater()
        harness.deleteLater()


if __name__ == "__main__":
    unittest.main()
