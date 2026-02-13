from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import preview_text


class _AuditConsistencyHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditConsistencyMixin(_AuditConsistencyHostTypingFallback):
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

    def _consistency_entry_label(
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

    def _collect_audit_consistency_groups(
        self,
        only_inconsistent: bool,
        sort_mode: str,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, str]]] = {}
        first_seen_order: dict[str, int] = {}
        source_order = 0
        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            for idx, segment in enumerate(session.segments, start=1):
                source_text = "\n".join(
                    self._segment_source_lines_for_display(segment)).strip()
                if not source_text:
                    continue
                if source_text not in first_seen_order:
                    first_seen_order[source_text] = source_order
                    source_order += 1
                tl_text = "\n".join(
                    self._normalize_translation_lines(
                        segment.translation_lines)
                ).strip()
                entry = {
                    "path": str(path),
                    "uid": segment.uid,
                    "entry": self._consistency_entry_label(session, segment, idx),
                    "translation": tl_text,
                }
                grouped.setdefault(source_text, []).append(entry)

        groups: list[dict[str, Any]] = []
        for source_text, entries in grouped.items():
            if len(entries) < 2:
                continue
            variants = Counter((entry.get("translation") or "").strip()
                               for entry in entries)
            unique_count = len(variants)
            if only_inconsistent and unique_count <= 1:
                continue
            most_common_text = ""
            if variants:
                most_common_text = max(
                    variants.items(),
                    key=lambda kv: (kv[1], bool(kv[0]), len(kv[0])),
                )[0]
            groups.append(
                {
                    "source_text": source_text,
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
            or self.audit_consistency_target_edit is None
            or self.audit_consistency_goto_btn is None
            or self.audit_consistency_apply_btn is None
            or self.audit_consistency_use_selected_btn is None
            or self.audit_consistency_use_common_btn is None
        ):
            return
        group_payload = self._audit_consistency_group_payload(
            self.audit_consistency_groups_list.currentItem()
        )
        self.audit_consistency_entries_list.clear()
        self.audit_consistency_goto_btn.setEnabled(False)
        self.audit_consistency_use_selected_btn.setEnabled(False)
        self.audit_consistency_apply_btn.setEnabled(group_payload is not None)
        self.audit_consistency_use_common_btn.setEnabled(group_payload is not None)
        if group_payload is None:
            self.audit_consistency_target_edit.setPlainText("")
            return

        entries = group_payload.get("entries")
        if not isinstance(entries, list):
            self.audit_consistency_target_edit.setPlainText("")
            return
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
            relative = self._relative_path(Path(path_raw))
            translation_preview = preview_text(
                translation if translation else "(empty)", 90
            )
            label = f"{relative} | {entry_label} | {translation_preview}"
            item = QListWidgetItem(label)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "path": path_raw,
                    "uid": uid_raw,
                    "translation": translation,
                },
            )
            self.audit_consistency_entries_list.addItem(item)

        if self.audit_consistency_entries_list.count() > 0:
            self.audit_consistency_entries_list.setCurrentRow(0)
            first_payload = self._audit_consistency_entry_payload(
                self.audit_consistency_entries_list.currentItem()
            )
            if first_payload is not None:
                first_translation = first_payload.get("translation")
                if isinstance(first_translation, str):
                    self.audit_consistency_target_edit.setPlainText(first_translation)
                else:
                    self.audit_consistency_target_edit.setPlainText("")
                return
        self.audit_consistency_target_edit.setPlainText("")

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
        translation = payload.get("translation")
        if isinstance(translation, str):
            self.audit_consistency_target_edit.setPlainText(translation)

    def _refresh_audit_consistency_panel(self, preferred_source: Optional[str] = None) -> None:
        if (
            self.audit_consistency_only_inconsistent_check is None
            or self.audit_consistency_sort_combo is None
            or self.audit_consistency_groups_list is None
            or self.audit_consistency_status_label is None
        ):
            return
        only_inconsistent = self.audit_consistency_only_inconsistent_check.isChecked()
        sort_mode_raw = self.audit_consistency_sort_combo.currentData()
        sort_mode = sort_mode_raw if isinstance(sort_mode_raw, str) else "source_order"
        groups = self._collect_audit_consistency_groups(only_inconsistent, sort_mode)
        self.audit_consistency_groups_list.clear()
        selected_row = -1
        total_entries = 0
        for idx, group in enumerate(groups):
            source_text = str(group.get("source_text", ""))
            count = int(group.get("entry_count", 0))
            variants = int(group.get("variant_count", 0))
            total_entries += count
            label = (
                f"x{count} | variants: {variants} | "
                f"{preview_text(source_text, 96)}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.audit_consistency_groups_list.addItem(item)
            if preferred_source and source_text == preferred_source:
                selected_row = idx

        if groups:
            if selected_row < 0:
                selected_row = 0
            self.audit_consistency_groups_list.setCurrentRow(selected_row)
        self.audit_consistency_status_label.setText(
            f"Duplicate groups: {len(groups)} | Duplicate entries: {total_entries}"
        )
        self._refresh_audit_consistency_entries()

    def _use_selected_audit_consistency_entry(self) -> None:
        if (
            self.audit_consistency_entries_list is None
            or self.audit_consistency_target_edit is None
        ):
            return
        payload = self._audit_consistency_entry_payload(
            self.audit_consistency_entries_list.currentItem()
        )
        if payload is None:
            self.statusBar().showMessage("Select an entry first.")
            return
        translation = payload.get("translation")
        if not isinstance(translation, str):
            translation = ""
        self.audit_consistency_target_edit.setPlainText(translation)
        self.statusBar().showMessage("Loaded selected entry translation as target.")

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
        self.statusBar().showMessage("Loaded most-common translation as target.")

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

    def _apply_audit_consistency_target_to_group(self) -> None:
        if (
            self.audit_consistency_groups_list is None
            or self.audit_consistency_target_edit is None
        ):
            return
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
        target_lines = self._normalize_translation_lines(target_text)
        touched_paths: set[Path] = set()
        touched_current = False
        changed_entries = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path_raw = entry.get("path")
            uid_raw = entry.get("uid")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            if not isinstance(uid_raw, str) or not uid_raw:
                continue
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
            if current_lines == target_lines:
                continue
            target_segment.translation_lines = list(target_lines)
            changed_entries += 1
            touched_paths.add(path)
            if self.current_path is not None and path == self.current_path:
                touched_current = True

        if changed_entries <= 0:
            self.statusBar().showMessage("No translations changed in this group.")
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
        self._refresh_audit_consistency_panel(preferred_source=source_key)
        self.statusBar().showMessage(
            f"Synchronized translation across {changed_entries} duplicate entries."
        )
