from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core.models import DialogueSegment, FileSession
from ..ui.ui_components import DialogueBlockWidget, ItemNameDescriptionWidget

BlockWidgetType = DialogueBlockWidget | ItemNameDescriptionWidget


class _RenderHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class RenderMixin(_RenderHostTypingFallback):
    def _block_view_meta(
        self,
        *,
        translator_mode: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
    ) -> tuple[Any, ...]:
        return (
            translator_mode,
            actor_mode,
            name_index_kind,
            name_index_label,
            self.thin_width_spin.value(),
            self.wide_width_spin.value(),
            self.max_lines_spin.value(),
            bool(self.hide_control_codes_check.isChecked()),
            bool(self.infer_speaker_check.isChecked()),
        )

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
        target_uid_order = [segment.uid for segment in session.segments]
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
        self.block_widgets = cast(dict[str, BlockWidgetType], cached_block_widgets)
        self.rendered_blocks_path = session.path
        self.rendered_block_uid_order = target_uid_order
        self.rendered_block_view_meta = view_meta
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)
        self.scroll_area.setEnabled(True)
        self._refresh_translator_detail_panel()

        target_widget = (
            self.block_widgets.get(focus_uid)
            if focus_uid and focus_uid in self.block_widgets
            else None
        )
        if preserve_scroll and previous_scroll_value is not None:
            def restore_scroll_and_focus_cached_container() -> None:
                self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)
                if target_widget is not None:
                    target_widget.focus_editor()

            QTimer.singleShot(0, restore_scroll_and_focus_cached_container)
            return True
        if start_at_top and target_widget is None:
            QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
            return True
        if target_widget is not None:
            def focus_and_reveal_cached_container() -> None:
                target_widget.focus_editor()
                self.scroll_area.ensureWidgetVisible(target_widget, 20, 20)

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
        combined_fields_raw = getattr(segment, "name_index_combined_fields", ())
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
        widget.split_overflow_requested.connect(self._on_split_overflow_requested)

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
                translator_mode=translator_mode,
                name_index_label=name_index_label,
            )
        else:
            widget = DialogueBlockWidget(
                segment=segment,
                block_number=block_number,
                thin_width=self.thin_width_spin.value(),
                wide_width=self.wide_width_spin.value(),
                max_lines=self.max_lines_spin.value(),
                infer_name_from_first_line=self.infer_speaker_check.isChecked(),
                hide_control_codes_when_unfocused=self.hide_control_codes_check.isChecked(),
                hidden_control_line_transform=self._hidden_control_line_transform,
                hidden_control_colored_line_resolver=self._hidden_control_line_with_color_spans,
                speaker_display_resolver=self._resolve_speaker_display_name,
                speaker_display_html_resolver=self._render_text_with_color_codes_html,
                hint_display_html_resolver=self._render_text_with_color_codes_html_muted,
                color_code_resolver=self._color_for_rpgm_code,
                speaker_tint_color=self._speaker_color_for_segment(segment),
                translator_mode=translator_mode,
                actor_mode=actor_mode,
                name_index_kind=name_index_kind,
                name_index_label=name_index_label,
                allow_structural_actions=(not translator_mode) and (not actor_mode),
            )
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
        expected_is_name_desc = self._is_name_desc_combined_segment(actor_mode, segment)
        if expected_is_name_desc:
            if not isinstance(widget, ItemNameDescriptionWidget):
                return False
            return (
                bool(widget.translator_mode) == bool(translator_mode)
                and str(widget.name_index_label).strip() == clean_label
            )

        if not isinstance(widget, DialogueBlockWidget):
            return False
        return (
            bool(widget.translator_mode) == bool(translator_mode)
            and bool(widget.actor_mode) == bool(actor_mode)
            and str(widget.name_index_kind).strip().lower() == name_index_kind
            and str(widget.name_index_label).strip() == clean_label
            and int(widget.thin_width) == int(self.thin_width_spin.value())
            and int(widget.wide_width) == int(self.wide_width_spin.value())
            and int(widget.max_lines) == int(self.max_lines_spin.value())
            and bool(widget.infer_name_from_first_line) == bool(self.infer_speaker_check.isChecked())
            and bool(widget.allow_structural_actions) == ((not translator_mode) and (not actor_mode))
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
        source_lines = segment.source_lines or segment.original_lines or segment.lines or [""]
        name_lines, desc_lines = widget._split_combined_lines(list(edited_lines))
        source_name_lines, source_desc_lines = widget._split_combined_lines(list(source_lines))
        widget._raw_name_lines = list(name_lines)
        widget._raw_desc_lines = list(desc_lines)
        widget._source_name_text = "\n".join(source_name_lines).strip()
        widget._source_desc_text = "\n".join(source_desc_lines).strip()
        widget.context_label.setText(segment.context)
        widget.set_hide_control_codes_when_unfocused(self.hide_control_codes_check.isChecked())
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
        widget.speaker_tint_color = self._speaker_color_for_segment(segment)
        widget._actor_id = widget._actor_id_from_uid()
        widget._name_index_field = widget._name_index_field_from_uid()
        edited_lines = segment.translation_lines if widget.translator_mode else segment.lines
        if not edited_lines:
            edited_lines = [""]
        widget._raw_lines = list(edited_lines)
        if widget.translator_mode:
            source_lines = segment.source_lines or segment.original_lines or segment.lines or [""]
            widget._source_hint_lines = list(source_lines)
        widget.context_label.setText(segment.context)
        widget._apply_editor_width()
        widget.set_hide_control_codes_when_unfocused(self.hide_control_codes_check.isChecked())
        widget._sync_control_code_visibility(force=True)
        widget.refresh_metadata()

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
        translator_mode: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
    ) -> bool:
        if self.rendered_blocks_path is None or self.rendered_blocks_path != session.path:
            return False
        if self.rendered_block_uid_order != [segment.uid for segment in session.segments]:
            return False
        if len(self.block_widgets) != len(session.segments):
            return False
        for segment in session.segments:
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
        session: FileSession,
        pool: dict[str, BlockWidgetType],
        cached_uid_order: list[str],
        cached_meta: tuple[Any, ...],
        target_meta: tuple[Any, ...],
    ) -> bool:
        if cached_meta != target_meta:
            return False
        target_uid_order = [segment.uid for segment in session.segments]
        if cached_uid_order != target_uid_order:
            return False
        return len(pool) == len(target_uid_order)

    def _restore_cached_widget_pool(
        self,
        session: FileSession,
        pool: dict[str, BlockWidgetType],
        *,
        translator_mode: bool,
        actor_mode: bool,
        name_index_label: str,
        merge_pairs: set[tuple[str, str]],
    ) -> None:
        self.block_widgets = {}
        segment_count = len(session.segments)
        for idx, segment in enumerate(session.segments):
            widget = pool.pop(segment.uid, None)
            if widget is None:
                continue
            self.blocks_layout.addWidget(widget)
            widget.show()
            self.block_widgets[segment.uid] = widget

            if (not translator_mode) and (not actor_mode) and idx < segment_count - 1:
                next_segment = session.segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_widget = self._build_merge_connector_widget(
                        session,
                        segment,
                        next_segment,
                    )
                    self.blocks_layout.addWidget(connector_widget)
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
                cast(Qt.ScrollBarPolicy, state.get("previous_h_scroll_policy", self._default_h_scroll_policy))
            )
        else:
            self.scroll_area.setVerticalScrollBarPolicy(self._default_v_scroll_policy)
            self.scroll_area.setHorizontalScrollBarPolicy(self._default_h_scroll_policy)
        if state is not None:
            reuse_pool_raw = state.get("reuse_pool")
            if isinstance(reuse_pool_raw, dict):
                for widget in reuse_pool_raw.values():
                    if isinstance(widget, QWidget):
                        widget.deleteLater()
        self._pending_render_state = None
        self.scroll_area.setEnabled(True)

    def _precompute_merge_pairs(self, session: FileSession) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
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
                if self._same_merge_signature(left_segment, right_segment):
                    pairs.add((left_segment.uid, right_segment.uid))
        return pairs

    def _estimated_block_placeholder_height(self, actor_mode: bool, translator_mode: bool) -> int:
        editor_height = max(130, 18 * (self.max_lines_spin.value() + 2))
        if actor_mode:
            chrome = 140
        elif translator_mode:
            chrome = 180
        else:
            chrome = 195
        return editor_height + chrome

    def _new_height_placeholder(self, height: int) -> QWidget:
        placeholder = QWidget()
        placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        placeholder.setMinimumHeight(height)
        placeholder.setMaximumHeight(height)
        return placeholder

    def _render_next_block_batch(self) -> None:
        state = self._pending_render_state
        if state is None:
            return

        session = cast(FileSession, state["session"])
        session_path = cast(Path, state["session_path"])
        current_session = self.sessions.get(session_path)
        if current_session is None or current_session is not session:
            self._cancel_pending_block_build()
            return
        if self.current_path != session_path:
            self._cancel_pending_block_build()
            return

        segment_count = cast(int, state["segment_count"])
        start_idx = cast(int, state["index"])
        end_idx = min(segment_count, start_idx + self._render_batch_size)
        segments = cast(list[DialogueSegment], state["segments"])
        translator_mode = bool(state["translator_mode"])
        actor_mode = bool(state["actor_mode"])
        name_index_kind = cast(str, state.get("name_index_kind", ""))
        name_index_label = cast(str, state.get("name_index_label", "Entry"))
        merge_pairs = cast(set[tuple[str, str]], state["merge_pairs"])
        block_placeholders = cast(list[QWidget], state["block_placeholders"])
        connector_placeholders = cast(dict[int, QWidget], state["connector_placeholders"])
        reuse_pool = cast(dict[str, BlockWidgetType], state.get("reuse_pool", {}))
        focus_uid = cast(Optional[str], state["focus_uid"])

        for idx in range(start_idx, end_idx):
            segment = segments[idx]
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
                    block_number=idx + 1,
                    name_index_label=name_index_label,
                )
            else:
                if reused_widget is not None:
                    reused_widget.deleteLater()
                widget = self._create_block_widget(
                    segment=segment,
                    block_number=idx + 1,
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                    name_index_kind=name_index_kind,
                    name_index_label=name_index_label,
                )
            placeholder = block_placeholders[idx] if idx < len(block_placeholders) else None
            placeholder_index = (
                self.blocks_layout.indexOf(placeholder)
                if placeholder is not None
                else -1
            )
            insert_index = (
                placeholder_index
                if placeholder_index >= 0
                else max(0, self.blocks_layout.count() - 1)
            )
            self.blocks_layout.insertWidget(insert_index, widget)
            widget.show()
            if placeholder is not None:
                self.blocks_layout.removeWidget(placeholder)
                placeholder.deleteLater()
            self.block_widgets[segment.uid] = widget

            if focus_uid and focus_uid == segment.uid:
                state["target_widget"] = widget

            if (not translator_mode) and (not actor_mode) and idx < segment_count - 1:
                next_segment = segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_placeholder = connector_placeholders.get(idx)
                    connector_index = (
                        self.blocks_layout.indexOf(connector_placeholder)
                        if connector_placeholder is not None
                        else -1
                    )
                    insert_index = (
                        connector_index
                        if connector_index >= 0
                        else max(0, self.blocks_layout.count() - 1)
                    )
                    connector_widget = self._build_merge_connector_widget(
                        session,
                        segment,
                        next_segment,
                    )
                    self.blocks_layout.insertWidget(insert_index, connector_widget)
                    if connector_placeholder is not None:
                        self.blocks_layout.removeWidget(connector_placeholder)
                        connector_placeholder.deleteLater()

        state["index"] = end_idx
        if end_idx < segment_count:
            self._set_audit_progress_overlay(
                self.scroll_area,
                self.main_render_progress_overlay,
                f"Rendering {end_idx}/{segment_count}",
            )
            self._render_blocks_timer.start(1)
            return

        preserve_scroll = bool(state["preserve_scroll"])
        previous_scroll_value = cast(Optional[int], state["previous_scroll_value"])
        start_at_top = bool(state.get("start_at_top", False))
        target_widget = cast(Optional[BlockWidgetType], state.get("target_widget"))
        self.rendered_blocks_path = session_path
        self.rendered_block_uid_order = [segment.uid for segment in segments]
        self.rendered_block_view_meta = cast(
            Optional[tuple[Any, ...]],
            state.get("view_meta"),
        )
        self._cancel_pending_block_build()
        self._refresh_translator_detail_panel()

        if preserve_scroll and previous_scroll_value is not None:
            def restore_scroll_and_focus() -> None:
                self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)
                if target_widget is not None:
                    target_widget.focus_editor()

            QTimer.singleShot(0, restore_scroll_and_focus)
            return

        if start_at_top and target_widget is None:
            QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
            return

        if target_widget is not None:
            def focus_and_reveal() -> None:
                target_widget.focus_editor()
                self.scroll_area.ensureWidgetVisible(target_widget, 20, 20)

            QTimer.singleShot(0, focus_and_reveal)

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
        self.current_segment_lookup = {
            segment.uid: segment for segment in session.segments}
        actor_mode = self._is_name_index_session(session)
        name_index_kind = self._name_index_kind(session) if actor_mode else ""
        name_index_label = self._name_index_label(session)
        translator_mode = self._is_translator_mode()
        view_meta = self._block_view_meta(
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
        )
        if translator_mode:
            cached_reference_map = self.reference_summary_cache_by_path.get(session.path)
            if cached_reference_map is None:
                cached_reference_map = self._build_reference_summary_for_session(session)
                self.reference_summary_cache_by_path[session.path] = cached_reference_map
            self.current_reference_map = cached_reference_map
        else:
            self.current_reference_map = {}
        if self.selected_segment_uid and self.selected_segment_uid not in self.current_segment_lookup:
            self.selected_segment_uid = None
        if focus_uid and focus_uid in self.current_segment_lookup:
            self.selected_segment_uid = focus_uid
        self._sync_translator_mode_ui()
        source_dirty, tl_dirty = self._session_dirty_flags_cached(session)

        if actor_mode:
            header = (
                f"{session.path.name} | {len(session.segments)} "
                f"{name_index_label.lower()} entry(ies)"
            )
        else:
            header = f"{session.path.name} | {len(session.segments)} dialogue block(s)"
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
                view_meta,
                focus_uid=focus_uid,
                preserve_scroll=preserve_scroll,
                previous_scroll_value=previous_scroll_value,
                start_at_top=start_at_top,
            ):
                return
            self._switch_to_new_active_blocks_container()

        if not session.segments:
            self._hide_audit_progress_overlay(self.main_render_progress_overlay)
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
                label = QLabel("No code 101 dialogue blocks found in this file.")
            self.blocks_layout.addWidget(label)
            self.blocks_layout.addStretch(1)
            self.scroll_area.setEnabled(True)
            self._refresh_translator_detail_panel()
            return

        if self._can_fast_refresh_session_widgets(
            session,
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
        ):
            for idx, segment in enumerate(session.segments, start=1):
                widget = self.block_widgets.get(segment.uid)
                if widget is None:
                    continue
                self._sync_reused_block_widget(
                    widget,
                    segment=segment,
                    block_number=idx,
                    name_index_label=name_index_label,
                )
            self.rendered_blocks_path = session.path
            self.rendered_block_uid_order = [segment.uid for segment in session.segments]
            self.rendered_block_view_meta = view_meta
            self._hide_audit_progress_overlay(self.main_render_progress_overlay)
            self._refresh_translator_detail_panel()
            target_widget = (
                self.block_widgets.get(focus_uid)
                if focus_uid and focus_uid in self.block_widgets
                else None
            )
            if preserve_scroll and previous_scroll_value is not None:
                def restore_scroll_and_focus_reused() -> None:
                    self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)
                    if target_widget is not None:
                        target_widget.focus_editor()

                QTimer.singleShot(0, restore_scroll_and_focus_reused)
                return
            if start_at_top and target_widget is None:
                QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
                return
            if target_widget is not None:
                def focus_and_reveal_reused() -> None:
                    target_widget.focus_editor()
                    self.scroll_area.ensureWidgetVisible(target_widget, 20, 20)

                QTimer.singleShot(0, focus_and_reveal_reused)
            return

        segment_count = len(session.segments)
        merge_pairs = (
            self._precompute_merge_pairs(session)
            if (not translator_mode) and (not actor_mode)
            else set()
        )
        current_cache_widgets: set[QWidget] = set()
        if (
            self.rendered_blocks_path is not None
            and self.rendered_blocks_path != session.path
            and self.block_widgets
        ):
            current_cache_path = self.rendered_blocks_path
            self.cached_block_widgets_by_path[current_cache_path] = dict(self.block_widgets)
            self.cached_block_uid_order_by_path[current_cache_path] = list(
                self.rendered_block_uid_order
            )
            if self.rendered_block_view_meta is not None:
                self.cached_block_view_meta_by_path[current_cache_path] = self.rendered_block_view_meta
            current_cache_widgets = set(cast(list[QWidget], list(self.block_widgets.values())))

        cached_pool_raw = self.cached_block_widgets_by_path.pop(session.path, None)
        cached_uid_order = self.cached_block_uid_order_by_path.pop(session.path, [])
        cached_meta = self.cached_block_view_meta_by_path.pop(session.path, ())
        cached_pool: dict[str, BlockWidgetType] = (
            dict(cached_pool_raw) if isinstance(cached_pool_raw, dict) else {}
        )

        if cached_pool and self._can_restore_cached_widget_pool(
            session,
            cached_pool,
            cached_uid_order,
            cast(tuple[Any, ...], cached_meta),
            view_meta,
        ):
            preserve_widgets: set[QWidget] = set(current_cache_widgets)
            preserve_widgets.update(cast(list[QWidget], list(cached_pool.values())))
            self.rendered_blocks_path = None
            self.rendered_block_uid_order = []
            self._clear_blocks(
                preserve_widgets=preserve_widgets if preserve_widgets else None
            )
            self._restore_cached_widget_pool(
                session,
                cached_pool,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
                name_index_label=name_index_label,
                merge_pairs=merge_pairs,
            )
            self.rendered_blocks_path = session.path
            self.rendered_block_uid_order = [segment.uid for segment in session.segments]
            self.rendered_block_view_meta = view_meta
            self.scroll_area.setEnabled(True)
            self._hide_audit_progress_overlay(self.main_render_progress_overlay)
            self._refresh_translator_detail_panel()
            target_widget = (
                self.block_widgets.get(focus_uid)
                if focus_uid and focus_uid in self.block_widgets
                else None
            )
            if preserve_scroll and previous_scroll_value is not None:
                def restore_scroll_and_focus_cached() -> None:
                    self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)
                    if target_widget is not None:
                        target_widget.focus_editor()

                QTimer.singleShot(0, restore_scroll_and_focus_cached)
                return
            if start_at_top and target_widget is None:
                QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(0))
                return
            if target_widget is not None:
                def focus_and_reveal_cached() -> None:
                    target_widget.focus_editor()
                    self.scroll_area.ensureWidgetVisible(target_widget, 20, 20)

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
            preserve_widget_set.update(cast(list[QWidget], list(reuse_pool.values())))
        self._clear_blocks(
            preserve_widgets=preserve_widget_set if preserve_widget_set else None
        )
        self.block_widgets = {}

        block_placeholder_height = self._estimated_block_placeholder_height(
            actor_mode=actor_mode,
            translator_mode=translator_mode,
        )
        connector_placeholder_height = 30
        block_placeholders: list[QWidget] = []
        connector_placeholders: dict[int, QWidget] = {}
        for idx, segment in enumerate(session.segments):
            _ = segment
            block_placeholder = self._new_height_placeholder(block_placeholder_height)
            self.blocks_layout.addWidget(block_placeholder)
            block_placeholders.append(block_placeholder)
            if idx < segment_count - 1:
                next_segment = session.segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_placeholder = self._new_height_placeholder(
                        connector_placeholder_height
                    )
                    self.blocks_layout.addWidget(connector_placeholder)
                    connector_placeholders[idx] = connector_placeholder

        previous_v_scroll_policy = self.scroll_area.verticalScrollBarPolicy()
        previous_h_scroll_policy = self.scroll_area.horizontalScrollBarPolicy()
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.blocks_layout.addStretch(1)
        self.scroll_area.setEnabled(False)
        self._pending_render_state = {
            "session": session,
            "session_path": session.path,
            "segments": session.segments,
            "segment_count": segment_count,
            "index": 0,
            "translator_mode": translator_mode,
            "actor_mode": actor_mode,
            "name_index_kind": name_index_kind,
            "name_index_label": name_index_label,
            "merge_pairs": merge_pairs,
            "block_placeholders": block_placeholders,
            "connector_placeholders": connector_placeholders,
            "focus_uid": focus_uid,
            "preserve_scroll": preserve_scroll,
            "previous_scroll_value": previous_scroll_value,
            "start_at_top": start_at_top,
            "previous_v_scroll_policy": previous_v_scroll_policy,
            "previous_h_scroll_policy": previous_h_scroll_policy,
            "target_widget": None,
            "reuse_pool": reuse_pool,
            "view_meta": view_meta,
        }
        self._set_audit_progress_overlay(
            self.scroll_area,
            self.main_render_progress_overlay,
            f"Rendering 0/{segment_count}",
        )
        self._render_blocks_timer.start(0)



