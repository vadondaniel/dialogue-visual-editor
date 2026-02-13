from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem, QMenu

from .audit_constants import SANITIZE_CHAR_RULES
from ..core.models import DialogueSegment, FileSession


class _AuditSanitizeHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditSanitizeUiMixin(_AuditSanitizeHostTypingFallback):
    def _highlight_audit_literal_html(self, text: str, literal: str) -> str:
        source_text = text or ""
        if not literal:
            return html.escape(source_text).replace("\n", "<br>")
        style = self._audit_highlight_style()
        parts: list[str] = []
        cursor = 0
        token_len = len(literal)
        while cursor <= len(source_text):
            hit = source_text.find(literal, cursor)
            if hit < 0:
                break
            if hit > cursor:
                parts.append(html.escape(source_text[cursor:hit]))
            parts.append(
                "<span style=\""
                + style
                + "\">"
                + html.escape(source_text[hit: hit + token_len])
                + "</span>"
            )
            cursor = hit + token_len
        if cursor < len(source_text):
            parts.append(html.escape(source_text[cursor:]))
        return "".join(parts).replace("\n", "<br>")

    def _add_audit_sanitize_occurrence_result(
        self,
        path: Path,
        uid: str,
        rule_id: str,
        entry_text: str,
        occurrences: list[dict[str, Any]],
        find_text: str,
        show_field_label: bool,
        view_key: Optional[tuple[int, str, str]] = None,
    ) -> None:
        if self.audit_sanitize_occurrences_list is None:
            return
        if not occurrences:
            return
        relative_path = self._relative_path(path)
        total_hits = sum(
            int(occurrence.get("hit_count", 0))
            for occurrence in occurrences
        )
        line_count = len(occurrences)
        hit_label = "hit" if total_hits == 1 else "hits"
        line_label = "line" if line_count == 1 else "lines"
        header_text = f"{relative_path} | {entry_text} | {total_hits} {hit_label} across {line_count} {line_label}"

        item = QListWidgetItem()
        item.setFlags(
            item.flags()
            | Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )
        item.setData(
            Qt.ItemDataRole.UserRole,
            {"path": str(path), "uid": uid, "rule_id": rule_id},
        )
        if view_key is not None:
            item.setData(Qt.ItemDataRole.UserRole + 1, view_key)
        self.audit_sanitize_occurrences_list.addItem(item)

        body = QLabel()
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        body.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lines_html: list[str] = []
        ignored_row = False
        for occurrence in occurrences:
            field_label = str(occurrence.get("field_label", ""))
            line_index = int(occurrence.get("line_index", 0))
            hit_count = int(occurrence.get("hit_count", 0))
            line_text = str(occurrence.get("line_text", ""))
            ignored_row = ignored_row or bool(occurrence.get("ignored", False))
            if show_field_label:
                prefix = f"<b>{html.escape(field_label)} L{line_index} x{hit_count}</b>: "
            else:
                prefix = f"<b>L{line_index} x{hit_count}</b>: "
            lines_html.append(
                prefix + self._highlight_audit_literal_html(line_text, find_text))
        effective_header_text = header_text
        if ignored_row:
            effective_header_text = f"[Ignored] {header_text}"
            lines_html.insert(
                0, "<i>Ignored for selected rule (not applied in bulk).</i>")
        body.setText(
            "<div style=\"padding: 4px 0;\">"
            f"<b>{html.escape(effective_header_text)}</b><br>"
            f"{'<br>'.join(lines_html)}"
            "</div>"
        )

        item.setSizeHint(body.sizeHint())
        self.audit_sanitize_occurrences_list.setItemWidget(item, body)
        if view_key is not None and self.audit_sanitize_active_view_key != view_key:
            item.setHidden(True)

    def _audit_entry_text_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
        index: int,
    ) -> str:
        if not self._is_name_index_session(session):
            return f"Block {index}"
        name_index_label = self._name_index_label(session)
        actor_id = self._actor_id_from_uid(segment.uid)
        if actor_id is not None:
            return f"{name_index_label} ID {actor_id}"
        return f"{name_index_label} {index}"

    def _audit_sanitize_scope(self) -> str:
        if self.audit_sanitize_scope_combo is None:
            return "original"
        return str(self.audit_sanitize_scope_combo.currentData() or "original")

    def _audit_sanitize_rule_payload(
        self, item: Optional[QListWidgetItem]
    ) -> Optional[dict[str, str]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        rule_id = payload.get("rule_id")
        label = payload.get("label")
        find_text = payload.get("find_text")
        replace_text = payload.get("replace_text")
        if (
            not isinstance(rule_id, str)
            or not isinstance(label, str)
            or not isinstance(find_text, str)
            or not isinstance(replace_text, str)
            or not find_text
        ):
            return None
        return {
            "rule_id": rule_id,
            "label": label,
            "find_text": find_text,
            "replace_text": replace_text,
        }

    def _audit_sanitize_rule_payload_by_id(self, rule_id: str) -> Optional[dict[str, str]]:
        for candidate_rule_id, label, find_text, replace_text in SANITIZE_CHAR_RULES:
            if candidate_rule_id != rule_id:
                continue
            return {
                "rule_id": candidate_rule_id,
                "label": label,
                "find_text": find_text,
                "replace_text": replace_text,
            }
        return None

    def _audit_sanitize_entry_key(self, path_raw: str, uid: str) -> tuple[str, str]:
        return (str(Path(path_raw)), uid)

    def _is_audit_sanitize_entry_ignored(
        self,
        rule_id: str,
        path_raw: str,
        uid: str,
    ) -> bool:
        rule_set = self.audit_sanitize_ignored_entries_by_rule.get(rule_id)
        if not rule_set:
            return False
        return self._audit_sanitize_entry_key(path_raw, uid) in rule_set

    def _set_audit_sanitize_entry_ignored(
        self,
        rule_id: str,
        path_raw: str,
        uid: str,
        ignored: bool,
    ) -> None:
        key = self._audit_sanitize_entry_key(path_raw, uid)
        if ignored:
            rule_set = self.audit_sanitize_ignored_entries_by_rule.setdefault(
                rule_id, set())
            rule_set.add(key)
        else:
            rule_set = self.audit_sanitize_ignored_entries_by_rule.get(rule_id)
            if rule_set is None:
                return
            rule_set.discard(key)
            if not rule_set:
                self.audit_sanitize_ignored_entries_by_rule.pop(rule_id, None)
        self._invalidate_audit_caches()
        self._refresh_audit_sanitize_panel()

    def _on_audit_sanitize_rules_context_menu(self, pos: Any) -> None:
        if self.audit_sanitize_rules_list is None:
            return
        item = self.audit_sanitize_rules_list.itemAt(pos)
        if item is None:
            return
        row = self.audit_sanitize_rules_list.row(item)
        if row >= 0 and self.audit_sanitize_rules_list.currentRow() != row:
            self.audit_sanitize_rules_list.setCurrentRow(row)

        payload = self._audit_sanitize_rule_payload(item)
        if payload is None:
            return

        menu = QMenu(self.audit_sanitize_rules_list)
        apply_action = menu.addAction("Apply Rule")
        chosen = menu.exec(
            self.audit_sanitize_rules_list.viewport().mapToGlobal(pos))
        if chosen is apply_action:
            self._apply_audit_sanitize_rules([payload])
            return

    def _audit_sanitize_occurrence_payload(
        self, item: Optional[QListWidgetItem]
    ) -> Optional[dict[str, str]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        path_raw = payload.get("path")
        uid = payload.get("uid")
        rule_id = payload.get("rule_id")
        if (
            not isinstance(path_raw, str)
            or not path_raw
            or not isinstance(uid, str)
            or not uid
            or not isinstance(rule_id, str)
            or not rule_id
        ):
            return None
        return {
            "path": path_raw,
            "uid": uid,
            "rule_id": rule_id,
        }

    def _audit_sanitize_occurrence_view_key_from_item(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[tuple[int, str, str]]:
        if item is None:
            return None
        raw_key = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(raw_key, (tuple, list)) or len(raw_key) != 3:
            return None
        generation_raw, scope_raw, rule_id_raw = raw_key
        if (
            not isinstance(generation_raw, int)
            or not isinstance(scope_raw, str)
            or not isinstance(rule_id_raw, str)
        ):
            return None
        return (generation_raw, scope_raw, rule_id_raw)

    def _set_audit_sanitize_occurrence_view_visibility(
        self,
        view_key: Optional[tuple[int, str, str]],
    ) -> None:
        if self.audit_sanitize_occurrences_list is None:
            return
        first_visible_row = -1
        for row in range(self.audit_sanitize_occurrences_list.count()):
            item = self.audit_sanitize_occurrences_list.item(row)
            item_key = self._audit_sanitize_occurrence_view_key_from_item(item)
            visible = view_key is not None and item_key == view_key
            item.setHidden(not visible)
            if visible and first_visible_row < 0:
                first_visible_row = row
        if first_visible_row >= 0:
            self.audit_sanitize_occurrences_list.setCurrentRow(
                first_visible_row)
            if self.audit_sanitize_goto_btn is not None:
                self.audit_sanitize_goto_btn.setEnabled(True)
        else:
            if self.audit_sanitize_occurrences_list.currentRow() >= 0:
                self.audit_sanitize_occurrences_list.setCurrentRow(-1)
            if self.audit_sanitize_goto_btn is not None:
                self.audit_sanitize_goto_btn.setEnabled(False)
        self.audit_sanitize_active_view_key = view_key

    def _on_audit_sanitize_occurrences_context_menu(self, pos: Any) -> None:
        if self.audit_sanitize_occurrences_list is None:
            return
        item = self.audit_sanitize_occurrences_list.itemAt(pos)
        if item is None:
            return
        row = self.audit_sanitize_occurrences_list.row(item)
        if row >= 0 and self.audit_sanitize_occurrences_list.currentRow() != row:
            self.audit_sanitize_occurrences_list.setCurrentRow(row)

        payload = self._audit_sanitize_occurrence_payload(item)
        if payload is None:
            return
        rule_payload = self._audit_sanitize_rule_payload_by_id(
            payload["rule_id"])
        if rule_payload is None:
            return

        ignored = self._is_audit_sanitize_entry_ignored(
            payload["rule_id"],
            payload["path"],
            payload["uid"],
        )
        menu = QMenu(self.audit_sanitize_occurrences_list)
        go_to_action = menu.addAction("Go To")
        apply_entry_action = menu.addAction("Apply Rule To Entry")
        menu.addSeparator()
        toggle_ignore_action = menu.addAction(
            "Unignore Entry" if ignored else "Ignore Entry"
        )
        chosen = menu.exec(
            self.audit_sanitize_occurrences_list.viewport().mapToGlobal(pos))
        if chosen is go_to_action:
            self._go_to_selected_audit_sanitize_occurrence()
            return
        if chosen is apply_entry_action:
            self._apply_audit_sanitize_rule_to_entry(
                rule_payload,
                payload["path"],
                payload["uid"],
            )
            return
        if chosen is toggle_ignore_action:
            self._set_audit_sanitize_entry_ignored(
                payload["rule_id"],
                payload["path"],
                payload["uid"],
                not ignored,
            )
            self.statusBar().showMessage(
                "Entry unignored." if ignored else "Entry ignored."
            )

    def _apply_audit_sanitize_payload(
        self,
        generation: int,
        scope: str,
        selected_rule_id: str,
        selected_find_text: str,
        payload: dict[str, Any],
    ) -> None:
        if (
            self.audit_sanitize_rules_list is None
            or self.audit_sanitize_summary_label is None
            or self.audit_sanitize_occurrences_list is None
            or self.audit_sanitize_goto_btn is None
        ):
            return

        counts = cast(dict[str, int], payload.get("counts", {}))
        total_hits_all_rules = 0
        rules_with_hits = 0
        for row in range(self.audit_sanitize_rules_list.count()):
            item = self.audit_sanitize_rules_list.item(row)
            rule_payload = self._audit_sanitize_rule_payload(item)
            if rule_payload is None:
                continue
            hits = int(counts.get(rule_payload["rule_id"], 0))
            total_hits_all_rules += hits
            if hits > 0:
                rules_with_hits += 1
            item.setText(f"{rule_payload['label']} | hits: {hits}")

        self.audit_sanitize_total_hits = total_hits_all_rules
        self.audit_sanitize_rules_with_hits = rules_with_hits
        self.audit_sanitize_counts_cache_key = (generation, scope)
        self.audit_sanitize_counts_cache = dict(counts)

        prefix = (
            f"Potential replacements: {total_hits_all_rules} across "
            f"{rules_with_hits}/{len(SANITIZE_CHAR_RULES)} rules."
        )
        view_key = (generation, scope, selected_rule_id)
        if not selected_rule_id or not selected_find_text:
            self.audit_sanitize_summary_label.setText(prefix)
            self._set_audit_sanitize_occurrence_view_visibility(None)
            self.audit_sanitize_displayed_key = view_key
            self.audit_sanitize_display_complete = True
            self._hide_audit_progress_overlay(
                self.audit_sanitize_progress_overlay)
            return

        records = list(cast(list[dict[str, Any]], payload.get("records", [])))
        total_hits = int(payload.get("total_hits", 0))
        entries = int(payload.get("entries", 0))
        block_count = int(payload.get("block_count", len(records)))
        self.audit_sanitize_occurrence_cache_key = (
            generation, scope, selected_rule_id)
        self.audit_sanitize_occurrence_cache_payload = {
            "records": list(records),
            "total_hits": total_hits,
            "entries": entries,
            "block_count": block_count,
        }
        self.audit_sanitize_occurrence_cache_by_key[
            view_key
        ] = cast(dict[str, Any], dict(self.audit_sanitize_occurrence_cache_payload))
        if block_count <= 0:
            self.audit_sanitize_summary_label.setText(
                f"{prefix} Selected rule: 0 hits in 0 lines across 0 blocks."
            )
            self._set_audit_sanitize_occurrence_view_visibility(None)
            self.audit_sanitize_displayed_key = view_key
            self.audit_sanitize_display_complete = True
            self._hide_audit_progress_overlay(
                self.audit_sanitize_progress_overlay)
            return

        if view_key in self.audit_sanitize_built_view_keys:
            line_label = "line" if entries == 1 else "lines"
            block_label = "block" if block_count == 1 else "blocks"
            self.audit_sanitize_summary_label.setText(
                f"{prefix} Selected rule: {total_hits} hits in {entries} {line_label} across {block_count} {block_label}."
            )
            self._set_audit_sanitize_occurrence_view_visibility(view_key)
            self.audit_sanitize_displayed_key = view_key
            self.audit_sanitize_display_complete = True
            self._hide_audit_progress_overlay(
                self.audit_sanitize_progress_overlay)
            return

        line_label = "line" if entries == 1 else "lines"
        block_label = "block" if block_count == 1 else "blocks"
        self.audit_sanitize_summary_label.setText(
            f"{prefix} Selected rule: {total_hits} hits in {entries} {line_label} across {block_count} {block_label}."
        )
        self._set_audit_progress_overlay(
            self.audit_sanitize_occurrences_list,
            self.audit_sanitize_progress_overlay,
            f"Rendering 0/{block_count}",
        )
        self.audit_sanitize_render_records = records
        self.audit_sanitize_render_index = 0
        self.audit_sanitize_render_generation = generation
        self.audit_sanitize_render_scope = scope
        self.audit_sanitize_render_rule_id = selected_rule_id
        self.audit_sanitize_render_find_text = selected_find_text
        self.audit_sanitize_render_show_field_label = scope == "both"
        self.audit_sanitize_render_total_hits = total_hits
        self.audit_sanitize_render_entries = entries
        self.audit_sanitize_render_block_count = block_count
        self.audit_sanitize_display_complete = False
        self._set_audit_sanitize_occurrence_view_visibility(None)
        self.audit_sanitize_active_view_key = view_key
        self._render_next_audit_sanitize_occurrence_batch()

    def _refresh_audit_sanitize_panel(self) -> None:
        if (
            self.audit_sanitize_rules_list is None
            or self.audit_sanitize_summary_label is None
            or self.audit_sanitize_occurrences_list is None
            or self.audit_sanitize_goto_btn is None
        ):
            return
        selected_payload = self._audit_sanitize_rule_payload(
            self.audit_sanitize_rules_list.currentItem()
        )
        if self.audit_sanitize_apply_selected_btn is not None:
            self.audit_sanitize_apply_selected_btn.setEnabled(
                selected_payload is not None)

        scope = self._audit_sanitize_scope()
        selected_rule_id = selected_payload["rule_id"] if selected_payload is not None else ""
        selected_find_text = selected_payload["find_text"] if selected_payload is not None else ""
        requested_key = (self.audit_cache_generation, scope, selected_rule_id)
        if (
            self.audit_sanitize_display_complete
            and self.audit_sanitize_displayed_key == requested_key
        ):
            self._hide_audit_progress_overlay(
                self.audit_sanitize_progress_overlay)
            return

        self._stop_audit_sanitize_render()
        self.audit_sanitize_display_complete = False
        self.audit_sanitize_displayed_key = None

        counts_key = (self.audit_cache_generation, scope)
        occurrence_key = (
            (self.audit_cache_generation, scope, selected_rule_id)
            if selected_rule_id
            else None
        )
        counts_cached = (
            self.audit_sanitize_counts_cache_key == counts_key
            and bool(self.audit_sanitize_counts_cache)
        )
        occurrence_cached_payload: Optional[dict[str, Any]] = None
        if occurrence_key is not None:
            cached = self.audit_sanitize_occurrence_cache_by_key.get(
                occurrence_key)
            if isinstance(cached, dict):
                occurrence_cached_payload = cached
            elif (
                self.audit_sanitize_occurrence_cache_key == occurrence_key
                and isinstance(self.audit_sanitize_occurrence_cache_payload, dict)
            ):
                occurrence_cached_payload = self.audit_sanitize_occurrence_cache_payload
        occurrence_cached = occurrence_cached_payload is not None
        if counts_cached and (not selected_rule_id or occurrence_cached):
            cached_payload: dict[str, Any] = {
                "counts": dict(self.audit_sanitize_counts_cache)}
            if selected_rule_id and occurrence_cached:
                cached_payload.update(
                    cast(dict[str, Any], occurrence_cached_payload))
            self._apply_audit_sanitize_payload(
                generation=self.audit_cache_generation,
                scope=scope,
                selected_rule_id=selected_rule_id,
                selected_find_text=selected_find_text,
                payload=cached_payload,
            )
            return

        request: dict[str, Any] = {
            "generation": self.audit_cache_generation,
            "scope": scope,
            "selected_rule_id": selected_rule_id,
            "selected_find_text": selected_find_text,
            "path_sessions": self._audit_path_sessions_snapshot(),
        }
        if counts_cached and selected_rule_id:
            request["mode"] = "occurrences"
            request["selected_ignored"] = set(
                self.audit_sanitize_ignored_entries_by_rule.get(
                    selected_rule_id, set())
            )
            self.audit_sanitize_summary_label.setText(
                "Scanning selected rule...")
        else:
            request["mode"] = "full"
            request["ignored_entries_by_rule"] = {
                rule_id: set(keys)
                for rule_id, keys in self.audit_sanitize_ignored_entries_by_rule.items()
            }
            self.audit_sanitize_summary_label.setText(
                "Scanning sanitize results...")
        self._queue_audit_sanitize_worker(request)

    def _refresh_audit_sanitize_occurrences(self) -> None:
        self._refresh_audit_sanitize_panel()

    def _render_next_audit_sanitize_occurrence_batch(self) -> None:
        try:
            if (
                self.audit_sanitize_occurrences_list is None
                or self.audit_sanitize_goto_btn is None
            ):
                self._stop_audit_sanitize_render()
                return
            records = self.audit_sanitize_render_records
            total_blocks = len(records)
            if total_blocks <= 0:
                self._stop_audit_sanitize_render()
                return
            start = self.audit_sanitize_render_index
            end = min(start + self.audit_result_batch_size, total_blocks)
            prev_updates = self.audit_sanitize_occurrences_list.updatesEnabled()
            self.audit_sanitize_occurrences_list.setUpdatesEnabled(False)
            try:
                for record in records[start:end]:
                    self._add_audit_sanitize_occurrence_result(
                        path=cast(Path, record["path"]),
                        uid=str(record["uid"]),
                        rule_id=self.audit_sanitize_render_rule_id,
                        entry_text=str(record["entry_text"]),
                        occurrences=cast(
                            list[dict[str, Any]], record["occurrences"]),
                        find_text=self.audit_sanitize_render_find_text,
                        show_field_label=self.audit_sanitize_render_show_field_label,
                        view_key=(
                            self.audit_sanitize_render_generation,
                            self.audit_sanitize_render_scope,
                            self.audit_sanitize_render_rule_id,
                        ),
                    )
            finally:
                self.audit_sanitize_occurrences_list.setUpdatesEnabled(
                    prev_updates)
            self.audit_sanitize_render_index = end
            if self.audit_sanitize_summary_label is not None:
                prefix = (
                    f"Potential replacements: {self.audit_sanitize_total_hits} across "
                    f"{self.audit_sanitize_rules_with_hits}/{len(SANITIZE_CHAR_RULES)} rules."
                )
                line_label = (
                    "line"
                    if self.audit_sanitize_render_entries == 1
                    else "lines"
                )
                block_label = (
                    "block"
                    if self.audit_sanitize_render_block_count == 1
                    else "blocks"
                )
                self.audit_sanitize_summary_label.setText(
                    f"{prefix} Selected rule: {self.audit_sanitize_render_total_hits} hits in "
                    f"{self.audit_sanitize_render_entries} {line_label} across {self.audit_sanitize_render_block_count} {block_label}."
                )
            if end < total_blocks:
                self._set_audit_progress_overlay(
                    self.audit_sanitize_occurrences_list,
                    self.audit_sanitize_progress_overlay,
                    f"Rendering {end}/{total_blocks}",
                )
                self.audit_sanitize_render_timer.start(
                    self.audit_render_batch_interval_ms)
                return
            rendered_view_key = (
                self.audit_sanitize_render_generation,
                self.audit_sanitize_render_scope,
                self.audit_sanitize_render_rule_id,
            )
            self.audit_sanitize_built_view_keys.add(rendered_view_key)
            self._set_audit_sanitize_occurrence_view_visibility(
                rendered_view_key)
            self.audit_sanitize_displayed_key = rendered_view_key
            self.audit_sanitize_display_complete = True
            self._stop_audit_sanitize_render()
        except Exception as exc:
            self._stop_audit_sanitize_render()
            if self.audit_sanitize_summary_label is not None:
                self.audit_sanitize_summary_label.setText(
                    f"Sanitize render failed: {exc}")

    def _go_to_selected_audit_sanitize_occurrence(self) -> None:
        if self.audit_sanitize_occurrences_list is None:
            return
        item = self.audit_sanitize_occurrences_list.currentItem()
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
