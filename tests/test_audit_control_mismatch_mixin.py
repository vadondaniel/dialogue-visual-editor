from __future__ import annotations

from collections import Counter
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

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


class _Harness(AuditControlMismatchMixin):
    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            normalized: list[str] = []
            for item in value:
                if isinstance(item, str):
                    normalized.append(item)
                elif item is None:
                    normalized.append("")
                else:
                    normalized.append(str(item))
            return normalized or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    def _segment_source_lines_for_display(self, segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    def _audit_entry_text_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
        index: int,
    ) -> str:
        _ = session
        _ = segment
        return f"Block {index}"

    @staticmethod
    def _control_request_key(request: dict[str, Any] | None) -> tuple[Any, ...]:
        if not isinstance(request, dict):
            return ()
        return (
            request.get("generation"),
            request.get("only_translated"),
        )

    @staticmethod
    def _audit_highlight_style() -> str:
        return "background-color:#facc15; color:#111827;"

    @staticmethod
    def _color_for_rpgm_code(code: int) -> str:
        return f"#{code:06d}"

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

    def _jump_to_audit_location(self, path_raw: str, uid_raw: str) -> None:
        self.last_jump = (path_raw, uid_raw)

    def _stop_audit_control_mismatch_render(self) -> None:
        self.stop_render_calls = getattr(self, "stop_render_calls", 0) + 1


class _TimerStub:
    def __init__(self) -> None:
        self.started: list[int] = []

    def start(self, interval_ms: int) -> None:
        self.started.append(int(interval_ms))


class _FutureStub:
    def __init__(self, *, done: bool, result_payload: Any = None, error: Exception | None = None) -> None:
        self._done = done
        self._result_payload = result_payload
        self._error = error

    def done(self) -> bool:
        return self._done

    def result(self) -> Any:
        if self._error is not None:
            raise self._error
        return self._result_payload


class _StatusLabelStub:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _ButtonStub:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


class _CheckStub:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _ItemStub:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self, _role: Any) -> Any:
        return self._payload


class _ResultsListStub:
    def __init__(self, current_item: _ItemStub | None = None) -> None:
        self._current_item = current_item
        self._updates_enabled = True
        self._count = 0

    def currentItem(self) -> _ItemStub | None:
        return self._current_item

    def count(self) -> int:
        return self._count

    def clear(self) -> None:
        self._count = 0

    def updatesEnabled(self) -> bool:
        return self._updates_enabled

    def setUpdatesEnabled(self, enabled: bool) -> None:
        self._updates_enabled = bool(enabled)

    def setCurrentRow(self, _row: int) -> None:
        return

    def addItem(self, _item: Any) -> None:
        self._count += 1

    def setItemWidget(self, _item: Any, _widget: Any) -> None:
        return


class AuditControlMismatchMixinTests(unittest.TestCase):
    def test_extract_matches_and_counter_summary_defensive(self) -> None:
        harness = _Harness()
        self.assertEqual(harness._extract_control_token_matches(""), [])
        self.assertEqual(harness._counter_summary_text(Counter()), "(none)")

    def test_render_side_html_handles_invalid_color_capture(self) -> None:
        harness = _Harness()

        class _BadMatch:
            @staticmethod
            def group(_index: int) -> str:
                return "bad"

        class _BadRegex:
            @staticmethod
            def fullmatch(_token: str) -> _BadMatch:
                return _BadMatch()

        with patch.object(
            harness,
            "_extract_control_token_matches",
            return_value=[(r"\C[bad]", 0, 7)],
        ):
            with patch(
                "helpers.audit.audit_control_mismatch_mixin.COLOR_CODE_TOKEN_RE",
                new=_BadRegex(),
            ):
                rendered = harness._render_control_mismatch_side_html(r"\C[bad] tail", {0})
        self.assertIn("opacity: 0.92;", rendered)
        self.assertIn("#000000", rendered)

    def test_scan_groups_all_translation_only_uses_first_segment_as_anchor(self) -> None:
        harness = _Harness()
        first = _segment("Map001.json:I:1", "", r"TL \!", translation_only=True)
        second = _segment("Map001.json:I:2", "", r"TL \.", translation_only=True)
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[first, second],
        )

        groups = harness._control_mismatch_scan_groups(session)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["anchor_segment"].uid, "Map001.json:I:1")
        self.assertEqual(groups[0]["anchor_index"], 1)
        self.assertEqual(len(groups[0]["segments"]), 2)

    def test_group_translation_lines_falls_back_when_segment_normalizer_raises(self) -> None:
        harness = _Harness()
        segment = _segment("Map001.json:L0:0", "JP", r"TL \!")

        def _raiser(_segment: DialogueSegment, _lines: list[str]) -> list[str]:
            raise RuntimeError("normalize failed")

        setattr(harness, "_normalize_audit_translation_lines_for_segment", _raiser)
        lines = harness._control_mismatch_group_translation_lines([segment])
        self.assertEqual(lines, [r"TL \!"])

    def test_group_translation_lines_uses_segment_normalizer_when_available(self) -> None:
        harness = _Harness()
        segment = _segment("Map001.json:L0:0", "JP", "TL")
        setattr(
            harness,
            "_normalize_audit_translation_lines_for_segment",
            lambda _segment, _lines: ["TL-A", "TL-B"],
        )
        lines = harness._control_mismatch_group_translation_lines([segment])
        self.assertEqual(lines, ["TL-A", "TL-B"])

    def test_resolve_source_lines_fallback_paths(self) -> None:
        harness = _Harness()
        session = FileSession(path=Path("Map001.json"), data={}, bundles=[], segments=[])
        segment = _segment("Map001.json:L0:0", "JP source", "TL")

        def _type_error_resolver(anchor: DialogueSegment) -> list[str]:
            return [f"{anchor.uid}-logical-source"]

        setattr(harness, "_logical_translation_source_lines_for_segment", _type_error_resolver)
        resolved_via_type_error = harness._resolve_control_mismatch_group_source_lines(
            session,
            segment,
        )
        self.assertEqual(resolved_via_type_error, ["Map001.json:L0:0-logical-source"])

        def _error_resolver(_anchor: DialogueSegment, session: FileSession | None = None) -> list[str]:
            _ = session
            raise RuntimeError("broken")

        setattr(harness, "_logical_translation_source_lines_for_segment", _error_resolver)
        resolved_via_exception = harness._resolve_control_mismatch_group_source_lines(
            session,
            segment,
        )
        self.assertEqual(resolved_via_exception, ["JP source"])

        def _type_error_then_exception(
            _anchor: DialogueSegment,
            session: FileSession | None = None,
        ) -> list[str]:
            if session is not None:
                raise TypeError("kw not supported")
            raise RuntimeError("fallback failed")

        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            _type_error_then_exception,
        )
        resolved_double_fallback = harness._resolve_control_mismatch_group_source_lines(
            session,
            segment,
        )
        self.assertEqual(resolved_double_fallback, ["JP source"])

    def test_resolve_translation_lines_fallback_paths(self) -> None:
        harness = _Harness()
        session = FileSession(path=Path("Map001.json"), data={}, bundles=[], segments=[])
        anchor = _segment("Map001.json:L0:0", "JP", "TL")
        follow = _segment("Map001.json:I:1", "", r"TL \!", translation_only=True)
        group_segments = [anchor, follow]

        def _type_error_resolver(_segment: DialogueSegment) -> list[str]:
            return [r"TL \!"]

        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            _type_error_resolver,
        )
        resolved_via_type_error = harness._resolve_control_mismatch_group_translation_lines(
            session,
            anchor,
            group_segments,
        )
        self.assertEqual(resolved_via_type_error, [r"TL \!"])

        def _error_resolver(_segment: DialogueSegment, session: FileSession | None = None) -> list[str]:
            _ = session
            raise RuntimeError("broken")

        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            _error_resolver,
        )
        resolved_via_exception = harness._resolve_control_mismatch_group_translation_lines(
            session,
            anchor,
            group_segments,
        )
        self.assertEqual(resolved_via_exception, ["TL", r"TL \!"])

        def _type_error_then_exception(
            _segment: DialogueSegment,
            session: FileSession | None = None,
        ) -> list[str]:
            if session is not None:
                raise TypeError("kw not supported")
            raise RuntimeError("fallback failed")

        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            _type_error_then_exception,
        )
        resolved_double_fallback = harness._resolve_control_mismatch_group_translation_lines(
            session,
            anchor,
            group_segments,
        )
        self.assertEqual(resolved_double_fallback, ["TL", r"TL \!"])

    def test_group_entry_text_without_followups_returns_base(self) -> None:
        harness = _Harness()
        anchor = _segment("Map001.json:L0:0", "JP", "TL")
        session = FileSession(path=Path("Map001.json"), data={}, bundles=[], segments=[anchor])
        entry_text = harness._control_mismatch_group_entry_text(
            session,
            anchor,
            1,
            [anchor],
        )
        self.assertEqual(entry_text, "Block 1")

    def test_add_result_noop_when_results_list_missing(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_results_list = None
        harness._add_audit_control_mismatch_result(
            path=Path("Map001.json"),
            uid="Map001.json:L0:0",
            entry_text="Block 1",
            source_text=r"JP \!",
            tl_text=r"TL \.",
            missing_in_tl=Counter([r"\!"]),
            extra_in_tl=Counter([r"\."]),
            source_token_count=1,
            tl_token_count=1,
        )
        self.assertFalse(hasattr(harness, "last_jump"))

    def test_refresh_panel_returns_when_required_widgets_missing(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_results_list = None
        harness.audit_control_mismatch_status_label = None
        harness.audit_control_mismatch_goto_btn = None
        harness._refresh_audit_control_mismatch_panel()

    def test_worker_ignored_resolver_and_only_translated_filter_paths(self) -> None:
        harness = _Harness()
        mismatch_segment = _segment("Map001.json:L0:0", r"JP \!", r"TL \.")
        empty_translation_segment = _segment("Map001.json:L0:1", r"JP \!", "")
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[mismatch_segment, empty_translation_segment],
        )

        def _type_error_then_exception(
            _segment: DialogueSegment,
            session: FileSession | None = None,
            translator_mode: bool = True,
        ) -> bool:
            _ = translator_mode
            if session is not None:
                raise TypeError("kw not supported")
            raise RuntimeError("fallback failed")

        setattr(harness, "_segment_control_mismatch_ignored", _type_error_then_exception)
        payload_with_type_error = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )
        self.assertEqual(payload_with_type_error["scanned_blocks"], 1)
        self.assertEqual(len(payload_with_type_error["records"]), 1)

        def _always_raise(
            _segment: DialogueSegment,
            session: FileSession | None = None,
            translator_mode: bool = True,
        ) -> bool:
            _ = (session, translator_mode)
            raise RuntimeError("broken")

        setattr(harness, "_segment_control_mismatch_ignored", _always_raise)
        payload_with_exception = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )
        self.assertEqual(payload_with_exception["scanned_blocks"], 1)

        delattr(harness, "_segment_control_mismatch_ignored")
        payload_empty_tl_skipped = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), FileSession(
                path=Path("Map001.json"),
                data={},
                bundles=[],
                segments=[empty_translation_segment],
            ))],
            only_translated=True,
        )
        self.assertEqual(payload_empty_tl_skipped["scanned_blocks"], 0)

    def test_queue_worker_dedup_and_idle_start_paths(self) -> None:
        harness = _Harness()
        harness.audit_control_worker_running_request = {"generation": 1, "only_translated": True}
        harness.audit_control_worker_pending_request = None
        harness.audit_control_worker_future = object()
        harness.start_next_calls = 0
        harness._start_next_audit_control_worker = lambda: setattr(
            harness,
            "start_next_calls",
            harness.start_next_calls + 1,
        )
        request = {"generation": 1, "only_translated": True, "path_sessions": []}
        harness._queue_audit_control_worker(request)
        self.assertIsNone(harness.audit_control_worker_pending_request)
        self.assertEqual(harness.start_next_calls, 0)

        harness.audit_control_worker_running_request = None
        harness.audit_control_worker_future = None
        harness._queue_audit_control_worker(request)
        self.assertEqual(harness.audit_control_worker_pending_request, request)
        self.assertEqual(harness.start_next_calls, 1)

    def test_start_next_worker_returns_when_no_pending_request(self) -> None:
        harness = _Harness()
        harness.audit_control_worker_pending_request = None
        harness._start_next_audit_control_worker()

    def test_poll_worker_pending_and_not_done_paths(self) -> None:
        harness = _Harness()
        harness.audit_control_worker_future = None
        harness.audit_control_worker_pending_request = {"generation": 1, "only_translated": True}
        harness.poll_start_next_calls = 0
        harness._start_next_audit_control_worker = lambda: setattr(
            harness,
            "poll_start_next_calls",
            harness.poll_start_next_calls + 1,
        )
        harness._poll_audit_control_worker()
        self.assertEqual(harness.poll_start_next_calls, 1)

        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(done=False)
        harness.audit_control_worker_pending_request = None
        harness.audit_control_worker_timer = _TimerStub()
        harness._poll_audit_control_worker()
        self.assertEqual(harness.audit_control_worker_timer.started, [18])

    def test_poll_worker_exception_and_pending_result_paths(self) -> None:
        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(done=True, error=RuntimeError("boom"))
        harness.audit_control_worker_running_request = {"generation": 1, "only_translated": True}
        harness.audit_control_worker_pending_request = {"generation": 2, "only_translated": True}
        harness.poll_start_next_calls = 0
        harness._start_next_audit_control_worker = lambda: setattr(
            harness,
            "poll_start_next_calls",
            harness.poll_start_next_calls + 1,
        )
        harness._poll_audit_control_worker()
        self.assertEqual(harness.poll_start_next_calls, 1)

        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(
            done=True,
            result_payload={"scanned_blocks": 0, "records": []},
        )
        harness.audit_control_worker_running_request = {"generation": 1, "only_translated": True}
        harness.audit_control_worker_pending_request = {"generation": 2, "only_translated": True}
        harness.poll_start_next_calls = 0
        harness._start_next_audit_control_worker = lambda: setattr(
            harness,
            "poll_start_next_calls",
            harness.poll_start_next_calls + 1,
        )
        harness._poll_audit_control_worker()
        self.assertEqual(harness.poll_start_next_calls, 1)

    def test_poll_worker_result_guard_paths(self) -> None:
        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(
            done=True,
            result_payload={"scanned_blocks": 0, "records": []},
        )
        harness.audit_control_worker_running_request = "not-a-dict"
        harness.audit_control_worker_pending_request = None
        harness._poll_audit_control_worker()

        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(
            done=True,
            result_payload={"scanned_blocks": 0, "records": []},
        )
        harness.audit_control_worker_running_request = {"generation": 1, "only_translated": True}
        harness.audit_control_worker_pending_request = None
        harness.audit_control_mismatch_results_list = None
        harness.audit_control_mismatch_status_label = _StatusLabelStub()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness._poll_audit_control_worker()

        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(
            done=True,
            result_payload={"scanned_blocks": 0, "records": []},
        )
        harness.audit_control_worker_running_request = {"generation": 0, "only_translated": True}
        harness.audit_control_worker_pending_request = None
        harness.audit_cache_generation = 1
        harness.audit_control_mismatch_results_list = _ResultsListStub()
        harness.audit_control_mismatch_status_label = _StatusLabelStub()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness._poll_audit_control_worker()

        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(
            done=True,
            result_payload={"scanned_blocks": 0, "records": []},
        )
        harness.audit_control_worker_running_request = {"generation": 1, "only_translated": True}
        harness.audit_control_worker_pending_request = None
        harness.audit_cache_generation = 1
        harness.audit_control_mismatch_results_list = _ResultsListStub()
        harness.audit_control_mismatch_status_label = _StatusLabelStub()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness.audit_control_mismatch_only_translated_check = _CheckStub(False)
        harness._poll_audit_control_worker()

    def test_poll_worker_sets_no_mismatch_status(self) -> None:
        harness = _Harness()
        harness.audit_control_worker_future = _FutureStub(
            done=True,
            result_payload={"scanned_blocks": 1, "records": []},
        )
        harness.audit_control_worker_running_request = {"generation": 2, "only_translated": True}
        harness.audit_control_worker_pending_request = None
        harness.audit_cache_generation = 2
        harness.audit_control_mismatch_results_list = _ResultsListStub()
        harness.audit_control_mismatch_status_label = _StatusLabelStub()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness.audit_control_mismatch_only_translated_check = _CheckStub(True)
        harness.audit_control_mismatch_cache_key = None
        harness.audit_control_mismatch_cache_records = []
        harness.audit_control_mismatch_cache_scanned_blocks = 0
        harness.audit_control_mismatch_displayed_key = None
        harness.audit_control_mismatch_display_complete = False
        harness._poll_audit_control_worker()

        self.assertIn("No control mismatches found across 1 scanned block", harness.audit_control_mismatch_status_label.text)
        self.assertEqual(harness.audit_control_mismatch_displayed_key, (2, True))
        self.assertTrue(harness.audit_control_mismatch_display_complete)

    def test_render_batch_guard_paths(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_results_list = None
        harness.audit_control_mismatch_status_label = _StatusLabelStub()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness._render_next_audit_control_mismatch_batch()
        self.assertEqual(harness.stop_render_calls, 1)

        harness = _Harness()
        harness.audit_control_mismatch_results_list = _ResultsListStub()
        harness.audit_control_mismatch_status_label = _StatusLabelStub()
        harness.audit_control_mismatch_goto_btn = _ButtonStub()
        harness.audit_control_mismatch_render_records = []
        harness._render_next_audit_control_mismatch_batch()
        self.assertEqual(harness.stop_render_calls, 1)

    def test_go_to_selected_control_mismatch_guard_paths(self) -> None:
        harness = _Harness()
        harness.audit_control_mismatch_results_list = None
        harness._go_to_selected_audit_control_mismatch()
        self.assertFalse(hasattr(harness, "last_jump"))

        harness.audit_control_mismatch_results_list = _ResultsListStub(current_item=None)
        harness._go_to_selected_audit_control_mismatch()
        self.assertFalse(hasattr(harness, "last_jump"))

        harness.audit_control_mismatch_results_list = _ResultsListStub(
            current_item=_ItemStub(payload="bad")
        )
        harness._go_to_selected_audit_control_mismatch()
        self.assertFalse(hasattr(harness, "last_jump"))

        harness.audit_control_mismatch_results_list = _ResultsListStub(
            current_item=_ItemStub(payload={"uid": "Map001.json:L0:0"})
        )
        harness._go_to_selected_audit_control_mismatch()
        self.assertFalse(hasattr(harness, "last_jump"))

        harness.audit_control_mismatch_results_list = _ResultsListStub(
            current_item=_ItemStub(payload={"path": "Map001.json"})
        )
        harness._go_to_selected_audit_control_mismatch()
        self.assertFalse(hasattr(harness, "last_jump"))

    def test_translation_only_followup_is_unified_with_source_block(self) -> None:
        harness = _Harness()
        source = _segment("Map001.json:L0:0", r"JP \!", "TL first part")
        followup = _segment(
            "Map001.json:I:1",
            "",
            r"TL second part \!",
            translation_only=True,
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[source, followup],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(payload["records"], [])

    def test_unified_followup_still_reports_real_mismatch_once(self) -> None:
        harness = _Harness()
        source = _segment("Map001.json:L0:0", r"JP \!", "TL first part")
        followup = _segment(
            "Map001.json:I:1",
            "",
            r"TL second part \.",
            translation_only=True,
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[source, followup],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        records = payload["records"]
        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["uid"], "Map001.json:L0:0")
        self.assertIn("TL split", records[0]["entry_text"])

    def test_worker_prefers_problem_check_translation_resolver_for_split_followups(self) -> None:
        harness = _Harness()
        anchor = _segment("Map001.json:L0:0", r"\C[2]JP\C[0]", r"\C[2]TL\C[0]")
        followup = _segment(
            "Map001.json:I:1",
            "",
            r"\C[2]TL\C[0]",
            translation_only=True,
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor, followup],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            lambda _segment, session=None: [r"\C[2]TL\C[0]"],
        )
        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            lambda _segment, session=None: [r"\C[2]JP\C[0]"],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(payload["records"], [])

    def test_worker_prefers_logical_source_resolver(self) -> None:
        harness = _Harness()
        anchor = _segment("Map001.json:L0:0", r"\C[2]JP\C[0]", "TL")
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor],
        )
        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            lambda _segment, session=None: ["JP"],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            lambda _segment, session=None: ["TL"],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(payload["records"], [])

    def test_worker_skips_groups_marked_control_mismatch_ignored(self) -> None:
        harness = _Harness()
        anchor = _segment("Map001.json:L0:0", r"\C[2]JP\C[0]", r"\C[2]TL")
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor],
        )
        setattr(
            harness,
            "_segment_control_mismatch_ignored",
            lambda _segment, session=None, translator_mode=True: True,
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        self.assertEqual(payload["scanned_blocks"], 0)
        self.assertEqual(payload["records"], [])


if __name__ == "__main__":
    unittest.main()
