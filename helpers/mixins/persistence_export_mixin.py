from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

from PySide6.QtWidgets import QMessageBox, QWidget

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import chunk_lines

ApplyVersionKind = Literal["original", "working", "translated"]


class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class PersistenceExportMixin(_EditorHostTypingFallback):
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
        self._update_file_item_text(session.path)
        if self.current_path == session.path:
            header = f"{session.path.name} | {len(session.segments)} dialogue block(s)"
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
        suffix = " [empty]" if len(session.segments) == 0 else ""
        item.setText(f"{prefix}{path.name} ({len(session.segments)}){suffix}")

    def _build_entries_for_segment(self, segment: DialogueSegment) -> list[dict[str, Any]]:
        return self._build_entries_for_segment_lines(segment, segment.lines)

    def _build_entries_for_segment_lines(
        self,
        segment: DialogueSegment,
        lines_source: list[str],
        speaker_override: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        lines = list(lines_source) if lines_source else [""]
        if self.auto_split_check.isChecked():
            chunks = chunk_lines(lines, self.max_lines_spin.value())
        else:
            chunks = [lines]

        entries: list[dict[str, Any]] = []
        line_template = segment.code401_template if isinstance(
            segment.code401_template, dict) else {}
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
                    line_entry["code"] = 401
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
                        {"code": 401, "indent": indent, "parameters": [line]})
        return entries

    def _collect_change_log(self, session: FileSession) -> list[tuple[str, str, str]]:
        changes: list[tuple[str, str, str]] = []
        for segment in session.segments:
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
                    pass

            if translator_mode:
                self._mark_session_translation_saved(session)
            else:
                self._mark_session_source_saved(session)
                self._mark_session_translation_saved(session)
                self._clear_structural_history_for_path(session.path)

            self._refresh_dirty_state(session)
            if refresh_current_view and self.current_path == session.path:
                self._render_session(session, preserve_scroll=True)

            if translator_mode:
                self.statusBar().showMessage(
                    f"Saved TL snapshot to DB: {session.path.name}")
            else:
                self.statusBar().showMessage(
                    f"Saved snapshot to DB: {session.path.name}")
            return True
        except Exception as exc:
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
            if not tl_dirty:
                self.statusBar().showMessage("No unsaved TL changes in current file.")
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
                if self._session_has_translation_changes(session)
            ]
            if not dirty_paths:
                self.statusBar().showMessage("No unsaved TL files.")
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

        self.statusBar().showMessage(f"Saved {len(dirty_paths)} snapshot file(s) to DB.")
        return True

    def _selected_apply_version(self) -> ApplyVersionKind:
        raw = self.apply_version_combo.currentData()
        if raw == "original":
            return "original"
        if raw == "working":
            return "working"
        return "translated"

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
                f"Apply '{version_label}' snapshots to JSON game files in:\n"
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
        target_paths = [path for path in self.file_paths if path in self.sessions]
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
                with path.open("w", encoding="utf-8") as dst:
                    dst.write(payload)
                applied += 1
            except Exception as exc:
                failed.append(f"{path.name}: {exc}")

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
            pass

        current_dir = self.data_dir
        self._load_data_folder(current_dir)
        if missing or failed:
            self.statusBar().showMessage(
                f"Applied {version_label} snapshots to {applied} file(s) with warnings."
            )
        else:
            self.statusBar().showMessage(
                f"Applied {version_label} snapshots to {applied} file(s)."
            )

    def _export_translated_data_for_session(self, session: FileSession) -> Any:
        exported_session = copy.deepcopy(session)
        source_lookup = {segment.uid: segment for segment in session.segments}
        for export_segment in exported_session.segments:
            source_segment = source_lookup.get(export_segment.uid)
            if source_segment is None:
                continue
            tl_lines = self._normalize_translation_lines(
                source_segment.translation_lines)
            has_tl = any(line.strip() for line in tl_lines)
            export_segment.lines = tl_lines if has_tl else list(
                source_segment.lines or [""])

            speaker_en = source_segment.translation_speaker.strip()
            if speaker_en:
                params = export_segment.params
                while len(params) <= 4:
                    params.append("")
                params[4] = speaker_en
                export_segment.code101["parameters"] = params

        self._apply_session_to_json(exported_session)
        return exported_session.data
