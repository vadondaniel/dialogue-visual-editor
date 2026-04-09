from __future__ import annotations

import os
import unittest
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractItemView, QApplication

from helpers.ui.ui_components import (
    InferredSpeakerCandidatesDialog,
)


class _EditorStub:
    def __init__(self) -> None:
        self.accept_calls: list[str] = []
        self.rows: list[dict[str, Any]] = [
            {
                "speaker_key": "Hero",
                "suggested_translation": "Aki",
                "count": 3,
                "sample_path": "Map001.json",
                "sample_uid": "Map001:1",
                "sample_context": "Map001 > Event 1",
            },
            {
                "speaker_key": "Rival",
                "suggested_translation": "Riku",
                "count": 2,
                "sample_path": "Map001.json",
                "sample_uid": "Map001:2",
                "sample_context": "Map001 > Event 2",
            },
        ]

    def _collect_inferred_speaker_candidates_for_manager(self) -> list[dict[str, Any]]:
        return list(self.rows)

    def _accept_inferred_speaker_candidate_for_manager(self, speaker_key: str) -> int:
        self.accept_calls.append(speaker_key)
        return 1

    def _set_speaker_translation_everywhere(self, speaker_key: str, translated_name: str) -> int:
        _ = speaker_key
        _ = translated_name
        return 0

    def _jump_to_speaker_candidate_entry_for_manager(self, path_raw: str, uid: str) -> bool:
        _ = path_raw
        _ = uid
        return True


class InferredSpeakerCandidatesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_allows_multi_select_and_batch_accept(self) -> None:
        editor = _EditorStub()
        dialog = InferredSpeakerCandidatesDialog(editor)
        self.addCleanup(dialog.close)

        self.assertEqual(
            dialog.tree.selectionMode(),
            QAbstractItemView.SelectionMode.ExtendedSelection,
        )
        self.assertEqual(
            dialog.tree.selectionBehavior(),
            QAbstractItemView.SelectionBehavior.SelectRows,
        )

        first = dialog.tree.topLevelItem(0)
        second = dialog.tree.topLevelItem(1)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)

        dialog.tree.clearSelection()
        if first is not None:
            first.setSelected(True)
            dialog.tree.setCurrentItem(first)
        if second is not None:
            second.setSelected(True)
        dialog._sync_action_buttons()

        self.assertTrue(dialog.accept_btn.isEnabled())
        self.assertFalse(dialog.set_translation_btn.isEnabled())
        self.assertFalse(dialog.go_to_entry_btn.isEnabled())

        dialog._on_accept_clicked()

        self.assertEqual(len(editor.accept_calls), 2)
        self.assertEqual(set(editor.accept_calls), {"Hero", "Rival"})
        self.assertIn("Accepted 2 inferred speakers", dialog.status_label.text())


if __name__ == "__main__":
    unittest.main()
