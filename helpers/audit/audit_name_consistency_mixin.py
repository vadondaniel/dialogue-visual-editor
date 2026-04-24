from __future__ import annotations

import html
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import preview_text, strip_control_tokens


class _AuditNameConsistencyHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditNameConsistencyMixin(_AuditNameConsistencyHostTypingFallback):
    def _name_consistency_cache_generation(self) -> int:
        generation_resolver = getattr(self, "_audit_generation", None)
        if callable(generation_resolver):
            try:
                resolved = generation_resolver("name_consistency")
            except Exception:
                resolved = None
            if isinstance(resolved, (int, float, str)):
                try:
                    return int(resolved)
                except Exception:
                    pass
        return int(getattr(self, "audit_cache_generation", 0))

    def _name_consistency_request_key(
        self,
        request: Optional[dict[str, Any]],
    ) -> tuple[Any, ...]:
        if not isinstance(request, dict):
            return ()
        return (
            request.get("generation"),
            request.get("dialogue_only"),
            request.get("only_discrepancies"),
            request.get("filter_text"),
            request.get("sort_mode"),
        )

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

    def _name_consistency_match_key(self, value: str) -> str:
        plain = self._name_consistency_plain_text(value)
        return re.sub(r"\s+", "", plain).casefold()

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

    def _name_consistency_source_lines_for_segment(
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

    def _name_consistency_translation_lines_for_segment(
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
                tl_lines_raw = normalize_for_segment(
                    segment,
                    segment.translation_lines,
                )
            except Exception:
                tl_lines_raw = self._normalize_translation_lines(
                    segment.translation_lines
                )
        else:
            tl_lines_raw = self._normalize_translation_lines(segment.translation_lines)
        return self._normalize_translation_lines(tl_lines_raw)

    def _name_consistency_scan_groups(
        self,
        session: FileSession,
    ) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        leading_translation_only: list[DialogueSegment] = []
        for idx, segment in enumerate(session.segments, start=1):
            if bool(getattr(segment, "translation_only", False)):
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

    def _name_consistency_source_lines_for_group(
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
        return self._name_consistency_source_lines_for_segment(anchor_segment)

    def _name_consistency_translation_lines_for_group(
        self,
        session: FileSession,
        anchor_segment: DialogueSegment,
        group_segments: list[DialogueSegment],
    ) -> list[str]:
        logical_translation_resolver = getattr(
            self,
            "_logical_translation_lines_for_segment",
            None,
        )
        if callable(logical_translation_resolver):
            resolved_translation: Any = None
            try:
                resolved_translation = logical_translation_resolver(
                    anchor_segment,
                    session=session,
                )
            except TypeError:
                try:
                    resolved_translation = logical_translation_resolver(
                        anchor_segment
                    )
                except Exception:
                    resolved_translation = None
            except Exception:
                resolved_translation = None
            if isinstance(resolved_translation, list):
                normalized = self._normalize_translation_lines(resolved_translation)
                normalize_for_segment = getattr(
                    self, "_normalize_audit_translation_lines_for_segment", None
                )
                if callable(normalize_for_segment):
                    try:
                        normalized_raw = normalize_for_segment(anchor_segment, normalized)
                    except Exception:
                        normalized_raw = normalized
                    return self._normalize_translation_lines(normalized_raw) or [""]
                return normalized or [""]

        lines: list[str] = []
        for segment in group_segments:
            lines.extend(self._name_consistency_translation_lines_for_segment(segment))
        return lines if lines else [""]

    def _collect_misc_glossary_entries(
        self,
        path_sessions: Optional[list[tuple[Path, FileSession]]] = None,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        field_resolver = getattr(self, "_name_index_field_from_uid", None)
        rows: list[tuple[Path, FileSession]] = []
        if isinstance(path_sessions, list):
            rows = path_sessions
        else:
            snapshot_resolver = getattr(self, "_audit_path_sessions_snapshot", None)
            if callable(snapshot_resolver):
                try:
                    snapshot_rows = snapshot_resolver()
                except Exception:
                    snapshot_rows = None
                if isinstance(snapshot_rows, list):
                    rows = [
                        cast(tuple[Path, FileSession], row)
                        for row in snapshot_rows
                        if isinstance(row, tuple)
                        and len(row) == 2
                        and isinstance(row[0], Path)
                        and isinstance(row[1], FileSession)
                    ]
            if not rows:
                for path in getattr(self, "file_paths", []):
                    session = getattr(self, "sessions", {}).get(path)
                    if isinstance(path, Path) and isinstance(session, FileSession):
                        rows.append((path, session))
        for path, session in rows:
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
                source_lines = self._name_consistency_source_lines_for_segment(segment)
                tl_lines = self._name_consistency_translation_lines_for_segment(segment)
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

    def _collect_dialogue_rows(
        self,
        dialogue_only: bool,
        path_sessions: Optional[list[tuple[Path, FileSession]]] = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        scan_rows: list[tuple[Path, FileSession]] = []
        if isinstance(path_sessions, list):
            scan_rows = path_sessions
        else:
            snapshot_resolver = getattr(self, "_audit_path_sessions_snapshot", None)
            if callable(snapshot_resolver):
                try:
                    snapshot_rows = snapshot_resolver()
                except Exception:
                    snapshot_rows = None
                if isinstance(snapshot_rows, list):
                    scan_rows = [
                        cast(tuple[Path, FileSession], row)
                        for row in snapshot_rows
                        if isinstance(row, tuple)
                        and len(row) == 2
                        and isinstance(row[0], Path)
                        and isinstance(row[1], FileSession)
                    ]
            if not scan_rows:
                for path in getattr(self, "file_paths", []):
                    session = getattr(self, "sessions", {}).get(path)
                    if isinstance(path, Path) and isinstance(session, FileSession):
                        scan_rows.append((path, session))
        for path, session in scan_rows:
            if self._is_name_index_session(session):
                continue
            for group in self._name_consistency_scan_groups(session):
                segment = cast(DialogueSegment, group["anchor_segment"])
                block_index = int(group["anchor_index"])
                group_segments = cast(list[DialogueSegment], group["segments"])
                if dialogue_only and not bool(getattr(segment, "is_structural_dialogue", False)):
                    continue
                source_lines = self._name_consistency_source_lines_for_group(
                    session,
                    segment,
                )
                tl_lines = self._name_consistency_translation_lines_for_group(
                    session,
                    segment,
                    group_segments,
                )
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
                source_fold = self._name_consistency_match_key(source_block)
                if not source_fold:
                    continue
                tl_fold = self._name_consistency_match_key(tl_block)
                line_rows: list[tuple[int, str, str]] = []
                max_len = max(len(source_lines), len(tl_lines))
                for line_index in range(max_len):
                    source_raw = source_lines[line_index] if line_index < len(source_lines) else ""
                    source_line = source_raw if isinstance(source_raw, str) else ""
                    source_line_fold = self._name_consistency_match_key(source_line)
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

    def _collect_audit_name_consistency_base(
        self,
        dialogue_only: bool,
        path_sessions: Optional[list[tuple[Path, FileSession]]] = None,
    ) -> dict[str, Any]:
        glossary_entries = self._collect_misc_glossary_entries(
            path_sessions=path_sessions
        )
        dialogue_rows = self._collect_dialogue_rows(
            dialogue_only=dialogue_only,
            path_sessions=path_sessions,
        )
        return {
            "glossary_entries": glossary_entries,
            "dialogue_rows": dialogue_rows,
        }

    def _collect_audit_name_consistency_groups(
        self,
        dialogue_only: bool,
        only_discrepancies: bool = True,
        filter_text: str = "",
        sort_mode: str = "hits_desc",
        base_payload: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        glossary_entries: list[dict[str, Any]] = []
        dialogue_rows: list[dict[str, Any]] = []
        if isinstance(base_payload, dict):
            glossary_raw = base_payload.get("glossary_entries")
            if isinstance(glossary_raw, list):
                glossary_entries = [
                    item for item in glossary_raw if isinstance(item, dict)
                ]
            dialogue_raw = base_payload.get("dialogue_rows")
            if isinstance(dialogue_raw, list):
                dialogue_rows = [item for item in dialogue_raw if isinstance(item, dict)]
        if not glossary_entries or not dialogue_rows:
            fallback_payload = self._collect_audit_name_consistency_base(
                dialogue_only=dialogue_only
            )
            glossary_raw = fallback_payload.get("glossary_entries")
            if isinstance(glossary_raw, list):
                glossary_entries = [
                    item for item in glossary_raw if isinstance(item, dict)
                ]
            dialogue_raw = fallback_payload.get("dialogue_rows")
            if isinstance(dialogue_raw, list):
                dialogue_rows = [item for item in dialogue_raw if isinstance(item, dict)]
        if not glossary_entries:
            return []
        if not dialogue_rows:
            return []
        filter_fold = self._name_consistency_match_key(filter_text)
        groups: list[dict[str, Any]] = []
        for glossary_entry in glossary_entries:
            source_term = str(glossary_entry.get("source_term", ""))
            expected_tl = str(glossary_entry.get("expected_tl", ""))
            misc_context = str(glossary_entry.get("misc_context", ""))
            misc_path = str(glossary_entry.get("misc_path", ""))
            misc_entry = str(glossary_entry.get("misc_entry", ""))
            source_term_fold = self._name_consistency_match_key(source_term)
            expected_tl_fold = self._name_consistency_match_key(expected_tl)
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
                )
                combined = self._name_consistency_match_key(combined)
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

    def _compute_audit_name_consistency_groups_worker(
        self,
        path_sessions: list[tuple[Path, FileSession]],
        dialogue_only: bool,
        only_discrepancies: bool,
        filter_text: str,
        sort_mode: str,
        base_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        effective_base = (
            base_payload
            if isinstance(base_payload, dict)
            else self._collect_audit_name_consistency_base(
                dialogue_only=dialogue_only,
                path_sessions=path_sessions,
            )
        )
        groups = self._collect_audit_name_consistency_groups(
            dialogue_only=dialogue_only,
            only_discrepancies=only_discrepancies,
            filter_text=filter_text,
            sort_mode=sort_mode,
            base_payload=effective_base,
        )
        return {
            "base_payload": effective_base,
            "groups": groups,
        }

    def _queue_audit_name_consistency_worker(self, request: dict[str, Any]) -> None:
        request_key = self._name_consistency_request_key(request)
        if request_key == self._name_consistency_request_key(
            self.audit_name_consistency_worker_running_request
        ):
            return
        if request_key == self._name_consistency_request_key(
            self.audit_name_consistency_worker_pending_request
        ):
            return
        self.audit_name_consistency_worker_pending_request = request
        if self.audit_name_consistency_worker_future is None:
            self._start_next_audit_name_consistency_worker()

    def _start_next_audit_name_consistency_worker(self) -> None:
        request = self.audit_name_consistency_worker_pending_request
        if request is None:
            return
        self.audit_name_consistency_worker_pending_request = None
        self.audit_name_consistency_worker_running_request = request
        try:
            self.audit_name_consistency_worker_future = self.audit_worker_executor.submit(
                self._compute_audit_name_consistency_groups_worker,
                cast(list[tuple[Path, FileSession]], request["path_sessions"]),
                bool(request["dialogue_only"]),
                bool(request["only_discrepancies"]),
                str(request["filter_text"]),
                str(request["sort_mode"]),
                cast(Optional[dict[str, Any]], request.get("base_payload")),
            )
        except Exception:
            self.audit_name_consistency_worker_future = None
            self.audit_name_consistency_worker_running_request = None
            if self.audit_name_consistency_status_label is not None:
                self.audit_name_consistency_status_label.setText(
                    "Glossary consistency scan failed."
                )
            return
        self.audit_name_consistency_worker_timer.start(18)

    def _poll_audit_name_consistency_worker(self) -> None:
        future = self.audit_name_consistency_worker_future
        if future is None:
            if self.audit_name_consistency_worker_pending_request is not None:
                self._start_next_audit_name_consistency_worker()
            return
        if not future.done():
            self.audit_name_consistency_worker_timer.start(18)
            return

        running_request = self.audit_name_consistency_worker_running_request
        self.audit_name_consistency_worker_future = None
        self.audit_name_consistency_worker_running_request = None
        try:
            payload = cast(dict[str, Any], future.result())
        except Exception:
            if self.audit_name_consistency_worker_pending_request is not None:
                self._start_next_audit_name_consistency_worker()
            if self.audit_name_consistency_status_label is not None:
                self.audit_name_consistency_status_label.setText(
                    "Glossary consistency scan failed."
                )
            return
        if self.audit_name_consistency_worker_pending_request is not None:
            self._start_next_audit_name_consistency_worker()
            return
        if not isinstance(running_request, dict):
            return
        generation = int(running_request.get("generation", -1))
        dialogue_only = bool(running_request.get("dialogue_only", True))
        only_discrepancies = bool(running_request.get("only_discrepancies", True))
        filter_text = str(running_request.get("filter_text", ""))
        sort_mode = str(running_request.get("sort_mode", "hits_desc"))
        if generation != self._name_consistency_cache_generation():
            return
        if (
            self.audit_name_consistency_dialogue_only_check is None
            or self.audit_name_consistency_only_discrepancy_check is None
        ):
            return
        current_filter_text = ""
        if self.audit_name_consistency_filter_edit is not None:
            current_filter_text = self.audit_name_consistency_filter_edit.text()
        current_sort_mode = "hits_desc"
        if self.audit_name_consistency_sort_combo is not None:
            sort_data = self.audit_name_consistency_sort_combo.currentData()
            if isinstance(sort_data, str) and sort_data.strip():
                current_sort_mode = sort_data
        if (
            self.audit_name_consistency_dialogue_only_check.isChecked()
            != dialogue_only
            or self.audit_name_consistency_only_discrepancy_check.isChecked()
            != only_discrepancies
            or current_filter_text != filter_text
            or current_sort_mode != sort_mode
        ):
            return
        base_payload_raw = payload.get("base_payload")
        if isinstance(base_payload_raw, dict):
            self.audit_name_consistency_base_cache_key = (
                generation,
                dialogue_only,
            )
            self.audit_name_consistency_base_payload = cast(
                dict[str, Any], dict(base_payload_raw)
            )
        groups_raw = payload.get("groups")
        groups = (
            [item for item in groups_raw if isinstance(item, dict)]
            if isinstance(groups_raw, list)
            else []
        )
        requested_key = (
            generation,
            dialogue_only,
            only_discrepancies,
            filter_text,
            sort_mode,
        )
        self.audit_name_consistency_cache_key = requested_key
        self.audit_name_consistency_cache_groups = list(groups)
        self._render_audit_name_consistency_groups(
            list(groups),
            only_discrepancies=only_discrepancies,
            requested_key=requested_key,
        )

    def _render_audit_name_consistency_groups(
        self,
        groups: list[dict[str, Any]],
        *,
        only_discrepancies: bool,
        requested_key: tuple[int, bool, bool, str, str],
    ) -> None:
        if (
            self.audit_name_consistency_groups_list is None
            or self.audit_name_consistency_status_label is None
        ):
            return
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
                    f"Glossary issues: {len(groups)} | Missing lines: {total_hits} | Checked lines: {total_checked}"
                )
            else:
                self.audit_name_consistency_status_label.setText(
                    f"Glossary terms: {len(groups)} | Terms with misses: {groups_with_discrepancy} | Missing lines: {total_hits} | Checked lines: {total_checked}"
                )
        else:
            self.audit_name_consistency_status_label.setText(
                "No glossary issues found between misc entries and dialogue translations."
            )
        self.audit_name_consistency_displayed_key = requested_key
        self.audit_name_consistency_display_complete = True
        self._refresh_audit_name_consistency_entries()
        self._refresh_audit_name_consistency_replace_state()
        self._refresh_audit_name_consistency_misc_go_state()

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
            current_lines = self._name_consistency_translation_lines_for_segment(
                target_segment
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
            normalize_for_segment = getattr(
                self, "_normalize_audit_translation_lines_for_segment", None
            )
            compose_resolver = getattr(self, "_compose_translation_lines_for_segment", None)
            visible_next_lines = list(next_lines)
            if callable(normalize_for_segment):
                try:
                    stored_visible_raw = normalize_for_segment(
                        target_segment,
                        visible_next_lines,
                    )
                    visible_next_lines = self._normalize_translation_lines(stored_visible_raw)
                except Exception:
                    visible_next_lines = list(next_lines)
            stored_lines: list[str] = list(visible_next_lines)
            if callable(compose_resolver):
                try:
                    composed_raw = compose_resolver(target_segment, visible_next_lines)
                except Exception:
                    composed_raw = stored_lines
                if isinstance(composed_raw, list):
                    stored_lines = self._normalize_translation_lines(composed_raw)
            target_segment.translation_lines = list(stored_lines)
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
        self._refresh_audit_translation_collision_panel()
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
        generation = self._name_consistency_cache_generation()
        requested_key = (
            generation,
            dialogue_only,
            only_discrepancies,
            filter_text,
            sort_mode,
        )
        display_complete = bool(
            getattr(self, "audit_name_consistency_display_complete", False)
        )
        displayed_key = getattr(self, "audit_name_consistency_displayed_key", None)
        if (
            display_complete
            and displayed_key == requested_key
        ):
            self._refresh_audit_name_consistency_entries()
            self._refresh_audit_name_consistency_replace_state()
            self._refresh_audit_name_consistency_misc_go_state()
            return
        self.audit_name_consistency_display_complete = False
        self.audit_name_consistency_displayed_key = None
        cache_key = getattr(self, "audit_name_consistency_cache_key", None)
        cache_groups_raw = getattr(self, "audit_name_consistency_cache_groups", [])
        if cache_key == requested_key and isinstance(cache_groups_raw, list):
            groups = [item for item in cache_groups_raw if isinstance(item, dict)]
            self._render_audit_name_consistency_groups(
                groups,
                only_discrepancies=only_discrepancies,
                requested_key=requested_key,
            )
            return
        base_key = (generation, dialogue_only)
        base_payload: Optional[dict[str, Any]] = None
        if (
            self.audit_name_consistency_base_cache_key == base_key
            and isinstance(self.audit_name_consistency_base_payload, dict)
        ):
            base_payload = cast(
                dict[str, Any], dict(self.audit_name_consistency_base_payload)
            )
        worker_ready = bool(
            hasattr(self, "audit_name_consistency_worker_timer")
            and hasattr(self, "audit_worker_executor")
        )
        if not worker_ready:
            groups = self._collect_audit_name_consistency_groups(
                dialogue_only=dialogue_only,
                only_discrepancies=only_discrepancies,
                filter_text=filter_text,
                sort_mode=sort_mode,
                base_payload=base_payload,
            )
            self.audit_name_consistency_cache_key = requested_key
            self.audit_name_consistency_cache_groups = list(groups)
            self._render_audit_name_consistency_groups(
                groups,
                only_discrepancies=only_discrepancies,
                requested_key=requested_key,
            )
            return
        self.audit_name_consistency_groups_list.clear()
        self.audit_name_consistency_status_label.setText(
            "Scanning glossary consistency..."
        )
        self._refresh_audit_name_consistency_entries()
        self._refresh_audit_name_consistency_replace_state()
        self._refresh_audit_name_consistency_misc_go_state()
        request = {
            "generation": generation,
            "dialogue_only": dialogue_only,
            "only_discrepancies": only_discrepancies,
            "filter_text": filter_text,
            "sort_mode": sort_mode,
            "base_payload": base_payload,
            "path_sessions": self._audit_path_sessions_snapshot(),
        }
        self._queue_audit_name_consistency_worker(request)

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
