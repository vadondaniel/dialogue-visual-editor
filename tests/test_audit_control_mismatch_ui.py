from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
import unittest
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem

from helpers.audit.audit_control_mismatch_mixin import (
    AuditControlMismatchMixin,
)
from helpers.core.models import DialogueSegment, FileSession


def _segment(
    uid: str,
    source_text: str,
    translation_text: str,
    *,
    translation_only: bool = False,
) -> DialogueSegment:
    source_lines = source_text.split("\n") if source_text else [""]
    translation_lines = translation_text.split("\n") if translation_text else [""]
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(source_lines),
        original_lines=list(source_lines),
        source_lines=list(source_lines),
        translation_lines=list(translation_lines),
        original_translation_lines=list(translation_lines),
        translation_only=translation_only,
    )


class _ButtonStub:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _CheckBoxStub:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _TimerStub:
    def __init__(self) -> None:
        self.started_with: list[int] = []

    def start(self, interval_ms: int) -> None:
        self.started_with.append(interval_ms)


class _FutureStub:
    def __init__(
        self,
        *,
        done: bool,
        payload: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._done = done
        self._payload = payload or {}
        self._error = error

    def done(self) -> bool:
        return self._done

    def result(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return dict(self._payload)


class _ExecutorStub:
    def __init__(self) -> None:
        self.raise_error: Exception | None = None
        self.return_future: Any = _FutureStub(done=False)

    def submit(self, _fn: Any, _path_sessions: Any, _only_translated: Any) -> Any:
        if self.raise_error is not None:
            raise self.raise_error
        return self.return_future


class _Harness(AuditControlMismatchMixin):
    def __init__(self) -> None:
        self.audit_control_mismatch_results_list: Any = None
        self.audit_control_mismatch_status_label: Any = None
        self.audit_control_mismatch_goto_btn: Any = None
        self.audit_control_mismatch_only_translated_check: Any = None
        self.audit_control_mismatch_progress_overlay: object = object()
        self.audit_control_mismatch_display_complete = False
        self.audit_control_mismatch_displayed_key: tuple[int, bool] | None = None
        self.audit_control_mismatch_cache_scanned_blocks = 0
        self.audit_control_mismatch_cache_key: tuple[int, bool] | None = None
        self.audit_control_mismatch_cache_records: list[dict[str, Any]] = []
        self.audit_control_mismatch_render_records: list[dict[str, Any]] = []
        self.audit_control_mismatch_render_index = 0
        self.audit_control_mismatch_render_scanned_blocks = 0
        self.audit_control_mismatch_render_only_translated = True
        self.audit_control_mismatch_render_generation = 0
        self.audit_control_mismatch_render_timer = _TimerStub()
        self.audit_cache_generation = 1
        self.audit_result_batch_size = 1
        self.audit_render_batch_interval_ms = 7
        self.sessions: dict[Path, FileSession] = {}
        self.path_sessions: list[tuple[Path, FileSession]] = []
        self.overlay_messages: list[str] = []
        self.stop_render_calls = 0
        self.jump_calls: list[tuple[str, str]] = []

        self.audit_control_worker_running_request: dict[str, Any] | None = None
        self.audit_control_worker_pending_request: dict[str, Any] | None = None
        self.audit_control_worker_future: Any = None
        self.audit_control_worker_timer = _TimerStub()
        self.audit_worker_executor = _ExecutorStub()

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

    @staticmethod
    def _audit_highlight_style() -> str:
        return "background:#ff0;"

    @staticmethod
    def _color_for_rpgm_code(code: int) -> str:
        return f"#{code:06x}"

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    def _segment_source_lines_for_display(self, segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    @staticmethod
    def _audit_entry_text_for_segment(
        _session: FileSession,
        _segment: DialogueSegment,
        index: int,
    ) -> str:
        return f"Block {index}"

    def _set_audit_progress_overlay(
        self,
        _list_widget: object,
        _overlay: object,
        message: str,
    ) -> None:
        self.overlay_messages.append(message)

    def _stop_audit_control_mismatch_render(self) -> None:
        self.stop_render_calls += 1

    def _audit_path_sessions_snapshot(self) -> list[tuple[Path, FileSession]]:
        return list(self.path_sessions)

    def _jump_to_audit_location(self, path_raw: str, uid: str) -> None:
        self.jump_calls.append((path_raw, uid))

    @staticmethod
    def _control_request_key(request: dict[str, Any] | None) -> tuple[Any, ...]:
        if not isinstance(request, dict):
            return ()
        return (
            int(request.get("generation", -1)),
            bool(request.get("only_translated", True)),
        )


def _record(uid: str, *, source_text: str = r"\C[2]JP", tl_text: str = r"\C[2]TL") -> dict[str, Any]:
    return {
        "path": Path("Map001.json"),
        "uid": uid,
        "entry_text": "Block 1",
        "source_text": source_text,
        "tl_text": tl_text,
        "missing_in_tl": Counter({r"\C[2]": 1}),
        "extra_in_tl": Counter({r"\I[1]": 1}),
        "source_token_count": 1,
        "tl_token_count": 1,
    }


class AuditControlMismatchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_token_helpers_and_counter_summary(self) -> None:
        harness = _Harness()

        matches = harness._extract_control_token_matches(r"A \C[2] B \I[1]")
        tokens = harness._extract_control_tokens(r"A \C[2] B \I[1]")
        src_hi, tl_hi = harness._control_mismatch_highlight_indices(
            [r"\C[2]", r"\I[1]"],
            [r"\C[2]", r"\N[1]"],
        )
        summary = harness._counter_summary_text(Counter({"b": 1, "a": 2, "c": 1}), limit=2)

        self.assertEqual(tokens, [r"\C[2]", r"\I[1]"])
        self.assertEqual(len(matches), 2)
        self.assertEqual(src_hi, {1})
        self.assertEqual(tl_hi, {1})
        self.assertEqual(summary, "a x2, b, ...")

    def test_render_side_and_tooltip_html(self) -> None:
        harness = _Harness()

        empty_html = harness._render_control_mismatch_side_html("", set())
        plain_html = harness._render_control_mismatch_side_html("A < B\nC", set())
        rich_html = harness._render_control_mismatch_side_html(r"X \C[2] Y \I[1]", {1})
        tooltip = harness._build_control_mismatch_tooltip_html(
            source_text=r"JP \C[2]",
            tl_text=r"TL \I[1]",
            missing_in_tl=Counter({r"\C[2]": 1}),
            extra_in_tl=Counter({r"\I[1]": 1}),
        )

        self.assertEqual(empty_html, "<i>(empty)</i>")
        self.assertIn("A &lt; B<br/>C", plain_html)
        self.assertIn("background:#ff0;", rich_html)
        self.assertIn("color: #000002;", rich_html)
        self.assertIn("Control Mismatch Preview", tooltip)
        self.assertIn("Missing", tooltip)
        self.assertIn("Translation", tooltip)

    def test_scan_groups_and_resolvers(self) -> None:
        harness = _Harness()
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[
                _segment("lead", "", "L", translation_only=True),
                _segment("a1", r"JP \C[2]", r"TL \C[2]"),
                _segment("a1f", "", r"TL \I[1]", translation_only=True),
            ],
        )
        groups = harness._control_mismatch_scan_groups(session)
        group = groups[0]
        entry_text = harness._control_mismatch_group_entry_text(
            session,
            group["anchor_segment"],
            int(group["anchor_index"]),
            list(group["segments"]),
        )

        setattr(harness, "_logical_translation_source_lines_for_segment", lambda *_args, **_kwargs: ["S1", "S2"])
        resolved_source = harness._resolve_control_mismatch_group_source_lines(session, session.segments[1])
        setattr(harness, "_logical_translation_lines_for_problem_checks", lambda *_args, **_kwargs: ["T1", "T2"])
        resolved_tl = harness._resolve_control_mismatch_group_translation_lines(
            session,
            session.segments[1],
            list(group["segments"]),
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(entry_text, "Block 2 (+2 TL splits)")
        self.assertEqual(resolved_source, ["S1", "S2"])
        self.assertEqual(resolved_tl, ["T1", "T2"])

    def test_add_result_and_go_to_selected(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_results_list = QListWidget()
        record = _record("u1")
        harness._add_audit_control_mismatch_result(
            path=record["path"],
            uid=record["uid"],
            entry_text=record["entry_text"],
            source_text=record["source_text"],
            tl_text=record["tl_text"],
            missing_in_tl=record["missing_in_tl"],
            extra_in_tl=record["extra_in_tl"],
            source_token_count=record["source_token_count"],
            tl_token_count=record["tl_token_count"],
        )

        self.assertEqual(harness.audit_control_mismatch_results_list.count(), 1)
        item = harness.audit_control_mismatch_results_list.item(0)
        widget = harness.audit_control_mismatch_results_list.itemWidget(item)
        self.assertIsInstance(widget, QLabel)
        assert isinstance(widget, QLabel)
        self.assertIn("Missing", widget.text())

        harness.audit_control_mismatch_results_list.setCurrentItem(item)
        harness._go_to_selected_audit_control_mismatch()
        self.assertEqual(harness.jump_calls, [("Map001.json", "u1")])

    def test_refresh_panel_fast_path_cache_path_and_queue_path(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_results_list = QListWidget()
        harness.audit_control_mismatch_status_label = QLabel()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness.audit_control_mismatch_only_translated_check = _CheckBoxStub(True)

        harness.audit_control_mismatch_results_list.addItem(QListWidgetItem("row"))
        harness.audit_control_mismatch_results_list.setCurrentRow(0)
        harness.audit_control_mismatch_cache_scanned_blocks = 3
        harness.audit_control_mismatch_display_complete = True
        harness.audit_control_mismatch_displayed_key = (harness.audit_cache_generation, True)
        harness._refresh_audit_control_mismatch_panel()
        self.assertIn("Found 1 mismatched block out of 3 scanned", harness.audit_control_mismatch_status_label.text())
        self.assertTrue(harness.audit_control_mismatch_goto_btn.enabled)

        harness.audit_control_mismatch_results_list.clear()
        harness.audit_control_mismatch_cache_scanned_blocks = 1
        harness._refresh_audit_control_mismatch_panel()
        self.assertEqual(
            harness.audit_control_mismatch_status_label.text(),
            "No control mismatches found across 1 scanned block (translated only).",
        )

        harness.audit_control_mismatch_display_complete = False
        harness.audit_control_mismatch_displayed_key = None
        harness.sessions = {}
        harness._refresh_audit_control_mismatch_panel()
        self.assertEqual(harness.audit_control_mismatch_status_label.text(), "No data loaded.")

        path = Path("Map001.json")
        harness.sessions = {path: FileSession(path=path, data={}, bundles=[], segments=[])}
        harness.audit_control_mismatch_cache_key = (harness.audit_cache_generation, True)
        harness.audit_control_mismatch_cache_records = []
        harness.audit_control_mismatch_cache_scanned_blocks = 2
        harness._refresh_audit_control_mismatch_panel()
        self.assertIn("No control mismatches found across 2 scanned blocks", harness.audit_control_mismatch_status_label.text())
        self.assertTrue(harness.audit_control_mismatch_display_complete)

        harness.audit_control_mismatch_display_complete = False
        harness.audit_control_mismatch_displayed_key = None
        harness.audit_control_mismatch_cache_records = [_record("u1")]
        harness._refresh_audit_control_mismatch_panel()
        self.assertIn("Found 1 mismatched block out of 2 scanned.", harness.audit_control_mismatch_status_label.text())
        self.assertEqual(harness.overlay_messages[-1], "Rendering 0/1")

        harness.audit_control_mismatch_cache_key = (999, False)
        harness.path_sessions = [(path, harness.sessions[path])]
        harness.audit_control_worker_future = object()
        harness._refresh_audit_control_mismatch_panel()
        self.assertIsNotNone(harness.audit_control_worker_pending_request)

    def test_render_batch_and_queue_worker(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_results_list = QListWidget()
        harness.audit_control_mismatch_status_label = QLabel()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness.audit_control_mismatch_render_records = [_record("u1"), _record("u2")]
        harness.audit_control_mismatch_render_scanned_blocks = 5
        harness.audit_control_mismatch_render_generation = 4
        harness.audit_control_mismatch_render_only_translated = False

        harness._render_next_audit_control_mismatch_batch()
        self.assertEqual(harness.audit_control_mismatch_render_index, 1)
        self.assertEqual(harness.overlay_messages[-1], "Rendering 1/2")
        self.assertEqual(harness.audit_control_mismatch_render_timer.started_with[-1], harness.audit_render_batch_interval_ms)

        harness._render_next_audit_control_mismatch_batch()
        self.assertEqual(harness.audit_control_mismatch_render_index, 2)
        self.assertTrue(harness.audit_control_mismatch_display_complete)
        self.assertEqual(harness.audit_control_mismatch_displayed_key, (4, False))
        self.assertTrue(harness.audit_control_mismatch_goto_btn.enabled)
        self.assertIn("Found 2 mismatched blocks out of 5 scanned.", harness.audit_control_mismatch_status_label.text())
        self.assertEqual(harness.stop_render_calls, 1)

        queue_harness = _Harness()
        queue_harness.audit_control_worker_future = object()
        request = {"generation": 1, "only_translated": True, "path_sessions": []}
        queue_harness._queue_audit_control_worker(request)
        queue_harness._queue_audit_control_worker(request)
        self.assertEqual(queue_harness.audit_control_worker_pending_request, request)

    def test_start_and_poll_worker_paths(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_status_label = QLabel()
        harness.audit_control_mismatch_results_list = QListWidget()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness.audit_control_mismatch_only_translated_check = _CheckBoxStub(True)

        request = {
            "generation": 1,
            "only_translated": True,
            "path_sessions": [],
        }
        harness.audit_control_worker_pending_request = dict(request)
        harness._start_next_audit_control_worker()
        self.assertIsNone(harness.audit_control_worker_pending_request)
        self.assertEqual(harness.audit_control_worker_running_request, request)
        self.assertEqual(harness.audit_control_worker_timer.started_with[-1], 18)

        failed = _Harness()
        failed.audit_control_mismatch_status_label = QLabel()
        failed.audit_worker_executor.raise_error = RuntimeError("submit failed")
        failed.audit_control_worker_pending_request = dict(request)
        failed._start_next_audit_control_worker()
        self.assertIn("Control mismatch scan failed: submit failed", failed.audit_control_mismatch_status_label.text())

        polling = _Harness()
        polling.audit_control_mismatch_status_label = QLabel()
        polling.audit_control_mismatch_results_list = QListWidget()
        polling.audit_control_mismatch_goto_btn = _ButtonStub()
        polling.audit_control_mismatch_only_translated_check = _CheckBoxStub(True)
        polling.audit_control_worker_running_request = dict(request)
        polling.audit_control_worker_future = _FutureStub(
            done=True,
            payload={"scanned_blocks": 2, "records": [_record("u1")]},
        )
        polling._poll_audit_control_worker()
        self.assertEqual(polling.audit_control_mismatch_cache_key, (1, True))
        self.assertEqual(polling.overlay_messages[-1], "Rendering 0/1")

        error_poll = _Harness()
        error_poll.audit_control_mismatch_status_label = QLabel()
        error_poll.audit_control_worker_running_request = dict(request)
        error_poll.audit_control_worker_future = _FutureStub(done=True, error=RuntimeError("boom"))
        error_poll._poll_audit_control_worker()
        self.assertIn("Control mismatch scan failed: boom", error_poll.audit_control_mismatch_status_label.text())


if __name__ == "__main__":
    unittest.main()
