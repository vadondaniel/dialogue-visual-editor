from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from typing import Any, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMenu

from app import DialogueVisualEditor


def _call_editor_method(name: str, self_obj: object, *args: Any, **kwargs: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args, **kwargs)


def _write_marker_data_folder(data_folder: Path) -> None:
    data_folder.mkdir(parents=True, exist_ok=True)
    (data_folder / "System.json").write_text("{}", encoding="utf-8")


class _RememberCheckStub:
    def __init__(self, checked: bool) -> None:
        self._checked = bool(checked)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        self._checked = bool(value)

    def blockSignals(self, _blocked: bool) -> None:
        return None


class _StateHarness:
    def __init__(self, ui_state_path: Path) -> None:
        self.ui_state_path = ui_state_path
        self.remember_folder_check = _RememberCheckStub(False)
        self.last_folder_path = ""
        self.data_dir: Path | None = None
        self.recent_projects: list[dict[str, str]] = []
        self.legacy_project_ui_settings_by_folder: dict[str, dict[str, Any]] = {}
        self._applied_global_settings: dict[str, Any] = {}
        self._load_data_folder_calls: list[Path] = []
        self._rebuild_previous_projects_menu_calls = 0

    def _collect_global_ui_settings(self) -> dict[str, Any]:
        return {"hide_control_codes": True}

    def _global_settings_subset_from_mapping(self, raw: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            _call_editor_method("_global_settings_subset_from_mapping", self, raw),
        )

    def _normalize_recent_projects_payload(
        self,
        raw: Any,
        *,
        validate_exists: bool = True,
    ) -> list[dict[str, str]]:
        return cast(
            list[dict[str, str]],
            _call_editor_method(
                "_normalize_recent_projects_payload",
                self,
                raw,
                validate_exists=validate_exists,
            ),
        )

    def _recent_project_entry_from_data_folder(
        self,
        data_folder: Path,
        *,
        validate_exists: bool = True,
        last_seen_title: str = "",
    ) -> dict[str, str] | None:
        return cast(
            dict[str, str] | None,
            _call_editor_method(
                "_recent_project_entry_from_data_folder",
                self,
                data_folder,
                validate_exists=validate_exists,
                last_seen_title=last_seen_title,
            ),
        )

    def _apply_global_ui_settings(
        self,
        settings: dict[str, Any],
        *,
        rerender: bool = True,
    ) -> None:
        self._applied_global_settings = dict(settings)
        _ = rerender

    def _sync_settings_toggle_actions_from_controls(self) -> None:
        return None

    def _load_data_folder(self, folder: Path) -> None:
        self._load_data_folder_calls.append(folder)

    def _rebuild_previous_projects_menu(self) -> None:
        self._rebuild_previous_projects_menu_calls += 1


class _HistoryHarness:
    def __init__(self) -> None:
        self.recent_projects: list[dict[str, str]] = []
        self._save_ui_state_calls = 0
        self._rebuild_previous_projects_menu_calls = 0

    def _save_ui_state(self) -> None:
        self._save_ui_state_calls += 1

    def _rebuild_previous_projects_menu(self) -> None:
        self._rebuild_previous_projects_menu_calls += 1

    def _recent_project_entry_from_data_folder(
        self,
        data_folder: Path,
        *,
        validate_exists: bool = True,
        last_seen_title: str = "",
    ) -> dict[str, str] | None:
        return cast(
            dict[str, str] | None,
            _call_editor_method(
                "_recent_project_entry_from_data_folder",
                self,
                data_folder,
                validate_exists=validate_exists,
                last_seen_title=last_seen_title,
            ),
        )

    def _normalize_recent_projects_payload(
        self,
        raw: Any,
        *,
        validate_exists: bool = True,
    ) -> list[dict[str, str]]:
        return cast(
            list[dict[str, str]],
            _call_editor_method(
                "_normalize_recent_projects_payload",
                self,
                raw,
                validate_exists=validate_exists,
            ),
        )

    def _recent_project_title(self, entry: dict[str, str]) -> str:
        return str(_call_editor_method("_recent_project_title", self, entry))


class _MenuHarness:
    def __init__(self) -> None:
        self._file_previous_projects_menu = QMenu()
        self._file_previous_projects_show_all_action = None
        self.recent_projects = [
            {
                "root_folder": str(Path("C:/A")),
                "data_folder": str(Path("C:/A/data")),
            },
            {
                "root_folder": str(Path("C:/B")),
                "data_folder": str(Path("C:/B/data")),
            },
        ]
        self.opened_root_folders: list[str] = []
        self.show_all_calls = 0
        self.prune_calls = 0

    def _prune_recent_projects(
        self,
        *,
        persist: bool = False,
        rebuild_menu: bool = True,
    ) -> bool:
        _ = (persist, rebuild_menu)
        self.prune_calls += 1
        return False

    def _recent_projects_for_menu(self) -> list[dict[str, str]]:
        return cast(
            list[dict[str, str]],
            _call_editor_method("_recent_projects_for_menu", self),
        )

    def _recent_project_menu_label(self, entry: dict[str, str]) -> str:
        title = Path(entry["root_folder"]).name or "Project"
        return title

    def _open_recent_project(self, root_folder: str) -> None:
        self.opened_root_folders.append(root_folder)

    def _show_recent_projects_dialog(self) -> None:
        self.show_all_calls += 1


class _OpenHarness:
    def __init__(self) -> None:
        self.recent_projects: list[dict[str, str]] = []
        self._prune_calls = 0
        self._load_calls: list[Path] = []
        self._remove_calls: list[str] = []

    def _prune_recent_projects(
        self,
        *,
        persist: bool = False,
        rebuild_menu: bool = True,
    ) -> bool:
        _ = (persist, rebuild_menu)
        self._prune_calls += 1
        return False

    def _load_data_folder(self, folder: Path) -> None:
        self._load_calls.append(folder)

    def _remove_recent_project(
        self,
        root_folder: str,
        *,
        persist: bool = True,
        rebuild_menu: bool = True,
    ) -> bool:
        _ = (persist, rebuild_menu)
        self._remove_calls.append(root_folder)
        return True


class RecentProjectsHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_ui_state_round_trip_includes_recent_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_folder = tmp_path / "GameA" / "data"
            _write_marker_data_folder(data_folder)
            root_folder = data_folder.parent
            state_path = tmp_path / "ui_state.json"

            save_harness = _StateHarness(state_path)
            save_harness.recent_projects = [
                {
                    "root_folder": str(root_folder.resolve()),
                    "data_folder": str(data_folder.resolve()),
                }
            ]
            _call_editor_method("_save_ui_state", save_harness)

            load_harness = _StateHarness(state_path)
            _call_editor_method("_load_ui_state", load_harness)
            self.assertEqual(len(load_harness.recent_projects), 1)
            self.assertEqual(
                load_harness.recent_projects[0]["root_folder"],
                str(root_folder.resolve()),
            )
            self.assertEqual(
                load_harness.recent_projects[0]["data_folder"],
                str(data_folder.resolve()),
            )

    def test_load_ui_state_auto_prunes_invalid_recent_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_folder = tmp_path / "GameA" / "data"
            _write_marker_data_folder(data_folder)
            root_folder = data_folder.parent.resolve()
            missing_root = tmp_path / "MissingGame"
            state_path = tmp_path / "ui_state.json"
            payload = {
                "remember_last_folder": False,
                "last_folder": "",
                "global_settings": {},
                "recent_projects": [
                    {
                        "root_folder": str(root_folder),
                        "data_folder": str(data_folder.resolve()),
                    },
                    {
                        "root_folder": str(missing_root),
                        "data_folder": str(missing_root / "data"),
                    },
                    {"root_folder": "", "data_folder": ""},
                ],
            }
            state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            harness = _StateHarness(state_path)
            _call_editor_method("_load_ui_state", harness)
            self.assertEqual(len(harness.recent_projects), 1)
            self.assertEqual(harness.recent_projects[0]["root_folder"], str(root_folder))

    def test_record_recent_projects_is_mru_and_dedupes_by_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            a_data = tmp_path / "ProjA" / "data"
            a_www_data = tmp_path / "ProjA" / "www" / "data"
            b_data = tmp_path / "ProjB" / "data"
            _write_marker_data_folder(a_data)
            _write_marker_data_folder(a_www_data)
            _write_marker_data_folder(b_data)

            harness = _HistoryHarness()
            _call_editor_method("_record_recent_project_from_data_folder", harness, a_data)
            _call_editor_method("_record_recent_project_from_data_folder", harness, b_data)
            _call_editor_method("_record_recent_project_from_data_folder", harness, a_www_data)

            self.assertEqual(len(harness.recent_projects), 2)
            self.assertEqual(
                harness.recent_projects[0]["root_folder"],
                str((tmp_path / "ProjA").resolve()),
            )
            self.assertEqual(
                harness.recent_projects[1]["root_folder"],
                str((tmp_path / "ProjB").resolve()),
            )

    def test_recent_projects_for_menu_returns_top_twelve(self) -> None:
        harness = _HistoryHarness()
        harness.recent_projects = [
            {"root_folder": f"R{i}", "data_folder": f"D{i}"} for i in range(15)
        ]
        rows = cast(
            list[dict[str, str]],
            _call_editor_method("_recent_projects_for_menu", harness),
        )
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0]["root_folder"], "R0")
        self.assertEqual(rows[-1]["root_folder"], "R11")

    def test_remove_recent_project_updates_state_and_rebuilds_menu(self) -> None:
        harness = _HistoryHarness()
        harness.recent_projects = [
            {"root_folder": "A", "data_folder": "A/data"},
            {"root_folder": "B", "data_folder": "B/data"},
        ]

        changed = bool(
            _call_editor_method(
                "_remove_recent_project",
                harness,
                "A",
                persist=True,
                rebuild_menu=True,
            )
        )
        self.assertTrue(changed)
        self.assertEqual(harness.recent_projects, [{"root_folder": "B", "data_folder": "B/data"}])
        self.assertEqual(harness._save_ui_state_calls, 1)
        self.assertEqual(harness._rebuild_previous_projects_menu_calls, 1)

    def test_rebuild_previous_projects_menu_has_show_all_and_project_actions(self) -> None:
        harness = _MenuHarness()
        _call_editor_method("_rebuild_previous_projects_menu", harness)

        actions = harness._file_previous_projects_menu.actions()
        self.assertGreaterEqual(len(actions), 4)
        self.assertEqual(actions[-1].text(), "Show All...")
        self.assertEqual(harness.prune_calls, 1)

        actions[0].trigger()
        self.assertEqual(harness.opened_root_folders, [str(Path("C:/A"))])
        actions[-1].trigger()
        self.assertEqual(harness.show_all_calls, 1)

    def test_open_recent_project_routes_through_load_data_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "GameA"
            root.mkdir(parents=True, exist_ok=True)
            harness = _OpenHarness()
            harness.recent_projects = [
                {"root_folder": str(root.resolve()), "data_folder": str(root.resolve() / "data")}
            ]

            _call_editor_method("_open_recent_project", harness, str(root.resolve()))
            self.assertEqual(harness._prune_calls, 1)
            self.assertEqual(harness._load_calls, [root.resolve()])
            self.assertEqual(harness._remove_calls, [])

    def test_recent_project_title_prefers_last_seen_and_menu_label_is_title_only(self) -> None:
        harness = _HistoryHarness()
        entry = {
            "root_folder": str(Path("C:/ProjA")),
            "data_folder": str(Path("C:/ProjA/data")),
            "last_seen_title": "Translated Name",
        }

        title = str(_call_editor_method("_recent_project_title", harness, entry))
        menu_label = str(_call_editor_method("_recent_project_menu_label", harness, entry))

        self.assertEqual(title, "Translated Name")
        self.assertEqual(menu_label, "Translated Name")

    def test_show_recent_projects_dialog_executes_without_runtime_name_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_folder = tmp_path / "GameA" / "data"
            _write_marker_data_folder(data_folder)
            root_folder = data_folder.parent.resolve()

            with patch.object(DialogueVisualEditor, "_load_ui_state", lambda _self: None):
                editor = DialogueVisualEditor()
            try:
                editor.recent_projects = [
                    {
                        "root_folder": str(root_folder),
                        "data_folder": str(data_folder.resolve()),
                        "last_seen_title": "Game A",
                    }
                ]
                editor._save_ui_state = lambda: None  # type: ignore[method-assign]
                with patch.object(QDialog, "exec", return_value=int(QDialog.DialogCode.Rejected)):
                    editor._show_recent_projects_dialog()
            finally:
                editor.close()
                editor.deleteLater()


if __name__ == "__main__":
    unittest.main()
