from __future__ import annotations

import os
import unittest
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QListWidgetItem, QWidget
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


class AuditWindowMixinTests(unittest.TestCase):
    def test_refresh_audit_tab_dispatches_search(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_SEARCH)

        self.assertEqual(harness.calls, ["search", "search_preview"])

    def test_refresh_audit_tab_dispatches_control_panel(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_CONTROL_MISMATCH)

        self.assertEqual(harness.calls, ["control"])

    def test_refresh_audit_tab_dispatches_term_panel(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_TERM_USAGE)

        self.assertEqual(harness.calls, ["term", "term_suggestions"])

    def test_refresh_audit_tab_dispatches_name_consistency_panel(self) -> None:
        harness = _Harness()

        harness._refresh_audit_tab(harness._AUDIT_TAB_NAME_CONSISTENCY)

        self.assertEqual(harness.calls, ["name_consistency"])

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


class AuditWindowMixinQtSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_consistency_entries_item_activated_triggers_confirm_apply(self) -> None:
        harness = _QtHarness()
        harness._build_audit_window()
        entries_list = harness.audit_consistency_entries_list
        self.assertIsNotNone(entries_list)
        assert entries_list is not None

        item = QListWidgetItem("Entry")
        entries_list.addItem(item)
        entries_list.setCurrentItem(item)

        entries_list.itemActivated.emit(item)

        self.assertIn("confirm_apply", harness.calls)
        self.assertNotIn("goto_entry", harness.calls)
        if harness.audit_window is not None:
            harness.audit_window.close()
            harness.audit_window.deleteLater()
        harness.deleteLater()


if __name__ == "__main__":
    unittest.main()
