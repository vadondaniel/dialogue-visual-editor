from __future__ import annotations

import html
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem, QMessageBox, QWidget

from ..core.models import FileSession
from ..core.text_utils import strip_control_tokens


class _AuditSearchHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditSearchMixin(_AuditSearchHostTypingFallback):
    _CONTROL_QUERY_RE = re.compile(
        r"""
        \\[A-Za-z]+\d*<[^>]*>        |
        \\[A-Za-z]+\d*\[[^\]]*\]     |
        \\[\.\!\|\{\}\^]             |
        \\[ntr]
        """,
        re.VERBOSE,
    )

    def _is_control_code_search_query(self, query: str) -> bool:
        return bool(self._CONTROL_QUERY_RE.search(query or ""))

    def _normalize_text_for_natural_search(self, text: str, case_sensitive: bool = False) -> str:
        without_codes = strip_control_tokens(text or "")
        normalized = "".join(without_codes.split())
        return normalized if case_sensitive else normalized.casefold()

    def _natural_match_spans(
        self,
        source_text: str,
        needle: str,
        case_sensitive: bool,
    ) -> list[tuple[int, int]]:
        if not source_text or not needle:
            return []

        compact_chars: list[str] = []
        compact_source_positions: list[int] = []
        next_visible_start = 0
        for match in self._CONTROL_QUERY_RE.finditer(source_text):
            segment = source_text[next_visible_start:match.start()]
            for idx, char in enumerate(segment):
                if char.isspace():
                    continue
                compact_chars.append(char if case_sensitive else char.casefold())
                compact_source_positions.append(next_visible_start + idx)
            next_visible_start = match.end()
        tail = source_text[next_visible_start:]
        for idx, char in enumerate(tail):
            if char.isspace():
                continue
            compact_chars.append(char if case_sensitive else char.casefold())
            compact_source_positions.append(next_visible_start + idx)

        compact_text = "".join(compact_chars)
        if not compact_text:
            return []

        spans: list[tuple[int, int]] = []
        search_from = 0
        while search_from <= len(compact_text):
            found_at = compact_text.find(needle, search_from)
            if found_at < 0:
                break
            end_at = found_at + len(needle) - 1
            if end_at >= len(compact_source_positions):
                break
            start_src = compact_source_positions[found_at]
            end_src = compact_source_positions[end_at] + 1
            spans.append((start_src, end_src))
            search_from = found_at + 1
        return spans

    def _schedule_audit_search(self) -> None:
        if self.audit_search_timer is None:
            return
        self.audit_search_timer.start()

    def _audit_search_case_sensitive_enabled(self) -> bool:
        action = getattr(self, "audit_search_case_sensitive_check", None)
        if action is None:
            return False
        checker = getattr(action, "isChecked", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return False

    def _highlight_audit_match_html(
        self,
        text: str,
        query: str,
        needle: str,
        natural_mode: bool,
        case_sensitive: bool,
    ) -> str:
        source_text = text or ""
        if not query:
            return html.escape(source_text).replace("\n", "<br>")
        highlight_style = self._audit_highlight_style()
        spans: list[tuple[int, int]] = []
        if natural_mode:
            spans = self._natural_match_spans(source_text, needle, case_sensitive)
        else:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(re.escape(query), flags)
            spans = [match.span() for match in pattern.finditer(source_text)]
        if not spans:
            return html.escape(source_text).replace("\n", "<br>")
        parts: list[str] = []
        last_idx = 0
        for start, end in spans:
            if start > last_idx:
                parts.append(html.escape(source_text[last_idx:start]))
            parts.append(
                "<span style=\""
                + highlight_style
                + "\">"
                + html.escape(source_text[start:end])
                + "</span>"
            )
            last_idx = end
        if last_idx < len(source_text):
            parts.append(html.escape(source_text[last_idx:]))
        highlighted = "".join(parts)
        return highlighted.replace("\n", "<br>")

    def _add_audit_search_result(
        self,
        path: Path,
        uid: str,
        entry_text: str,
        matched_field: str,
        matched_text: str,
        query: str,
        needle: str,
        natural_mode: bool,
        case_sensitive: bool,
    ) -> None:
        if self.audit_search_results_list is None:
            return
        relative_path = self._relative_path(path)
        header_text = f"{relative_path} | {entry_text} | {matched_field}"

        item = QListWidgetItem()
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "path": str(path),
                "uid": uid,
                "matched_scope": matched_field.casefold(),
                "entry_text": entry_text,
                "matched_field": matched_field,
                "matched_text": matched_text,
            },
        )
        self.audit_search_results_list.addItem(item)

        body = QLabel()
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        body.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.setText(
            "<div style=\"padding: 4px 0;\">"
            f"<b>{html.escape(header_text)}</b><br>"
            f"{self._highlight_audit_match_html(matched_text, query, needle, natural_mode, case_sensitive)}"
            "</div>"
        )

        item.setSizeHint(body.sizeHint())
        self.audit_search_results_list.setItemWidget(item, body)

    def _compute_audit_search_records_worker(
        self,
        path_sessions: list[tuple[Path, FileSession]],
        scope: str,
        needle: str,
        natural_mode: bool,
        case_sensitive: bool,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path, session in path_sessions:
            is_name_index = self._is_name_index_session(session)
            name_index_label = self._name_index_label(session)
            for idx, segment in enumerate(list(session.segments), start=1):
                original_text = "\n".join(
                    self._segment_source_lines_for_display(segment))
                translation_text = "\n".join(
                    self._normalize_translation_lines(
                        segment.translation_lines)
                )
                entry_text = f"{name_index_label} {idx}" if is_name_index else f"Block {idx}"
                if is_name_index:
                    actor_id = self._actor_id_from_uid(segment.uid)
                    if actor_id is not None:
                        entry_text = f"{name_index_label} ID {actor_id}"
                original_match_text = (
                    self._normalize_text_for_natural_search(
                        original_text,
                        case_sensitive,
                    ) if natural_mode else (
                        original_text if case_sensitive else original_text.casefold()
                    )
                )
                translation_match_text = (
                    self._normalize_text_for_natural_search(
                        translation_text,
                        case_sensitive,
                    ) if natural_mode else (
                        translation_text if case_sensitive else translation_text.casefold()
                    )
                )
                if scope in ("original", "both") and needle in original_match_text:
                    records.append(
                        {
                            "path": path,
                            "uid": segment.uid,
                            "entry_text": entry_text,
                            "matched_field": "Original",
                            "matched_text": original_text,
                        }
                    )
                if scope in ("translation", "both") and needle in translation_match_text:
                    records.append(
                        {
                            "path": path,
                            "uid": segment.uid,
                            "entry_text": entry_text,
                            "matched_field": "Translation",
                            "matched_text": translation_text,
                        }
                    )
        return records

    def _queue_audit_search_worker(self, request: dict[str, Any]) -> None:
        request_key = self._search_request_key(request)
        if request_key == self._search_request_key(self.audit_search_worker_running_request):
            return
        if request_key == self._search_request_key(self.audit_search_worker_pending_request):
            return
        self.audit_search_worker_pending_request = request
        if self.audit_search_worker_future is None:
            self._start_next_audit_search_worker()

    def _start_next_audit_search_worker(self) -> None:
        request = self.audit_search_worker_pending_request
        if request is None:
            return
        self.audit_search_worker_pending_request = None
        self.audit_search_worker_running_request = request
        try:
            self.audit_search_worker_future = self.audit_worker_executor.submit(
                self._compute_audit_search_records_worker,
                cast(list[tuple[Path, FileSession]], request["path_sessions"]),
                str(request["scope"]),
                str(request["needle"]),
                bool(request.get("natural_mode", False)),
                bool(request.get("case_sensitive", True)),
            )
        except Exception as exc:
            self.audit_search_worker_future = None
            self.audit_search_worker_running_request = None
            if self.audit_search_status_label is not None:
                self.audit_search_status_label.setText(
                    f"Search scan failed: {exc}")
            return
        self.audit_search_worker_timer.start(18)

    def _poll_audit_search_worker(self) -> None:
        future = self.audit_search_worker_future
        if future is None:
            if self.audit_search_worker_pending_request is not None:
                self._start_next_audit_search_worker()
            return
        if not future.done():
            self.audit_search_worker_timer.start(18)
            return

        running_request = self.audit_search_worker_running_request
        self.audit_search_worker_future = None
        self.audit_search_worker_running_request = None
        try:
            records = cast(list[dict[str, Any]], future.result())
        except Exception as exc:
            if self.audit_search_worker_pending_request is not None:
                self._start_next_audit_search_worker()
                return
            if self.audit_search_status_label is not None:
                self.audit_search_status_label.setText(
                    f"Search scan failed: {exc}")
            return

        if self.audit_search_worker_pending_request is not None:
            self._start_next_audit_search_worker()
            return
        if not isinstance(running_request, dict):
            return
        generation = int(running_request.get("generation", -1))
        query = str(running_request.get("query", ""))
        scope = str(running_request.get("scope", "original"))
        needle = str(running_request.get("needle", ""))
        case_sensitive = bool(running_request.get("case_sensitive", True))
        if generation != self.audit_cache_generation:
            return
        if (
            self.audit_search_query_edit is None
            or self.audit_search_scope_combo is None
            or self.audit_search_results_list is None
            or self.audit_search_status_label is None
            or self.audit_search_goto_btn is None
            or self.audit_search_replace_selected_btn is None
            or self.audit_search_replace_all_btn is None
        ):
            return
        current_query = self.audit_search_query_edit.text().strip()
        current_scope = str(
            self.audit_search_scope_combo.currentData() or "original")
        current_case_sensitive = self._audit_search_case_sensitive_enabled()
        if (
            current_query != query
            or current_scope != scope
            or current_case_sensitive != case_sensitive
        ):
            return
        cache_key = (generation, scope, needle, case_sensitive)
        self.audit_search_cache_key = cache_key
        self.audit_search_cache_records = list(records)
        if not records:
            self.audit_search_status_label.setText(
                f"No matches for '{query}' in {scope}."
            )
            self.audit_search_replace_selected_btn.setEnabled(False)
            self.audit_search_replace_all_btn.setEnabled(False)
            self.audit_search_displayed_key = cache_key
            self.audit_search_display_complete = True
            return
        match_label = "match" if len(records) == 1 else "matches"
        self.audit_search_status_label.setText(
            f"Found {len(records)} {match_label} for '{query}' in {scope}."
        )
        self._set_audit_progress_overlay(
            self.audit_search_results_list,
            self.audit_search_progress_overlay,
            f"Rendering 0/{len(records)}",
        )
        self.audit_search_render_records = records
        self.audit_search_render_index = 0
        self.audit_search_render_generation = generation
        self.audit_search_render_query = query
        self.audit_search_render_needle = needle
        self.audit_search_render_natural_mode = bool(
            running_request.get("natural_mode", False))
        self.audit_search_render_case_sensitive = case_sensitive
        self.audit_search_render_scope = scope
        self.audit_search_display_complete = False
        self.audit_search_render_timer.start(
            self.audit_render_batch_interval_ms)

    def _run_audit_search(self) -> None:
        if (
            self.audit_search_query_edit is None
            or self.audit_search_replace_edit is None
            or self.audit_search_scope_combo is None
            or self.audit_search_results_list is None
            or self.audit_search_status_label is None
            or self.audit_search_goto_btn is None
            or self.audit_search_replace_selected_btn is None
            or self.audit_search_replace_all_btn is None
        ):
            return
        if self.audit_search_timer is not None:
            self.audit_search_timer.stop()

        query = self.audit_search_query_edit.text().strip()
        scope = str(self.audit_search_scope_combo.currentData() or "original")
        case_sensitive = self._audit_search_case_sensitive_enabled()

        if not query:
            self._stop_audit_search_render()
            self.audit_search_results_list.clear()
            self.audit_search_goto_btn.setEnabled(False)
            self.audit_search_replace_selected_btn.setEnabled(False)
            self.audit_search_replace_all_btn.setEnabled(False)
            self.audit_search_displayed_key = None
            self.audit_search_display_complete = False
            self.audit_search_status_label.setText("Type to search.")
            self.audit_search_worker_pending_request = None
            self._refresh_audit_search_replace_preview()
            return
        if not self.sessions:
            self._stop_audit_search_render()
            self.audit_search_results_list.clear()
            self.audit_search_goto_btn.setEnabled(False)
            self.audit_search_replace_selected_btn.setEnabled(False)
            self.audit_search_replace_all_btn.setEnabled(False)
            self.audit_search_displayed_key = None
            self.audit_search_display_complete = False
            self.audit_search_status_label.setText("No data loaded.")
            self.audit_search_worker_pending_request = None
            self._refresh_audit_search_replace_preview()
            return

        control_query = self._is_control_code_search_query(query)
        if control_query:
            needle = query if case_sensitive else query.casefold()
        else:
            needle = self._normalize_text_for_natural_search(query, case_sensitive)
        requested_key = (self.audit_cache_generation, scope, needle, case_sensitive)
        if (
            self.audit_search_display_complete
            and self.audit_search_displayed_key == requested_key
        ):
            rows = self.audit_search_results_list.count()
            if rows > 0:
                match_label = "match" if rows == 1 else "matches"
                self.audit_search_status_label.setText(
                    f"Found {rows} {match_label} for '{query}' in {scope}."
                )
                self.audit_search_goto_btn.setEnabled(
                    self.audit_search_results_list.currentItem() is not None
                )
                self.audit_search_replace_selected_btn.setEnabled(
                    self.audit_search_results_list.currentItem() is not None
                )
                self.audit_search_replace_all_btn.setEnabled(True)
            else:
                self.audit_search_status_label.setText(
                    f"No matches for '{query}' in {scope}."
                )
                self.audit_search_goto_btn.setEnabled(False)
                self.audit_search_replace_selected_btn.setEnabled(False)
                self.audit_search_replace_all_btn.setEnabled(False)
                self._refresh_audit_search_replace_preview()
            return

        self._stop_audit_search_render()
        self.audit_search_results_list.clear()
        self.audit_search_goto_btn.setEnabled(False)
        self.audit_search_replace_selected_btn.setEnabled(False)
        self.audit_search_replace_all_btn.setEnabled(False)
        self.audit_search_display_complete = False
        self.audit_search_displayed_key = None
        cache_key = (self.audit_cache_generation, scope, needle, case_sensitive)
        if self.audit_search_cache_key == cache_key:
            records = list(self.audit_search_cache_records)
            if not records:
                self.audit_search_status_label.setText(
                    f"No matches for '{query}' in {scope}."
                )
                self.audit_search_replace_selected_btn.setEnabled(False)
                self.audit_search_replace_all_btn.setEnabled(False)
                self.audit_search_displayed_key = cache_key
                self.audit_search_display_complete = True
                self._refresh_audit_search_replace_preview()
                return
            match_label = "match" if len(records) == 1 else "matches"
            self.audit_search_status_label.setText(
                f"Found {len(records)} {match_label} for '{query}' in {scope}."
            )
            self._set_audit_progress_overlay(
                self.audit_search_results_list,
                self.audit_search_progress_overlay,
                f"Rendering 0/{len(records)}",
            )
            self.audit_search_render_records = records
            self.audit_search_render_index = 0
            self.audit_search_render_generation = self.audit_cache_generation
            self.audit_search_render_query = query
            self.audit_search_render_needle = needle
            self.audit_search_render_natural_mode = not control_query
            self.audit_search_render_scope = scope
            self.audit_search_replace_all_btn.setEnabled(True)
            self.audit_search_render_timer.start(
                self.audit_render_batch_interval_ms)
            self._refresh_audit_search_replace_preview()
            return

        request = {
            "generation": self.audit_cache_generation,
            "query": query,
            "scope": scope,
            "needle": needle,
            "natural_mode": not control_query,
            "case_sensitive": case_sensitive,
            "path_sessions": self._audit_path_sessions_snapshot(),
        }
        self.audit_search_status_label.setText(
            f"Scanning for '{query}' in {scope}..."
        )
        self._refresh_audit_search_replace_preview()
        self._queue_audit_search_worker(request)

    def _render_next_audit_search_batch(self) -> None:
        if (
            self.audit_search_results_list is None
            or self.audit_search_status_label is None
            or self.audit_search_goto_btn is None
            or self.audit_search_replace_selected_btn is None
            or self.audit_search_replace_all_btn is None
        ):
            self._stop_audit_search_render()
            return
        records = self.audit_search_render_records
        total = len(records)
        if total <= 0:
            self.audit_search_status_label.setText("Type to search.")
            self.audit_search_replace_selected_btn.setEnabled(False)
            self.audit_search_replace_all_btn.setEnabled(False)
            self._refresh_audit_search_replace_preview()
            self._stop_audit_search_render()
            return
        start = self.audit_search_render_index
        end = min(start + self.audit_result_batch_size, total)
        query = self.audit_search_render_query
        needle = str(getattr(self, "audit_search_render_needle", query.casefold()))
        natural_mode = bool(
            getattr(self, "audit_search_render_natural_mode", False))
        case_sensitive = bool(
            getattr(self, "audit_search_render_case_sensitive", True))
        scope = self.audit_search_render_scope
        prev_updates = self.audit_search_results_list.updatesEnabled()
        self.audit_search_results_list.setUpdatesEnabled(False)
        try:
            for record in records[start:end]:
                self._add_audit_search_result(
                    path=cast(Path, record["path"]),
                    uid=str(record["uid"]),
                    entry_text=str(record["entry_text"]),
                    matched_field=str(record["matched_field"]),
                    matched_text=str(record["matched_text"]),
                    query=query,
                    needle=needle,
                    natural_mode=natural_mode,
                    case_sensitive=case_sensitive,
                )
        finally:
            self.audit_search_results_list.setUpdatesEnabled(prev_updates)
        self.audit_search_render_index = end
        if end < total:
            self._set_audit_progress_overlay(
                self.audit_search_results_list,
                self.audit_search_progress_overlay,
                f"Rendering {end}/{total}",
            )
            self.audit_search_render_timer.start(
                self.audit_render_batch_interval_ms)
            return
        if self.audit_search_results_list.count() > 0:
            self.audit_search_results_list.setCurrentRow(0)
            self.audit_search_goto_btn.setEnabled(True)
            self.audit_search_replace_selected_btn.setEnabled(True)
            self.audit_search_replace_all_btn.setEnabled(True)
        else:
            self.audit_search_replace_selected_btn.setEnabled(False)
            self.audit_search_replace_all_btn.setEnabled(False)
        self.audit_search_displayed_key = (
            self.audit_search_render_generation,
            scope,
            needle,
            case_sensitive,
        )
        self.audit_search_display_complete = True
        match_label = "match" if total == 1 else "matches"
        self.audit_search_status_label.setText(
            f"Found {total} {match_label} for '{query}' in {scope}."
        )
        self._refresh_audit_search_replace_preview()
        self._stop_audit_search_render()

    def _go_to_selected_audit_result(self) -> None:
        if self.audit_search_results_list is None:
            return
        item = self.audit_search_results_list.currentItem()
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

    def _replace_regex_for_case(self, find_text: str, case_sensitive: bool) -> re.Pattern[str]:
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.compile(re.escape(find_text), flags)

    def _inline_replace_diff_html(
        self,
        source_text: str,
        find_text: str,
        replace_text: str,
        case_sensitive: bool,
    ) -> tuple[str, int]:
        if not find_text:
            return html.escape(source_text).replace("\n", "<br>"), 0
        pattern = self._replace_regex_for_case(find_text, case_sensitive)
        parts: list[str] = []
        cursor = 0
        replacements = 0
        for match in pattern.finditer(source_text):
            if match.start() > cursor:
                parts.append(html.escape(source_text[cursor:match.start()]))
            old_text = html.escape(match.group(0))
            new_text = html.escape(replace_text)
            parts.append(
                "<span style=\"background-color:#fee2e2; color:#991b1b; "
                "text-decoration:line-through; font-weight:600;\">"
                f"{old_text}</span>"
            )
            parts.append(" ")
            parts.append(
                "<span style=\"background-color:#dcfce7; color:#166534; "
                "font-weight:600;\">"
                f"{new_text}</span>"
            )
            cursor = match.end()
            replacements += 1
        if cursor < len(source_text):
            parts.append(html.escape(source_text[cursor:]))
        return "".join(parts).replace("\n", "<br>"), replacements

    def _refresh_audit_search_replace_preview(self) -> None:
        if self.audit_search_results_list is None:
            return
        if self.audit_search_query_edit is None or self.audit_search_replace_edit is None:
            return
        query = self.audit_search_query_edit.text().strip()
        replace_text = self.audit_search_replace_edit.text()
        case_sensitive = (
            self._audit_search_case_sensitive_enabled()
        )
        control_query = self._is_control_code_search_query(query)
        natural_mode = not control_query
        needle = (
            query if case_sensitive else query.casefold()
            if control_query
            else self._normalize_text_for_natural_search(query, case_sensitive)
        )

        list_widget = self.audit_search_results_list
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            payload_raw = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(payload_raw, dict):
                continue
            path_raw = payload_raw.get("path")
            entry_text_raw = payload_raw.get("entry_text")
            matched_field_raw = payload_raw.get("matched_field")
            matched_text_raw = payload_raw.get("matched_text")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            entry_text = entry_text_raw if isinstance(entry_text_raw, str) else "Entry"
            matched_field = matched_field_raw if isinstance(
                matched_field_raw, str) else "Match"
            matched_text = matched_text_raw if isinstance(matched_text_raw, str) else ""
            rel_path = self._relative_path(Path(path_raw))
            header_text = f"{rel_path} | {entry_text} | {matched_field}"

            highlighted = self._highlight_audit_match_html(
                matched_text,
                query,
                needle,
                natural_mode,
                case_sensitive,
            )
            rendered_line = highlighted
            replace_mode = bool(replace_text)
            if replace_mode and query:
                diff_html, _replacement_hits = self._inline_replace_diff_html(
                    matched_text,
                    query,
                    replace_text,
                    case_sensitive,
                )
                rendered_line = diff_html
            body_html = (
                "<div style=\"padding: 4px 0;\">"
                f"<b>{html.escape(header_text)}</b><br>"
                f"{rendered_line}"
            )
            body_html += "</div>"

            widget = list_widget.itemWidget(item)
            if not isinstance(widget, QLabel):
                widget = QLabel()
                widget.setTextFormat(Qt.TextFormat.RichText)
                widget.setWordWrap(True)
                widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                widget.setTextInteractionFlags(
                    Qt.TextInteractionFlag.NoTextInteraction)
                widget.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                list_widget.setItemWidget(item, widget)
            widget.setText(body_html)
            item.setSizeHint(widget.sizeHint())

    def _replace_in_lines(
        self,
        lines: list[str],
        find_text: str,
        replace_text: str,
        case_sensitive: bool,
    ) -> tuple[list[str], int]:
        if not find_text:
            return list(lines), 0
        pattern = self._replace_regex_for_case(find_text, case_sensitive)
        updated = list(lines) if lines else [""]
        total = 0
        for idx, line in enumerate(updated):
            hits = len(list(pattern.finditer(line)))
            if hits <= 0:
                continue
            updated[idx] = pattern.sub(replace_text, line)
            total += hits
        return updated, total

    def _replace_in_session_entry(
        self,
        path_raw: str,
        uid: str,
        find_text: str,
        replace_text: str,
        matched_scope: str,
        case_sensitive: bool,
    ) -> tuple[bool, int]:
        path = Path(path_raw)
        session = self.sessions.get(path)
        if session is None:
            return False, 0
        target = None
        for segment in session.segments:
            if segment.uid == uid:
                target = segment
                break
        if target is None:
            return False, 0

        changed = False
        replacements = 0
        if matched_scope in {"original", "both"}:
            source_lines = list(target.lines) if target.lines else [""]
            replaced_lines, count = self._replace_in_lines(
                source_lines, find_text, replace_text, case_sensitive
            )
            if count > 0 and replaced_lines != source_lines:
                target.lines = list(replaced_lines)
                target.source_lines = list(replaced_lines)
                changed = True
                replacements += count
        if matched_scope in {"translation", "both"}:
            tl_lines = self._normalize_translation_lines(target.translation_lines)
            replaced_lines, count = self._replace_in_lines(
                tl_lines, find_text, replace_text, case_sensitive
            )
            if count > 0 and replaced_lines != tl_lines:
                target.translation_lines = list(replaced_lines)
                changed = True
                replacements += count
        if changed:
            self._refresh_dirty_state(session)
        return changed, replacements

    def _scope_from_matched_field(self, value: str) -> str:
        lowered = (value or "").strip().casefold()
        if lowered.startswith("translation"):
            return "translation"
        if lowered.startswith("original"):
            return "original"
        return "both"

    def _selected_audit_search_payload(self) -> Optional[dict[str, str]]:
        if self.audit_search_results_list is None:
            return None
        item = self.audit_search_results_list.currentItem()
        if item is None:
            return None
        payload_raw = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload_raw, dict):
            return None
        path_raw = payload_raw.get("path")
        uid_raw = payload_raw.get("uid")
        scope_raw = payload_raw.get("matched_scope")
        if not isinstance(path_raw, str) or not path_raw:
            return None
        if not isinstance(uid_raw, str) or not uid_raw:
            return None
        matched_scope = (
            scope_raw if isinstance(scope_raw, str) and scope_raw else "both"
        )
        return {"path": path_raw, "uid": uid_raw, "scope": matched_scope}

    def _replace_selected_audit_search_result(self) -> None:
        if (
            self.audit_search_query_edit is None
            or self.audit_search_replace_edit is None
            or self.audit_search_results_list is None
        ):
            return
        payload = self._selected_audit_search_payload()
        if payload is None:
            self.statusBar().showMessage("Select a search result first.")
            return
        find_text = self.audit_search_query_edit.text()
        if not find_text:
            self.statusBar().showMessage("Enter text in Find first.")
            return
        replace_text = self.audit_search_replace_edit.text()
        case_sensitive = (
            self._audit_search_case_sensitive_enabled()
        )
        changed, replacements = self._replace_in_session_entry(
            payload["path"],
            payload["uid"],
            find_text,
            replace_text,
            self._scope_from_matched_field(payload["scope"]),
            case_sensitive,
        )
        if not changed:
            self.statusBar().showMessage("No replacements applied for selected result.")
            return

        self._invalidate_audit_caches()
        self._refresh_audit_sanitize_panel()
        self._refresh_audit_control_mismatch_panel()
        if self.current_path is not None:
            current = self.sessions.get(self.current_path)
            if current is not None:
                self._render_session(
                    current,
                    focus_uid=self.selected_segment_uid,
                    preserve_scroll=True,
                )
        else:
            self._refresh_translator_detail_panel()
        self._run_audit_search()
        self._refresh_audit_search_replace_preview()
        match_label = "match" if replacements == 1 else "matches"
        self.statusBar().showMessage(
            f"Replaced {replacements} {match_label} in selected result."
        )

    def _replace_all_audit_search_results(self) -> None:
        if (
            self.audit_search_query_edit is None
            or self.audit_search_replace_edit is None
            or self.audit_search_results_list is None
            or self.audit_search_scope_combo is None
        ):
            return
        if not self.audit_search_display_complete:
            self.statusBar().showMessage("Wait for search to finish before Replace All.")
            return
        find_text = self.audit_search_query_edit.text()
        if not find_text:
            self.statusBar().showMessage("Enter text in Find first.")
            return
        replace_text = self.audit_search_replace_edit.text()
        case_sensitive = (
            self._audit_search_case_sensitive_enabled()
        )
        result_count = self.audit_search_results_list.count()
        if result_count <= 0:
            self.statusBar().showMessage("No search results to replace.")
            return

        button = QMessageBox.question(
            cast(QWidget, self),
            "Replace all matches",
            (
                f"Replace '{find_text}' with '{replace_text}' "
                f"in {result_count} result {'entry' if result_count == 1 else 'entries'}?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if button != QMessageBox.StandardButton.Yes:
            return

        unique_targets: dict[tuple[str, str, str], None] = {}
        for row in range(result_count):
            item = self.audit_search_results_list.item(row)
            payload_raw = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(payload_raw, dict):
                continue
            path_raw = payload_raw.get("path")
            uid_raw = payload_raw.get("uid")
            scope_raw = payload_raw.get("matched_scope")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            if not isinstance(uid_raw, str) or not uid_raw:
                continue
            matched_scope = scope_raw if isinstance(scope_raw, str) else "both"
            key = (path_raw, uid_raw, self._scope_from_matched_field(matched_scope))
            unique_targets[key] = None

        touched_current = False
        changed_entries = 0
        total_replacements = 0
        for path_raw, uid, scope in unique_targets.keys():
            changed, replacements = self._replace_in_session_entry(
                path_raw,
                uid,
                find_text,
                replace_text,
                scope,
                case_sensitive,
            )
            if not changed:
                continue
            changed_entries += 1
            total_replacements += replacements
            path = Path(path_raw)
            if self.current_path is not None and path == self.current_path:
                touched_current = True

        if changed_entries <= 0:
            self.statusBar().showMessage("No replacements applied.")
            return

        self._invalidate_audit_caches()
        self._refresh_audit_sanitize_panel()
        self._refresh_audit_control_mismatch_panel()
        if touched_current and self.current_path is not None:
            current = self.sessions.get(self.current_path)
            if current is not None:
                self._render_session(
                    current,
                    focus_uid=self.selected_segment_uid,
                    preserve_scroll=True,
                )
        else:
            self._refresh_translator_detail_panel()
        self._run_audit_search()
        self._refresh_audit_search_replace_preview()
        match_label = "match" if total_replacements == 1 else "matches"
        entry_label = "entry" if changed_entries == 1 else "entries"
        self.statusBar().showMessage(
            f"Replaced {total_replacements} {match_label} in {changed_entries} result {entry_label}."
        )
