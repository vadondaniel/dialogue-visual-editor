from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

from dialogue_visual_editor.helpers.core.models import DialogueSegment
from dialogue_visual_editor.helpers.ui.ui_components import ItemNameDescriptionWidget


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


def _widget(segment: DialogueSegment) -> ItemNameDescriptionWidget:
    return ItemNameDescriptionWidget(
        segment=segment,
        block_number=1,
        hide_control_codes_when_unfocused=False,
        hidden_control_line_transform=None,
        hidden_control_colored_line_resolver=None,
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


if __name__ == "__main__":
    unittest.main()
