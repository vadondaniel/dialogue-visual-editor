from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import Qt

from dialogue_visual_editor.app import FILE_LIST_SCOPE_ROLE, DialogueVisualEditor


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


class _ListItemHarness:
    def __init__(self, path: Path, scope: str) -> None:
        self._data: dict[int, Any] = {
            int(Qt.ItemDataRole.UserRole): str(path),
            FILE_LIST_SCOPE_ROLE: scope,
        }

    def data(self, role: int) -> Any:
        return self._data.get(int(role))


class _ScopeSelectionHarness:
    def __init__(self, path: Path) -> None:
        self.file_view_scope_by_path: dict[Path, str] = {path: "dialogue"}
        self.file_items_scoped: dict[tuple[Path, str], object] = {}
        self.file_items: dict[Path, object] = {}
        self._open_calls: list[tuple[Path, str | None, str]] = []

    def _file_ref_from_item(self, item: object | None) -> tuple[Path, str] | None:
        return cast(tuple[Path, str] | None, _call_editor_method("_file_ref_from_item", self, item))

    def _open_file(
        self,
        path: Path,
        force_reload: bool = False,
        focus_uid: str | None = None,
        view_scope: str | None = None,
    ) -> None:
        _ = (force_reload, focus_uid)
        previous_scope = self.file_view_scope_by_path.get(path, "")
        self._open_calls.append((path, view_scope, previous_scope))
        if isinstance(view_scope, str) and view_scope:
            self.file_view_scope_by_path[path] = view_scope


class FileScopeSelectionTests(unittest.TestCase):
    def test_on_file_selected_does_not_prewrite_scope_before_open(self) -> None:
        path = Path("Map001.json")
        harness = _ScopeSelectionHarness(path)
        misc_item = object()
        harness.file_items_scoped[(path, "misc")] = misc_item
        selected_item = _ListItemHarness(path, "misc")

        _call_editor_method("_on_file_selected", harness, selected_item, None)

        self.assertEqual(harness._open_calls, [(path, "misc", "dialogue")])
        self.assertIs(harness.file_items[path], misc_item)
        self.assertEqual(harness.file_view_scope_by_path[path], "misc")


if __name__ == "__main__":
    unittest.main()
