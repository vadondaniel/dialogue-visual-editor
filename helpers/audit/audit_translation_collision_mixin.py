from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import preview_text


class _AuditTranslationCollisionHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditTranslationCollisionMixin(
    _AuditTranslationCollisionHostTypingFallback
):
    _BLOCK_ENTRY_RE = re.compile(r"^Block\s+(\d+)$", re.IGNORECASE)

    def _audit_translation_collision_group_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _audit_translation_collision_entry_payload(
        self,
        item: Optional[QListWidgetItem],
    ) -> Optional[dict[str, Any]]:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return None
        return payload

    def _translation_collision_entry_label(
        self,
        session: FileSession,
        segment: DialogueSegment,
        index: int,
    ) -> str:
        entry_resolver = getattr(self, "_audit_entry_text_for_segment", None)
        if callable(entry_resolver):
            return str(entry_resolver(session, segment, index))
        if segment.segment_kind == "map_display_name":
            return "Map displayName"
        if not self._is_name_index_session(session):
            return f"Block {index}"
        name_index_label = self._name_index_label(session)
        actor_id = self._actor_id_from_uid(segment.uid)
        if actor_id is not None:
            return f"{name_index_label} ID {actor_id}"
        return f"{name_index_label} {index}"

    def _translation_collision_entry_locator(
        self,
        path_raw: str,
        entry_label: str,
    ) -> str:
        relative_path = self._relative_path(Path(path_raw))
        file_stem = (
            Path(relative_path).stem.strip()
            or Path(path_raw).stem.strip()
            or Path(path_raw).name.strip()
            or "File"
        )
        block_match = self._BLOCK_ENTRY_RE.fullmatch(entry_label.strip())
        if block_match is not None:
            return f"{file_stem}:{block_match.group(1)}"
        return f"{file_stem}:{entry_label.strip() or 'Entry'}"

    def _collect_audit_translation_collision_groups(
        self,
        dialogue_only: bool,
        only_translated: bool,
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        first_seen_order: dict[str, int] = {}
        seen_order = 0
        normalize_for_segment = getattr(
            self,
            "_normalize_audit_translation_lines_for_segment",
            None,
        )
        for path, session in self._audit_path_sessions_snapshot():
            for block_index, segment in enumerate(session.segments, start=1):
                if dialogue_only and not bool(
                    getattr(segment, "is_structural_dialogue", False)
                ):
                    continue
                source_text = "\n".join(
                    self._segment_source_lines_for_display(segment)
                ).strip()
                if not source_text:
                    continue
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
                    tl_lines_raw = self._normalize_translation_lines(
                        segment.translation_lines
                    )
                translation_text = "\n".join(
                    self._normalize_translation_lines(tl_lines_raw)
                ).strip()
                if only_translated and not translation_text:
                    continue
                if translation_text not in first_seen_order:
                    first_seen_order[translation_text] = seen_order
                    seen_order += 1
                grouped.setdefault(translation_text, []).append(
                    {
                        "path": str(path),
                        "uid": segment.uid,
                        "entry": self._translation_collision_entry_label(
                            session,
                            segment,
                            block_index,
                        ),
                        "source_text": source_text,
                    }
                )
        groups: list[dict[str, Any]] = []
        for translation_text, entries in grouped.items():
            if len(entries) < 2:
                continue
            source_variants = Counter(
                str(entry.get("source_text", "")) for entry in entries
            )
            if len(source_variants) <= 1:
                continue
            most_common_source = ""
            if source_variants:
                most_common_source = max(
                    source_variants.items(),
                    key=lambda kv: (
                        kv[1],
                        bool(str(kv[0]).strip()),
                        len(str(kv[0])),
                    ),
                )[0]
            groups.append(
                {
                    "translation_text": translation_text,
                    "entries": entries,
                    "entry_count": len(entries),
                    "source_count": len(source_variants),
                    "most_common_source": most_common_source,
                    "first_seen_order": first_seen_order.get(translation_text, 0),
                }
            )
        groups.sort(
            key=lambda row: (
                int(row.get("first_seen_order", 0)),
                -int(row.get("source_count", 0)),
                -int(row.get("entry_count", 0)),
            )
        )
        return groups

    def _refresh_audit_translation_collision_entries(self) -> None:
        if (
            self.audit_translation_collision_groups_list is None
            or self.audit_translation_collision_entries_list is None
            or self.audit_translation_collision_goto_btn is None
        ):
            return
        group_payload = self._audit_translation_collision_group_payload(
            self.audit_translation_collision_groups_list.currentItem()
        )
        self.audit_translation_collision_entries_list.clear()
        self.audit_translation_collision_goto_btn.setEnabled(False)
        if group_payload is None:
            return
        entries_raw = group_payload.get("entries")
        if not isinstance(entries_raw, list):
            return
        parsed_entries: list[dict[str, str]] = []
        max_locator_width = 0
        for entry in entries_raw:
            if not isinstance(entry, dict):
                continue
            path_raw = entry.get("path")
            uid_raw = entry.get("uid")
            entry_label = entry.get("entry")
            source_text = entry.get("source_text")
            if not isinstance(path_raw, str) or not path_raw:
                continue
            if not isinstance(uid_raw, str) or not uid_raw:
                continue
            if not isinstance(entry_label, str):
                entry_label = "Entry"
            if not isinstance(source_text, str):
                source_text = ""
            locator = self._translation_collision_entry_locator(
                path_raw,
                entry_label,
            )
            max_locator_width = max(max_locator_width, len(locator))
            parsed_entries.append(
                {
                    "path": path_raw,
                    "uid": uid_raw,
                    "entry": entry_label,
                    "source_text": source_text,
                    "locator": locator,
                }
            )
        for entry in parsed_entries:
            source_preview = (
                entry["source_text"]
                .replace("\r", "\\r")
                .replace("\n", "\\n")
                .replace("\t", "\\t")
            )
            if not source_preview:
                source_preview = "(empty source)"
            locator = entry["locator"]
            padded_locator = (
                locator.ljust(max_locator_width)
                if max_locator_width > len(locator)
                else locator
            )
            item = QListWidgetItem(
                f"{padded_locator} | {preview_text(source_preview, 132)}"
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "path": entry["path"],
                    "uid": entry["uid"],
                },
            )
            self.audit_translation_collision_entries_list.addItem(item)
        if self.audit_translation_collision_entries_list.count() > 0:
            self.audit_translation_collision_entries_list.setCurrentRow(0)
            self.audit_translation_collision_goto_btn.setEnabled(True)

    def _refresh_audit_translation_collision_panel(self) -> None:
        if (
            self.audit_translation_collision_dialogue_only_check is None
            or self.audit_translation_collision_only_translated_check is None
            or self.audit_translation_collision_groups_list is None
            or self.audit_translation_collision_status_label is None
        ):
            return
        preferred_translation = ""
        selected_group = self._audit_translation_collision_group_payload(
            self.audit_translation_collision_groups_list.currentItem()
        )
        if selected_group is not None:
            selected_translation = selected_group.get("translation_text")
            if isinstance(selected_translation, str):
                preferred_translation = selected_translation
        dialogue_only = (
            self.audit_translation_collision_dialogue_only_check.isChecked()
        )
        only_translated = (
            self.audit_translation_collision_only_translated_check.isChecked()
        )
        groups = self._collect_audit_translation_collision_groups(
            dialogue_only=dialogue_only,
            only_translated=only_translated,
        )
        self.audit_translation_collision_groups_list.clear()
        selected_row = -1
        total_entries = 0
        for idx, group in enumerate(groups):
            translation_text = str(group.get("translation_text", ""))
            entry_count = int(group.get("entry_count", 0))
            source_count = int(group.get("source_count", 0))
            total_entries += entry_count
            label = (
                f"x{entry_count} | sources: {source_count} | "
                f"{preview_text(translation_text if translation_text else '(empty)', 96)}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.audit_translation_collision_groups_list.addItem(item)
            if preferred_translation and translation_text == preferred_translation:
                if selected_row < 0:
                    selected_row = idx
        if groups:
            if selected_row < 0:
                selected_row = 0
            self.audit_translation_collision_groups_list.setCurrentRow(selected_row)
            self.audit_translation_collision_status_label.setText(
                (
                    f"Collision groups: {len(groups)} | "
                    f"Colliding entries: {total_entries}"
                )
            )
        else:
            if only_translated:
                self.audit_translation_collision_status_label.setText(
                    "No translation collisions found (translated entries only)."
                )
            else:
                self.audit_translation_collision_status_label.setText(
                    "No translation collisions found."
                )
        self._refresh_audit_translation_collision_entries()

    def _go_to_selected_audit_translation_collision_entry(self) -> None:
        if self.audit_translation_collision_entries_list is None:
            return
        payload = self._audit_translation_collision_entry_payload(
            self.audit_translation_collision_entries_list.currentItem()
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
