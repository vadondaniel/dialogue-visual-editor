from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from .models import DialogueSegment, FileSession
from .parser import parse_dialogue_file
from .text_utils import chunk_lines

if TYPE_CHECKING:
    from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton



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
        invalidate_reference = getattr(self, "_invalidate_reference_summary_cache", None)
        if callable(invalidate_reference):
            invalidate_reference()
        invalidate_cached_view = getattr(self, "_invalidate_cached_block_view_for_path", None)
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
                entries.append({"code": 401, "indent": indent, "parameters": [line]})
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
            name_index_kind = name_index_kind_raw.strip().lower() if isinstance(name_index_kind_raw, str) else ""
            if name_index_kind == "system":
                for segment in session.segments:
                    path_tokens_raw = getattr(segment, "system_text_path", ())
                    if not isinstance(path_tokens_raw, tuple):
                        continue
                    new_value = "\n".join(segment.lines) if segment.lines else ""
                    self._set_json_value_by_path(session.data, path_tokens_raw, new_value)
                return

        if is_name_index_session and isinstance(session.data, list):
            uid_prefix_raw = getattr(session, "name_index_uid_prefix", "A")
            uid_prefix = uid_prefix_raw.strip() if isinstance(uid_prefix_raw, str) else "A"
            id_pattern = re.compile(rf":{re.escape(uid_prefix)}:(\d+)(?::([A-Za-z0-9_]+))?$")
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
                combined_fields_raw = getattr(segment, "name_index_combined_fields", ())
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
                    rebuilt.extend(self._build_entries_for_segment(token.segment))
            bundle.commands_ref[:] = rebuilt

    def _save_session(self, session: FileSession, refresh_current_view: bool = False) -> bool:
        if self._is_translator_mode():
            if not self._save_translation_state([session.path]):
                return False
            self._mark_session_translation_saved(session)
            self._refresh_dirty_state(session)
            if refresh_current_view and self.current_path == session.path:
                self._render_session(session)
            self.statusBar().showMessage(f"Saved TL state: {session.path.name}")
            return True

        try:
            was_visible = session.path in self.file_items
            changes = self._collect_change_log(session)
            self._apply_session_to_json(session)

            if self.backup_check.isChecked():
                backup_path = session.path.with_suffix(session.path.suffix + ".bak")
                if not backup_path.exists():
                    shutil.copy2(session.path, backup_path)

            with session.path.open("w", encoding="utf-8") as dst:
                json.dump(session.data, dst, ensure_ascii=False, indent=0)

            if self.index_db is not None:
                try:
                    rel = self._relative_path(session.path)
                    self.index_db.log_changes(rel, changes)
                except Exception:
                    pass

            if not self._save_translation_state([session.path]):
                return False

            reloaded = parse_dialogue_file(session.path)
            self._apply_translation_state_to_session(reloaded)
            self.sessions[session.path] = reloaded
            self._clear_structural_history_for_path(session.path)

            now_visible = self.show_empty_files_check.isChecked() or bool(reloaded.segments)
            if was_visible != now_visible:
                self._rebuild_file_list(preferred_path=self.current_path)
            else:
                self._update_file_item_text(session.path)

            if self.index_db is not None:
                try:
                    self.index_db.update_file_index(
                        self._relative_path(session.path),
                        session.path.stat().st_mtime,
                        reloaded.segments,
                    )
                except Exception:
                    pass

            if self.current_path == session.path and refresh_current_view:
                self._render_session(reloaded)
            else:
                self._refresh_dirty_state(reloaded)

            self.statusBar().showMessage(f"Saved: {session.path.name}")
            return True
        except Exception as exc:
            QMessageBox.critical(
                cast(QWidget, self),
                "Save failed",
                f"Failed to save file:\n{session.path}\n\n{exc}",
            )
            return False

    def _save_current_file(self) -> bool:
        if self.current_path is None:
            QMessageBox.warning(cast(QWidget, self), "No file selected", "Select a file before saving.")
            return False
        session = self.sessions.get(self.current_path)
        if session is None:
            QMessageBox.warning(cast(QWidget, self), "Not loaded", "Current file has not been loaded yet.")
            return False
        if (not self._is_translator_mode()) and (not self._session_has_source_changes(session)):
            if self._session_has_translation_changes(session):
                if not self._save_translation_state([session.path]):
                    return False
                self._mark_session_translation_saved(session)
                self._refresh_dirty_state(session)
                self.statusBar().showMessage(f"Saved TL state: {session.path.name}")
                return True
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
                segment.translation_lines = list(segment.original_translation_lines)
                segment.translation_speaker = segment.original_translation_speaker
            self._refresh_dirty_state(session)
            self._render_session(session)
            self.statusBar().showMessage(f"Reset TL changes in {session.path.name}.")
            return

        if not self._session_has_source_changes(session):
            self.statusBar().showMessage("No unsaved source changes in current JSON.")
            return

        button = QMessageBox.question(
            cast(QWidget, self),
            "Reset current JSON",
            f"Discard all unsaved changes in '{session.path.name}' and reload from disk?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if button != QMessageBox.StandardButton.Yes:
            return

        before = session
        self._open_file(session.path, force_reload=True)
        reloaded = self.sessions.get(session.path)
        if reloaded is not None and reloaded is not before and not reloaded.dirty:
            self.statusBar().showMessage(f"Reset {session.path.name} to on-disk state.")

    def _save_all_files(self) -> bool:
        if self._is_translator_mode():
            if not any(self._session_has_translation_changes(session) for session in self.sessions.values()):
                self.statusBar().showMessage("No unsaved TL files.")
                return True
            if not self._save_translation_state(list(self.sessions.keys())):
                return False
            for session in self.sessions.values():
                self._mark_session_translation_saved(session)
                self._refresh_dirty_state(session)
            if self.current_path is not None:
                current = self.sessions.get(self.current_path)
                if current is not None:
                    self._render_session(current)
            self.statusBar().showMessage("Saved TL state for all files.")
            return True

        source_dirty_paths = [
            path for path, session in self.sessions.items()
            if self._session_has_source_changes(session)
        ]
        tl_dirty_paths = [
            path for path, session in self.sessions.items()
            if self._session_has_translation_changes(session)
        ]

        if not source_dirty_paths and not tl_dirty_paths:
            self.statusBar().showMessage("No unsaved files.")
            return True

        failures: list[str] = []
        for path in source_dirty_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            ok = self._save_session(session, refresh_current_view=(path == self.current_path))
            if not ok:
                failures.append(path.name)

        tl_only_paths = [path for path in tl_dirty_paths if path not in source_dirty_paths]
        if tl_only_paths and not failures:
            if not self._save_translation_state(tl_only_paths):
                failures.extend(path.name for path in tl_only_paths)
            else:
                for path in tl_only_paths:
                    session = self.sessions.get(path)
                    if session is None:
                        continue
                    self._mark_session_translation_saved(session)
                    self._refresh_dirty_state(session)

        if failures:
            QMessageBox.warning(
                cast(QWidget, self),
                "Save completed with errors",
                "Some files failed to save:\n" + "\n".join(failures),
            )
            return False
        saved_total = len(source_dirty_paths) + len(tl_only_paths)
        self.statusBar().showMessage(f"Saved {saved_total} file(s).")
        return True

    def _export_translated_data_for_session(self, session: FileSession) -> Any:
        exported_session = copy.deepcopy(session)
        source_lookup = {segment.uid: segment for segment in session.segments}
        for export_segment in exported_session.segments:
            source_segment = source_lookup.get(export_segment.uid)
            if source_segment is None:
                continue
            tl_lines = self._normalize_translation_lines(source_segment.translation_lines)
            has_tl = any(line.strip() for line in tl_lines)
            export_segment.lines = tl_lines if has_tl else list(source_segment.lines or [""])

            speaker_en = source_segment.translation_speaker.strip()
            if speaker_en:
                params = export_segment.params
                while len(params) <= 4:
                    params.append("")
                params[4] = speaker_en
                export_segment.code101["parameters"] = params

        self._apply_session_to_json(exported_session)
        return exported_session.data

    def _export_session_to_folder(self, session: FileSession, out_dir: Path) -> bool:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / session.path.name
            exported_data = self._export_translated_data_for_session(session)
            with output_path.open("w", encoding="utf-8") as dst:
                json.dump(exported_data, dst, ensure_ascii=False, indent=0)
            return True
        except Exception as exc:
            QMessageBox.critical(
                cast(QWidget, self),
                "Export failed",
                f"Failed to export translation file:\n{session.path.name}\n\n{exc}",
            )
            return False

    def _choose_export_folder(self) -> Optional[Path]:
        if self.data_dir is None:
            return None
        chosen = QFileDialog.getExistingDirectory(
            cast(QWidget, self),
            "Select export folder",
            str(self.data_dir.parent),
        )
        if not chosen:
            return None
        return Path(chosen).resolve()

    def _export_current_translation(self) -> None:
        if self.current_path is None:
            QMessageBox.warning(cast(QWidget, self), "No file selected", "Select a file before exporting.")
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            QMessageBox.warning(cast(QWidget, self), "Not loaded", "Current file has not been loaded yet.")
            return
        out_dir = self._choose_export_folder()
        if out_dir is None:
            return
        if self._export_session_to_folder(session, out_dir):
            self.statusBar().showMessage(f"Exported TL file: {session.path.name}")

    def _export_all_translations(self) -> None:
        if not self.sessions:
            QMessageBox.warning(cast(QWidget, self), "No files loaded", "Load files before exporting translations.")
            return
        out_dir = self._choose_export_folder()
        if out_dir is None:
            return

        failed: list[str] = []
        for session in self.sessions.values():
            if not self._export_session_to_folder(session, out_dir):
                failed.append(session.path.name)
        if failed:
            QMessageBox.warning(
                cast(QWidget, self),
                "Export completed with errors",
                "Failed to export:\n" + "\n".join(failed),
            )
            return
        self.statusBar().showMessage(f"Exported TL files: {len(self.sessions)}")
