from __future__ import annotations

import html
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem

from ..core.models import FileSession


class _AuditSearchHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditSearchMixin(_AuditSearchHostTypingFallback):
    def _schedule_audit_search(self) -> None:
        if self.audit_search_timer is None:
            return
        self.audit_search_timer.start()

    def _highlight_audit_match_html(self, text: str, query: str) -> str:
        source_text = text or ""
        if not query:
            return html.escape(source_text).replace("\n", "<br>")
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        highlight_style = self._audit_highlight_style()
        parts: list[str] = []
        last_idx = 0
        for match in pattern.finditer(source_text):
            start, end = match.span()
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
            {"path": str(path), "uid": uid},
        )
        self.audit_search_results_list.addItem(item)

        body = QLabel()
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        body.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.setText(
            "<div style=\"padding: 4px 0;\">"
            f"<b>{html.escape(header_text)}</b><br>"
            f"{self._highlight_audit_match_html(matched_text, query)}"
            "</div>"
        )

        item.setSizeHint(body.sizeHint())
        self.audit_search_results_list.setItemWidget(item, body)

    def _compute_audit_search_records_worker(
        self,
        path_sessions: list[tuple[Path, FileSession]],
        scope: str,
        needle: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path, session in path_sessions:
            is_name_index = self._is_name_index_session(session)
            name_index_label = self._name_index_label(session)
            for idx, segment in enumerate(list(session.segments), start=1):
                original_text = "\n".join(self._segment_source_lines_for_display(segment))
                translation_text = "\n".join(
                    self._normalize_translation_lines(segment.translation_lines)
                )
                entry_text = f"{name_index_label} {idx}" if is_name_index else f"Block {idx}"
                if is_name_index:
                    actor_id = self._actor_id_from_uid(segment.uid)
                    if actor_id is not None:
                        entry_text = f"{name_index_label} ID {actor_id}"
                if scope in ("original", "both") and needle in original_text.casefold():
                    records.append(
                        {
                            "path": path,
                            "uid": segment.uid,
                            "entry_text": entry_text,
                            "matched_field": "Original",
                            "matched_text": original_text,
                        }
                    )
                if scope in ("translation", "both") and needle in translation_text.casefold():
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
            )
        except Exception as exc:
            self.audit_search_worker_future = None
            self.audit_search_worker_running_request = None
            if self.audit_search_status_label is not None:
                self.audit_search_status_label.setText(f"Search scan failed: {exc}")
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
                self.audit_search_status_label.setText(f"Search scan failed: {exc}")
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
        if generation != self.audit_cache_generation:
            return
        if (
            self.audit_search_query_edit is None
            or self.audit_search_scope_combo is None
            or self.audit_search_results_list is None
            or self.audit_search_status_label is None
            or self.audit_search_goto_btn is None
        ):
            return
        current_query = self.audit_search_query_edit.text().strip()
        current_scope = str(self.audit_search_scope_combo.currentData() or "original")
        if current_query != query or current_scope != scope:
            return
        cache_key = (generation, scope, needle)
        self.audit_search_cache_key = cache_key
        self.audit_search_cache_records = list(records)
        if not records:
            self.audit_search_status_label.setText(
                f"No matches for '{query}' in {scope}."
            )
            self.audit_search_displayed_key = cache_key
            self.audit_search_display_complete = True
            return
        self.audit_search_status_label.setText(
            f"Found {len(records)} match(es) for '{query}' in {scope}."
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
        self.audit_search_render_scope = scope
        self.audit_search_display_complete = False
        self.audit_search_render_timer.start(self.audit_render_batch_interval_ms)

    def _run_audit_search(self) -> None:
        if (
            self.audit_search_query_edit is None
            or self.audit_search_scope_combo is None
            or self.audit_search_results_list is None
            or self.audit_search_status_label is None
            or self.audit_search_goto_btn is None
        ):
            return
        if self.audit_search_timer is not None:
            self.audit_search_timer.stop()

        query = self.audit_search_query_edit.text().strip()
        scope = str(self.audit_search_scope_combo.currentData() or "original")

        if not query:
            self._stop_audit_search_render()
            self.audit_search_results_list.clear()
            self.audit_search_goto_btn.setEnabled(False)
            self.audit_search_displayed_key = None
            self.audit_search_display_complete = False
            self.audit_search_status_label.setText("Type to search.")
            self.audit_search_worker_pending_request = None
            return
        if not self.sessions:
            self._stop_audit_search_render()
            self.audit_search_results_list.clear()
            self.audit_search_goto_btn.setEnabled(False)
            self.audit_search_displayed_key = None
            self.audit_search_display_complete = False
            self.audit_search_status_label.setText("No data loaded.")
            self.audit_search_worker_pending_request = None
            return

        needle = query.casefold()
        requested_key = (self.audit_cache_generation, scope, needle)
        if (
            self.audit_search_display_complete
            and self.audit_search_displayed_key == requested_key
        ):
            rows = self.audit_search_results_list.count()
            if rows > 0:
                self.audit_search_status_label.setText(
                    f"Found {rows} match(es) for '{query}' in {scope}."
                )
                self.audit_search_goto_btn.setEnabled(
                    self.audit_search_results_list.currentItem() is not None
                )
            else:
                self.audit_search_status_label.setText(
                    f"No matches for '{query}' in {scope}."
                )
                self.audit_search_goto_btn.setEnabled(False)
            return

        self._stop_audit_search_render()
        self.audit_search_results_list.clear()
        self.audit_search_goto_btn.setEnabled(False)
        self.audit_search_display_complete = False
        self.audit_search_displayed_key = None
        cache_key = (self.audit_cache_generation, scope, needle)
        if self.audit_search_cache_key == cache_key:
            records = list(self.audit_search_cache_records)
            if not records:
                self.audit_search_status_label.setText(
                    f"No matches for '{query}' in {scope}."
                )
                self.audit_search_displayed_key = cache_key
                self.audit_search_display_complete = True
                return
            self.audit_search_status_label.setText(
                f"Found {len(records)} match(es) for '{query}' in {scope}."
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
            self.audit_search_render_scope = scope
            self.audit_search_render_timer.start(self.audit_render_batch_interval_ms)
            return

        request = {
            "generation": self.audit_cache_generation,
            "query": query,
            "scope": scope,
            "needle": needle,
            "path_sessions": self._audit_path_sessions_snapshot(),
        }
        self.audit_search_status_label.setText(
            f"Scanning for '{query}' in {scope}..."
        )
        self._queue_audit_search_worker(request)

    def _render_next_audit_search_batch(self) -> None:
        if (
            self.audit_search_results_list is None
            or self.audit_search_status_label is None
            or self.audit_search_goto_btn is None
        ):
            self._stop_audit_search_render()
            return
        records = self.audit_search_render_records
        total = len(records)
        if total <= 0:
            self.audit_search_status_label.setText("Type to search.")
            self._stop_audit_search_render()
            return
        start = self.audit_search_render_index
        end = min(start + self.audit_result_batch_size, total)
        query = self.audit_search_render_query
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
            self.audit_search_render_timer.start(self.audit_render_batch_interval_ms)
            return
        if self.audit_search_results_list.count() > 0:
            self.audit_search_results_list.setCurrentRow(0)
            self.audit_search_goto_btn.setEnabled(True)
        self.audit_search_displayed_key = (
            self.audit_search_render_generation,
            scope,
            query.casefold(),
        )
        self.audit_search_display_complete = True
        self.audit_search_status_label.setText(
            f"Found {total} match(es) for '{query}' in {scope}."
        )
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

