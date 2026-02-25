from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

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
        )

        buttons = {
            button.text(): button for button in dialog.findChildren(QPushButton)
        }
        buttons["Normalize Codes..."].click()
        buttons["Trim Extra Ellipses..."].click()
        buttons["Smart Collapse All..."].click()
        buttons["Variable Lengths..."].click()

        self.assertEqual(calls["normalize"], 1)
        self.assertEqual(calls["trim"], 1)
        self.assertEqual(calls["collapse"], 1)
        self.assertEqual(calls["variables"], 1)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
