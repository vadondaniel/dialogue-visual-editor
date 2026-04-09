from __future__ import annotations

import os
import unittest
from typing import Any, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextBlock
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from helpers.ui.ui_components import ControlCodeHighlighter


def _block_has_color(block: QTextBlock, color_hex: str) -> bool:
    target = color_hex.lower()
    layout = block.layout()
    for fmt_range in layout.formats():
        range_any = cast(Any, fmt_range)
        color = range_any.format.foreground().color()
        if color.isValid() and color.name().lower() == target and range_any.length > 0:
            return True
    return False


class ControlCodeHighlighterColorFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_flow_color_carries_across_lines(self) -> None:
        editor = QPlainTextEdit()
        highlighter = ControlCodeHighlighter(
            editor.document(),
            dark_theme=False,
            color_code_resolver=lambda code: "#22aa22" if code == 2 else "",
            resolve_color_flow=True,
        )
        editor.setPlainText("\\C[2]Hero\nLine two")
        highlighter.rehighlight()

        first = editor.document().firstBlock()
        second = first.next()
        self.assertTrue(_block_has_color(first, "#22aa22"))
        self.assertTrue(_block_has_color(second, "#22aa22"))

    def test_initial_active_color_applies_without_visible_token(self) -> None:
        editor = QPlainTextEdit()
        highlighter = ControlCodeHighlighter(
            editor.document(),
            dark_theme=False,
            color_code_resolver=lambda code: "#22aa22" if code == 2 else "",
            resolve_color_flow=True,
        )
        highlighter.set_initial_active_color_code(2)
        editor.setPlainText("Line one\nLine two")
        highlighter.rehighlight()

        first = editor.document().firstBlock()
        second = first.next()
        self.assertTrue(_block_has_color(first, "#22aa22"))
        self.assertTrue(_block_has_color(second, "#22aa22"))


if __name__ == "__main__":
    unittest.main()
