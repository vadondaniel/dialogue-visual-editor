from __future__ import annotations

import html
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import preview_text, strip_control_tokens


class _AuditNameConsistencyHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditNameConsistencyMixin(_AuditNameConsistencyHostTypingFallback):
    def _replace_name_consistency_case_insensitive(
        self,
        text: str,
        source: str,
        target: str,
    ) -> tuple[str, int]:
        if not text or not source:
            return text, 0
        pattern = re.compile(re.escape(source), flags=re.IGNORECASE)
        return pattern.subn(target, text)

    def _name_consistency_plain_text(self, value: str) -> str:
        plain_resolver = getattr(self, "_plain_text_for_suggestions", None)
        if callable(plain_resolver):
            try:
                resolved = plain_resolver(value)
            except Exception:
                resolved = ""
            if isinstance(resolved, str):
                return resolved
        base = strip_control_tokens(value or "").replace("\u3000", " ")
        return re.sub(r"\s+", " ", base).strip()

    def _name_consistency_entry_label(
        self,
        session: FileSession,
        segment: DialogueSegment,
        block_index: int,
    ) -> str:
        entry_resolver = getattr(self, "_audit_entry_text_for_segment", None)
        if callable(entry_resolver):
            return str(entry_resolver(session, segment, block_index))
        if not self._is_name_index_session(session):
            return f"Block {block_index}"
        name_index_label = self._name_index_label(session)
        actor_id = self._actor_id_from_uid(segment.uid)
        if actor_id is not None:
            return f"{name_index_label} ID {actor_id}"
        return f"{name_index_label} {block_index}"

    def _audit_name_consistency_group_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _audit_name_consistency_entry_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _first_non_empty_line_pair(
        self,
        source_lines: list[str],
        target_lines: list[str],
    ) -> tuple[str, str]:
        max_len = max(len(source_lines), len(target_lines))
        for idx in range(max_len):
            source_raw = source_lines[idx] if idx < len(source_lines) else ""
            target_raw = target_lines[idx] if idx < len(target_lines) else ""
            source_line = source_raw if isinstance(source_raw, str) else ""
            target_line = target_raw if isinstance(target_raw, str) else ""
            if source_line.strip():
                return source_line, target_line
        return "", ""

    def _collect_misc_glossary_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        field_resolver = getattr(self, "_name_index_field_from_uid", None)
        for path, session in self._audit_path_sessions_snapshot():
            if not self._is_name_index_session(session):
                continue
            for block_index, segment in enumerate(session.segments, start=1):
                if segment.segment_kind != "name_index":
                    continue
                field_name = "name"
                if callable(field_resolver):
                    try:
                        resolved_field = field_resolver(segment.uid)
                    except Exception:
                        resolved_field = "name"
                    if isinstance(resolved_field, str) and resolved_field.strip():
                        field_name = resolved_field.strip().lower()
                if field_name != "name":
                    continue
                source_lines = self._segment_source_lines_for_display(segment)
                tl_lines = self._normalize_translation_lines(segment.translation_lines)
                if not isinstance(source_lines, list) or not source_lines:
                    continue
                if not isinstance(tl_lines, list):
                    tl_lines = [""]
                source_line, expected_line = self._first_non_empty_line_pair(
                    source_lines,
                    tl_lines,
                )
                source_term = self._name_consistency_plain_text(source_line)
                expected_tl = self._name_consistency_plain_text(expected_line)
                if not source_term or not expected_tl:
                    continue
                key = (
                    source_term.casefold(),
                    expected_tl.casefold(),
                    str(path),
                    segment.uid,
                )
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    {
                        "source_term": source_term,
                        "expected_tl": expected_tl,
                        "misc_path": str(path),
                        "misc_uid": segment.uid,
                        "misc_entry": self._name_consistency_entry_label(
                            session, segment, block_index
                        ),
                        "misc_context": (
                            segment.context if isinstance(segment.context, str) else str(path)
                        ),
                    }
                )
        return entries

    def _collect_dialogue_rows(self, dialogue_only: bool) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path, session in self._audit_path_sessions_snapshot():
            if self._is_name_index_session(session):
                continue
            for block_index, segment in enumerate(session.segments, start=1):
                if dialogue_only and not bool(getattr(segment, "is_structural_dialogue", False)):
                    continue
                source_lines = self._segment_source_lines_for_display(segment)
                tl_lines = self._normalize_translation_lines(segment.translation_lines)
                if not isinstance(source_lines, list) or not source_lines:
                    continue
                if not isinstance(tl_lines, list):
                    tl_lines = [""]
                source_block = "\n".join(
                    line if isinstance(line, str) else "" for line in source_lines
                )
                tl_block = "\n".join(
                    line if isinstance(line, str) else "" for line in tl_lines
                )
                source_fold = self._name_consistency_plain_text(source_block).casefold()
                if not source_fold:
                    continue
                tl_fold = self._name_consistency_plain_text(tl_block).casefold()
                line_rows: list[tuple[int, str, str]] = []
                max_len = max(len(source_lines), len(tl_lines))
                for line_index in range(max_len):
                    source_raw = source_lines[line_index] if line_index < len(source_lines) else ""
                    source_line = source_raw if isinstance(source_raw, str) else ""
                    source_line_fold = self._name_consistency_plain_text(source_line).casefold()
                    line_rows.append((line_index + 1, source_line, source_line_fold))
                rows.append(
                    {
                        "path": str(path),
                        "uid": segment.uid,
                        "entry": self._name_consistency_entry_label(session, segment, block_index),
                        "source_block": source_block,
                        "source_block_fold": source_fold,
                        "tl_block": tl_block,
                        "tl_block_fold": tl_fold,
                        "source_line_rows": line_rows,
                    }
                )
        return rows

    def _first_matching_dialogue_line(
        self,
        line_rows: list[tuple[int, str, str]],
        source_term_fold: str,
    ) -> tuple[int, str]:
        for line_index, source_line, source_line_fold in line_rows:
            if source_term_fold in source_line_fold:
                return line_index, source_line
        if not line_rows:
            return 0, ""
        line_index, source_line, _source_line_fold = line_rows[0]
        return line_index, source_line

    def _collect_audit_name_consistency_groups(
        self,
        dialogue_only: bool,
        only_discrepancies: bool = True,
        filter_text: str = "",
        sort_mode: str = "hits_desc",
    ) -> list[dict[str, Any]]:
        glossary_entries = self._collect_misc_glossary_entries()
        if not glossary_entries:
            return []
        dialogue_rows = self._collect_dialogue_rows(dialogue_only=dialogue_only)
        if not dialogue_rows:
            return []
        filter_fold = filter_text.strip().casefold()
        groups: list[dict[str, Any]] = []
        for glossary_entry in glossary_entries:
            source_term = str(glossary_entry.get("source_term", ""))
            expected_tl = str(glossary_entry.get("expected_tl", ""))
            misc_context = str(glossary_entry.get("misc_context", ""))
            misc_path = str(glossary_entry.get("misc_path", ""))
            misc_entry = str(glossary_entry.get("misc_entry", ""))
            source_term_fold = source_term.casefold()
            expected_tl_fold = expected_tl.casefold()
            if not source_term_fold or not expected_tl_fold:
                continue
            if filter_fold:
                combined = " ".join(
                    (
                        source_term,
                        expected_tl,
                        misc_context,
                        misc_path,
                        misc_entry,
                    )
                ).casefold()
                if filter_fold not in combined:
                    continue

            checked_count = 0
            mismatch_entries: list[dict[str, Any]] = []
            for row in dialogue_rows:
                source_block_fold = str(row.get("source_block_fold", ""))
                if source_term_fold not in source_block_fold:
                    continue
                checked_count += 1
                tl_block_fold = str(row.get("tl_block_fold", ""))
                if expected_tl_fold in tl_block_fold:
                    continue
                line_rows = row.get("source_line_rows")
                lines = line_rows if isinstance(line_rows, list) else []
                line_index, source_line = self._first_matching_dialogue_line(
                    lines,
                    source_term_fold,
                )
                mismatch_entries.append(
                    {
                        "path": str(row.get("path", "")),
                        "uid": str(row.get("uid", "")),
                        "entry": str(row.get("entry", "Entry")),
                        "line_index": line_index,
                        "source_line": source_line,
                        "translation_block": str(row.get("tl_block", "")),
                        "source_term": source_term,
                        "expected_tl": expected_tl,
                        "misc_context": misc_context,
                        "misc_entry": misc_entry,
                    }
                )
            if checked_count <= 0:
                continue
            if only_discrepancies and not mismatch_entries:
                continue
            groups.append(
                {
                    "source_term": source_term,
                    "expected_tl": expected_tl,
                    "misc_context": misc_context,
                    "misc_path": misc_path,
                    "misc_uid": str(glossary_entry.get("misc_uid", "")),
                    "misc_entry": misc_entry,
                    "checked_count": checked_count,
                    "entry_count": len(mismatch_entries),
                    "has_discrepancy": bool(mismatch_entries),
                    "entries": mismatch_entries,
                }
            )

        if sort_mode == "source_az":
            groups.sort(
                key=lambda row: (
                    str(row.get("source_term", "")).casefold(),
                    -int(row.get("entry_count", 0)),
                )
            )
        elif sort_mode == "source_za":
            groups.sort(
                key=lambda row: (
                    str(row.get("source_term", "")).casefold(),
                    int(row.get("entry_count", 0)),
                ),
                reverse=True,
            )
        elif sort_mode == "checked_desc":
            groups.sort(
                key=lambda row: (
                    -int(row.get("checked_count", 0)),
                    -int(row.get("entry_count", 0)),
                    str(row.get("source_term", "")).casefold(),
                )
            )
        elif sort_mode == "path_az":
            groups.sort(
                key=lambda row: (
                    str(row.get("misc_path", "")).casefold(),
                    str(row.get("source_term", "")).casefold(),
                )
            )
        else:
            groups.sort(
                key=lambda row: (
                    -int(row.get("entry_count", 0)),
                    -int(row.get("checked_count", 0)),
                    str(row.get("source_term", "")).casefold(),
                )
            )
        return groups

    def _highlight_term_html(self, text: str, term: str) -> str:
        source_text = text or ""
        if not source_text:
            return "<i>(empty)</i>"
        if not term:
            return html.escape(source_text).replace("\n", "<br>")
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        spans = [match.span() for match in pattern.finditer(source_text)]
        if not spans:
            return html.escape(source_text).replace("\n", "<br>")
        highlight_style = self._audit_highlight_style()
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
        return "".join(parts).replace("\n", "<br>")

    def _add_name_consistency_entry_item(
        self,
        entry: dict[str, Any],
    ) -> None:
        if self.audit_name_consistency_entries_list is None:
            return
        path_raw = entry.get("path")
        uid_raw = entry.get("uid")
        if not isinstance(path_raw, str) or not path_raw:
            return
        if not isinstance(uid_raw, str) or not uid_raw:
            return
        entry_label = entry.get("entry")
        line_index = entry.get("line_index")
        source_line = entry.get("source_line")
        tl_block = entry.get("translation_block")
        source_term = entry.get("source_term")
        if not isinstance(entry_label, str):
            entry_label = "Entry"
        line_no = int(line_index) if isinstance(line_index, int) else 0
        source_text = source_line if isinstance(source_line, str) else ""
        tl_text = tl_block if isinstance(tl_block, str) else ""
        source_term_text = source_term if isinstance(source_term, str) else ""
        relative = self._relative_path(Path(path_raw))

        item = QListWidgetItem()
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "path": path_raw,
                "uid": uid_raw,
            },
        )
        self.audit_name_consistency_entries_list.addItem(item)

        body = QLabel()
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        body.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        body.setText(
            "<div style=\"padding:4px 0;\">"
            f"<b>{html.escape(relative)} | {html.escape(entry_label)} | line {line_no}</b><br>"
            f"<b>JP:</b> {self._highlight_term_html(preview_text(source_text, 120), source_term_text)}<br>"
            f"<b>TL:</b> {html.escape(preview_text(tl_text if tl_text else '(empty)', 120)).replace(chr(10), '<br>')}"
            "</div>"
        )
        item.setSizeHint(body.sizeHint())
        self.audit_name_consistency_entries_list.setItemWidget(item, body)

    def _refresh_audit_name_consistency_entries(self) -> None:
        if (
            self.audit_name_consistency_groups_list is None
            or self.audit_name_consistency_entries_list is None
            or self.audit_name_consistency_goto_btn is None
        ):
            return
        payload = self._audit_name_consistency_group_payload(
            self.audit_name_consistency_groups_list.currentItem()
        )
        self.audit_name_consistency_entries_list.clear()
        self.audit_name_consistency_goto_btn.setEnabled(False)
        if payload is None:
            return
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return
        for entry in entries:
            if isinstance(entry, dict):
                self._add_name_consistency_entry_item(entry)
        if self.audit_name_consistency_entries_list.count() > 0:
            self.audit_name_consistency_entries_list.setCurrentRow(0)
            self.audit_name_consistency_goto_btn.setEnabled(True)

    def _refresh_audit_name_consistency_replace_state(self) -> None:
        if (
            self.audit_name_consistency_replace_btn is None
            or self.audit_name_consistency_replace_find_edit is None
            or self.audit_name_consistency_groups_list is None
        ):
            return
        payload = self._audit_name_consistency_group_payload(
            self.audit_name_consistency_groups_list.currentItem()
        )
        find_text = self.audit_name_consistency_replace_find_edit.text().strip()
        expected_tl = ""
        if payload is not None:
            expected_raw = payload.get("expected_tl")
            if isinstance(expected_raw, str):
                expected_tl = expected_raw.strip()
        can_apply = bool(payload is not None and find_text and expected_tl)
        self.audit_name_consistency_replace_btn.setEnabled(can_apply)

    def _refresh_audit_name_consistency_misc_go_state(self) -> None:
        if (
            self.audit_name_consistency_goto_misc_btn is None
            or self.audit_name_consistency_groups_list is None
        ):
            return
        payload = self._audit_name_consistency_group_payload(
            self.audit_name_consistency_groups_list.currentItem()
        )
        path_raw = payload.get("misc_path") if payload is not None else ""
        uid_raw = payload.get("misc_uid") if payload is not None else ""
        can_go = (
            isinstance(path_raw, str)
            and bool(path_raw)
            and isinstance(uid_raw, str)
            and bool(uid_raw)
        )
        self.audit_name_consistency_goto_misc_btn.setEnabled(can_go)

    def _apply_audit_name_consistency_replace_in_hits(self) -> None:
        if (
            self.audit_name_consistency_groups_list is None
            or self.audit_name_consistency_replace_find_edit is None
            or self.audit_name_consistency_replace_btn is None
        ):
            return
        payload = self._audit_name_consistency_group_payload(
            self.audit_name_consistency_groups_list.currentItem()
        )
        if payload is None:
            self.statusBar().showMessage("Select a mismatch group first.")
            self._refresh_audit_name_consistency_replace_state()
            return
        find_text = self.audit_name_consistency_replace_find_edit.text().strip()
        if not find_text:
            self.statusBar().showMessage("Enter the current TL term in 'Seen as'.")
            self._refresh_audit_name_consistency_replace_state()
            return
        expected_raw = payload.get("expected_tl")
        expected_tl = expected_raw.strip() if isinstance(expected_raw, str) else ""
        if not expected_tl:
            self.statusBar().showMessage("Expected glossary translation is empty.")
            self._refresh_audit_name_consistency_replace_state()
            return
        if find_text.casefold() == expected_tl.casefold():
            self.statusBar().showMessage("'Seen as' already matches expected glossary TL.")
            self._refresh_audit_name_consistency_replace_state()
            return

        entries_raw = payload.get("entries")
        entries = entries_raw if isinstance(entries_raw, list) else []
        if not entries:
            self.statusBar().showMessage("Selected group has no dialogue hits.")
            self._refresh_audit_name_consistency_replace_state()
            return

        touched_paths: set[Path] = set()
        changed_blocks = 0
        replaced_total = 0
        processed: set[tuple[str, str]] = set()
        touched_current = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path_raw = entry.get("path")
            uid_raw = entry.get("uid")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            if not isinstance(uid_raw, str) or not uid_raw:
                continue
            key = (path_raw, uid_raw)
            if key in processed:
                continue
            processed.add(key)
            path = Path(path_raw)
            session = self.sessions.get(path)
            if session is None:
                continue
            target_segment: Optional[DialogueSegment] = None
            for segment in session.segments:
                if segment.uid == uid_raw:
                    target_segment = segment
                    break
            if target_segment is None:
                continue
            current_lines = self._normalize_translation_lines(
                target_segment.translation_lines
            )
            next_lines: list[str] = []
            block_replacements = 0
            for line in current_lines:
                replaced_line, count = self._replace_name_consistency_case_insensitive(
                    line,
                    find_text,
                    expected_tl,
                )
                next_lines.append(replaced_line)
                block_replacements += count
            if block_replacements <= 0:
                continue
            target_segment.translation_lines = list(next_lines)
            changed_blocks += 1
            replaced_total += block_replacements
            touched_paths.add(path)
            if self.current_path is not None and path == self.current_path:
                touched_current = True

        if changed_blocks <= 0:
            self.statusBar().showMessage(
                f"No replaceable '{find_text}' occurrences found in selected hits."
            )
            self._refresh_audit_name_consistency_replace_state()
            return

        for path in touched_paths:
            session = self.sessions.get(path)
            if session is not None:
                self._refresh_dirty_state(session)

        self._invalidate_audit_caches()
        self._refresh_audit_sanitize_panel()
        self._refresh_audit_control_mismatch_panel()
        if touched_current and self.current_path is not None:
            current_session = self.sessions.get(self.current_path)
            if current_session is not None:
                self._render_session(
                    current_session,
                    focus_uid=self.selected_segment_uid,
                    preserve_scroll=True,
                )
        else:
            self._refresh_translator_detail_panel()
        self._refresh_audit_name_consistency_panel()
        self.audit_name_consistency_replace_find_edit.setText("")
        self.statusBar().showMessage(
            f"Replaced '{find_text}' -> '{expected_tl}' in {changed_blocks} blocks ({replaced_total} matches)."
        )

    def _refresh_audit_name_consistency_panel(self) -> None:
        if (
            self.audit_name_consistency_dialogue_only_check is None
            or self.audit_name_consistency_only_discrepancy_check is None
            or self.audit_name_consistency_groups_list is None
            or self.audit_name_consistency_status_label is None
        ):
            return
        dialogue_only = self.audit_name_consistency_dialogue_only_check.isChecked()
        only_discrepancies = self.audit_name_consistency_only_discrepancy_check.isChecked()
        filter_text = ""
        if self.audit_name_consistency_filter_edit is not None:
            filter_text = self.audit_name_consistency_filter_edit.text()
        sort_mode = "hits_desc"
        if self.audit_name_consistency_sort_combo is not None:
            sort_data = self.audit_name_consistency_sort_combo.currentData()
            if isinstance(sort_data, str) and sort_data.strip():
                sort_mode = sort_data

        groups = self._collect_audit_name_consistency_groups(
            dialogue_only=dialogue_only,
            only_discrepancies=only_discrepancies,
            filter_text=filter_text,
            sort_mode=sort_mode,
        )
        self.audit_name_consistency_groups_list.clear()
        total_hits = 0
        total_checked = 0
        groups_with_discrepancy = 0
        for group in groups:
            source_term = str(group.get("source_term", ""))
            expected_tl = str(group.get("expected_tl", ""))
            hit_count = int(group.get("entry_count", 0))
            checked_count = int(group.get("checked_count", 0))
            misc_context = str(group.get("misc_context", ""))
            total_hits += hit_count
            total_checked += checked_count
            if bool(group.get("has_discrepancy", False)):
                groups_with_discrepancy += 1
            label = (
                f"miss {hit_count}/{checked_count} | "
                f"{preview_text(source_term, 48)} -> {preview_text(expected_tl, 48)} | "
                f"{preview_text(misc_context, 56)}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.audit_name_consistency_groups_list.addItem(item)
        if groups:
            self.audit_name_consistency_groups_list.setCurrentRow(0)
            if only_discrepancies:
                self.audit_name_consistency_status_label.setText(
                    f"Glossary consistency issues: {len(groups)} | Missing lines: {total_hits} | Checked lines: {total_checked}"
                )
            else:
                self.audit_name_consistency_status_label.setText(
                    f"Glossary terms: {len(groups)} | Terms with misses: {groups_with_discrepancy} | Missing lines: {total_hits} | Checked lines: {total_checked}"
                )
        else:
            self.audit_name_consistency_status_label.setText(
                "No glossary consistency issues found between misc entries and dialogue translations."
            )
        self._refresh_audit_name_consistency_entries()
        self._refresh_audit_name_consistency_replace_state()
        self._refresh_audit_name_consistency_misc_go_state()

    def _go_to_selected_audit_name_consistency_entry(self) -> None:
        if self.audit_name_consistency_entries_list is None:
            return
        payload = self._audit_name_consistency_entry_payload(
            self.audit_name_consistency_entries_list.currentItem()
        )
        if payload is None:
            return
        path_raw = payload.get("path")
        uid_raw = payload.get("uid")
        if not isinstance(path_raw, str) or not path_raw:
            return
        if not isinstance(uid_raw, str) or not uid_raw:
            return
        self._jump_to_audit_location(path_raw, uid_raw)

    def _go_to_selected_audit_name_consistency_misc(self) -> None:
        if self.audit_name_consistency_groups_list is None:
            return
        payload = self._audit_name_consistency_group_payload(
            self.audit_name_consistency_groups_list.currentItem()
        )
        if payload is None:
            return
        path_raw = payload.get("misc_path")
        uid_raw = payload.get("misc_uid")
        if not isinstance(path_raw, str) or not path_raw:
            return
        if not isinstance(uid_raw, str) or not uid_raw:
            return
        self._jump_to_audit_location(path_raw, uid_raw)
