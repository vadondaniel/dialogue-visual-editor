from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

from app import DialogueVisualEditor
from helpers.core.models import DialogueSegment, FileSession


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


class _CheckStub:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


def _segment(uid: str, text: str, *, kind: str = "dialogue") -> DialogueSegment:
    lines = text.split("\n") if text else [""]
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(lines),
        original_lines=list(lines),
        source_lines=list(lines),
        segment_kind=kind,
    )


def _session(path: Path, segments: list[DialogueSegment]) -> FileSession:
    return FileSession(
        path=path,
        data=[],
        bundles=[],
        segments=segments,
    )


class _Harness:
    def __init__(self, *, show_empty: bool) -> None:
        self.show_empty_files_check = _CheckStub(show_empty)
        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}
        self._supports_dialogue_paths: set[Path] = set()
        self._supports_misc_paths: set[Path] = set()
        self._scope_segments_by_key: dict[tuple[Path, bool], list[DialogueSegment]] = {}
        self._scope_count_by_key: dict[tuple[Path, bool], int] = {}

    @staticmethod
    def _is_translator_mode() -> bool:
        return False

    def _session_supports_dialogue_scope(self, session: FileSession) -> bool:
        return session.path in self._supports_dialogue_paths

    def _session_supports_misc_scope(self, session: FileSession) -> bool:
        return session.path in self._supports_misc_paths

    def _scope_display_segments_and_count(
        self,
        session: FileSession,
        *,
        translator_mode: bool,
        actor_mode: bool,
    ) -> tuple[list[DialogueSegment], int]:
        _ = translator_mode
        key = (session.path, actor_mode)
        segments = self._scope_segments_by_key.get(key, list(session.segments))
        count = self._scope_count_by_key.get(key, len(segments))
        return segments, count

    def register_scope(
        self,
        session: FileSession,
        *,
        supports_dialogue: bool,
        supports_misc: bool,
        dialogue_segments: list[DialogueSegment],
        dialogue_count: int,
        misc_segments: list[DialogueSegment],
        misc_count: int,
    ) -> None:
        path = session.path
        self.file_paths.append(path)
        self.sessions[path] = session
        if supports_dialogue:
            self._supports_dialogue_paths.add(path)
        if supports_misc:
            self._supports_misc_paths.add(path)
        self._scope_segments_by_key[(path, False)] = list(dialogue_segments)
        self._scope_count_by_key[(path, False)] = dialogue_count
        self._scope_segments_by_key[(path, True)] = list(misc_segments)
        self._scope_count_by_key[(path, True)] = misc_count


class FileVisibilityPathTests(unittest.TestCase):
    def test_show_empty_off_hides_file_when_scopes_have_zero_display_count(self) -> None:
        harness = _Harness(show_empty=False)
        path = Path("Map006.json")
        map_empty = _segment(
            "Map006.json:map_display_name",
            "",
            kind="map_display_name",
        )
        session = _session(path, [map_empty])
        harness.register_scope(
            session,
            supports_dialogue=True,
            supports_misc=False,
            dialogue_segments=[map_empty],
            dialogue_count=0,
            misc_segments=[],
            misc_count=0,
        )

        visible = cast(list[Path], _call_editor_method("_visible_file_paths", harness))

        self.assertEqual(visible, [])

    def test_show_empty_on_keeps_file_when_scopes_have_zero_display_count(self) -> None:
        harness = _Harness(show_empty=True)
        path = Path("Map006.json")
        map_empty = _segment(
            "Map006.json:map_display_name",
            "",
            kind="map_display_name",
        )
        session = _session(path, [map_empty])
        harness.register_scope(
            session,
            supports_dialogue=True,
            supports_misc=False,
            dialogue_segments=[map_empty],
            dialogue_count=0,
            misc_segments=[],
            misc_count=0,
        )

        visible = cast(list[Path], _call_editor_method("_visible_file_paths", harness))

        self.assertEqual(visible, [path])

    def test_show_empty_off_keeps_file_when_misc_scope_has_entries(self) -> None:
        harness = _Harness(show_empty=False)
        path = Path("Map007.json")
        map_empty = _segment(
            "Map007.json:map_display_name",
            "",
            kind="map_display_name",
        )
        actor_name = _segment("Map007.json:A:1", "Town Crier", kind="name_index")
        session = _session(path, [map_empty, actor_name])
        harness.register_scope(
            session,
            supports_dialogue=True,
            supports_misc=True,
            dialogue_segments=[map_empty],
            dialogue_count=0,
            misc_segments=[actor_name],
            misc_count=1,
        )

        visible = cast(list[Path], _call_editor_method("_visible_file_paths", harness))

        self.assertEqual(visible, [path])


if __name__ == "__main__":
    unittest.main()
