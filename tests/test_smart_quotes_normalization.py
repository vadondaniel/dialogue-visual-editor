from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from app import DialogueVisualEditor
from helpers.core.models import DialogueSegment, FileSession, NO_SPEAKER_KEY


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


def _segment(
    uid: str,
    source_text: str,
    *,
    tl_lines: list[str],
    kind: str = "dialogue",
    speaker: str = "",
    tl_speaker: str = "",
) -> DialogueSegment:
    source_lines = source_text.split("\n") if source_text else [""]
    return DialogueSegment(
        uid=uid,
        context=f"{uid} ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=list(source_lines),
        original_lines=list(source_lines),
        source_lines=list(source_lines),
        segment_kind=kind,
        translation_lines=list(tl_lines),
        translation_speaker=tl_speaker,
    )


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _Harness:
    def __init__(self) -> None:
        self.path = Path("Map001.json")
        self.sessions: dict[Path, FileSession] = {}
        self.current_path: Path | None = self.path
        self.speaker_translation_map: dict[str, str] = {}
        self.refresh_dirty_paths: list[Path] = []
        self.render_calls = 0
        self._status_bar = _StatusBarStub()
        self.persist_calls: list[set[Path]] = []

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [
                item if isinstance(item, str) else ("" if item is None else str(item))
                for item in value
            ] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    @staticmethod
    def _speaker_key_for_segment(segment: DialogueSegment) -> str:
        return segment.speaker_name if segment.speaker_name.strip() else NO_SPEAKER_KEY

    @staticmethod
    def _segment_is_safe_for_smart_quotes_normalization(segment: DialogueSegment) -> bool:
        return segment.segment_kind in {
            "dialogue",
            "choice",
            "script_message",
            "tyrano_dialogue",
        }

    def _refresh_dirty_state(self, session: FileSession) -> None:
        self.refresh_dirty_paths.append(session.path)

    def _render_session(
        self,
        _session: FileSession,
        focus_uid: str | None = None,
        preserve_scroll: bool = False,
        start_at_top: bool = False,
    ) -> None:
        _ = (focus_uid, preserve_scroll, start_at_top)
        self.render_calls += 1

    def _persist_sessions_for_paths(self, paths: set[Path]) -> tuple[int, int]:
        self.persist_calls.append(set(paths))
        return 1, 0

    def statusBar(self) -> _StatusBarStub:
        return self._status_bar


class _FakeCheckBox:
    def __init__(self, _text: str, _parent: object) -> None:
        self._checked = False

    def setChecked(self, checked: bool) -> None:
        self._checked = bool(checked)

    def isChecked(self) -> bool:
        return self._checked


class _FakeMessageBox:
    Icon = QMessageBox.Icon
    StandardButton = QMessageBox.StandardButton

    information_calls: list[tuple[str, str]] = []

    @classmethod
    def information(cls, _parent: object, title: str, text: str) -> int:
        cls.information_calls.append((title, text))
        return 0

    def __init__(self, _parent: object) -> None:
        self.checkbox: _FakeCheckBox | None = None

    def setIcon(self, _icon: object) -> None:
        return None

    def setWindowTitle(self, _title: str) -> None:
        return None

    def setText(self, _text: str) -> None:
        return None

    def setCheckBox(self, checkbox: _FakeCheckBox) -> None:
        self.checkbox = checkbox

    def setStandardButtons(self, _buttons: object) -> None:
        return None

    def setDefaultButton(self, _button: object) -> None:
        return None

    def exec(self) -> int:
        return int(self.StandardButton.Yes)


class SmartQuotesNormalizationTests(unittest.TestCase):
    def test_count_and_apply_skip_plugin_and_other_code_like_segments(self) -> None:
        harness = _Harness()
        dialogue = _segment(
            "Map001:1",
            "source",
            tl_lines=['"Hi"', "don't"],
            kind="dialogue",
            speaker="Hero",
            tl_speaker='"Aki"',
        )
        choice = _segment(
            "Map001:2",
            "source",
            tl_lines=["'Yes'"],
            kind="choice",
            speaker="",
            tl_speaker="",
        )
        script_message = _segment(
            "Map001:3",
            "source",
            tl_lines=['"Go"'],
            kind="script_message",
            speaker="Narrator",
            tl_speaker="It's me",
        )
        plugin_text = _segment(
            "Map001:P:1",
            "source",
            tl_lines=['"Plugin code"'],
            kind="plugin_text",
            speaker="",
            tl_speaker="",
        )
        note_text = _segment(
            "Map001:N:1",
            "source",
            tl_lines=["'notes'"],
            kind="note_text",
            speaker="",
            tl_speaker="",
        )
        harness.sessions[harness.path] = FileSession(
            path=harness.path,
            data=[],
            bundles=[],
            segments=[dialogue, choice, script_message, plugin_text, note_text],
        )

        text_count, speaker_count = cast(
            tuple[int, int],
            _call_editor_method("_count_possible_smart_quote_normalizations", harness),
        )
        self.assertEqual((text_count, speaker_count), (7, 3))

        applied = cast(
            tuple[int, int, int, int, set[Path]],
            _call_editor_method("_apply_smart_quote_normalization", harness),
        )
        self.assertEqual(applied[0], 10)
        self.assertEqual(applied[1], 7)
        self.assertEqual(applied[2], 3)
        self.assertEqual(applied[3], 3)
        self.assertEqual(applied[4], {harness.path})
        self.assertEqual(harness.refresh_dirty_paths, [harness.path])
        self.assertEqual(harness.render_calls, 1)

        self.assertEqual(dialogue.translation_lines, ["\u201CHi\u201D", "don\u2019t"])
        self.assertEqual(choice.translation_lines, ["\u2018Yes\u2019"])
        self.assertEqual(script_message.translation_lines, ["\u201CGo\u201D"])
        self.assertEqual(dialogue.translation_speaker, "\u201CAki\u201D")
        self.assertEqual(script_message.translation_speaker, "It\u2019s me")
        self.assertEqual(plugin_text.translation_lines, ['"Plugin code"'])
        self.assertEqual(note_text.translation_lines, ["'notes'"])
        self.assertEqual(harness.speaker_translation_map.get("Hero"), "\u201CAki\u201D")
        self.assertEqual(harness.speaker_translation_map.get("Narrator"), "It\u2019s me")

    def test_normalizations_count_wrapper_uses_smart_quotes_total(self) -> None:
        harness = _Harness()
        harness.sessions[harness.path] = FileSession(
            path=harness.path,
            data=[],
            bundles=[],
            segments=[],
        )
        harness._count_possible_smart_quote_normalizations = (  # type: ignore[method-assign]
            lambda: (5, 2)
        )

        total = cast(
            int,
            _call_editor_method("_normalizations_count_possible_smart_quotes", harness),
        )

        self.assertEqual(total, 7)

    def test_open_smart_quotes_dialog_persists_and_reports_status(self) -> None:
        harness = _Harness()
        harness.sessions[harness.path] = FileSession(
            path=harness.path,
            data=[],
            bundles=[],
            segments=[],
        )
        harness._count_possible_smart_quote_normalizations = (  # type: ignore[method-assign]
            lambda: (3, 1)
        )
        harness._apply_smart_quote_normalization = (  # type: ignore[method-assign]
            lambda: (4, 3, 1, 2, {harness.path})
        )
        _FakeMessageBox.information_calls.clear()

        with (
            patch("app.QMessageBox", _FakeMessageBox),
            patch("app.QCheckBox", _FakeCheckBox),
        ):
            _call_editor_method("_open_smart_quotes_dialog", harness)

        self.assertEqual(harness.persist_calls, [{harness.path}])
        self.assertTrue(harness.statusBar().messages)
        self.assertIn("Converted 4 quote/apostrophe occurrences", harness.statusBar().messages[-1])
        self.assertIn("Persisted 1 file.", harness.statusBar().messages[-1])


if __name__ == "__main__":
    unittest.main()
