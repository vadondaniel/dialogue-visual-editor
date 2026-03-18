from __future__ import annotations

import runpy
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class DialogueVisualEditorPywTests(unittest.TestCase):
    @staticmethod
    def _pyw_path() -> Path:
        return Path(__file__).resolve().parents[1] / "dialogue_visual_editor.pyw"

    @staticmethod
    def _fake_app_module(exit_code: int = 11) -> types.ModuleType:
        fake_module = types.ModuleType("app")

        class _FakeEditor:
            pass

        def _fake_main() -> int:
            return exit_code

        setattr(fake_module, "DialogueVisualEditor", _FakeEditor)
        setattr(fake_module, "main", _fake_main)
        return fake_module

    def test_pyw_exports_dialogue_editor_and_main(self) -> None:
        fake_module = self._fake_app_module()
        with patch.dict("sys.modules", {"app": fake_module}, clear=False):
            result = runpy.run_path(str(self._pyw_path()), run_name="dialogue_visual_editor_stub")

        self.assertEqual(result["__all__"], ["DialogueVisualEditor", "main"])
        self.assertIs(result["DialogueVisualEditor"], fake_module.DialogueVisualEditor)
        self.assertIs(result["main"], fake_module.main)

    def test_pyw_main_entrypoint_raises_system_exit_with_main_code(self) -> None:
        fake_module = self._fake_app_module(exit_code=23)
        with patch.dict("sys.modules", {"app": fake_module}, clear=False):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(str(self._pyw_path()), run_name="__main__")

        self.assertEqual(raised.exception.code, 23)


if __name__ == "__main__":
    unittest.main()
