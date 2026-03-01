from __future__ import annotations

from collections import Counter
import copy
import hashlib
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox, QTextEdit, QWidget

from ..core.models import DialogueSegment, FileSession, NO_SPEAKER_KEY
from ..core.text_utils import (
    first_overflow_char_index,
    preview_text,
    split_lines_by_row_budget,
    total_display_rows,
    visible_length,
)
from ..mixins.presentation_mixins import is_dark_palette


class _AuditConsistencyHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditConsistencyMixin(_AuditConsistencyHostTypingFallback):
    _BLOCK_ENTRY_RE = re.compile(r"^Block\s+(\d+)$", re.IGNORECASE)
    _NAME_INDEX_ALIAS_FIELD_RE = re.compile(r"^alt_\d+$", re.IGNORECASE)
    _CONSISTENCY_TARGET_SPLIT_DIVIDER_RE = re.compile(
        r"^(?:-+|\|+|-{5,}\s*Block\s+\d+\s*-{5,})$",
        re.IGNORECASE,
    )
    _CONSISTENCY_TARGET_MIN_LINES = 5
    _CONSISTENCY_TARGET_MAX_LINES = 16

    def _consistency_entry_file_stem(self, path_raw: str) -> str:
        relative_path = self._relative_path(Path(path_raw))
        file_stem = Path(relative_path).stem.strip() or Path(path_raw).stem.strip()
        if not file_stem:
            file_stem = Path(path_raw).name.strip() or "File"
        return file_stem

    def _consistency_source_language_label(self) -> str:
        source_label_resolver = getattr(
            self,
            "_translation_project_source_language_label",
            None,
        )
        if callable(source_label_resolver):
            try:
                resolved = source_label_resolver()
            except Exception:
                resolved = ""
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
        return "Source"

    def _consistency_target_language_label(self) -> str:
        target_label_resolver = getattr(
            self,
            "_translation_profile_target_language_label",
            None,
        )
        if callable(target_label_resolver):
            try:
                resolved = target_label_resolver()
            except Exception:
                resolved = ""
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
        return "Target"

    def _consistency_speakers_for_segment(
        self,
        segment: DialogueSegment,
    ) -> tuple[str, str]:
        speaker_key = segment.speaker_name
        speaker_key_resolver = getattr(self, "_speaker_key_for_segment", None)
        if callable(speaker_key_resolver):
            try:
                resolved_key = speaker_key_resolver(segment)
            except Exception:
                resolved_key = speaker_key
            if isinstance(resolved_key, str) and resolved_key.strip():
                speaker_key = resolved_key.strip()

        normalize_speaker_key = getattr(self, "_normalize_speaker_key", None)
        if callable(normalize_speaker_key):
            normalized = normalize_speaker_key(speaker_key)
            if isinstance(normalized, str) and normalized.strip():
                speaker_key = normalized.strip()
        elif not speaker_key.strip():
            speaker_key = NO_SPEAKER_KEY

        if not speaker_key.strip():
            speaker_key = NO_SPEAKER_KEY

        speaker_en = ""
        speaker_translation = getattr(self, "_speaker_translation_for_key", None)
        if callable(speaker_translation):
            translated = speaker_translation(speaker_key)
            if isinstance(translated, str) and translated.strip():
                speaker_en = translated.strip()
        if not speaker_en and isinstance(segment.translation_speaker, str):
            speaker_en = segment.translation_speaker.strip()
        if speaker_key == NO_SPEAKER_KEY:
            speaker_en = ""
        return speaker_key, speaker_en

    def _consistency_neighbor_text_for_segment(
        self,
        segment: DialogueSegment,
    ) -> tuple[str, str]:
        source_text = "\n".join(self._consistency_source_lines_for_segment(segment)).strip()
        tl_lines = self._consistency_translation_lines_for_segment(segment)
        translation_text = "\n".join(tl_lines).strip()
        return source_text, translation_text

    def _consistency_source_lines_for_segment(
        self,
        segment: DialogueSegment,
    ) -> list[str]:
        source_lines_resolver = getattr(self, "_segment_source_lines_for_translation", None)
        if callable(source_lines_resolver):
            try:
                resolved = source_lines_resolver(segment)
            except Exception:
                resolved = None
            if isinstance(resolved, list):
                return self._normalize_translation_lines(resolved)
        return self._normalize_translation_lines(
            self._segment_source_lines_for_display(segment)
        )

    def _consistency_translation_lines_for_segment(
        self,
        segment: DialogueSegment,
    ) -> list[str]:
        visible_lines_resolver = getattr(self, "_segment_translation_lines_for_translation", None)
        if callable(visible_lines_resolver):
            try:
                resolved_visible = visible_lines_resolver(segment)
            except Exception:
                resolved_visible = None
            if isinstance(resolved_visible, list):
                candidate = self._normalize_translation_lines(resolved_visible)
                normalize_for_segment = getattr(
                    self, "_normalize_audit_translation_lines_for_segment", None
                )
                if callable(normalize_for_segment):
                    try:
                        normalized_raw = normalize_for_segment(segment, candidate)
                    except Exception:
                        normalized_raw = candidate
                    return self._normalize_translation_lines(normalized_raw)
                return candidate

        normalize_for_segment = getattr(
            self, "_normalize_audit_translation_lines_for_segment", None
        )
        if callable(normalize_for_segment):
            try:
                tl_lines_raw = normalize_for_segment(segment, segment.translation_lines)
            except Exception:
                tl_lines_raw = self._normalize_translation_lines(segment.translation_lines)
        else:
            tl_lines_raw = self._normalize_translation_lines(segment.translation_lines)
        return self._normalize_translation_lines(tl_lines_raw)

    def _consistency_actor_id_for_segment(
        self,
        segment: DialogueSegment,
    ) -> Optional[int]:
        actor_id_raw = getattr(segment, "actor_alias_actor_id", None)
        if isinstance(actor_id_raw, int):
            return actor_id_raw
        actor_id_resolver = getattr(self, "_actor_id_from_uid", None)
        if callable(actor_id_resolver):
            try:
                resolved = actor_id_resolver(segment.uid)
            except Exception:
                resolved = None
            if isinstance(resolved, int):
                return resolved
        return None

    def _consistency_effective_translation_text(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> str:
        tl_text = "\n".join(self._consistency_translation_lines_for_segment(segment)).strip()
        if tl_text:
            return tl_text
        if not bool(getattr(segment, "is_actor_name_alias", False)):
            return tl_text

        is_actor_session_resolver = getattr(self, "_is_actor_index_session", None)
        is_actor_session = False
        if callable(is_actor_session_resolver):
            try:
                is_actor_session = bool(is_actor_session_resolver(session))
            except Exception:
                is_actor_session = False
        if not is_actor_session:
            kind = str(getattr(session, "name_index_kind", "")).strip().lower()
            is_actor_session = kind == "actor"
        if not is_actor_session:
            return tl_text

        actor_id = self._consistency_actor_id_for_segment(segment)
        source_text = "\n".join(self._consistency_source_lines_for_segment(segment)).strip()
        if actor_id is not None and source_text:
            peer_translations: list[str] = []
            for candidate in session.segments:
                if not bool(getattr(candidate, "is_actor_name_alias", False)):
                    continue
                if self._consistency_actor_id_for_segment(candidate) != actor_id:
                    continue
                candidate_source = "\n".join(
                    self._consistency_source_lines_for_segment(candidate)
                ).strip()
                if candidate_source != source_text:
                    continue
                candidate_tl = "\n".join(
                    self._consistency_translation_lines_for_segment(candidate)
                ).strip()
                if candidate_tl:
                    peer_translations.append(candidate_tl)
            if peer_translations:
                return Counter(peer_translations).most_common(1)[0][0]

        actor_maps_resolver = getattr(self, "_actor_name_maps", None)
        if not callable(actor_maps_resolver):
            return tl_text
        try:
            actor_maps = actor_maps_resolver()
        except Exception:
            actor_maps = None
        if not (
            isinstance(actor_maps, tuple)
            and len(actor_maps) >= 2
            and isinstance(actor_maps[0], dict)
            and isinstance(actor_maps[1], dict)
        ):
            return tl_text
        jp_by_id = cast(dict[int, str], actor_maps[0])
        en_by_id = cast(dict[int, str], actor_maps[1])
        if actor_id is None:
            return tl_text
        actor_source = str(jp_by_id.get(actor_id, "")).strip()
        actor_translated = str(en_by_id.get(actor_id, "")).strip()
        if (
            source_text
            and actor_source
            and actor_translated
            and actor_translated != actor_source
            and source_text == actor_source
        ):
            return actor_translated
        return tl_text

    def _consistency_logical_entry_rows_for_session(
        self,
        session: FileSession,
        dialogue_only: bool,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        leading_translation_only: list[DialogueSegment] = []
        for idx, segment in enumerate(session.segments, start=1):
            if dialogue_only and not bool(getattr(segment, "is_structural_dialogue", False)):
                continue
            if bool(getattr(segment, "translation_only", False)):
                if rows:
                    cast(list[DialogueSegment], rows[-1]["segments"]).append(segment)
                else:
                    leading_translation_only.append(segment)
                continue
            entry_segments: list[DialogueSegment] = [segment]
            if leading_translation_only:
                entry_segments.extend(leading_translation_only)
                leading_translation_only = []
            rows.append(
                {
                    "anchor_segment": segment,
                    "anchor_index": idx,
                    "segments": entry_segments,
                }
            )
        if leading_translation_only and rows:
            cast(list[DialogueSegment], rows[0]["segments"]).extend(leading_translation_only)
        return rows

    def _consistency_translation_chunks_for_entry(
        self,
        session: FileSession,
        segments: list[DialogueSegment],
    ) -> list[str]:
        chunks: list[str] = []
        first_segment_lines: list[str] = []
        for segment in segments:
            segment_lines = self._consistency_translation_lines_for_segment(segment)
            if not first_segment_lines:
                first_segment_lines = list(segment_lines)
            chunk = "\n".join(segment_lines)
            chunks.append(chunk)
        if len(segments) == 1 and chunks and not any(
            line.strip() for line in first_segment_lines
        ):
            alias_fallback = self._consistency_effective_translation_text(
                session,
                segments[0],
            )
            if alias_fallback.strip():
                chunks[0] = alias_fallback
        return chunks

    def _consistency_translation_text_for_chunks(
        self,
        chunks: list[str],
    ) -> str:
        return "\n".join(chunks).rstrip("\n")

    def _consistency_target_display_text_for_chunks(
        self,
        chunks: list[str],
    ) -> str:
        normalized_chunks: list[str] = []
        for chunk in chunks:
            if isinstance(chunk, str):
                normalized_chunks.append(chunk)
        if not normalized_chunks:
            return ""
        if len(normalized_chunks) <= 1:
            return normalized_chunks[0]
        max_lines_spin = getattr(self, "max_lines_spin", None)
        line_limit = int(max_lines_spin.value()) if max_lines_spin is not None else 4
        line_limit = max(1, line_limit)
        parts: list[str] = []
        for index, chunk in enumerate(normalized_chunks):
            chunk_lines = self._normalize_translation_lines(chunk)
            parts.extend(chunk_lines)
            if index < len(normalized_chunks) - 1:
                pad_lines = max(0, line_limit - len(chunk_lines))
                parts.extend(
                    [""] * pad_lines
                )
                # Keep one blank boundary row; it will be styled as separator.
                parts.extend([""])
        return "\n".join(parts)

    def _consistency_target_display_text_for_payload(
        self,
        payload: Optional[dict[str, Any]],
    ) -> str:
        if not isinstance(payload, dict):
            return ""
        chunks_raw = payload.get("translation_chunks")
        chunks: list[str] = []
        if isinstance(chunks_raw, list):
            for raw_chunk in chunks_raw:
                if isinstance(raw_chunk, str):
                    chunks.append(raw_chunk)
        if chunks:
            return self._consistency_target_display_text_for_chunks(chunks)
        translation = payload.get("translation")
        return translation if isinstance(translation, str) else ""

    def _consistency_target_is_split_divider(self, line_text: str) -> bool:
        return self._CONSISTENCY_TARGET_SPLIT_DIVIDER_RE.fullmatch(line_text.strip()) is not None

    def _resize_audit_consistency_target_editor_for_content(self) -> None:
        target_edit = getattr(self, "audit_consistency_target_edit", None)
        if target_edit is None:
            return
        document = getattr(target_edit, "document", None)
        if not callable(document):
            return
        try:
            doc = document()
        except Exception:
            return
        block_count = 0
        if doc is not None and hasattr(doc, "blockCount"):
            try:
                block_count = int(doc.blockCount())
            except Exception:
                block_count = 0
        if block_count <= 0 and hasattr(target_edit, "toPlainText"):
            try:
                block_count = len(str(target_edit.toPlainText()).splitlines()) or 1
            except Exception:
                block_count = 1
        desired_lines = max(
            self._CONSISTENCY_TARGET_MIN_LINES,
            min(self._CONSISTENCY_TARGET_MAX_LINES, block_count),
        )
        font_metrics = getattr(target_edit, "fontMetrics", None)
        if not callable(font_metrics):
            return
        try:
            line_height = int(font_metrics().lineSpacing())
        except Exception:
            return
        try:
            doc_margin = int(doc.documentMargin() * 2) if doc is not None else 0
        except Exception:
            doc_margin = 0
        try:
            frame = int(target_edit.frameWidth() * 2)
        except Exception:
            frame = 0
        target_height = line_height * desired_lines + doc_margin + frame + 2
        set_fixed_height = getattr(target_edit, "setFixedHeight", None)
        if callable(set_fixed_height):
            try:
                set_fixed_height(target_height)
            except Exception:
                pass

    def _consistency_target_chunks_for_text(
        self,
        text: str,
    ) -> list[dict[str, Any]]:
        lines = self._normalize_translation_lines(text)
        chunks: list[dict[str, Any]] = []
        current_lines: list[str] = []
        current_indices: list[int] = []
        pending_blank_index: Optional[int] = None
        in_separator_zone = False
        max_lines_spin = getattr(self, "max_lines_spin", None)
        line_limit = int(max_lines_spin.value()) if max_lines_spin is not None else 4
        line_limit = max(1, line_limit)

        def flush_current() -> None:
            nonlocal current_lines, current_indices
            chunk_lines = list(current_lines) if current_lines else [""]
            chunks.append(
                {
                    "lines": self._normalize_translation_lines(chunk_lines),
                    "display_indices": list(current_indices),
                }
            )
            current_lines = []
            current_indices = []

        for line_index, line_text in enumerate(lines):
            if self._consistency_target_is_split_divider(line_text):
                pending_blank_index = None
                flush_current()
                in_separator_zone = True
                continue
            if line_text == "":
                if in_separator_zone:
                    continue
                if pending_blank_index is not None:
                    # second consecutive blank = explicit boundary split
                    pending_blank_index = None
                    flush_current()
                    in_separator_zone = True
                    continue
                pending_blank_index = line_index
                continue
            if pending_blank_index is not None:
                if len(current_lines) >= line_limit:
                    # single blank after a full chunk is treated as boundary row
                    flush_current()
                    in_separator_zone = False
                else:
                    current_lines.append("")
                    current_indices.append(pending_blank_index)
                pending_blank_index = None
            in_separator_zone = False
            current_lines.append(line_text)
            current_indices.append(line_index)

        if pending_blank_index is not None:
            if len(current_lines) < line_limit:
                current_lines.append("")
                current_indices.append(pending_blank_index)
            pending_blank_index = None

        if current_lines or not chunks:
            flush_current()
        return chunks

    def _consistency_target_separator_display_indices(
        self,
        text: str,
    ) -> list[int]:
        lines = self._normalize_translation_lines(text)
        separator_indices: list[int] = []
        pending_blank_index: Optional[int] = None
        in_separator_zone = False
        max_lines_spin = getattr(self, "max_lines_spin", None)
        line_limit = int(max_lines_spin.value()) if max_lines_spin is not None else 4
        line_limit = max(1, line_limit)
        current_line_count = 0
        for line_index, line_text in enumerate(lines):
            if self._consistency_target_is_split_divider(line_text):
                separator_indices.append(line_index)
                pending_blank_index = None
                in_separator_zone = True
                current_line_count = 0
                continue
            if line_text == "":
                if in_separator_zone:
                    continue
                if pending_blank_index is not None:
                    separator_indices.append(line_index)
                    pending_blank_index = None
                    in_separator_zone = True
                    current_line_count = 0
                    continue
                pending_blank_index = line_index
                continue
            if pending_blank_index is not None:
                if current_line_count >= line_limit:
                    separator_indices.append(pending_blank_index)
                    current_line_count = 0
                else:
                    current_line_count += 1
                pending_blank_index = None
            in_separator_zone = False
            current_line_count += 1
        return separator_indices

    def _consistency_chunk_line_counts_from_payload(
        self,
        payload: dict[str, Any],
    ) -> list[int]:
        counts_raw = payload.get("chunk_line_counts")
        if isinstance(counts_raw, list):
            parsed_counts: list[int] = []
            for raw_count in counts_raw:
                if isinstance(raw_count, int):
                    parsed_counts.append(max(1, raw_count))
            if parsed_counts:
                return parsed_counts

        chunks_raw = payload.get("translation_chunks")
        if isinstance(chunks_raw, list):
            parsed_counts = []
            for raw_chunk in chunks_raw:
                if isinstance(raw_chunk, str):
                    parsed_counts.append(
                        max(1, len(self._normalize_translation_lines(raw_chunk)))
                    )
            if parsed_counts:
                return parsed_counts
        return []

    def _consistency_split_target_lines_for_chain(
        self,
        target_lines: list[str],
        segment_count: int,
        selected_pattern_counts: list[int],
    ) -> list[list[str]]:
        if segment_count <= 0:
            return []
        remaining = list(target_lines)
        split_lines: list[list[str]] = []
        pattern_non_last_count = max(0, len(selected_pattern_counts) - 1)
        for segment_index in range(segment_count):
            if segment_index == segment_count - 1:
                chunk = list(remaining) if remaining else [""]
                remaining = []
            else:
                preferred = (
                    selected_pattern_counts[segment_index]
                    if segment_index < pattern_non_last_count
                    else 1
                )
                keep_count = max(1, int(preferred))
                if remaining:
                    chunk = list(remaining[:keep_count])
                    remaining = list(remaining[keep_count:])
                    if not chunk:
                        chunk = [""]
                else:
                    chunk = [""]
            split_lines.append(self._normalize_translation_lines(chunk))
        return split_lines

    def _consistency_remove_segment_from_session(
        self,
        session: FileSession,
        uid: str,
    ) -> bool:
        remove_resolver = getattr(self, "_remove_segment_by_uid", None)
        if callable(remove_resolver):
            try:
                removed = bool(remove_resolver(session, uid))
            except Exception:
                removed = False
            if removed:
                return True
        for idx, segment in enumerate(session.segments):
            if segment.uid == uid:
                del session.segments[idx]
                return True
        return False

    def _consistency_build_translation_only_segment(
        self,
        session: FileSession,
        anchor_segment: DialogueSegment,
    ) -> DialogueSegment:
        new_segment_uid_resolver = getattr(self, "_new_segment_uid", None)
        if callable(new_segment_uid_resolver):
            try:
                uid = str(new_segment_uid_resolver(session.path))
            except Exception:
                uid = f"{session.path.name}:I:consistency"
        else:
            uid = f"{session.path.name}:I:consistency"

        new_tl_uid_resolver = getattr(self, "_new_translation_uid", None)
        if callable(new_tl_uid_resolver):
            try:
                tl_uid = str(new_tl_uid_resolver())
            except Exception:
                tl_uid = ""
        else:
            tl_uid = ""

        base_source_lines = [""]
        inferred_marker = ""
        inferred_marker_resolver = getattr(self, "_inferred_line1_speaker_marker", None)
        if callable(inferred_marker_resolver):
            try:
                inferred_marker_raw = inferred_marker_resolver(anchor_segment)
            except Exception:
                inferred_marker_raw = ""
            if isinstance(inferred_marker_raw, str):
                inferred_marker = inferred_marker_raw
        with_marker_resolver = getattr(self, "_with_inferred_line1_marker", None)
        if callable(with_marker_resolver):
            try:
                base_source_lines = self._normalize_translation_lines(
                    with_marker_resolver([""], inferred_marker)
                )
            except Exception:
                base_source_lines = [""]

        return DialogueSegment(
            uid=uid,
            context=anchor_segment.context,
            code101=copy.deepcopy(anchor_segment.code101),
            lines=list(base_source_lines),
            original_lines=list(base_source_lines),
            source_lines=list(base_source_lines),
            code401_template=copy.deepcopy(anchor_segment.code401_template),
            segment_kind=anchor_segment.segment_kind,
            line_entry_code=anchor_segment.line_entry_code,
            choice_branch_entries=copy.deepcopy(anchor_segment.choice_branch_entries),
            script_entries_template=copy.deepcopy(anchor_segment.script_entries_template),
            script_entry_roles=list(anchor_segment.script_entry_roles),
            script_entry_quotes=list(anchor_segment.script_entry_quotes),
            script_entry_expression_templates=copy.deepcopy(
                anchor_segment.script_entry_expression_templates
            ),
            tl_uid=tl_uid,
            translation_lines=list(base_source_lines),
            original_translation_lines=list(base_source_lines),
            translation_speaker=anchor_segment.translation_speaker,
            original_translation_speaker=anchor_segment.translation_speaker,
            disable_line1_speaker_inference=anchor_segment.disable_line1_speaker_inference,
            original_disable_line1_speaker_inference=anchor_segment.disable_line1_speaker_inference,
            force_line1_speaker_inference=anchor_segment.force_line1_speaker_inference,
            original_force_line1_speaker_inference=anchor_segment.force_line1_speaker_inference,
            inserted=True,
            translation_only=True,
        )

    def _consistency_align_entry_chain_segments(
        self,
        session: FileSession,
        anchor_uid: str,
        segment_uids: list[str],
        desired_count: int,
        lookup: dict[str, DialogueSegment],
    ) -> tuple[list[DialogueSegment], bool]:
        if desired_count <= 0:
            desired_count = 1
        anchor_segment = lookup.get(anchor_uid)
        if anchor_segment is None:
            return [], False

        resolved_uids: list[str] = []
        for uid in segment_uids:
            if uid in lookup and uid not in resolved_uids:
                resolved_uids.append(uid)
        if not resolved_uids:
            resolved_uids = [anchor_uid]
        elif resolved_uids[0] != anchor_uid:
            resolved_uids = [anchor_uid] + [uid for uid in resolved_uids if uid != anchor_uid]

        changed = False
        if len(resolved_uids) > desired_count:
            remove_uids = list(resolved_uids[desired_count:])
            for remove_uid in remove_uids:
                removed = self._consistency_remove_segment_from_session(session, remove_uid)
                if removed:
                    lookup.pop(remove_uid, None)
                    changed = True
            resolved_uids = list(resolved_uids[:desired_count])

        while len(resolved_uids) < desired_count:
            anchor_index = next(
                (idx for idx, segment in enumerate(session.segments) if segment.uid == anchor_uid),
                -1,
            )
            if anchor_index < 0:
                break
            insert_after_uid = resolved_uids[-1] if resolved_uids else anchor_uid
            insert_after_index = next(
                (
                    idx
                    for idx, segment in enumerate(session.segments)
                    if segment.uid == insert_after_uid
                ),
                anchor_index,
            )
            new_segment = self._consistency_build_translation_only_segment(
                session,
                anchor_segment,
            )
            session.segments.insert(insert_after_index + 1, new_segment)
            lookup[new_segment.uid] = new_segment
            resolved_uids.append(new_segment.uid)
            changed = True

        resolved_segments = [
            lookup[uid]
            for uid in resolved_uids
            if uid in lookup
        ]
        return resolved_segments, changed

    def _find_consistency_entry_segment(
        self,
        payload: dict[str, Any],
    ) -> Optional[tuple[FileSession, int, DialogueSegment]]:
        path_raw = payload.get("path")
        uid_raw = payload.get("uid")
        if not isinstance(path_raw, str) or not path_raw:
            return None
        if not isinstance(uid_raw, str) or not uid_raw:
            return None

        path = Path(path_raw)
        session = self.sessions.get(path)
        if session is None:
            return None

        for idx, segment in enumerate(session.segments):
            if segment.uid == uid_raw:
                return session, idx, segment
        return None

    def _consistency_neighbor_slot_payload(
        self,
        session: FileSession,
        index: int,
    ) -> dict[str, str]:
        source_label = self._consistency_source_language_label()
        target_label = self._consistency_target_language_label()
        if index < 0 or index >= len(session.segments):
            return {
                "speaker_source": NO_SPEAKER_KEY,
                "text_source": "-",
                "speaker_target": "-",
                "text_target": "-",
                "source_label": source_label,
                "target_label": target_label,
            }
        segment = session.segments[index]
        speaker_source, speaker_target = self._consistency_speakers_for_segment(segment)
        text_source, text_target = self._consistency_neighbor_text_for_segment(segment)
        return {
            "speaker_source": speaker_source or NO_SPEAKER_KEY,
            "text_source": text_source or "-",
            "speaker_target": speaker_target or "-",
            "text_target": text_target or "-",
            "source_label": source_label,
            "target_label": target_label,
        }

    def _consistency_neighbor_context_payload(
        self,
        payload: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        source_label = self._consistency_source_language_label()
        target_label = self._consistency_target_language_label()
        empty_slots: dict[str, dict[str, str]] = {
            "previous": {
                "speaker_source": NO_SPEAKER_KEY,
                "text_source": "-",
                "speaker_target": "-",
                "text_target": "-",
                "source_label": source_label,
                "target_label": target_label,
            },
            "current": {
                "speaker_source": NO_SPEAKER_KEY,
                "text_source": "-",
                "speaker_target": "-",
                "text_target": "-",
                "source_label": source_label,
                "target_label": target_label,
            },
            "next": {
                "speaker_source": NO_SPEAKER_KEY,
                "text_source": "-",
                "speaker_target": "-",
                "text_target": "-",
                "source_label": source_label,
                "target_label": target_label,
            },
        }
        if payload is None:
            return {
                "status": "Select an entry to inspect neighboring strings.",
                "slots": empty_slots,
                "entry_header": "",
            }
        resolved = self._find_consistency_entry_segment(payload)
        if resolved is None:
            return {
                "status": "Selected entry no longer exists.",
                "slots": empty_slots,
                "entry_header": "",
            }
        session, segment_index, _segment = resolved
        relative = self._relative_path(session.path)
        entry_label = payload.get("entry")
        if not isinstance(entry_label, str) or not entry_label.strip():
            entry_label = "Entry"
        return {
            "status": (
                f"Source: {source_label} | Target: {target_label} | "
                f"Entry: {relative} | {entry_label}"
            ),
            "entry_header": f"Entry: {relative} | {entry_label}",
            "slots": {
                "previous": self._consistency_neighbor_slot_payload(
                    session, segment_index - 1
                ),
                "current": self._consistency_neighbor_slot_payload(session, segment_index),
                "next": self._consistency_neighbor_slot_payload(session, segment_index + 1),
            },
        }

    def _build_consistency_neighbor_preview_text(
        self,
        payload: Optional[dict[str, Any]],
    ) -> str:
        context_payload = self._consistency_neighbor_context_payload(payload)
        slots = context_payload.get("slots")
        if not isinstance(slots, dict):
            return str(context_payload.get("status", "")).strip()

        def block_text(label: str, key: str) -> str:
            slot = slots.get(key)
            if not isinstance(slot, dict):
                return f"[{label}]"
            source_label = str(slot.get("source_label", "Source"))
            target_label = str(slot.get("target_label", "Target"))
            return "\n".join(
                [
                    f"[{label}]",
                    f"Speaker ({source_label}): {slot.get('speaker_source', NO_SPEAKER_KEY)}",
                    f"Text ({source_label}): {slot.get('text_source', '-')}",
                    f"Speaker ({target_label}): {slot.get('speaker_target', '-')}",
                    f"Text ({target_label}): {slot.get('text_target', '-')}",
                ]
            )

        entry_header = str(context_payload.get("entry_header", "")).strip()
        if not entry_header:
            status = str(context_payload.get("status", "")).strip()
            return status or "Select an entry to inspect neighboring strings."
        return "\n".join(
            [
                entry_header,
                "",
                block_text("Previous", "previous"),
                "",
                block_text("Current", "current"),
                "",
                block_text("Next", "next"),
            ]
        )

    def _set_consistency_neighbor_section(
        self,
        section_widgets: dict[str, Any],
        section_payload: dict[str, Any],
    ) -> None:
        source_speaker_edit = section_widgets.get("source_speaker_edit")
        if source_speaker_edit is not None and hasattr(source_speaker_edit, "setText"):
            source_speaker_edit.setText(str(section_payload.get("speaker_source", "")))
        target_speaker_edit = section_widgets.get("target_speaker_edit")
        if target_speaker_edit is not None and hasattr(target_speaker_edit, "setText"):
            target_speaker_edit.setText(str(section_payload.get("speaker_target", "")))
        source_text_edit = section_widgets.get("source_text_edit")
        if source_text_edit is not None and hasattr(source_text_edit, "setPlainText"):
            source_text_edit.setPlainText(str(section_payload.get("text_source", "")))
        target_text_edit = section_widgets.get("target_text_edit")
        if target_text_edit is not None and hasattr(target_text_edit, "setPlainText"):
            target_text_edit.setPlainText(str(section_payload.get("text_target", "")))

    def _refresh_audit_consistency_neighbors_preview(self) -> None:
        neighbors_check = getattr(self, "audit_consistency_neighbors_check", None)
        show_context = bool(neighbors_check is not None and neighbors_check.isChecked())

        payload: Optional[dict[str, Any]] = None
        if self.audit_consistency_entries_list is not None:
            payload = self._audit_consistency_entry_payload(
                self.audit_consistency_entries_list.currentItem()
            )

        sections = getattr(self, "audit_consistency_neighbors_sections", None)
        legend_label = getattr(self, "audit_consistency_neighbors_legend_label", None)
        if isinstance(sections, dict) and legend_label is not None:
            if not show_context:
                legend_label.setText("Show Context is disabled.")
                empty = self._consistency_neighbor_context_payload(None)
                empty_slots = empty.get("slots")
                if isinstance(empty_slots, dict):
                    for section_key, section_payload in empty_slots.items():
                        section_widgets = sections.get(section_key)
                        if isinstance(section_widgets, dict) and isinstance(
                            section_payload, dict
                        ):
                            self._set_consistency_neighbor_section(
                                section_widgets, section_payload
                            )
                return
            context_payload = self._consistency_neighbor_context_payload(payload)
            legend_label.setText(str(context_payload.get("status", "")))
            slots = context_payload.get("slots")
            if isinstance(slots, dict):
                for section_key in ("previous", "current", "next"):
                    section_widgets = sections.get(section_key)
                    section_payload = slots.get(section_key)
                    if isinstance(section_widgets, dict) and isinstance(
                        section_payload, dict
                    ):
                        self._set_consistency_neighbor_section(
                            section_widgets, section_payload
                        )
            return

        neighbors_edit = getattr(self, "audit_consistency_neighbors_edit", None)
        if neighbors_edit is None:
            return
        if not show_context:
            neighbors_edit.setPlainText("")
            return
        neighbors_edit.setPlainText(self._build_consistency_neighbor_preview_text(payload))

    def _consistency_variant_hash(self, variant_text: str) -> int:
        digest = hashlib.blake2b(
            variant_text.encode("utf-8", errors="ignore"),
            digest_size=8,
        ).digest()
        return int.from_bytes(digest, byteorder="big", signed=False)

    def _consistency_variant_color_map(
        self,
        variants: set[str],
    ) -> dict[str, QColor]:
        if not variants:
            return {}
        ordered_variants = sorted(
            variants,
            key=lambda text: self._consistency_variant_hash(text),
        )
        total = len(ordered_variants)
        dark = is_dark_palette()
        if dark:
            saturation = 110
            value = 90
        else:
            saturation = 65
            value = 240
        color_map: dict[str, QColor] = {}
        for idx, text in enumerate(ordered_variants):
            hue = int((idx * 360) / max(total, 1)) % 360
            color_map[text] = QColor.fromHsv(hue, saturation, value)
        return color_map

    def _consistency_variant_bg(
        self,
        variant_text: str,
        color_map: dict[str, QColor],
    ) -> QColor:
        if not variant_text.strip():
            return QColor("#3f3f46") if is_dark_palette() else QColor("#e5e7eb")
        return color_map.get(
            variant_text,
            QColor("#4b5563") if is_dark_palette() else QColor("#dbeafe"),
        )

    def _consistency_variant_fg(self) -> QColor:
        return QColor("#f8fafc") if is_dark_palette() else QColor("#111827")

    def _audit_consistency_group_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _audit_consistency_entry_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _consistency_name_index_field_name(
        self,
        segment: DialogueSegment,
    ) -> str:
        combined_fields_raw = getattr(segment, "name_index_combined_fields", None)
        if isinstance(combined_fields_raw, tuple):
            combined_fields: list[str] = []
            for raw_field in combined_fields_raw:
                if not isinstance(raw_field, str):
                    continue
                cleaned = raw_field.strip().lower()
                if cleaned:
                    combined_fields.append(cleaned)
            if combined_fields:
                return " + ".join(combined_fields)

        field_from_uid = getattr(self, "_name_index_field_from_uid", None)
        if callable(field_from_uid):
            try:
                resolved_field = field_from_uid(segment.uid)
            except Exception:
                resolved_field = "name"
            if isinstance(resolved_field, str) and resolved_field.strip():
                cleaned_field = resolved_field.strip().lower()
                if self._NAME_INDEX_ALIAS_FIELD_RE.fullmatch(cleaned_field):
                    return "alias"
                return cleaned_field
        return "name"

    def _consistency_group_label_for_session(self, session: FileSession) -> str:
        if not self._is_name_index_session(session):
            return ""
        label_resolver = getattr(self, "_name_index_label", None)
        if callable(label_resolver):
            try:
                resolved = label_resolver(session)
            except Exception:
                resolved = ""
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip()
        raw_label = getattr(session, "name_index_label", "")
        if isinstance(raw_label, str):
            return raw_label.strip()
        return ""

    def _consistency_entry_label(
        self,
        session: FileSession,
        segment: DialogueSegment,
        block_index: int,
    ) -> str:
        entry_resolver = getattr(self, "_audit_entry_text_for_segment", None)
        if callable(entry_resolver):
            entry_label = str(entry_resolver(session, segment, block_index))
        elif not self._is_name_index_session(session):
            entry_label = f"Block {block_index}"
        else:
            name_index_label = self._name_index_label(session)
            actor_id = self._actor_id_from_uid(segment.uid)
            if actor_id is not None:
                entry_label = f"{name_index_label} ID {actor_id}"
            else:
                entry_label = f"{name_index_label} {block_index}"

        if not self._is_name_index_session(session):
            return entry_label
        field_name = self._consistency_name_index_field_name(segment)
        if not field_name or field_name == "name":
            return entry_label
        decorated = f"{entry_label} ({field_name})"
        if decorated == entry_label:
            return entry_label
        return decorated

    def _consistency_entry_locator(
        self,
        path_raw: str,
        entry_label: str,
    ) -> str:
        file_stem = self._consistency_entry_file_stem(path_raw)
        match = self._BLOCK_ENTRY_RE.fullmatch(entry_label.strip())
        if match is not None:
            return f"{file_stem}:{match.group(1)}"
        return f"{file_stem}:{entry_label.strip() or 'Entry'}"

    def _consistency_entry_display_label(
        self,
        path_raw: str,
        entry_label: str,
        translation: str,
        locator_width: int = 0,
    ) -> str:
        locator = self._consistency_entry_locator(path_raw, entry_label)
        padded_locator = (
            locator.ljust(locator_width) if locator_width > len(locator) else locator
        )

        translation_preview = (
            (translation or "")
            .replace("\r", "\\r")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        if not translation_preview:
            translation_preview = "(empty)"
        return f"{padded_locator} | {translation_preview}"

    def _consistency_target_overflow_metrics_for_segment(
        self,
        segment: DialogueSegment,
        target_lines: list[str],
    ) -> dict[str, float | int | bool]:
        thin_width_spin = getattr(self, "thin_width_spin", None)
        wide_width_spin = getattr(self, "wide_width_spin", None)
        max_lines_spin = getattr(self, "max_lines_spin", None)
        thin_width = int(thin_width_spin.value()) if thin_width_spin is not None else 42
        wide_width = int(wide_width_spin.value()) if wide_width_spin is not None else 48
        width_limit = thin_width if segment.has_face else wide_width
        row_limit = float(max(1, int(max_lines_spin.value()))) if max_lines_spin is not None else 4.0

        max_visible = 0
        for line in target_lines:
            max_visible = max(max_visible, visible_length(line))
        char_over = max(0, max_visible - width_limit)
        row_total = total_display_rows(target_lines)
        row_over = max(0.0, row_total - row_limit)
        return {
            "width_limit": width_limit,
            "max_visible": max_visible,
            "char_over": char_over,
            "row_limit": row_limit,
            "row_total": row_total,
            "row_over": row_over,
            "has_char_over": char_over > 0,
            "has_row_over": row_over > 0.0,
            "has_overflow": (char_over > 0) or (row_over > 0.0),
        }

    def _refresh_audit_consistency_target_overflow_status(self) -> None:
        if self.audit_consistency_target_edit is None:
            return

        target_edit = self.audit_consistency_target_edit
        self._resize_audit_consistency_target_editor_for_content()
        target_edit.setExtraSelections([])
        if self.audit_consistency_groups_list is None:
            return
        group_payload = self._audit_consistency_group_payload(
            self.audit_consistency_groups_list.currentItem()
        )
        if group_payload is None:
            return
        entries = group_payload.get("entries")
        if not isinstance(entries, list) or not entries:
            return

        segment: Optional[DialogueSegment] = None
        selected_session: Optional[FileSession] = None
        selected_payload = (
            self._audit_consistency_entry_payload(self.audit_consistency_entries_list.currentItem())
            if self.audit_consistency_entries_list is not None
            else None
        )
        if isinstance(selected_payload, dict):
            resolved_selected = self._find_consistency_entry_segment(selected_payload)
            if resolved_selected is not None:
                selected_session, _index, segment = resolved_selected
        if segment is None:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                resolved = self._find_consistency_entry_segment(entry)
                if resolved is None:
                    continue
                selected_session, _index, segment = resolved
                break
        if segment is None:
            return

        target_chunks = self._consistency_target_chunks_for_text(target_edit.toPlainText())
        if not target_chunks:
            return
        segments_for_chunks: list[DialogueSegment] = [segment]
        if isinstance(selected_payload, dict) and selected_session is not None:
            segment_uids_raw = selected_payload.get("segment_uids")
            if isinstance(segment_uids_raw, list):
                session_lookup = {
                    candidate.uid: candidate for candidate in selected_session.segments
                }
                resolved_segments: list[DialogueSegment] = []
                for uid_raw in segment_uids_raw:
                    if not isinstance(uid_raw, str) or not uid_raw:
                        continue
                    candidate = session_lookup.get(uid_raw)
                    if candidate is not None:
                        resolved_segments.append(candidate)
                if resolved_segments:
                    segments_for_chunks = resolved_segments

        normalize_for_segment = getattr(
            self, "_normalize_audit_translation_lines_for_segment", None
        )
        dark = is_dark_palette()
        overflow_bg = QColor("#7f1d1d" if dark else "#fee2e2")
        overflow_fg = QColor("#fecaca" if dark else "#991b1b")
        char_fmt = QTextCharFormat()
        char_fmt.setBackground(overflow_bg)
        char_fmt.setForeground(overflow_fg)
        line_fmt = QTextCharFormat()
        line_fmt.setBackground(overflow_bg)
        line_fmt.setForeground(overflow_fg)
        separator_fmt = QTextCharFormat()
        separator_bg = QColor("#334155" if dark else "#cbd5e1")
        separator_fmt.setBackground(separator_bg)
        separator_fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)

        selections: list[QTextEdit.ExtraSelection] = []
        document = target_edit.document()
        for separator_index in self._consistency_target_separator_display_indices(
            target_edit.toPlainText()
        ):
            block = document.findBlockByNumber(separator_index)
            if not block.isValid():
                continue
            cursor = QTextCursor(document)
            cursor.setPosition(block.position())
            cursor.setPosition(
                block.position() + len(block.text()),
                QTextCursor.MoveMode.KeepAnchor,
            )
            extra = QTextEdit.ExtraSelection()
            setattr(extra, "cursor", cursor)
            setattr(extra, "format", separator_fmt)
            selections.append(extra)

        for chunk_index, chunk in enumerate(target_chunks):
            chunk_lines_raw = chunk.get("lines")
            display_indices_raw = chunk.get("display_indices")
            if not isinstance(chunk_lines_raw, list):
                continue
            if not isinstance(display_indices_raw, list):
                continue
            display_indices = [
                idx for idx in display_indices_raw if isinstance(idx, int) and idx >= 0
            ]
            if not display_indices:
                continue
            chunk_lines = self._normalize_translation_lines(chunk_lines_raw)
            chunk_segment = (
                segments_for_chunks[chunk_index]
                if chunk_index < len(segments_for_chunks)
                else segments_for_chunks[-1]
            )

            if callable(normalize_for_segment):
                try:
                    normalized_chunk_raw = normalize_for_segment(
                        chunk_segment, chunk_lines
                    )
                except Exception:
                    normalized_chunk_raw = chunk_lines
                normalized_chunk = self._normalize_translation_lines(normalized_chunk_raw)
            else:
                normalized_chunk = chunk_lines

            metrics = self._consistency_target_overflow_metrics_for_segment(
                chunk_segment,
                normalized_chunk,
            )
            width_limit = int(metrics["width_limit"])
            row_limit = float(metrics["row_limit"])

            for line_index, line_text in enumerate(normalized_chunk):
                if line_index >= len(display_indices):
                    break
                display_line_index = display_indices[line_index]
                overflow_idx = first_overflow_char_index(line_text, width_limit)
                if overflow_idx is None:
                    continue
                block = document.findBlockByNumber(display_line_index)
                if not block.isValid():
                    continue
                block_text = block.text()
                if overflow_idx >= len(block_text):
                    continue
                cursor = QTextCursor(document)
                start_pos = block.position() + overflow_idx
                cursor.setPosition(start_pos)
                cursor.setPosition(
                    block.position() + len(block_text),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                extra = QTextEdit.ExtraSelection()
                setattr(extra, "cursor", cursor)
                setattr(extra, "format", char_fmt)
                selections.append(extra)

            kept_lines, overflow_lines = split_lines_by_row_budget(normalized_chunk, row_limit)
            overflow_start = len(kept_lines) if overflow_lines else len(normalized_chunk)
            for line_index in range(overflow_start, len(normalized_chunk)):
                if line_index >= len(display_indices):
                    break
                display_line_index = display_indices[line_index]
                block = document.findBlockByNumber(display_line_index)
                if not block.isValid():
                    continue
                block_text = block.text()
                cursor = QTextCursor(document)
                cursor.setPosition(block.position())
                cursor.setPosition(
                    block.position() + len(block_text),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                extra = QTextEdit.ExtraSelection()
                setattr(extra, "cursor", cursor)
                setattr(extra, "format", line_fmt)
                selections.append(extra)

        target_edit.setExtraSelections(selections)

    def _collect_audit_consistency_groups(
        self,
        only_inconsistent: bool,
        dialogue_only: bool,
        sort_mode: str,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        first_seen_order: dict[str, int] = {}
        group_labels: dict[str, set[str]] = {}
        source_order = 0
        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            for entry_row in self._consistency_logical_entry_rows_for_session(
                session,
                dialogue_only,
            ):
                segment = entry_row.get("anchor_segment")
                idx_raw = entry_row.get("anchor_index")
                segments_raw = entry_row.get("segments")
                if not isinstance(segment, DialogueSegment):
                    continue
                if not isinstance(idx_raw, int):
                    continue
                if not isinstance(segments_raw, list):
                    continue
                member_segments = [
                    candidate
                    for candidate in segments_raw
                    if isinstance(candidate, DialogueSegment)
                ]
                if not member_segments:
                    continue
                idx = idx_raw
                source_text = "\n".join(
                    self._consistency_source_lines_for_segment(segment))
                if not source_text.strip():
                    continue
                if source_text not in first_seen_order:
                    first_seen_order[source_text] = source_order
                    source_order += 1
                group_label = self._consistency_group_label_for_session(session)
                if group_label:
                    group_labels.setdefault(source_text, set()).add(group_label)
                translation_chunks = self._consistency_translation_chunks_for_entry(
                    session,
                    member_segments,
                )
                tl_text = self._consistency_translation_text_for_chunks(
                    translation_chunks,
                )
                segment_uids = [
                    member.uid
                    for member in member_segments
                    if isinstance(member.uid, str) and member.uid
                ]
                entry = {
                    "path": str(path),
                    "uid": segment.uid,
                    "entry": self._consistency_entry_label(session, segment, idx),
                    "translation": tl_text,
                    "segment_uids": segment_uids,
                    "translation_chunks": list(translation_chunks),
                    "chunk_line_counts": [
                        max(1, len(self._normalize_translation_lines(chunk)))
                        for chunk in translation_chunks
                    ],
                }
                speaker_jp, speaker_en = self._consistency_speakers_for_segment(segment)
                entry["speaker_jp"] = speaker_jp
                entry["speaker_en"] = speaker_en
                grouped.setdefault(source_text, []).append(entry)

        groups: list[dict[str, Any]] = []
        for source_text, entries in grouped.items():
            if len(entries) < 2:
                continue
            variants: Counter[tuple[str, ...]] = Counter()
            variant_text_by_key: dict[tuple[str, ...], str] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                chunks_raw = entry.get("translation_chunks")
                chunks: list[str] = []
                if isinstance(chunks_raw, list):
                    for raw_chunk in chunks_raw:
                        if isinstance(raw_chunk, str):
                            chunks.append(raw_chunk)
                if not chunks:
                    chunks.append(str(entry.get("translation", "")))
                variant_key = tuple(chunks)
                variants[variant_key] += 1
                variant_text_by_key.setdefault(
                    variant_key,
                    str(entry.get("translation", "")),
                )
            unique_count = len(variants)
            if only_inconsistent and unique_count <= 1:
                continue
            most_common_text = ""
            if variants:
                most_common_variant = max(
                    variants.items(),
                    key=lambda kv: (
                        kv[1],
                        bool(variant_text_by_key.get(kv[0], "").strip()),
                        len(variant_text_by_key.get(kv[0], "")),
                    ),
                )[0]
                most_common_text = variant_text_by_key.get(most_common_variant, "")
            groups.append(
                {
                    "source_text": source_text,
                    "label_hint": " / ".join(
                        sorted(group_labels.get(source_text, set()))
                    ),
                    "entries": entries,
                    "entry_count": len(entries),
                    "variant_count": unique_count,
                    "most_common_translation": most_common_text,
                    "first_seen_order": first_seen_order.get(source_text, 0),
                }
            )

        if sort_mode == "occurrence":
            groups.sort(
                key=lambda row: (
                    -int(row.get("entry_count", 0)),
                    -int(row.get("variant_count", 0)),
                    int(row.get("first_seen_order", 0)),
                )
            )
        elif sort_mode == "variants":
            groups.sort(
                key=lambda row: (
                    -int(row.get("variant_count", 0)),
                    -int(row.get("entry_count", 0)),
                    int(row.get("first_seen_order", 0)),
                )
            )
        elif sort_mode == "alphabetical":
            groups.sort(
                key=lambda row: (
                    str(row.get("source_text", "")).casefold(),
                    -int(row.get("entry_count", 0)),
                )
            )
        else:
            groups.sort(
                key=lambda row: (
                    int(row.get("first_seen_order", 0)),
                    -int(row.get("entry_count", 0)),
                )
            )
        return groups

    def _refresh_audit_consistency_entries(self) -> None:
        if (
            self.audit_consistency_groups_list is None
            or self.audit_consistency_entries_list is None
            or self.audit_consistency_source_edit is None
            or self.audit_consistency_target_edit is None
            or self.audit_consistency_goto_btn is None
            or self.audit_consistency_apply_btn is None
            or self.audit_consistency_use_common_btn is None
        ):
            return
        group_payload = self._audit_consistency_group_payload(
            self.audit_consistency_groups_list.currentItem()
        )
        self.audit_consistency_entries_list.clear()
        self.audit_consistency_goto_btn.setEnabled(False)
        self.audit_consistency_apply_btn.setEnabled(group_payload is not None)
        self.audit_consistency_use_common_btn.setEnabled(group_payload is not None)
        if group_payload is None:
            self.audit_consistency_source_edit.setPlainText("")
            self.audit_consistency_target_edit.setPlainText("")
            self._refresh_audit_consistency_target_overflow_status()
            return
        source_text = group_payload.get("source_text")
        if isinstance(source_text, str):
            self.audit_consistency_source_edit.setPlainText(source_text)
        else:
            self.audit_consistency_source_edit.setPlainText("")

        entries = group_payload.get("entries")
        if not isinstance(entries, list):
            self.audit_consistency_source_edit.setPlainText("")
            self.audit_consistency_target_edit.setPlainText("")
            self._refresh_audit_consistency_target_overflow_status()
            return
        variants = {
            str(entry.get("translation", ""))
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("translation"), str)
            and str(entry.get("translation", "")).strip()
        }
        color_map = self._consistency_variant_color_map(variants)
        foreground = self._consistency_variant_fg()
        parsed_entries: list[dict[str, Any]] = []
        max_locator_width = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path_raw = entry.get("path")
            uid_raw = entry.get("uid")
            entry_label = entry.get("entry")
            translation = entry.get("translation")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            if not isinstance(uid_raw, str) or not uid_raw:
                continue
            if not isinstance(entry_label, str):
                entry_label = "Entry"
            if not isinstance(translation, str):
                translation = ""
            speaker_jp = str(entry.get("speaker_jp", "")).strip()
            speaker_en = str(entry.get("speaker_en", "")).strip()
            segment_uids_raw = entry.get("segment_uids")
            segment_uids: list[str] = []
            if isinstance(segment_uids_raw, list):
                for raw_uid in segment_uids_raw:
                    if isinstance(raw_uid, str) and raw_uid:
                        segment_uids.append(raw_uid)
            if not segment_uids:
                segment_uids = [uid_raw]
            translation_chunks_raw = entry.get("translation_chunks")
            translation_chunks: list[str] = []
            if isinstance(translation_chunks_raw, list):
                for raw_chunk in translation_chunks_raw:
                    if isinstance(raw_chunk, str):
                        translation_chunks.append(raw_chunk)
            if not translation_chunks:
                translation_chunks = [translation]
            chunk_line_counts_raw = entry.get("chunk_line_counts")
            chunk_line_counts: list[int] = []
            if isinstance(chunk_line_counts_raw, list):
                for raw_count in chunk_line_counts_raw:
                    if isinstance(raw_count, int):
                        chunk_line_counts.append(max(1, raw_count))
            if not chunk_line_counts:
                chunk_line_counts = [
                    max(1, len(self._normalize_translation_lines(chunk)))
                    for chunk in translation_chunks
                ]
            locator = self._consistency_entry_locator(path_raw, entry_label)
            max_locator_width = max(max_locator_width, len(locator))
            parsed_entries.append(
                {
                    "path": path_raw,
                    "uid": uid_raw,
                    "entry": entry_label,
                    "translation": translation,
                    "speaker_jp": speaker_jp,
                    "speaker_en": speaker_en,
                    "segment_uids": segment_uids,
                    "translation_chunks": translation_chunks,
                    "chunk_line_counts": chunk_line_counts,
                }
            )

        for entry in parsed_entries:
            path_raw = entry["path"]
            uid_raw = entry["uid"]
            entry_label = entry["entry"]
            translation = entry["translation"]
            speaker_jp = entry["speaker_jp"]
            speaker_en = entry["speaker_en"]
            segment_uids = entry["segment_uids"]
            translation_chunks = entry["translation_chunks"]
            chunk_line_counts = entry["chunk_line_counts"]
            label = self._consistency_entry_display_label(
                path_raw,
                entry_label,
                translation,
                locator_width=max_locator_width,
            )
            item = QListWidgetItem(label)
            item.setBackground(
                QBrush(
                    self._consistency_variant_bg(
                        translation,
                        color_map,
                    )
                )
            )
            item.setForeground(QBrush(foreground))
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "path": path_raw,
                    "uid": uid_raw,
                    "entry": entry_label,
                    "translation": translation,
                    "speaker_jp": speaker_jp,
                    "speaker_en": speaker_en,
                    "segment_uids": segment_uids,
                    "translation_chunks": translation_chunks,
                    "chunk_line_counts": chunk_line_counts,
                },
            )
            self.audit_consistency_entries_list.addItem(item)

        if self.audit_consistency_entries_list.count() > 0:
            self.audit_consistency_entries_list.setCurrentRow(0)
            first_payload = self._audit_consistency_entry_payload(
                self.audit_consistency_entries_list.currentItem()
            )
            target_value = self._consistency_target_display_text_for_payload(
                first_payload
            )
            self.audit_consistency_target_edit.setPlainText(target_value)
            self._refresh_audit_consistency_target_overflow_status()
            self._refresh_audit_consistency_neighbors_preview()
            return
        self.audit_consistency_target_edit.setPlainText("")
        self._refresh_audit_consistency_target_overflow_status()
        self._refresh_audit_consistency_neighbors_preview()

    def _on_audit_consistency_entry_selected(self) -> None:
        if (
            self.audit_consistency_entries_list is None
            or self.audit_consistency_target_edit is None
        ):
            return
        payload = self._audit_consistency_entry_payload(
            self.audit_consistency_entries_list.currentItem()
        )
        if payload is None:
            return
        target_value = self._consistency_target_display_text_for_payload(payload)
        current_target = self.audit_consistency_target_edit.toPlainText()
        # Keep a non-empty draft target while browsing empty entries.
        if target_value.strip() or not current_target.strip():
            self.audit_consistency_target_edit.setPlainText(target_value)
        self._refresh_audit_consistency_target_overflow_status()
        self._refresh_audit_consistency_neighbors_preview()

    def _refresh_audit_consistency_panel(
        self,
        preferred_source: Optional[str] = None,
        preferred_row: Optional[int] = None,
    ) -> None:
        if (
            self.audit_consistency_only_inconsistent_check is None
            or self.audit_consistency_dialogue_only_check is None
            or self.audit_consistency_sort_combo is None
            or self.audit_consistency_groups_list is None
            or self.audit_consistency_status_label is None
        ):
            return
        only_inconsistent = self.audit_consistency_only_inconsistent_check.isChecked()
        dialogue_only = self.audit_consistency_dialogue_only_check.isChecked()
        sort_mode_raw = self.audit_consistency_sort_combo.currentData()
        sort_mode = sort_mode_raw if isinstance(sort_mode_raw, str) else "source_order"
        groups = self._collect_audit_consistency_groups(
            only_inconsistent,
            dialogue_only,
            sort_mode,
        )
        self.audit_consistency_groups_list.clear()
        selected_row = -1
        total_entries = 0
        for idx, group in enumerate(groups):
            source_text = str(group.get("source_text", ""))
            label_hint = str(group.get("label_hint", "")).strip()
            count = int(group.get("entry_count", 0))
            variants = int(group.get("variant_count", 0))
            total_entries += count
            if label_hint:
                label = (
                    f"x{count} | variants: {variants} | {label_hint} | "
                    f"{preview_text(source_text, 96)}"
                )
            else:
                label = (
                    f"x{count} | variants: {variants} | "
                    f"{preview_text(source_text, 96)}"
                )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.audit_consistency_groups_list.addItem(item)
            if preferred_source and source_text == preferred_source:
                if selected_row < 0:
                    selected_row = idx

        if groups:
            if selected_row < 0:
                if preferred_row is not None:
                    selected_row = max(0, min(int(preferred_row), len(groups) - 1))
                else:
                    selected_row = 0
            self.audit_consistency_groups_list.setCurrentRow(selected_row)
        self.audit_consistency_status_label.setText(
            f"Duplicate groups: {len(groups)} | Duplicate entries: {total_entries}"
        )
        self._refresh_audit_consistency_entries()
        self._refresh_audit_consistency_target_overflow_status()
        self._refresh_audit_consistency_neighbors_preview()

    def _use_most_common_audit_consistency_translation(self) -> None:
        if self.audit_consistency_groups_list is None or self.audit_consistency_target_edit is None:
            return
        payload = self._audit_consistency_group_payload(
            self.audit_consistency_groups_list.currentItem()
        )
        if payload is None:
            self.statusBar().showMessage("Select a duplicate group first.")
            return
        target = payload.get("most_common_translation")
        if not isinstance(target, str):
            target = ""
        self.audit_consistency_target_edit.setPlainText(target)
        self._refresh_audit_consistency_target_overflow_status()
        self.statusBar().showMessage("Loaded most-common translation as target.")

    def _confirm_and_apply_audit_consistency_target_to_group(self) -> None:
        if self.audit_consistency_groups_list is None:
            return
        payload = self._audit_consistency_group_payload(
            self.audit_consistency_groups_list.currentItem()
        )
        if payload is None:
            self.statusBar().showMessage("Select a duplicate group first.")
            return
        source_text = str(payload.get("source_text", "")).strip()
        label_hint = str(payload.get("label_hint", "")).strip()
        target_preview = "(empty)"
        if self.audit_consistency_target_edit is not None:
            raw_target = self.audit_consistency_target_edit.toPlainText()
            if raw_target.strip():
                target_preview = preview_text(raw_target, 120)
        prompt_lines = ["Apply current target translation to this duplicate group?", ""]
        if label_hint:
            prompt_lines.append(f"Labels: {label_hint}")
        prompt_lines.append(f"Target: {target_preview}")
        prompt_lines.append(preview_text(source_text, 120))
        prompt = "\n".join(prompt_lines)
        parent_widget = cast(
            Optional[QWidget],
            getattr(self, "audit_window", None),
        )
        answer = QMessageBox.question(
            parent_widget,
            "Confirm Apply",
            prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._focus_audit_consistency_groups_list()
            return
        self._apply_audit_consistency_target_to_group(advance_to_next=True)
        self._focus_audit_consistency_groups_list()

    def _go_to_selected_audit_consistency_entry(self) -> None:
        if self.audit_consistency_entries_list is None:
            return
        payload = self._audit_consistency_entry_payload(
            self.audit_consistency_entries_list.currentItem()
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

    def _apply_audit_consistency_target_to_group(
        self,
        advance_to_next: bool = True,
    ) -> None:
        if (
            self.audit_consistency_groups_list is None
            or self.audit_consistency_target_edit is None
        ):
            return
        current_row = self.audit_consistency_groups_list.currentRow()
        next_row = current_row
        next_source_key = ""
        if advance_to_next and current_row >= 0:
            next_row = min(
                current_row + 1,
                max(0, self.audit_consistency_groups_list.count() - 1),
            )
            next_item = self.audit_consistency_groups_list.item(next_row)
            next_payload = self._audit_consistency_group_payload(next_item)
            if isinstance(next_payload, dict):
                next_source_raw = next_payload.get("source_text")
                if isinstance(next_source_raw, str):
                    next_source_key = next_source_raw
        group_payload = self._audit_consistency_group_payload(
            self.audit_consistency_groups_list.currentItem()
        )
        if group_payload is None:
            self.statusBar().showMessage("Select a duplicate group first.")
            return
        source_key_raw = group_payload.get("source_text")
        source_key = source_key_raw if isinstance(source_key_raw, str) else ""
        entries = group_payload.get("entries")
        if not isinstance(entries, list) or not entries:
            self.statusBar().showMessage("Selected group is empty.")
            return

        target_text = self.audit_consistency_target_edit.toPlainText()
        target_chunks_payload = self._consistency_target_chunks_for_text(target_text)
        target_chunks_lines: list[list[str]] = []
        for chunk in target_chunks_payload:
            chunk_lines_raw = chunk.get("lines")
            if isinstance(chunk_lines_raw, list):
                target_chunks_lines.append(self._normalize_translation_lines(chunk_lines_raw))
        if not target_chunks_lines:
            target_chunks_lines = [self._normalize_translation_lines(target_text)]
        target_lines = [
            line
            for chunk_lines in target_chunks_lines
            for line in chunk_lines
        ]
        selected_pattern_counts: list[int] = []
        if len(target_chunks_lines) > 1:
            selected_pattern_counts = [
                max(1, len(chunk_lines))
                for chunk_lines in target_chunks_lines
            ]
        selected_entry_payload: Optional[dict[str, Any]] = None
        if self.audit_consistency_entries_list is not None:
            selected_entry_payload = self._audit_consistency_entry_payload(
                self.audit_consistency_entries_list.currentItem()
            )
        if isinstance(selected_entry_payload, dict):
            selected_pattern_counts = self._consistency_chunk_line_counts_from_payload(
                selected_entry_payload
            )
        if not selected_pattern_counts and entries:
            first_entry = entries[0]
            if isinstance(first_entry, dict):
                selected_pattern_counts = self._consistency_chunk_line_counts_from_payload(
                    first_entry
                )
        if not selected_pattern_counts:
            selected_pattern_counts = [max(1, len(target_lines))]

        touched_paths: set[Path] = set()
        touched_current = False
        structure_changed_paths: set[Path] = set()
        current_focus_uid: Optional[str] = None
        changed_entries = 0
        segment_lookup_by_path: dict[Path, dict[str, DialogueSegment]] = {}
        normalize_for_segment = getattr(
            self, "_normalize_audit_translation_lines_for_segment", None
        )
        compose_resolver = getattr(self, "_compose_translation_lines_for_segment", None)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path_raw = entry.get("path")
            uid_raw = entry.get("uid")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            if not isinstance(uid_raw, str) or not uid_raw:
                continue
            segment_uids_raw = entry.get("segment_uids")
            segment_uids: list[str] = []
            if isinstance(segment_uids_raw, list):
                for raw_uid in segment_uids_raw:
                    if isinstance(raw_uid, str) and raw_uid:
                        segment_uids.append(raw_uid)
            if not segment_uids:
                segment_uids = [uid_raw]
            path = Path(path_raw)
            session = self.sessions.get(path)
            if session is None:
                continue
            lookup = segment_lookup_by_path.get(path)
            if lookup is None:
                lookup = {segment.uid: segment for segment in session.segments}
                segment_lookup_by_path[path] = lookup
            target_segments, structure_changed = self._consistency_align_entry_chain_segments(
                session,
                uid_raw,
                segment_uids,
                len(selected_pattern_counts),
                lookup,
            )
            if not target_segments:
                continue
            target_lines_for_entry = self._consistency_split_target_lines_for_chain(
                target_lines,
                len(target_segments),
                selected_pattern_counts,
            )
            changed_this_entry = bool(structure_changed)
            for segment_index, target_segment in enumerate(target_segments):
                segment_target_lines = (
                    target_lines_for_entry[segment_index]
                    if segment_index < len(target_lines_for_entry)
                    else [""]
                )
                current_lines = self._consistency_translation_lines_for_segment(
                    target_segment
                )
                if callable(normalize_for_segment):
                    try:
                        target_lines_for_segment_raw = normalize_for_segment(
                            target_segment,
                            segment_target_lines,
                        )
                    except Exception:
                        target_lines_for_segment_raw = list(segment_target_lines)
                else:
                    target_lines_for_segment_raw = list(segment_target_lines)
                target_lines_for_segment = self._normalize_translation_lines(
                    target_lines_for_segment_raw
                )
                if current_lines == target_lines_for_segment:
                    continue
                stored_lines = list(target_lines_for_segment)
                if callable(compose_resolver):
                    try:
                        composed = compose_resolver(target_segment, target_lines_for_segment)
                    except Exception:
                        composed = stored_lines
                    if isinstance(composed, list):
                        stored_lines = self._normalize_translation_lines(composed)
                target_segment.translation_lines = list(stored_lines)
                changed_this_entry = True
            if not changed_this_entry:
                continue
            changed_entries += 1
            touched_paths.add(path)
            if structure_changed:
                structure_changed_paths.add(path)
            if self.current_path is not None and path == self.current_path:
                touched_current = True
                if current_focus_uid is None:
                    current_focus_uid = uid_raw

        if changed_entries <= 0:
            self.statusBar().showMessage("No translations changed in this group.")
            if advance_to_next:
                preferred_source = (
                    next_source_key if next_source_key else source_key
                )
                self._refresh_audit_consistency_panel(
                    preferred_source=preferred_source,
                    preferred_row=next_row,
                )
                self._focus_audit_consistency_groups_list()
            return

        for path in touched_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            self._refresh_dirty_state(session)

        self._invalidate_audit_caches()
        self._refresh_active_non_consistency_audit_panel()
        if touched_current and self.current_path is not None:
            current_session = self.sessions.get(self.current_path)
            did_structural_refresh = False
            if (
                current_session is not None
                and self.current_path in structure_changed_paths
            ):
                fast_structure_refresh = getattr(
                    self, "_refresh_after_structure_change_without_full_rerender", None
                )
                if callable(fast_structure_refresh):
                    try:
                        did_structural_refresh = bool(
                            fast_structure_refresh(
                                current_session,
                                focus_uid=current_focus_uid,
                                preserve_scroll=True,
                            )
                        )
                    except TypeError:
                        did_structural_refresh = bool(
                            fast_structure_refresh(
                                current_session,
                                focus_uid=current_focus_uid,
                            )
                        )
                if not did_structural_refresh and current_session is not None:
                    render_session = getattr(self, "_render_session", None)
                    if callable(render_session):
                        try:
                            render_session(
                                current_session,
                                focus_uid=current_focus_uid,
                                preserve_scroll=True,
                            )
                        except TypeError:
                            render_session(current_session, focus_uid=current_focus_uid)
                        did_structural_refresh = True
            if not did_structural_refresh:
                rerender_near_viewport = getattr(
                    self, "_rerender_blocks_near_viewport", None
                )
                if callable(rerender_near_viewport):
                    try:
                        rerender_near_viewport(overscan_px=240)
                    except TypeError:
                        rerender_near_viewport()
        self._refresh_translator_detail_panel()
        preferred_source = (
            next_source_key if advance_to_next and next_source_key else source_key
        )
        preferred_row = next_row if advance_to_next else None
        self._refresh_audit_consistency_panel(
            preferred_source=preferred_source,
            preferred_row=preferred_row,
        )
        if advance_to_next:
            self._focus_audit_consistency_groups_list()
        self.statusBar().showMessage(
            f"Synchronized translation across {changed_entries} duplicate entries."
        )

    def _focus_audit_consistency_groups_list(self) -> None:
        if self.audit_consistency_groups_list is None:
            return
        groups_list_widget = self.audit_consistency_groups_list
        entries_list_widget = self.audit_consistency_entries_list

        def apply_focus() -> None:
            if self.audit_consistency_groups_list is None:
                return
            audit_window = getattr(self, "audit_window", None)
            if audit_window is not None and audit_window.isVisible():
                audit_window.raise_()
                audit_window.activateWindow()
            target_widget = groups_list_widget
            if entries_list_widget is not None and entries_list_widget.count() > 0:
                target_widget = entries_list_widget
            if target_widget.currentRow() < 0 and target_widget.count() > 0:
                target_widget.setCurrentRow(0)
            target_widget.setFocus(Qt.FocusReason.OtherFocusReason)

        apply_focus()
        for delay_ms in (0, 30, 120):
            QTimer.singleShot(delay_ms, apply_focus)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def _refresh_active_non_consistency_audit_panel(self) -> None:
        tab_index_resolver = getattr(self, "_current_audit_tab_index", None)
        if not callable(tab_index_resolver):
            return
        try:
            active_tab = tab_index_resolver()
        except Exception:
            return
        if not isinstance(active_tab, int):
            return

        sanitize_tab = getattr(self, "_AUDIT_TAB_SANITIZE", None)
        if isinstance(sanitize_tab, int) and active_tab == sanitize_tab:
            self._refresh_audit_sanitize_panel()
            return

        control_tab = getattr(self, "_AUDIT_TAB_CONTROL_MISMATCH", None)
        if isinstance(control_tab, int) and active_tab == control_tab:
            self._refresh_audit_control_mismatch_panel()
            return

        collision_tab = getattr(self, "_AUDIT_TAB_TRANSLATION_COLLISION", None)
        if isinstance(collision_tab, int) and active_tab == collision_tab:
            self._refresh_audit_translation_collision_panel()
            return

        name_tab = getattr(self, "_AUDIT_TAB_NAME_CONSISTENCY", None)
        if isinstance(name_tab, int) and active_tab == name_tab:
            self._refresh_audit_name_consistency_panel()
