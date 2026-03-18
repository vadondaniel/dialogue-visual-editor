from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dialogue_visual_editor import app


class AppEntrypointTests(unittest.TestCase):
    def test_set_windows_app_id_calls_shell_api_on_win32(self) -> None:
        set_app_id = Mock()
        fake_shell32 = type("Shell32", (), {"SetCurrentProcessExplicitAppUserModelID": set_app_id})()
        fake_windll = type("Windll", (), {"shell32": fake_shell32})()

        with patch("dialogue_visual_editor.app.sys.platform", "win32"):
            with patch("dialogue_visual_editor.app.ctypes.windll", fake_windll):
                app._set_windows_app_id("com.test.app")

        set_app_id.assert_called_once_with("com.test.app")

    def test_set_windows_app_id_ignores_shell_api_errors(self) -> None:
        set_app_id = Mock(side_effect=RuntimeError("boom"))
        fake_shell32 = type("Shell32", (), {"SetCurrentProcessExplicitAppUserModelID": set_app_id})()
        fake_windll = type("Windll", (), {"shell32": fake_shell32})()

        with patch("dialogue_visual_editor.app.sys.platform", "win32"):
            with patch("dialogue_visual_editor.app.ctypes.windll", fake_windll):
                app._set_windows_app_id("com.test.app")

        set_app_id.assert_called_once_with("com.test.app")

    def test_set_windows_app_id_noop_on_non_windows(self) -> None:
        with patch("dialogue_visual_editor.app.sys.platform", "linux"):
            with patch("dialogue_visual_editor.app.ctypes.windll", create=True) as windll_mock:
                app._set_windows_app_id("com.test.app")
        self.assertFalse(windll_mock.shell32.SetCurrentProcessExplicitAppUserModelID.called)

    def test_main_success_path_sets_icons_and_returns_exit_code(self) -> None:
        fake_qapp = Mock()
        fake_qapp.exec.return_value = 7
        fake_window = Mock()
        fake_icon = Mock()
        fake_icon.isNull.return_value = False

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_app_path = Path(tmpdir) / "app.py"
            fake_app_path.write_text("# placeholder", encoding="utf-8")

            with patch("dialogue_visual_editor.app._set_windows_app_id") as set_id_mock:
                with patch("dialogue_visual_editor.app.configure_file_logging", return_value=Path(tmpdir) / "log.txt"):
                    with patch("dialogue_visual_editor.app.install_global_exception_hooks") as install_hooks_mock:
                        with patch("dialogue_visual_editor.app.QApplication", return_value=fake_qapp):
                            with patch("dialogue_visual_editor.app.QIcon", return_value=fake_icon):
                                with patch("dialogue_visual_editor.app.DialogueVisualEditor", return_value=fake_window):
                                    with patch("dialogue_visual_editor.app.logger") as logger_mock:
                                        with patch("dialogue_visual_editor.app.__file__", str(fake_app_path)):
                                            exit_code = app.main()

        self.assertEqual(exit_code, 7)
        set_id_mock.assert_called_once_with(app.APP_ID)
        install_hooks_mock.assert_called_once()
        fake_qapp.setWindowIcon.assert_called_once_with(fake_icon)
        fake_window.setWindowIcon.assert_called_once_with(fake_icon)
        fake_window.show.assert_called_once()
        logger_mock.info.assert_called()

    def test_main_uses_warning_when_logging_setup_fails(self) -> None:
        fake_qapp = Mock()
        fake_qapp.exec.return_value = 0
        fake_window = Mock()
        fake_icon = Mock()
        fake_icon.isNull.return_value = False

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_app_path = Path(tmpdir) / "app.py"
            fake_app_path.write_text("# placeholder", encoding="utf-8")

            with patch("dialogue_visual_editor.app.configure_file_logging", side_effect=RuntimeError("fail")):
                with patch("dialogue_visual_editor.app.install_global_exception_hooks"):
                    with patch("dialogue_visual_editor.app.QApplication", return_value=fake_qapp):
                        with patch("dialogue_visual_editor.app.QIcon", return_value=fake_icon):
                            with patch("dialogue_visual_editor.app.DialogueVisualEditor", return_value=fake_window):
                                with patch("dialogue_visual_editor.app.logger") as logger_mock:
                                    with patch("dialogue_visual_editor.app.__file__", str(fake_app_path)):
                                        exit_code = app.main()

        self.assertEqual(exit_code, 0)
        logger_mock.warning.assert_called_once()

    def test_main_raises_when_icon_is_invalid(self) -> None:
        fake_qapp = Mock()
        fake_icon = Mock()
        fake_icon.isNull.return_value = True

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_app_path = Path(tmpdir) / "app.py"
            fake_app_path.write_text("# placeholder", encoding="utf-8")

            with patch("dialogue_visual_editor.app.configure_file_logging", return_value=Path(tmpdir) / "log.txt"):
                with patch("dialogue_visual_editor.app.install_global_exception_hooks"):
                    with patch("dialogue_visual_editor.app.QApplication", return_value=fake_qapp):
                        with patch("dialogue_visual_editor.app.QIcon", return_value=fake_icon):
                            with patch("dialogue_visual_editor.app.__file__", str(fake_app_path)):
                                with self.assertRaises(FileNotFoundError):
                                    app.main()


if __name__ == "__main__":
    unittest.main()

