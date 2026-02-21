from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dialogue_visual_editor.helpers.core.project_path_utils import (
    project_fallback_title_from_data_folder,
    project_root_folder_for_data_folder,
    resolve_project_data_folder,
)


def _touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ProjectPathUtilsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
