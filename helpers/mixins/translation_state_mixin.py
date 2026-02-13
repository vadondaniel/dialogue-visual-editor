from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtWidgets import QMessageBox, QWidget

from ..core.models import (
    DialogueSegment,
    FileSession,
)
from ..core.text_utils import (
    fuzzy_compare_text,
    natural_sort_key,
    preview_text,
    similarity_signature,
    split_lines_preserve_empty,
    unique_preserve_order,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton


class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class TranslationStateMixin(_EditorHostTypingFallback):
    # Provided by DialogueVisualEditor at runtime; declared for static analyzers.
    editor_mode_combo: "QComboBox"
    save_btn: "QPushButton"
    save_all_btn: "QPushButton"
    reset_json_btn: "QPushButton"
    auto_split_check: "QCheckBox"
    translation_state_path: Optional[Path]
    translation_state: dict[str, Any]
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
        self._rerender_current_file()

    def _update_mode_controls(self) -> None:
        translator_mode = self._is_translator_mode()
        if translator_mode:
            self.save_btn.setText("Save")
            self.save_all_btn.setText("Save All")
            self.reset_json_btn.setText("Reset TL/JSON")
            self.auto_split_check.setToolTip(
                "Used when building translated snapshot data."
            )
        else:
            self.save_btn.setText("Save")
            self.save_all_btn.setText("Save All")
            self.reset_json_btn.setText("Reset JSON")
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

    def _segment_reference_source_text(self, segment: DialogueSegment) -> str:
        source_lines = segment.source_lines or segment.original_lines or segment.lines or [
            ""]
        return "\n".join(source_lines)

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

    def _load_translation_state(self) -> None:
        self.translation_state = {
            "version": 1,
            "uid_counter": 0,
            "speaker_map": {},
            "files": {},
        }
        self.speaker_translation_map = {}
        self.translation_uid_counter = 0
        if self.translation_state_path is None:
            return
        if not self.translation_state_path.exists():
            return

        try:
            with self.translation_state_path.open("r", encoding="utf-8") as src:
                loaded = json.load(src)
            if isinstance(loaded, dict):
                self.translation_state.update(loaded)
        except Exception as exc:
            QMessageBox.warning(
                cast(QWidget, self),
                "Translation state warning",
                f"Failed to load translation state:\n{self.translation_state_path}\n\n{exc}",
            )
            return

        speaker_map_raw = self.translation_state.get("speaker_map")
        if isinstance(speaker_map_raw, dict):
            for key, value in speaker_map_raw.items():
                if isinstance(key, str) and isinstance(value, str) and value.strip():
                    self.speaker_translation_map[key] = value.strip()

        counter_raw = self.translation_state.get("uid_counter", 0)
        if isinstance(counter_raw, int):
            self.translation_uid_counter = max(0, counter_raw)

        files_raw = self.translation_state.get("files")
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
        files_raw = self.translation_state.get("files")
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
        for uid, entry in entries.items():
            source_hash = entry.get("source_hash")
            if isinstance(source_hash, str) and source_hash:
                hash_buckets.setdefault(source_hash, []).append(uid)

        for idx, segment in enumerate(session.segments):
            segment.source_lines = list(
                segment.lines) if segment.lines else [""]
            source_hash = self._segment_source_hash(segment)
            chosen_uid = ""
            preferred_uid = order[idx] if idx < len(order) else ""

            if preferred_uid and preferred_uid in unused:
                preferred_entry = entries.get(preferred_uid, {})
                preferred_hash = preferred_entry.get("source_hash")
                if isinstance(preferred_hash, str) and preferred_hash == source_hash:
                    chosen_uid = preferred_uid
                    unused.remove(preferred_uid)

            if not chosen_uid:
                for candidate_uid in hash_buckets.get(source_hash, []):
                    if candidate_uid in unused:
                        chosen_uid = candidate_uid
                        unused.remove(candidate_uid)
                        break

            if not chosen_uid and preferred_uid and preferred_uid in unused:
                chosen_uid = preferred_uid
                unused.remove(preferred_uid)

            if not chosen_uid:
                chosen_uid = self._new_translation_uid()

            entry = entries.get(chosen_uid, {})
            tl_lines = self._normalize_translation_lines(
                entry.get("translation_lines"))
            speaker_en_raw = entry.get("speaker_en")
            speaker_en = speaker_en_raw.strip() if isinstance(speaker_en_raw, str) else ""
            speaker_key = self._speaker_key_for_state(segment)
            if not speaker_en:
                speaker_en = self.speaker_translation_map.get(speaker_key, "")

            segment.tl_uid = chosen_uid
            segment.translation_lines = list(tl_lines)
            segment.original_translation_lines = list(tl_lines)
            segment.translation_speaker = speaker_en
            segment.original_translation_speaker = speaker_en

            if speaker_en:
                self.speaker_translation_map[speaker_key] = speaker_en

    def _sync_translation_state_from_sessions(self) -> None:
        files_state: dict[str, Any] = {}
        for path, session in self.sessions.items():
            files_state[self._relative_path(
                path)] = self._translation_state_for_session(session)

        sorted_speaker_map: dict[str, str] = {}
        for key in sorted(self.speaker_translation_map.keys(), key=natural_sort_key):
            value = self.speaker_translation_map.get(key, "").strip()
            if value:
                sorted_speaker_map[key] = value

        self.translation_state = {
            "version": 1,
            "uid_counter": self.translation_uid_counter,
            "speaker_map": sorted_speaker_map,
            "files": files_state,
        }

    def _translation_state_for_session(self, session: FileSession) -> dict[str, Any]:
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
            entries[segment.tl_uid] = {
                "source_hash": self._segment_source_hash(segment),
                "source_preview": preview_text(self._segment_reference_source_text(segment), 130),
                "speaker_jp": speaker_key,
                "speaker_en": speaker_en,
                "translation_lines": translation_lines,
            }
            if speaker_en:
                self.speaker_translation_map[speaker_key] = speaker_en
        return {"order": order, "entries": entries}

    def _save_translation_state(self, changed_paths: Optional[list[Path]] = None) -> bool:
        if self.translation_state_path is None:
            return True
        try:
            if changed_paths is None:
                self._sync_translation_state_from_sessions()
            else:
                files_raw = self.translation_state.get("files")
                if not isinstance(files_raw, dict):
                    files_raw = {}
                    self.translation_state["files"] = files_raw
                for path in changed_paths:
                    session = self.sessions.get(path)
                    if session is None:
                        continue
                    files_raw[self._relative_path(
                        path)] = self._translation_state_for_session(session)

                sorted_speaker_map: dict[str, str] = {}
                for key in sorted(self.speaker_translation_map.keys(), key=natural_sort_key):
                    value = self.speaker_translation_map.get(key, "").strip()
                    if value:
                        sorted_speaker_map[key] = value
                self.translation_state["speaker_map"] = sorted_speaker_map
                self.translation_state["uid_counter"] = self.translation_uid_counter
                self.translation_state["version"] = 1

            with self.translation_state_path.open("w", encoding="utf-8") as dst:
                json.dump(self.translation_state, dst,
                          ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            QMessageBox.critical(
                cast(QWidget, self),
                "Save failed",
                f"Failed to save translation state:\n{self.translation_state_path}\n\n{exc}",
            )
            return False

    def _session_has_source_changes(self, session: FileSession) -> bool:
        for segment in session.segments:
            if segment.inserted:
                return True
            if segment.merged_segments:
                return True
            if segment.lines != segment.original_lines:
                return True
        return False

    def _session_has_translation_changes(self, session: FileSession) -> bool:
        for segment in session.segments:
            if self._normalize_translation_lines(segment.translation_lines) != self._normalize_translation_lines(
                segment.original_translation_lines
            ):
                return True
            if segment.translation_speaker.strip() != segment.original_translation_speaker.strip():
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

    def _build_reference_summary_for_session(self, session: FileSession) -> dict[str, tuple[str, str]]:
        rows: list[dict[str, Any]] = []
        for row_path, row_session in self.sessions.items():
            for block_number, segment in enumerate(row_session.segments, start=1):
                source_text = self._segment_reference_source_text(
                    segment).strip()
                if not source_text:
                    continue
                rows.append(
                    {
                        "path": row_path,
                        "uid": segment.uid,
                        "file": row_path.name,
                        "block_number": block_number,
                        "source_text": source_text,
                        "translation_text": self._segment_reference_translation_text(segment),
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
            own_source = self._segment_reference_source_text(segment).strip()
            own_path = session.path
            own_uid = segment.uid

            exact_candidates = [
                row for row in exact_groups.get(own_source, [])
                if not (row["path"] == own_path and row["uid"] == own_uid)
            ]
            exact_cross_file = [
                row for row in exact_candidates if row["path"] != own_path]
            exact_pool = exact_cross_file if exact_cross_file else exact_candidates
            if exact_pool:
                en_variants = unique_preserve_order(
                    [cast(str, row["translation_text"])
                     for row in exact_pool if cast(str, row["translation_text"])]
                )
                samples = []
                for row in exact_pool[:3]:
                    sample_tl = cast(
                        str, row["translation_text"]) or "(no EN yet)"
                    samples.append(
                        f"{row['file']}#{row['block_number']}: {preview_text(sample_tl, 48)}"
                    )
                exact_scope = "in other files" if exact_cross_file else "in this file/folder"
                block_label = "block" if len(exact_pool) == 1 else "blocks"
                variant_label = "variant" if len(en_variants) == 1 else "variants"
                exact_summary = (
                    f"Exact JP matches {exact_scope}: {len(exact_pool)} {block_label}, EN {variant_label}: {len(en_variants)}."
                )
                if samples:
                    exact_summary += " " + " | ".join(samples)
            else:
                exact_summary = "Exact JP matches: none."

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
                            str, row["translation_text"]) or "(no EN yet)"
                        sample_parts.append(
                            f"{row['file']}#{row['block_number']} ({ratio:.2f}): {preview_text(sample_tl, 44)}"
                        )
                    candidate_label = "candidate" if len(scored) == 1 else "candidates"
                    similar_summary = f"Similar JP phrases: {len(scored)} {candidate_label}. " + " | ".join(
                        sample_parts)
                else:
                    similar_summary = "Similar JP phrases: none."
            else:
                similar_summary = "Similar JP phrases: none."

            summaries[segment.uid] = (exact_summary, similar_summary)
        return summaries
