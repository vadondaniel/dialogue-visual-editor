from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import html
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem

from .audit_constants import COLOR_CODE_TOKEN_RE
from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import CONTROL_TOKEN_RE


class _AuditControlHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditControlMismatchMixin(_AuditControlHostTypingFallback):
    def _extract_control_token_matches(self, text: str) -> list[tuple[str, int, int]]:
        if not text:
            return []
        return [(match.group(0), match.start(), match.end()) for match in CONTROL_TOKEN_RE.finditer(text)]

    def _extract_control_tokens(self, text: str) -> list[str]:
        return [token for token, _start, _end in self._extract_control_token_matches(text)]

    def _control_mismatch_highlight_indices(
        self,
        source_tokens: list[str],
        tl_tokens: list[str],
    ) -> tuple[set[int], set[int]]:
        source_indices: set[int] = set()
        tl_indices: set[int] = set()
        matcher = SequenceMatcher(a=source_tokens, b=tl_tokens, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            source_indices.update(range(i1, i2))
            tl_indices.update(range(j1, j2))
        return source_indices, tl_indices

    def _counter_summary_text(self, counts: Counter[str], limit: int = 10) -> str:
        if not counts:
            return "(none)"
        parts: list[str] = []
        sorted_items = sorted(counts.items(), key=lambda item: item[0])
        for idx, (token, count) in enumerate(sorted_items):
            if idx >= limit:
                break
            if count == 1:
                parts.append(token)
            else:
                parts.append(f"{token} x{count}")
        if len(sorted_items) > limit:
            parts.append("...")
        return ", ".join(parts)

    def _render_control_mismatch_side_html(
        self,
        text: str,
        highlight_token_indices: set[int],
    ) -> str:
        source_text = text or ""
        if not source_text:
            return "<i>(empty)</i>"

        token_matches = self._extract_control_token_matches(source_text)
        if not token_matches:
            return html.escape(source_text).replace("\n", "<br/>")

        parts: list[str] = []
        cursor = 0
        active_color = ""
        highlight_style = self._audit_highlight_style()

        def append_plain_chunk(chunk: str) -> None:
            if not chunk:
                return
            escaped = html.escape(chunk).replace("\n", "<br/>")
            if active_color:
                parts.append(
                    f"<span style=\"color: {active_color};\">{escaped}</span>")
            else:
                parts.append(escaped)

        for token_index, (token, start, end) in enumerate(token_matches):
            append_plain_chunk(source_text[cursor:start])
            should_highlight = token_index in highlight_token_indices

            token_style_parts: list[str] = ["opacity: 0.92;"]
            if active_color:
                token_style_parts.append(f"color: {active_color};")
            if should_highlight:
                token_style_parts.append(highlight_style)
            else:
                token_style_parts.append("font-weight: 500;")
            token_style = " ".join(token_style_parts)
            parts.append(
                "<span style=\""
                + token_style
                + "\">"
                + html.escape(token)
                + "</span>"
            )

            color_match = COLOR_CODE_TOKEN_RE.fullmatch(token)
            if color_match is not None:
                try:
                    color_code = int(color_match.group(1))
                except Exception:
                    color_code = 0
                active_color = self._color_for_rpgm_code(color_code)

            cursor = end

        append_plain_chunk(source_text[cursor:])
        if parts:
            return "".join(parts)
        return html.escape(source_text).replace("\n", "<br/>")

    def _build_control_mismatch_tooltip_html(
        self,
        source_text: str,
        tl_text: str,
        missing_in_tl: Counter[str],
        extra_in_tl: Counter[str],
    ) -> str:
        source_tokens = self._extract_control_tokens(source_text)
        tl_tokens = self._extract_control_tokens(tl_text)
        source_highlight_indices, tl_highlight_indices = self._control_mismatch_highlight_indices(
            source_tokens,
            tl_tokens,
        )
        missing_text = html.escape(
            self._counter_summary_text(missing_in_tl, limit=14))
        extra_text = html.escape(
            self._counter_summary_text(extra_in_tl, limit=14))
        source_html = self._render_control_mismatch_side_html(
            source_text, source_highlight_indices)
        tl_html = self._render_control_mismatch_side_html(
            tl_text, tl_highlight_indices)
        return (
            "<div style=\"max-width: 980px;\">"
            "<b>Control Mismatch Preview</b><br/>"
            "<span><b>Missing:</b> "
            + missing_text
            + "</span><br/>"
            "<span><b>Extra:</b> "
            + extra_text
            + "</span><br/><br/>"
            "<b>Original</b><br/>"
            + source_html
            + "<br/><br/>"
            "<b>Translation</b><br/>"
            + tl_html
            + "</div>"
        )

    def _control_mismatch_scan_groups(
        self,
        session: FileSession,
    ) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        leading_translation_only: list[DialogueSegment] = []
        for idx, segment in enumerate(list(session.segments), start=1):
            if segment.translation_only:
                if groups:
                    cast(list[DialogueSegment], groups[-1]["segments"]).append(segment)
                else:
                    leading_translation_only.append(segment)
                continue

            group_segments: list[DialogueSegment] = [segment]
            if leading_translation_only:
                group_segments.extend(leading_translation_only)
                leading_translation_only = []
            groups.append(
                {
                    "anchor_segment": segment,
                    "anchor_index": idx,
                    "segments": group_segments,
                }
            )

        if leading_translation_only:
            if groups:
                cast(list[DialogueSegment], groups[0]["segments"]).extend(
                    leading_translation_only
                )
            else:
                anchor_segment = leading_translation_only[0]
                groups.append(
                    {
                        "anchor_segment": anchor_segment,
                        "anchor_index": 1,
                        "segments": list(leading_translation_only),
                    }
                )
        return groups

    def _control_mismatch_group_translation_lines(
        self,
        segments: list[DialogueSegment],
    ) -> list[str]:
        lines: list[str] = []
        normalize_for_segment = getattr(
            self, "_normalize_audit_translation_lines_for_segment", None
        )
        for segment in segments:
            if callable(normalize_for_segment):
                try:
                    tl_lines_raw = normalize_for_segment(
                        segment, segment.translation_lines
                    )
                    lines.extend(self._normalize_translation_lines(tl_lines_raw))
                    continue
                except Exception:
                    pass
            lines.extend(self._normalize_translation_lines(segment.translation_lines))
        return lines if lines else [""]

    def _resolve_control_mismatch_group_source_lines(
        self,
        session: FileSession,
        anchor_segment: DialogueSegment,
    ) -> list[str]:
        logical_source_resolver = getattr(
            self,
            "_logical_translation_source_lines_for_segment",
            None,
        )
        if callable(logical_source_resolver):
            resolved_source: Any = None
            try:
                resolved_source = logical_source_resolver(
                    anchor_segment,
                    session=session,
                )
            except TypeError:
                try:
                    resolved_source = logical_source_resolver(anchor_segment)
                except Exception:
                    resolved_source = None
            except Exception:
                resolved_source = None
            if isinstance(resolved_source, list):
                return self._normalize_translation_lines(resolved_source) or [""]
        return self._segment_source_lines_for_display(anchor_segment)

    def _resolve_control_mismatch_group_translation_lines(
        self,
        session: FileSession,
        anchor_segment: DialogueSegment,
        group_segments: list[DialogueSegment],
    ) -> list[str]:
        logical_problem_translation_resolver = getattr(
            self,
            "_logical_translation_lines_for_problem_checks",
            None,
        )
        if callable(logical_problem_translation_resolver):
            resolved_problem_lines: Any = None
            try:
                resolved_problem_lines = logical_problem_translation_resolver(
                    anchor_segment,
                    session=session,
                )
            except TypeError:
                try:
                    resolved_problem_lines = logical_problem_translation_resolver(
                        anchor_segment
                    )
                except Exception:
                    resolved_problem_lines = None
            except Exception:
                resolved_problem_lines = None
            if isinstance(resolved_problem_lines, list):
                return self._normalize_translation_lines(resolved_problem_lines) or [""]
        return self._control_mismatch_group_translation_lines(group_segments)

    def _control_mismatch_group_entry_text(
        self,
        session: FileSession,
        anchor_segment: DialogueSegment,
        anchor_index: int,
        group_segments: list[DialogueSegment],
    ) -> str:
        base = self._audit_entry_text_for_segment(
            session, anchor_segment, anchor_index
        )
        followup_count = sum(
            1
            for segment in group_segments
            if segment.translation_only and segment.uid != anchor_segment.uid
        )
        if followup_count <= 0:
            return base
        split_label = "split" if followup_count == 1 else "splits"
        return f"{base} (+{followup_count} TL {split_label})"

    def _add_audit_control_mismatch_result(
        self,
        path: Path,
        uid: str,
        entry_text: str,
        source_text: str,
        tl_text: str,
        missing_in_tl: Counter[str],
        extra_in_tl: Counter[str],
        source_token_count: int,
        tl_token_count: int,
    ) -> None:
        if self.audit_control_mismatch_results_list is None:
            return
        relative_path = self._relative_path(path)
        issue_count = sum(missing_in_tl.values()) + sum(extra_in_tl.values())
        header_text = (
            f"{relative_path} | {entry_text} | mismatch ({issue_count}) | "
            f"OG tokens: {source_token_count}, TL tokens: {tl_token_count}"
        )

        item = QListWidgetItem()
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        item.setData(
            Qt.ItemDataRole.UserRole,
            {"path": str(path), "uid": uid},
        )
        tooltip_html = self._build_control_mismatch_tooltip_html(
            source_text=source_text,
            tl_text=tl_text,
            missing_in_tl=missing_in_tl,
            extra_in_tl=extra_in_tl,
        )
        item.setToolTip(tooltip_html)
        self.audit_control_mismatch_results_list.addItem(item)

        body = QLabel()
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        body.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.setToolTip(tooltip_html)
        missing_text = self._counter_summary_text(missing_in_tl)
        extra_text = self._counter_summary_text(extra_in_tl)
        body.setText(
            "<div style=\"padding: 4px 0;\">"
            f"<b>{html.escape(header_text)}</b><br>"
            f"Missing: {html.escape(missing_text)}<br>"
            f"Extra: {html.escape(extra_text)}"
            "</div>"
        )
        item.setSizeHint(body.sizeHint())
        self.audit_control_mismatch_results_list.setItemWidget(item, body)

    def _refresh_audit_control_mismatch_panel(self) -> None:
        if (
            self.audit_control_mismatch_results_list is None
            or self.audit_control_mismatch_status_label is None
            or self.audit_control_mismatch_goto_btn is None
        ):
            return

        only_translated = bool(
            self.audit_control_mismatch_only_translated_check is not None
            and self.audit_control_mismatch_only_translated_check.isChecked()
        )
        requested_key = (self.audit_cache_generation, only_translated)
        if (
            self.audit_control_mismatch_display_complete
            and self.audit_control_mismatch_displayed_key == requested_key
        ):
            shown = self.audit_control_mismatch_results_list.count()
            scanned = self.audit_control_mismatch_cache_scanned_blocks
            if shown > 0:
                shown_label = "block" if shown == 1 else "blocks"
                self.audit_control_mismatch_status_label.setText(
                    f"Found {shown} mismatched {shown_label} out of {scanned} scanned."
                )
                self.audit_control_mismatch_goto_btn.setEnabled(
                    self.audit_control_mismatch_results_list.currentItem() is not None
                )
            else:
                suffix = " (translated only)." if only_translated else "."
                scanned_label = "block" if scanned == 1 else "blocks"
                self.audit_control_mismatch_status_label.setText(
                    f"No control mismatches found across {scanned} scanned {scanned_label}{suffix}"
                )
                self.audit_control_mismatch_goto_btn.setEnabled(False)
            return

        self._stop_audit_control_mismatch_render()
        self.audit_control_mismatch_results_list.clear()
        self.audit_control_mismatch_goto_btn.setEnabled(False)
        self.audit_control_mismatch_display_complete = False
        self.audit_control_mismatch_displayed_key = None

        if not self.sessions:
            self.audit_control_mismatch_status_label.setText("No data loaded.")
            return

        cache_key = (self.audit_cache_generation, only_translated)
        if self.audit_control_mismatch_cache_key == cache_key:
            records = list(self.audit_control_mismatch_cache_records)
            scanned_blocks = self.audit_control_mismatch_cache_scanned_blocks
            mismatched_blocks = len(records)
            if mismatched_blocks <= 0:
                suffix = " (translated only)." if only_translated else "."
                scanned_label = "block" if scanned_blocks == 1 else "blocks"
                self.audit_control_mismatch_status_label.setText(
                    f"No control mismatches found across {scanned_blocks} scanned {scanned_label}{suffix}"
                )
                self.audit_control_mismatch_displayed_key = cache_key
                self.audit_control_mismatch_display_complete = True
                return
            mismatched_label = "block" if mismatched_blocks == 1 else "blocks"
            self.audit_control_mismatch_status_label.setText(
                f"Found {mismatched_blocks} mismatched {mismatched_label} out of {scanned_blocks} scanned."
            )
            self._set_audit_progress_overlay(
                self.audit_control_mismatch_results_list,
                self.audit_control_mismatch_progress_overlay,
                f"Rendering 0/{mismatched_blocks}",
            )
            self.audit_control_mismatch_render_records = records
            self.audit_control_mismatch_render_index = 0
            self.audit_control_mismatch_render_scanned_blocks = scanned_blocks
            self.audit_control_mismatch_render_only_translated = only_translated
            self.audit_control_mismatch_render_generation = self.audit_cache_generation
            self.audit_control_mismatch_render_timer.start(
                self.audit_render_batch_interval_ms)
            return

        request = {
            "generation": self.audit_cache_generation,
            "only_translated": only_translated,
            "path_sessions": self._audit_path_sessions_snapshot(),
        }
        self.audit_control_mismatch_status_label.setText(
            "Scanning control-code mismatches..."
        )
        self._queue_audit_control_worker(request)

    def _compute_audit_control_mismatch_worker(
        self,
        path_sessions: list[tuple[Path, FileSession]],
        only_translated: bool,
    ) -> dict[str, Any]:
        scanned_blocks = 0
        records: list[dict[str, Any]] = []
        for path, session in path_sessions:
            groups = self._control_mismatch_scan_groups(session)
            for group in groups:
                anchor_segment = cast(DialogueSegment, group["anchor_segment"])
                anchor_index = int(group["anchor_index"])
                group_segments = cast(list[DialogueSegment], group["segments"])
                source_lines = self._resolve_control_mismatch_group_source_lines(
                    session,
                    anchor_segment,
                )
                tl_lines = self._resolve_control_mismatch_group_translation_lines(
                    session,
                    anchor_segment,
                    group_segments,
                )
                if only_translated and not any(line.strip() for line in tl_lines):
                    continue
                scanned_blocks += 1

                source_tokens = self._extract_control_tokens(
                    "\n".join(source_lines))
                tl_tokens = self._extract_control_tokens("\n".join(tl_lines))
                source_counter = Counter(source_tokens)
                tl_counter = Counter(tl_tokens)
                if source_counter == tl_counter:
                    continue
                records.append(
                    {
                        "path": path,
                        "uid": anchor_segment.uid,
                        "entry_text": self._control_mismatch_group_entry_text(
                            session,
                            anchor_segment,
                            anchor_index,
                            group_segments,
                        ),
                        "source_text": "\n".join(source_lines),
                        "tl_text": "\n".join(tl_lines),
                        "missing_in_tl": source_counter - tl_counter,
                        "extra_in_tl": tl_counter - source_counter,
                        "source_token_count": sum(source_counter.values()),
                        "tl_token_count": sum(tl_counter.values()),
                    }
                )
        return {"scanned_blocks": scanned_blocks, "records": records}

    def _queue_audit_control_worker(self, request: dict[str, Any]) -> None:
        request_key = self._control_request_key(request)
        if request_key == self._control_request_key(self.audit_control_worker_running_request):
            return
        if request_key == self._control_request_key(self.audit_control_worker_pending_request):
            return
        self.audit_control_worker_pending_request = request
        if self.audit_control_worker_future is None:
            self._start_next_audit_control_worker()

    def _start_next_audit_control_worker(self) -> None:
        request = self.audit_control_worker_pending_request
        if request is None:
            return
        self.audit_control_worker_pending_request = None
        self.audit_control_worker_running_request = request
        try:
            self.audit_control_worker_future = self.audit_worker_executor.submit(
                self._compute_audit_control_mismatch_worker,
                cast(list[tuple[Path, FileSession]], request["path_sessions"]),
                bool(request["only_translated"]),
            )
        except Exception as exc:
            self.audit_control_worker_future = None
            self.audit_control_worker_running_request = None
            if self.audit_control_mismatch_status_label is not None:
                self.audit_control_mismatch_status_label.setText(
                    f"Control mismatch scan failed: {exc}"
                )
            return
        self.audit_control_worker_timer.start(18)

    def _poll_audit_control_worker(self) -> None:
        future = self.audit_control_worker_future
        if future is None:
            if self.audit_control_worker_pending_request is not None:
                self._start_next_audit_control_worker()
            return
        if not future.done():
            self.audit_control_worker_timer.start(18)
            return

        running_request = self.audit_control_worker_running_request
        self.audit_control_worker_future = None
        self.audit_control_worker_running_request = None
        try:
            payload = cast(dict[str, Any], future.result())
        except Exception as exc:
            if self.audit_control_worker_pending_request is not None:
                self._start_next_audit_control_worker()
                return
            if self.audit_control_mismatch_status_label is not None:
                self.audit_control_mismatch_status_label.setText(
                    f"Control mismatch scan failed: {exc}"
                )
            return

        if self.audit_control_worker_pending_request is not None:
            self._start_next_audit_control_worker()
            return
        if not isinstance(running_request, dict):
            return
        if (
            self.audit_control_mismatch_results_list is None
            or self.audit_control_mismatch_status_label is None
            or self.audit_control_mismatch_goto_btn is None
        ):
            return

        generation = int(running_request.get("generation", -1))
        only_translated = bool(running_request.get("only_translated", True))
        if generation != self.audit_cache_generation:
            return
        current_only_translated = bool(
            self.audit_control_mismatch_only_translated_check is not None
            and self.audit_control_mismatch_only_translated_check.isChecked()
        )
        if current_only_translated != only_translated:
            return

        scanned_blocks = int(payload.get("scanned_blocks", 0))
        records = list(cast(list[dict[str, Any]], payload.get("records", [])))
        cache_key = (generation, only_translated)
        self.audit_control_mismatch_cache_key = cache_key
        self.audit_control_mismatch_cache_records = list(records)
        self.audit_control_mismatch_cache_scanned_blocks = scanned_blocks
        mismatched_blocks = len(records)
        if mismatched_blocks <= 0:
            suffix = " (translated only)." if only_translated else "."
            scanned_label = "block" if scanned_blocks == 1 else "blocks"
            self.audit_control_mismatch_status_label.setText(
                f"No control mismatches found across {scanned_blocks} scanned {scanned_label}{suffix}"
            )
            self.audit_control_mismatch_displayed_key = cache_key
            self.audit_control_mismatch_display_complete = True
            return
        mismatched_label = "block" if mismatched_blocks == 1 else "blocks"
        self.audit_control_mismatch_status_label.setText(
            f"Found {mismatched_blocks} mismatched {mismatched_label} out of {scanned_blocks} scanned."
        )
        self._set_audit_progress_overlay(
            self.audit_control_mismatch_results_list,
            self.audit_control_mismatch_progress_overlay,
            f"Rendering 0/{mismatched_blocks}",
        )
        self.audit_control_mismatch_render_records = records
        self.audit_control_mismatch_render_index = 0
        self.audit_control_mismatch_render_scanned_blocks = scanned_blocks
        self.audit_control_mismatch_render_only_translated = only_translated
        self.audit_control_mismatch_render_generation = generation
        self.audit_control_mismatch_display_complete = False
        self.audit_control_mismatch_render_timer.start(
            self.audit_render_batch_interval_ms)

    def _render_next_audit_control_mismatch_batch(self) -> None:
        if (
            self.audit_control_mismatch_results_list is None
            or self.audit_control_mismatch_status_label is None
            or self.audit_control_mismatch_goto_btn is None
        ):
            self._stop_audit_control_mismatch_render()
            return
        records = self.audit_control_mismatch_render_records
        total = len(records)
        if total <= 0:
            self._stop_audit_control_mismatch_render()
            return
        start = self.audit_control_mismatch_render_index
        end = min(start + self.audit_result_batch_size, total)
        prev_updates = self.audit_control_mismatch_results_list.updatesEnabled()
        self.audit_control_mismatch_results_list.setUpdatesEnabled(False)
        try:
            for record in records[start:end]:
                self._add_audit_control_mismatch_result(
                    path=cast(Path, record["path"]),
                    uid=str(record["uid"]),
                    entry_text=str(record["entry_text"]),
                    source_text=str(record["source_text"]),
                    tl_text=str(record["tl_text"]),
                    missing_in_tl=cast(Counter[str], record["missing_in_tl"]),
                    extra_in_tl=cast(Counter[str], record["extra_in_tl"]),
                    source_token_count=int(record["source_token_count"]),
                    tl_token_count=int(record["tl_token_count"]),
                )
        finally:
            self.audit_control_mismatch_results_list.setUpdatesEnabled(
                prev_updates)
        self.audit_control_mismatch_render_index = end
        scanned_blocks = self.audit_control_mismatch_render_scanned_blocks
        if end < total:
            self._set_audit_progress_overlay(
                self.audit_control_mismatch_results_list,
                self.audit_control_mismatch_progress_overlay,
                f"Rendering {end}/{total}",
            )
            self.audit_control_mismatch_render_timer.start(
                self.audit_render_batch_interval_ms)
            return
        if self.audit_control_mismatch_results_list.count() > 0:
            self.audit_control_mismatch_results_list.setCurrentRow(0)
            self.audit_control_mismatch_goto_btn.setEnabled(True)
        self.audit_control_mismatch_displayed_key = (
            self.audit_control_mismatch_render_generation,
            bool(self.audit_control_mismatch_render_only_translated),
        )
        self.audit_control_mismatch_display_complete = True
        total_label = "block" if total == 1 else "blocks"
        self.audit_control_mismatch_status_label.setText(
            f"Found {total} mismatched {total_label} out of {scanned_blocks} scanned."
        )
        self._stop_audit_control_mismatch_render()

    def _go_to_selected_audit_control_mismatch(self) -> None:
        if self.audit_control_mismatch_results_list is None:
            return
        item = self.audit_control_mismatch_results_list.currentItem()
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        path_raw = payload.get("path")
        uid_raw = payload.get("uid")
        if not isinstance(path_raw, str) or not path_raw:
            return
        if not isinstance(uid_raw, str) or not uid_raw:
            return
        self._jump_to_audit_location(path_raw, uid_raw)
