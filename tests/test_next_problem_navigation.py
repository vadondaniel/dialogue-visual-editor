from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

from dialogue_visual_editor.app import DialogueVisualEditor
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


class _StatusBarHarness:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _NextProblemHarness:
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.file_paths: list[Path] = []
        self.current_path: Path | None = None
        self.selected_segment_uid: str | None = None
        self.problem_uids: set[str] = set()
        self._status_bar = _StatusBarHarness()
        self.open_calls: list[tuple[Path, str | None, str | None]] = []

    def _problem_checks_summary_text(self) -> str:
        return "missing translation"

    def _is_translator_mode(self) -> bool:
        return True

    def _segment_has_layout_problem(
        self,
        session: FileSession,
        segment: DialogueSegment,
        translator_mode: bool,
    ) -> bool:
        _ = (session, translator_mode)
        return segment.uid in self.problem_uids

    def _is_misc_segment_kind_for_scope(self, segment: DialogueSegment) -> bool:
        return segment.segment_kind in {
            "name_index",
            "system_text",
            "plugin_text",
            "plugin_command_text",
            "note_text",
            "actor_name_alias",
        }

    def _open_file(
        self,
        path: Path,
        force_reload: bool = False,
        focus_uid: str | None = None,
        view_scope: str | None = None,
    ) -> None:
        _ = force_reload
        self.open_calls.append((path, focus_uid, view_scope))

    def statusBar(self) -> _StatusBarHarness:
        return self._status_bar


def _make_segment(uid: str, *, kind: str) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        segment_kind=kind,
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=["jp line"],
        original_lines=["jp line"],
        source_lines=["jp line"],
    )


class NextProblemNavigationTests(unittest.TestCase):
    def test_jump_to_next_problem_opens_misc_scope_for_misc_segment(self) -> None:
        harness = _NextProblemHarness()
        path = Path("Map001.json")
        misc_segment = _make_segment("seg-misc", kind="plugin_command_text")
        session = FileSession(path=path, data={}, bundles=[], segments=[misc_segment])
        harness.sessions[path] = session
        harness.file_paths = [path]
        harness.problem_uids = {"seg-misc"}

        _call_editor_method("_jump_to_next_problem", harness)

        self.assertEqual(harness.open_calls, [(path, "seg-misc", "misc")])

    def test_jump_to_next_problem_opens_dialogue_scope_for_dialogue_segment(self) -> None:
        harness = _NextProblemHarness()
        path = Path("Map001.json")
        dialogue_segment = _make_segment("seg-dialogue", kind="dialogue")
        session = FileSession(path=path, data={}, bundles=[], segments=[dialogue_segment])
        harness.sessions[path] = session
        harness.file_paths = [path]
        harness.problem_uids = {"seg-dialogue"}

        _call_editor_method("_jump_to_next_problem", harness)

        self.assertEqual(harness.open_calls, [(path, "seg-dialogue", "dialogue")])


if __name__ == "__main__":
    unittest.main()
