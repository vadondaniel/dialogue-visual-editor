from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dialogue_visual_editor.helpers.ui.normalizations_dialog import (
    NormalizationsDialog,
)


class NormalizationsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_action_buttons_trigger_bound_callbacks(self) -> None:
        calls = {
            "normalize": 0,
            "trim": 0,
            "collapse": 0,
            "variables": 0,
        }
        counts = {
            "normalize": 6,
            "trim": 3,
            "collapse": 2,
        }

        dialog = NormalizationsDialog(
            on_normalize_codes=lambda: calls.__setitem__(
                "normalize", calls["normalize"] + 1
            ),
            on_trim_extra_ellipses=lambda: calls.__setitem__(
                "trim", calls["trim"] + 1
            ),
            on_smart_collapse_all=lambda: calls.__setitem__(
                "collapse", calls["collapse"] + 1
            ),
            on_variable_lengths=lambda: calls.__setitem__(
                "variables", calls["variables"] + 1
            ),
            count_normalize_codes=lambda: counts["normalize"],
            count_trim_extra_ellipses=lambda: counts["trim"],
            count_smart_collapse_all=lambda: counts["collapse"],
        )

        self.assertEqual(dialog.normalize_codes_btn.text(), "Normalize Codes... (6)")
        self.assertEqual(dialog.trim_ellipses_btn.text(), "Trim Extra Ellipses... (3)")
        self.assertEqual(dialog.smart_collapse_btn.text(), "Smart Collapse All... (2)")
        self.assertEqual(dialog.variable_lengths_btn.text(), "Variable Lengths...")

        dialog.normalize_codes_btn.click()
        dialog.trim_ellipses_btn.click()
        dialog.smart_collapse_btn.click()
        dialog.variable_lengths_btn.click()

        self.assertEqual(calls["normalize"], 1)
        self.assertEqual(calls["trim"], 1)
        self.assertEqual(calls["collapse"], 1)
        self.assertEqual(calls["variables"], 1)
        dialog.deleteLater()

    def test_counts_refresh_after_action_runs(self) -> None:
        counts = {
            "normalize": 2,
            "trim": 1,
            "collapse": 4,
        }

        def _normalize() -> None:
            counts["normalize"] = 0

        dialog = NormalizationsDialog(
            on_normalize_codes=_normalize,
            on_trim_extra_ellipses=lambda: None,
            on_smart_collapse_all=lambda: None,
            on_variable_lengths=lambda: None,
            count_normalize_codes=lambda: counts["normalize"],
            count_trim_extra_ellipses=lambda: counts["trim"],
            count_smart_collapse_all=lambda: counts["collapse"],
        )

        dialog.normalize_codes_btn.click()

        self.assertEqual(dialog.normalize_codes_btn.text(), "Normalize Codes... (0)")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
