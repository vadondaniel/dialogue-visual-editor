from __future__ import annotations

import unittest
from typing import Any, cast

from app import DialogueVisualEditor
from helpers.mixins.structural_editing_mixin import StructuralEditingMixin


class _StatusBarHarness:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _FakeDocument:
    def __init__(self, *, undo_available: bool = False, redo_available: bool = False) -> None:
        self.undo_available = undo_available
        self.redo_available = redo_available

    def isUndoAvailable(self) -> bool:
        return self.undo_available

    def isRedoAvailable(self) -> bool:
        return self.redo_available


class _FakeTextEditor:
    def __init__(self, document: _FakeDocument) -> None:
        self._document = document
        self.undo_calls = 0
        self.redo_calls = 0

    def document(self) -> _FakeDocument:
        return self._document

    def undo(self) -> None:
        self.undo_calls += 1
        self._document.undo_available = False
        self._document.redo_available = True

    def redo(self) -> None:
        self.redo_calls += 1
        self._document.redo_available = False


class _GlobalShortcutHarness(StructuralEditingMixin):
    def __init__(
        self,
        *,
        translator_mode: bool,
        structural_result: bool,
        editor: _FakeTextEditor | None = None,
    ) -> None:
        self.translator_mode = translator_mode
        self.structural_result = structural_result
        self.editor = editor
        self.undo_calls = 0
        self.redo_calls = 0
        self._undo_pipeline_revision = 0
        self._last_text_edit_revision = 0
        self._last_structural_edit_revision = 0
        self._last_undo_pipeline_domain = ""
        self._undo_pipeline_text_stack_operation = False
        self._status_bar = _StatusBarHarness()

    def _focused_text_editor(self) -> _FakeTextEditor | None:
        return self.editor

    def _is_translator_mode(self) -> bool:
        return self.translator_mode

    def _undo_last_structural_action(self) -> bool:
        self.undo_calls += 1
        return self.structural_result

    def _redo_last_structural_action(self) -> bool:
        self.redo_calls += 1
        return self.structural_result

    def statusBar(self) -> _StatusBarHarness:
        return self._status_bar


class GlobalUndoShortcutTests(unittest.TestCase):
    def test_translator_mode_ctrl_z_attempts_structural_undo(self) -> None:
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=True,
        )

        DialogueVisualEditor._on_global_undo_shortcut(cast(Any, harness))

        self.assertEqual(harness.undo_calls, 1)
        self.assertEqual(harness.statusBar().messages, [])

    def test_ctrl_z_uses_focused_text_editor_undo_first(self) -> None:
        editor = _FakeTextEditor(_FakeDocument(undo_available=True))
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=True,
            editor=editor,
        )

        DialogueVisualEditor._on_global_undo_shortcut(cast(Any, harness))

        self.assertEqual(editor.undo_calls, 1)
        self.assertEqual(harness.undo_calls, 0)
        self.assertEqual(harness._last_undo_pipeline_domain, "text")

    def test_ctrl_z_does_not_fall_through_to_older_structural_history(self) -> None:
        editor = _FakeTextEditor(_FakeDocument(undo_available=False))
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=True,
            editor=editor,
        )
        harness._last_text_edit_revision = 2
        harness._last_structural_edit_revision = 1

        DialogueVisualEditor._on_global_undo_shortcut(cast(Any, harness))

        self.assertEqual(harness.undo_calls, 0)
        self.assertEqual(harness.statusBar().messages, ["Nothing to undo."])

    def test_ctrl_z_allows_focused_editor_fallback_for_newer_structural_action(self) -> None:
        editor = _FakeTextEditor(_FakeDocument(undo_available=False))
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=True,
            editor=editor,
        )
        harness._last_text_edit_revision = 1
        harness._last_structural_edit_revision = 2

        DialogueVisualEditor._on_global_undo_shortcut(cast(Any, harness))

        self.assertEqual(harness.undo_calls, 1)
        self.assertEqual(harness.statusBar().messages, [])

    def test_translator_mode_ctrl_y_attempts_structural_redo(self) -> None:
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=True,
        )

        DialogueVisualEditor._on_global_redo_shortcut(cast(Any, harness))

        self.assertEqual(harness.redo_calls, 1)
        self.assertEqual(harness.statusBar().messages, [])

    def test_ctrl_y_does_not_fall_through_after_text_undo(self) -> None:
        editor = _FakeTextEditor(_FakeDocument(redo_available=False))
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=True,
            editor=editor,
        )
        harness._last_undo_pipeline_domain = "text"

        DialogueVisualEditor._on_global_redo_shortcut(cast(Any, harness))

        self.assertEqual(harness.redo_calls, 0)
        self.assertEqual(harness.statusBar().messages, ["Nothing to redo."])

    def test_ctrl_z_reports_nothing_when_structural_undo_empty(self) -> None:
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=False,
        )

        DialogueVisualEditor._on_global_undo_shortcut(cast(Any, harness))

        self.assertEqual(harness.undo_calls, 1)
        self.assertEqual(harness.statusBar().messages, ["Nothing to undo."])


if __name__ == "__main__":
    unittest.main()
