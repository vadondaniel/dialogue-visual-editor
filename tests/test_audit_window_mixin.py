from __future__ import annotations

import unittest

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

    def _hide_audit_progress_overlay(self, overlay: object) -> None:
        self.hidden_overlays.append(overlay)


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


if __name__ == "__main__":
    unittest.main()
