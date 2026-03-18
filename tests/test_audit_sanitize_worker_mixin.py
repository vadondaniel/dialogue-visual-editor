from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Callable, cast

from dialogue_visual_editor.helpers.audit.audit_constants import SANITIZE_CHAR_RULES
from dialogue_visual_editor.helpers.audit.audit_core_mixin import AuditCoreMixin
from dialogue_visual_editor.helpers.audit.audit_sanitize_worker_mixin import (
    AuditSanitizeWorkerMixin,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


class _TimerStub:
    def __init__(self) -> None:
        self.starts: list[int] = []

    def start(self, interval_ms: int) -> None:
        self.starts.append(interval_ms)


class _LabelStub:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def setText(self, text: str) -> None:
        self.texts.append(text)


class _RulesListStub:
    def __init__(self, item: Any = None) -> None:
        self._item = item

    def currentItem(self) -> Any:
        return self._item


class _ImmediateFuture:
    def __init__(self, *, result_value: Any = None, result_error: Exception | None = None) -> None:
        self._result_value = result_value
        self._result_error = result_error

    def done(self) -> bool:
        return True

    def result(self) -> Any:
        if self._result_error is not None:
            raise self._result_error
        return self._result_value


class _PendingFuture:
    @staticmethod
    def done() -> bool:
        return False


class _ExecutorStub:
    def __init__(self) -> None:
        self.raise_on_submit = False
        self.calls: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []
        self.forced_future: Any = None

    def submit(self, fn: Callable[..., Any], *args: Any) -> Any:
        self.calls.append((fn, args))
        if self.raise_on_submit:
            raise RuntimeError("submit failed")
        if self.forced_future is not None:
            return self.forced_future
        try:
            result = fn(*args)
            return _ImmediateFuture(result_value=result)
        except Exception as exc:  # pragma: no cover - defensive
            return _ImmediateFuture(result_error=exc)


class _Harness(AuditSanitizeWorkerMixin):
    _sanitize_request_key = AuditCoreMixin._sanitize_request_key

    def __init__(self) -> None:
        self.scope = "both"
        self.audit_cache_generation = 3
        self.audit_sanitize_worker_pending_request: dict[str, Any] | None = None
        self.audit_sanitize_worker_running_request: dict[str, Any] | None = None
        self.audit_sanitize_worker_future: Any = None
        self.audit_worker_executor = _ExecutorStub()
        self.audit_sanitize_worker_timer = _TimerStub()
        self.audit_sanitize_summary_label = _LabelStub()
        self.audit_sanitize_rules_list = _RulesListStub(item=object())
        self.audit_sanitize_occurrences_list = object()
        self.audit_sanitize_goto_btn = object()
        self.audit_sanitize_counts_cache: dict[str, int] = {}
        self.audit_sanitize_counts_cache_key: tuple[int, str] | None = None
        self.selected_rule_payload: dict[str, str] | None = {
            "rule_id": SANITIZE_CHAR_RULES[0][0],
            "find_text": SANITIZE_CHAR_RULES[0][2],
            "label": SANITIZE_CHAR_RULES[0][1],
            "replace_text": SANITIZE_CHAR_RULES[0][3],
        }
        self.applied_payload_args: dict[str, Any] | None = None

    @staticmethod
    def _audit_entry_text_for_segment(
        _session: FileSession,
        _segment: DialogueSegment,
        index: int,
    ) -> str:
        return f"Block {index}"

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    def _audit_sanitize_scope(self) -> str:
        return self.scope

    def _audit_sanitize_rule_payload(self, _item: Any) -> dict[str, str] | None:
        return self.selected_rule_payload

    def _apply_audit_sanitize_payload(self, **kwargs: Any) -> None:
        self.applied_payload_args = kwargs


def _segment(uid: str, source_line: str, translation_line: str) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[source_line],
        original_lines=[source_line],
        source_lines=[source_line],
        translation_lines=[translation_line],
        original_translation_lines=[translation_line],
    )


class AuditSanitizeWorkerMixinTests(unittest.TestCase):
    def test_compute_payload_worker_collects_counts_and_occurrences(self) -> None:
        harness = _Harness()
        selected_rule_id, _label, selected_find_text, _replace = SANITIZE_CHAR_RULES[0]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[_segment("uid-1", f"A{selected_find_text}A", selected_find_text)],
        )

        payload = harness._compute_audit_sanitize_payload_worker(
            [(session.path, session)],
            scope="both",
            selected_rule_id=selected_rule_id,
            selected_find_text=selected_find_text,
            ignored_entries_by_rule={selected_rule_id: {(str(session.path), "uid-1")}},
        )

        self.assertGreaterEqual(payload["counts"][selected_rule_id], 2)
        self.assertEqual(payload["total_hits"], 2)
        self.assertEqual(payload["entries"], 2)
        self.assertEqual(payload["block_count"], 1)

    def test_compute_occurrences_worker_collects_translation_hits(self) -> None:
        harness = _Harness()
        selected_find_text = SANITIZE_CHAR_RULES[4][2]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[_segment("uid-1", "source", f"one{selected_find_text}two")],
        )

        payload = harness._compute_audit_sanitize_occurrences_worker(
            [(session.path, session)],
            scope="translation",
            selected_find_text=selected_find_text,
            selected_ignored={(str(session.path), "uid-1")},
        )

        self.assertEqual(payload["total_hits"], 1)
        self.assertEqual(payload["entries"], 1)
        self.assertEqual(payload["block_count"], 1)

    def test_compute_occurrences_worker_handles_original_and_translation_misses(self) -> None:
        harness = _Harness()
        selected_find_text = SANITIZE_CHAR_RULES[0][2]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[
                _segment("uid-1", f"before{selected_find_text}after", "plain"),
                _segment("uid-2", "plain", "plain"),
            ],
        )

        payload = harness._compute_audit_sanitize_occurrences_worker(
            [(session.path, session)],
            scope="both",
            selected_find_text=selected_find_text,
            selected_ignored=set(),
        )

        self.assertEqual(payload["total_hits"], 1)
        self.assertEqual(payload["entries"], 1)
        self.assertEqual(payload["block_count"], 1)
        record = payload["records"][0]
        self.assertEqual(record["uid"], "uid-1")
        self.assertEqual(record["occurrences"][0]["field_label"], "OG")

    def test_queue_worker_skips_duplicate_requests(self) -> None:
        harness = _Harness()
        request = {
            "mode": "full",
            "generation": 1,
            "scope": "both",
            "selected_rule_id": "r",
            "selected_find_text": "x",
        }
        harness.audit_sanitize_worker_running_request = dict(request)
        harness._queue_audit_sanitize_worker(request)
        self.assertIsNone(harness.audit_sanitize_worker_pending_request)

        harness.audit_sanitize_worker_running_request = None
        harness.audit_sanitize_worker_pending_request = dict(request)
        harness._queue_audit_sanitize_worker(request)
        self.assertEqual(harness.audit_sanitize_worker_pending_request, request)

    def test_queue_worker_starts_worker_for_new_request_when_idle(self) -> None:
        harness = _Harness()
        request = {
            "mode": "full",
            "path_sessions": [],
            "scope": "both",
            "selected_rule_id": "r",
            "selected_find_text": "x",
            "ignored_entries_by_rule": {},
        }

        harness._queue_audit_sanitize_worker(request)

        self.assertIsNone(harness.audit_sanitize_worker_pending_request)
        self.assertEqual(harness.audit_sanitize_worker_running_request, request)
        self.assertIsNotNone(harness.audit_sanitize_worker_future)
        self.assertEqual(harness.audit_sanitize_worker_timer.starts[-1], 18)

    def test_start_next_worker_submits_occurrence_mode(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_worker_pending_request = {
            "mode": "occurrences",
            "path_sessions": [],
            "scope": "both",
            "selected_find_text": "x",
            "selected_ignored": set(),
        }

        harness._start_next_audit_sanitize_worker()

        self.assertIsNotNone(harness.audit_sanitize_worker_future)
        self.assertEqual(harness.audit_sanitize_worker_timer.starts[-1], 18)

    def test_start_next_worker_handles_submit_failure(self) -> None:
        harness = _Harness()
        harness.audit_worker_executor.raise_on_submit = True
        harness.audit_sanitize_worker_pending_request = {
            "mode": "full",
            "path_sessions": [],
            "scope": "both",
            "selected_rule_id": "r",
            "selected_find_text": "x",
            "ignored_entries_by_rule": {},
        }

        harness._start_next_audit_sanitize_worker()

        self.assertIsNone(harness.audit_sanitize_worker_future)
        self.assertIsNone(harness.audit_sanitize_worker_running_request)
        self.assertTrue(harness.audit_sanitize_summary_label.texts)

    def test_start_next_worker_returns_when_no_pending_request(self) -> None:
        harness = _Harness()

        harness._start_next_audit_sanitize_worker()

        self.assertIsNone(harness.audit_sanitize_worker_future)
        self.assertIsNone(harness.audit_sanitize_worker_running_request)

    def test_poll_worker_restarts_timer_when_future_not_done(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_worker_future = _PendingFuture()

        harness._poll_audit_sanitize_worker()

        self.assertEqual(harness.audit_sanitize_worker_timer.starts[-1], 18)

    def test_poll_worker_starts_next_when_idle_with_pending_request(self) -> None:
        harness = _Harness()
        pending = {
            "mode": "full",
            "path_sessions": [],
            "scope": "both",
            "selected_rule_id": "r",
            "selected_find_text": "x",
            "ignored_entries_by_rule": {},
        }
        harness.audit_sanitize_worker_pending_request = pending

        harness._poll_audit_sanitize_worker()

        self.assertEqual(harness.audit_sanitize_worker_running_request, pending)
        self.assertIsNone(harness.audit_sanitize_worker_pending_request)
        self.assertIsNotNone(harness.audit_sanitize_worker_future)

    def test_poll_worker_applies_payload_when_request_matches(self) -> None:
        harness = _Harness()
        selected = harness.selected_rule_payload or {}
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"counts": {selected["rule_id"]: 1}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0}
        )
        harness.audit_sanitize_worker_running_request = {
            "mode": "full",
            "generation": harness.audit_cache_generation,
            "scope": harness.scope,
            "selected_rule_id": selected["rule_id"],
            "selected_find_text": selected["find_text"],
        }

        harness._poll_audit_sanitize_worker()

        self.assertIsNotNone(harness.applied_payload_args)

    def test_poll_worker_starts_next_when_future_errors_and_pending_exists(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_error=RuntimeError("future failed")
        )
        harness.audit_sanitize_worker_running_request = {"mode": "full"}
        pending = {
            "mode": "full",
            "path_sessions": [],
            "scope": "both",
            "selected_rule_id": "r",
            "selected_find_text": "x",
            "ignored_entries_by_rule": {},
        }
        harness.audit_sanitize_worker_pending_request = pending

        harness._poll_audit_sanitize_worker()

        self.assertEqual(harness.audit_sanitize_worker_running_request, pending)
        self.assertIsNone(harness.audit_sanitize_worker_pending_request)
        self.assertIsNotNone(harness.audit_sanitize_worker_future)
        self.assertEqual(harness.audit_sanitize_summary_label.texts, [])

    def test_poll_worker_sets_error_label_when_future_errors_without_pending(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_error=RuntimeError("future failed")
        )
        harness.audit_sanitize_worker_running_request = {"mode": "full"}

        harness._poll_audit_sanitize_worker()

        self.assertIsNone(harness.audit_sanitize_worker_future)
        self.assertIsNone(harness.audit_sanitize_worker_running_request)
        self.assertIn("Sanitize scan failed:", harness.audit_sanitize_summary_label.texts[-1])

    def test_poll_worker_starts_next_when_success_but_pending_exists(self) -> None:
        harness = _Harness()
        selected = harness.selected_rule_payload or {}
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"counts": {}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0}
        )
        harness.audit_sanitize_worker_running_request = {
            "mode": "full",
            "generation": harness.audit_cache_generation,
            "scope": harness.scope,
            "selected_rule_id": selected["rule_id"],
            "selected_find_text": selected["find_text"],
        }
        pending = {
            "mode": "full",
            "path_sessions": [],
            "scope": "both",
            "selected_rule_id": "r",
            "selected_find_text": "x",
            "ignored_entries_by_rule": {},
        }
        harness.audit_sanitize_worker_pending_request = pending

        harness._poll_audit_sanitize_worker()

        self.assertEqual(harness.audit_sanitize_worker_running_request, pending)
        self.assertIsNone(harness.audit_sanitize_worker_pending_request)
        self.assertIsNotNone(harness.audit_sanitize_worker_future)
        self.assertIsNone(harness.applied_payload_args)

    def test_poll_worker_ignores_non_dict_running_request(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"counts": {}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0}
        )
        harness.audit_sanitize_worker_running_request = cast(Any, "invalid")

        harness._poll_audit_sanitize_worker()

        self.assertIsNone(harness.applied_payload_args)

    def test_poll_worker_returns_when_required_ui_state_missing(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_occurrences_list = None
        selected = harness.selected_rule_payload or {}
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"counts": {}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0}
        )
        harness.audit_sanitize_worker_running_request = {
            "mode": "full",
            "generation": harness.audit_cache_generation,
            "scope": harness.scope,
            "selected_rule_id": selected["rule_id"],
            "selected_find_text": selected["find_text"],
        }

        harness._poll_audit_sanitize_worker()

        self.assertIsNone(harness.applied_payload_args)

    def test_poll_worker_skips_payload_when_scope_mismatches(self) -> None:
        harness = _Harness()
        selected = harness.selected_rule_payload or {}
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"counts": {}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0}
        )
        harness.audit_sanitize_worker_running_request = {
            "mode": "full",
            "generation": harness.audit_cache_generation,
            "scope": "original",
            "selected_rule_id": selected["rule_id"],
            "selected_find_text": selected["find_text"],
        }

        harness._poll_audit_sanitize_worker()

        self.assertIsNone(harness.applied_payload_args)

    def test_poll_worker_skips_payload_when_rule_selection_changed(self) -> None:
        harness = _Harness()
        selected = harness.selected_rule_payload or {}
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"counts": {}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0}
        )
        harness.audit_sanitize_worker_running_request = {
            "mode": "full",
            "generation": harness.audit_cache_generation,
            "scope": harness.scope,
            "selected_rule_id": "different",
            "selected_find_text": selected["find_text"],
        }

        harness._poll_audit_sanitize_worker()

        self.assertIsNone(harness.applied_payload_args)

    def test_poll_worker_occurrences_mode_merges_with_zeroed_counts_when_key_mismatches(self) -> None:
        harness = _Harness()
        selected = harness.selected_rule_payload or {}
        harness.audit_sanitize_counts_cache = {selected["rule_id"]: 9}
        harness.audit_sanitize_counts_cache_key = (harness.audit_cache_generation + 1, harness.scope)
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"records": [], "total_hits": 1, "entries": 1, "block_count": 1}
        )
        harness.audit_sanitize_worker_running_request = {
            "mode": "occurrences",
            "generation": harness.audit_cache_generation,
            "scope": harness.scope,
            "selected_rule_id": selected["rule_id"],
            "selected_find_text": selected["find_text"],
        }

        harness._poll_audit_sanitize_worker()

        self.assertIsNotNone(harness.applied_payload_args)
        payload = cast(dict[str, Any], harness.applied_payload_args)["payload"]
        self.assertEqual(len(payload["counts"]), len(SANITIZE_CHAR_RULES))
        self.assertEqual(payload["counts"][selected["rule_id"]], 0)

    def test_poll_worker_skips_payload_when_generation_mismatches(self) -> None:
        harness = _Harness()
        selected = harness.selected_rule_payload or {}
        harness.audit_sanitize_worker_future = _ImmediateFuture(
            result_value={"counts": {}, "records": [], "total_hits": 0, "entries": 0, "block_count": 0}
        )
        harness.audit_sanitize_worker_running_request = {
            "mode": "full",
            "generation": harness.audit_cache_generation + 1,
            "scope": harness.scope,
            "selected_rule_id": selected["rule_id"],
            "selected_find_text": selected["find_text"],
        }

        harness._poll_audit_sanitize_worker()

        self.assertIsNone(harness.applied_payload_args)


if __name__ == "__main__":
    unittest.main()
