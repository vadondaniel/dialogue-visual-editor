from __future__ import annotations

import os
import re
import unittest
from typing import Any, Callable, Optional, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

from helpers.core.models import DialogueSegment
from helpers.ui.ui_components import ItemNameDescriptionWidget


def _segment() -> DialogueSegment:
    lines = [r"\C[2]NameJP", "", r"\C[3]DescJP"]
    return DialogueSegment(
        uid="Actors.json:A:1:name",
        context="Actors > 1",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(lines),
        original_lines=list(lines),
        source_lines=list(lines),
    )


def _widget(
    segment: DialogueSegment,
    *,
    hidden_control_colored_line_resolver: Optional[
        Callable[[str], tuple[str, list[tuple[int, int, str, float]]]]
    ] = None,
) -> ItemNameDescriptionWidget:
    return ItemNameDescriptionWidget(
        segment=segment,
        block_number=1,
        hide_control_codes_when_unfocused=False,
        hidden_control_line_transform=None,
        hidden_control_colored_line_resolver=hidden_control_colored_line_resolver,
        color_code_resolver=None,
        variable_label_resolver=None,
        translator_mode=False,
        name_index_label="Item",
    )


class ItemNameDescriptionWidgetFocusRemapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_name_editor_mouse_focus_deferred_reveal_preserves_cursor_position(self) -> None:
        widget = _widget(_segment())
        widget.set_hide_control_codes_when_unfocused(True)
        widget.name_editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self.assertFalse(widget._showing_raw_name)

        cursor = widget.name_editor.textCursor()
        cursor.setPosition(4)
        widget.name_editor.setTextCursor(cursor)

        widget.eventFilter(
            widget.name_editor,
            QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason),
        )
        self.assertTrue(widget._pending_mouse_reveal_name)
        self.assertFalse(widget._showing_raw_name)

        widget._apply_deferred_mouse_reveal_for_editor(widget.name_editor)
        self.assertFalse(widget._pending_mouse_reveal_name)
        self.assertTrue(widget._showing_raw_name)
        self.assertEqual(widget.name_editor.textCursor().position(), len(r"\C[2]") + 4)
        widget.deleteLater()

    def test_desc_editor_mouse_focus_deferred_reveal_preserves_cursor_position(self) -> None:
        widget = _widget(_segment())
        widget.set_hide_control_codes_when_unfocused(True)
        widget.desc_editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self.assertFalse(widget._showing_raw_desc)

        cursor = widget.desc_editor.textCursor()
        cursor.setPosition(3)
        widget.desc_editor.setTextCursor(cursor)

        widget.eventFilter(
            widget.desc_editor,
            QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason),
        )
        self.assertTrue(widget._pending_mouse_reveal_desc)
        self.assertFalse(widget._showing_raw_desc)

        widget._apply_deferred_mouse_reveal_for_editor(widget.desc_editor)
        self.assertFalse(widget._pending_mouse_reveal_desc)
        self.assertTrue(widget._showing_raw_desc)
        self.assertEqual(widget.desc_editor.textCursor().position(), len(r"\C[3]") + 3)
        widget.deleteLater()

    def test_non_mouse_focus_reveals_immediately(self) -> None:
        widget = _widget(_segment())
        widget.set_hide_control_codes_when_unfocused(True)
        widget.name_editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self.assertFalse(widget._showing_raw_name)

        widget.eventFilter(
            widget.name_editor,
            QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason),
        )
        self.assertFalse(widget._pending_mouse_reveal_name)
        self.assertTrue(widget._showing_raw_name)
        widget.deleteLater()

    def test_mouse_focus_deferred_reveal_works_from_viewport_release(self) -> None:
        widget = _widget(_segment())
        widget.set_hide_control_codes_when_unfocused(True)
        widget.name_editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self.assertFalse(widget._showing_raw_name)

        widget.eventFilter(
            widget.name_editor,
            QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason),
        )
        self.assertTrue(widget._pending_mouse_reveal_name)
        widget.eventFilter(widget.name_editor.viewport(), QEvent(QEvent.Type.MouseButtonRelease))
        self.assertFalse(widget._pending_mouse_reveal_name)
        self.assertTrue(widget._showing_raw_name)
        widget.deleteLater()

    def test_pending_mouse_reveal_also_reveals_on_keypress(self) -> None:
        widget = _widget(_segment())
        widget.set_hide_control_codes_when_unfocused(True)
        widget.desc_editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self.assertFalse(widget._showing_raw_desc)

        widget.eventFilter(
            widget.desc_editor,
            QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason),
        )
        self.assertTrue(widget._pending_mouse_reveal_desc)
        widget.eventFilter(
            widget.desc_editor,
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B, Qt.KeyboardModifier.NoModifier, "b"),
        )
        self.assertFalse(widget._pending_mouse_reveal_desc)
        self.assertTrue(widget._showing_raw_desc)
        widget.deleteLater()

    def test_desc_editor_hidden_mode_keeps_colored_preview_spans(self) -> None:
        color_token_re = re.compile(r"\\[Cc]\[(\d+)\]")

        def colored_mask(value: str) -> tuple[str, list[tuple[int, int, str, float]]]:
            output: list[str] = []
            spans: list[tuple[int, int, str, float]] = []
            cursor = 0
            out_pos = 0
            active_color = ""
            for match in color_token_re.finditer(value):
                chunk = value[cursor:match.start()]
                if chunk:
                    output.append(chunk)
                    next_pos = out_pos + len(chunk)
                    spans.append((out_pos, next_pos, active_color, 1.0))
                    out_pos = next_pos
                color_code = int(match.group(1))
                active_color = "#22aa22" if color_code == 3 else ""
                cursor = match.end()
            tail = value[cursor:]
            if tail:
                output.append(tail)
                next_pos = out_pos + len(tail)
                spans.append((out_pos, next_pos, active_color, 1.0))
            return "".join(output), spans

        widget = _widget(
            _segment(),
            hidden_control_colored_line_resolver=colored_mask,
        )
        widget.set_hide_control_codes_when_unfocused(True)
        widget.desc_editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self._app.processEvents()

        self.assertFalse(widget._showing_raw_desc)
        self.assertNotIn(r"\C[3]", widget.desc_editor.toPlainText())

        selections = widget.desc_editor.extraSelections()
        colored = 0
        for selection in selections:
            selection_any = cast(Any, selection)
            color = selection_any.format.foreground().color()
            if color.isValid() and color.name().lower() == "#22aa22":
                colored += 1
        self.assertGreaterEqual(colored, 1)
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
