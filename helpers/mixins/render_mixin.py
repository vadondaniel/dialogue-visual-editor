from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import DialogueSegment, FileSession
from ..core.text_utils import strip_control_tokens
from ..ui.ui_components import DialogueBlockWidget, ItemNameDescriptionWidget

BlockWidgetType = DialogueBlockWidget | ItemNameDescriptionWidget


class _RenderHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class RenderMixin(_RenderHostTypingFallback):
    _PLUGIN_NUMBER_RE = re.compile(
        r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"
    )
    _ALPHANUMERIC_TEXT_RE = re.compile(r"^[A-Za-z0-9]+(?:[ \t]+[A-Za-z0-9]+)*$")
    _TYRANO_SCRIPT_TEXT_UID_RE = re.compile(r":ks:\d+$")

    @classmethod
    def _text_is_non_meaningful_parameter_value(cls, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        lowered = stripped.lower()
        if lowered in {"true", "false", "on", "off", "none"}:
            return True
        if bool(cls._PLUGIN_NUMBER_RE.fullmatch(stripped)):
            return True
        candidate = stripped
        if candidate.startswith("[") and candidate.endswith("]"):
            candidate = candidate[1:-1].strip()
        if "," not in candidate:
            return False
        parts = [part.strip() for part in candidate.split(",")]
        if not parts or any(not part for part in parts):
            return False
        return all(bool(cls._PLUGIN_NUMBER_RE.fullmatch(part)) for part in parts)

    def _is_map_display_name_segment(self, segment: DialogueSegment) -> bool:
        return segment.segment_kind == "map_display_name"

    @staticmethod
    def _is_misc_segment_for_display(segment: DialogueSegment) -> bool:
        return segment.segment_kind in {
            "name_index",
            "system_text",
            "plugin_text",
            "plugin_command_text",
            "note_text",
            "actor_name_alias",
            "tyrano_tag_text",
        }

    @staticmethod
    def _source_uid_is_plugins_parameter_entry(source_uid: str) -> bool:
        normalized = source_uid.strip().lower()
        if not normalized:
            return False
        return normalized.startswith("plugins.js:j:") and ":param_" in normalized

    @classmethod
    def _source_uid_is_tyrano_script_string_entry(cls, source_uid: str) -> bool:
        normalized = source_uid.strip().lower()
        if not normalized:
            return False
        return bool(cls._TYRANO_SCRIPT_TEXT_UID_RE.search(normalized))

    @classmethod
    def _text_is_alphanumeric_only(cls, text: str) -> bool:
        compact = " ".join(text.split())
        if not compact:
            return False
        return bool(cls._ALPHANUMERIC_TEXT_RE.fullmatch(compact))

    def _plugin_group_key_and_title_for_segment(
        self,
        session_path: Path,
        segment: DialogueSegment,
    ) -> Optional[tuple[str, str]]:
        if segment.segment_kind != "plugin_text":
            return None
        path_tokens_raw = getattr(segment, "plugin_text_path", ())
        path_tokens = (
            path_tokens_raw
            if isinstance(path_tokens_raw, tuple)
            else tuple(path_tokens_raw) if isinstance(path_tokens_raw, list) else ()
        )
        if len(path_tokens) < 2:
            return None
        list_marker = path_tokens[0]
        if not isinstance(list_marker, str) or "plugins_js_array" not in list_marker:
            return None
        plugin_index_raw = path_tokens[1]
        if not isinstance(plugin_index_raw, int) or plugin_index_raw < 0:
            return None
        plugin_index = plugin_index_raw
        plugin_name = ""
        if len(segment.params) > 4 and isinstance(segment.params[4], str):
            plugin_name = segment.params[4].strip()
        title = f"Plugin {plugin_index + 1}"
        if plugin_name:
            title = f"{title}: {plugin_name}"
        group_key = f"{session_path.as_posix()}::plugin::{plugin_index}"
        return group_key, title

    def _plugin_group_collapsed_state(self) -> dict[str, bool]:
        raw = getattr(self, "_plugin_group_collapsed_state_map", None)
        if isinstance(raw, dict):
            return cast(dict[str, bool], raw)
        created: dict[str, bool] = {}
        setattr(self, "_plugin_group_collapsed_state_map", created)
        return created

    def _is_plugin_group_collapsed(self, group_key: str) -> bool:
        state_map = self._plugin_group_collapsed_state()
        value = state_map.get(group_key)
        if isinstance(value, bool):
            return value
        return True

    def _set_plugin_group_collapsed(self, group_key: str, collapsed: bool) -> None:
        state_map = self._plugin_group_collapsed_state()
        state_map[group_key] = bool(collapsed)

    def _plugin_group_description_hint_for_segment(
        self,
        segment: DialogueSegment,
        *,
        translator_mode: bool,
    ) -> Optional[str]:
        if segment.segment_kind != "plugin_text":
            return None
        path_tokens_raw = getattr(segment, "plugin_text_path", ())
        path_tokens = (
            path_tokens_raw
            if isinstance(path_tokens_raw, tuple)
            else tuple(path_tokens_raw) if isinstance(path_tokens_raw, list) else ()
        )
        if len(path_tokens) < 3:
            return None
        if path_tokens[2] != "description":
            return None
        source_text = self._segment_source_text_for_meaningful_check(segment)
        chosen_text = source_text
        if translator_mode:
            translation_lines: list[str] = []
            translation_resolver = getattr(
                self,
                "_segment_translation_lines_for_translation",
                None,
            )
            if callable(translation_resolver):
                try:
                    resolved = translation_resolver(segment)
                    if isinstance(resolved, list):
                        translation_lines = [
                            line if isinstance(line, str) else str(line)
                            for line in resolved
                        ]
                except Exception:
                    translation_lines = []
            elif isinstance(segment.translation_lines, list):
                translation_lines = [
                    line if isinstance(line, str) else str(line)
                    for line in segment.translation_lines
                ]
            translation_text = "\n".join(translation_lines)
            visible_translation = strip_control_tokens(
                translation_text
            ).replace("\u3000", " ").strip()
            if visible_translation:
                chosen_text = translation_text
        visible = strip_control_tokens(chosen_text).replace("\u3000", " ").strip()
        if not visible:
            return None
        compact = " ".join(part.strip() for part in visible.splitlines() if part.strip())
        if not compact:
            return None
        max_len = 80
        if len(compact) > max_len:
            compact = compact[: max_len - 3].rstrip() + "..."
        return compact

    def _update_plugin_group_header_counts(
        self,
        count_labels: dict[str, QLabel],
        member_widgets_by_group: dict[str, list[QWidget]],
        description_hints_by_group: dict[str, str],
    ) -> None:
        for group_key, count_label in count_labels.items():
            members = member_widgets_by_group.get(group_key, [])
            count = len(members)
            label = "entry" if count == 1 else "entries"
            text = f"{count} {label}"
            hint = description_hints_by_group.get(group_key, "").strip()
            if hint:
                text = f"{text}  |  {hint}"
            count_label.setText(text)

    def _build_plugin_group_header_widget(
        self,
        *,
        group_key: str,
        title: str,
        member_widgets: list[QWidget],
    ) -> tuple[QWidget, QLabel]:
        header = QFrame(self.scroll_container)
        header.setObjectName("pluginGroupHeader")
        header.setStyleSheet(
            "QFrame#pluginGroupHeader {"
            "background: rgba(148, 163, 184, 0.12);"
            "border: 1px solid rgba(100, 116, 139, 0.35);"
            "border-radius: 6px;"
            "}"
            "QToolButton {"
            "border: 0;"
            "font-weight: 600;"
            "padding: 2px 4px;"
            "text-align: left;"
            "}"
            "QLabel#pluginGroupCount {"
            "color: #64748b;"
            "}"
        )
        row = QHBoxLayout(header)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)

        toggle = QToolButton(header)
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setText(title)
        toggle.setAutoRaise(True)
        row.addWidget(toggle, 1)

        count_label = QLabel("", header)
        count_label.setObjectName("pluginGroupCount")
        row.addWidget(count_label)

        collapsed = self._is_plugin_group_collapsed(group_key)
        toggle.blockSignals(True)
        toggle.setChecked(not collapsed)
        toggle.blockSignals(False)
        toggle.setArrowType(
            Qt.ArrowType.DownArrow if not collapsed else Qt.ArrowType.RightArrow
        )
        self._set_plugin_group_collapsed(group_key, collapsed)

        def on_toggled(expanded: bool) -> None:
            collapsed_now = not expanded
            toggle.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
            self._set_plugin_group_collapsed(group_key, collapsed_now)
            for member_widget in member_widgets:
                member_widget.setVisible(expanded)
            self._schedule_dialogue_editor_visibility_update()

        toggle.toggled.connect(on_toggled)
        return header, count_label

    def _hide_non_meaningful_entries_enabled(self) -> bool:
        checkbox = getattr(self, "hide_non_meaningful_entries_check", None)
        if checkbox is None:
            return False
        checker = getattr(checkbox, "isChecked", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _segment_source_text_for_meaningful_check(self, segment: DialogueSegment) -> str:
        lines = segment.source_lines or segment.original_lines or segment.lines or [""]
        return "\n".join(lines)

    def _is_empty_map_display_name_segment(self, segment: DialogueSegment) -> bool:
        if not self._is_map_display_name_segment(segment):
            return False
        source_text = self._segment_source_text_for_meaningful_check(segment)
        visible = strip_control_tokens(source_text).replace("\u3000", " ").strip()
        return not bool(visible)

    def _is_plugin_non_meaningful_parameter_segment(self, segment: DialogueSegment) -> bool:
        if segment.segment_kind not in {"plugin_text", "plugin_command_text"}:
            return False
        if segment.segment_kind == "plugin_text":
            path_tokens_raw = getattr(segment, "plugin_text_path", ())
            path_tokens = (
                path_tokens_raw
                if isinstance(path_tokens_raw, tuple)
                else tuple(path_tokens_raw) if isinstance(path_tokens_raw, list) else ()
            )
            if len(path_tokens) < 4:
                return False
            if path_tokens[2] != "parameters":
                return False
        else:
            path_tokens_raw = getattr(segment, "plugin_command_text_path", ())
            path_tokens = (
                path_tokens_raw
                if isinstance(path_tokens_raw, tuple)
                else tuple(path_tokens_raw) if isinstance(path_tokens_raw, list) else ()
            )
            if not path_tokens:
                return False
            has_parameter_marker = any(
                (
                    index + 1 < len(path_tokens)
                    and path_tokens[index] == "parameters"
                    and path_tokens[index + 1] == 3
                )
                for index in range(len(path_tokens))
            )
            if not has_parameter_marker:
                return False
        source_text = self._segment_source_text_for_meaningful_check(segment)
        return self._text_is_non_meaningful_parameter_value(source_text)

    def _is_tyrano_script_string_non_meaningful_segment(self, segment: DialogueSegment) -> bool:
        if segment.segment_kind != "tyrano_tag_text":
            return False
        join_mode_raw = getattr(segment, "tyrano_tag_text_join_mode", "")
        join_mode = join_mode_raw.strip().lower() if isinstance(join_mode_raw, str) else ""
        if join_mode != "script_string":
            return False
        source_text = self._segment_source_text_for_meaningful_check(segment)
        visible = strip_control_tokens(source_text).replace("\u3000", " ").strip()
        return self._text_is_alphanumeric_only(visible)

    def _is_meaningful_segment_for_display(self, segment: DialogueSegment) -> bool:
        if self._is_empty_map_display_name_segment(segment):
            return False
        if self._is_plugin_non_meaningful_parameter_segment(segment):
            return False
        if self._is_tyrano_script_string_non_meaningful_segment(segment):
            return False
        return True

    def _is_actor_name_index_session(self, session: FileSession) -> bool:
        checker = getattr(self, "_is_actor_index_session", None)
        if callable(checker):
            try:
                return bool(checker(session))
            except Exception:
                pass
        raw_kind = getattr(session, "name_index_kind", "")
        kind = raw_kind.strip().lower() if isinstance(raw_kind, str) else ""
        return kind == "actor"

    def _filter_actor_name_index_display_segments(
        self,
        session: FileSession,
        segments: list[DialogueSegment],
    ) -> list[DialogueSegment]:
        if not self._is_actor_name_index_session(session):
            return segments
        filtered: list[DialogueSegment] = []
        seen_names: set[str] = set()
        field_from_uid_resolver = getattr(self, "_name_index_field_from_uid", None)
        for segment in segments:
            source_text = self._segment_source_text_for_meaningful_check(segment)
            visible = strip_control_tokens(source_text).replace("\u3000", " ").strip()
            if not visible:
                continue
            field_name = "name"
            if callable(field_from_uid_resolver):
                try:
                    resolved_field = field_from_uid_resolver(segment.uid)
                except Exception:
                    resolved_field = None
                if isinstance(resolved_field, str) and resolved_field.strip():
                    field_name = resolved_field.strip().lower()
            is_alias_segment = bool(getattr(segment, "is_actor_name_alias", False))
            if field_name == "name" or is_alias_segment:
                key = visible.casefold()
                if key in seen_names:
                    continue
                seen_names.add(key)
            filtered.append(segment)
        return filtered

    def _translation_state_entry_is_meaningful_for_display(
        self,
        entry: dict[str, Any],
    ) -> bool:
        source_preview_raw = entry.get("source_preview", "")
        source_preview = source_preview_raw if isinstance(source_preview_raw, str) else ""
        visible_source = strip_control_tokens(source_preview).replace("\u3000", " ").strip()
        if not visible_source:
            return False
        if not self._hide_non_meaningful_entries_enabled():
            return True
        source_uid_raw = entry.get("source_uid", "")
        source_uid = source_uid_raw if isinstance(source_uid_raw, str) else ""
        if (
            self._source_uid_is_plugins_parameter_entry(source_uid)
            and self._text_is_non_meaningful_parameter_value(visible_source)
        ):
            return False
        if (
            self._source_uid_is_tyrano_script_string_entry(source_uid)
            and self._text_is_alphanumeric_only(visible_source)
        ):
            return False
        return True

    def _display_block_count(
        self,
        segments: list[DialogueSegment],
        *,
        actor_mode: bool,
    ) -> int:
        if actor_mode:
            return len(segments)
        numbers = self._display_block_numbers(segments, actor_mode=False)
        return len({number for number in numbers.values() if number > 0})

    def _display_block_numbers(
        self,
        segments: list[DialogueSegment],
        *,
        actor_mode: bool,
    ) -> dict[str, int]:
        numbers: dict[str, int] = {}
        if actor_mode:
            for idx, segment in enumerate(segments, start=1):
                numbers[segment.uid] = idx
            return numbers

        next_number = 1
        current_chain_number: Optional[int] = None
        for segment in segments:
            if self._is_map_display_name_segment(segment):
                numbers[segment.uid] = 0
                continue
            if bool(getattr(segment, "translation_only", False)):
                if current_chain_number is None:
                    current_chain_number = next_number
                    next_number += 1
                numbers[segment.uid] = current_chain_number
                continue
            current_chain_number = next_number
            numbers[segment.uid] = current_chain_number
            next_number += 1
        return numbers

    def _segment_allows_structural_actions(
        self,
        segment: DialogueSegment,
        *,
        actor_mode: bool,
    ) -> bool:
        if actor_mode:
            return False
        return segment.is_structural_dialogue

    def _apply_block_visual_state(self, uid: str, widget: BlockWidgetType) -> None:
        set_selected = getattr(widget, "set_selected_state", None)
        if callable(set_selected):
            set_selected(self.selected_segment_uid == uid)
        set_pinned = getattr(widget, "set_audit_pinned_state", None)
        if callable(set_pinned):
            set_pinned(self.audit_pinned_uid == uid)

    def _flash_pending_audit_target(
        self, focus_uid: Optional[str], target_widget: Optional[BlockWidgetType]
    ) -> None:
        if focus_uid is None or target_widget is None:
            return
        if self.pending_audit_flash_uid != focus_uid:
            return
        flash_highlight = getattr(target_widget, "flash_highlight", None)
        if not callable(flash_highlight):
            return
        flash_highlight()
        self.pending_audit_flash_uid = None

    def _target_widget_visible_in_viewport(
        self, target_widget: BlockWidgetType
    ) -> bool:
        viewport = self.scroll_area.viewport()
        target_top_left = target_widget.mapTo(viewport, QPoint(0, 0))
        target_rect = QRect(target_top_left, target_widget.size())
        visible_rect = viewport.rect().adjusted(20, 20, -20, -20)
        if visible_rect.isEmpty():
            visible_rect = viewport.rect()
        return target_rect.intersects(visible_rect)

    def _focus_target_widget(
        self,
        target_widget: BlockWidgetType,
        *,
        preserve_scroll_value: Optional[int] = None,
    ) -> None:
        scroll_bar = self.scroll_area.verticalScrollBar()
        if preserve_scroll_value is not None:
            scroll_bar.setValue(preserve_scroll_value)
        already_visible = self._target_widget_visible_in_viewport(target_widget)
        target_widget.focus_editor()
        self._schedule_dialogue_editor_visibility_update()
        if preserve_scroll_value is not None and already_visible:
            scroll_bar.setValue(preserve_scroll_value)
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(preserve_scroll_value)
            )
            return
        if not already_visible:
            self.scroll_area.ensureWidgetVisible(target_widget, 20, 20)

    def _ensure_dialogue_editor_visibility_tracking(self) -> None:
        if bool(getattr(self, "_dialogue_editor_visibility_tracking_ready", False)):
            return
        self.scroll_area.verticalScrollBar().valueChanged.connect(
            self._schedule_dialogue_editor_visibility_update
        )
        self.scroll_area.horizontalScrollBar().valueChanged.connect(
            self._schedule_dialogue_editor_visibility_update
        )
        setattr(self, "_dialogue_editor_visibility_tracking_ready", True)

    def _schedule_dialogue_editor_visibility_update(self) -> None:
        self._ensure_dialogue_editor_visibility_tracking()
        timer = cast(
            Optional[QTimer],
            getattr(self, "_dialogue_editor_visibility_timer", None),
        )
        if timer is None:
            timer = QTimer(cast(QObject, self))
            timer.setSingleShot(True)
            timer.timeout.connect(self._update_visible_dialogue_editors)
            setattr(self, "_dialogue_editor_visibility_timer", timer)
        timer.start(15)

    def _refresh_block_width_constraints(self) -> None:
        if not self.block_widgets:
            return
        for widget in self.block_widgets.values():
            apply_width = getattr(widget, "_apply_editor_width", None)
            if callable(apply_width):
                apply_width()

    def _schedule_block_width_constraints_refresh(self) -> None:
        timer = cast(
            Optional[QTimer],
            getattr(self, "_block_width_constraints_timer", None),
        )
        if timer is None:
            timer = QTimer(cast(QObject, self))
            timer.setSingleShot(True)
            timer.timeout.connect(self._refresh_block_width_constraints)
            setattr(self, "_block_width_constraints_timer", timer)
        timer.start(15)

    def _update_visible_dialogue_editors(self) -> None:
        if not self.block_widgets:
            return
        viewport = self.scroll_area.viewport()
        expanded_viewport = viewport.rect().adjusted(0, -800, 0, 800)
        for widget in self.block_widgets.values():
            if not isinstance(widget, DialogueBlockWidget):
                continue
            top_left = widget.mapTo(viewport, QPoint(0, 0))
            widget_rect = QRect(top_left, widget.size())
            widget.set_editor_active(expanded_viewport.intersects(widget_rect))

    def _rerender_blocks_near_viewport(self, overscan_px: int = 800) -> None:
        current_path = self.current_path
        if current_path is None:
            return
        session = self.sessions.get(current_path)
        if session is None:
            return
        if not self.block_widgets:
            return
        actor_mode = self._is_name_index_session(session)
        translator_mode = self._is_translator_mode()
        display_segments = self._display_segments_for_session(
            session,
            translator_mode=translator_mode,
            actor_mode=actor_mode,
        )
        block_numbers = self._display_block_numbers(
            display_segments,
            actor_mode=actor_mode,
        )
        segment_lookup = {segment.uid: segment for segment in display_segments}
        name_index_label = self._name_index_label(session)
        viewport = self.scroll_area.viewport()
        expanded_viewport = viewport.rect().adjusted(
            0, -max(0, overscan_px), 0, max(0, overscan_px)
        )
        for uid in self.rendered_block_uid_order:
            segment = segment_lookup.get(uid)
            widget = self.block_widgets.get(uid)
            if segment is None or widget is None:
                continue
            top_left = widget.mapTo(viewport, QPoint(0, 0))
            widget_rect = QRect(top_left, widget.size())
            if not expanded_viewport.intersects(widget_rect):
                continue
            self._sync_reused_block_widget(
                widget,
                segment=segment,
                block_number=block_numbers.get(uid, 1),
                name_index_label=name_index_label,
            )
            self._apply_block_visual_state(uid, widget)
        self._refresh_translator_detail_panel()
        self._schedule_dialogue_editor_visibility_update()

    def _block_view_meta(
        self,
        *,
        translator_mode: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
        current_page: int,
        total_pages: int,
        page_size: int,
    ) -> tuple[Any, ...]:
        return (
            translator_mode,
            actor_mode,
            name_index_kind,
            name_index_label,
            self.thin_width_spin.value(),
            self.wide_width_spin.value(),
            self.max_lines_spin.value(),
            int(current_page),
            int(total_pages),
            int(page_size),
            bool(self.hide_control_codes_check.isChecked()),
            bool(self.infer_speaker_check.isChecked()),
            bool(self._hide_non_meaningful_entries_enabled()),
        )

    def _pagination_page_size_value(self) -> int:
        page_size_resolver = getattr(self, "_pagination_page_size", None)
        if callable(page_size_resolver):
            try:
                value = int(page_size_resolver())
            except Exception:
                value = 50
            return max(1, value)
        return 50

    def _pagination_state_key(
        self,
        session: FileSession,
        *,
        actor_mode: bool,
    ) -> tuple[Path, str]:
        scope = "misc" if actor_mode else "dialogue"
        normalizer = getattr(self, "_normalized_view_scope_for_path", None)
        if callable(normalizer):
            try:
                normalized_scope = normalizer(session.path, session, scope)
            except Exception:
                normalized_scope = scope
            if isinstance(normalized_scope, str) and normalized_scope.strip():
                scope = normalized_scope.strip().lower()
        return session.path, scope

    def _pagination_page_map(self) -> dict[tuple[Path, str], int]:
        raw = getattr(self, "_pagination_page_by_scope_key", None)
        if isinstance(raw, dict):
            return cast(dict[tuple[Path, str], int], raw)
        created: dict[tuple[Path, str], int] = {}
        setattr(self, "_pagination_page_by_scope_key", created)
        return created

    def _paginate_segments_for_render(
        self,
        session: FileSession,
        display_segments: list[DialogueSegment],
        *,
        actor_mode: bool,
        focus_uid: Optional[str],
    ) -> tuple[list[DialogueSegment], dict[str, Any]]:
        page_size = self._pagination_page_size_value()
        state_key = self._pagination_state_key(session, actor_mode=actor_mode)
        page_map = self._pagination_page_map()
        if actor_mode:
            total_entries = len(display_segments)
            total_pages = max(1, (total_entries + page_size - 1) // page_size)
            stored_page = int(page_map.get(state_key, 1))
            target_page = max(1, min(stored_page, total_pages))

            def page_for_uid(uid: str) -> Optional[int]:
                for idx, segment in enumerate(display_segments):
                    if segment.uid == uid:
                        return (idx // page_size) + 1
                return None

            if isinstance(focus_uid, str) and focus_uid:
                focus_page = page_for_uid(focus_uid)
                if focus_page is not None:
                    target_page = focus_page
            else:
                selected_uid = getattr(self, "selected_segment_uid", None)
                if isinstance(selected_uid, str) and selected_uid:
                    selected_page = page_for_uid(selected_uid)
                    if selected_page is not None:
                        target_page = selected_page

            target_page = max(1, min(target_page, total_pages))
            page_map[state_key] = target_page
            start_index = (target_page - 1) * page_size
            end_index = min(total_entries, start_index + page_size)
            paged_segments = display_segments[start_index:end_index]
            return paged_segments, {
                "state_key": state_key,
                "current_page": target_page,
                "total_pages": total_pages,
                "total_entries": total_entries,
                "page_size": page_size,
                "page_start_index": start_index + 1 if total_entries > 0 else 0,
                "page_end_index": end_index if total_entries > 0 else 0,
            }

        logical_groups: list[list[DialogueSegment]] = []
        current_group: list[DialogueSegment] = []
        for segment in display_segments:
            if bool(getattr(segment, "translation_only", False)):
                if current_group:
                    current_group.append(segment)
                else:
                    logical_groups.append([segment])
                continue
            if current_group:
                logical_groups.append(current_group)
            current_group = [segment]
        if current_group:
            logical_groups.append(current_group)

        total_entries = len(logical_groups)
        total_pages = max(1, (total_entries + page_size - 1) // page_size)
        stored_page = int(page_map.get(state_key, 1))
        target_page = max(1, min(stored_page, total_pages))

        uid_to_page: dict[str, int] = {}
        for group_index, group in enumerate(logical_groups):
            page_number = (group_index // page_size) + 1
            for segment in group:
                uid_to_page[segment.uid] = page_number

        if isinstance(focus_uid, str) and focus_uid:
            focus_page = uid_to_page.get(focus_uid)
            if focus_page is not None:
                target_page = focus_page
        else:
            selected_uid = getattr(self, "selected_segment_uid", None)
            if isinstance(selected_uid, str) and selected_uid:
                selected_page = uid_to_page.get(selected_uid)
                if selected_page is not None:
                    target_page = selected_page

        target_page = max(1, min(target_page, total_pages))
        page_map[state_key] = target_page
        start_index = (target_page - 1) * page_size
        end_index = min(total_entries, start_index + page_size)
        page_groups = logical_groups[start_index:end_index]
        paged_segments: list[DialogueSegment] = [
            segment for group in page_groups for segment in group
        ]
        return paged_segments, {
            "state_key": state_key,
            "current_page": target_page,
            "total_pages": total_pages,
            "total_entries": total_entries,
            "page_size": page_size,
            "page_start_index": start_index + 1 if total_entries > 0 else 0,
            "page_end_index": end_index if total_entries > 0 else 0,
        }

    def _apply_pagination_render_state(self, payload: dict[str, Any]) -> None:
        state_key = payload.get("state_key")
        if isinstance(state_key, tuple) and len(state_key) == 2:
            setattr(self, "_pagination_active_scope_key", state_key)
        else:
            setattr(self, "_pagination_active_scope_key", None)
        setattr(self, "_pagination_current_page", int(payload.get("current_page", 1)))
        setattr(self, "_pagination_total_pages", int(payload.get("total_pages", 1)))
        setattr(self, "_pagination_total_entries", int(payload.get("total_entries", 0)))
        setattr(self, "_pagination_active_page_size", int(payload.get("page_size", 50)))
        setattr(self, "_pagination_page_start_index", int(payload.get("page_start_index", 0)))
        setattr(self, "_pagination_page_end_index", int(payload.get("page_end_index", 0)))
        refresh_controls = getattr(self, "_refresh_pagination_controls", None)
        if callable(refresh_controls):
            refresh_controls()

    def _display_segments_for_session(
        self,
        session: FileSession,
        *,
        translator_mode: bool,
        actor_mode: bool,
    ) -> list[DialogueSegment]:
        if actor_mode or translator_mode:
            segments = list(session.segments)
        else:
            segments = [segment for segment in session.segments if not segment.translation_only]
        has_misc_segments = any(
            self._is_misc_segment_for_display(segment)
            for segment in segments
        )
        has_structural_dialogue_segments = any(
            segment.segment_kind in {
                "dialogue",
                "choice",
                "script_message",
                "tyrano_dialogue",
            }
            for segment in segments
        )
        has_mixed_scope_segments = bool(
            getattr(session, "has_mixed_dialogue_misc_segments", False)
        ) or (has_misc_segments and has_structural_dialogue_segments)
        if has_mixed_scope_segments:
            if actor_mode:
                segments = [
                    segment
                    for segment in segments
                    if self._is_misc_segment_for_display(segment)
                ]
            else:
                segments = [
                    segment
                    for segment in segments
                    if not self._is_misc_segment_for_display(segment)
                ]
        if not self._hide_non_meaningful_entries_enabled():
            filtered = segments
        else:
            filtered = [
                segment
                for segment in segments
                if self._is_meaningful_segment_for_display(segment)
            ]
        if actor_mode:
            return self._filter_actor_name_index_display_segments(session, filtered)
        return filtered

    def _create_blocks_container(self) -> tuple[QWidget, QVBoxLayout]:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addStretch(1)
        return container, layout

    def _store_current_block_container_cache(self) -> None:
        path = self.rendered_blocks_path
        if path is None or self._pending_render_state is not None:
            return
        self.cached_block_containers_by_path[path] = {
            "container": self.scroll_container,
            "block_widgets": dict(self.block_widgets),
            "uid_order": list(self.rendered_block_uid_order),
            "view_meta": self.rendered_block_view_meta,
        }

    def _try_restore_cached_block_container(
        self,
        session: FileSession,
        display_segments: list[DialogueSegment],
        view_meta: tuple[Any, ...],
        *,
        focus_uid: Optional[str],
        preserve_scroll: bool,
        previous_scroll_value: Optional[int],
        start_at_top: bool,
    ) -> bool:
        cached = self.cached_block_containers_by_path.get(session.path)
        if not isinstance(cached, dict):
            return False
        cached_container = cached.get("container")
        cached_block_widgets = cached.get("block_widgets")
        cached_uid_order = cached.get("uid_order")
        cached_meta = cached.get("view_meta")
        if not isinstance(cached_container, QWidget):
            return False
        if not isinstance(cached_block_widgets, dict):
            return False
        if not isinstance(cached_uid_order, list):
            return False
        if cast(tuple[Any, ...], cached_meta) != view_meta:
            return False
        target_uid_order = [segment.uid for segment in display_segments]
        if cached_uid_order != target_uid_order:
            return False

        current_widget = self.scroll_area.takeWidget()
        if current_widget is not None and current_widget is not cached_container:
            current_path = self.rendered_blocks_path
            if current_path is not None:
                self.cached_block_containers_by_path[current_path] = {
                    "container": current_widget,
                    "block_widgets": dict(self.block_widgets),
                    "uid_order": list(self.rendered_block_uid_order),
                    "view_meta": self.rendered_block_view_meta,
                }
            else:
                current_widget.deleteLater()

        self.scroll_area.setWidget(cached_container)
        self.scroll_container = cached_container
        layout_obj = self.scroll_container.layout()
        if isinstance(layout_obj, QVBoxLayout):
            self.blocks_layout = layout_obj
        self.block_widgets = cast(
            dict[str, BlockWidgetType], cached_block_widgets)
        for uid, widget in self.block_widgets.items():
            self._apply_block_visual_state(uid, widget)
        self.rendered_blocks_path = session.path
        self.rendered_block_uid_order = target_uid_order
        self.rendered_block_view_meta = view_meta
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)
        self.scroll_area.setEnabled(True)
        self._refresh_translator_detail_panel()
        self._schedule_dialogue_editor_visibility_update()

        target_widget = (
            self.block_widgets.get(focus_uid)
            if focus_uid and focus_uid in self.block_widgets
            else None
        )
        self._flash_pending_audit_target(focus_uid, target_widget)
        if preserve_scroll and previous_scroll_value is not None:
            def restore_scroll_and_focus_cached_container() -> None:
                if target_widget is not None:
                    self._focus_target_widget(
                        target_widget,
                        preserve_scroll_value=previous_scroll_value,
                    )
                else:
                    self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)

            QTimer.singleShot(0, restore_scroll_and_focus_cached_container)
            return True
        if start_at_top and target_widget is None:
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
            return True
        if target_widget is not None:
            def focus_and_reveal_cached_container() -> None:
                self._focus_target_widget(target_widget)

            QTimer.singleShot(0, focus_and_reveal_cached_container)
        return True

    def _switch_to_new_active_blocks_container(self) -> None:
        current_widget = self.scroll_area.takeWidget()
        if current_widget is not None:
            current_path = self.rendered_blocks_path
            if current_path is not None and self._pending_render_state is None:
                self.cached_block_containers_by_path[current_path] = {
                    "container": current_widget,
                    "block_widgets": dict(self.block_widgets),
                    "uid_order": list(self.rendered_block_uid_order),
                    "view_meta": self.rendered_block_view_meta,
                }
            else:
                current_widget.deleteLater()
        self.scroll_container, self.blocks_layout = self._create_blocks_container()
        self.scroll_area.setWidget(self.scroll_container)
        self.block_widgets = {}
        self.rendered_blocks_path = None
        self.rendered_block_uid_order = []
        self.rendered_block_view_meta = None

    def _invalidate_cached_block_view_for_path(self, path: Path) -> None:
        cached_container = self.cached_block_containers_by_path.pop(path, None)
        if isinstance(cached_container, dict):
            container = cached_container.get("container")
            if isinstance(container, QWidget) and container is not self.scroll_container:
                container.deleteLater()
        pool = self.cached_block_widgets_by_path.pop(path, None)
        if isinstance(pool, dict):
            for widget in pool.values():
                if isinstance(widget, QWidget):
                    widget.deleteLater()
        self.cached_block_uid_order_by_path.pop(path, None)
        self.cached_block_view_meta_by_path.pop(path, None)

    def _clear_cached_block_views(self) -> None:
        paths = set(self.cached_block_widgets_by_path.keys())
        paths.update(self.cached_block_containers_by_path.keys())
        for path in list(paths):
            self._invalidate_cached_block_view_for_path(path)

    def _invalidate_reference_summary_cache(self) -> None:
        self.reference_summary_cache_by_path.clear()

    def _session_dirty_flags_cached(self, session: FileSession) -> tuple[bool, bool]:
        source_cached = getattr(session, "_cached_source_dirty", None)
        tl_cached = getattr(session, "_cached_tl_dirty", None)
        if isinstance(source_cached, bool) and isinstance(tl_cached, bool):
            return source_cached, tl_cached
        source_dirty = self._session_has_source_changes(session)
        tl_dirty = self._session_has_translation_changes(session)
        setattr(session, "_cached_source_dirty", source_dirty)
        setattr(session, "_cached_tl_dirty", tl_dirty)
        session.dirty = source_dirty or tl_dirty
        return source_dirty, tl_dirty

    def _is_name_desc_combined_segment(self, actor_mode: bool, segment: DialogueSegment) -> bool:
        combined_fields_raw = getattr(
            segment, "name_index_combined_fields", ())
        return (
            actor_mode
            and isinstance(combined_fields_raw, tuple)
            and "name" in combined_fields_raw
            and "description" in combined_fields_raw
        )

    def _bind_block_widget_signals(self, widget: BlockWidgetType) -> None:
        widget.text_changed.connect(self._on_block_text_changed)
        widget.activated.connect(self._on_block_activated)
        widget.insert_after_requested.connect(self._on_insert_after_requested)
        widget.delete_requested.connect(self._on_delete_requested)
        widget.reset_requested.connect(self._on_reset_requested)
        widget.split_overflow_requested.connect(
            self._on_split_overflow_requested)
        if isinstance(widget, DialogueBlockWidget):
            widget.line1_inference_override_changed.connect(
                self._on_line1_inference_override_changed
            )

    def _translator_source_hint_lines_for_segment(
        self,
        segment: DialogueSegment,
    ) -> list[str]:
        def normalize_lines(value: Any) -> list[str]:
            if isinstance(value, list):
                lines = [
                    line if isinstance(line, str) else ("" if line is None else str(line))
                    for line in value
                ]
                return lines if lines else [""]
            if isinstance(value, str):
                return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            return [""]

        logical_source_resolver = getattr(
            self,
            "_logical_translation_source_lines_for_segment",
            None,
        )
        if callable(logical_source_resolver):
            try:
                resolved = logical_source_resolver(segment)
            except Exception:
                resolved = None
            if isinstance(resolved, list):
                normalized = normalize_lines(resolved)
                return normalized if normalized else [""]
        source_lines = (
            segment.source_lines
            or segment.original_lines
            or segment.lines
            or [""]
        )
        normalized_fallback = normalize_lines(source_lines)
        return normalized_fallback if normalized_fallback else [""]

    def _configure_dialogue_widget_translation_context(
        self,
        widget: DialogueBlockWidget,
        segment: DialogueSegment,
    ) -> None:
        logical_source_resolver = getattr(
            self,
            "_logical_translation_source_lines_for_segment",
            None,
        )
        widget.source_hint_lines_resolver = (
            logical_source_resolver if callable(logical_source_resolver) else None
        )
        widget.control_mismatch_source_lines_resolver = (
            logical_source_resolver if callable(logical_source_resolver) else None
        )
        logical_translation_resolver = getattr(
            self,
            "_logical_translation_lines_for_problem_checks",
            None,
        )
        if not callable(logical_translation_resolver):
            logical_translation_resolver = getattr(
                self,
                "_logical_translation_lines_for_segment",
                None,
            )
        widget.control_mismatch_translation_lines_resolver = (
            logical_translation_resolver if callable(logical_translation_resolver) else None
        )
        if widget.translator_mode:
            widget._source_hint_lines = self._translator_source_hint_lines_for_segment(
                segment
            )

    def _create_block_widget(
        self,
        segment: DialogueSegment,
        block_number: int,
        translator_mode: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
    ) -> BlockWidgetType:
        if self._is_name_desc_combined_segment(actor_mode, segment):
            widget = ItemNameDescriptionWidget(
                segment=segment,
                block_number=block_number,
                hide_control_codes_when_unfocused=self.hide_control_codes_check.isChecked(),
                hidden_control_line_transform=self._hidden_control_line_transform,
                hidden_control_colored_line_resolver=self._hidden_control_line_with_color_spans,
                color_code_resolver=self._color_for_rpgm_code,
                variable_label_resolver=self._variable_label_for_rpgm_index,
                translator_mode=translator_mode,
                name_index_label=name_index_label,
            )
        else:
            allow_structural = self._segment_allows_structural_actions(
                segment,
                actor_mode=actor_mode,
            )
            widget = DialogueBlockWidget(
                segment=segment,
                block_number=block_number,
                thin_width=self.thin_width_spin.value(),
                wide_width=self.wide_width_spin.value(),
                max_lines=self.max_lines_spin.value(),
                infer_name_from_first_line=self.infer_speaker_check.isChecked(),
                smart_collapse_allow_comma_endings=bool(
                    self.smart_collapse_allow_comma_endings
                ),
                smart_collapse_allow_colon_triplet_endings=bool(
                    self.smart_collapse_allow_colon_triplet_endings
                ),
                smart_collapse_ellipsis_lowercase_rule=bool(
                    self.smart_collapse_ellipsis_lowercase_rule
                ),
                smart_collapse_collapse_if_no_punctuation=bool(
                    self.smart_collapse_collapse_if_no_punctuation
                ),
                smart_collapse_min_soft_ratio=(
                    self._smart_collapse_min_soft_ratio()
                    if self._smart_collapse_use_soft_ratio_rule()
                    else 0.0
                ),
                hide_control_codes_when_unfocused=self.hide_control_codes_check.isChecked(),
                hidden_control_line_transform=self._hidden_control_line_transform,
                hidden_control_colored_line_resolver=self._hidden_control_line_with_color_spans,
                speaker_display_resolver=self._resolve_speaker_display_name,
                speaker_display_html_resolver=self._render_text_with_color_codes_html,
                hint_display_html_resolver=self._render_text_with_color_codes_html_muted,
                color_code_resolver=self._color_for_rpgm_code,
                variable_label_resolver=self._variable_label_for_rpgm_index,
                speaker_tint_color=self._speaker_color_for_segment(segment),
                translator_mode=translator_mode,
                highlight_control_mismatch=bool(
                    self.problem_control_mismatch_check.isChecked()
                ),
                highlight_contains_japanese=bool(
                    self.problem_contains_japanese_check.isChecked()
                ),
                actor_mode=actor_mode,
                name_index_kind=name_index_kind,
                name_index_label=name_index_label,
                allow_structural_actions=allow_structural,
                inferred_speaker_name_resolver=self._inferred_speaker_from_segment_line1,
                segment_prompt_type_resolver=getattr(self, "_segment_prompt_type", None),
            )
            self._configure_dialogue_widget_translation_context(widget, segment)
        self._bind_block_widget_signals(widget)
        return widget

    def _can_reuse_block_widget(
        self,
        widget: BlockWidgetType,
        *,
        segment: DialogueSegment,
        translator_mode: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
    ) -> bool:
        clean_label = name_index_label.strip() or "Entry"
        expected_is_name_desc = self._is_name_desc_combined_segment(
            actor_mode, segment)
        if expected_is_name_desc:
            if not isinstance(widget, ItemNameDescriptionWidget):
                return False
            return (
                bool(widget.translator_mode) == bool(translator_mode)
                and str(widget.name_index_label).strip() == clean_label
            )

        if not isinstance(widget, DialogueBlockWidget):
            return False
        allow_structural = self._segment_allows_structural_actions(
            segment,
            actor_mode=actor_mode,
        )
        return (
            bool(widget.translator_mode) == bool(translator_mode)
            and bool(widget.actor_mode) == bool(actor_mode)
            and str(widget.name_index_kind).strip().lower() == name_index_kind
            and str(widget.name_index_label).strip() == clean_label
            and int(widget.thin_width) == int(self.thin_width_spin.value())
            and int(widget.wide_width) == int(self.wide_width_spin.value())
            and int(widget.max_lines) == int(self.max_lines_spin.value())
            and bool(widget.infer_name_from_first_line) == bool(self.infer_speaker_check.isChecked())
            and bool(widget.allow_structural_actions) == allow_structural
        )

    def _sync_reused_item_name_desc_widget(
        self,
        widget: ItemNameDescriptionWidget,
        segment: DialogueSegment,
        block_number: int,
        name_index_label: str,
    ) -> None:
        widget.segment = segment
        widget.block_number = block_number
        widget.name_index_label = name_index_label.strip() or "Item"
        widget._actor_id = widget._actor_id_from_uid()
        edited_lines = segment.translation_lines if widget.translator_mode else segment.lines
        if not edited_lines:
            edited_lines = [""]
        source_lines = segment.source_lines or segment.original_lines or segment.lines or [
            ""]
        name_lines, desc_lines = widget._split_combined_lines(
            list(edited_lines))
        source_name_lines, source_desc_lines = widget._split_combined_lines(
            list(source_lines))
        widget._raw_name_lines = list(name_lines)
        widget._raw_desc_lines = list(desc_lines)
        widget._source_name_text = "\n".join(source_name_lines).strip()
        widget._source_desc_text = "\n".join(source_desc_lines).strip()
        widget.context_label.setText(segment.context)
        widget.set_hide_control_codes_when_unfocused(
            self.hide_control_codes_check.isChecked())
        widget._sync_control_code_visibility(force=True)
        widget._refresh_meta_label()
        widget._refresh_status()
        widget._refresh_block_style()

    def _sync_reused_dialogue_widget(
        self,
        widget: DialogueBlockWidget,
        segment: DialogueSegment,
        block_number: int,
    ) -> None:
        widget.segment = segment
        widget.block_number = block_number
        widget.thin_width = max(1, self.thin_width_spin.value())
        widget.wide_width = max(1, self.wide_width_spin.value())
        widget.max_lines = max(1, self.max_lines_spin.value())
        widget.infer_name_from_first_line = self.infer_speaker_check.isChecked()
        widget.smart_collapse_allow_comma_endings = bool(
            self.smart_collapse_allow_comma_endings
        )
        widget.smart_collapse_allow_colon_triplet_endings = bool(
            self.smart_collapse_allow_colon_triplet_endings
        )
        widget.smart_collapse_ellipsis_lowercase_rule = bool(
            self.smart_collapse_ellipsis_lowercase_rule
        )
        widget.smart_collapse_collapse_if_no_punctuation = bool(
            self.smart_collapse_collapse_if_no_punctuation
        )
        widget.smart_collapse_min_soft_ratio = max(
            0.0,
            min(
                1.0,
                float(
                    self._smart_collapse_min_soft_ratio()
                    if self._smart_collapse_use_soft_ratio_rule()
                    else 0.0
                ),
            ),
        )
        widget.inferred_speaker_name_resolver = self._inferred_speaker_from_segment_line1
        widget.segment_prompt_type_resolver = getattr(self, "_segment_prompt_type", None)
        widget.speaker_tint_color = self._speaker_color_for_segment(segment)
        widget.allow_structural_actions = self._segment_allows_structural_actions(
            segment,
            actor_mode=widget.actor_mode,
        )
        if widget.actor_mode:
            widget.collapse_button.setVisible(False)
            widget.smart_collapse_button.setVisible(False)
            widget.wrap_button.setVisible(False)
            widget.insert_button.setVisible(False)
            widget.delete_button.setVisible(False)
        else:
            is_standard_dialogue = segment.is_structural_dialogue
            widget.collapse_button.setVisible(is_standard_dialogue)
            widget.smart_collapse_button.setVisible(is_standard_dialogue)
            widget.wrap_button.setVisible(is_standard_dialogue)
            widget.insert_button.setVisible(widget.allow_structural_actions)
            widget.delete_button.setVisible(widget.allow_structural_actions)
        widget._actor_id = widget._actor_id_from_uid()
        widget._name_index_field = widget._name_index_field_from_uid()
        widget._load_editor_lines_from_segment()
        self._configure_dialogue_widget_translation_context(widget, segment)
        widget.context_label.setText(segment.context)
        widget._apply_editor_width()
        widget.set_hide_control_codes_when_unfocused(
            self.hide_control_codes_check.isChecked())
        widget.set_control_mismatch_highlighting_enabled(
            bool(self.problem_control_mismatch_check.isChecked())
        )
        widget.set_japanese_char_problem_enabled(
            bool(self.problem_contains_japanese_check.isChecked())
        )
        widget._sync_control_code_visibility(force=True)
        widget.refresh_metadata()
        widget._refresh_block_style()

    def _sync_reused_block_widget(
        self,
        widget: BlockWidgetType,
        segment: DialogueSegment,
        block_number: int,
        name_index_label: str,
    ) -> None:
        if isinstance(widget, ItemNameDescriptionWidget):
            self._sync_reused_item_name_desc_widget(
                widget,
                segment,
                block_number,
                name_index_label,
            )
            return
        if isinstance(widget, DialogueBlockWidget):
            self._sync_reused_dialogue_widget(
                widget,
                segment,
                block_number,
            )

    def _can_fast_refresh_session_widgets(
        self,
        session: FileSession,
        display_segments: list[DialogueSegment],
        translator_mode: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
    ) -> bool:
        if self.rendered_blocks_path is None or self.rendered_blocks_path != session.path:
            return False
        if self.rendered_block_uid_order != [segment.uid for segment in display_segments]:
            return False
        if len(self.block_widgets) != len(display_segments):
            return False
        for segment in display_segments:
            widget = self.block_widgets.get(segment.uid)
            if widget is None:
                return False
            if not self._can_reuse_block_widget(
                widget,
                segment=segment,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
                name_index_kind=name_index_kind,
                name_index_label=name_index_label,
            ):
                return False
        return True

    def _can_restore_cached_widget_pool(
        self,
        display_segments: list[DialogueSegment],
        pool: dict[str, BlockWidgetType],
        cached_uid_order: list[str],
        cached_meta: tuple[Any, ...],
        target_meta: tuple[Any, ...],
    ) -> bool:
        if cached_meta != target_meta:
            return False
        target_uid_order = [segment.uid for segment in display_segments]
        if cached_uid_order != target_uid_order:
            return False
        return len(pool) == len(target_uid_order)

    def _restore_cached_widget_pool(
        self,
        session: FileSession,
        display_segments: list[DialogueSegment],
        pool: dict[str, BlockWidgetType],
        *,
        block_numbers: dict[str, int],
        translator_mode: bool,
        actor_mode: bool,
        name_index_label: str,
        merge_pairs: set[tuple[str, str]],
    ) -> None:
        self.block_widgets = {}
        segment_count = len(display_segments)
        plugin_group_members: dict[str, list[QWidget]] = {}
        plugin_group_count_labels: dict[str, QLabel] = {}
        plugin_group_description_hints: dict[str, str] = {}
        active_plugin_group_key: Optional[str] = None
        for idx, segment in enumerate(display_segments):
            group_info = self._plugin_group_key_and_title_for_segment(
                session.path,
                segment,
            )
            if group_info is None:
                active_plugin_group_key = None
            else:
                group_key, group_title = group_info
                if group_key != active_plugin_group_key:
                    members = plugin_group_members.get(group_key)
                    if members is None:
                        members = []
                        plugin_group_members[group_key] = members
                    header_widget, count_label = self._build_plugin_group_header_widget(
                        group_key=group_key,
                        title=group_title,
                        member_widgets=members,
                    )
                    plugin_group_count_labels[group_key] = count_label
                    self.blocks_layout.addWidget(header_widget)
                active_plugin_group_key = group_key
                if group_key not in plugin_group_description_hints:
                    hint = self._plugin_group_description_hint_for_segment(
                        segment,
                        translator_mode=translator_mode,
                    )
                    if hint:
                        plugin_group_description_hints[group_key] = hint

            widget = pool.pop(segment.uid, None)
            if widget is None:
                continue
            self._sync_reused_block_widget(
                widget,
                segment=segment,
                block_number=block_numbers.get(segment.uid, idx + 1),
                name_index_label=name_index_label,
            )
            self.blocks_layout.addWidget(widget)
            widget.show()
            self.block_widgets[segment.uid] = widget
            self._apply_block_visual_state(segment.uid, widget)
            if active_plugin_group_key is not None:
                members = plugin_group_members.setdefault(active_plugin_group_key, [])
                members.append(widget)
                if self._is_plugin_group_collapsed(active_plugin_group_key):
                    widget.hide()

            if (not actor_mode) and idx < segment_count - 1:
                next_segment = display_segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_widget = self._build_merge_connector_widget(
                        session,
                        segment,
                        next_segment,
                    )
                    self.blocks_layout.addWidget(connector_widget)
        self._update_plugin_group_header_counts(
            plugin_group_count_labels,
            plugin_group_members,
            plugin_group_description_hints,
        )
        self.blocks_layout.addStretch(1)
        for leftover in pool.values():
            leftover.deleteLater()

    def _clear_blocks(self, preserve_widgets: Optional[set[QWidget]] = None) -> None:
        self._cancel_pending_block_build()
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)
        preserve = preserve_widgets if preserve_widgets is not None else set()
        while self.blocks_layout.count():
            item = self.blocks_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if widget in preserve:
                    self.blocks_layout.removeWidget(widget)
                    widget.hide()
                    widget.setParent(None)
                    continue
                widget.deleteLater()
        if preserve_widgets is None:
            self.rendered_blocks_path = None
            self.rendered_block_uid_order = []
            self.rendered_block_view_meta = None

    def _cancel_pending_block_build(self) -> None:
        state = self._pending_render_state
        self._render_blocks_timer.stop()
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)
        if state is not None and "previous_v_scroll_policy" in state:
            self.scroll_area.setVerticalScrollBarPolicy(
                cast(Qt.ScrollBarPolicy, state["previous_v_scroll_policy"])
            )
            self.scroll_area.setHorizontalScrollBarPolicy(
                cast(Qt.ScrollBarPolicy, state.get(
                    "previous_h_scroll_policy", self._default_h_scroll_policy))
            )
        else:
            self.scroll_area.setVerticalScrollBarPolicy(
                self._default_v_scroll_policy)
            self.scroll_area.setHorizontalScrollBarPolicy(
                self._default_h_scroll_policy)
        if state is not None:
            reuse_pool_raw = state.get("reuse_pool")
            if isinstance(reuse_pool_raw, dict):
                reuse_pool = cast(dict[str, Any], reuse_pool_raw)
                for widget in reuse_pool.values():
                    if isinstance(widget, QWidget):
                        widget.deleteLater()
        self._pending_render_state = None
        self.scroll_area.setEnabled(True)

    def _precompute_merge_pairs(
        self,
        session: FileSession,
        translator_mode: bool,
    ) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        if translator_mode:
            # Translator mode merges are TL-only structural cleanup.
            for idx in range(len(session.segments) - 1):
                left_segment = session.segments[idx]
                right_segment = session.segments[idx + 1]
                if (not left_segment.is_structural_dialogue) or (not right_segment.is_structural_dialogue):
                    continue
                if not right_segment.translation_only:
                    continue
                if self._same_merge_signature(left_segment, right_segment):
                    pairs.add((left_segment.uid, right_segment.uid))
            return pairs
        for bundle in session.bundles:
            tokens = bundle.tokens
            for idx in range(len(tokens) - 1):
                left = tokens[idx]
                right = tokens[idx + 1]
                if left.kind != "dialogue" or right.kind != "dialogue":
                    continue
                left_segment = left.segment
                right_segment = right.segment
                if left_segment is None or right_segment is None:
                    continue
                if (not left_segment.is_structural_dialogue) or (not right_segment.is_structural_dialogue):
                    continue
                if self._same_merge_signature(left_segment, right_segment):
                    pairs.add((left_segment.uid, right_segment.uid))
        return pairs

    def _render_next_block_batch(self) -> None:
        # Block batching is disabled. Rendering now happens in one pass.
        self._cancel_pending_block_build()

    def _render_session(
        self,
        session: FileSession,
        focus_uid: Optional[str] = None,
        preserve_scroll: bool = False,
        start_at_top: bool = False,
    ) -> None:
        self._cancel_pending_block_build()
        previous_scroll_value = self.scroll_area.verticalScrollBar(
        ).value() if preserve_scroll else None
        if start_at_top and not preserve_scroll:
            self.scroll_area.verticalScrollBar().setValue(0)
        actor_mode_resolver = getattr(self, "_actor_mode_for_path", None)
        if callable(actor_mode_resolver):
            try:
                actor_mode = bool(actor_mode_resolver(session.path, session))
            except Exception:
                actor_mode = self._is_name_index_session(session)
        else:
            actor_mode = self._is_name_index_session(session)
        name_index_kind = self._name_index_kind(session) if actor_mode else ""
        name_index_label = self._name_index_label(session)
        translator_mode = self._is_translator_mode()
        all_display_segments = self._display_segments_for_session(
            session,
            translator_mode=translator_mode,
            actor_mode=actor_mode,
        )
        display_segments, pagination_state = self._paginate_segments_for_render(
            session,
            all_display_segments,
            actor_mode=actor_mode,
            focus_uid=focus_uid,
        )
        block_numbers = self._display_block_numbers(
            all_display_segments,
            actor_mode=actor_mode,
        )
        page_segment_uids = {segment.uid for segment in display_segments}
        self.current_segment_lookup = {
            segment.uid: segment for segment in all_display_segments}
        self._apply_pagination_render_state(pagination_state)
        view_meta = self._block_view_meta(
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
            current_page=int(pagination_state.get("current_page", 1)),
            total_pages=int(pagination_state.get("total_pages", 1)),
            page_size=int(pagination_state.get("page_size", 50)),
        )
        if translator_mode:
            cached_reference_map = self.reference_summary_cache_by_path.get(
                session.path)
            if cached_reference_map is None:
                cached_reference_map = self._build_reference_summary_for_session(
                    session)
                self.reference_summary_cache_by_path[session.path] = cached_reference_map
            self.current_reference_map = cached_reference_map
        else:
            self.current_reference_map = {}
        if self.selected_segment_uid and self.selected_segment_uid not in self.current_segment_lookup:
            self.selected_segment_uid = None
        if focus_uid and focus_uid in self.current_segment_lookup:
            self.selected_segment_uid = focus_uid
        elif (
            self.selected_segment_uid is not None
            and self.selected_segment_uid not in page_segment_uids
        ):
            self.selected_segment_uid = None
        self._sync_translator_mode_ui()
        source_dirty, tl_dirty = self._session_dirty_flags_cached(session)

        if actor_mode:
            entry_count = len(all_display_segments)
            entry_label = "entry" if entry_count == 1 else "entries"
            header = (
                f"{session.path.name} | {entry_count} "
                f"{name_index_label.lower()} {entry_label}"
            )
        else:
            block_count = self._display_block_count(
                all_display_segments,
                actor_mode=False,
            )
            block_label = "dialogue block" if block_count == 1 else "dialogue blocks"
            header = f"{session.path.name} | {block_count} {block_label}"
        total_pages = int(pagination_state.get("total_pages", 1))
        if total_pages > 1:
            header += (
                f" | Page {int(pagination_state.get('current_page', 1))}/{total_pages}"
            )
        if source_dirty and tl_dirty:
            header += " | UNSAVED SOURCE+TL"
        elif source_dirty:
            header += " | UNSAVED SOURCE"
        elif tl_dirty:
            header += " | UNSAVED TL"
        self.file_header_label.setText(header)
        self._update_reset_json_button(session)

        if self.rendered_blocks_path is not None and self.rendered_blocks_path != session.path:
            if self._try_restore_cached_block_container(
                session,
                display_segments,
                view_meta,
                focus_uid=focus_uid,
                preserve_scroll=preserve_scroll,
                previous_scroll_value=previous_scroll_value,
                start_at_top=start_at_top,
            ):
                return
            self._switch_to_new_active_blocks_container()

        if not display_segments:
            self._hide_audit_progress_overlay(
                self.main_render_progress_overlay)
            self._clear_blocks()
            self.block_widgets = {}
            self.rendered_blocks_path = None
            self.rendered_block_uid_order = []
            self.rendered_block_view_meta = None
            self.selected_segment_uid = None
            if actor_mode:
                label = QLabel(
                    f"No {name_index_label.lower()} entries found in this file."
                )
            else:
                label = QLabel(
                    "No dialogue/choice/script-message blocks found in this file.")
            self.blocks_layout.addWidget(label)
            self.blocks_layout.addStretch(1)
            self.scroll_area.setEnabled(True)
            self._refresh_translator_detail_panel()
            return

        if self._can_fast_refresh_session_widgets(
            session,
            display_segments,
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
        ):
            for idx, segment in enumerate(display_segments, start=1):
                widget = self.block_widgets.get(segment.uid)
                if widget is None:
                    continue
                self._sync_reused_block_widget(
                    widget,
                    segment=segment,
                    block_number=block_numbers.get(segment.uid, idx),
                    name_index_label=name_index_label,
                )
                self._apply_block_visual_state(segment.uid, widget)
            self.rendered_blocks_path = session.path
            self.rendered_block_uid_order = [
                segment.uid for segment in display_segments]
            self.rendered_block_view_meta = view_meta
            self._hide_audit_progress_overlay(
                self.main_render_progress_overlay)
            self._refresh_translator_detail_panel()
            self._schedule_dialogue_editor_visibility_update()
            target_widget = (
                self.block_widgets.get(focus_uid)
                if focus_uid and focus_uid in self.block_widgets
                else None
            )
            self._flash_pending_audit_target(focus_uid, target_widget)
            if preserve_scroll and previous_scroll_value is not None:
                def restore_scroll_and_focus_reused() -> None:
                    if target_widget is not None:
                        self._focus_target_widget(
                            target_widget,
                            preserve_scroll_value=previous_scroll_value,
                        )
                    else:
                        self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)

                QTimer.singleShot(0, restore_scroll_and_focus_reused)
                return
            if start_at_top and target_widget is None:
                QTimer.singleShot(
                    0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
                return
            if target_widget is not None:
                def focus_and_reveal_reused() -> None:
                    self._focus_target_widget(target_widget)

                QTimer.singleShot(0, focus_and_reveal_reused)
            return

        segment_count = len(display_segments)
        merge_pairs = (
            self._precompute_merge_pairs(session, translator_mode=translator_mode)
            if (not actor_mode)
            else set()
        )
        current_cache_widgets: set[QWidget] = set()
        if (
            self.rendered_blocks_path is not None
            and self.rendered_blocks_path != session.path
            and self.block_widgets
        ):
            current_cache_path = self.rendered_blocks_path
            self.cached_block_widgets_by_path[current_cache_path] = dict(
                self.block_widgets)
            self.cached_block_uid_order_by_path[current_cache_path] = list(
                self.rendered_block_uid_order
            )
            if self.rendered_block_view_meta is not None:
                self.cached_block_view_meta_by_path[current_cache_path] = self.rendered_block_view_meta
            current_cache_widgets = set(
                cast(list[QWidget], list(self.block_widgets.values())))

        cached_pool_raw = self.cached_block_widgets_by_path.pop(
            session.path, None)
        cached_uid_order = self.cached_block_uid_order_by_path.pop(
            session.path, [])
        cached_meta = self.cached_block_view_meta_by_path.pop(session.path, ())
        cached_pool: dict[str, BlockWidgetType] = (
            dict(cached_pool_raw) if isinstance(cached_pool_raw, dict) else {}
        )

        if cached_pool and self._can_restore_cached_widget_pool(
            display_segments,
            cached_pool,
            cached_uid_order,
            cast(tuple[Any, ...], cached_meta),
            view_meta,
        ):
            preserve_widgets: set[QWidget] = set(current_cache_widgets)
            preserve_widgets.update(
                cast(list[QWidget], list(cached_pool.values())))
            self.rendered_blocks_path = None
            self.rendered_block_uid_order = []
            self._clear_blocks(
                preserve_widgets=preserve_widgets if preserve_widgets else None
            )
            self._restore_cached_widget_pool(
                session,
                display_segments,
                cached_pool,
                block_numbers=block_numbers,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
                name_index_label=name_index_label,
                merge_pairs=merge_pairs,
            )
            self.rendered_blocks_path = session.path
            self.rendered_block_uid_order = [
                segment.uid for segment in display_segments]
            self.rendered_block_view_meta = view_meta
            self.scroll_area.setEnabled(True)
            self._hide_audit_progress_overlay(
                self.main_render_progress_overlay)
            self._refresh_translator_detail_panel()
            self._schedule_dialogue_editor_visibility_update()
            target_widget = (
                self.block_widgets.get(focus_uid)
                if focus_uid and focus_uid in self.block_widgets
                else None
            )
            self._flash_pending_audit_target(focus_uid, target_widget)
            if preserve_scroll and previous_scroll_value is not None:
                def restore_scroll_and_focus_cached() -> None:
                    if target_widget is not None:
                        self._focus_target_widget(
                            target_widget,
                            preserve_scroll_value=previous_scroll_value,
                        )
                    else:
                        self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)

                QTimer.singleShot(0, restore_scroll_and_focus_cached)
                return
            if start_at_top and target_widget is None:
                QTimer.singleShot(
                    0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
                return
            if target_widget is not None:
                def focus_and_reveal_cached() -> None:
                    self._focus_target_widget(target_widget)

                QTimer.singleShot(0, focus_and_reveal_cached)
            return

        reuse_pool: dict[str, BlockWidgetType] = {}
        if self.rendered_blocks_path is not None and self.rendered_blocks_path == session.path:
            reuse_pool = dict(self.block_widgets)
        elif cached_pool:
            reuse_pool = cached_pool
        self.rendered_blocks_path = None
        self.rendered_block_uid_order = []
        preserve_widget_set: set[QWidget] = set(current_cache_widgets)
        if reuse_pool:
            preserve_widget_set.update(
                cast(list[QWidget], list(reuse_pool.values())))
        self._clear_blocks(
            preserve_widgets=preserve_widget_set if preserve_widget_set else None
        )
        self.block_widgets = {}
        plugin_group_members: dict[str, list[QWidget]] = {}
        plugin_group_count_labels: dict[str, QLabel] = {}
        plugin_group_description_hints: dict[str, str] = {}
        active_plugin_group_key: Optional[str] = None

        target_widget: Optional[BlockWidgetType] = None
        for idx, segment in enumerate(display_segments):
            group_info = self._plugin_group_key_and_title_for_segment(
                session.path,
                segment,
            )
            if group_info is None:
                active_plugin_group_key = None
            else:
                group_key, group_title = group_info
                if group_key != active_plugin_group_key:
                    members = plugin_group_members.get(group_key)
                    if members is None:
                        members = []
                        plugin_group_members[group_key] = members
                    header_widget, count_label = self._build_plugin_group_header_widget(
                        group_key=group_key,
                        title=group_title,
                        member_widgets=members,
                    )
                    plugin_group_count_labels[group_key] = count_label
                    self.blocks_layout.addWidget(header_widget)
                active_plugin_group_key = group_key
                if group_key not in plugin_group_description_hints:
                    hint = self._plugin_group_description_hint_for_segment(
                        segment,
                        translator_mode=translator_mode,
                    )
                    if hint:
                        plugin_group_description_hints[group_key] = hint

            reused_widget = reuse_pool.pop(segment.uid, None)
            if (
                reused_widget is not None
                and self._can_reuse_block_widget(
                    reused_widget,
                    segment=segment,
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                    name_index_kind=name_index_kind,
                    name_index_label=name_index_label,
                )
            ):
                widget = reused_widget
                self._sync_reused_block_widget(
                    widget,
                    segment=segment,
                    block_number=block_numbers.get(segment.uid, idx + 1),
                    name_index_label=name_index_label,
                )
            else:
                if reused_widget is not None:
                    reused_widget.deleteLater()
                widget = self._create_block_widget(
                    segment=segment,
                    block_number=block_numbers.get(segment.uid, idx + 1),
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                    name_index_kind=name_index_kind,
                    name_index_label=name_index_label,
                )
            self.blocks_layout.addWidget(widget)
            widget.show()
            self.block_widgets[segment.uid] = widget
            self._apply_block_visual_state(segment.uid, widget)
            if focus_uid and focus_uid == segment.uid:
                target_widget = widget
            if active_plugin_group_key is not None:
                members = plugin_group_members.setdefault(active_plugin_group_key, [])
                members.append(widget)
                if self._is_plugin_group_collapsed(active_plugin_group_key):
                    widget.hide()

            if (not actor_mode) and idx < segment_count - 1:
                next_segment = display_segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_widget = self._build_merge_connector_widget(
                        session,
                        segment,
                        next_segment,
                    )
                    self.blocks_layout.addWidget(connector_widget)
        self._update_plugin_group_header_counts(
            plugin_group_count_labels,
            plugin_group_members,
            plugin_group_description_hints,
        )
        self.blocks_layout.addStretch(1)
        for leftover in reuse_pool.values():
            leftover.deleteLater()

        self.rendered_blocks_path = session.path
        self.rendered_block_uid_order = [
            segment.uid for segment in display_segments]
        self.rendered_block_view_meta = view_meta
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)
        self.scroll_area.setEnabled(True)
        self._refresh_translator_detail_panel()
        self._schedule_dialogue_editor_visibility_update()
        self._flash_pending_audit_target(focus_uid, target_widget)
        if preserve_scroll and previous_scroll_value is not None:
            def restore_scroll_and_focus_immediate() -> None:
                if target_widget is not None:
                    self._focus_target_widget(
                        target_widget,
                        preserve_scroll_value=previous_scroll_value,
                    )
                else:
                    self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)

            QTimer.singleShot(0, restore_scroll_and_focus_immediate)
            return
        if start_at_top and target_widget is None:
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
            return
        if target_widget is not None:
            def focus_and_reveal_immediate() -> None:
                self._focus_target_widget(target_widget)

            QTimer.singleShot(0, focus_and_reveal_immediate)
