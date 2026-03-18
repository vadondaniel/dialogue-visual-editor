from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dialogue_visual_editor.helpers.core import project_path_utils
from dialogue_visual_editor.helpers.core.project_path_utils import (
    _contains_ks_files,
    _folder_file_names_lower,
    candidate_project_data_folders,
    project_fallback_title_from_data_folder,
    project_root_folder_for_data_folder,
    resolve_project_data_folder,
)


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ProjectPathUtilsTests(unittest.TestCase):
    def test_folder_file_names_lower_handles_non_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "not_a_folder.txt"
            file_path.write_text("x", encoding="utf-8")
            self.assertEqual(_folder_file_names_lower(file_path), set())

    def test_contains_ks_files_handles_rglob_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            with patch.object(Path, "rglob", side_effect=OSError("fail")):
                self.assertFalse(_contains_ks_files(folder))

    def test_candidate_project_data_folders_falls_back_when_resolve_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selected = Path(tmpdir) / "www"
            selected.mkdir(parents=True, exist_ok=True)
            with patch.object(Path, "resolve", side_effect=OSError("fail")):
                candidates = candidate_project_data_folders(selected)

        self.assertEqual(candidates[0], selected)

    def test_project_root_non_data_folder_returns_resolved_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "SomeFolder"
            root_dir.mkdir(parents=True, exist_ok=True)
            resolved = project_root_folder_for_data_folder(root_dir)
            self.assertEqual(resolved, root_dir.resolve())

    def test_resolve_keeps_rpg_data_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            _touch(data_dir / "System.json", "{}")
            resolved = resolve_project_data_folder(data_dir)
            self.assertEqual(resolved, data_dir.resolve())

    def test_resolve_rpg_from_www_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            www_dir = Path(tmpdir) / "www"
            _touch(www_dir / "data" / "System.json", "{}")
            resolved = resolve_project_data_folder(www_dir)
            self.assertEqual(resolved, (www_dir / "data").resolve())

    def test_resolve_rpg_from_game_root_prefers_www_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            _touch(root_dir / "www" / "data" / "System.json", "{}")
            resolved = resolve_project_data_folder(root_dir)
            self.assertEqual(resolved, (root_dir / "www" / "data").resolve())

    def test_resolve_rpg_from_game_root_with_data_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            _touch(root_dir / "data" / "System.json", "{}")
            resolved = resolve_project_data_folder(root_dir)
            self.assertEqual(resolved, (root_dir / "data").resolve())

    def test_resolve_tyrano_from_game_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            _touch(
                root_dir / "resources" / "app" / "data" / "scenario" / "scene1.ks",
                "[tb_start_text mode=1 ]\nline[p]\n[_tb_end_text]\n",
            )
            resolved = resolve_project_data_folder(root_dir)
            self.assertEqual(resolved, (root_dir / "resources" / "app" / "data").resolve())

    def test_resolve_tyrano_from_scenario_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scenario_dir = Path(tmpdir) / "data" / "scenario"
            _touch(
                scenario_dir / "scene1.ks",
                "[tb_start_text mode=1 ]\nline[p]\n[_tb_end_text]\n",
            )
            resolved = resolve_project_data_folder(scenario_dir)
            self.assertEqual(resolved, scenario_dir.parent.resolve())

    def test_resolve_unknown_folder_falls_back_to_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            selected = Path(tmpdir) / "empty_project"
            selected.mkdir(parents=True, exist_ok=True)
            resolved = resolve_project_data_folder(selected)
            self.assertEqual(resolved, selected.resolve())

    def test_project_root_folder_for_rpg_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "MyGame" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            root = project_root_folder_for_data_folder(data_dir)
            self.assertEqual(root, (Path(tmpdir) / "MyGame").resolve())

    def test_project_root_folder_for_www_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "MyGame" / "www" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            root = project_root_folder_for_data_folder(data_dir)
            self.assertEqual(root, (Path(tmpdir) / "MyGame").resolve())

    def test_project_root_folder_for_tyrano_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "GameX" / "resources" / "app" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            root = project_root_folder_for_data_folder(data_dir)
            self.assertEqual(root, (Path(tmpdir) / "GameX").resolve())

    def test_project_fallback_title_uses_root_name_instead_of_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "MyRoot" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            title = project_fallback_title_from_data_folder(data_dir)
            self.assertEqual(title, "MyRoot")

    def test_project_fallback_title_uses_parent_name_when_root_is_data(self) -> None:
        fake_root = SimpleNamespace(
            name="data",
            parent=SimpleNamespace(name="ParentName"),
        )
        with patch.object(
            project_path_utils,
            "project_root_folder_for_data_folder",
            return_value=fake_root,
        ):
            title = project_fallback_title_from_data_folder(Path("data"))
        self.assertEqual(title, "ParentName")

    def test_project_fallback_title_uses_data_folder_name_when_parent_is_blank(self) -> None:
        fake_root = SimpleNamespace(
            name="",
            parent=SimpleNamespace(name=""),
        )
        with patch.object(
            project_path_utils,
            "project_root_folder_for_data_folder",
            return_value=fake_root,
        ):
            title = project_fallback_title_from_data_folder(Path("SelectedDataFolder"))
        self.assertEqual(title, "SelectedDataFolder")


if __name__ == "__main__":
    unittest.main()
