from __future__ import annotations

import unittest
from typing import Any, cast

from app import DialogueVisualEditor


class _StatusBarHarness:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _GlobalShortcutHarness:
    def __init__(self, *, translator_mode: bool, structural_result: bool) -> None:
        self.translator_mode = translator_mode
        self.structural_result = structural_result
        self.undo_calls = 0
        self.redo_calls = 0
        self._status_bar = _StatusBarHarness()

    def _focused_text_editor(self) -> None:
        return None

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

    def test_translator_mode_ctrl_y_attempts_structural_redo(self) -> None:
        harness = _GlobalShortcutHarness(
            translator_mode=True,
            structural_result=True,
        )

        DialogueVisualEditor._on_global_redo_shortcut(cast(Any, harness))

        self.assertEqual(harness.redo_calls, 1)
        self.assertEqual(harness.statusBar().messages, [])

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
