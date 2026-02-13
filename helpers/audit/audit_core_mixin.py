from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget

from ..core.models import FileSession
from ..mixins.presentation_mixins import is_dark_palette


class _AuditCoreHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditCoreMixin(_AuditCoreHostTypingFallback):
    def _set_audit_pinned_uid(self, uid: Optional[str]) -> None:
        self.audit_pinned_uid = uid
        refresh_visuals = getattr(self, "_refresh_block_visual_states", None)
        if callable(refresh_visuals):
            refresh_visuals()

    def _overlay_host_widget(self, target_widget: QWidget) -> QWidget:
        viewport_getter = getattr(target_widget, "viewport", None)
        if callable(viewport_getter):
            try:
                viewport = viewport_getter()
            except Exception:
                viewport = None
            if isinstance(viewport, QWidget):
                return viewport
        return target_widget

    def _create_audit_progress_overlay(self, target_widget: QWidget) -> QLabel:
        overlay = QLabel(self._overlay_host_widget(target_widget))
        overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay.setWordWrap(True)
        overlay.setTextFormat(Qt.TextFormat.PlainText)
        overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet(
            "QLabel {"
            "background-color: rgba(2, 6, 23, 140);"
            "color: #f8fafc;"
            "font-size: 15px;"
            "font-weight: 700;"
            "padding: 0;"
            "}"
        )
        overlay.hide()
        return overlay

    def _set_audit_progress_overlay(
        self,
        target_widget: Optional[QWidget],
        overlay: Optional[QLabel],
        text: str,
    ) -> None:
        if target_widget is None or overlay is None:
            return
        host = self._overlay_host_widget(target_widget)
        if host.width() <= 0 or host.height() <= 0:
            return
        if overlay.parentWidget() is not host:
            overlay.setParent(host)
        overlay.setGeometry(host.rect())
        overlay.setText(text)
        if not overlay.isVisible():
            overlay.show()
        overlay.raise_()

    def _hide_audit_progress_overlay(self, overlay: Optional[QLabel]) -> None:
        if overlay is not None and overlay.isVisible():
            overlay.hide()

    def _audit_path_sessions_snapshot(self) -> list[tuple[Path, FileSession]]:
        rows: list[tuple[Path, FileSession]] = []
        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            rows.append((path, session))
        return rows

    def _search_request_key(self, request: Optional[dict[str, Any]]) -> tuple[Any, ...]:
        if not isinstance(request, dict):
            return ()
        return (
            request.get("generation"),
            request.get("scope"),
            request.get("needle"),
            request.get("case_sensitive"),
        )

    def _sanitize_request_key(self, request: Optional[dict[str, Any]]) -> tuple[Any, ...]:
        if not isinstance(request, dict):
            return ()
        return (
            request.get("mode"),
            request.get("generation"),
            request.get("scope"),
            request.get("selected_rule_id"),
            request.get("selected_find_text"),
        )

    def _control_request_key(self, request: Optional[dict[str, Any]]) -> tuple[Any, ...]:
        if not isinstance(request, dict):
            return ()
        return (
            request.get("generation"),
            request.get("only_translated"),
        )

    def _stop_audit_search_render(self) -> None:
        self.audit_search_render_timer.stop()
        self._hide_audit_progress_overlay(self.audit_search_progress_overlay)
        self.audit_search_render_records = []
        self.audit_search_render_index = 0
        self.audit_search_render_query = ""
        self.audit_search_render_scope = "original"
        self.audit_search_render_generation = 0

    def _stop_audit_sanitize_render(self) -> None:
        self.audit_sanitize_render_timer.stop()
        self._hide_audit_progress_overlay(self.audit_sanitize_progress_overlay)
        self.audit_sanitize_render_records = []
        self.audit_sanitize_render_index = 0
        self.audit_sanitize_render_rule_id = ""
        self.audit_sanitize_render_find_text = ""
        self.audit_sanitize_render_show_field_label = False
        self.audit_sanitize_render_generation = 0
        self.audit_sanitize_render_scope = "original"
        self.audit_sanitize_render_total_hits = 0
        self.audit_sanitize_render_entries = 0
        self.audit_sanitize_render_block_count = 0

    def _stop_audit_control_mismatch_render(self) -> None:
        self.audit_control_mismatch_render_timer.stop()
        self._hide_audit_progress_overlay(
            self.audit_control_mismatch_progress_overlay)
        self.audit_control_mismatch_render_records = []
        self.audit_control_mismatch_render_index = 0
        self.audit_control_mismatch_render_scanned_blocks = 0
        self.audit_control_mismatch_render_only_translated = True
        self.audit_control_mismatch_render_generation = 0

    def _invalidate_audit_caches(self) -> None:
        self.audit_cache_generation += 1
        self.audit_search_cache_key = None
        self.audit_search_cache_records = []
        self.audit_sanitize_counts_cache_key = None
        self.audit_sanitize_counts_cache = {}
        self.audit_sanitize_occurrence_cache_key = None
        self.audit_sanitize_occurrence_cache_payload = None
        self.audit_sanitize_occurrence_cache_by_key = {}
        self.audit_control_mismatch_cache_key = None
        self.audit_control_mismatch_cache_records = []
        self.audit_control_mismatch_cache_scanned_blocks = 0
        self.audit_search_displayed_key = None
        self.audit_search_display_complete = False
        self.audit_sanitize_displayed_key = None
        self.audit_sanitize_display_complete = False
        self.audit_sanitize_built_view_keys = set()
        self.audit_sanitize_active_view_key = None
        self.audit_control_mismatch_displayed_key = None
        self.audit_control_mismatch_display_complete = False
        if self.audit_sanitize_occurrences_list is not None:
            self.audit_sanitize_occurrences_list.clear()
        self.audit_search_worker_pending_request = None
        self.audit_sanitize_worker_pending_request = None
        self.audit_control_worker_pending_request = None
        self._stop_audit_search_render()
        self._stop_audit_sanitize_render()
        self._stop_audit_control_mismatch_render()

    def _audit_highlight_style(self) -> str:
        if is_dark_palette():
            return "background-color:#facc15; color:#111827; font-weight:600;"
        return "background-color:#fde047; color:#111827; font-weight:600;"

    def _jump_to_audit_location(self, path_raw: str, uid_raw: str) -> bool:
        path = Path(path_raw)
        if path not in self.sessions:
            self.statusBar().showMessage(
                f"Cannot jump: {path.name} is not loaded."
            )
            return False

        if path not in self.file_items:
            self._rebuild_file_list(preferred_path=path)

        file_item = self.file_items.get(path)
        if file_item is not None:
            row = self.file_list.row(file_item)
            if row >= 0:
                self.file_list.blockSignals(True)
                self.file_list.setCurrentRow(row)
                self.file_list.blockSignals(False)

        self.pending_audit_flash_uid = uid_raw
        self._set_audit_pinned_uid(uid_raw)
        self._open_file(path, focus_uid=uid_raw)
        self._schedule_audit_target_flash(uid_raw)
        self.statusBar().showMessage(
            f"Jumped to {self._relative_path(path)} ({uid_raw})."
        )
        return True

    def _schedule_audit_target_flash(self, uid: str) -> None:
        for delay_ms in (0, 90, 220):
            QTimer.singleShot(
                delay_ms, lambda target_uid=uid: self._flash_audit_target_block(target_uid)
            )

    def _flash_audit_target_block(self, uid: str) -> None:
        if self.pending_audit_flash_uid != uid:
            return
        widget = self.block_widgets.get(uid)
        if widget is None:
            return
        flash_highlight = getattr(widget, "flash_highlight", None)
        if callable(flash_highlight):
            flash_highlight()
            self.pending_audit_flash_uid = None
            self._set_audit_pinned_uid(uid)
