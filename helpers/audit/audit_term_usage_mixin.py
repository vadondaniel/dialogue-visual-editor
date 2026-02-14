from __future__ import annotations

from collections import Counter, defaultdict
from html import escape
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import preview_text, strip_control_tokens


class _AuditTermUsageHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditTermUsageMixin(_AuditTermUsageHostTypingFallback):
    _JP_TERM_RE = re.compile(r"[ぁ-ゟァ-ヿ一-龯々〆〤ー]{2,}")
    _EN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
    _EN_STOPWORDS = {
        "the", "and", "for", "that", "with", "from", "this", "have", "your",
        "you", "are", "was", "were", "will", "would", "could", "should",
        "they", "them", "their", "his", "her", "its", "our", "ours", "it's",
        "is", "am", "be", "been", "being", "to", "of", "in", "on", "at", "as",
        "by", "or", "an", "a", "it", "we", "i", "me", "my", "mine",
    }

    def _marker_text_to_rich_html(self, text: str) -> str:
        if not text:
            return ""
        parts: list[str] = []
        cursor = 0
        while cursor < len(text):
            start = text.find("[[", cursor)
            if start < 0:
                parts.append(escape(text[cursor:]))
                break
            parts.append(escape(text[cursor:start]))
            end = text.find("]]", start + 2)
            if end < 0:
                parts.append(escape(text[start:]))
                break
            highlighted = escape(text[start + 2:end])
            parts.append(
                "<span style=\"background-color:#facc15;color:#111827;font-weight:700;\">"
                f"{highlighted}"
                "</span>"
            )
            cursor = end + 2
        return "".join(parts).replace("\n", "<br>")

    def _add_audit_term_hit_item(
        self,
        text: str,
        payload: dict[str, str],
    ) -> None:
        if self.audit_term_hits_list is None:
            return
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, payload)
        rich_label = QLabel()
        rich_label.setTextFormat(Qt.TextFormat.RichText)
        rich_label.setWordWrap(True)
        rich_label.setText(self._marker_text_to_rich_html(text))
        rich_label.setStyleSheet("QLabel { padding: 6px 8px; }")
        item.setSizeHint(rich_label.sizeHint())
        self.audit_term_hits_list.addItem(item)
        self.audit_term_hits_list.setItemWidget(item, rich_label)

    def _normalize_text_for_block_match(self, value: str) -> str:
        base = strip_control_tokens(value or "").replace("\u3000", " ")
        squashed = re.sub(r"\s+", "", base)
        return squashed.casefold()

    def _plain_text_for_suggestions(self, value: str) -> str:
        base = strip_control_tokens(value or "").replace("\u3000", " ")
        return re.sub(r"\s+", " ", base).strip()

    def _suggestion_item_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _collect_audit_term_suggestions(
        self,
        dialogue_only: bool,
    ) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        source_resolver = getattr(self, "_segment_source_lines_for_translation", None)
        tl_resolver = getattr(self, "_segment_translation_lines_for_translation", None)
        jp_counts: Counter[str] = Counter()
        en_word_counts: Counter[str] = Counter()
        en_bigram_counts: Counter[str] = Counter()
        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            for segment in session.segments:
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
                if isinstance(source_lines, list):
                    for line in source_lines:
                        plain = self._plain_text_for_suggestions(
                            line if isinstance(line, str) else ""
                        )
                        if not plain:
                            continue
                        for token in self._JP_TERM_RE.findall(plain):
                            if len(token) >= 2:
                                jp_counts[token] += 1
                if isinstance(tl_lines, list):
                    for line in tl_lines:
                        plain = self._plain_text_for_suggestions(
                            line if isinstance(line, str) else ""
                        )
                        if not plain:
                            continue
                        words = [
                            token.lower()
                            for token in self._EN_WORD_RE.findall(plain)
                            if len(token) >= 3
                        ]
                        filtered_words = [
                            token
                            for token in words
                            if token not in self._EN_STOPWORDS
                        ]
                        for token in filtered_words:
                            en_word_counts[token] += 1
                        if len(filtered_words) >= 2:
                            for idx in range(len(filtered_words) - 1):
                                bigram = f"{filtered_words[idx]} {filtered_words[idx + 1]}"
                                en_bigram_counts[bigram] += 1

        jp_suggestions = [
            (token, count)
            for token, count in jp_counts.items()
            if count >= 2
        ]
        jp_suggestions.sort(key=lambda row: (-row[1], -len(row[0]), row[0]))
        jp_suggestions = jp_suggestions[:80]

        en_suggestions_counter: Counter[str] = Counter()
        for token, count in en_word_counts.items():
            if count >= 3:
                en_suggestions_counter[token] += count
        for token, count in en_bigram_counts.items():
            if count >= 2:
                en_suggestions_counter[token] += count
        en_suggestions = list(en_suggestions_counter.items())
        en_suggestions.sort(key=lambda row: (-row[1], -len(row[0]), row[0]))
        en_suggestions = en_suggestions[:120]
        return jp_suggestions, en_suggestions

    def _refresh_audit_term_suggestions_panel(self) -> None:
        if (
            self.audit_term_dialogue_only_check is None
            or self.audit_term_suggest_jp_list is None
            or self.audit_term_suggest_en_list is None
        ):
            return
        dialogue_only = self.audit_term_dialogue_only_check.isChecked()
        jp_suggestions, en_suggestions = self._collect_audit_term_suggestions(
            dialogue_only
        )
        self.audit_term_suggest_jp_list.clear()
        self.audit_term_suggest_en_list.clear()
        for token, count in jp_suggestions:
            item = QListWidgetItem(f"{token} ({count})")
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "token": token,
                    "count": count,
                },
            )
            self.audit_term_suggest_jp_list.addItem(item)
        for token, count in en_suggestions:
            item = QListWidgetItem(f"{token} ({count})")
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "token": token,
                    "count": count,
                },
            )
            self.audit_term_suggest_en_list.addItem(item)

    def _use_selected_audit_term_jp_suggestion(self) -> None:
        if self.audit_term_suggest_jp_list is None or self.audit_term_query_edit is None:
            return
        payload = self._suggestion_item_payload(
            self.audit_term_suggest_jp_list.currentItem()
        )
        if payload is None:
            return
        token_raw = payload.get("token")
        token = token_raw if isinstance(token_raw, str) else ""
        if not token:
            return
        self.audit_term_query_edit.setText(token)
        self._refresh_audit_term_panel()

    def _append_selected_audit_term_en_suggestion(self) -> None:
        if self.audit_term_suggest_en_list is None or self.audit_term_candidates_edit is None:
            return
        payload = self._suggestion_item_payload(
            self.audit_term_suggest_en_list.currentItem()
        )
        if payload is None:
            return
        token_raw = payload.get("token")
        token = token_raw if isinstance(token_raw, str) else ""
        if not token:
            return
        current_candidates = self._parse_audit_term_candidates(
            self.audit_term_candidates_edit.text()
        )
        if token.casefold() not in {value.casefold() for value in current_candidates}:
            current_candidates.append(token)
        self.audit_term_candidates_edit.setText(" | ".join(current_candidates))
        self._refresh_audit_term_panel()

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

    def _visible_text_for_match(self, value: str) -> str:
        base = strip_control_tokens(value or "").replace("\u3000", " ")
        return re.sub(r"\s+", " ", base).strip()

    def _normalized_no_space_with_map(self, value: str) -> tuple[str, list[int]]:
        normalized = self._visible_text_for_match(value)
        chars: list[str] = []
        idx_map: list[int] = []
        for idx, ch in enumerate(normalized):
            if ch.isspace():
                continue
            chars.append(ch.casefold())
            idx_map.append(idx)
        return "".join(chars), idx_map

    def _candidate_context_snippet(self, text: str, candidate: str, radius: int = 70) -> str:
        if not text:
            return ""
        visible = self._visible_text_for_match(text)
        if not candidate:
            return preview_text(visible, 170)
        compact_text, idx_map = self._normalized_no_space_with_map(text)
        compact_candidate, _unused = self._normalized_no_space_with_map(candidate)
        if not compact_text or not compact_candidate:
            return preview_text(visible, 170)
        found = compact_text.find(compact_candidate)
        if found < 0:
            return preview_text(visible, 170)
        start_idx = idx_map[found]
        end_compact = found + len(compact_candidate) - 1
        if end_compact >= len(idx_map):
            end_compact = len(idx_map) - 1
        end_idx = idx_map[end_compact] + 1
        left = max(0, start_idx - radius)
        right = min(len(visible), end_idx + radius)
        snippet = visible[left:right]
        rel_start = max(0, start_idx - left)
        rel_end = max(rel_start, end_idx - left)
        highlighted = f"{snippet[:rel_start]}[[{snippet[rel_start:rel_end]}]]{snippet[rel_end:]}"
        prefix = "..." if left > 0 else ""
        suffix = "..." if right < len(visible) else ""
        return f"{prefix}{highlighted}{suffix}"

    def _candidate_group_for_entry(
        self,
        entry: dict[str, Any],
        candidates: list[str],
    ) -> str:
        if not candidates:
            return "__all__"
        block_match_raw = entry.get("translation_block_match")
        block_match = block_match_raw if isinstance(block_match_raw, str) else ""
        matched: list[tuple[int, int, str]] = []
        for idx, candidate in enumerate(candidates):
            normalized_candidate = self._normalize_text_for_block_match(candidate)
            if not normalized_candidate:
                continue
            if normalized_candidate in block_match:
                matched.append((len(normalized_candidate), idx, candidate))
        if matched:
            # Prefer the most specific (longest) candidate; keep user order as tie-breaker.
            matched.sort(key=lambda row: (-row[0], row[1]))
            return matched[0][2]
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
            display_en = preview_text(translation_line if translation_line else "(empty)", 170)
            if candidates and group_key not in ("", "__all__", "__unmatched__"):
                display_en = self._candidate_context_snippet(
                    translation_block_text,
                    group_key,
                )
            label = (
                f"{relative} | {entry_label} | line {line_label}\n"
                f"JP: {preview_text(source_line, 170)}\n"
                f"EN: {display_en}"
            )
            self._add_audit_term_hit_item(
                label,
                {
                    "path": path_raw,
                    "uid": uid_raw,
                },
            )
        if self.audit_term_hits_list.count() > 0:
            self.audit_term_hits_list.setCurrentRow(0)
            self.audit_term_goto_btn.setEnabled(True)
        self._refresh_audit_term_apply_state()

    def _refresh_audit_term_apply_state(self) -> None:
        if (
            self.audit_term_apply_canonical_btn is None
            or self.audit_term_candidates_edit is None
            or self.audit_term_variants_list is None
        ):
            return
        candidates = self._parse_audit_term_candidates(
            self.audit_term_candidates_edit.text()
        )
        payload = self._audit_term_variant_payload(
            self.audit_term_variants_list.currentItem()
        )
        if not candidates or payload is None:
            self.audit_term_apply_canonical_btn.setEnabled(False)
            return
        canonical = candidates[0]
        group_key_raw = payload.get("group_key")
        group_key = group_key_raw if isinstance(group_key_raw, str) else ""
        can_apply = (
            group_key not in ("", "__all__", "__unmatched__")
            and group_key.casefold() != canonical.casefold()
        )
        self.audit_term_apply_canonical_btn.setEnabled(can_apply)

    def _replace_case_insensitive(self, text: str, source: str, target: str) -> tuple[str, int]:
        if not text or not source:
            return text, 0
        pattern = re.compile(re.escape(source), flags=re.IGNORECASE)
        replaced, count = pattern.subn(target, text)
        return replaced, count

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
            canonical = candidates[0]
            self.audit_term_status_label.setText(
                f"Canonical: {canonical} | Candidates: {len(candidates)} | Groups: {len(groups)} | Hits: {total_hits}"
            )
        else:
            self.audit_term_status_label.setText(
                f"Candidates empty: showing raw hits | Hits: {total_hits}"
            )
        self._refresh_audit_term_hits()
        self._refresh_audit_term_apply_state()

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

    def _apply_selected_audit_term_variant_to_canonical(self) -> None:
        if (
            self.audit_term_candidates_edit is None
            or self.audit_term_variants_list is None
            or self.audit_term_apply_canonical_btn is None
        ):
            return
        candidates = self._parse_audit_term_candidates(
            self.audit_term_candidates_edit.text()
        )
        if not candidates:
            self.statusBar().showMessage("Enter candidates first; first one is canonical.")
            return
        canonical = candidates[0]
        payload = self._audit_term_variant_payload(
            self.audit_term_variants_list.currentItem()
        )
        if payload is None:
            self.statusBar().showMessage("Select a candidate group first.")
            return
        source_raw = payload.get("group_key")
        source_candidate = source_raw if isinstance(source_raw, str) else ""
        if source_candidate in ("", "__all__", "__unmatched__"):
            self.statusBar().showMessage("Select a concrete candidate group.")
            return
        if source_candidate.casefold() == canonical.casefold():
            self.statusBar().showMessage("Selected group is already canonical.")
            return
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            self.statusBar().showMessage("Selected group is empty.")
            return

        touched_paths: set[Path] = set()
        touched_current = False
        changed_blocks = 0
        replaced_total = 0
        processed_uids: set[tuple[str, str]] = set()
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
            if key in processed_uids:
                continue
            processed_uids.add(key)
            path = Path(path_raw)
            session = self.sessions.get(path)
            if session is None:
                continue
            target_segment = None
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
            segment_replace_count = 0
            for line in current_lines:
                replaced_line, count = self._replace_case_insensitive(
                    line,
                    source_candidate,
                    canonical,
                )
                next_lines.append(replaced_line)
                segment_replace_count += count
            if segment_replace_count <= 0:
                continue
            target_segment.translation_lines = list(next_lines)
            changed_blocks += 1
            replaced_total += segment_replace_count
            touched_paths.add(path)
            if self.current_path is not None and path == self.current_path:
                touched_current = True

        if changed_blocks <= 0:
            self.statusBar().showMessage(
                f"No replaceable '{source_candidate}' occurrences found in selected group."
            )
            return

        for path in touched_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
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
        self._refresh_audit_term_panel()
        self.statusBar().showMessage(
            f"Replaced '{source_candidate}' -> '{canonical}' in {changed_blocks} blocks ({replaced_total} matches)."
        )
