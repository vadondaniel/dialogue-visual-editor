from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dialogue_visual_editor.helpers.core.models import DialogueSegment
from dialogue_visual_editor.helpers.ui.ui_components import DialogueBlockWidget


def _segment(lines: list[str] | None = None) -> DialogueSegment:
    resolved = list(lines) if lines else ["hello"]
    return DialogueSegment(
        uid="Map001:0",
        context="Map001 > Event 1",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(resolved),
        original_lines=list(resolved),
        source_lines=list(resolved),
    )


def _widget(segment: DialogueSegment) -> DialogueBlockWidget:
    return DialogueBlockWidget(
        segment=segment,
        block_number=1,
        thin_width=34,
        wide_width=44,
        max_lines=4,
        infer_name_from_first_line=True,
        smart_collapse_allow_comma_endings=True,
        smart_collapse_allow_colon_triplet_endings=True,
        smart_collapse_ellipsis_lowercase_rule=True,
        smart_collapse_collapse_if_no_punctuation=False,
        smart_collapse_min_soft_ratio=0.5,
        hide_control_codes_when_unfocused=False,
        hidden_control_line_transform=None,
        hidden_control_colored_line_resolver=None,
        speaker_display_resolver=None,
        speaker_display_html_resolver=None,
        hint_display_html_resolver=None,
        color_code_resolver=None,
        variable_label_resolver=None,
        speaker_tint_color="#0284c7",
        translator_mode=False,
        highlight_control_mismatch=False,
        actor_mode=False,
        name_index_kind="",
        name_index_label="Entry",
        allow_structural_actions=True,
        inferred_speaker_name_resolver=None,
    )


class DialogueBlockWidgetLazyEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_editor_mount_and_unmount_toggle_preview(self) -> None:
        segment = _segment(["line one", "line two"])
        widget = _widget(segment)
        self.assertIsNone(widget.editor)
        self.assertFalse(widget._preview.isHidden())
        self.assertIn("line one", widget._preview.text())

        widget.set_editor_active(True)
        self.assertIsNotNone(widget.editor)
        self.assertTrue(widget._preview.isHidden())

        widget.set_editor_active(False)
        self.assertIsNone(widget.editor)
        self.assertFalse(widget._preview.isHidden())
        widget.deleteLater()

    def test_set_editor_lines_while_unmounted_updates_segment(self) -> None:
        segment = _segment(["before"])
        widget = _widget(segment)
        self.assertIsNone(widget.editor)

        widget._set_editor_lines(["after", "next"])

        self.assertEqual(segment.lines, ["after", "next"])
        self.assertIn("after", widget._preview.text())
        self.assertIn("next", widget._preview.text())
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
