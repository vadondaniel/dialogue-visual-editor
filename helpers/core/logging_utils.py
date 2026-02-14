from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any, Optional

_LOG_FILE_NAME = "dialogue_visual_editor.log"
_DEFAULT_LOGGER_NAME = "dialogue_visual_editor"
_MAX_LOG_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 5

_configure_lock = threading.Lock()
_hooks_lock = threading.Lock()
_configured_log_path: Optional[Path] = None
_hooks_installed = False
_ExcInfoType = (
    tuple[type[BaseException], BaseException, Optional[TracebackType]]
    | tuple[None, None, None]
)


def _default_log_directory() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if isinstance(local_appdata, str) and local_appdata.strip():
        return Path(local_appdata) / "DialogueVisualEditor" / "logs"
    return Path.home() / ".dialogue_visual_editor" / "logs"


def configure_file_logging(
    log_dir: Optional[Path] = None,
    level: int = logging.INFO,
) -> Path:
    global _configured_log_path
    with _configure_lock:
        if _configured_log_path is not None:
            return _configured_log_path

        target_dir = log_dir if log_dir is not None else _default_log_directory()
        target_dir.mkdir(parents=True, exist_ok=True)
        log_path = target_dir / _LOG_FILE_NAME

        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        has_target_handler = False
        for handler in root_logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                handler_path = Path(handler.baseFilename)
                if handler_path == log_path:
                    has_target_handler = True
                    break

        if not has_target_handler:
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=_MAX_LOG_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)

        logging.captureWarnings(True)
        _configured_log_path = log_path
        return log_path


def install_global_exception_hooks(logger_name: str = _DEFAULT_LOGGER_NAME) -> None:
    global _hooks_installed
    with _hooks_lock:
        if _hooks_installed:
            return

        logger = logging.getLogger(logger_name)
        previous_excepthook = sys.excepthook
        previous_thread_hook = getattr(threading, "excepthook", None)
        previous_unraisable_hook = getattr(sys, "unraisablehook", None)

        def _normalize_exc_info(
            exc_type: Optional[type[BaseException]],
            exc_value: Optional[BaseException],
            exc_traceback: Optional[TracebackType],
        ) -> _ExcInfoType:
            if exc_type is None or exc_value is None:
                return (None, None, None)
            return (exc_type, exc_value, exc_traceback)

        def _log_excepthook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            exc_traceback: Optional[TracebackType],
        ) -> None:
            if issubclass(exc_type, KeyboardInterrupt):
                previous_excepthook(exc_type, exc_value, exc_traceback)
                return
            logger.critical(
                "Unhandled exception.",
                exc_info=_normalize_exc_info(exc_type, exc_value, exc_traceback),
            )
            previous_excepthook(exc_type, exc_value, exc_traceback)

        def _log_thread_excepthook(args: threading.ExceptHookArgs) -> None:
            if args.exc_type and issubclass(args.exc_type, KeyboardInterrupt):
                if callable(previous_thread_hook):
                    previous_thread_hook(args)
                return
            logger.critical(
                "Unhandled thread exception in '%s'.",
                args.thread.name if args.thread is not None else "unknown",
                exc_info=_normalize_exc_info(
                    args.exc_type,
                    args.exc_value,
                    args.exc_traceback,
                ),
            )
            if callable(previous_thread_hook):
                previous_thread_hook(args)

        def _log_unraisable_hook(unraisable: Any) -> None:
            logger.error(
                "Unraisable exception: %s",
                getattr(unraisable, "err_msg", "") or "(no message)",
                exc_info=_normalize_exc_info(
                    getattr(unraisable, "exc_type", None),
                    getattr(unraisable, "exc_value", None),
                    getattr(unraisable, "exc_traceback", None),
                ),
            )
            if callable(previous_unraisable_hook):
                previous_unraisable_hook(unraisable)

        sys.excepthook = _log_excepthook
        if callable(previous_thread_hook):
            threading.excepthook = _log_thread_excepthook
        if callable(previous_unraisable_hook):
            sys.unraisablehook = _log_unraisable_hook
        _hooks_installed = True
