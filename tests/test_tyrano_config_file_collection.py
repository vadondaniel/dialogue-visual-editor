from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional, cast

from app import DialogueVisualEditor


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


class _Harness:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.detected_rpg_engine = "tyrano"

    def _relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.data_dir).as_posix()
        except Exception:
            return path.as_posix()

    def _candidate_tyrano_scenario_dirs(self, folder: Path) -> list[Path]:
        return cast(
            list[Path],
            _call_editor_method("_candidate_tyrano_scenario_dirs", self, folder),
        )

    def _resolve_tyrano_scenario_dir(self, folder: Path) -> Optional[Path]:
        return cast(
            Optional[Path],
            _call_editor_method("_resolve_tyrano_scenario_dir", self, folder),
        )

    def _tyrano_config_candidates(self, data_dir: Path) -> list[Path]:
        return cast(
            list[Path],
            _call_editor_method("_tyrano_config_candidates", self, data_dir),
        )

    def _collect_tyrano_script_paths(self, data_dir: Path) -> list[Path]:
        return cast(
            list[Path],
            _call_editor_method("_collect_tyrano_script_paths", self, data_dir),
        )


class TyranoConfigFileCollectionTests(unittest.TestCase):
    def test_collect_tyrano_script_paths_includes_config_tjs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            scenario_dir = data_dir / "scenario"
            system_dir = data_dir / "system"
            scenario_dir.mkdir(parents=True)
            system_dir.mkdir(parents=True)
            ks_path = scenario_dir / "scene1.ks"
            config_path = system_dir / "Config.tjs"
            ks_path.write_text("[tb_start_text mode=1 ]\nline[p]\n[_tb_end_text]\n", encoding="utf-8")
            config_path.write_text(";System.title=Title\n", encoding="utf-8")

            harness = _Harness(data_dir)
            collected = harness._collect_tyrano_script_paths(data_dir)

        self.assertIn(ks_path.resolve(), collected)
        self.assertIn(config_path.resolve(), collected)

    def test_collect_supported_file_paths_for_tyrano_includes_config_tjs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            scenario_dir = data_dir / "scenario"
            system_dir = data_dir / "system"
            scenario_dir.mkdir(parents=True)
            system_dir.mkdir(parents=True)
            (scenario_dir / "scene1.ks").write_text(
                "[tb_start_text mode=1 ]\nline[p]\n[_tb_end_text]\n",
                encoding="utf-8",
            )
            config_path = system_dir / "Config.tjs"
            config_path.write_text(";System.title=Title\n", encoding="utf-8")

            harness = _Harness(data_dir)
            collected = cast(
                list[Path],
                _call_editor_method("_collect_supported_file_paths", harness, data_dir),
            )

        self.assertIn(config_path.resolve(), collected)

    def test_collect_tyrano_script_paths_includes_others_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            scenario_dir = data_dir / "scenario"
            others_dir = data_dir / "others"
            scenario_dir.mkdir(parents=True)
            others_dir.mkdir(parents=True)
            ks_path = scenario_dir / "scene1.ks"
            const_js_path = others_dir / "const.js"
            script_js_path = others_dir / "script.js"
            ks_path.write_text("[tb_start_text mode=1 ]\nline[p]\n[_tb_end_text]\n", encoding="utf-8")
            const_js_path.write_text("const A = 'x';\n", encoding="utf-8")
            script_js_path.write_text("const B = 'y';\n", encoding="utf-8")

            harness = _Harness(data_dir)
            collected = harness._collect_tyrano_script_paths(data_dir)

        self.assertIn(ks_path.resolve(), collected)
        self.assertIn(const_js_path.resolve(), collected)
        self.assertIn(script_js_path.resolve(), collected)

    def test_collect_supported_file_paths_for_tyrano_includes_others_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            scenario_dir = data_dir / "scenario"
            others_dir = data_dir / "others"
            scenario_dir.mkdir(parents=True)
            others_dir.mkdir(parents=True)
            (scenario_dir / "scene1.ks").write_text(
                "[tb_start_text mode=1 ]\nline[p]\n[_tb_end_text]\n",
                encoding="utf-8",
            )
            const_js_path = others_dir / "const.js"
            const_js_path.write_text("const A = 'x';\n", encoding="utf-8")

            harness = _Harness(data_dir)
            collected = cast(
                list[Path],
                _call_editor_method("_collect_supported_file_paths", harness, data_dir),
            )

        self.assertIn(const_js_path.resolve(), collected)


if __name__ == "__main__":
    unittest.main()
