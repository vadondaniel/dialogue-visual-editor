from __future__ import annotations

import logging
import sys
import tempfile
import threading
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from helpers.core import logging_utils


class LoggingUtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root_logger = logging.getLogger()
        self.original_handlers = list(self.root_logger.handlers)
        self.original_level = self.root_logger.level
        self.original_sys_excepthook = sys.excepthook
        self.original_thread_excepthook = threading.excepthook
        self.original_unraisablehook = sys.unraisablehook
        self.original_configured_log_path = logging_utils._configured_log_path
        self.original_hooks_installed = logging_utils._hooks_installed

        for handler in self.original_handlers:
            self.root_logger.removeHandler(handler)
        logging_utils._configured_log_path = None
        logging_utils._hooks_installed = False

    def tearDown(self) -> None:
        for handler in list(self.root_logger.handlers):
            self.root_logger.removeHandler(handler)
            if handler not in self.original_handlers:
                handler.close()
        for handler in self.original_handlers:
            self.root_logger.addHandler(handler)
        self.root_logger.setLevel(self.original_level)

        sys.excepthook = self.original_sys_excepthook
        threading.excepthook = self.original_thread_excepthook
        sys.unraisablehook = self.original_unraisablehook
        logging_utils._configured_log_path = self.original_configured_log_path
        logging_utils._hooks_installed = self.original_hooks_installed

    def test_default_log_directory_prefers_localappdata(self) -> None:
        with patch.dict(
            logging_utils.os.environ,
            {"LOCALAPPDATA": r"C:\Users\Tester\AppData\Local"},
            clear=True,
        ):
            target = logging_utils._default_log_directory()

        expected = (
            Path(r"C:\Users\Tester\AppData\Local")
            / "DialogueVisualEditor"
            / "logs"
        )
        self.assertEqual(target, expected)

    def test_default_log_directory_falls_back_to_home(self) -> None:
        fallback_home = Path("C:/Users/UnitTest")
        with patch.dict(logging_utils.os.environ, {"LOCALAPPDATA": "   "}, clear=True):
            with patch.object(logging_utils.Path, "home", return_value=fallback_home):
                target = logging_utils._default_log_directory()

        self.assertEqual(
            target,
            fallback_home / ".dialogue_visual_editor" / "logs",
        )

    def test_configure_file_logging_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            first_path = logging_utils.configure_file_logging(
                log_dir=target_dir,
                level=logging.DEBUG,
            )
            second_path = logging_utils.configure_file_logging(
                log_dir=target_dir,
                level=logging.ERROR,
            )

            self.assertEqual(first_path, second_path)
            matching_handlers = [
                handler
                for handler in self.root_logger.handlers
                if isinstance(handler, RotatingFileHandler)
                and Path(handler.baseFilename) == first_path
            ]
            self.assertEqual(len(matching_handlers), 1)
            for handler in matching_handlers:
                self.root_logger.removeHandler(handler)
                handler.close()

        self.assertEqual(logging_utils._configured_log_path, first_path)
        self.assertEqual(self.root_logger.level, logging.DEBUG)

    def test_configure_file_logging_prefers_first_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first_dir = Path(tmpdir) / "first"
            second_dir = Path(tmpdir) / "second"
            first_path = logging_utils.configure_file_logging(
                log_dir=first_dir,
                level=logging.INFO,
            )
            second_path = logging_utils.configure_file_logging(
                log_dir=second_dir,
                level=logging.ERROR,
            )

            self.assertEqual(first_path, second_path)
            self.assertEqual(first_path, first_dir / "dialogue_visual_editor.log")
            self.assertFalse(second_dir.exists())
            for handler in list(self.root_logger.handlers):
                if isinstance(handler, RotatingFileHandler) and Path(
                    handler.baseFilename
                ) == first_path:
                    self.root_logger.removeHandler(handler)
                    handler.close()

    def test_install_global_exception_hooks_thread_hook_with_missing_exception_type(
        self,
    ) -> None:
        logger = Mock()
        thread_calls: list[threading.ExceptHookArgs] = []

        def previous_thread_hook(args: threading.ExceptHookArgs) -> None:
            thread_calls.append(args)

        def previous_sys_hook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            _exc_tb: object,
        ) -> None:
            pass

        sys.excepthook = previous_sys_hook
        threading.excepthook = previous_thread_hook
        sys.unraisablehook = None  # type: ignore[assignment]

        with patch.object(logging_utils.logging, "getLogger", return_value=logger):
            logging_utils.install_global_exception_hooks("dialogue_visual_editor.tests")

        null_thread_args = threading.ExceptHookArgs((None, None, None, None))
        threading.excepthook(null_thread_args)  # type: ignore[arg-type]

        self.assertEqual(len(thread_calls), 1)
        self.assertEqual(thread_calls[0], null_thread_args)
        self.assertEqual(logger.critical.call_count, 1)
        self.assertEqual(logger.critical.call_args_list[0].kwargs["exc_info"], (None, None, None))
        self.assertEqual(logger.critical.call_args_list[0].args[1], "unknown")

    def test_configure_file_logging_reuses_existing_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "logs"
            target_dir.mkdir(parents=True, exist_ok=True)
            log_path = target_dir / "dialogue_visual_editor.log"
            existing_handler = RotatingFileHandler(
                log_path,
                maxBytes=1024,
                backupCount=1,
                encoding="utf-8",
            )
            self.root_logger.addHandler(existing_handler)

            with patch.object(
                logging_utils,
                "_default_log_directory",
                return_value=target_dir,
            ):
                configured_path = logging_utils.configure_file_logging(
                    log_dir=None,
                    level=logging.WARNING,
                )

            self.assertEqual(configured_path, log_path)
            matching_handlers = [
                handler
                for handler in self.root_logger.handlers
                if isinstance(handler, RotatingFileHandler)
                and Path(handler.baseFilename) == configured_path
            ]
            self.assertEqual(len(matching_handlers), 1)
            for handler in matching_handlers:
                self.root_logger.removeHandler(handler)
                handler.close()

    def test_default_log_directory_uses_home_when_localappdata_is_missing(self) -> None:
        fallback_home = Path("C:/Users/UnitTest")
        with patch.dict(logging_utils.os.environ, {}, clear=True):
            with patch.object(logging_utils.Path, "home", return_value=fallback_home):
                target = logging_utils._default_log_directory()

        self.assertEqual(
            target,
            fallback_home / ".dialogue_visual_editor" / "logs",
        )

    def test_configure_file_logging_creates_directory_and_registers_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "nested" / "logs"
            with patch.object(logging_utils.logging, "captureWarnings") as capture_warnings:
                configured_path = logging_utils.configure_file_logging(
                    log_dir=target_dir,
                    level=logging.WARNING,
                )

            self.assertEqual(configured_path, target_dir / "dialogue_visual_editor.log")
            self.assertTrue(target_dir.is_dir())
            self.assertEqual(capture_warnings.call_count, 1)
            self.assertEqual(capture_warnings.call_args.args[0], True)
            self.assertEqual(self.root_logger.level, logging.WARNING)

            matching_handlers = [
                handler
                for handler in self.root_logger.handlers
                if isinstance(handler, RotatingFileHandler)
                and Path(handler.baseFilename) == configured_path
            ]
            self.assertEqual(len(matching_handlers), 1)
            for handler in list(self.root_logger.handlers):
                if isinstance(handler, RotatingFileHandler) and Path(
                    handler.baseFilename
                ) == configured_path:
                    self.root_logger.removeHandler(handler)
                    handler.close()

    def test_configure_file_logging_adds_new_handler_for_different_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            existing_dir = target_dir / "existing"
            existing_dir.mkdir(parents=True, exist_ok=True)
            existing_path = existing_dir / "dialogue_visual_editor.log"
            existing_handler = RotatingFileHandler(
                existing_path,
                maxBytes=1024,
                backupCount=1,
                encoding="utf-8",
            )
            self.root_logger.addHandler(existing_handler)

            configured_path = logging_utils.configure_file_logging(
                log_dir=target_dir,
                level=logging.INFO,
            )

            handler_paths = {
                Path(handler.baseFilename)
                for handler in self.root_logger.handlers
                if isinstance(handler, RotatingFileHandler)
            }
            self.assertIn(existing_path, handler_paths)
            self.assertIn(configured_path, handler_paths)
            self.assertEqual(len(handler_paths), 2)
            for handler in list(self.root_logger.handlers):
                if isinstance(handler, RotatingFileHandler):
                    self.root_logger.removeHandler(handler)
                    handler.close()

    def test_install_global_exception_hooks_delegates_to_existing_hooks(
        self,
    ) -> None:
        logger = Mock()
        sys_calls: list[tuple[type[BaseException], BaseException]] = []
        thread_calls: list[threading.ExceptHookArgs] = []
        unraisable_calls: list[object] = []

        def previous_sys_hook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            _exc_tb: object,
        ) -> None:
            sys_calls.append((exc_type, exc_value))

        def previous_thread_hook(args: threading.ExceptHookArgs) -> None:
            thread_calls.append(args)

        def previous_unraisable_hook(unraisable: object) -> None:
            unraisable_calls.append(unraisable)

        sys.excepthook = previous_sys_hook
        threading.excepthook = previous_thread_hook
        sys.unraisablehook = previous_unraisable_hook

        with patch.object(logging_utils.logging, "getLogger", return_value=logger) as get_logger:
            logging_utils.install_global_exception_hooks("dialogue_visual_editor.custom")

        self.assertEqual(get_logger.call_args.args[0], "dialogue_visual_editor.custom")

        try:
            raise RuntimeError("worker failed")
        except RuntimeError:
            exc_type, exc_value, exc_traceback = sys.exc_info()

        self.assertIsNotNone(exc_type)
        self.assertIsNotNone(exc_value)
        sys.excepthook(exc_type, exc_value, exc_traceback)  # type: ignore[arg-type]
        self.assertEqual(len(sys_calls), 1)
        self.assertEqual(logger.critical.call_count, 1)

        worker = threading.Thread(name="Worker-2")
        thread_args = threading.ExceptHookArgs(
            (exc_type, exc_value, exc_traceback, worker)
        )
        threading.excepthook(thread_args)  # type: ignore[arg-type]
        self.assertEqual(len(thread_calls), 1)
        self.assertIs(thread_calls[0], thread_args)
        self.assertEqual(logger.critical.call_count, 2)

        unraisable = SimpleNamespace(
            err_msg="during async op",
            exc_type=exc_type,
            exc_value=exc_value,
            exc_traceback=exc_traceback,
        )
        sys.unraisablehook(unraisable)
        self.assertEqual(len(unraisable_calls), 1)
        self.assertEqual(logger.error.call_count, 1)
        self.assertIs(unraisable_calls[0], unraisable)

    def test_install_global_exception_hooks_logs_and_delegates(self) -> None:
        logger = Mock()
        sys_calls: list[tuple[type[BaseException], BaseException]] = []
        thread_calls: list[threading.ExceptHookArgs] = []
        unraisable_calls: list[object] = []

        def previous_sys_hook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            _exc_tb: object,
        ) -> None:
            sys_calls.append((exc_type, exc_value))

        def previous_thread_hook(args: threading.ExceptHookArgs) -> None:
            thread_calls.append(args)

        def previous_unraisable_hook(unraisable: object) -> None:
            unraisable_calls.append(unraisable)

        sys.excepthook = previous_sys_hook
        threading.excepthook = previous_thread_hook
        sys.unraisablehook = previous_unraisable_hook

        with patch.object(logging_utils.logging, "getLogger", return_value=logger) as get_logger:
            logging_utils.install_global_exception_hooks("dialogue_visual_editor.tests")
            logging_utils.install_global_exception_hooks("dialogue_visual_editor.tests")

        self.assertEqual(get_logger.call_count, 1)

        try:
            raise ValueError("boom")
        except ValueError:
            exc_type, exc_value, exc_traceback = sys.exc_info()

        self.assertIsNotNone(exc_type)
        self.assertIsNotNone(exc_value)
        sys.excepthook(exc_type, exc_value, exc_traceback)  # type: ignore[arg-type]
        self.assertEqual(len(sys_calls), 1)
        self.assertEqual(logger.critical.call_count, 1)
        self.assertEqual(logger.critical.call_args_list[0].args[0], "Unhandled exception.")
        self.assertEqual(
            logger.critical.call_args_list[0].kwargs["exc_info"][0],
            ValueError,
        )

        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.assertEqual(len(sys_calls), 2)
        self.assertEqual(logger.critical.call_count, 1)

        worker = threading.Thread(name="Worker-1")
        thread_args = threading.ExceptHookArgs((exc_type, exc_value, exc_traceback, worker))
        threading.excepthook(thread_args)  # type: ignore[arg-type]
        self.assertEqual(len(thread_calls), 1)
        self.assertEqual(logger.critical.call_count, 2)
        self.assertEqual(
            logger.critical.call_args_list[1].args[0],
            "Unhandled thread exception in '%s'.",
        )
        self.assertEqual(logger.critical.call_args_list[1].args[1], "Worker-1")

        unknown_thread_args = threading.ExceptHookArgs(
            (exc_type, exc_value, exc_traceback, None)
        )
        threading.excepthook(unknown_thread_args)  # type: ignore[arg-type]
        self.assertEqual(len(thread_calls), 2)
        self.assertEqual(logger.critical.call_count, 3)
        self.assertEqual(logger.critical.call_args_list[2].args[1], "unknown")

        keyboard_thread_args = threading.ExceptHookArgs(
            (KeyboardInterrupt, KeyboardInterrupt(), None, worker)
        )
        threading.excepthook(keyboard_thread_args)  # type: ignore[arg-type]
        self.assertEqual(len(thread_calls), 3)
        self.assertEqual(logger.critical.call_count, 3)

        unraisable = SimpleNamespace(
            err_msg="during finalizer",
            exc_type=exc_type,
            exc_value=exc_value,
            exc_traceback=exc_traceback,
        )
        sys.unraisablehook(unraisable)
        self.assertEqual(len(unraisable_calls), 1)
        self.assertEqual(logger.error.call_count, 1)
        self.assertEqual(
            logger.error.call_args_list[0].args[0],
            "Unraisable exception: %s",
        )
        self.assertEqual(logger.error.call_args_list[0].args[1], "during finalizer")

        unraisable_empty = SimpleNamespace(
            err_msg="",
            exc_type=None,
            exc_value=None,
            exc_traceback=None,
        )
        sys.unraisablehook(unraisable_empty)
        self.assertEqual(len(unraisable_calls), 2)
        self.assertEqual(logger.error.call_count, 2)
        self.assertEqual(logger.error.call_args_list[1].args[1], "(no message)")
        self.assertEqual(
            logger.error.call_args_list[1].kwargs["exc_info"],
            (None, None, None),
        )

    def test_install_global_exception_hooks_handles_missing_optional_hooks(self) -> None:
        logger = Mock()
        sys_calls: list[tuple[type[BaseException], BaseException]] = []

        def previous_sys_hook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            _exc_tb: object,
        ) -> None:
            sys_calls.append((exc_type, exc_value))

        sys.excepthook = previous_sys_hook
        threading.excepthook = None  # type: ignore[assignment]
        sys.unraisablehook = None  # type: ignore[assignment]

        with patch.object(logging_utils.logging, "getLogger", return_value=logger):
            logging_utils.install_global_exception_hooks("dialogue_visual_editor.tests")

        self.assertIsNone(threading.excepthook)
        self.assertIsNone(sys.unraisablehook)

        try:
            raise RuntimeError("broken")
        except RuntimeError:
            exc_type, exc_value, exc_traceback = sys.exc_info()

        self.assertIsNotNone(exc_type)
        self.assertIsNotNone(exc_value)
        sys.excepthook(exc_type, exc_value, exc_traceback)  # type: ignore[arg-type]
        self.assertEqual(len(sys_calls), 1)
        self.assertEqual(logger.critical.call_count, 1)


if __name__ == "__main__":
    unittest.main()
