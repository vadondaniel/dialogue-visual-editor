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
            if checked_count <= 0 or not mismatch_entries:
                continue
            groups.append(
                {
                    "source_term": source_term,
                    "expected_tl": expected_tl,
                    "misc_context": misc_context,
                    "misc_path": misc_path,
                    "misc_entry": misc_entry,
                    "checked_count": checked_count,
                    "entry_count": len(mismatch_entries),
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

    def _refresh_audit_name_consistency_panel(self) -> None:
        if (
            self.audit_name_consistency_dialogue_only_check is None
            or self.audit_name_consistency_groups_list is None
            or self.audit_name_consistency_status_label is None
        ):
            return
        dialogue_only = self.audit_name_consistency_dialogue_only_check.isChecked()
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
            filter_text=filter_text,
            sort_mode=sort_mode,
        )
        self.audit_name_consistency_groups_list.clear()
        total_hits = 0
        total_checked = 0
        for group in groups:
            source_term = str(group.get("source_term", ""))
            expected_tl = str(group.get("expected_tl", ""))
            hit_count = int(group.get("entry_count", 0))
            checked_count = int(group.get("checked_count", 0))
            misc_context = str(group.get("misc_context", ""))
            total_hits += hit_count
            total_checked += checked_count
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
            self.audit_name_consistency_status_label.setText(
                f"Glossary misses: {len(groups)} | Missing lines: {total_hits} | Checked lines: {total_checked}"
            )
        else:
            self.audit_name_consistency_status_label.setText(
                "No glossary misses found between misc entries and dialogue translations."
            )
        self._refresh_audit_name_consistency_entries()

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
