from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QWidget

from ..core.models import (
    DialogueSegment,
    FileSession,
    NO_SPEAKER_KEY,
)
from ..core.text_utils import (
    fuzzy_compare_text,
    natural_sort_key,
    preview_text,
    similarity_signature,
    split_lines_preserve_empty,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton

logger = logging.getLogger(__name__)
_DEFAULT_TRANSLATION_PROFILE_ID = "default"
_DEFAULT_TRANSLATION_PROFILE_NAME = "Default"
_DEFAULT_SOURCE_LANGUAGE_CODE = "ja"
_DEFAULT_TARGET_LANGUAGE_CODE = "en"


class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class TranslationStateMixin(_EditorHostTypingFallback):
    # Provided by DialogueVisualEditor at runtime; declared for static analyzers.
    editor_mode_combo: "QComboBox"
    save_btn: "QPushButton | QAction"
    save_all_btn: "QPushButton | QAction"
    reset_json_btn: "QPushButton"
    auto_split_check: "QCheckBox"
    translation_state_path: Optional[Path]
    translation_state: dict[str, Any]
    active_translation_profile_id: str
    translation_profiles_meta: dict[str, dict[str, Any]]
    speaker_translation_map: dict[str, str]
    translation_uid_counter: int
    sessions: dict[Path, FileSession]
    current_path: Optional[Path]

    # Implemented by DialogueVisualEditor.
    def _rerender_current_file(self) -> None:
        ...

    def _relative_path(self, path: Path) -> str:
        ...

    def _is_translator_mode(self) -> bool:
        return str(self.editor_mode_combo.currentData()) == "translator"

    def _on_editor_mode_changed(self, _index: int) -> None:
        current_mode = str(self.editor_mode_combo.currentData())
        previous_mode_raw = getattr(self, "_editor_mode_last_data", current_mode)
        previous_mode = (
            previous_mode_raw if isinstance(previous_mode_raw, str) else current_mode
        )
        if current_mode != previous_mode:
            has_dirty = any(session.dirty for session in self.sessions.values())
            if has_dirty:
                response = QMessageBox.warning(
                    cast(QWidget, self),
                    "Unsaved changes",
                    (
                        "You have unsaved changes.\n"
                        "Switching edit mode changes how text is edited/shown.\n\n"
                        "Switch mode anyway?"
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if response != QMessageBox.StandardButton.Yes:
                    if not bool(getattr(self, "_editor_mode_reverting", False)):
                        setattr(self, "_editor_mode_reverting", True)
                        try:
                            previous_index = self.editor_mode_combo.findData(previous_mode)
                            if previous_index >= 0:
                                self.editor_mode_combo.setCurrentIndex(previous_index)
                        finally:
                            setattr(self, "_editor_mode_reverting", False)
                    return

        self._update_mode_controls()
        refresh_file_items = getattr(self, "_refresh_all_file_item_text", None)
        if callable(refresh_file_items):
            refresh_file_items()
        sync_mode_ui = getattr(self, "_sync_translator_mode_ui", None)
        if callable(sync_mode_ui):
            sync_mode_ui()
        refresh_window_title = getattr(self, "_update_window_title", None)
        if callable(refresh_window_title):
            refresh_window_title()
        self._rerender_current_file()

    def _update_mode_controls(self) -> None:
        translator_mode = self._is_translator_mode()
        self.save_btn.setText("Save")
        self.save_all_btn.setText("Save All")
        self.reset_json_btn.setText("Reset JSON")
        if translator_mode:
            self.auto_split_check.setToolTip(
                "Used when building translated snapshot data.")
        else:
            self.auto_split_check.setToolTip(
                "Auto-split long dialogue on save.")
        setattr(self, "_editor_mode_last_data", str(self.editor_mode_combo.currentData()))

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            lines: list[str] = []
            for item in value:
                if isinstance(item, str):
                    lines.append(item)
                elif item is None:
                    lines.append("")
                else:
                    lines.append(str(item))
            return lines or [""]
        if isinstance(value, str):
            return split_lines_preserve_empty(value)
        return [""]

    def _new_translation_uid(self) -> str:
        self.translation_uid_counter += 1
        return f"T{self.translation_uid_counter:08d}"

    def _segment_source_text_for_mapping(self, segment: DialogueSegment) -> str:
        return "\n".join(segment.lines or [""])

    def _segment_source_hash(self, segment: DialogueSegment) -> str:
        payload = "\n".join(
            [
                segment.segment_kind,
                segment.context,
                str(segment.background),
                str(segment.position),
                segment.face_name,
                str(segment.face_index),
                segment.speaker_name,
                self._segment_source_text_for_mapping(segment),
            ]
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _legacy_tyrano_dialogue_source_text_for_hash(segment: DialogueSegment) -> str:
        if segment.segment_kind != "tyrano_dialogue":
            return ""
        prefixes_raw = getattr(segment, "tyrano_line_prefixes", ())
        if not isinstance(prefixes_raw, (list, tuple)):
            return ""
        prefixes = [
            prefix if isinstance(prefix, str) else ""
            for prefix in prefixes_raw
        ]
        if not any(prefixes):
            return ""
        lines_raw = list(segment.lines or [""])
        lines = [
            line if isinstance(line, str) else ("" if line is None else str(line))
            for line in lines_raw
        ]
        prefixed_lines: list[str] = []
        for line_index, line_text in enumerate(lines):
            prefix = prefixes[line_index] if line_index < len(prefixes) else ""
            prefixed_lines.append(f"{prefix}{line_text}")
        return "\n".join(prefixed_lines)

    def _segment_source_hash_candidates(self, segment: DialogueSegment) -> list[str]:
        current_hash = self._segment_source_hash(segment)
        candidates = [current_hash]
        legacy_tyrano_source_text = self._legacy_tyrano_dialogue_source_text_for_hash(
            segment
        )
        if legacy_tyrano_source_text:
            legacy_tyrano_payload = "\n".join(
                [
                    segment.segment_kind,
                    segment.context,
                    str(segment.background),
                    str(segment.position),
                    segment.face_name,
                    str(segment.face_index),
                    segment.speaker_name,
                    legacy_tyrano_source_text,
                ]
            )
            legacy_tyrano_hash = hashlib.sha1(
                legacy_tyrano_payload.encode("utf-8")
            ).hexdigest()
            if legacy_tyrano_hash not in candidates:
                candidates.append(legacy_tyrano_hash)
        # Backward compatibility: older script-message parsing did not capture face
        # info, so saved state hashes used empty face values.
        if segment.segment_kind == "script_message":
            legacy_payload = "\n".join(
                [
                    segment.segment_kind,
                    segment.context,
                    str(segment.background),
                    str(segment.position),
                    "",
                    "0",
                    segment.speaker_name,
                    self._segment_source_text_for_mapping(segment),
                ]
            )
            legacy_hash = hashlib.sha1(legacy_payload.encode("utf-8")).hexdigest()
            if legacy_hash not in candidates:
                candidates.append(legacy_hash)
        return candidates

    def _translation_only_segment_uid(self, session: FileSession, tl_uid: str) -> str:
        safe_uid = tl_uid if tl_uid else self._new_translation_uid()
        return f"{session.path.name}:TI:{safe_uid}"

    def _ensure_unique_session_segment_uids(self, session: FileSession) -> int:
        seen_uids: set[str] = set()
        renamed_count = 0
        for index, segment in enumerate(session.segments, start=1):
            uid_raw = segment.uid if isinstance(segment.uid, str) else ""
            normalized_uid = uid_raw.strip()
            if not normalized_uid:
                normalized_uid = f"{session.path.name}:I:{index}"
            if normalized_uid not in seen_uids:
                if normalized_uid != uid_raw:
                    segment.uid = normalized_uid
                    renamed_count += 1
                seen_uids.add(normalized_uid)
                continue

            if segment.translation_only and segment.tl_uid:
                base_uid = f"{session.path.name}:TI:{segment.tl_uid}"
            else:
                base_uid = normalized_uid
            if not base_uid:
                base_uid = f"{session.path.name}:I:{index}"
            unique_uid = base_uid
            duplicate_suffix = 2
            while unique_uid in seen_uids:
                unique_uid = f"{base_uid}:dup{duplicate_suffix}"
                duplicate_suffix += 1
            segment.uid = unique_uid
            seen_uids.add(unique_uid)
            renamed_count += 1

        if renamed_count > 0:
            logger.warning(
                "Reassigned %d duplicate/blank segment UID(s) in '%s'.",
                renamed_count,
                session.path,
            )
        return renamed_count

    def _build_translation_only_segment_from_state(
        self,
        session: FileSession,
        tl_uid: str,
        entry: dict[str, Any],
        template_segment: Optional[DialogueSegment],
    ) -> DialogueSegment:
        template = template_segment
        context_raw = entry.get("context")
        context = context_raw if isinstance(context_raw, str) else (
            template.context if template is not None else ""
        )
        code101_raw = entry.get("code101")
        if isinstance(code101_raw, dict):
            code101 = copy.deepcopy(code101_raw)
        elif template is not None:
            code101 = copy.deepcopy(template.code101)
        else:
            code101 = {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]}
        code401_template_raw = entry.get("code401_template")
        if isinstance(code401_template_raw, dict):
            code401_template = copy.deepcopy(code401_template_raw)
        elif template is not None:
            code401_template = copy.deepcopy(template.code401_template)
        else:
            code401_template = {"code": 401, "indent": 0, "parameters": [""]}

        source_lines = self._normalize_translation_lines(entry.get("source_lines"))
        if not source_lines and template is not None:
            source_lines = list(
                template.source_lines or template.original_lines or template.lines or [""]
            )
        if not source_lines:
            source_lines = [""]

        original_lines = self._normalize_translation_lines(entry.get("original_lines"))
        if not original_lines:
            original_lines = list(source_lines)

        tl_lines = self._normalize_translation_lines(entry.get("translation_lines"))
        speaker_en_raw = entry.get("speaker_en")
        speaker_en = speaker_en_raw.strip() if isinstance(speaker_en_raw, str) else ""
        disable_line1_inference_raw = entry.get("line1_speaker_inference_disabled")
        disable_line1_inference = bool(
            disable_line1_inference_raw) if isinstance(disable_line1_inference_raw, bool) else False
        force_line1_inference_raw = entry.get("line1_speaker_inference_forced")
        force_line1_inference = bool(
            force_line1_inference_raw) if isinstance(force_line1_inference_raw, bool) else False
        if disable_line1_inference:
            force_line1_inference = False
        uid_raw = entry.get("segment_uid")
        segment_uid = (
            uid_raw.strip()
            if isinstance(uid_raw, str) and uid_raw.strip()
            else self._translation_only_segment_uid(session, tl_uid)
        )

        return DialogueSegment(
            uid=segment_uid,
            context=context,
            code101=code101,
            lines=list(source_lines),
            original_lines=list(original_lines),
            source_lines=list(source_lines),
            code401_template=code401_template,
            tl_uid=tl_uid,
            translation_lines=list(tl_lines),
            original_translation_lines=list(tl_lines),
            translation_speaker=speaker_en,
            original_translation_speaker=speaker_en,
            disable_line1_speaker_inference=disable_line1_inference,
            original_disable_line1_speaker_inference=disable_line1_inference,
            force_line1_speaker_inference=force_line1_inference,
            original_force_line1_speaker_inference=force_line1_inference,
            inserted=False,
            translation_only=True,
        )

    def _segment_reference_source_text(self, segment: DialogueSegment) -> str:
        source_lines = segment.source_lines or segment.original_lines or segment.lines or [
            ""]
        return "\n".join(source_lines)

    def _reference_anchor_index_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> int:
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
            return -1
        if not bool(getattr(segment, "translation_only", False)):
            return segment_index
        for idx in range(segment_index - 1, -1, -1):
            if not bool(getattr(segments[idx], "translation_only", False)):
                return idx
        for idx in range(segment_index + 1, len(segments)):
            if not bool(getattr(segments[idx], "translation_only", False)):
                return idx
        return segment_index

    def _reference_anchor_segment_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> DialogueSegment:
        anchor_index = self._reference_anchor_index_for_segment(session, segment)
        if 0 <= anchor_index < len(session.segments):
            return session.segments[anchor_index]
        return segment

    def _reference_source_text_for_matching(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> str:
        logical_source_resolver = getattr(
            self,
            "_logical_translation_source_lines_for_segment",
            None,
        )
        if callable(logical_source_resolver) and segment.is_structural_dialogue:
            resolved_lines: Any = None
            try:
                resolved_lines = logical_source_resolver(segment, session=session)
            except TypeError:
                try:
                    resolved_lines = logical_source_resolver(segment)
                except Exception:
                    resolved_lines = None
            except Exception:
                resolved_lines = None
            if isinstance(resolved_lines, list):
                normalized = self._normalize_translation_lines(resolved_lines)
                return "\n".join(normalized)
        anchor_segment = self._reference_anchor_segment_for_segment(session, segment)
        return self._segment_reference_source_text(anchor_segment)

    def _segment_reference_translation_text(self, segment: DialogueSegment) -> str:
        lines = self._normalize_translation_lines(segment.translation_lines)
        return "\n".join(lines).strip()

    def _speaker_key_for_state(self, segment: DialogueSegment) -> str:
        resolver = getattr(self, "_speaker_key_for_segment", None)
        if callable(resolver):
            try:
                resolved = resolver(segment)
                if isinstance(resolved, str):
                    cleaned = resolved.strip()
                    if cleaned:
                        return cleaned
            except Exception:
                pass
        return segment.speaker_name

    def _normalize_translation_profile_id(self, profile_id: Any) -> str:
        if isinstance(profile_id, str):
            cleaned = profile_id.strip()
            if cleaned:
                return cleaned
        return _DEFAULT_TRANSLATION_PROFILE_ID

    def _normalize_language_code(self, value: Any, default: str) -> str:
        if isinstance(value, str):
            cleaned = value.strip().replace("_", "-").lower()
            if cleaned and re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", cleaned):
                return cleaned
        return default

    def _default_translation_prompt_template(self) -> str:
        return (
            "Translate `{source_field}` from {source_language_code} into "
            "{target_language_code} for each entry, writing output to `{target_field}`.\n"
            "Keep JSON structure and IDs unchanged.\n"
            "Do not change `speaker`, `{source_field}`, `context_before`, `context_after`, or `context_windows`.\n"
            "Preserve all control codes and symbols exactly (`\\\\C[]` `\\\\V[]` `\\\\N[]` `\\\\I[]` `\\\\{` `♡`).\n"
            "Keep \\\\n line breaks from `{source_field}`.\n"
            "Use natural game dialogue in {target_language_code}; keep the same tone "
            "(taunts/flirting/insults) without sanitizing.\n"
            "`{target_field}` is only the JSON field name; it stores {target_language_code} text.\n"
            "Return JSON only.\n\n"
            "```json\n"
            "{payload_json}\n"
            "```"
        )

    def _default_translation_profile_name(self, profile_id: str) -> str:
        if profile_id == _DEFAULT_TRANSLATION_PROFILE_ID:
            return _DEFAULT_TRANSLATION_PROFILE_NAME
        return profile_id

    def _normalize_profile_speaker_map(self, raw_map: Any) -> dict[str, str]:
        normalized: dict[str, str] = {}
        if not isinstance(raw_map, dict):
            return normalized
        for key, value in raw_map.items():
            if not (
                isinstance(key, str)
                and key.strip()
                and key.strip() != NO_SPEAKER_KEY
                and isinstance(value, str)
            ):
                continue
            cleaned_value = value.strip()
            if cleaned_value:
                normalized[key.strip()] = cleaned_value
        return normalized

    def _normalize_profile_files_state(self, raw_files: Any) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        if not isinstance(raw_files, dict):
            return normalized
        for key, value in raw_files.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized[key] = value
        return normalized

    def _normalize_translation_profile_payload(
        self,
        profile_id: str,
        raw_profile: Any,
    ) -> dict[str, Any]:
        profile_dict = raw_profile if isinstance(raw_profile, dict) else {}
        raw_name = profile_dict.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else (
            self._default_translation_profile_name(profile_id)
        )
        raw_uid_counter = profile_dict.get("uid_counter", 0)
        uid_counter = raw_uid_counter if isinstance(raw_uid_counter, int) else 0
        if uid_counter < 0:
            uid_counter = 0
        raw_prompt_template = profile_dict.get("prompt_template")
        prompt_template = (
            raw_prompt_template.strip()
            if isinstance(raw_prompt_template, str)
            else ""
        )
        if not prompt_template:
            legacy_prompt_instructions = profile_dict.get("prompt_instructions")
            if isinstance(legacy_prompt_instructions, str) and legacy_prompt_instructions.strip():
                prompt_template = (
                    self._default_translation_prompt_template()
                    + "\n\n"
                    + legacy_prompt_instructions.strip()
                )
            else:
                prompt_template = self._default_translation_prompt_template()
        return {
            "name": name,
            "uid_counter": uid_counter,
            "target_language_code": self._normalize_language_code(
                profile_dict.get("target_language_code"),
                _DEFAULT_TARGET_LANGUAGE_CODE,
            ),
            "prompt_template": prompt_template,
            "speaker_map": self._normalize_profile_speaker_map(
                profile_dict.get("speaker_map")
            ),
            "files": self._normalize_profile_files_state(profile_dict.get("files")),
        }

    def _normalize_translation_state_v2(self, raw_state: Any) -> dict[str, Any]:
        raw_dict = raw_state if isinstance(raw_state, dict) else {}
        raw_version = raw_dict.get("version")
        profiles: dict[str, dict[str, Any]] = {}

        if raw_version == 2:
            raw_profiles = raw_dict.get("profiles")
            if isinstance(raw_profiles, dict):
                for raw_profile_id, raw_profile in raw_profiles.items():
                    if not isinstance(raw_profile_id, str):
                        continue
                    profile_id = self._normalize_translation_profile_id(raw_profile_id)
                    if profile_id in profiles:
                        continue
                    profiles[profile_id] = self._normalize_translation_profile_payload(
                        profile_id,
                        raw_profile,
                    )
        else:
            profile_id = _DEFAULT_TRANSLATION_PROFILE_ID
            profiles[profile_id] = self._normalize_translation_profile_payload(
                profile_id,
                {
                    "name": _DEFAULT_TRANSLATION_PROFILE_NAME,
                    "uid_counter": raw_dict.get("uid_counter", 0),
                    "speaker_map": raw_dict.get("speaker_map"),
                    "files": raw_dict.get("files"),
                },
            )

        if _DEFAULT_TRANSLATION_PROFILE_ID not in profiles:
            profiles[_DEFAULT_TRANSLATION_PROFILE_ID] = (
                self._normalize_translation_profile_payload(
                    _DEFAULT_TRANSLATION_PROFILE_ID,
                    {"name": _DEFAULT_TRANSLATION_PROFILE_NAME},
                )
            )

        raw_active_profile_id = raw_dict.get("active_profile_id")
        active_profile_id = self._normalize_translation_profile_id(raw_active_profile_id)
        has_raw_active = (
            isinstance(raw_active_profile_id, str)
            and raw_active_profile_id.strip()
            and active_profile_id in profiles
        )
        if not has_raw_active:
            current_active = getattr(self, "active_translation_profile_id", "")
            if (
                current_active
                and isinstance(current_active, str)
                and current_active.strip()
                and current_active.strip() in profiles
            ):
                active_profile_id = current_active.strip()
        if active_profile_id not in profiles:
            sorted_profile_ids = sorted(profiles.keys(), key=natural_sort_key)
            active_profile_id = (
                sorted_profile_ids[0]
                if sorted_profile_ids
                else _DEFAULT_TRANSLATION_PROFILE_ID
            )
        source_language_code = self._normalize_language_code(
            raw_dict.get("source_language_code"),
            _DEFAULT_SOURCE_LANGUAGE_CODE,
        )

        return {
            "version": 2,
            "active_profile_id": active_profile_id,
            "source_language_code": source_language_code,
            "profiles": profiles,
        }

    def _refresh_translation_profiles_meta(self) -> None:
        profiles_raw = self.translation_state.get("profiles")
        profiles = profiles_raw if isinstance(profiles_raw, dict) else {}
        meta: dict[str, dict[str, Any]] = {}
        for raw_profile_id, raw_profile_state in profiles.items():
            if not isinstance(raw_profile_id, str):
                continue
            profile_id = self._normalize_translation_profile_id(raw_profile_id)
            state = raw_profile_state if isinstance(raw_profile_state, dict) else {}
            raw_name = state.get("name")
            name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else (
                self._default_translation_profile_name(profile_id)
            )
            target_language_code = self._normalize_language_code(
                state.get("target_language_code"),
                _DEFAULT_TARGET_LANGUAGE_CODE,
            )
            prompt_template_raw = state.get("prompt_template")
            prompt_template = (
                prompt_template_raw.strip()
                if isinstance(prompt_template_raw, str)
                else self._default_translation_prompt_template()
            )
            if not prompt_template:
                prompt_template = self._default_translation_prompt_template()
            meta[profile_id] = {
                "name": name,
                "target_language_code": target_language_code,
                "prompt_template": prompt_template,
            }
        if not meta:
            meta[_DEFAULT_TRANSLATION_PROFILE_ID] = {
                "name": _DEFAULT_TRANSLATION_PROFILE_NAME,
                "target_language_code": _DEFAULT_TARGET_LANGUAGE_CODE,
                "prompt_template": self._default_translation_prompt_template(),
            }
        self.translation_profiles_meta = meta

    def _translation_project_source_language_code(self) -> str:
        self.translation_state = self._normalize_translation_state_v2(self.translation_state)
        raw_source_language_code = self.translation_state.get("source_language_code")
        normalized_source_language_code = self._normalize_language_code(
            raw_source_language_code,
            _DEFAULT_SOURCE_LANGUAGE_CODE,
        )
        self.translation_state["source_language_code"] = normalized_source_language_code
        return normalized_source_language_code

    def _set_translation_project_source_language_code(self, source_language_code: str) -> None:
        self.translation_state = self._normalize_translation_state_v2(self.translation_state)
        self.translation_state["source_language_code"] = self._normalize_language_code(
            source_language_code,
            _DEFAULT_SOURCE_LANGUAGE_CODE,
        )

    def _translation_profile_target_language_code(
        self,
        profile_id: Optional[str] = None,
    ) -> str:
        normalized_profile_id = self._normalize_translation_profile_id(
            profile_id if isinstance(profile_id, str) else self.active_translation_profile_id
        )
        profile_state = self._ensure_translation_profile(normalized_profile_id)
        target_language_code = self._normalize_language_code(
            profile_state.get("target_language_code"),
            _DEFAULT_TARGET_LANGUAGE_CODE,
        )
        profile_state["target_language_code"] = target_language_code
        self._refresh_translation_profiles_meta()
        return target_language_code

    def _language_code_display_label(self, language_code: str, default: str) -> str:
        normalized = self._normalize_language_code(language_code, default)
        return normalized.upper()

    def _translation_project_source_language_label(self) -> str:
        return self._language_code_display_label(
            self._translation_project_source_language_code(),
            _DEFAULT_SOURCE_LANGUAGE_CODE,
        )

    def _translation_profile_target_language_label(
        self,
        profile_id: Optional[str] = None,
    ) -> str:
        return self._language_code_display_label(
            self._translation_profile_target_language_code(profile_id),
            _DEFAULT_TARGET_LANGUAGE_CODE,
        )

    def _empty_exact_reference_summary(self) -> str:
        source_label = self._translation_project_source_language_label()
        return f"Exact {source_label} matches: none."

    def _empty_similar_reference_summary(self) -> str:
        source_label = self._translation_project_source_language_label()
        return f"Similar {source_label} phrases: none."

    def _translation_profile_prompt_template(
        self,
        profile_id: Optional[str] = None,
    ) -> str:
        normalized_profile_id = self._normalize_translation_profile_id(
            profile_id if isinstance(profile_id, str) else self.active_translation_profile_id
        )
        profile_state = self._ensure_translation_profile(normalized_profile_id)
        raw_prompt_template = profile_state.get("prompt_template")
        prompt_template = (
            raw_prompt_template.strip()
            if isinstance(raw_prompt_template, str)
            else self._default_translation_prompt_template()
        )
        if not prompt_template:
            prompt_template = self._default_translation_prompt_template()
        profile_state["prompt_template"] = prompt_template
        self._refresh_translation_profiles_meta()
        return prompt_template

    def _set_translation_profile_prompt_settings(
        self,
        *,
        target_language_code: str,
        prompt_template: str,
        profile_id: Optional[str] = None,
    ) -> None:
        normalized_profile_id = self._normalize_translation_profile_id(
            profile_id if isinstance(profile_id, str) else self.active_translation_profile_id
        )
        profile_state = self._ensure_translation_profile(normalized_profile_id)
        profile_state["target_language_code"] = self._normalize_language_code(
            target_language_code,
            _DEFAULT_TARGET_LANGUAGE_CODE,
        )
        normalized_prompt_template = (
            prompt_template.strip()
            if isinstance(prompt_template, str)
            else ""
        )
        if not normalized_prompt_template:
            normalized_prompt_template = self._default_translation_prompt_template()
        profile_state["prompt_template"] = normalized_prompt_template
        self._refresh_translation_profiles_meta()

    def _translation_profile_prompt_instructions(
        self,
        profile_id: Optional[str] = None,
    ) -> str:
        return self._translation_profile_prompt_template(profile_id)

    def _ensure_translation_profile(self, profile_id: str) -> dict[str, Any]:
        normalized_state = self._normalize_translation_state_v2(self.translation_state)
        self.translation_state = normalized_state
        profiles_raw = normalized_state.get("profiles")
        profiles = profiles_raw if isinstance(profiles_raw, dict) else {}
        normalized_profile_id = self._normalize_translation_profile_id(profile_id)
        profile_state_raw = profiles.get(normalized_profile_id)
        if not isinstance(profile_state_raw, dict):
            profile_state_raw = self._normalize_translation_profile_payload(
                normalized_profile_id,
                {"name": self._default_translation_profile_name(normalized_profile_id)},
            )
            profiles[normalized_profile_id] = profile_state_raw
        else:
            profile_state_raw = self._normalize_translation_profile_payload(
                normalized_profile_id,
                profile_state_raw,
            )
            profiles[normalized_profile_id] = profile_state_raw
        self.translation_state["profiles"] = profiles
        self._refresh_translation_profiles_meta()
        return profile_state_raw

    def _active_profile_state(self) -> dict[str, Any]:
        active_profile_raw = getattr(self, "active_translation_profile_id", "")
        if not (isinstance(active_profile_raw, str) and active_profile_raw.strip()):
            active_profile_raw = self.translation_state.get("active_profile_id", "")
        active_profile_id = self._normalize_translation_profile_id(active_profile_raw)
        profile_state = self._ensure_translation_profile(active_profile_id)
        self.active_translation_profile_id = active_profile_id
        self.translation_state["active_profile_id"] = active_profile_id
        return profile_state

    def _active_profile_files_state(self) -> dict[str, Any]:
        profile_state = self._active_profile_state()
        files_raw = profile_state.get("files")
        if not isinstance(files_raw, dict):
            files_raw = {}
            profile_state["files"] = files_raw
        return files_raw

    def _load_translation_state(self) -> None:
        self.translation_state = self._normalize_translation_state_v2({})
        self.active_translation_profile_id = self.translation_state["active_profile_id"]
        self._refresh_translation_profiles_meta()
        self.speaker_translation_map = {}
        self.translation_uid_counter = 0
        if self.translation_state_path is None:
            return
        if not self.translation_state_path.exists():
            return

        try:
            with self.translation_state_path.open("r", encoding="utf-8") as src:
                loaded = json.load(src)
            self.translation_state = self._normalize_translation_state_v2(loaded)
            self.active_translation_profile_id = self.translation_state["active_profile_id"]
            self._refresh_translation_profiles_meta()
        except Exception as exc:
            logger.exception(
                "Failed to load translation state from '%s'.",
                self.translation_state_path,
            )
            QMessageBox.warning(
                cast(QWidget, self),
                "Translation state warning",
                f"Failed to load translation state:\n{self.translation_state_path}\n\n{exc}",
            )
            return

        profile_state = self._active_profile_state()
        speaker_map_raw = profile_state.get("speaker_map")
        if isinstance(speaker_map_raw, dict):
            self.speaker_translation_map.update(speaker_map_raw)

        counter_raw = profile_state.get("uid_counter", 0)
        if isinstance(counter_raw, int):
            self.translation_uid_counter = max(0, counter_raw)

        files_raw = profile_state.get("files")
        if isinstance(files_raw, dict):
            for file_state in files_raw.values():
                if not isinstance(file_state, dict):
                    continue
                entries = file_state.get("entries")
                if not isinstance(entries, dict):
                    continue
                for uid in entries.keys():
                    if not isinstance(uid, str):
                        continue
                    match = re.fullmatch(r"T(\d+)", uid)
                    if not match:
                        continue
                    try:
                        parsed = int(match.group(1))
                    except Exception:
                        continue
                    self.translation_uid_counter = max(
                        self.translation_uid_counter, parsed)

    def _apply_translation_state_to_session(self, session: FileSession) -> None:
        rel_path = self._relative_path(session.path)
        is_name_index_session = bool(getattr(session, "is_name_index_session", False))
        files_raw = self._active_profile_files_state()
        file_state: dict[str, Any] = {}
        if isinstance(files_raw, dict):
            candidate = files_raw.get(rel_path)
            if isinstance(candidate, dict):
                file_state = candidate

        order_raw = file_state.get("order")
        order: list[str] = [item for item in order_raw if isinstance(
            item, str)] if isinstance(order_raw, list) else []
        entries_raw = file_state.get("entries")
        entries: dict[str, dict[str, Any]] = {}
        if isinstance(entries_raw, dict):
            for key, value in entries_raw.items():
                if isinstance(key, str) and isinstance(value, dict):
                    entries[key] = value

        unused = set(entries.keys())
        hash_buckets: dict[str, list[str]] = {}
        source_uid_buckets: dict[str, list[str]] = {}
        for uid, entry in entries.items():
            source_hash = entry.get("source_hash")
            if isinstance(source_hash, str) and source_hash:
                hash_buckets.setdefault(source_hash, []).append(uid)
            source_uid = entry.get("source_uid")
            if isinstance(source_uid, str) and source_uid:
                source_uid_buckets.setdefault(source_uid, []).append(uid)

        for idx, segment in enumerate(session.segments):
            segment.source_lines = list(
                segment.lines) if segment.lines else [""]
            source_hash_candidates = self._segment_source_hash_candidates(segment)
            chosen_uid = ""
            preferred_uid = order[idx] if idx < len(order) else ""
            preferred_hash = ""

            # Name-index sessions have stable parser UIDs (e.g. States.json:S:12:message1).
            # Prefer direct UID mapping before hash/order matching.
            if is_name_index_session:
                for candidate_uid in source_uid_buckets.get(segment.uid, []):
                    if candidate_uid in unused:
                        chosen_uid = candidate_uid
                        unused.remove(candidate_uid)
                        break

            if preferred_uid and preferred_uid in unused:
                preferred_entry_raw = entries.get(preferred_uid)
                preferred_entry = preferred_entry_raw if isinstance(
                    preferred_entry_raw, dict) else {}
                preferred_hash_raw = preferred_entry.get("source_hash")
                preferred_hash = preferred_hash_raw.strip() if isinstance(
                    preferred_hash_raw, str) else ""
                if preferred_hash and preferred_hash in source_hash_candidates:
                    chosen_uid = preferred_uid
                    unused.remove(preferred_uid)

            if not chosen_uid:
                for candidate_uid in source_uid_buckets.get(segment.uid, []):
                    if candidate_uid in unused:
                        chosen_uid = candidate_uid
                        unused.remove(candidate_uid)
                        break

            if not chosen_uid:
                seen_candidate_uids: set[str] = set()
                for source_hash in source_hash_candidates:
                    for candidate_uid in hash_buckets.get(source_hash, []):
                        if candidate_uid in seen_candidate_uids:
                            continue
                        seen_candidate_uids.add(candidate_uid)
                        if candidate_uid in unused:
                            chosen_uid = candidate_uid
                            unused.remove(candidate_uid)
                            break
                    if chosen_uid:
                        break

            # Keep positional fallback only for legacy state rows that don't have
            # source hashes; otherwise parser changes (e.g. added choice segments)
            # can shift IDs and misalign all following translations.
            force_positional_match = (
                bool(getattr(self, "_translation_state_force_positional_match", False))
                and (not is_name_index_session)
            )
            if (
                not chosen_uid
                and (not is_name_index_session)
                and preferred_uid
                and preferred_uid in unused
                and (not preferred_hash or force_positional_match)
            ):
                chosen_uid = preferred_uid
                unused.remove(preferred_uid)

            if not chosen_uid:
                chosen_uid = self._new_translation_uid()

            entry = entries.get(chosen_uid, {})
            tl_lines = self._normalize_translation_lines(
                entry.get("translation_lines"))
            speaker_en_raw = entry.get("speaker_en")
            speaker_en = speaker_en_raw.strip() if isinstance(speaker_en_raw, str) else ""
            disable_line1_inference_raw = entry.get(
                "line1_speaker_inference_disabled")
            disable_line1_inference = bool(
                disable_line1_inference_raw) if isinstance(disable_line1_inference_raw, bool) else False
            force_line1_inference_raw = entry.get(
                "line1_speaker_inference_forced")
            force_line1_inference = bool(
                force_line1_inference_raw) if isinstance(force_line1_inference_raw, bool) else False
            if disable_line1_inference:
                force_line1_inference = False
            if is_name_index_session:
                speaker_key = NO_SPEAKER_KEY
                speaker_en = ""
            else:
                speaker_key = self._speaker_key_for_state(segment)
                speaker_field_present = "speaker_en" in entry
                if not speaker_en and (not speaker_field_present):
                    speaker_lookup = getattr(self, "_speaker_translation_for_key", None)
                    if callable(speaker_lookup):
                        try:
                            resolved_speaker = speaker_lookup(speaker_key)
                        except Exception:
                            resolved_speaker = ""
                        if isinstance(resolved_speaker, str):
                            speaker_en = resolved_speaker.strip()
                    if not speaker_en:
                        map_value = self.speaker_translation_map.get(speaker_key, "")
                        if isinstance(map_value, str):
                            speaker_en = map_value.strip()
                if speaker_key == NO_SPEAKER_KEY:
                    speaker_en = ""

            segment.tl_uid = chosen_uid
            segment.translation_lines = list(tl_lines)
            segment.original_translation_lines = list(tl_lines)
            segment.translation_speaker = speaker_en
            segment.original_translation_speaker = speaker_en
            segment.disable_line1_speaker_inference = disable_line1_inference
            segment.original_disable_line1_speaker_inference = disable_line1_inference
            segment.force_line1_speaker_inference = force_line1_inference
            segment.original_force_line1_speaker_inference = force_line1_inference

            if speaker_en and speaker_key != NO_SPEAKER_KEY:
                self.speaker_translation_map[speaker_key] = speaker_en

        # Keep parser order for name-index sessions (e.g. System/MapInfos/etc.).
        # Reordering by saved TL order is only needed for dialogue sessions that
        # can contain translation-only inserted blocks.
        if is_name_index_session:
            self._ensure_unique_session_segment_uids(session)
            setattr(
                session,
                "_original_tl_order",
                [segment.tl_uid for segment in session.segments],
            )
            return

        source_segments_in_order: list[DialogueSegment] = []
        source_segments_by_tl_uid: dict[str, DialogueSegment] = {}
        map_display_segments: list[DialogueSegment] = []
        for segment in session.segments:
            if segment.translation_only:
                continue
            if segment.segment_kind == "map_display_name":
                map_display_segments.append(segment)
                continue
            source_segments_in_order.append(segment)
            if segment.tl_uid:
                source_segments_by_tl_uid[segment.tl_uid] = segment

        ordered_segments: list[DialogueSegment] = []
        tl_only_segments_by_uid: dict[str, DialogueSegment] = {}
        source_tl_uids = set(source_segments_by_tl_uid.keys())
        tl_only_before_source_uid: dict[str, list[DialogueSegment]] = {}
        tl_only_after_source_uid: dict[str, list[DialogueSegment]] = {}
        tl_only_suffix_segments: list[DialogueSegment] = []

        def template_for_translation_only() -> Optional[DialogueSegment]:
            for candidate in reversed(ordered_segments):
                if not candidate.translation_only and candidate.segment_kind != "map_display_name":
                    return candidate
            for candidate in session.segments:
                if not candidate.translation_only and candidate.segment_kind != "map_display_name":
                    return candidate
            return session.segments[0] if session.segments else None

        for tl_uid in order:
            entry = entries.get(tl_uid)
            if not isinstance(entry, dict):
                continue
            if not bool(entry.get("translation_only")):
                continue
            if tl_uid in tl_only_segments_by_uid:
                continue
            tl_only_segments_by_uid[tl_uid] = self._build_translation_only_segment_from_state(
                session,
                tl_uid,
                entry,
                template_for_translation_only(),
            )

        for order_index, tl_uid in enumerate(order):
            tl_only_segment = tl_only_segments_by_uid.get(tl_uid)
            if tl_only_segment is None:
                continue

            anchor_before = ""
            for scan_uid in reversed(order[:order_index]):
                if scan_uid in source_tl_uids:
                    anchor_before = scan_uid
                    break

            if anchor_before:
                tl_only_after_source_uid.setdefault(anchor_before, []).append(
                    tl_only_segment
                )
                continue

            anchor_after = ""
            for scan_uid in order[order_index + 1:]:
                if scan_uid in source_tl_uids:
                    anchor_after = scan_uid
                    break

            if anchor_after:
                tl_only_before_source_uid.setdefault(anchor_after, []).append(
                    tl_only_segment
                )
                continue

            tl_only_suffix_segments.append(tl_only_segment)

        for source_segment in source_segments_in_order:
            if source_segment.tl_uid:
                for tl_only_segment in tl_only_before_source_uid.get(
                    source_segment.tl_uid, []
                ):
                    ordered_segments.append(tl_only_segment)
            ordered_segments.append(source_segment)
            if source_segment.tl_uid:
                for tl_only_segment in tl_only_after_source_uid.get(
                    source_segment.tl_uid, []
                ):
                    ordered_segments.append(tl_only_segment)

        ordered_segments.extend(tl_only_suffix_segments)

        session.segments = map_display_segments + ordered_segments
        self._ensure_unique_session_segment_uids(session)
        setattr(session, "_original_tl_order", [segment.tl_uid for segment in session.segments])

    def _sync_translation_state_from_sessions(self) -> None:
        files_state: dict[str, Any] = {}
        for path, session in self.sessions.items():
            files_state[self._relative_path(
                path)] = self._translation_state_for_session(session)

        sorted_speaker_map: dict[str, str] = {}
        for key in sorted(self.speaker_translation_map.keys(), key=natural_sort_key):
            if key == NO_SPEAKER_KEY:
                continue
            value = self.speaker_translation_map.get(key, "").strip()
            if value:
                sorted_speaker_map[key] = value

        profile_state = self._active_profile_state()
        profile_state["uid_counter"] = self.translation_uid_counter
        profile_state["speaker_map"] = sorted_speaker_map
        profile_state["files"] = files_state
        self.translation_state["version"] = 2
        self.translation_state["active_profile_id"] = self.active_translation_profile_id
        self._refresh_translation_profiles_meta()

    def _translation_state_for_session(self, session: FileSession) -> dict[str, Any]:
        is_name_index_session = bool(getattr(session, "is_name_index_session", False))
        order: list[str] = []
        entries: dict[str, Any] = {}
        for segment in session.segments:
            if not segment.tl_uid:
                segment.tl_uid = self._new_translation_uid()
            order.append(segment.tl_uid)
            translation_lines = self._normalize_translation_lines(
                segment.translation_lines)
            speaker_en = segment.translation_speaker.strip()
            speaker_key = self._speaker_key_for_state(segment)
            if is_name_index_session:
                speaker_en = ""
                speaker_key = NO_SPEAKER_KEY
            elif speaker_key == NO_SPEAKER_KEY:
                speaker_en = ""
            source_lines = list(
                segment.source_lines or segment.original_lines or segment.lines or [""]
            )
            entry: dict[str, Any] = {
                "source_hash": "" if segment.translation_only else self._segment_source_hash(segment),
                "source_uid": segment.uid,
                "source_preview": preview_text(self._segment_reference_source_text(segment), 130),
                "speaker_jp": speaker_key,
                "speaker_en": speaker_en,
                "translation_lines": translation_lines,
                "translation_only": bool(segment.translation_only),
                "line1_speaker_inference_disabled": bool(
                    segment.disable_line1_speaker_inference),
                "line1_speaker_inference_forced": bool(
                    segment.force_line1_speaker_inference),
            }
            if segment.translation_only:
                entry["segment_uid"] = segment.uid
                entry["context"] = segment.context
                entry["code101"] = copy.deepcopy(segment.code101)
                entry["code401_template"] = copy.deepcopy(segment.code401_template)
                entry["source_lines"] = source_lines
                entry["original_lines"] = list(segment.original_lines or source_lines)
            entries[segment.tl_uid] = entry
            if speaker_en and speaker_key != NO_SPEAKER_KEY:
                self.speaker_translation_map[speaker_key] = speaker_en
        return {"order": order, "entries": entries}

    def _save_translation_state(self, changed_paths: Optional[list[Path]] = None) -> bool:
        if self.translation_state_path is None:
            return True
        try:
            self._active_profile_state()
            if changed_paths is None:
                self._sync_translation_state_from_sessions()
            else:
                profile_state = self._active_profile_state()
                files_raw = profile_state.get("files")
                if not isinstance(files_raw, dict):
                    files_raw = {}
                    profile_state["files"] = files_raw
                for path in changed_paths:
                    session = self.sessions.get(path)
                    if session is None:
                        continue
                    files_raw[self._relative_path(
                        path)] = self._translation_state_for_session(session)

                sorted_speaker_map: dict[str, str] = {}
                for key in sorted(self.speaker_translation_map.keys(), key=natural_sort_key):
                    if key == NO_SPEAKER_KEY:
                        continue
                    value = self.speaker_translation_map.get(key, "").strip()
                    if value:
                        sorted_speaker_map[key] = value
                profile_state["speaker_map"] = sorted_speaker_map
                profile_state["uid_counter"] = self.translation_uid_counter
                self.translation_state["version"] = 2
                self.translation_state["active_profile_id"] = self.active_translation_profile_id
                self._refresh_translation_profiles_meta()

            with self.translation_state_path.open("w", encoding="utf-8") as dst:
                json.dump(self.translation_state, dst,
                          ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            logger.exception(
                "Failed to save translation state to '%s'.",
                self.translation_state_path,
            )
            QMessageBox.critical(
                cast(QWidget, self),
                "Save failed",
                f"Failed to save translation state:\n{self.translation_state_path}\n\n{exc}",
            )
            return False

    def _session_has_source_changes(self, session: FileSession) -> bool:
        if bool(getattr(session, "_has_external_source_edits", False)):
            return True
        for segment in session.segments:
            if segment.translation_only:
                continue
            if segment.inserted:
                return True
            if segment.merged_segments:
                return True
            if segment.lines != segment.original_lines:
                return True
        return False

    def _session_has_translation_changes(self, session: FileSession) -> bool:
        original_order_raw = getattr(session, "_original_tl_order", None)
        if isinstance(original_order_raw, list):
            original_order = [item for item in original_order_raw if isinstance(item, str)]
            current_order = [segment.tl_uid for segment in session.segments if isinstance(segment.tl_uid, str)]
            if current_order != original_order:
                return True
        for segment in session.segments:
            if self._normalize_translation_lines(segment.translation_lines) != self._normalize_translation_lines(
                segment.original_translation_lines
            ):
                return True
            if segment.translation_speaker.strip() != segment.original_translation_speaker.strip():
                return True
            if (
                bool(segment.disable_line1_speaker_inference)
                != bool(segment.original_disable_line1_speaker_inference)
            ):
                return True
            if (
                bool(segment.force_line1_speaker_inference)
                != bool(segment.original_force_line1_speaker_inference)
            ):
                return True
        return False

    def _mark_session_translation_saved(self, session: FileSession) -> None:
        for segment in session.segments:
            segment.translation_lines = self._normalize_translation_lines(
                segment.translation_lines)
            segment.original_translation_lines = list(
                segment.translation_lines)
            segment.translation_speaker = segment.translation_speaker.strip()
            segment.original_translation_speaker = segment.translation_speaker
            segment.original_disable_line1_speaker_inference = bool(
                segment.disable_line1_speaker_inference)
            segment.original_force_line1_speaker_inference = bool(
                segment.force_line1_speaker_inference)
            if segment.translation_only:
                segment.inserted = False
        setattr(session, "_original_tl_order", [segment.tl_uid for segment in session.segments])

    def _exact_reference_candidates(
        self,
        own_source: str,
        own_path: Path,
        own_uid: str,
        exact_groups: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], bool]:
        exact_candidates = [
            row for row in exact_groups.get(own_source, [])
            if not (row["path"] == own_path and row["uid"] == own_uid)
        ]
        exact_cross_file = [
            row for row in exact_candidates if row["path"] != own_path]
        if exact_cross_file:
            return exact_cross_file, True
        return exact_candidates, False

    def _build_exact_reference_summary(
        self,
        own_source: str,
        own_path: Path,
        own_uid: str,
        exact_groups: dict[str, list[dict[str, Any]]],
    ) -> str:
        exact_pool, is_cross_file = self._exact_reference_candidates(
            own_source=own_source,
            own_path=own_path,
            own_uid=own_uid,
            exact_groups=exact_groups,
        )
        source_label = self._translation_project_source_language_label()
        target_label = self._translation_profile_target_language_label()
        if not exact_pool:
            return self._empty_exact_reference_summary()

        translated_rows: list[dict[str, Any]] = []
        variant_counts: dict[str, int] = {}
        variant_first_seen: dict[str, int] = {}
        variant_example_ref: dict[str, str] = {}

        for index, row in enumerate(exact_pool):
            translation = cast(str, row["translation_text"]).strip()
            if not translation:
                continue
            translated_rows.append(row)
            if translation not in variant_counts:
                variant_counts[translation] = 0
                variant_first_seen[translation] = index
                variant_example_ref[translation] = f"{row['file']}#{row['block_number']}"
            variant_counts[translation] += 1

        scope = "other files" if is_cross_file else "this file/folder"
        block_label = "block" if len(exact_pool) == 1 else "blocks"
        summary = f"Exact {source_label} matches in {scope}: {len(exact_pool)} {block_label}."

        if not translated_rows:
            return summary + f" No {target_label} translations in matches yet."

        ranked_variants = sorted(
            variant_counts.keys(),
            key=lambda text: (
                -variant_counts[text],
                variant_first_seen.get(text, 0),
            ),
        )

        variant_label = "variant" if len(ranked_variants) == 1 else "variants"
        summary += (
            f" Filled {target_label}: {len(translated_rows)}/{len(exact_pool)}."
            f" {len(ranked_variants)} {variant_label}."
        )

        top_variants: list[str] = []
        for translation in ranked_variants[:3]:
            count = variant_counts[translation]
            sample_ref = variant_example_ref.get(translation, "")
            top_variants.append(
                f"x{count} {preview_text(translation, 64)} ({sample_ref})"
            )
        if top_variants:
            summary += f" Top {target_label}: " + " | ".join(top_variants)

        empty_count = len(exact_pool) - len(translated_rows)
        if empty_count > 0:
            empty_label = "entry" if empty_count == 1 else "entries"
            summary += f" Empty {target_label}: {empty_count} {empty_label}."
        return summary

    def _other_profile_translation_rows_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> list[tuple[str, str, str]]:
        own_source = self._segment_reference_source_text(segment).strip()
        if not own_source:
            return []

        current_translation = self._segment_reference_translation_text(segment).strip()
        rows: list[tuple[str, str, str]] = []

        profiles_raw = self.translation_state.get("profiles")
        profiles = profiles_raw if isinstance(profiles_raw, dict) else {}
        rel_path = self._relative_path(session.path)
        source_hash_candidates = self._segment_source_hash_candidates(segment)
        active_profile_id = self._normalize_translation_profile_id(
            getattr(self, "active_translation_profile_id", "")
        )

        for raw_profile_id, raw_profile_state in profiles.items():
            if not isinstance(raw_profile_id, str) or not raw_profile_id.strip():
                continue
            profile_id = self._normalize_translation_profile_id(raw_profile_id)
            if profile_id == active_profile_id:
                continue
            if not isinstance(raw_profile_state, dict):
                continue
            files_raw = raw_profile_state.get("files")
            files = files_raw if isinstance(files_raw, dict) else {}
            file_state_raw = files.get(rel_path)
            if not isinstance(file_state_raw, dict):
                continue
            entries_raw = file_state_raw.get("entries")
            entries = entries_raw if isinstance(entries_raw, dict) else {}
            chosen_translation = ""
            for entry_raw in entries.values():
                if not isinstance(entry_raw, dict):
                    continue
                source_uid_raw = entry_raw.get("source_uid")
                source_uid = source_uid_raw.strip() if isinstance(source_uid_raw, str) else ""
                if source_uid != segment.uid:
                    continue
                translation_lines_raw = entry_raw.get("translation_lines")
                translation_lines = self._normalize_translation_lines(translation_lines_raw)
                candidate_text = "\n".join(translation_lines).strip()
                if candidate_text:
                    chosen_translation = candidate_text
                    break
            if not chosen_translation:
                for entry_raw in entries.values():
                    if not isinstance(entry_raw, dict):
                        continue
                    source_hash_raw = entry_raw.get("source_hash")
                    source_hash = source_hash_raw.strip() if isinstance(source_hash_raw, str) else ""
                    if not source_hash or source_hash not in source_hash_candidates:
                        continue
                    translation_lines_raw = entry_raw.get("translation_lines")
                    translation_lines = self._normalize_translation_lines(translation_lines_raw)
                    candidate_text = "\n".join(translation_lines).strip()
                    if candidate_text:
                        chosen_translation = candidate_text
                        break
            if not chosen_translation:
                continue
            if current_translation and chosen_translation == current_translation:
                continue
            profile_name = ""
            meta_raw = self.translation_profiles_meta.get(profile_id)
            if isinstance(meta_raw, dict):
                meta_name = meta_raw.get("name")
                if isinstance(meta_name, str):
                    profile_name = meta_name.strip()
            if not profile_name:
                profile_name_raw = raw_profile_state.get("name")
                if isinstance(profile_name_raw, str):
                    profile_name = profile_name_raw.strip()
            if not profile_name:
                profile_name = self._default_translation_profile_name(profile_id)
            rows.append((profile_id, profile_name, chosen_translation))

        rows.sort(key=lambda item: natural_sort_key(item[1]))
        return rows

    def _build_reference_summary_for_session(self, session: FileSession) -> dict[str, tuple[str, str]]:
        rows: list[dict[str, Any]] = []
        source_label = self._translation_project_source_language_label()
        target_label = self._translation_profile_target_language_label()
        for row_path, row_session in self.sessions.items():
            emitted_anchor_uids: set[str] = set()
            for block_number, segment in enumerate(row_session.segments, start=1):
                anchor_segment = self._reference_anchor_segment_for_segment(
                    row_session,
                    segment,
                )
                anchor_uid = anchor_segment.uid if isinstance(anchor_segment.uid, str) else ""
                if anchor_uid and anchor_uid in emitted_anchor_uids:
                    continue
                if anchor_uid:
                    emitted_anchor_uids.add(anchor_uid)
                source_text = self._reference_source_text_for_matching(
                    row_session,
                    segment,
                ).strip()
                if not source_text:
                    continue
                rows.append(
                    {
                        "path": row_path,
                        "uid": anchor_uid if anchor_uid else segment.uid,
                        "file": row_path.name,
                        "block_number": self._reference_anchor_index_for_segment(
                            row_session,
                            segment,
                        ) + 1,
                        "source_text": source_text,
                        "translation_text": self._segment_reference_translation_text(
                            anchor_segment
                        ),
                        "compare_text": fuzzy_compare_text(source_text),
                    }
                )

        exact_groups: dict[str, list[dict[str, Any]]] = {}
        similar_groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            source_text = cast(str, row["source_text"])
            exact_groups.setdefault(source_text, []).append(row)
            signature = similarity_signature(source_text)
            if len(signature) >= 3:
                similar_groups.setdefault(signature, []).append(row)

        summaries: dict[str, tuple[str, str]] = {}
        for segment in session.segments:
            own_source = self._reference_source_text_for_matching(session, segment).strip()
            own_path = session.path
            own_anchor = self._reference_anchor_segment_for_segment(session, segment)
            own_uid = own_anchor.uid

            exact_summary = self._build_exact_reference_summary(
                own_source=own_source,
                own_path=own_path,
                own_uid=own_uid,
                exact_groups=exact_groups,
            )

            similar_signature = similarity_signature(own_source)
            similar_rows = [
                row
                for row in similar_groups.get(similar_signature, [])
                if not (row["path"] == own_path and row["uid"] == own_uid)
                and row["source_text"] != own_source
            ] if len(similar_signature) >= 3 else []

            if similar_rows:
                own_compare = fuzzy_compare_text(own_source)
                scored: list[tuple[float, dict[str, Any]]] = []
                for row in similar_rows:
                    compare_text = cast(str, row["compare_text"])
                    ratio = SequenceMatcher(
                        None, own_compare, compare_text).ratio()
                    if ratio < 0.55:
                        continue
                    scored.append((ratio, row))
                scored.sort(key=lambda item: item[0], reverse=True)
                if scored:
                    sample_parts = []
                    for ratio, row in scored[:3]:
                        sample_tl = cast(
                            str, row["translation_text"]) or f"(no {target_label} yet)"
                        sample_parts.append(
                            f"{row['file']}#{row['block_number']} ({ratio:.2f}): {preview_text(sample_tl, 44)}"
                        )
                    candidate_label = "candidate" if len(scored) == 1 else "candidates"
                    similar_summary = f"Similar {source_label} phrases: {len(scored)} {candidate_label}. " + " | ".join(
                        sample_parts)
                else:
                    similar_summary = self._empty_similar_reference_summary()
            else:
                similar_summary = self._empty_similar_reference_summary()

            summaries[segment.uid] = (exact_summary, similar_summary)
        return summaries

    def _prompt_source_lines_for_segment(self, segment: DialogueSegment) -> list[str]:
        source_lines_resolver = getattr(self, "_segment_source_lines_for_translation", None)
        if callable(source_lines_resolver):
            try:
                resolved = source_lines_resolver(segment)
            except Exception:
                resolved = None
            if isinstance(resolved, list):
                normalized = self._normalize_translation_lines(resolved)
                if normalized:
                    return normalized

        display_lines_resolver = getattr(self, "_segment_source_lines_for_display", None)
        if callable(display_lines_resolver):
            try:
                resolved_display = display_lines_resolver(segment)
            except Exception:
                resolved_display = None
            if isinstance(resolved_display, list):
                normalized = self._normalize_translation_lines(resolved_display)
                if normalized:
                    return normalized

        fallback_lines = segment.source_lines or segment.original_lines or segment.lines or [""]
        return self._normalize_translation_lines(fallback_lines)

    def _prompt_speaker_values_for_segment(self, segment: DialogueSegment) -> tuple[str, str]:
        speaker_resolver = getattr(self, "_translator_panel_speaker_values", None)
        if callable(speaker_resolver):
            try:
                resolved = speaker_resolver(segment)
            except Exception:
                resolved = None
            if (
                isinstance(resolved, tuple)
                and len(resolved) == 2
                and isinstance(resolved[0], str)
                and isinstance(resolved[1], str)
            ):
                return resolved[0].strip(), resolved[1].strip()

        speaker_key = self._speaker_key_for_state(segment)
        source_speaker = "" if speaker_key == NO_SPEAKER_KEY else speaker_key

        target_speaker = ""
        speaker_translation_resolver = getattr(self, "_speaker_translation_for_key", None)
        if callable(speaker_translation_resolver) and speaker_key != NO_SPEAKER_KEY:
            try:
                translated = speaker_translation_resolver(speaker_key)
            except Exception:
                translated = None
            if isinstance(translated, str):
                target_speaker = translated.strip()
        if not target_speaker:
            target_speaker = segment.translation_speaker.strip()
        return source_speaker, target_speaker

    def _prompt_tl_speaker_label_for_segment(self, segment: DialogueSegment) -> str:
        source_speaker, target_speaker = self._prompt_speaker_values_for_segment(segment)
        speaker = target_speaker.strip() or source_speaker.strip()
        speaker = self._resolve_name_tokens_for_prompt_text(speaker).strip()
        if not speaker or speaker == NO_SPEAKER_KEY:
            return "Narration"
        return speaker

    def _resolve_name_tokens_for_prompt_text(self, text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        resolver = getattr(self, "_resolve_name_tokens_in_text", None)
        if not callable(resolver):
            return text
        try:
            resolved = resolver(text, prefer_translated=True)
        except TypeError:
            try:
                resolved = resolver(text, True)
            except Exception:
                resolved = text
        except Exception:
            resolved = text
        return resolved if isinstance(resolved, str) else text

    def _prompt_context_segment_rows(
        self,
        session: FileSession,
        anchor_index: int,
        direction: int,
        limit: int,
    ) -> list[tuple[int, DialogueSegment]]:
        if limit <= 0 or anchor_index < 0:
            return []
        if direction < 0:
            indexes = range(anchor_index - 1, -1, -1)
        else:
            indexes = range(anchor_index + 1, len(session.segments))

        rows: list[tuple[int, DialogueSegment]] = []
        for idx in indexes:
            segment = session.segments[idx]
            source_text = "\n".join(self._prompt_source_lines_for_segment(segment)).strip()
            if not source_text:
                continue
            rows.append((idx, segment))
            if len(rows) >= limit:
                break
        if direction < 0:
            rows.reverse()
        return rows

    def _prompt_inline_source_text_for_segment(self, segment: DialogueSegment) -> str:
        source_text = "\n".join(self._prompt_source_lines_for_segment(segment)).strip()
        if not source_text:
            source_text = "(empty)"
        source_text = self._resolve_name_tokens_for_prompt_text(source_text)
        normalized = source_text.replace("\r\n", "\n").replace("\r", "\n")
        escaped = normalized.replace("\n", "\\n")
        return escaped

    def _prompt_entry_type_for_segment(self, segment: DialogueSegment) -> str:
        type_resolver = getattr(self, "_segment_prompt_type", None)
        if callable(type_resolver):
            try:
                resolved = type_resolver(segment, "dialogue")
            except TypeError:
                try:
                    resolved = type_resolver(segment)
                except Exception:
                    resolved = "dialogue"
            except Exception:
                resolved = "dialogue"
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip().lower()
        return "dialogue"

    def _build_human_translation_reference_prompt(
        self,
        session: FileSession,
        segment: DialogueSegment,
        neighbor_count: int,
    ) -> str:
        source_language_label = self._translation_project_source_language_label()
        target_language_label = self._translation_profile_target_language_label()
        safe_neighbors = max(0, int(neighbor_count))

        anchor_index = -1
        for idx, row_segment in enumerate(session.segments):
            if row_segment.uid == segment.uid:
                anchor_index = idx
                break
        if anchor_index < 0:
            return ""

        before_rows = self._prompt_context_segment_rows(
            session,
            anchor_index,
            direction=-1,
            limit=safe_neighbors,
        )
        after_rows = self._prompt_context_segment_rows(
            session,
            anchor_index,
            direction=1,
            limit=safe_neighbors,
        )

        transcript_rows = [*before_rows, (anchor_index, segment), *after_rows]
        prompt_lines: list[str] = [
            f"Translate the following dialogue from {source_language_label} to {target_language_label}.",
            "Write natural, fluent game dialogue.",
            "Preserve intent, tone, and character voice.",
            "Keep control codes/placeholders unchanged when present.",
            "",
            "Transcript:",
        ]
        for _row_index, row_segment in transcript_rows:
            speaker_label = self._prompt_tl_speaker_label_for_segment(row_segment)
            source_text = self._prompt_inline_source_text_for_segment(row_segment)
            entry_type = self._prompt_entry_type_for_segment(row_segment)
            if entry_type == "thought":
                prompt_lines.append(f"{speaker_label}: ({source_text})")
            else:
                escaped_text = source_text.replace('"', '\\"')
                prompt_lines.append(f'{speaker_label}: "{escaped_text}"')

        return "\n".join(prompt_lines).strip() + "\n"
