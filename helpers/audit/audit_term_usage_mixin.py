from __future__ import annotations

from collections import defaultdict
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import preview_text, strip_control_tokens


class _AuditTermUsageHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditTermUsageMixin(_AuditTermUsageHostTypingFallback):
    def _normalize_text_for_block_match(self, value: str) -> str:
        base = strip_control_tokens(value or "").replace("\u3000", " ")
        squashed = re.sub(r"\s+", "", base)
        return squashed.casefold()

    def _parse_audit_term_candidates(self, raw_text: str) -> list[str]:
        if not raw_text.strip():
            return []
        parts = re.split(r"[\n,;|]+", raw_text)
        cleaned: list[str] = []
        seen: set[str] = set()
        for part in parts:
            token = part.strip()
            if not token:
                continue
            folded = token.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            cleaned.append(token)
        cleaned.sort(key=lambda value: (-len(value), value.casefold()))
        return cleaned

    def _highlight_candidate_in_text(self, text: str, candidate: str) -> str:
        if not text or not candidate:
            return text
        lower_text = text.casefold()
        lower_candidate = candidate.casefold()
        start = lower_text.find(lower_candidate)
        if start < 0:
            return text
        end = start + len(candidate)
        if end > len(text):
            end = len(text)
        return f"{text[:start]}[[{text[start:end]}]]{text[end:]}"

    def _candidate_group_for_entry(
        self,
        entry: dict[str, Any],
        candidates: list[str],
    ) -> str:
        if not candidates:
            return "__all__"
        block_match_raw = entry.get("translation_block_match")
        block_match = block_match_raw if isinstance(block_match_raw, str) else ""
        for candidate in candidates:
            if self._normalize_text_for_block_match(candidate) in block_match:
                return candidate
        return "__unmatched__"

    def _audit_term_variant_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _audit_term_hit_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _audit_term_entry_label(
        self,
        session: FileSession,
        segment: DialogueSegment,
        block_index: int,
    ) -> str:
        if not self._is_name_index_session(session):
            return f"Block {block_index}"
        name_index_label = self._name_index_label(session)
        actor_id = self._actor_id_from_uid(segment.uid)
        if actor_id is not None:
            return f"{name_index_label} ID {actor_id}"
        return f"{name_index_label} {block_index}"

    def _collect_audit_term_hits(
        self,
        term: str,
        dialogue_only: bool,
    ) -> list[dict[str, Any]]:
        source_resolver = getattr(self, "_segment_source_lines_for_translation", None)
        tl_resolver = getattr(self, "_segment_translation_lines_for_translation", None)
        hits: list[dict[str, Any]] = []
        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            for block_index, segment in enumerate(session.segments, start=1):
                if dialogue_only and not bool(getattr(segment, "is_structural_dialogue", False)):
                    continue
                if callable(source_resolver):
                    source_lines = source_resolver(segment)
                else:
                    source_lines = self._segment_source_lines_for_display(segment)
                if callable(tl_resolver):
                    tl_lines = tl_resolver(segment)
                else:
                    tl_lines = self._normalize_translation_lines(segment.translation_lines)
                if not isinstance(source_lines, list) or not source_lines:
                    continue
                if not isinstance(tl_lines, list):
                    tl_lines = [""]
                tl_block_text = "\n".join(tl_lines)
                tl_block_match = self._normalize_text_for_block_match(tl_block_text)
                entry_label = self._audit_term_entry_label(session, segment, block_index)
                term_match = self._normalize_text_for_block_match(term)
                for line_index, source_line_raw in enumerate(source_lines):
                    source_line = source_line_raw if isinstance(source_line_raw, str) else ""
                    source_match = self._normalize_text_for_block_match(source_line)
                    if term_match and term_match not in source_match:
                        continue
                    line_tl_raw = tl_lines[line_index] if line_index < len(tl_lines) else ""
                    line_tl = line_tl_raw if isinstance(line_tl_raw, str) else ""
                    normalized_line_tl = line_tl.strip()
                    hits.append(
                        {
                            "path": str(path),
                            "uid": segment.uid,
                            "entry": entry_label,
                            "line_index": line_index + 1,
                            "source_line": source_line,
                            "translation_line": normalized_line_tl,
                            "translation_block_text": tl_block_text,
                            "translation_block_match": tl_block_match,
                        }
                    )
        return hits

    def _build_term_groups(
        self,
        hits: list[dict[str, Any]],
        candidates: list[str],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in hits:
            if not isinstance(entry, dict):
                continue
            group_key = self._candidate_group_for_entry(entry, candidates)
            grouped[group_key].append(entry)
        if not candidates:
            return [
                {
                    "group_key": "__all__",
                    "entries": grouped.get("__all__", []),
                    "entry_count": len(grouped.get("__all__", [])),
                }
            ]
        groups: list[dict[str, Any]] = []
        for key in candidates:
            entries = grouped.get(key, [])
            if entries:
                groups.append(
                    {
                        "group_key": key,
                        "entries": entries,
                        "entry_count": len(entries),
                    }
                )
        unmatched = grouped.get("__unmatched__", [])
        if unmatched:
            groups.append(
                {
                    "group_key": "__unmatched__",
                    "entries": unmatched,
                    "entry_count": len(unmatched),
                }
            )
        return groups

    def _refresh_audit_term_hits(self) -> None:
        if (
            self.audit_term_variants_list is None
            or self.audit_term_hits_list is None
            or self.audit_term_goto_btn is None
            or self.audit_term_candidates_edit is None
        ):
            return
        payload = self._audit_term_variant_payload(
            self.audit_term_variants_list.currentItem()
        )
        candidates = self._parse_audit_term_candidates(
            self.audit_term_candidates_edit.text()
        )
        group_key_raw = payload.get("group_key") if payload is not None else ""
        group_key = group_key_raw if isinstance(group_key_raw, str) else ""
        self.audit_term_hits_list.clear()
        self.audit_term_goto_btn.setEnabled(False)
        if payload is None:
            return
        entries = payload.get("entries")
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path_raw = entry.get("path")
            uid_raw = entry.get("uid")
            entry_label = entry.get("entry")
            source_line = entry.get("source_line")
            translation_line = entry.get("translation_line")
            translation_block_text = entry.get("translation_block_text")
            line_index = entry.get("line_index")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            if not isinstance(uid_raw, str) or not uid_raw:
                continue
            if not isinstance(entry_label, str):
                entry_label = "Entry"
            if not isinstance(source_line, str):
                source_line = ""
            if not isinstance(translation_line, str):
                translation_line = ""
            if not isinstance(translation_block_text, str):
                translation_block_text = ""
            line_label = int(line_index) if isinstance(line_index, int) else 0
            relative = self._relative_path(Path(path_raw))
            display_en = translation_line if translation_line else "(empty)"
            if candidates and group_key not in ("", "__all__", "__unmatched__"):
                display_en = self._highlight_candidate_in_text(display_en, group_key)
            block_preview = preview_text(translation_block_text, 170)
            if candidates and group_key not in ("", "__all__", "__unmatched__"):
                block_preview = self._highlight_candidate_in_text(
                    block_preview,
                    group_key,
                )
            label = (
                f"{relative} | {entry_label} | line {line_label}\n"
                f"JP: {preview_text(source_line, 170)}\n"
                f"EN: {preview_text(display_en, 170)}\n"
                f"EN block: {block_preview}"
            )
            item = QListWidgetItem(label)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "path": path_raw,
                    "uid": uid_raw,
                },
            )
            self.audit_term_hits_list.addItem(item)
        if self.audit_term_hits_list.count() > 0:
            self.audit_term_hits_list.setCurrentRow(0)
            self.audit_term_goto_btn.setEnabled(True)

    def _refresh_audit_term_panel(self) -> None:
        if (
            self.audit_term_query_edit is None
            or self.audit_term_candidates_edit is None
            or self.audit_term_dialogue_only_check is None
            or self.audit_term_variants_list is None
            or self.audit_term_hits_list is None
            or self.audit_term_status_label is None
            or self.audit_term_goto_btn is None
        ):
            return
        term = self.audit_term_query_edit.text().strip()
        self.audit_term_variants_list.clear()
        self.audit_term_hits_list.clear()
        self.audit_term_goto_btn.setEnabled(False)
        if not term:
            self.audit_term_status_label.setText(
                "Type a JP source term to inspect variants."
            )
            return
        dialogue_only = self.audit_term_dialogue_only_check.isChecked()
        candidates = self._parse_audit_term_candidates(
            self.audit_term_candidates_edit.text()
        )
        hits = self._collect_audit_term_hits(term, dialogue_only)
        groups = self._build_term_groups(hits, candidates)
        total_hits = 0
        for group in groups:
            group_key_raw = group.get("group_key")
            group_key = group_key_raw if isinstance(group_key_raw, str) else ""
            count = int(group.get("entry_count", 0))
            total_hits += count
            if group_key == "__all__":
                label = f"x{count} | All hits"
            elif group_key == "__unmatched__":
                label = f"x{count} | (unmatched candidates)"
            else:
                label = f"x{count} | {preview_text(group_key, 110)}"
            item = QListWidgetItem(
                label
            )
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.audit_term_variants_list.addItem(item)
        if self.audit_term_variants_list.count() > 0:
            self.audit_term_variants_list.setCurrentRow(0)
        if candidates:
            self.audit_term_status_label.setText(
                f"Candidates: {len(candidates)} | Groups: {len(groups)} | Hits: {total_hits}"
            )
        else:
            self.audit_term_status_label.setText(
                f"Candidates empty: showing raw hits | Hits: {total_hits}"
            )
        self._refresh_audit_term_hits()

    def _go_to_selected_audit_term_hit(self) -> None:
        if self.audit_term_hits_list is None:
            return
        payload = self._audit_term_hit_payload(
            self.audit_term_hits_list.currentItem()
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
