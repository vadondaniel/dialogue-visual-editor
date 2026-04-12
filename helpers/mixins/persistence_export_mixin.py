from __future__ import annotations

from collections import Counter
import copy
import html
import json
import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from ..core.models import (
    NO_SPEAKER_KEY,
    CommandBundle,
    CommandToken,
    DialogueSegment,
    FileSession,
)
from ..core.parser import (
    is_tyrano_config_data,
    is_tyrano_config_path,
    is_tyrano_js_path,
    is_plugins_js_path,
    is_tyrano_script_data,
    is_tyrano_script_path,
    plugins_js_source_from_data,
    split_tyrano_dialogue_line_and_suffix,
    tyrano_config_source_from_data,
    tyrano_config_title_from_data,
    tyrano_script_source_from_data,
)
from ..core.script_message_utils import (
    build_game_message_call,
    build_game_message_templated_call,
)
from ..core.text_utils import (
    CONTROL_TOKEN_RE,
    chunk_lines_by_row_budget,
    split_lines_preserve_empty,
    strip_control_tokens,
    total_display_rows,
    visible_length,
)

ApplyVersionKind = Literal["original", "working", "translated"]
_HTML_TITLE_TAG_RE = re.compile(
    r"(<title\b[^>]*>)(.*?)(</title>)",
    re.IGNORECASE | re.DOTALL,
)
logger = logging.getLogger(__name__)
DEFAULT_TRANSLATION_PROFILE_ID = "default"


class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class PersistenceExportMixin(_EditorHostTypingFallback):
    _TRAILING_COLOR_CODE_RE = re.compile(r"\\[Cc]\[(\d+)\]\s*$")
    _TYRANO_PAGE_BREAK_TAG_RE = re.compile(r"\[\s*p(?:\s+[^\]]*)?\s*\]", re.IGNORECASE)
    _TYRANO_INLINE_BREAK_TAG_RE = re.compile(r"\[\s*r\s*\]", re.IGNORECASE)
    _TYRANO_LEADING_INDENT_RE = re.compile(r"^[ \t]+")
    _TYRANO_END_NAME_OVERRIDE_START = "// __DVE_END_NAME_MAP_START__"
    _TYRANO_END_NAME_OVERRIDE_END = "// __DVE_END_NAME_MAP_END__"
    _JAPANESE_CHAR_RE = re.compile(
        r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF"
        r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]"
    )

    def _problem_check_char_limit_enabled(self) -> bool:
        control = getattr(self, "problem_char_limit_check", None)
        return bool(control.isChecked()) if control is not None else True

    def _problem_check_line_limit_enabled(self) -> bool:
        control = getattr(self, "problem_line_limit_check", None)
        return bool(control.isChecked()) if control is not None else True

    def _problem_check_control_mismatch_enabled(self) -> bool:
        control = getattr(self, "problem_control_mismatch_check", None)
        return bool(control.isChecked()) if control is not None else False

    def _problem_check_trailing_color_code_enabled(self) -> bool:
        control = getattr(self, "problem_trailing_color_code_check", None)
        return bool(control.isChecked()) if control is not None else False

    def _problem_check_missing_translation_enabled(self) -> bool:
        control = getattr(self, "problem_missing_translation_check", None)
        return bool(control.isChecked()) if control is not None else False

    def _problem_check_contains_japanese_enabled(self) -> bool:
        control = getattr(self, "problem_contains_japanese_check", None)
        return bool(control.isChecked()) if control is not None else False

    def _normalize_problem_lines_for_segment(
        self,
        segment: DialogueSegment,
        value: Any,
    ) -> list[str]:
        normalized = self._normalize_translation_lines(value)
        segment_kind_raw = getattr(segment, "segment_kind", "")
        segment_kind = (
            segment_kind_raw.strip().lower()
            if isinstance(segment_kind_raw, str)
            else ""
        )
        if segment_kind not in {"tyrano_dialogue", "choice", "tyrano_tag_text"}:
            return normalized

        rewritten: list[str] = []
        for line in normalized:
            cleaned = re.sub(r"(?i)\[p\]", "", line)
            split_lines = re.split(r"(?i)\[r\]", cleaned)
            if split_lines:
                rewritten.extend(split_lines)
            else:
                rewritten.append(cleaned)
        return rewritten or [""]

    def _resolve_problem_source_lines_for_segment(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
        *,
        session: Optional[FileSession] = None,
        prefer_logical_chain: bool = False,
    ) -> list[str]:
        if translator_mode and prefer_logical_chain:
            logical_source_resolver = getattr(
                self,
                "_logical_translation_source_lines_for_segment",
                None,
            )
            if callable(logical_source_resolver):
                resolved_logical: Any = None
                try:
                    resolved_logical = logical_source_resolver(segment, session=session)
                except TypeError:
                    try:
                        resolved_logical = logical_source_resolver(segment)
                    except Exception:
                        resolved_logical = None
                except Exception:
                    resolved_logical = None
                if isinstance(resolved_logical, list):
                    return self._normalize_problem_lines_for_segment(
                        segment,
                        resolved_logical,
                    )

        source_lines_resolver = getattr(
            self, "_segment_source_lines_for_translation", None
        )
        if callable(source_lines_resolver):
            try:
                resolved_source = source_lines_resolver(segment)
            except Exception:
                resolved_source = None
            source_lines = (
                resolved_source
                if isinstance(resolved_source, list)
                else list(segment.source_lines or segment.original_lines or segment.lines or [""])
            )
        else:
            source_lines = list(segment.source_lines or segment.original_lines or segment.lines or [""])
        source_lines = [
            line if isinstance(line, str) else ("" if line is None else str(line))
            for line in source_lines
        ] or [""]
        return self._normalize_problem_lines_for_segment(segment, source_lines)

    def _resolve_problem_translation_lines_for_segment(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
        *,
        session: Optional[FileSession] = None,
        prefer_logical_chain: bool = False,
    ) -> list[str]:
        if translator_mode and prefer_logical_chain:
            logical_problem_translation_resolver = getattr(
                self,
                "_logical_translation_lines_for_problem_checks",
                None,
            )
            if callable(logical_problem_translation_resolver):
                resolved_problem_logical: Any = None
                try:
                    resolved_problem_logical = logical_problem_translation_resolver(
                        segment,
                        session=session,
                    )
                except TypeError:
                    try:
                        resolved_problem_logical = logical_problem_translation_resolver(
                            segment
                        )
                    except Exception:
                        resolved_problem_logical = None
                except Exception:
                    resolved_problem_logical = None
                if isinstance(resolved_problem_logical, list):
                    return self._normalize_problem_lines_for_segment(
                        segment,
                        resolved_problem_logical,
                    )

            logical_translation_resolver = getattr(
                self,
                "_logical_translation_lines_for_segment",
                None,
            )
            if callable(logical_translation_resolver):
                resolved_logical: Any = None
                try:
                    resolved_logical = logical_translation_resolver(segment, session=session)
                except TypeError:
                    try:
                        resolved_logical = logical_translation_resolver(segment)
                    except Exception:
                        resolved_logical = None
                except Exception:
                    resolved_logical = None
                if isinstance(resolved_logical, list):
                    return self._normalize_problem_lines_for_segment(
                        segment,
                        resolved_logical,
                    )

        translation_lines_resolver = getattr(
            self, "_segment_translation_lines_for_translation", None
        )
        if callable(translation_lines_resolver):
            try:
                resolved_tl = translation_lines_resolver(segment)
            except Exception:
                resolved_tl = None
            tl_lines = (
                self._normalize_problem_lines_for_segment(segment, resolved_tl)
                if isinstance(resolved_tl, list)
                else self._normalize_problem_lines_for_segment(segment, segment.translation_lines)
            )
        else:
            tl_lines = self._normalize_problem_lines_for_segment(segment, segment.translation_lines)
        return tl_lines

    def _resolve_trailing_color_translation_lines_for_segment(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
        *,
        session: Optional[FileSession] = None,
        prefer_logical_chain: bool = False,
    ) -> list[str]:
        if translator_mode and prefer_logical_chain:
            logical_translation_resolver = getattr(
                self,
                "_logical_translation_lines_for_segment",
                None,
            )
            if callable(logical_translation_resolver):
                resolved_logical: Any = None
                try:
                    resolved_logical = logical_translation_resolver(
                        segment,
                        session=session,
                    )
                except TypeError:
                    try:
                        resolved_logical = logical_translation_resolver(segment)
                    except Exception:
                        resolved_logical = None
                except Exception:
                    resolved_logical = None
                if isinstance(resolved_logical, list):
                    return self._normalize_problem_lines_for_segment(
                        segment,
                        resolved_logical,
                    )

        return self._resolve_problem_translation_lines_for_segment(
            segment,
            translator_mode,
            session=session,
            prefer_logical_chain=prefer_logical_chain,
        )

    def _segment_has_missing_translation_problem(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
    ) -> bool:
        if not translator_mode:
            return False
        source_lines_resolver = getattr(
            self, "_segment_source_lines_for_translation", None
        )
        if callable(source_lines_resolver):
            try:
                resolved_source = source_lines_resolver(segment)
            except Exception:
                resolved_source = None
            source_lines = (
                resolved_source
                if isinstance(resolved_source, list)
                else list(segment.source_lines or segment.original_lines or segment.lines or [""])
            )
        else:
            source_lines = list(segment.source_lines or segment.original_lines or segment.lines or [""])
        source_lines = [
            line if isinstance(line, str) else ("" if line is None else str(line))
            for line in source_lines
        ] or [""]
        source_lines = self._normalize_problem_lines_for_segment(segment, source_lines)
        if not any(visible_length(line) > 0 for line in source_lines):
            return False

        translation_lines_resolver = getattr(
            self, "_segment_translation_lines_for_translation", None
        )
        if callable(translation_lines_resolver):
            try:
                resolved_tl = translation_lines_resolver(segment)
            except Exception:
                resolved_tl = None
            tl_lines = (
                self._normalize_problem_lines_for_segment(segment, resolved_tl)
                if isinstance(resolved_tl, list)
                else self._normalize_problem_lines_for_segment(segment, segment.translation_lines)
            )
        else:
            tl_lines = self._normalize_problem_lines_for_segment(segment, segment.translation_lines)
        return not any(visible_length(line) > 0 for line in tl_lines)

    def _segment_has_trailing_color_code_problem(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
        *,
        session: Optional[FileSession] = None,
    ) -> bool:
        if self._segment_control_mismatch_ignored(
            segment,
            session=session,
            translator_mode=translator_mode,
        ):
            return False
        source_lines = self._resolve_problem_source_lines_for_segment(
            segment,
            translator_mode,
            session=session,
            prefer_logical_chain=True,
        )
        tl_lines = self._resolve_trailing_color_translation_lines_for_segment(
            segment,
            translator_mode,
            session=session,
            prefer_logical_chain=True,
        )

        if not "\n".join(tl_lines).strip():
            return False

        source_text = "\n".join(source_lines)
        tl_text = "\n".join(tl_lines)
        source_match = self._TRAILING_COLOR_CODE_RE.search(source_text)
        if source_match is None:
            return False
        tl_match = self._TRAILING_COLOR_CODE_RE.search(tl_text)
        if tl_match is None:
            return True
        return source_match.group(1) != tl_match.group(1)

    def _segment_has_japanese_text_problem(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
    ) -> bool:
        if not translator_mode:
            return False
        translation_lines_resolver = getattr(
            self, "_segment_translation_lines_for_translation", None
        )
        if callable(translation_lines_resolver):
            try:
                resolved_tl = translation_lines_resolver(segment)
            except Exception:
                resolved_tl = None
            tl_lines = (
                self._normalize_problem_lines_for_segment(segment, resolved_tl)
                if isinstance(resolved_tl, list)
                else self._normalize_problem_lines_for_segment(segment, segment.translation_lines)
            )
        else:
            tl_lines = self._normalize_problem_lines_for_segment(segment, segment.translation_lines)
        if not any(visible_length(line) > 0 for line in tl_lines):
            return False
        tl_text = strip_control_tokens("\n".join(tl_lines))
        return self._JAPANESE_CHAR_RE.search(tl_text) is not None

    def _control_mismatch_ignore_key(
        self,
        path: Path,
        anchor_uid: str,
    ) -> tuple[str, str]:
        return (str(path), anchor_uid)

    def _control_mismatch_ignore_entries(self) -> dict[tuple[str, str], dict[str, str]]:
        entries_raw = getattr(self, "control_mismatch_ignored_entries", None)
        if isinstance(entries_raw, dict):
            return cast(dict[tuple[str, str], dict[str, str]], entries_raw)
        entries: dict[tuple[str, str], dict[str, str]] = {}
        setattr(self, "control_mismatch_ignored_entries", entries)
        return entries

    def _control_mismatch_anchor_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> DialogueSegment:
        anchor_resolver = getattr(self, "_reference_anchor_segment_for_segment", None)
        if callable(anchor_resolver):
            try:
                resolved_anchor = anchor_resolver(session, segment)
            except Exception:
                resolved_anchor = None
            if isinstance(resolved_anchor, DialogueSegment):
                return resolved_anchor
        if not bool(getattr(segment, "translation_only", False)):
            return segment
        segments = session.segments
        segment_index = -1
        for idx, candidate in enumerate(segments):
            if candidate is segment:
                segment_index = idx
                break
        if segment_index < 0:
            for idx, candidate in enumerate(segments):
                if candidate.uid == segment.uid:
                    segment_index = idx
                    break
        if segment_index < 0:
            return segment
        for idx in range(segment_index - 1, -1, -1):
            if not bool(getattr(segments[idx], "translation_only", False)):
                return segments[idx]
        for idx in range(segment_index + 1, len(segments)):
            if not bool(getattr(segments[idx], "translation_only", False)):
                return segments[idx]
        return segment

    def _control_mismatch_signature_for_anchor(
        self,
        session: FileSession,
        anchor_segment: DialogueSegment,
        *,
        translator_mode: bool,
    ) -> str:
        source_lines = self._resolve_problem_source_lines_for_segment(
            anchor_segment,
            translator_mode,
            session=session,
            prefer_logical_chain=True,
        )
        tl_lines = self._resolve_problem_translation_lines_for_segment(
            anchor_segment,
            translator_mode,
            session=session,
            prefer_logical_chain=True,
        )
        source_text = "\n".join(self._normalize_translation_lines(source_lines))
        tl_text = "\n".join(self._normalize_translation_lines(tl_lines))
        return f"{source_text}\n\u241e\n{tl_text}"

    def _segment_control_mismatch_ignored(
        self,
        segment: DialogueSegment,
        *,
        session: Optional[FileSession] = None,
        translator_mode: bool = True,
    ) -> bool:
        if not translator_mode:
            return False
        owner_session = session
        if owner_session is None:
            session_resolver = getattr(self, "_session_for_segment", None)
            if callable(session_resolver):
                try:
                    resolved_session = session_resolver(segment)
                except Exception:
                    resolved_session = None
                if isinstance(resolved_session, FileSession):
                    owner_session = resolved_session
        if owner_session is None:
            return False

        entries = self._control_mismatch_ignore_entries()
        if not entries:
            return False
        anchor_segment = self._control_mismatch_anchor_for_segment(owner_session, segment)
        anchor_uid = anchor_segment.uid if isinstance(anchor_segment.uid, str) else ""
        if not anchor_uid:
            return False
        key = self._control_mismatch_ignore_key(owner_session.path, anchor_uid)
        ignore_entry = entries.get(key)
        if not isinstance(ignore_entry, dict):
            return False
        ignored_signature = ignore_entry.get("signature")
        if not isinstance(ignored_signature, str) or not ignored_signature:
            entries.pop(key, None)
            return False
        current_signature = self._control_mismatch_signature_for_anchor(
            owner_session,
            anchor_segment,
            translator_mode=translator_mode,
        )
        if current_signature != ignored_signature:
            entries.pop(key, None)
            return False
        return True

    def _set_control_mismatch_ignored_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
        *,
        include_identical: bool = False,
        translator_mode: bool = True,
    ) -> int:
        if not translator_mode:
            return 0
        anchor_segment = self._control_mismatch_anchor_for_segment(session, segment)
        target_signature = self._control_mismatch_signature_for_anchor(
            session,
            anchor_segment,
            translator_mode=translator_mode,
        )
        entries = self._control_mismatch_ignore_entries()

        def set_for_anchor(owner_session: FileSession, owner_anchor: DialogueSegment) -> bool:
            owner_anchor_uid = owner_anchor.uid if isinstance(owner_anchor.uid, str) else ""
            if not owner_anchor_uid:
                return False
            key = self._control_mismatch_ignore_key(owner_session.path, owner_anchor_uid)
            existing = entries.get(key)
            if isinstance(existing, dict) and existing.get("signature") == target_signature:
                return False
            entries[key] = {"signature": target_signature}
            return True

        if not include_identical:
            return 1 if set_for_anchor(session, anchor_segment) else 0

        changed = 0
        sessions_raw = getattr(self, "sessions", None)
        if isinstance(sessions_raw, dict):
            candidate_sessions = [
                candidate
                for candidate in sessions_raw.values()
                if isinstance(candidate, FileSession)
            ]
        else:
            candidate_sessions = [session]

        for owner_session in candidate_sessions:
            seen_anchor_uids: set[str] = set()
            for candidate_segment in owner_session.segments:
                owner_anchor = self._control_mismatch_anchor_for_segment(
                    owner_session,
                    candidate_segment,
                )
                owner_anchor_uid = owner_anchor.uid if isinstance(owner_anchor.uid, str) else ""
                if not owner_anchor_uid or owner_anchor_uid in seen_anchor_uids:
                    continue
                seen_anchor_uids.add(owner_anchor_uid)
                owner_signature = self._control_mismatch_signature_for_anchor(
                    owner_session,
                    owner_anchor,
                    translator_mode=translator_mode,
                )
                if owner_signature != target_signature:
                    continue
                if set_for_anchor(owner_session, owner_anchor):
                    changed += 1
        return changed

    def _clear_control_mismatch_ignored_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> bool:
        entries = self._control_mismatch_ignore_entries()
        if not entries:
            return False
        anchor_segment = self._control_mismatch_anchor_for_segment(session, segment)
        anchor_uid = anchor_segment.uid if isinstance(anchor_segment.uid, str) else ""
        if not anchor_uid:
            return False
        key = self._control_mismatch_ignore_key(session.path, anchor_uid)
        if key not in entries:
            return False
        entries.pop(key, None)
        return True

    def _prune_control_mismatch_ignores_for_session(
        self,
        session: FileSession,
        *,
        translator_mode: bool = True,
    ) -> int:
        entries = self._control_mismatch_ignore_entries()
        if not entries:
            return 0
        removed = 0
        session_path_key = str(session.path)
        session_anchor_by_uid = {
            candidate.uid: candidate
            for candidate in session.segments
            if isinstance(candidate.uid, str)
            and candidate.uid
        }
        keys_to_remove: list[tuple[str, str]] = []
        for key, entry in entries.items():
            if not isinstance(key, tuple) or len(key) != 2:
                keys_to_remove.append(key)
                continue
            path_key_raw, anchor_uid_raw = key
            if path_key_raw != session_path_key:
                continue
            if not isinstance(anchor_uid_raw, str) or (not anchor_uid_raw):
                keys_to_remove.append(key)
                continue
            anchor_segment = session_anchor_by_uid.get(anchor_uid_raw)
            if anchor_segment is None:
                keys_to_remove.append(key)
                continue
            ignored_signature = (
                entry.get("signature")
                if isinstance(entry, dict)
                else None
            )
            if not isinstance(ignored_signature, str) or not ignored_signature:
                keys_to_remove.append(key)
                continue
            current_signature = self._control_mismatch_signature_for_anchor(
                session,
                anchor_segment,
                translator_mode=translator_mode,
            )
            if current_signature != ignored_signature:
                keys_to_remove.append(key)
        for key in keys_to_remove:
            if key in entries:
                entries.pop(key, None)
                removed += 1
        return removed

    def _segment_has_control_code_mismatch_problem(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
        *,
        session: Optional[FileSession] = None,
    ) -> bool:
        if self._segment_control_mismatch_ignored(
            segment,
            session=session,
            translator_mode=translator_mode,
        ):
            return False
        source_lines = self._resolve_problem_source_lines_for_segment(
            segment,
            translator_mode,
            session=session,
            prefer_logical_chain=True,
        )
        tl_lines = self._resolve_problem_translation_lines_for_segment(
            segment,
            translator_mode,
            session=session,
            prefer_logical_chain=True,
        )

        if not "\n".join(tl_lines).strip():
            return False

        source_tokens = [
            match.group(0) for match in CONTROL_TOKEN_RE.finditer("\n".join(source_lines))
        ]
        tl_tokens = [
            match.group(0) for match in CONTROL_TOKEN_RE.finditer("\n".join(tl_lines))
        ]
        return Counter(source_tokens) != Counter(tl_tokens)

    def _segment_has_layout_problem(
        self,
        session: FileSession,
        segment: DialogueSegment,
        translator_mode: bool,
    ) -> bool:
        if (not translator_mode) and segment.translation_only:
            return False

        is_structural_dialogue = segment.is_structural_dialogue
        check_char_limit = (
            is_structural_dialogue
            and (not self._is_name_index_session(session))
            and self._problem_check_char_limit_enabled()
        )
        check_line_limit = (
            is_structural_dialogue
            and (not self._is_name_index_session(session))
            and self._problem_check_line_limit_enabled()
        )
        check_control_mismatch = self._problem_check_control_mismatch_enabled()
        check_trailing_color_code = (
            is_structural_dialogue
            and self._problem_check_trailing_color_code_enabled()
        )
        check_missing_translation = self._problem_check_missing_translation_enabled()
        check_contains_japanese = self._problem_check_contains_japanese_enabled()
        if not (
            check_char_limit
            or check_line_limit
            or check_control_mismatch
            or check_trailing_color_code
            or check_missing_translation
            or check_contains_japanese
        ):
            return False

        lines = (
            self._normalize_problem_lines_for_segment(segment, segment.translation_lines)
            if translator_mode
            else self._normalize_problem_lines_for_segment(segment, segment.lines)
            if segment.lines
            else [""]
        )
        if check_char_limit:
            width_chars = (
                self.thin_width_spin.value()
                if segment.has_face
                else self.wide_width_spin.value()
            )
            if any(visible_length(line) > width_chars for line in lines):
                return True

        if check_line_limit:
            max_rows = float(max(1, self.max_lines_spin.value()))
            if total_display_rows(lines) > max_rows:
                return True

        if check_control_mismatch:
            if self._segment_has_control_code_mismatch_problem(
                segment,
                translator_mode,
                session=session,
            ):
                return True
        if check_trailing_color_code:
            if self._segment_has_trailing_color_code_problem(
                segment,
                translator_mode,
                session=session,
            ):
                return True
        if check_missing_translation:
            if self._segment_has_missing_translation_problem(segment, translator_mode):
                return True
        if check_contains_japanese:
            if self._segment_has_japanese_text_problem(segment, translator_mode):
                return True
        return False

    def _problem_count_for_session(self, session: FileSession) -> int:
        translator_mode = self._is_translator_mode()
        return sum(
            1
            for segment in session.segments
            if self._segment_has_layout_problem(session, segment, translator_mode)
        )

    def _refresh_all_file_item_text(self) -> None:
        for path in self.file_paths:
            self._update_file_item_text(path)

    def _coerce_display_count(self, raw_value: object, fallback: int) -> int:
        if isinstance(raw_value, bool):
            return int(raw_value)
        if isinstance(raw_value, int):
            return raw_value
        if isinstance(raw_value, float):
            return int(raw_value)
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            if not stripped:
                return fallback
            try:
                return int(stripped)
            except ValueError:
                return fallback
        return fallback

    def _resolved_display_count(
        self,
        display_segments: list[DialogueSegment],
        *,
        actor_mode: bool,
    ) -> int:
        counter = getattr(self, "_display_block_count", None)
        if not callable(counter):
            return len(display_segments)
        try:
            raw_value = counter(display_segments, actor_mode=actor_mode)
        except Exception:
            return len(display_segments)
        return self._coerce_display_count(raw_value, len(display_segments))

    def _refresh_dirty_state(self, session: FileSession) -> None:
        prune_ignored = getattr(self, "_prune_control_mismatch_ignores_for_session", None)
        if callable(prune_ignored):
            try:
                prune_ignored(session, translator_mode=self._is_translator_mode())
            except Exception:
                pass
        invalidate_audit = getattr(self, "_invalidate_audit_caches", None)
        if callable(invalidate_audit):
            invalidate_audit()
        invalidate_reference = getattr(
            self, "_invalidate_reference_summary_cache", None)
        if callable(invalidate_reference):
            invalidate_reference()
        invalidate_cached_view = getattr(
            self, "_invalidate_cached_block_view_for_path", None)
        if callable(invalidate_cached_view):
            invalidate_cached_view(session.path)
        source_dirty = self._session_has_source_changes(session)
        tl_dirty = self._session_has_translation_changes(session)
        setattr(session, "_cached_source_dirty", source_dirty)
        setattr(session, "_cached_tl_dirty", tl_dirty)
        session.dirty = source_dirty or tl_dirty
        self._update_window_title()
        self._update_file_item_text(session.path)
        if self.current_path == session.path:
            actor_mode_resolver = getattr(self, "_actor_mode_for_path", None)
            if callable(actor_mode_resolver):
                try:
                    actor_mode = bool(actor_mode_resolver(session.path, session))
                except Exception:
                    actor_mode = self._is_name_index_session(session)
            else:
                actor_mode = self._is_name_index_session(session)
            translator_mode = self._is_translator_mode()
            display_segments_resolver = getattr(self, "_display_segments_for_session", None)
            if callable(display_segments_resolver):
                display_segments_raw = display_segments_resolver(
                    session,
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                )
                if isinstance(display_segments_raw, list):
                    block_count = self._resolved_display_count(
                        display_segments_raw,
                        actor_mode=actor_mode,
                    )
                else:
                    block_count = len(session.segments)
            else:
                block_count = len(session.segments)
            if actor_mode:
                name_index_label_resolver = getattr(self, "_name_index_label", None)
                if callable(name_index_label_resolver):
                    try:
                        name_index_label = str(name_index_label_resolver(session))
                    except Exception:
                        name_index_label = "Entry"
                else:
                    name_index_label = "Entry"
                entry_label = "entry" if block_count == 1 else "entries"
                header = f"{session.path.name} | {block_count} {name_index_label.lower()} {entry_label}"
            else:
                block_label = "dialogue block" if block_count == 1 else "dialogue blocks"
                header = f"{session.path.name} | {block_count} {block_label}"
            if source_dirty and tl_dirty:
                header += " | UNSAVED SOURCE+TL"
            elif source_dirty:
                header += " | UNSAVED SOURCE"
            elif tl_dirty:
                header += " | UNSAVED TL"
            self.file_header_label.setText(header)
            self._update_reset_json_button(session)

    def _update_file_item_text(self, path: Path) -> None:
        display_name = path.stem if path.stem else path.name
        session = self.sessions.get(path)
        if session is None:
            item = self.file_items.get(path)
            if item is not None:
                item.setText(display_name)
            return

        file_items_resolver = getattr(self, "_file_list_items_for_path", None)
        if callable(file_items_resolver):
            try:
                scoped_items_raw = file_items_resolver(path)
            except Exception:
                scoped_items_raw = []
        else:
            scoped_items_raw = []

        scoped_items: list[tuple[str, Any]] = []
        if isinstance(scoped_items_raw, list):
            for entry in scoped_items_raw:
                if not isinstance(entry, tuple) or len(entry) != 2:
                    continue
                scope_raw, item = entry
                if not isinstance(scope_raw, str):
                    continue
                scoped_items.append((scope_raw, item))
        if not scoped_items:
            item = self.file_items.get(path)
            if item is None:
                return
            scoped_items = [("dialogue", item)]

        prefix = "* " if session.dirty else ""
        translator_mode = self._is_translator_mode()
        display_segments_resolver = getattr(self, "_display_segments_for_session", None)
        actor_mode_resolver = getattr(self, "_actor_mode_for_path", None)
        for scope, item in scoped_items:
            actor_mode = scope.strip().lower() == "misc"
            if callable(actor_mode_resolver):
                if scope.strip().lower() not in {"dialogue", "misc"}:
                    try:
                        actor_mode = bool(actor_mode_resolver(path, session))
                    except Exception:
                        actor_mode = self._is_name_index_session(session)
            if callable(display_segments_resolver):
                display_segments_raw = display_segments_resolver(
                    session,
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                )
                if isinstance(display_segments_raw, list):
                    display_segments = display_segments_raw
                    display_count = self._resolved_display_count(
                        display_segments,
                        actor_mode=actor_mode,
                    )
                else:
                    display_segments = list(session.segments)
                    display_count = len(session.segments)
            else:
                display_segments = list(session.segments)
                display_count = len(session.segments)
            problems = sum(
                1
                for segment in display_segments
                if self._segment_has_layout_problem(session, segment, translator_mode)
            )
            problem_badge = f" [!{problems}]" if problems > 0 else ""
            suffix = " [empty]" if display_count == 0 else ""
            item.setText(
                f"{prefix}{display_name} ({display_count}){problem_badge}{suffix}")

    def _build_entries_for_segment(self, segment: DialogueSegment) -> list[dict[str, Any]]:
        if segment.segment_kind == "choice":
            return self._build_entries_for_choice_segment(segment, segment.lines)
        if segment.segment_kind == "script_message":
            return self._build_entries_for_script_message_segment(segment, segment.lines)
        return self._build_entries_for_segment_lines(segment, segment.lines)

    def _build_entries_for_choice_segment(
        self,
        segment: DialogueSegment,
        lines_source: list[str],
    ) -> list[dict[str, Any]]:
        base_cmd = copy.deepcopy(segment.code101)
        params = base_cmd.get("parameters")
        if not isinstance(params, list):
            params = []
        existing_choices = params[0] if params and isinstance(params[0], list) else []
        branch_entries = [
            entry for entry in segment.choice_branch_entries if isinstance(entry, dict)
        ]
        target_count = 0
        if isinstance(existing_choices, list) and existing_choices:
            target_count = len(existing_choices)
        elif branch_entries:
            target_count = len(branch_entries)
        else:
            target_count = max(1, len(lines_source))

        incoming_lines = list(lines_source) if lines_source else [""]
        normalized_lines = list(incoming_lines[:target_count])
        while len(normalized_lines) < target_count:
            normalized_lines.append("")

        while len(params) <= 0:
            params.append([])
        params[0] = list(normalized_lines)
        base_cmd["parameters"] = params

        for idx, branch_entry in enumerate(branch_entries):
            branch_params = branch_entry.get("parameters")
            if not isinstance(branch_params, list):
                branch_params = []
            if not branch_params:
                branch_params = [idx, ""]
            elif len(branch_params) == 1:
                branch_params.append("")
            text = normalized_lines[idx] if idx < len(normalized_lines) else ""
            branch_params[1] = text
            branch_entry["parameters"] = branch_params
        return [base_cmd]

    def _set_script_message_call_entry(
        self,
        entry: dict[str, Any],
        *,
        kind: str,
        text: str,
        quote_char: str,
        expression_terms: Optional[list[str]] = None,
    ) -> None:
        params = entry.get("parameters")
        if not isinstance(params, list):
            params = []
        while len(params) <= 0:
            params.append("")
        if expression_terms:
            params[0] = build_game_message_templated_call(
                kind,
                text,
                quote_char,
                expression_terms=expression_terms,
            )
        else:
            params[0] = build_game_message_call(kind, text, quote_char)
        entry["parameters"] = params

    def _build_entries_for_script_message_segment(
        self,
        segment: DialogueSegment,
        lines_source: list[str],
        speaker_override: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        templates = [
            entry for entry in segment.script_entries_template if isinstance(entry, dict)
        ]
        roles = list(segment.script_entry_roles)
        quotes = list(segment.script_entry_quotes)
        expression_templates = list(segment.script_entry_expression_templates)
        if not templates:
            return self._build_entries_for_segment_lines(
                segment,
                lines_source,
                speaker_override=speaker_override,
            )

        incoming_lines = list(lines_source) if lines_source else [""]
        speaker_text_raw = (
            speaker_override
            if speaker_override is not None
            else segment.speaker_name
        )
        speaker_text = "" if speaker_text_raw == NO_SPEAKER_KEY else speaker_text_raw

        add_indexes = [
            idx for idx, role in enumerate(roles)
            if role == "add" and idx < len(templates)
        ]
        if not add_indexes:
            return [copy.deepcopy(entry) for entry in templates]
        last_add_index = add_indexes[-1]
        first_add_template = copy.deepcopy(templates[add_indexes[0]])
        first_add_quote = (
            quotes[add_indexes[0]]
            if add_indexes[0] < len(quotes)
            else '"'
        )
        first_add_expression_terms: Optional[list[str]] = None
        if add_indexes[0] < len(expression_templates):
            first_add_template_payload = expression_templates[add_indexes[0]]
            if isinstance(first_add_template_payload, dict):
                expr_terms_raw = first_add_template_payload.get("expr_terms")
                if isinstance(expr_terms_raw, list):
                    first_add_expression_terms = [
                        term.strip()
                        for term in expr_terms_raw
                        if isinstance(term, str) and term.strip()
                    ] or None
        built_entries: list[dict[str, Any]] = []
        add_cursor = 0

        for idx, template in enumerate(templates):
            role = roles[idx] if idx < len(roles) else "other"
            quote_char = quotes[idx] if idx < len(quotes) else '"'
            expression_terms: Optional[list[str]] = None
            if idx < len(expression_templates):
                expression_template_payload = expression_templates[idx]
                if isinstance(expression_template_payload, dict):
                    expr_terms_raw = expression_template_payload.get("expr_terms")
                    if isinstance(expr_terms_raw, list):
                        expression_terms = [
                            term.strip()
                            for term in expr_terms_raw
                            if isinstance(term, str) and term.strip()
                        ] or None
            rebuilt_entry = copy.deepcopy(template)
            if role == "speaker":
                self._set_script_message_call_entry(
                    rebuilt_entry,
                    kind="setSpeakerName",
                    text=speaker_text,
                    quote_char=quote_char,
                    expression_terms=expression_terms,
                )
                built_entries.append(rebuilt_entry)
                continue
            if role == "add":
                if add_cursor >= len(incoming_lines):
                    continue
                next_text = incoming_lines[add_cursor]
                add_cursor += 1
                self._set_script_message_call_entry(
                    rebuilt_entry,
                    kind="add",
                    text=next_text,
                    quote_char=quote_char,
                    expression_terms=expression_terms,
                )
                built_entries.append(rebuilt_entry)
                if idx == last_add_index:
                    while add_cursor < len(incoming_lines):
                        extra_entry = copy.deepcopy(first_add_template)
                        extra_code = extra_entry.get("code")
                        if not isinstance(extra_code, int) or extra_code == 355:
                            extra_entry["code"] = 655
                        self._set_script_message_call_entry(
                            extra_entry,
                            kind="add",
                            text=incoming_lines[add_cursor],
                            quote_char=first_add_quote,
                            expression_terms=first_add_expression_terms,
                        )
                        built_entries.append(extra_entry)
                        add_cursor += 1
                continue
            built_entries.append(rebuilt_entry)
        return built_entries

    def _build_entries_for_segment_lines(
        self,
        segment: DialogueSegment,
        lines_source: list[str],
        speaker_override: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        lines = list(lines_source) if lines_source else [""]
        if self.auto_split_check.isChecked():
            chunks = chunk_lines_by_row_budget(
                lines,
                float(max(1, self.max_lines_spin.value())),
            )
        else:
            chunks = [lines]

        entries: list[dict[str, Any]] = []
        line_template = segment.code401_template if isinstance(
            segment.code401_template, dict) else {}
        line_entry_code_raw = segment.line_entry_code
        line_entry_code = line_entry_code_raw if isinstance(
            line_entry_code_raw, int) else 401
        for chunk in chunks:
            cmd101 = copy.deepcopy(segment.code101)
            if speaker_override is not None:
                params = cmd101.get("parameters")
                if not isinstance(params, list):
                    params = []
                while len(params) <= 4:
                    params.append("")
                params[4] = speaker_override
                cmd101["parameters"] = params
            entries.append(cmd101)
            indent = cmd101.get("indent", 0)
            if not chunk:
                chunk = [""]
            for line in chunk:
                if line_template:
                    line_entry = copy.deepcopy(line_template)
                    line_entry["code"] = line_entry_code
                    if "indent" not in line_entry:
                        line_entry["indent"] = indent
                    params = line_entry.get("parameters")
                    if not isinstance(params, list):
                        params = []
                    if params:
                        params[0] = line
                    else:
                        params.append(line)
                    line_entry["parameters"] = params
                    entries.append(line_entry)
                else:
                    entries.append(
                        {"code": line_entry_code, "indent": indent, "parameters": [line]})
        return entries

    def _collect_change_log(self, session: FileSession) -> list[tuple[str, str, str]]:
        changes: list[tuple[str, str, str]] = []
        for segment in session.segments:
            if segment.translation_only:
                continue
            old_text = segment.original_text_joined()
            new_text = segment.text_joined()
            if segment.inserted:
                changes.append((segment.uid, "", new_text))
            elif old_text != new_text:
                changes.append((segment.uid, old_text, new_text))
        return changes

    def _set_json_value_by_path(self, root: Any, path_tokens: tuple[Any, ...], value: str) -> bool:
        if not path_tokens:
            return False

        target: Any = root
        for token in path_tokens[:-1]:
            if isinstance(token, int):
                if not isinstance(target, list) or token < 0 or token >= len(target):
                    return False
                target = target[token]
                continue
            if isinstance(token, str):
                if not isinstance(target, dict) or token not in target:
                    return False
                target = target[token]
                continue
            return False

        leaf = path_tokens[-1]
        if isinstance(leaf, int):
            if not isinstance(target, list) or leaf < 0 or leaf >= len(target):
                return False
            if not isinstance(target[leaf], str):
                return False
            target[leaf] = value
            return True
        if isinstance(leaf, str):
            if not isinstance(target, dict):
                return False
            current_value = target.get(leaf)
            if not isinstance(current_value, str):
                return False
            target[leaf] = value
            return True
        return False

    def _string_json_value_by_path(self, root: Any, path_tokens: tuple[Any, ...]) -> Optional[str]:
        if not path_tokens:
            return None
        target: Any = root
        for token in path_tokens:
            if isinstance(token, int):
                if not isinstance(target, list) or token < 0 or token >= len(target):
                    return None
                target = target[token]
                continue
            if isinstance(token, str):
                if not isinstance(target, dict) or token not in target:
                    return None
                target = target[token]
                continue
            return None
        return target if isinstance(target, str) else None

    def _actor_alias_targets_for_segment(
        self,
        segment: DialogueSegment,
    ) -> list[tuple[Path, tuple[Any, ...]]]:
        targets_raw = getattr(segment, "actor_alias_target_refs", ())
        if not isinstance(targets_raw, (list, tuple)):
            return []
        targets: list[tuple[Path, tuple[Any, ...]]] = []
        for item in targets_raw:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            path_raw, path_tokens_raw = item
            if isinstance(path_raw, Path):
                target_path = path_raw
            elif isinstance(path_raw, str):
                target_path = Path(path_raw)
            else:
                continue
            path_tokens = (
                path_tokens_raw
                if isinstance(path_tokens_raw, tuple)
                else tuple(path_tokens_raw)
                if isinstance(path_tokens_raw, list)
                else ()
            )
            if not path_tokens:
                continue
            targets.append((target_path, path_tokens))
        return targets

    def _resolve_session_for_target_path(
        self,
        sessions_by_path: dict[Path, FileSession],
        target_path: Path,
    ) -> Optional[FileSession]:
        direct = sessions_by_path.get(target_path)
        if isinstance(direct, FileSession):
            return direct
        try:
            target_resolved = target_path.resolve()
        except Exception:
            target_resolved = target_path
        for candidate_path, candidate_session in sessions_by_path.items():
            if not isinstance(candidate_path, Path):
                continue
            if not isinstance(candidate_session, FileSession):
                continue
            if candidate_path == target_path:
                return candidate_session
            try:
                candidate_resolved = candidate_path.resolve()
            except Exception:
                candidate_resolved = candidate_path
            if candidate_resolved == target_resolved:
                return candidate_session
        return None

    def _sync_actor_alias_targets_for_session(self, session: FileSession) -> list[FileSession]:
        alias_segments = [
            segment
            for segment in session.segments
            if bool(getattr(segment, "is_actor_name_alias", False))
        ]
        if not alias_segments:
            return []
        sessions_by_path = getattr(self, "sessions", None)
        if not isinstance(sessions_by_path, dict):
            return []

        changed_sessions: dict[Path, FileSession] = {}
        for alias_segment in alias_segments:
            alias_value = "\n".join(alias_segment.lines) if alias_segment.lines else ""
            for target_path, path_tokens in self._actor_alias_targets_for_segment(alias_segment):
                target_session = self._resolve_session_for_target_path(
                    sessions_by_path,
                    target_path,
                )
                if not isinstance(target_session, FileSession):
                    continue
                if target_session.path == session.path:
                    continue
                current_value = self._string_json_value_by_path(target_session.data, path_tokens)
                if current_value is None or current_value == alias_value:
                    continue
                if not self._set_json_value_by_path(target_session.data, path_tokens, alias_value):
                    continue
                setattr(target_session, "_has_external_source_edits", True)
                changed_sessions[target_session.path] = target_session

        refresh_dirty = getattr(self, "_refresh_dirty_state", None)
        if callable(refresh_dirty):
            for target_session in changed_sessions.values():
                refresh_dirty(target_session)

        return list(changed_sessions.values())

    def _translated_export_lines_for_segment(self, segment: DialogueSegment) -> list[str]:
        visible_tl_lines = self._normalize_translation_lines(segment.translation_lines)
        visible_lines_resolver = getattr(
            self, "_segment_translation_lines_for_translation", None
        )
        if callable(visible_lines_resolver):
            try:
                resolved_lines = visible_lines_resolver(segment)
                if isinstance(resolved_lines, list):
                    visible_tl_lines = self._normalize_translation_lines(resolved_lines)
            except Exception:
                pass

        has_tl = any(line.strip() for line in visible_tl_lines)
        if has_tl:
            compose_lines_resolver = getattr(
                self, "_compose_translation_lines_for_segment", None
            )
            if callable(compose_lines_resolver):
                try:
                    composed_lines = compose_lines_resolver(segment, visible_tl_lines)
                    return self._normalize_translation_lines(composed_lines)
                except Exception:
                    return list(visible_tl_lines)
            return list(visible_tl_lines)

        return list(segment.lines or [""])

    def _actor_id_from_segment_uid_for_alias(self, uid: str) -> Optional[int]:
        resolver = getattr(self, "_actor_id_from_uid", None)
        if callable(resolver):
            try:
                actor_id_raw = resolver(uid)
            except Exception:
                actor_id_raw = None
            if isinstance(actor_id_raw, int) and actor_id_raw > 0:
                return actor_id_raw
        match = re.search(r":[A-Za-z]:(\d+)(?::[A-Za-z0-9_]+)?$", uid)
        if match is None:
            return None
        try:
            actor_id = int(match.group(1))
        except Exception:
            return None
        return actor_id if actor_id > 0 else None

    def _actor_name_translation_maps_for_session(
        self,
        session: FileSession,
    ) -> tuple[dict[int, str], dict[int, str]]:
        source_by_actor_id: dict[int, str] = {}
        translated_by_actor_id: dict[int, str] = {}
        for segment in session.segments:
            if bool(getattr(segment, "is_actor_name_alias", False)):
                continue
            actor_id = self._actor_id_from_segment_uid_for_alias(segment.uid)
            if actor_id is None:
                continue
            source_value = "\n".join(segment.lines) if segment.lines else ""
            translated_lines = self._translated_export_lines_for_segment(segment)
            translated_value = "\n".join(translated_lines) if translated_lines else ""
            source_by_actor_id.setdefault(actor_id, source_value)
            translated_by_actor_id.setdefault(actor_id, translated_value)
        return source_by_actor_id, translated_by_actor_id

    def _translated_actor_alias_value_for_segment(
        self,
        alias_segment: DialogueSegment,
        actor_source_by_id: dict[int, str],
        actor_translated_by_id: dict[int, str],
    ) -> str:
        alias_lines = self._translated_export_lines_for_segment(alias_segment)
        alias_value = "\n".join(alias_lines) if alias_lines else ""
        visible_tl_lines = self._normalize_translation_lines(alias_segment.translation_lines)
        has_explicit_alias_tl = any(line.strip() for line in visible_tl_lines)
        if has_explicit_alias_tl:
            return alias_value

        actor_id_raw = getattr(alias_segment, "actor_alias_actor_id", None)
        actor_id = (
            actor_id_raw
            if isinstance(actor_id_raw, int) and actor_id_raw > 0
            else self._actor_id_from_segment_uid_for_alias(alias_segment.uid)
        )
        if actor_id is None:
            return alias_value
        actor_source = actor_source_by_id.get(actor_id, "")
        actor_translated = actor_translated_by_id.get(actor_id, "")
        alias_source = "\n".join(alias_segment.lines) if alias_segment.lines else ""
        if (
            actor_source
            and actor_translated
            and actor_translated != actor_source
            and alias_source == actor_source
        ):
            return actor_translated
        return alias_value

    def _is_actor_index_session_for_alias_map(self, session: FileSession) -> bool:
        if bool(getattr(session, "is_actor_index_session", False)):
            return True
        if not bool(getattr(session, "is_name_index_session", False)):
            return False
        uid_prefix_raw = getattr(session, "name_index_uid_prefix", "")
        uid_prefix = uid_prefix_raw.strip().upper() if isinstance(uid_prefix_raw, str) else ""
        return uid_prefix == "A"

    def _actor_command_translation_map_for_session(
        self,
        session: FileSession,
    ) -> dict[int, dict[str, str]]:
        actor_source_by_id, actor_translated_by_id = self._actor_name_translation_maps_for_session(
            session
        )
        mapping: dict[int, dict[str, str]] = {}
        for segment in session.segments:
            actor_id = self._actor_id_from_segment_uid_for_alias(segment.uid)
            if actor_id is None:
                continue
            source_value = "\n".join(segment.lines) if segment.lines else ""
            if not source_value:
                continue
            if bool(getattr(segment, "is_actor_name_alias", False)):
                translated_value = self._translated_actor_alias_value_for_segment(
                    segment,
                    actor_source_by_id,
                    actor_translated_by_id,
                )
            else:
                translated_lines = self._translated_export_lines_for_segment(segment)
                translated_value = "\n".join(translated_lines) if translated_lines else ""
            if not translated_value or translated_value == source_value:
                continue
            entry_map = mapping.setdefault(actor_id, {})
            entry_map.setdefault(source_value, translated_value)
        return mapping

    def _apply_actor_command_translation_map_to_data(
        self,
        data: Any,
        actor_name_map: dict[int, dict[str, str]],
    ) -> bool:
        if not actor_name_map:
            return False
        updated = False

        def walk(node: Any) -> None:
            nonlocal updated
            if isinstance(node, dict):
                code_raw = node.get("code")
                parameters = node.get("parameters")
                if code_raw == 320 and isinstance(parameters, list) and len(parameters) >= 2:
                    actor_id_raw = parameters[0]
                    source_name_raw = parameters[1]
                    if (
                        isinstance(actor_id_raw, int)
                        and actor_id_raw > 0
                        and isinstance(source_name_raw, str)
                    ):
                        per_actor_map = actor_name_map.get(actor_id_raw, {})
                        translated_value = per_actor_map.get(source_name_raw, "")
                        if translated_value and translated_value != source_name_raw:
                            parameters[1] = translated_value
                            updated = True
                for value in node.values():
                    walk(value)
                return
            if isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)
        return updated

    def _save_translated_actor_alias_target_snapshots_for_session(
        self,
        session: FileSession,
        *,
        profile_id: str,
    ) -> int:
        version_db = getattr(self, "version_db", None)
        if version_db is None:
            return 0
        sessions_by_path = getattr(self, "sessions", None)
        if not isinstance(sessions_by_path, dict):
            return 0

        alias_segments = [
            segment
            for segment in session.segments
            if bool(getattr(segment, "is_actor_name_alias", False))
        ]
        if not alias_segments:
            return 0

        actor_source_by_id, actor_translated_by_id = self._actor_name_translation_maps_for_session(
            session
        )
        overrides_by_target: dict[Path, dict[tuple[Any, ...], str]] = {}
        for alias_segment in alias_segments:
            alias_value = self._translated_actor_alias_value_for_segment(
                alias_segment,
                actor_source_by_id,
                actor_translated_by_id,
            )
            for target_path, path_tokens in self._actor_alias_targets_for_segment(alias_segment):
                target_session = self._resolve_session_for_target_path(
                    sessions_by_path,
                    target_path,
                )
                if not isinstance(target_session, FileSession):
                    continue
                if target_session.path == session.path:
                    continue
                target_overrides = overrides_by_target.setdefault(target_session.path, {})
                target_overrides[path_tokens] = alias_value

        saved_count = 0
        for target_path, target_overrides in overrides_by_target.items():
            target_session = self._resolve_session_for_target_path(
                sessions_by_path,
                target_path,
            )
            if not isinstance(target_session, FileSession):
                continue

            translated_data = self._export_translated_data_for_session(target_session)
            updated = False
            for path_tokens, alias_value in target_overrides.items():
                current_value = self._string_json_value_by_path(translated_data, path_tokens)
                if current_value is None:
                    continue
                if current_value == alias_value:
                    continue
                if self._set_json_value_by_path(translated_data, path_tokens, alias_value):
                    updated = True
            if not updated:
                continue
            rel_path = self._relative_path(target_session.path)
            version_db.save_translated_snapshot(
                rel_path,
                translated_data,
                profile_id=profile_id,
            )
            saved_count += 1

        return saved_count

    def _refresh_translated_snapshots_from_loaded_sessions(
        self,
        *,
        profile_id: str,
    ) -> int:
        version_db = getattr(self, "version_db", None)
        if version_db is None:
            return 0
        sessions_by_path = getattr(self, "sessions", None)
        if not isinstance(sessions_by_path, dict):
            return 0

        payload_by_path: dict[Path, Any] = {}
        for path, session in sessions_by_path.items():
            if not isinstance(path, Path):
                continue
            if not isinstance(session, FileSession):
                continue
            payload_by_path[session.path] = self._export_translated_data_for_session(session)

        actor_name_map: dict[int, dict[str, str]] = {}
        for session in sessions_by_path.values():
            if not isinstance(session, FileSession):
                continue
            if not self._is_actor_index_session_for_alias_map(session):
                continue
            session_map = self._actor_command_translation_map_for_session(session)
            for actor_id, per_actor_map in session_map.items():
                combined = actor_name_map.setdefault(actor_id, {})
                for source_name, translated_name in per_actor_map.items():
                    combined.setdefault(source_name, translated_name)

        for source_session in sessions_by_path.values():
            if not isinstance(source_session, FileSession):
                continue
            alias_segments = [
                segment
                for segment in source_session.segments
                if bool(getattr(segment, "is_actor_name_alias", False))
            ]
            if not alias_segments:
                continue
            actor_source_by_id, actor_translated_by_id = (
                self._actor_name_translation_maps_for_session(source_session)
            )
            for alias_segment in alias_segments:
                alias_value = self._translated_actor_alias_value_for_segment(
                    alias_segment,
                    actor_source_by_id,
                    actor_translated_by_id,
                )
                for target_path, path_tokens in self._actor_alias_targets_for_segment(alias_segment):
                    target_session = self._resolve_session_for_target_path(
                        sessions_by_path,
                        target_path,
                    )
                    if not isinstance(target_session, FileSession):
                        continue
                    target_data = payload_by_path.get(target_session.path)
                    if target_data is None:
                        continue
                    self._set_json_value_by_path(target_data, path_tokens, alias_value)

        saved_count = 0
        for path, translated_data in payload_by_path.items():
            self._apply_actor_command_translation_map_to_data(translated_data, actor_name_map)
            rel_path = self._relative_path(path)
            version_db.save_translated_snapshot(
                rel_path,
                translated_data,
                profile_id=profile_id,
            )
            saved_count += 1
        return saved_count

    @staticmethod
    def _tyrano_body_item_kind_for_line(line: str) -> str:
        stripped = line.strip()
        if stripped.startswith("#"):
            return "speaker"
        if stripped and (not stripped.startswith(("[", ";", "*", "@", "//"))):
            return "text"
        return "raw"

    @staticmethod
    def _escape_tyrano_tag_attribute_value(value: str, quote_char: str) -> str:
        escaped = value.replace("\\", "\\\\")
        if quote_char == "'":
            escaped = escaped.replace("'", "\\'")
        else:
            escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")
        return escaped

    @staticmethod
    def _encode_tyrano_choice_spacing(value: str) -> str:
        if not value:
            return ""
        # Tyrano collapses regular ASCII spaces in choice labels; use narrow NBSP
        # so spacing remains visible without the width of ideographic space.
        return value.replace(" ", "\u202F")

    @staticmethod
    def _join_tyrano_text_lines_for_attribute(lines: list[str]) -> str:
        flattened: list[str] = []
        for line in lines:
            flattened.extend(split_lines_preserve_empty(line))
        return "[r]".join(flattened)

    @staticmethod
    def _join_tyrano_text_lines_for_script_string(lines: list[str]) -> str:
        flattened: list[str] = []
        for line in lines:
            flattened.extend(split_lines_preserve_empty(line))
        return "\n".join(flattened)

    @classmethod
    def _upsert_tyrano_end_name_override_block(
        cls,
        raw_chunks: list[dict[str, Any]],
        end_name_overrides: dict[str, str],
    ) -> list[dict[str, Any]]:
        stripped_chunks: list[dict[str, Any]] = []
        in_override_block = False
        for chunk in raw_chunks:
            if not isinstance(chunk, dict):
                if not in_override_block:
                    stripped_chunks.append(chunk)
                continue
            kind_raw = chunk.get("kind")
            kind = kind_raw.strip().lower() if isinstance(kind_raw, str) else ""
            if kind != "raw_line":
                if not in_override_block:
                    stripped_chunks.append(chunk)
                continue
            line_raw = chunk.get("line")
            line = line_raw if isinstance(line_raw, str) else ""
            marker = line.strip()
            if marker == cls._TYRANO_END_NAME_OVERRIDE_START:
                in_override_block = True
                continue
            if in_override_block and marker == cls._TYRANO_END_NAME_OVERRIDE_END:
                in_override_block = False
                continue
            if not in_override_block:
                stripped_chunks.append(chunk)

        if not end_name_overrides:
            return stripped_chunks

        if stripped_chunks:
            last_chunk = stripped_chunks[-1]
            if isinstance(last_chunk, dict):
                kind_raw = last_chunk.get("kind")
                kind = kind_raw.strip().lower() if isinstance(kind_raw, str) else ""
                line_raw = last_chunk.get("line")
                line = line_raw if isinstance(line_raw, str) else ""
                if kind == "raw_line" and line.strip():
                    stripped_chunks.append({"kind": "raw_line", "line": ""})

        block_lines: list[str] = [cls._TYRANO_END_NAME_OVERRIDE_START]
        block_lines.append("const DVE_END_NAME_MAP = {")
        for source_id, translated_name in sorted(end_name_overrides.items()):
            escaped_source = cls._escape_tyrano_tag_attribute_value(source_id, "'")
            escaped_tl = cls._escape_tyrano_tag_attribute_value(translated_name, "'")
            block_lines.append(f"    '{escaped_source}': '{escaped_tl}',")
        block_lines.extend(
            [
                "};",
                "function _dveGetEndDisplayName(id) {",
                "    return DVE_END_NAME_MAP[id] || id;",
                "}",
                "if (typeof getEndDataIndex === 'function') {",
                "    getEndName = function(id) {",
                "        const num = getEndDataIndex(id);",
                "        if (0 > num) {",
                "            return _dveGetEndDisplayName(id);",
                "        }",
                "        return 'END ' + (num + 1) + '：' + _dveGetEndDisplayName(id);",
                "    };",
                "}",
                cls._TYRANO_END_NAME_OVERRIDE_END,
            ]
        )
        for line in block_lines:
            stripped_chunks.append({"kind": "raw_line", "line": line})
        return stripped_chunks

    @staticmethod
    def _escape_tyrano_config_value(value: str, quote_char: str) -> str:
        escaped = value.replace("\\", "\\\\")
        if quote_char == "'":
            escaped = escaped.replace("'", "\\'")
        elif quote_char == '"':
            escaped = escaped.replace('"', '\\"')
        return escaped.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")

    def _apply_session_to_tyrano_config_data(self, session: FileSession) -> bool:
        if not is_tyrano_config_data(session.data):
            return False
        raw_lines = session.data.get("__dve_tyrano_config_lines__")
        if not isinstance(raw_lines, list):
            return True

        title_segment: Optional[DialogueSegment] = None
        for segment in session.segments:
            path_tokens_raw = getattr(segment, "system_text_path", ())
            if not isinstance(path_tokens_raw, tuple):
                continue
            if path_tokens_raw == ("gameTitle",):
                title_segment = segment
                break
        if title_segment is None:
            return True

        line_index_raw = session.data.get("__dve_tyrano_config_title_line_index__", -1)
        if not isinstance(line_index_raw, int):
            return True
        if line_index_raw < 0 or line_index_raw >= len(raw_lines):
            return True
        line = raw_lines[line_index_raw]
        if not isinstance(line, str):
            return True

        span_raw = session.data.get("__dve_tyrano_config_title_span__", ())
        if (
            not isinstance(span_raw, (list, tuple))
            or len(span_raw) != 2
            or not isinstance(span_raw[0], int)
            or not isinstance(span_raw[1], int)
        ):
            return True
        value_start = span_raw[0]
        value_end = span_raw[1]
        if value_start < 0 or value_end < value_start or value_end > len(line):
            return True

        quote_raw = session.data.get("__dve_tyrano_config_title_quote__", "")
        quote_char = quote_raw if isinstance(quote_raw, str) and quote_raw in {'"', "'"} else ""
        title_lines = self._normalized_tyrano_segment_lines(title_segment)
        title_value = " ".join(line.strip() for line in title_lines if line.strip())
        escaped_value = self._escape_tyrano_config_value(title_value, quote_char)
        raw_lines[line_index_raw] = f"{line[:value_start]}{escaped_value}{line[value_end:]}"
        session.data["__dve_tyrano_config_lines__"] = raw_lines
        session.data["__dve_tyrano_config_title_span__"] = (
            value_start,
            value_start + len(escaped_value),
        )
        return True

    @staticmethod
    def _normalized_tyrano_segment_lines(segment: DialogueSegment) -> list[str]:
        incoming_lines_raw = list(segment.lines) if segment.lines else [""]
        incoming_lines = [
            line if isinstance(line, str) else ("" if line is None else str(line))
            for line in incoming_lines_raw
        ]
        return incoming_lines or [""]

    @staticmethod
    def _segment_tyrano_line_suffixes(segment: DialogueSegment) -> list[str]:
        suffixes_raw = getattr(segment, "tyrano_line_suffixes", ())
        if not isinstance(suffixes_raw, (list, tuple)):
            return []
        return [
            suffix if isinstance(suffix, str) else ""
            for suffix in suffixes_raw
        ]

    @staticmethod
    def _segment_tyrano_line_prefixes(segment: DialogueSegment) -> list[str]:
        prefixes_raw = getattr(segment, "tyrano_line_prefixes", ())
        if not isinstance(prefixes_raw, (list, tuple)):
            return []
        return [
            prefix if isinstance(prefix, str) else ""
            for prefix in prefixes_raw
        ]

    @classmethod
    def _split_tyrano_leading_indent(cls, text: str) -> tuple[str, str]:
        if not text:
            return "", ""
        match = cls._TYRANO_LEADING_INDENT_RE.match(text)
        if match is None:
            return "", text
        prefix = match.group(0)
        return prefix, text[len(prefix):]

    @classmethod
    def _fallback_tyrano_suffix_for_new_line(cls, stored_suffixes: list[str]) -> str:
        if len(stored_suffixes) == 1:
            only_suffix = stored_suffixes[0]
            if only_suffix:
                return only_suffix
        for suffix in reversed(stored_suffixes):
            if not suffix:
                continue
            has_page = cls._TYRANO_PAGE_BREAK_TAG_RE.search(suffix) is not None
            without_page = cls._TYRANO_PAGE_BREAK_TAG_RE.sub("", suffix)
            if cls._TYRANO_INLINE_BREAK_TAG_RE.search(without_page):
                return "[r]"
            if has_page:
                return suffix
        return ""

    @staticmethod
    def _fallback_tyrano_prefix_for_new_line(stored_prefixes: list[str]) -> str:
        if len(stored_prefixes) == 1:
            return stored_prefixes[0]
        for prefix in stored_prefixes:
            if prefix:
                return prefix
        return ""

    @classmethod
    def _render_tyrano_segment_lines_for_save(
        cls,
        segment: DialogueSegment,
        normalized_lines: list[str],
    ) -> tuple[list[str], list[str]]:
        stored_suffixes = cls._segment_tyrano_line_suffixes(segment)
        stored_prefixes = cls._segment_tyrano_line_prefixes(segment)
        fallback_suffix = cls._fallback_tyrano_suffix_for_new_line(stored_suffixes)
        fallback_prefix = cls._fallback_tyrano_prefix_for_new_line(stored_prefixes)

        prepared_lines: list[tuple[str, str]] = []
        for line_index, raw_line in enumerate(normalized_lines):
            line_text, inline_suffix = split_tyrano_dialogue_line_and_suffix(raw_line)
            if line_index < len(stored_suffixes):
                suffix = stored_suffixes[line_index] or inline_suffix
            else:
                suffix = inline_suffix or fallback_suffix
            line_prefix = (
                stored_prefixes[line_index]
                if line_index < len(stored_prefixes)
                else fallback_prefix
            )
            split_lines = split_lines_preserve_empty(line_text)
            if len(split_lines) <= 1:
                prepared_lines.append((f"{line_prefix}{line_text}", suffix))
                continue
            prepared_lines.append((f"{line_prefix}{split_lines[0]}", "[r]"))
            for split_line in split_lines[1:-1]:
                prepared_lines.append((split_line, "[r]"))
            prepared_lines.append((split_lines[-1], suffix))

        rendered_lines: list[str] = []
        used_suffixes: list[str] = []
        for line_index, (raw_line_text, raw_suffix) in enumerate(prepared_lines):
            line_text, inline_suffix = split_tyrano_dialogue_line_and_suffix(raw_line_text)
            suffix = raw_suffix or inline_suffix
            # Keep page-break markers only on terminal lines; intermediate
            # lines should carry line-break semantics only.
            if line_index < (len(prepared_lines) - 1):
                suffix_without_page = cls._TYRANO_PAGE_BREAK_TAG_RE.sub("", suffix)
                if cls._TYRANO_INLINE_BREAK_TAG_RE.search(suffix_without_page):
                    suffix = "[r]"
                else:
                    suffix = "[r]"
            rendered_lines.append(f"{line_text}{suffix}")
            used_suffixes.append(suffix)

        if rendered_lines and stored_suffixes and len(prepared_lines) < len(stored_suffixes):
            terminal_suffix = stored_suffixes[-1]
            if terminal_suffix:
                last_text, _ = split_tyrano_dialogue_line_and_suffix(rendered_lines[-1])
                rendered_lines[-1] = f"{last_text}{terminal_suffix}"
                used_suffixes[-1] = terminal_suffix
        return rendered_lines, used_suffixes

    @staticmethod
    def _segment_tyrano_text_indexes(segment: DialogueSegment) -> list[int]:
        text_indexes_raw = getattr(segment, "tyrano_text_item_indexes", ())
        if not isinstance(text_indexes_raw, (list, tuple)):
            return []
        return [index for index in text_indexes_raw if isinstance(index, int)]

    @classmethod
    def _first_tyrano_text_index_for_sort(cls, segment: DialogueSegment) -> int:
        text_indexes = cls._segment_tyrano_text_indexes(segment)
        if text_indexes:
            return min(text_indexes)
        return 1_000_000_000

    @staticmethod
    def _coerce_tyrano_choice_items(
        segment: DialogueSegment,
    ) -> list[tuple[int, int, int, str]]:
        raw_items = getattr(segment, "tyrano_choice_items", ())
        if not isinstance(raw_items, (list, tuple)):
            return []
        items: list[tuple[int, int, int, str]] = []
        for item in raw_items:
            if not isinstance(item, (list, tuple)) or len(item) != 4:
                continue
            chunk_index_raw, value_start_raw, value_end_raw, quote_raw = item
            if (
                not isinstance(chunk_index_raw, int)
                or not isinstance(value_start_raw, int)
                or not isinstance(value_end_raw, int)
            ):
                continue
            quote_char = (
                quote_raw
                if isinstance(quote_raw, str) and quote_raw in {'"', "'"}
                else '"'
            )
            items.append((chunk_index_raw, value_start_raw, value_end_raw, quote_char))
        return items

    def _apply_session_to_tyrano_script_data(self, session: FileSession) -> bool:
        if not is_tyrano_script_data(session.data):
            return False
        raw_chunks = session.data.get("__dve_tyrano_script_chunks__")
        if not isinstance(raw_chunks, list):
            return True

        dialogue_segments_by_chunk: dict[int, list[tuple[int, DialogueSegment]]] = {}
        for order_index, segment in enumerate(session.segments):
            if segment.segment_kind != "tyrano_dialogue":
                continue
            chunk_index_raw = getattr(segment, "tyrano_chunk_index", None)
            if not isinstance(chunk_index_raw, int):
                continue
            if chunk_index_raw < 0 or chunk_index_raw >= len(raw_chunks):
                continue
            dialogue_segments_by_chunk.setdefault(chunk_index_raw, []).append((order_index, segment))

        for chunk_index, ordered_chunk_segments in dialogue_segments_by_chunk.items():
            chunk_raw = raw_chunks[chunk_index]
            if not isinstance(chunk_raw, dict):
                continue
            chunk_kind_raw = chunk_raw.get("kind")
            chunk_kind = (
                chunk_kind_raw.strip().lower()
                if isinstance(chunk_kind_raw, str)
                else ""
            )
            if chunk_kind != "dialogue_block":
                continue
            body_items_raw = chunk_raw.get("body_items")
            if not isinstance(body_items_raw, list):
                continue
            body_items: list[dict[str, str]] = []
            for body_item in body_items_raw:
                if not isinstance(body_item, dict):
                    continue
                line_raw = body_item.get("line")
                line = line_raw if isinstance(line_raw, str) else ""
                kind_raw = body_item.get("kind")
                kind = (
                    kind_raw.strip().lower()
                    if isinstance(kind_raw, str)
                    else self._tyrano_body_item_kind_for_line(line)
                )
                body_items.append({"kind": kind, "line": line})

            chunk_segments_sorted = sorted(
                ordered_chunk_segments,
                key=lambda item: (
                    self._first_tyrano_text_index_for_sort(item[1]),
                    item[0],
                ),
            )
            speaker_item_index: int | None = None
            for _, segment in chunk_segments_sorted:
                speaker_item_index_raw = getattr(segment, "tyrano_speaker_item_index", None)
                if isinstance(speaker_item_index_raw, int) and 0 <= speaker_item_index_raw < len(body_items):
                    speaker_item_index = speaker_item_index_raw
                    break
            if speaker_item_index is None:
                for idx, body_item in enumerate(body_items):
                    if body_item.get("kind") == "speaker":
                        speaker_item_index = idx
                        break

            speaker_value = ""
            for _, segment in chunk_segments_sorted:
                speaker_value_raw = segment.speaker_name
                if not isinstance(speaker_value_raw, str):
                    continue
                cleaned_speaker = speaker_value_raw.strip()
                if cleaned_speaker and cleaned_speaker != NO_SPEAKER_KEY:
                    speaker_value = cleaned_speaker
                    break
            desired_speaker_line = f"#{speaker_value}" if speaker_value else "#"

            speaker_insert_at: int | None = None
            if speaker_item_index is not None:
                body_items[speaker_item_index]["kind"] = "speaker"
                body_items[speaker_item_index]["line"] = desired_speaker_line
            elif speaker_value:
                first_text_index = next(
                    (
                        idx
                        for idx, body_item in enumerate(body_items)
                        if body_item.get("kind") == "text"
                    ),
                    None,
                )
                insert_at = first_text_index if isinstance(first_text_index, int) else 0
                body_items.insert(insert_at, {"kind": "speaker", "line": desired_speaker_line})
                speaker_item_index = insert_at
                speaker_insert_at = insert_at

            existing_text_indexes = [
                idx
                for idx, body_item in enumerate(body_items)
                if body_item.get("kind") == "text"
            ]

            segment_lines_payload: list[dict[str, Any]] = []
            for sorted_index, (_, segment) in enumerate(chunk_segments_sorted):
                normalized_lines = self._normalized_tyrano_segment_lines(segment)
                rendered_lines, used_suffixes = self._render_tyrano_segment_lines_for_save(
                    segment,
                    normalized_lines,
                )
                used_prefixes: list[str] = []
                for rendered_line in rendered_lines:
                    line_text, _ = split_tyrano_dialogue_line_and_suffix(rendered_line)
                    line_prefix, _ = self._split_tyrano_leading_indent(line_text)
                    used_prefixes.append(line_prefix)
                segment_text_indexes = self._segment_tyrano_text_indexes(segment)
                if speaker_insert_at is not None:
                    segment_text_indexes = [
                        text_index + 1 if text_index >= speaker_insert_at else text_index
                        for text_index in segment_text_indexes
                    ]
                segment_lines_payload.append(
                    {
                        "segment": segment,
                        "lines": rendered_lines,
                        "suffixes": used_suffixes,
                        "prefixes": used_prefixes,
                        "text_indexes": segment_text_indexes,
                        "order_index": sorted_index,
                        "new_indexes": (),
                    }
                )

            has_any_non_blank_lines = any(
                any(line != "" for line in payload.get("lines", []))
                for payload in segment_lines_payload
            )
            new_body_items: list[dict[str, str]] = []
            if existing_text_indexes:
                sorted_text_indexes = sorted(existing_text_indexes)
                text_clusters: list[list[int]] = []
                current_cluster: list[int] = []
                for text_index in sorted_text_indexes:
                    if not current_cluster:
                        current_cluster = [text_index]
                        continue
                    if text_index == current_cluster[-1] + 1:
                        current_cluster.append(text_index)
                        continue
                    text_clusters.append(list(current_cluster))
                    current_cluster = [text_index]
                if current_cluster:
                    text_clusters.append(list(current_cluster))

                cluster_payloads: list[dict[str, Any]] = []
                for cluster in text_clusters:
                    cluster_payloads.append(
                        {
                            "indexes": set(cluster),
                            "start": cluster[0],
                            "end": cluster[-1],
                            "payloads": [],
                        }
                    )

                for payload in segment_lines_payload:
                    text_indexes_raw = payload.get("text_indexes", [])
                    text_indexes = (
                        text_indexes_raw
                        if isinstance(text_indexes_raw, list)
                        else []
                    )
                    if not text_indexes:
                        continue
                    first_index = min(text_indexes)
                    for cluster_payload in cluster_payloads:
                        if first_index in cluster_payload["indexes"]:
                            cluster_payload["payloads"].append(payload)
                            break

                cluster_by_start = {
                    int(cluster_payload["start"]): cluster_payload
                    for cluster_payload in cluster_payloads
                }
                all_cluster_indexes: set[int] = set()
                for cluster_payload in cluster_payloads:
                    all_cluster_indexes.update(cluster_payload["indexes"])

                body_index = 0
                while body_index < len(body_items):
                    cluster_payload = cluster_by_start.get(body_index)
                    if cluster_payload is not None:
                        payloads_in_cluster = list(cluster_payload.get("payloads", []))
                        payloads_in_cluster.sort(
                            key=lambda row: (
                                min(row.get("text_indexes", []) or [10**9]),
                                int(row.get("order_index", 0)),
                            )
                        )
                        next_text_index = len(new_body_items)
                        for payload in payloads_in_cluster:
                            payload_lines_raw = payload.get("lines", [])
                            payload_lines = payload_lines_raw if isinstance(payload_lines_raw, list) else []
                            payload["new_indexes"] = tuple(
                                range(next_text_index, next_text_index + len(payload_lines))
                            )
                            next_text_index += len(payload_lines)
                            for line in payload_lines:
                                new_body_items.append({"kind": "text", "line": line})
                        body_index = int(cluster_payload.get("end", body_index)) + 1
                        continue

                    if body_index in all_cluster_indexes:
                        body_index += 1
                        continue

                    new_body_items.append(body_items[body_index])
                    body_index += 1
            else:
                new_body_items = list(body_items)
                insert_at = (
                    speaker_item_index + 1
                    if isinstance(speaker_item_index, int)
                    else len(new_body_items)
                )
                for payload in segment_lines_payload:
                    payload_lines_raw = payload.get("lines", [])
                    payload_lines = payload_lines_raw if isinstance(payload_lines_raw, list) else []
                    if payload_lines:
                        payload["new_indexes"] = tuple(
                            range(insert_at, insert_at + len(payload_lines))
                        )
                        insert_at += len(payload_lines)
                        for offset, line in enumerate(payload_lines):
                            new_body_items.insert(
                                int(payload["new_indexes"][offset]),
                                {"kind": "text", "line": line},
                            )
                    else:
                        payload["new_indexes"] = ()

            unassigned_payloads = [
                payload
                for payload in segment_lines_payload
                if not payload.get("new_indexes")
                and bool(payload.get("lines"))
            ]
            if unassigned_payloads:
                next_text_index = len(new_body_items)
                for payload in unassigned_payloads:
                    payload_lines_raw = payload.get("lines", [])
                    payload_lines = payload_lines_raw if isinstance(payload_lines_raw, list) else []
                    payload["new_indexes"] = tuple(
                        range(next_text_index, next_text_index + len(payload_lines))
                    )
                    next_text_index += len(payload_lines)
                    for line in payload_lines:
                        new_body_items.append({"kind": "text", "line": line})

            updated_speaker_item_index: int | None = None
            for idx, body_item in enumerate(new_body_items):
                if body_item.get("kind") == "speaker":
                    updated_speaker_item_index = idx
                    break

            for payload in segment_lines_payload:
                segment_raw = payload.get("segment")
                if not isinstance(segment_raw, DialogueSegment):
                    continue
                suffixes_raw = payload.get("suffixes", [])
                suffixes = suffixes_raw if isinstance(suffixes_raw, list) else []
                prefixes_raw = payload.get("prefixes", [])
                prefixes = prefixes_raw if isinstance(prefixes_raw, list) else []
                new_indexes_raw = payload.get("new_indexes", ())
                text_indexes = (
                    tuple(new_indexes_raw)
                    if isinstance(new_indexes_raw, tuple)
                    else tuple()
                )
                segment = segment_raw
                setattr(segment, "tyrano_speaker_item_index", updated_speaker_item_index)
                setattr(segment, "tyrano_text_item_indexes", text_indexes)
                setattr(segment, "tyrano_line_suffixes", tuple(suffixes))
                setattr(segment, "tyrano_line_prefixes", tuple(prefixes))
                setattr(segment, "tyrano_editable_item_indexes", text_indexes)

            chunk_raw["body_items"] = new_body_items

        for segment in session.segments:
            if segment.segment_kind != "choice":
                continue
            choice_items = self._coerce_tyrano_choice_items(segment)
            if not choice_items:
                continue
            incoming_lines = self._normalized_tyrano_segment_lines(segment)
            updated_items: list[tuple[int, int, int, str]] = []
            for option_index, item in enumerate(choice_items):
                chunk_index, value_start, value_end, quote_char = item
                if option_index >= len(incoming_lines):
                    updated_items.append(item)
                    continue
                if chunk_index < 0 or chunk_index >= len(raw_chunks):
                    updated_items.append(item)
                    continue
                chunk_raw = raw_chunks[chunk_index]
                if not isinstance(chunk_raw, dict):
                    updated_items.append(item)
                    continue
                chunk_kind_raw = chunk_raw.get("kind")
                chunk_kind = (
                    chunk_kind_raw.strip().lower()
                    if isinstance(chunk_kind_raw, str)
                    else ""
                )
                if chunk_kind != "raw_line":
                    updated_items.append(item)
                    continue
                line_raw = chunk_raw.get("line")
                line = line_raw if isinstance(line_raw, str) else ""
                if value_start < 0 or value_end < value_start or value_end > len(line):
                    updated_items.append(item)
                    continue
                option_value_raw = self._join_tyrano_text_lines_for_attribute(
                    [incoming_lines[option_index]]
                )
                option_value = self._encode_tyrano_choice_spacing(option_value_raw)
                escaped_value = self._escape_tyrano_tag_attribute_value(
                    option_value,
                    quote_char,
                )
                chunk_raw["line"] = f"{line[:value_start]}{escaped_value}{line[value_end:]}"
                updated_items.append(
                    (chunk_index, value_start, value_start + len(escaped_value), quote_char)
                )
            setattr(segment, "tyrano_choice_items", tuple(updated_items))

        end_name_overrides: dict[str, str] = {}
        for segment in session.segments:
            if segment.segment_kind != "tyrano_tag_text":
                continue
            chunk_index_raw = getattr(segment, "tyrano_chunk_index", None)
            if not isinstance(chunk_index_raw, int):
                continue
            if chunk_index_raw < 0 or chunk_index_raw >= len(raw_chunks):
                continue
            chunk_raw = raw_chunks[chunk_index_raw]
            if not isinstance(chunk_raw, dict):
                continue
            chunk_kind_raw = chunk_raw.get("kind")
            chunk_kind = (
                chunk_kind_raw.strip().lower()
                if isinstance(chunk_kind_raw, str)
                else ""
            )
            if chunk_kind != "raw_line":
                continue
            line_raw = chunk_raw.get("line")
            line = line_raw if isinstance(line_raw, str) else ""
            span_raw = getattr(segment, "tyrano_tag_text_span", ())
            if (
                not isinstance(span_raw, (tuple, list))
                or len(span_raw) != 2
                or not isinstance(span_raw[0], int)
                or not isinstance(span_raw[1], int)
            ):
                continue
            value_start = span_raw[0]
            value_end = span_raw[1]
            if value_start < 0 or value_end < value_start or value_end > len(line):
                continue
            quote_raw = getattr(segment, "tyrano_tag_text_quote", '"')
            quote_char = (
                quote_raw if isinstance(quote_raw, str) and quote_raw in {'"', "'"} else '"'
            )
            join_mode_raw = getattr(segment, "tyrano_tag_text_join_mode", "")
            join_mode = join_mode_raw.strip().lower() if isinstance(join_mode_raw, str) else ""
            if join_mode == "script_string_end_id":
                source_id_raw = getattr(segment, "tyrano_script_end_list_id_source", "")
                source_id = source_id_raw if isinstance(source_id_raw, str) else ""
                translated_id = (
                    self._join_tyrano_text_lines_for_script_string(segment.lines)
                    if segment.lines
                    else ""
                ).strip()
                if source_id and translated_id and translated_id != source_id:
                    end_name_overrides[source_id] = translated_id
                continue
            if join_mode == "script_string_end_id_ref":
                # END key references must remain source-stable so game lookup
                # still resolves END_LIST ids.
                continue
            joined_value = (
                self._join_tyrano_text_lines_for_script_string(segment.lines)
                if join_mode == "script_string"
                else self._join_tyrano_text_lines_for_attribute(segment.lines)
                if segment.lines
                else ""
            )
            escaped_value = self._escape_tyrano_tag_attribute_value(
                joined_value,
                quote_char,
            )
            chunk_raw["line"] = f"{line[:value_start]}{escaped_value}{line[value_end:]}"
            setattr(
                segment,
                "tyrano_tag_text_span",
                (value_start, value_start + len(escaped_value)),
            )

        if is_tyrano_js_path(session.path):
            raw_chunks = self._upsert_tyrano_end_name_override_block(
                raw_chunks,
                end_name_overrides,
            )

        session.data["__dve_tyrano_script_chunks__"] = raw_chunks
        return True

    def _apply_session_to_json(self, session: FileSession) -> None:
        if self._apply_session_to_tyrano_config_data(session):
            return
        if self._apply_session_to_tyrano_script_data(session):
            return
        is_name_index_session = (
            bool(getattr(session, "is_name_index_session", False))
            or bool(getattr(session, "is_actor_index_session", False))
        )
        has_name_index_segments = any(
            segment.segment_kind == "name_index"
            for segment in session.segments
        )

        if isinstance(session.data, dict):
            for segment in session.segments:
                path_tokens_raw = getattr(segment, "map_display_name_path", ())
                if not isinstance(path_tokens_raw, tuple):
                    continue
                new_value = "\n".join(segment.lines) if segment.lines else ""
                self._set_json_value_by_path(session.data, path_tokens_raw, new_value)

        for segment in session.segments:
            path_tokens_raw = getattr(segment, "json_text_path", ())
            if not isinstance(path_tokens_raw, tuple):
                continue
            new_value = "\n".join(segment.lines) if segment.lines else ""
            self._set_json_value_by_path(session.data, path_tokens_raw, new_value)

        if is_name_index_session and isinstance(session.data, dict):
            name_index_kind_raw = getattr(session, "name_index_kind", "")
            name_index_kind = name_index_kind_raw.strip().lower(
            ) if isinstance(name_index_kind_raw, str) else ""
            if name_index_kind == "system":
                for segment in session.segments:
                    path_tokens_raw = getattr(segment, "system_text_path", ())
                    if not isinstance(path_tokens_raw, tuple):
                        continue
                    new_value = "\n".join(
                        segment.lines) if segment.lines else ""
                    self._set_json_value_by_path(
                        session.data, path_tokens_raw, new_value)
                return
            if name_index_kind == "plugin":
                for segment in session.segments:
                    path_tokens_raw = getattr(segment, "plugin_text_path", ())
                    if not isinstance(path_tokens_raw, tuple):
                        continue
                    new_value = "\n".join(
                        segment.lines) if segment.lines else ""
                    self._set_json_value_by_path(
                        session.data, path_tokens_raw, new_value)
                return

        if (is_name_index_session or has_name_index_segments) and isinstance(session.data, list):
            uid_prefix_raw = getattr(session, "name_index_uid_prefix", "")
            if not (isinstance(uid_prefix_raw, str) and uid_prefix_raw.strip()):
                inferred_prefix = ""
                for segment in session.segments:
                    if segment.segment_kind != "name_index":
                        continue
                    match = re.search(r":([A-Za-z]):\d+(?::[A-Za-z0-9_]+)?$", segment.uid)
                    if match is None:
                        continue
                    inferred_prefix = match.group(1)
                    break
                uid_prefix_raw = inferred_prefix or "A"
            uid_prefix = uid_prefix_raw.strip() if isinstance(uid_prefix_raw, str) else "A"
            id_pattern = re.compile(
                rf":{re.escape(uid_prefix)}:(\d+)(?::([A-Za-z0-9_]+))?$")
            values_by_entry_id: dict[int, dict[str, str]] = {}
            for segment in session.segments:
                if bool(getattr(segment, "is_actor_name_alias", False)):
                    continue
                match = id_pattern.search(segment.uid)
                if not match:
                    continue
                try:
                    entry_id = int(match.group(1))
                except Exception:
                    continue
                field_name = match.group(2) or "name"
                combined_fields_raw = getattr(
                    segment, "name_index_combined_fields", ())
                if (
                    isinstance(combined_fields_raw, tuple)
                    and "name" in combined_fields_raw
                    and "description" in combined_fields_raw
                ):
                    lines = list(segment.lines) if segment.lines else [""]
                    name_value = lines[0] if lines else ""
                    description_lines = lines[1:]
                    if description_lines and description_lines[0] == "":
                        description_lines = description_lines[1:]
                    description_value = "\n".join(description_lines)
                    field_values = values_by_entry_id.setdefault(entry_id, {})
                    field_values["name"] = name_value
                    field_values["description"] = description_value
                    continue
                entry_value = "\n".join(segment.lines) if segment.lines else ""
                field_values = values_by_entry_id.setdefault(entry_id, {})
                field_values[field_name] = entry_value

            if values_by_entry_id:
                for row in session.data:
                    if not isinstance(row, dict):
                        continue
                    entry_id = row.get("id")
                    if not isinstance(entry_id, int):
                        continue
                    field_values = values_by_entry_id.get(entry_id)
                    if not field_values:
                        continue
                    for field_name, entry_value in field_values.items():
                        row[field_name] = entry_value
            # Mixed files (e.g. Troops.json) can have both name-index rows and
            # command bundles that must also be rebuilt.
            if is_name_index_session and not session.bundles:
                return

        for bundle in session.bundles:
            rebuilt: list[Any] = []
            for token in bundle.tokens:
                if token.kind == "raw":
                    rebuilt.append(token.raw_entry)
                elif token.segment is not None:
                    rebuilt.extend(
                        self._build_entries_for_segment(token.segment))
            bundle.commands_ref[:] = rebuilt

    def _build_source_data_for_session(self, session: FileSession) -> Any:
        source_data = copy.deepcopy(session.data)
        list_mapping: dict[int, list[Any]] = {}
        self._collect_list_mapping_from_copied_data(
            session.data,
            source_data,
            list_mapping,
        )

        source_bundles: list[CommandBundle] = []
        for bundle in session.bundles:
            mapped_commands_ref = list_mapping.get(id(bundle.commands_ref))
            if not isinstance(mapped_commands_ref, list):
                # Fallback to legacy full deep-copy path when bundle list mapping is unknown.
                source_session = copy.deepcopy(session)
                self._apply_session_to_json(source_session)
                return source_session.data
            source_bundles.append(
                CommandBundle(
                    context=bundle.context,
                    commands_ref=mapped_commands_ref,
                    tokens=list(bundle.tokens),
                )
            )

        source_session = FileSession(
            path=session.path,
            data=source_data,
            bundles=source_bundles,
            segments=session.segments,
            dirty=session.dirty,
        )
        for attr_name, attr_value in vars(session).items():
            if attr_name in {"path", "data", "bundles", "segments", "dirty"}:
                continue
            setattr(source_session, attr_name, attr_value)
        self._apply_session_to_json(source_session)
        return source_data

    def _collect_list_mapping_from_copied_data(
        self,
        original_node: Any,
        copied_node: Any,
        mapping: dict[int, list[Any]],
    ) -> None:
        if isinstance(original_node, list) and isinstance(copied_node, list):
            mapping[id(original_node)] = copied_node
            pair_count = min(len(original_node), len(copied_node))
            for index in range(pair_count):
                self._collect_list_mapping_from_copied_data(
                    original_node[index],
                    copied_node[index],
                    mapping,
                )
            return
        if isinstance(original_node, dict) and isinstance(copied_node, dict):
            for key, original_value in original_node.items():
                if key not in copied_node:
                    continue
                self._collect_list_mapping_from_copied_data(
                    original_value,
                    copied_node[key],
                    mapping,
                )

    def _mark_session_source_saved(self, session: FileSession) -> None:
        for segment in session.segments:
            if segment.translation_only:
                continue
            normalized = list(segment.lines) if segment.lines else [""]
            segment.lines = normalized
            segment.original_lines = list(normalized)
            segment.source_lines = list(normalized)
            segment.inserted = False
            segment.merged_segments = []
        setattr(session, "_has_external_source_edits", False)

    def _save_session_snapshot_to_db(
        self,
        session: FileSession,
        *,
        save_working_snapshot: bool = True,
    ) -> None:
        if self.version_db is None:
            raise RuntimeError("Version database is not initialized.")
        rel_path = self._relative_path(session.path)
        translated_data = self._export_translated_data_for_session(session)
        active_profile_raw = getattr(self, "active_translation_profile_id", "")
        active_profile_id = (
            active_profile_raw.strip()
            if isinstance(active_profile_raw, str) and active_profile_raw.strip()
            else DEFAULT_TRANSLATION_PROFILE_ID
        )
        if save_working_snapshot:
            working_data = self._build_source_data_for_session(session)
            self.version_db.save_working_snapshot(rel_path, working_data)
        self.version_db.save_translated_snapshot(
            rel_path,
            translated_data,
            profile_id=active_profile_id,
        )

    def _save_session(
        self,
        session: FileSession,
        refresh_current_view: bool = False,
        *,
        save_translation_state: bool = True,
        show_status_message: bool = True,
    ) -> bool:
        if self.version_db is None:
            QMessageBox.critical(
                cast(QWidget, self),
                "Save failed",
                "Version database is not initialized. Reload the folder and try again.",
            )
            return False

        translator_mode = self._is_translator_mode()
        source_dirty_before_save = self._session_has_source_changes(session)
        linked_sessions: list[FileSession] = []
        if source_dirty_before_save:
            linked_sessions = self._sync_actor_alias_targets_for_session(session)
        try:
            if save_translation_state and (not self._save_translation_state([session.path])):
                return False

            save_working_snapshot = (not translator_mode) or source_dirty_before_save
            self._save_session_snapshot_to_db(
                session,
                save_working_snapshot=save_working_snapshot,
            )
            if translator_mode:
                active_profile_raw = getattr(self, "active_translation_profile_id", "")
                active_profile_id = (
                    active_profile_raw.strip()
                    if isinstance(active_profile_raw, str) and active_profile_raw.strip()
                    else DEFAULT_TRANSLATION_PROFILE_ID
                )
                self._save_translated_actor_alias_target_snapshots_for_session(
                    session,
                    profile_id=active_profile_id,
                )
            if self.index_db is not None:
                try:
                    rel_path = self._relative_path(session.path)
                    self.index_db.log_changes(
                        rel_path,
                        self._collect_change_log(session),
                    )
                    self.index_db.update_file_index(
                        rel_path,
                        session.path.stat().st_mtime,
                        session.segments,
                    )
                except Exception:
                    logger.exception(
                        "Failed to update index DB while saving '%s'.", session.path
                    )

            if translator_mode:
                if source_dirty_before_save:
                    self._mark_session_source_saved(session)
                    self._clear_structural_history_for_path(session.path)
                self._mark_session_translation_saved(session)
            else:
                self._mark_session_source_saved(session)
                self._mark_session_translation_saved(session)
                self._clear_structural_history_for_path(session.path)

            self._refresh_dirty_state(session)
            if refresh_current_view and self.current_path == session.path:
                rerender_nearby = getattr(
                    self, "_rerender_blocks_near_viewport", None)
                if callable(rerender_nearby):
                    rerender_nearby()
                refresh_visuals = getattr(self, "_refresh_block_visual_states", None)
                if callable(refresh_visuals):
                    refresh_visuals()
                refresh_detail = getattr(self, "_refresh_translator_detail_panel", None)
                if callable(refresh_detail):
                    refresh_detail()

            linked_count = 0
            linked_failures = 0
            for linked_session in linked_sessions:
                if linked_session.path == session.path:
                    continue
                if not self._session_has_source_changes(linked_session):
                    continue
                if self._save_session(
                    linked_session,
                    refresh_current_view=(self.current_path == linked_session.path),
                    save_translation_state=False,
                    show_status_message=False,
                ):
                    linked_count += 1
                else:
                    linked_failures += 1
            if linked_failures > 0:
                return False

            if show_status_message:
                if translator_mode and not source_dirty_before_save:
                    self.statusBar().showMessage(
                        f"Saved TL snapshot to DB: {session.path.name}")
                else:
                    if linked_count > 0:
                        file_label = "file" if linked_count == 1 else "files"
                        self.statusBar().showMessage(
                            f"Saved snapshot to DB: {session.path.name} (+{linked_count} linked {file_label})."
                        )
                    else:
                        self.statusBar().showMessage(
                            f"Saved snapshot to DB: {session.path.name}")
            return True
        except Exception as exc:
            logger.exception("Failed to save snapshot for '%s'.", session.path)
            QMessageBox.critical(
                cast(QWidget, self),
                "Save failed",
                f"Failed to save snapshot for:\n{session.path}\n\n{exc}",
            )
            return False

    def _save_current_file(self) -> bool:
        if self.current_path is None:
            QMessageBox.warning(
                cast(QWidget, self), "No file selected", "Select a file before saving.")
            return False
        session = self.sessions.get(self.current_path)
        if session is None:
            QMessageBox.warning(cast(QWidget, self), "Not loaded",
                                "Current file has not been loaded yet.")
            return False

        source_dirty = self._session_has_source_changes(session)
        tl_dirty = self._session_has_translation_changes(session)

        if self._is_translator_mode():
            if not source_dirty and not tl_dirty:
                self.statusBar().showMessage("No unsaved changes in current file.")
                return True
            return self._save_session(session, refresh_current_view=True)

        if not source_dirty and not tl_dirty:
            self.statusBar().showMessage("No unsaved changes in current file.")
            return True
        return self._save_session(session, refresh_current_view=True)

    def _on_reset_current_file_requested(self) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return
        if self._is_translator_mode():
            if not self._session_has_translation_changes(session):
                self.statusBar().showMessage("No unsaved TL changes in current file.")
                return
            button = QMessageBox.question(
                cast(QWidget, self),
                "Reset current TL",
                f"Discard unsaved TL changes in '{session.path.name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if button != QMessageBox.StandardButton.Yes:
                return
            for segment in session.segments:
                segment.translation_lines = list(
                    segment.original_translation_lines)
                segment.translation_speaker = segment.original_translation_speaker
                segment.disable_line1_speaker_inference = bool(
                    segment.original_disable_line1_speaker_inference
                )
                segment.force_line1_speaker_inference = bool(
                    segment.original_force_line1_speaker_inference
                )
            self._refresh_dirty_state(session)
            rerender_nearby = getattr(self, "_rerender_blocks_near_viewport", None)
            if callable(rerender_nearby):
                rerender_nearby()
                refresh_visuals = getattr(self, "_refresh_block_visual_states", None)
                if callable(refresh_visuals):
                    refresh_visuals()
                refresh_detail = getattr(self, "_refresh_translator_detail_panel", None)
                if callable(refresh_detail):
                    refresh_detail()
            else:
                self._render_session(session)
            self.statusBar().showMessage(
                f"Reset TL changes in {session.path.name}.")
            return

        if not self._session_has_source_changes(session):
            self.statusBar().showMessage("No unsaved source changes in current JSON.")
            return

        button = QMessageBox.question(
            cast(QWidget, self),
            "Reset current JSON",
            f"Discard all unsaved changes in '{session.path.name}' and reload from saved snapshot?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if button != QMessageBox.StandardButton.Yes:
            return

        before = session
        self._open_file(session.path, force_reload=True)
        reloaded = self.sessions.get(session.path)
        if reloaded is not None and reloaded is not before and not reloaded.dirty:
            self.statusBar().showMessage(
                f"Reset {session.path.name} to saved snapshot state.")

    def _save_all_files(self) -> bool:
        dirty_paths = [
            path
            for path, session in self.sessions.items()
            if self._session_has_source_changes(session)
            or self._session_has_translation_changes(session)
        ]
        if not dirty_paths:
            self.statusBar().showMessage("No unsaved files.")
            return True

        if not self._save_translation_state(dirty_paths):
            return False

        failures: list[str] = []
        progress_dialog = self._create_save_all_progress_dialog(len(dirty_paths))
        total_dirty = len(dirty_paths)
        for index, path in enumerate(dirty_paths, start=1):
            self._update_save_all_progress_dialog(
                progress_dialog,
                index - 1,
                f"Saving {index}/{total_dirty}: {path.name}",
            )
            session = self.sessions.get(path)
            if session is None:
                continue
            ok = self._save_session(
                session,
                refresh_current_view=(path == self.current_path),
                save_translation_state=False,
                show_status_message=False,
            )
            if not ok:
                failures.append(path.name)
            self._update_save_all_progress_dialog(
                progress_dialog,
                index,
                f"Saved {index}/{total_dirty}: {path.name}",
            )
        if progress_dialog is not None:
            progress_dialog.close()

        if failures:
            QMessageBox.warning(
                cast(QWidget, self),
                "Save completed with errors",
                "Some files failed to save:\n" + "\n".join(failures),
            )
            return False

        saved_count = len(dirty_paths)
        file_label = "snapshot file" if saved_count == 1 else "snapshot files"
        self.statusBar().showMessage(f"Saved {saved_count} {file_label} to DB.")
        return True

    def _create_save_all_progress_dialog(
        self,
        total_files: int,
    ) -> Optional[QProgressDialog]:
        app = QApplication.instance()
        if app is None:
            return None
        dialog = QProgressDialog(
            "Preparing save...",
            "",
            0,
            max(1, total_files),
            cast(QWidget, self),
        )
        dialog.setWindowTitle("Saving files")
        dialog.setMinimumDuration(0)
        dialog.setCancelButton(None)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.show()
        app.processEvents()
        return dialog

    def _update_save_all_progress_dialog(
        self,
        dialog: Optional[QProgressDialog],
        value: int,
        label_text: str,
    ) -> None:
        app = QApplication.instance()
        if dialog is not None:
            dialog.setValue(value)
            dialog.setLabelText(label_text)
        if app is not None:
            app.processEvents()

    def _selected_apply_version(self) -> ApplyVersionKind:
        raw = self.apply_version_combo.currentData()
        if raw == "original":
            return "original"
        if raw == "working":
            return "working"
        return "translated"

    def _system_game_title_from_snapshot(
        self,
        version: ApplyVersionKind,
        *,
        translated_profile_id: str = DEFAULT_TRANSLATION_PROFILE_ID,
    ) -> str:
        if self.version_db is None:
            return ""
        candidate_paths: list[Path] = []
        for path in self.file_paths:
            if path.name.strip().lower() == "system.json":
                candidate_paths.append(path)
        if not candidate_paths:
            for path in self.file_paths:
                if is_tyrano_config_path(path):
                    candidate_paths.append(path)
        for candidate_path in candidate_paths:
            rel_path = self._relative_path(candidate_path)
            payload = self.version_db.get_snapshot_payload(
                rel_path,
                version,
                profile_id=translated_profile_id,
            )
            if not payload:
                continue
            try:
                decoded = json.loads(payload)
            except Exception:
                continue
            if isinstance(decoded, dict):
                title_raw = decoded.get("gameTitle")
                if isinstance(title_raw, str) and title_raw.strip():
                    return title_raw
            title_text = tyrano_config_title_from_data(decoded).strip()
            if title_text:
                return title_text
        return ""

    def _index_html_candidates(self) -> list[Path]:
        if self.data_dir is None:
            return []
        data_dir = self.data_dir
        candidates = [
            data_dir.parent / "index.html",
            data_dir / "index.html",
            data_dir.parent.parent / "index.html",
        ]
        unique_candidates: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_candidates.append(resolved)
        return unique_candidates

    def _replace_index_html_title(self, html_text: str, title_text: str) -> tuple[str, bool]:
        escaped_title = html.escape(title_text, quote=False)
        if _HTML_TITLE_TAG_RE.search(html_text):
            updated = _HTML_TITLE_TAG_RE.sub(
                lambda match: f"{match.group(1)}{escaped_title}{match.group(3)}",
                html_text,
                count=1,
            )
            return updated, True
        head_close = re.search(r"</head\s*>", html_text, re.IGNORECASE)
        if head_close is None:
            return html_text, False
        newline = "\r\n" if "\r\n" in html_text else "\n"
        insert_text = f"<title>{escaped_title}</title>{newline}"
        insert_at = head_close.start()
        updated = html_text[:insert_at] + insert_text + html_text[insert_at:]
        return updated, True

    def _apply_game_title_to_index_html(self, game_title: str) -> tuple[bool, str]:
        stripped_title = game_title.strip()
        if not stripped_title:
            return False, ""
        index_path = next(
            (candidate for candidate in self._index_html_candidates() if candidate.is_file()),
            None,
        )
        if index_path is None:
            return False, "index.html not found."

        try:
            original_text = index_path.read_text(encoding="utf-8")
        except Exception:
            return False, f"Could not read {index_path.name} as UTF-8."

        updated_text, replaced = self._replace_index_html_title(
            original_text,
            stripped_title,
        )
        if not replaced:
            return False, f"Could not locate <title> or </head> in {index_path.name}."
        if updated_text == original_text:
            return False, ""

        if self.backup_check.isChecked():
            backup_path = index_path.with_suffix(index_path.suffix + ".bak")
            if not backup_path.exists():
                shutil.copy2(index_path, backup_path)
        index_path.write_text(updated_text, encoding="utf-8")
        return True, str(index_path)

    def _apply_selected_snapshot_to_game_files(self) -> None:
        if self.data_dir is None:
            QMessageBox.warning(
                cast(QWidget, self),
                "No folder selected",
                "Load a data folder before applying snapshots.",
            )
            return
        if self.version_db is None:
            QMessageBox.warning(
                cast(QWidget, self),
                "Snapshot DB unavailable",
                "Reload the data folder to initialize the snapshot database.",
            )
            return
        if not self.sessions:
            QMessageBox.warning(
                cast(QWidget, self),
                "No files loaded",
                "Load files before applying snapshots.",
            )
            return
        if not self._prompt_unsaved_if_any():
            return

        version = self._selected_apply_version()
        if version == "original":
            version_label = "Original"
        elif version == "working":
            version_label = "Working"
        else:
            version_label = "Translated"
        translated_profile_id = DEFAULT_TRANSLATION_PROFILE_ID
        translated_profile_name = ""
        if version == "translated":
            active_profile_raw = getattr(self, "active_translation_profile_id", "")
            active_profile_id = (
                active_profile_raw.strip()
                if isinstance(active_profile_raw, str) and active_profile_raw.strip()
                else DEFAULT_TRANSLATION_PROFILE_ID
            )
            chooser = getattr(self, "_prompt_translation_profile_for_apply", None)
            if callable(chooser):
                selected_profile_id = chooser(default_profile_id=active_profile_id)
                if not isinstance(selected_profile_id, str):
                    return
                normalized_selected = selected_profile_id.strip()
                if not normalized_selected:
                    return
                translated_profile_id = normalized_selected
            else:
                translated_profile_id = active_profile_id
            profile_name_resolver = getattr(self, "_translation_profile_name", None)
            if callable(profile_name_resolver):
                try:
                    resolved_name = profile_name_resolver(translated_profile_id)
                except Exception:
                    resolved_name = ""
                if isinstance(resolved_name, str):
                    translated_profile_name = resolved_name.strip()
            if not translated_profile_name:
                translated_profile_name = translated_profile_id

        version_status_label = version_label
        if version == "translated":
            version_status_label = f"{version_label} ({translated_profile_name})"
        button = QMessageBox.question(
            cast(QWidget, self),
            "Apply snapshots to game files",
            (
                f"Apply '{version_status_label}' snapshots to game files for:\n"
                f"{self.data_dir}\n\n"
                "This will overwrite current file contents."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if button != QMessageBox.StandardButton.Yes:
            return

        if version == "translated":
            try:
                self._refresh_translated_snapshots_from_loaded_sessions(
                    profile_id=translated_profile_id,
                )
            except Exception:
                logger.exception("Failed to refresh translated snapshots from loaded sessions.")

        applied = 0
        missing: list[str] = []
        failed: list[str] = []
        index_title_applied = False
        index_title_warning = ""
        translation_state_path = getattr(self, "translation_state_path", None)
        target_paths: list[Path] = []
        for path in self.file_paths:
            if path not in self.sessions:
                continue
            if isinstance(translation_state_path, Path) and path.resolve() == translation_state_path.resolve():
                continue
            target_paths.append(path)
        for path in target_paths:
            rel_path = self._relative_path(path)
            payload = self.version_db.get_snapshot_payload(
                rel_path,
                version,
                profile_id=translated_profile_id,
            )
            if not payload:
                missing.append(path.name)
                continue
            try:
                if self.backup_check.isChecked():
                    backup_path = path.with_suffix(path.suffix + ".bak")
                    if not backup_path.exists():
                        shutil.copy2(path, backup_path)
                output_text = payload
                if is_plugins_js_path(path):
                    decoded_payload = json.loads(payload)
                    output_text = plugins_js_source_from_data(decoded_payload)
                elif is_tyrano_script_path(path) or is_tyrano_js_path(path):
                    decoded_payload = json.loads(payload)
                    output_text = tyrano_script_source_from_data(decoded_payload)
                elif is_tyrano_config_path(path):
                    decoded_payload = json.loads(payload)
                    output_text = tyrano_config_source_from_data(decoded_payload)
                with path.open("w", encoding="utf-8") as dst:
                    dst.write(output_text)
                applied += 1
            except Exception as exc:
                logger.exception("Failed to apply snapshot to '%s'.", path)
                failed.append(f"{path.name}: {exc}")

        if applied > 0:
            try:
                game_title = self._system_game_title_from_snapshot(
                    version,
                    translated_profile_id=translated_profile_id,
                )
                index_title_applied, index_title_warning = self._apply_game_title_to_index_html(
                    game_title
                )
            except Exception as exc:
                logger.exception("Failed while syncing index.html title.")
                failed.append(f"index.html title sync: {exc}")

        if failed:
            QMessageBox.warning(
                cast(QWidget, self),
                "Apply completed with errors",
                "Some files failed:\n" + "\n".join(failed),
            )
        if missing:
            QMessageBox.warning(
                cast(QWidget, self),
                "Missing snapshots",
                "No snapshot found for:\n" + "\n".join(missing),
            )
        if applied <= 0:
            self.statusBar().showMessage("No files were applied.")
            return

        try:
            self.version_db.set_applied_version(version)
            if version == "translated":
                self.version_db.set_applied_translation_profile(translated_profile_id)
        except Exception:
            logger.exception("Failed to persist applied snapshot version '%s'.", version)

        # Applying snapshots to game files should not mutate editor/session state.
        # Keep in-memory snapshots untouched until user explicitly reloads.
        if missing or failed:
            file_label = "file" if applied == 1 else "files"
            title_suffix = " Synced index.html title." if index_title_applied else ""
            self.statusBar().showMessage(
                f"Applied {version_status_label} snapshots to {applied} {file_label} with warnings.{title_suffix}"
            )
        else:
            file_label = "file" if applied == 1 else "files"
            status_suffix = " Synced index.html title." if index_title_applied else ""
            if index_title_warning:
                status_suffix += f" ({index_title_warning})"
            self.statusBar().showMessage(
                f"Applied {version_status_label} snapshots to {applied} {file_label}.{status_suffix}"
            )

    def _export_translated_data_for_session(self, session: FileSession) -> Any:
        exported_session = copy.deepcopy(session)
        source_lookup = {segment.uid: segment for segment in session.segments}
        export_lookup = {segment.uid: segment for segment in exported_session.segments}

        tl_followups_by_source_uid: dict[str, list[str]] = {}
        last_source_uid = ""
        orphan_tl_uids: list[str] = []
        for segment in session.segments:
            if segment.translation_only:
                if last_source_uid:
                    tl_followups_by_source_uid.setdefault(last_source_uid, []).append(segment.uid)
                else:
                    orphan_tl_uids.append(segment.uid)
                continue
            if segment.segment_kind == "map_display_name":
                continue
            last_source_uid = segment.uid
        if orphan_tl_uids and session.segments:
            first_source_uid = ""
            for segment in session.segments:
                if not segment.translation_only and segment.segment_kind != "map_display_name":
                    first_source_uid = segment.uid
                    break
            if first_source_uid:
                tl_followups_by_source_uid.setdefault(first_source_uid, [])
                tl_followups_by_source_uid[first_source_uid] = (
                    list(orphan_tl_uids) + tl_followups_by_source_uid[first_source_uid]
                )

        for export_segment in exported_session.segments:
            source_segment = source_lookup.get(export_segment.uid)
            if source_segment is None:
                continue
            export_segment.lines = self._translated_export_lines_for_segment(source_segment)

            speaker_en = source_segment.translation_speaker.strip()
            if not speaker_en:
                speaker_key = NO_SPEAKER_KEY
                speaker_key_resolver = getattr(self, "_speaker_key_for_segment", None)
                if callable(speaker_key_resolver):
                    try:
                        resolved_key = speaker_key_resolver(source_segment)
                    except Exception:
                        resolved_key = NO_SPEAKER_KEY
                    if isinstance(resolved_key, str) and resolved_key.strip():
                        speaker_key = resolved_key.strip()

                if speaker_key == NO_SPEAKER_KEY:
                    explicit_speaker = source_segment.speaker_name.strip()
                    if explicit_speaker:
                        speaker_key = explicit_speaker

                if speaker_key != NO_SPEAKER_KEY:
                    speaker_translation_resolver = getattr(
                        self,
                        "_speaker_translation_for_key",
                        None,
                    )
                    if callable(speaker_translation_resolver):
                        try:
                            resolved_translation = speaker_translation_resolver(speaker_key)
                        except Exception:
                            resolved_translation = ""
                        if isinstance(resolved_translation, str):
                            speaker_en = resolved_translation.strip()

                if not speaker_en and speaker_key != NO_SPEAKER_KEY:
                    speaker_map_raw = getattr(self, "speaker_translation_map", None)
                    if isinstance(speaker_map_raw, dict):
                        map_value = speaker_map_raw.get(speaker_key, "")
                        if isinstance(map_value, str):
                            speaker_en = map_value.strip()

            has_explicit_speaker = source_segment.speaker_name != NO_SPEAKER_KEY
            if speaker_en and has_explicit_speaker:
                params = export_segment.params
                while len(params) <= 4:
                    params.append("")
                params[4] = speaker_en
                export_segment.code101["parameters"] = params

        if tl_followups_by_source_uid:
            for bundle in exported_session.bundles:
                idx = 0
                while idx < len(bundle.tokens):
                    token = bundle.tokens[idx]
                    if token.kind != "dialogue" or token.segment is None:
                        idx += 1
                        continue
                    source_uid = token.segment.uid
                    followup_uids = tl_followups_by_source_uid.get(source_uid, [])
                    if not followup_uids:
                        idx += 1
                        continue
                    inserted_tokens: list[CommandToken] = []
                    for followup_uid in followup_uids:
                        followup_segment = export_lookup.get(followup_uid)
                        if followup_segment is None:
                            continue
                        inserted_tokens.append(
                            CommandToken(kind="dialogue", segment=followup_segment)
                        )
                    if inserted_tokens:
                        bundle.tokens[idx + 1:idx + 1] = inserted_tokens
                        idx += len(inserted_tokens)
                    idx += 1

        self._apply_session_to_json(exported_session)
        return exported_session.data
