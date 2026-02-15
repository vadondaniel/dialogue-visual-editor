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

from PySide6.QtWidgets import QMessageBox, QWidget

from ..core.models import NO_SPEAKER_KEY, CommandToken, DialogueSegment, FileSession
from ..core.parser import is_plugins_js_path, plugins_js_source_from_data
from ..core.script_message_utils import build_game_message_call
from ..core.text_utils import (
    CONTROL_TOKEN_RE,
    chunk_lines_by_row_budget,
    total_display_rows,
    visible_length,
)

ApplyVersionKind = Literal["original", "working", "translated"]
_HTML_TITLE_TAG_RE = re.compile(
    r"(<title\b[^>]*>)(.*?)(</title>)",
    re.IGNORECASE | re.DOTALL,
)
logger = logging.getLogger(__name__)


class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class PersistenceExportMixin(_EditorHostTypingFallback):
    _TRAILING_COLOR_CODE_RE = re.compile(r"\\[Cc]\[(\d+)\]\s*$")

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

    def _segment_has_trailing_color_code_problem(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
    ) -> bool:
        _ = translator_mode
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

        translation_lines_resolver = getattr(
            self, "_segment_translation_lines_for_translation", None
        )
        if callable(translation_lines_resolver):
            try:
                resolved_tl = translation_lines_resolver(segment)
            except Exception:
                resolved_tl = None
            tl_lines = (
                self._normalize_translation_lines(resolved_tl)
                if isinstance(resolved_tl, list)
                else self._normalize_translation_lines(segment.translation_lines)
            )
        else:
            tl_lines = self._normalize_translation_lines(segment.translation_lines)

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

    def _segment_has_control_code_mismatch_problem(
        self,
        segment: DialogueSegment,
        translator_mode: bool,
    ) -> bool:
        _ = translator_mode
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

        translation_lines_resolver = getattr(
            self, "_segment_translation_lines_for_translation", None
        )
        if callable(translation_lines_resolver):
            try:
                resolved_tl = translation_lines_resolver(segment)
            except Exception:
                resolved_tl = None
            tl_lines = (
                self._normalize_translation_lines(resolved_tl)
                if isinstance(resolved_tl, list)
                else self._normalize_translation_lines(segment.translation_lines)
            )
        else:
            tl_lines = self._normalize_translation_lines(segment.translation_lines)

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
        if self._is_name_index_session(session):
            return False
        if not segment.is_structural_dialogue:
            return False
        if (not translator_mode) and segment.translation_only:
            return False

        check_char_limit = self._problem_check_char_limit_enabled()
        check_line_limit = self._problem_check_line_limit_enabled()
        check_control_mismatch = self._problem_check_control_mismatch_enabled()
        check_trailing_color_code = self._problem_check_trailing_color_code_enabled()
        if not (
            check_char_limit
            or check_line_limit
            or check_control_mismatch
            or check_trailing_color_code
        ):
            return False

        lines = (
            self._normalize_translation_lines(segment.translation_lines)
            if translator_mode
            else list(segment.lines) if segment.lines else [""]
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
            if self._segment_has_control_code_mismatch_problem(segment, translator_mode):
                return True
        if check_trailing_color_code:
            if self._segment_has_trailing_color_code_problem(segment, translator_mode):
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

    def _refresh_dirty_state(self, session: FileSession) -> None:
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
            actor_mode = self._is_name_index_session(session)
            translator_mode = self._is_translator_mode()
            display_segments_resolver = getattr(self, "_display_segments_for_session", None)
            if callable(display_segments_resolver):
                display_segments_raw = display_segments_resolver(
                    session,
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                )
                block_count = (
                    len(display_segments_raw)
                    if isinstance(display_segments_raw, list)
                    else len(session.segments)
                )
            else:
                block_count = len(session.segments)
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
        item = self.file_items.get(path)
        session = self.sessions.get(path)
        if item is None:
            return
        if session is None:
            item.setText(path.name)
            return
        prefix = "* " if session.dirty else ""
        actor_mode = self._is_name_index_session(session)
        translator_mode = self._is_translator_mode()
        display_segments_resolver = getattr(self, "_display_segments_for_session", None)
        if callable(display_segments_resolver):
            display_segments_raw = display_segments_resolver(
                session,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
            )
            display_count = (
                len(display_segments_raw)
                if isinstance(display_segments_raw, list)
                else len(session.segments)
            )
        else:
            display_count = len(session.segments)
        suffix = " [empty]" if display_count == 0 else ""
        problems = self._problem_count_for_session(session)
        problem_badge = f" [!{problems}]" if problems > 0 else ""
        item.setText(
            f"{prefix}{path.name} ({display_count}){problem_badge}{suffix}")

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
    ) -> None:
        params = entry.get("parameters")
        if not isinstance(params, list):
            params = []
        while len(params) <= 0:
            params.append("")
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
        built_entries: list[dict[str, Any]] = []
        add_cursor = 0

        for idx, template in enumerate(templates):
            role = roles[idx] if idx < len(roles) else "other"
            quote_char = quotes[idx] if idx < len(quotes) else '"'
            rebuilt_entry = copy.deepcopy(template)
            if role == "speaker":
                self._set_script_message_call_entry(
                    rebuilt_entry,
                    kind="setSpeakerName",
                    text=speaker_text,
                    quote_char=quote_char,
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

    def _apply_session_to_json(self, session: FileSession) -> None:
        is_name_index_session = (
            bool(getattr(session, "is_name_index_session", False))
            or bool(getattr(session, "is_actor_index_session", False))
        )

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

        if is_name_index_session and isinstance(session.data, list):
            uid_prefix_raw = getattr(session, "name_index_uid_prefix", "A")
            uid_prefix = uid_prefix_raw.strip() if isinstance(uid_prefix_raw, str) else "A"
            id_pattern = re.compile(
                rf":{re.escape(uid_prefix)}:(\d+)(?::([A-Za-z0-9_]+))?$")
            values_by_entry_id: dict[int, dict[str, str]] = {}
            for segment in session.segments:
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
        source_session = copy.deepcopy(session)
        self._apply_session_to_json(source_session)
        return source_session.data

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

    def _save_session_snapshot_to_db(self, session: FileSession) -> None:
        if self.version_db is None:
            raise RuntimeError("Version database is not initialized.")
        rel_path = self._relative_path(session.path)
        working_data = self._build_source_data_for_session(session)
        translated_data = self._export_translated_data_for_session(session)
        self.version_db.save_working_snapshot(rel_path, working_data)
        self.version_db.save_translated_snapshot(rel_path, translated_data)

    def _save_session(self, session: FileSession, refresh_current_view: bool = False) -> bool:
        if self.version_db is None:
            QMessageBox.critical(
                cast(QWidget, self),
                "Save failed",
                "Version database is not initialized. Reload the folder and try again.",
            )
            return False

        translator_mode = self._is_translator_mode()
        source_dirty_before_save = self._session_has_source_changes(session)
        try:
            if not self._save_translation_state([session.path]):
                return False

            self._save_session_snapshot_to_db(session)
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
                self._render_session(session, preserve_scroll=True)

            if translator_mode and not source_dirty_before_save:
                self.statusBar().showMessage(
                    f"Saved TL snapshot to DB: {session.path.name}")
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
        if self._is_translator_mode():
            dirty_paths = [
                path
                for path, session in self.sessions.items()
                if self._session_has_source_changes(session)
                or self._session_has_translation_changes(session)
            ]
            if not dirty_paths:
                self.statusBar().showMessage("No unsaved files.")
                return True
        else:
            dirty_paths = [
                path
                for path, session in self.sessions.items()
                if self._session_has_source_changes(session)
                or self._session_has_translation_changes(session)
            ]
            if not dirty_paths:
                self.statusBar().showMessage("No unsaved files.")
                return True

        failures: list[str] = []
        for path in dirty_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            ok = self._save_session(
                session, refresh_current_view=(path == self.current_path))
            if not ok:
                failures.append(path.name)

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

    def _selected_apply_version(self) -> ApplyVersionKind:
        raw = self.apply_version_combo.currentData()
        if raw == "original":
            return "original"
        if raw == "working":
            return "working"
        return "translated"

    def _system_game_title_from_snapshot(self, version: ApplyVersionKind) -> str:
        if self.version_db is None:
            return ""
        system_path: Optional[Path] = None
        for path in self.file_paths:
            if path.name.strip().lower() == "system.json":
                system_path = path
                break
        if system_path is None:
            return ""
        rel_path = self._relative_path(system_path)
        payload = self.version_db.get_snapshot_payload(rel_path, version)
        if not payload:
            return ""
        try:
            decoded = json.loads(payload)
        except Exception:
            return ""
        if not isinstance(decoded, dict):
            return ""
        title_raw = decoded.get("gameTitle")
        return title_raw if isinstance(title_raw, str) else ""

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
        button = QMessageBox.question(
            cast(QWidget, self),
            "Apply snapshots to game files",
            (
                f"Apply '{version_label}' snapshots to game files for:\n"
                f"{self.data_dir}\n\n"
                "This will overwrite current file contents."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if button != QMessageBox.StandardButton.Yes:
            return

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
            payload = self.version_db.get_snapshot_payload(rel_path, version)
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
                with path.open("w", encoding="utf-8") as dst:
                    dst.write(output_text)
                applied += 1
            except Exception as exc:
                logger.exception("Failed to apply snapshot to '%s'.", path)
                failed.append(f"{path.name}: {exc}")

        if applied > 0:
            try:
                game_title = self._system_game_title_from_snapshot(version)
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
        except Exception:
            logger.exception("Failed to persist applied snapshot version '%s'.", version)

        current_dir = self.data_dir
        if version == "translated":
            self._load_data_folder(
                current_dir,
                force_disk_import=True,
                import_target_version="translated",
            )
        else:
            self._load_data_folder(current_dir)
        if missing or failed:
            file_label = "file" if applied == 1 else "files"
            title_suffix = " Synced index.html title." if index_title_applied else ""
            self.statusBar().showMessage(
                f"Applied {version_label} snapshots to {applied} {file_label} with warnings.{title_suffix}"
            )
        else:
            file_label = "file" if applied == 1 else "files"
            status_suffix = " Synced index.html title." if index_title_applied else ""
            if index_title_warning:
                status_suffix += f" ({index_title_warning})"
            self.statusBar().showMessage(
                f"Applied {version_label} snapshots to {applied} {file_label}.{status_suffix}"
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
            last_source_uid = segment.uid
        if orphan_tl_uids and session.segments:
            first_source_uid = ""
            for segment in session.segments:
                if not segment.translation_only:
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
            visible_tl_lines = self._normalize_translation_lines(
                source_segment.translation_lines)
            visible_lines_resolver = getattr(
                self, "_segment_translation_lines_for_translation", None
            )
            if callable(visible_lines_resolver):
                try:
                    resolved_lines = visible_lines_resolver(source_segment)
                    if isinstance(resolved_lines, list):
                        visible_tl_lines = self._normalize_translation_lines(
                            resolved_lines
                        )
                except Exception:
                    pass
            has_tl = any(line.strip() for line in visible_tl_lines)
            if has_tl:
                compose_lines_resolver = getattr(
                    self, "_compose_translation_lines_for_segment", None
                )
                if callable(compose_lines_resolver):
                    try:
                        composed_lines = compose_lines_resolver(
                            source_segment, visible_tl_lines
                        )
                        export_segment.lines = self._normalize_translation_lines(
                            composed_lines
                        )
                    except Exception:
                        export_segment.lines = list(visible_tl_lines)
                else:
                    export_segment.lines = list(visible_tl_lines)
            else:
                export_segment.lines = list(source_segment.lines or [""])

            speaker_en = source_segment.translation_speaker.strip()
            if speaker_en and source_segment.speaker_name != NO_SPEAKER_KEY:
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
