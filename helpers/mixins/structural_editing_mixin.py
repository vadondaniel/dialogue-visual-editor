from __future__ import annotations

from concurrent.futures import Future
import copy
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.models import (
    CommandBundle,
    CommandToken,
    DeletedBlockAction,
    DialogueSegment,
    FileSession,
    InsertedBlockAction,
    MergeBlocksAction,
    NO_SPEAKER_KEY,
    ResetBlockAction,
    SplitOverflowAction,
    StructuralAction,
)
from ..core.text_utils import (
    smart_collapse_lines,
    split_lines_by_row_budget,
    total_display_rows,
)

class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class StructuralEditingMixin(_EditorHostTypingFallback):
    _COLOR_CODE_RE = re.compile(r"\\[Cc]\[(\d+)\]")
    _COLOR_CODE_AT_LINE_START_RE = re.compile(r"^\s*\\[Cc]\[(\d+)\]")
    _TRAILING_RESET_COLOR_RE = re.compile(r"\\[Cc]\[0\]\s*$")

    def _refresh_after_text_reset_without_full_rerender(
        self,
        session: FileSession,
        *,
        uid: str,
    ) -> bool:
        if self.current_path != session.path:
            return False
        if self._pending_render_state is not None:
            return False
        if self.rendered_blocks_path != session.path:
            return False
        if self._is_name_index_session(session):
            return False

        segment = self.current_segment_lookup.get(uid)
        if segment is None:
            return False
        widget = self.block_widgets.get(uid)
        if widget is None:
            return False

        block_number_raw = getattr(widget, "block_number", None)
        if isinstance(block_number_raw, int) and (not isinstance(block_number_raw, bool)) and block_number_raw > 0:
            block_number = block_number_raw
        else:
            try:
                block_number = self.rendered_block_uid_order.index(uid) + 1
            except ValueError:
                block_number = 1

        self._sync_reused_block_widget(
            widget,
            segment=segment,
            block_number=block_number,
            name_index_label=self._name_index_label(session),
        )
        self._apply_block_visual_state(uid, widget)

        if self._is_translator_mode():
            refreshed_reference_map = self._build_reference_summary_for_session(
                session
            )
            self.reference_summary_cache_by_path[session.path] = refreshed_reference_map
            self.current_reference_map = refreshed_reference_map
        else:
            self.current_reference_map = {}

        self._refresh_translator_detail_panel()
        return True

    def _smart_collapse_target_sessions(
        self,
        apply_all_files: bool,
    ) -> list[FileSession]:
        if apply_all_files:
            return list(self.sessions.values())
        if self.current_path is None:
            return []
        current_session = self.sessions.get(self.current_path)
        if current_session is None:
            return []
        return [current_session]

    def _count_projected_smart_collapse_changes(
        self,
        *,
        allow_comma_endings: bool,
        allow_colon_triplet_endings: bool,
        ellipsis_lowercase_rule: bool,
        collapse_if_no_punctuation: bool,
        min_soft_ratio: float,
        apply_all_files: bool,
        infer_speaker_enabled: Optional[bool] = None,
        thin_width_limit: Optional[int] = None,
        wide_width_limit: Optional[int] = None,
    ) -> tuple[int, int]:
        target_sessions = self._smart_collapse_target_sessions(apply_all_files)
        if not target_sessions:
            return 0, 0

        translator_mode = self._is_translator_mode()
        use_infer_speaker = (
            bool(self.infer_speaker_check.isChecked())
            if infer_speaker_enabled is None
            else bool(infer_speaker_enabled)
        )
        thin_spin = getattr(self, "thin_width_spin", None)
        wide_spin = getattr(self, "wide_width_spin", None)
        thin_default = (
            int(thin_spin.value())
            if thin_spin is not None and hasattr(thin_spin, "value")
            else 42
        )
        wide_default = (
            int(wide_spin.value())
            if wide_spin is not None and hasattr(wide_spin, "value")
            else 48
        )
        thin_limit = (
            thin_default
            if thin_width_limit is None
            else int(thin_width_limit)
        )
        wide_limit = (
            wide_default
            if wide_width_limit is None
            else int(wide_width_limit)
        )
        projected_blocks = 0
        projected_files = 0
        for session in target_sessions:
            if self._is_name_index_session(session):
                continue
            session_will_change = False
            for segment in session.segments:
                if not self._is_smart_collapse_eligible_segment(segment):
                    continue
                line_width = thin_limit if segment.has_face else wide_limit
                if translator_mode:
                    current_lines = self._normalize_translation_lines(
                        segment.translation_lines
                    )
                    collapsed_lines = self._collapsed_translation_lines_for_segment(
                        segment,
                        allow_comma_endings=allow_comma_endings,
                        allow_colon_triplet_endings=allow_colon_triplet_endings,
                        ellipsis_lowercase_rule=ellipsis_lowercase_rule,
                        collapse_if_no_punctuation=collapse_if_no_punctuation,
                        min_soft_ratio=min_soft_ratio,
                        infer_speaker_enabled=use_infer_speaker,
                        line_width=line_width,
                    )
                else:
                    current_lines = list(segment.lines) if segment.lines else [""]
                    collapsed_lines = self._collapsed_source_lines_for_segment(
                        segment,
                        allow_comma_endings=allow_comma_endings,
                        allow_colon_triplet_endings=allow_colon_triplet_endings,
                        ellipsis_lowercase_rule=ellipsis_lowercase_rule,
                        collapse_if_no_punctuation=collapse_if_no_punctuation,
                        min_soft_ratio=min_soft_ratio,
                        infer_speaker_enabled=use_infer_speaker,
                        line_width=line_width,
                    )
                if collapsed_lines == current_lines:
                    continue
                projected_blocks += 1
                session_will_change = True
            if session_will_change:
                projected_files += 1
        return projected_blocks, projected_files

    def _prompt_smart_collapse_all_options(
        self,
    ) -> Optional[tuple[bool, bool, bool, bool, float, bool]]:
        dialog = QDialog(cast(QWidget, self))
        dialog.setWindowTitle("Smart Collapse All")
        dialog.resize(420, 220)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)

        soft_rule_check = QCheckBox(
            "Collapse if previous line is shorter than threshold"
        )
        soft_rule_check.setChecked(
            bool(getattr(self, "smart_collapse_soft_ratio_rule_enabled", True))
        )
        form.addRow(soft_rule_check)

        allow_comma_check = QCheckBox(
            "Collapse if previous line ends with comma (, 、 ，)"
        )
        allow_comma_check.setChecked(
            bool(getattr(self, "smart_collapse_allow_comma_endings", False))
        )
        form.addRow(allow_comma_check)

        allow_colon_triplet_check = QCheckBox(
            "Collapse if previous line ends with ..."
        )
        allow_colon_triplet_check.setChecked(
            bool(getattr(self, "smart_collapse_allow_colon_triplet_endings", False))
        )
        form.addRow(allow_colon_triplet_check)

        ellipsis_lowercase_rule_check = QCheckBox(
            "Collapse if previous line ends with ... and next starts lowercase"
        )
        ellipsis_lowercase_rule_check.setChecked(
            bool(getattr(self, "smart_collapse_ellipsis_lowercase_rule", False))
        )
        form.addRow(ellipsis_lowercase_rule_check)

        no_punctuation_check = QCheckBox(
            "Collapse if previous line ends without punctuation"
        )
        no_punctuation_check.setChecked(
            bool(getattr(self, "smart_collapse_collapse_if_no_punctuation", True))
        )
        form.addRow(no_punctuation_check)

        threshold_spin = QSpinBox(dialog)
        threshold_spin.setRange(0, 100)
        threshold_spin.setSuffix("%")
        threshold_spin.setValue(
            int(getattr(self, "smart_collapse_soft_ratio_percent", 50))
        )
        threshold_spin.setEnabled(soft_rule_check.isChecked())
        soft_rule_check.toggled.connect(threshold_spin.setEnabled)
        form.addRow("Length threshold for collapse-if-short", threshold_spin)

        scope_all_files_check = QCheckBox("Apply to all dialogue files")
        scope_all_files_check.setChecked(False)
        form.addRow(scope_all_files_check)
        projected_count_label = QLabel("")
        projected_count_label.setWordWrap(True)
        form.addRow("Projected fixes", projected_count_label)

        projection_timer = QTimer(dialog)
        projection_timer.setSingleShot(True)
        projection_timer.setInterval(80)
        projection_poll_timer = QTimer(dialog)
        projection_poll_timer.setSingleShot(True)
        projection_poll_timer.setInterval(24)
        projection_executor = getattr(self, "audit_worker_executor", None)
        projection_future: Optional[Future[tuple[int, int]]] = None
        projection_future_request_id = 0
        pending_projection_request: Optional[dict[str, Any]] = None
        pending_projection_request_id = 0
        latest_projection_request_id = 0

        def _current_min_soft_ratio() -> float:
            if not bool(soft_rule_check.isChecked()):
                return 0.0
            return max(0.0, min(1.0, float(int(threshold_spin.value())) / 100.0))

        def _set_projected_count_label_result(
            projected_blocks: int,
            projected_files: int,
        ) -> None:
            block_label = "block" if projected_blocks == 1 else "blocks"
            file_label = "file" if projected_files == 1 else "files"
            projected_count_label.setText(
                f"{projected_blocks} {block_label} in {projected_files} {file_label}"
            )

        def _set_projected_count_label_calculating() -> None:
            projected_count_label.setText("calculating...")

        def _build_projection_request() -> dict[str, Any]:
            return {
                "allow_comma_endings": bool(allow_comma_check.isChecked()),
                "allow_colon_triplet_endings": bool(
                    allow_colon_triplet_check.isChecked()
                ),
                "ellipsis_lowercase_rule": bool(
                    ellipsis_lowercase_rule_check.isChecked()
                ),
                "collapse_if_no_punctuation": bool(no_punctuation_check.isChecked()),
                "min_soft_ratio": _current_min_soft_ratio(),
                "apply_all_files": bool(scope_all_files_check.isChecked()),
                "infer_speaker_enabled": bool(self.infer_speaker_check.isChecked()),
                "thin_width_limit": int(self.thin_width_spin.value()),
                "wide_width_limit": int(self.wide_width_spin.value()),
            }

        def _compute_projection_request(
            request: dict[str, Any],
        ) -> tuple[int, int]:
            return self._count_projected_smart_collapse_changes(
                allow_comma_endings=bool(request["allow_comma_endings"]),
                allow_colon_triplet_endings=bool(
                    request["allow_colon_triplet_endings"]
                ),
                ellipsis_lowercase_rule=bool(request["ellipsis_lowercase_rule"]),
                collapse_if_no_punctuation=bool(
                    request["collapse_if_no_punctuation"]
                ),
                min_soft_ratio=float(request["min_soft_ratio"]),
                apply_all_files=bool(request["apply_all_files"]),
                infer_speaker_enabled=bool(request["infer_speaker_enabled"]),
                thin_width_limit=int(request["thin_width_limit"]),
                wide_width_limit=int(request["wide_width_limit"]),
            )

        def _start_projection_request(
            request: dict[str, Any],
            request_id: int,
        ) -> None:
            nonlocal projection_future, projection_future_request_id
            projection_submit = getattr(projection_executor, "submit", None)
            if callable(projection_submit):
                try:
                    projection_future = cast(
                        Future[tuple[int, int]],
                        projection_submit(
                            _compute_projection_request,
                            request,
                        ),
                    )
                except Exception:
                    projection_future = None
                else:
                    projection_future_request_id = request_id
                    projection_poll_timer.start()
                    return
            projected_blocks, projected_files = _compute_projection_request(request)
            if request_id == latest_projection_request_id:
                _set_projected_count_label_result(
                    projected_blocks,
                    projected_files,
                )

        def _poll_projection_future() -> None:
            nonlocal projection_future, pending_projection_request, pending_projection_request_id
            current_future = projection_future
            if current_future is None:
                return
            if not current_future.done():
                projection_poll_timer.start()
                return
            projection_future = None
            completed_request_id = projection_future_request_id
            try:
                projected_blocks, projected_files = current_future.result()
            except Exception:
                projected_blocks, projected_files = 0, 0
            if completed_request_id == latest_projection_request_id:
                _set_projected_count_label_result(
                    projected_blocks,
                    projected_files,
                )
            if pending_projection_request is None:
                return
            next_request = pending_projection_request
            next_request_id = pending_projection_request_id
            pending_projection_request = None
            pending_projection_request_id = 0
            _start_projection_request(next_request, next_request_id)

        projection_poll_timer.timeout.connect(_poll_projection_future)

        def _dispatch_projected_count_refresh() -> None:
            nonlocal latest_projection_request_id, pending_projection_request, pending_projection_request_id
            latest_projection_request_id += 1
            request_id = latest_projection_request_id
            request = _build_projection_request()
            _set_projected_count_label_calculating()
            if projection_future is not None:
                pending_projection_request = request
                pending_projection_request_id = request_id
                return
            _start_projection_request(request, request_id)

        projection_timer.timeout.connect(_dispatch_projected_count_refresh)

        def _schedule_projected_count_refresh() -> None:
            _set_projected_count_label_calculating()
            projection_timer.start()

        soft_rule_check.toggled.connect(_schedule_projected_count_refresh)
        allow_comma_check.toggled.connect(_schedule_projected_count_refresh)
        allow_colon_triplet_check.toggled.connect(_schedule_projected_count_refresh)
        ellipsis_lowercase_rule_check.toggled.connect(
            _schedule_projected_count_refresh
        )
        no_punctuation_check.toggled.connect(_schedule_projected_count_refresh)
        scope_all_files_check.toggled.connect(_schedule_projected_count_refresh)
        threshold_spin.valueChanged.connect(_schedule_projected_count_refresh)

        def _cancel_projection_refresh() -> None:
            nonlocal latest_projection_request_id, pending_projection_request, pending_projection_request_id
            latest_projection_request_id += 1
            pending_projection_request = None
            pending_projection_request_id = 0
            projection_timer.stop()
            projection_poll_timer.stop()

        dialog.finished.connect(lambda _result: _cancel_projection_refresh())
        _schedule_projected_count_refresh()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return None

        allow_comma_endings = bool(allow_comma_check.isChecked())
        allow_colon_triplet_endings = bool(allow_colon_triplet_check.isChecked())
        ellipsis_lowercase_rule = bool(ellipsis_lowercase_rule_check.isChecked())
        collapse_if_no_punctuation = bool(no_punctuation_check.isChecked())
        min_soft_ratio = (
            float(int(threshold_spin.value())) / 100.0
            if bool(soft_rule_check.isChecked())
            else 0.0
        )
        return (
            allow_comma_endings,
            allow_colon_triplet_endings,
            ellipsis_lowercase_rule,
            collapse_if_no_punctuation,
            max(0.0, min(1.0, min_soft_ratio)),
            bool(scope_all_files_check.isChecked()),
        )

    def _is_smart_collapse_eligible_segment(self, segment: DialogueSegment) -> bool:
        if not segment.is_structural_dialogue:
            return False
        return segment.segment_kind in {"dialogue", "script_message", "tyrano_dialogue"}

    def _collapsed_source_lines_for_segment(
        self,
        segment: DialogueSegment,
        *,
        allow_comma_endings: bool,
        allow_colon_triplet_endings: bool,
        ellipsis_lowercase_rule: bool,
        collapse_if_no_punctuation: bool,
        min_soft_ratio: float,
        infer_speaker_enabled: Optional[bool] = None,
        line_width: Optional[int] = None,
    ) -> list[str]:
        current_lines = list(segment.lines) if segment.lines else [""]
        infer_enabled = (
            bool(self.infer_speaker_check.isChecked())
            if infer_speaker_enabled is None
            else bool(infer_speaker_enabled)
        )
        line_width_limit = (
            self._segment_line_width(segment)
            if line_width is None
            else int(line_width)
        )
        try:
            has_inferred_speaker = bool(
                self._segment_has_inferred_line1_speaker(
                    segment,
                    infer_speaker_enabled=infer_enabled,
                )
            )
        except TypeError:
            has_inferred_speaker = bool(
                self._segment_has_inferred_line1_speaker(segment)
            )
        if has_inferred_speaker:
            editable_lines = list(current_lines[1:]) if len(current_lines) > 1 else [""]
        else:
            editable_lines = list(current_lines)
        collapsed = smart_collapse_lines(
            editable_lines,
            line_width_limit,
            infer_name_from_first_line=(infer_enabled and (not has_inferred_speaker)),
            allow_comma_endings=allow_comma_endings,
            allow_colon_triplet_endings=allow_colon_triplet_endings,
            allow_ellipsis_lowercase_continuation=ellipsis_lowercase_rule,
            collapse_if_no_punctuation=collapse_if_no_punctuation,
            min_soft_ratio=max(0.0, min(1.0, float(min_soft_ratio))),
        )
        if has_inferred_speaker:
            speaker_line = current_lines[0] if current_lines else ""
            return [speaker_line] + collapsed
        return collapsed

    def _collapsed_translation_lines_for_segment(
        self,
        segment: DialogueSegment,
        *,
        allow_comma_endings: bool,
        allow_colon_triplet_endings: bool,
        ellipsis_lowercase_rule: bool,
        collapse_if_no_punctuation: bool,
        min_soft_ratio: float,
        infer_speaker_enabled: Optional[bool] = None,
        line_width: Optional[int] = None,
    ) -> list[str]:
        infer_enabled = (
            bool(self.infer_speaker_check.isChecked())
            if infer_speaker_enabled is None
            else bool(infer_speaker_enabled)
        )
        line_width_limit = (
            self._segment_line_width(segment)
            if line_width is None
            else int(line_width)
        )
        try:
            editable_lines = self._segment_translation_lines_for_translation(
                segment,
                infer_speaker_enabled=infer_enabled,
            )
        except TypeError:
            editable_lines = self._segment_translation_lines_for_translation(segment)
        try:
            has_inferred_speaker = bool(
                self._segment_has_inferred_line1_speaker(
                    segment,
                    infer_speaker_enabled=infer_enabled,
                )
            )
        except TypeError:
            has_inferred_speaker = bool(
                self._segment_has_inferred_line1_speaker(segment)
            )
        collapsed = smart_collapse_lines(
            editable_lines,
            line_width_limit,
            infer_name_from_first_line=(infer_enabled and (not has_inferred_speaker)),
            allow_comma_endings=allow_comma_endings,
            allow_colon_triplet_endings=allow_colon_triplet_endings,
            allow_ellipsis_lowercase_continuation=ellipsis_lowercase_rule,
            collapse_if_no_punctuation=collapse_if_no_punctuation,
            min_soft_ratio=max(0.0, min(1.0, float(min_soft_ratio))),
        )
        try:
            return self._compose_translation_lines_for_segment(
                segment,
                collapsed,
                infer_speaker_enabled=infer_enabled,
            )
        except TypeError:
            return self._compose_translation_lines_for_segment(segment, collapsed)

    def _smart_collapse_all_dialogue_blocks(self) -> None:
        if not self.sessions:
            return
        options = self._prompt_smart_collapse_all_options()
        if options is None:
            return

        (
            allow_comma_endings,
            allow_colon_triplet_endings,
            ellipsis_lowercase_rule,
            collapse_if_no_punctuation,
            min_soft_ratio,
            apply_all_files,
        ) = options
        translator_mode = self._is_translator_mode()
        changed_count = 0
        changed_sessions: list[FileSession] = []
        target_sessions = self._smart_collapse_target_sessions(apply_all_files)
        if not target_sessions:
            return
        for session in target_sessions:
            if self._is_name_index_session(session):
                continue
            session_changed = False
            for segment in session.segments:
                if not self._is_smart_collapse_eligible_segment(segment):
                    continue
                if translator_mode:
                    current_lines = self._normalize_translation_lines(
                        segment.translation_lines
                    )
                    collapsed_lines = self._collapsed_translation_lines_for_segment(
                    segment,
                    allow_comma_endings=allow_comma_endings,
                    allow_colon_triplet_endings=allow_colon_triplet_endings,
                    ellipsis_lowercase_rule=ellipsis_lowercase_rule,
                    collapse_if_no_punctuation=collapse_if_no_punctuation,
                    min_soft_ratio=min_soft_ratio,
                )
                    if collapsed_lines == current_lines:
                        continue
                    segment.translation_lines = list(collapsed_lines)
                else:
                    current_lines = list(segment.lines) if segment.lines else [""]
                    collapsed_lines = self._collapsed_source_lines_for_segment(
                    segment,
                    allow_comma_endings=allow_comma_endings,
                    allow_colon_triplet_endings=allow_colon_triplet_endings,
                    ellipsis_lowercase_rule=ellipsis_lowercase_rule,
                    collapse_if_no_punctuation=collapse_if_no_punctuation,
                    min_soft_ratio=min_soft_ratio,
                )
                    if collapsed_lines == current_lines:
                        continue
                    segment.lines = list(collapsed_lines)
                    segment.source_lines = list(collapsed_lines)
                changed_count += 1
                session_changed = True
            if session_changed:
                changed_sessions.append(session)

        if changed_count <= 0:
            self.statusBar().showMessage(
                "Smart Collapse All made no changes."
            )
            return

        for session in changed_sessions:
            self._refresh_dirty_state(session)
        focus_uid = self.selected_segment_uid
        current_session = (
            self.sessions.get(self.current_path)
            if self.current_path is not None
            else None
        )
        if current_session is not None:
            if not self._refresh_after_structure_change_without_full_rerender(
                current_session,
                focus_uid=focus_uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    current_session,
                    focus_uid=focus_uid,
                    preserve_scroll=True,
                )
        block_label = "block" if changed_count == 1 else "blocks"
        file_label = "file" if len(changed_sessions) == 1 else "files"
        self.statusBar().showMessage(
            f"Smart-collapsed {changed_count} {block_label} across {len(changed_sessions)} {file_label}."
        )

    def _active_color_code_at_end(self, lines: list[str]) -> int:
        active = 0
        joined = "\n".join(lines)
        for match in self._COLOR_CODE_RE.finditer(joined):
            try:
                active = int(match.group(1))
            except Exception:
                active = 0
        return active

    def _line_starts_with_color_code(self, line: str) -> bool:
        return self._COLOR_CODE_AT_LINE_START_RE.match(line) is not None

    def _apply_split_overflow_color_continuity(
        self,
        kept_lines: list[str],
        moved_lines: list[str],
        *,
        inferred_marker: str = "",
    ) -> tuple[list[str], list[str]]:
        if not kept_lines or not moved_lines:
            return kept_lines, moved_lines

        active_color = self._active_color_code_at_end(kept_lines)
        if active_color == 0:
            return kept_lines, moved_lines

        # If active color comes from inferred line-1 speaker marker, the marker
        # is copied to the moved block anyway, so injecting extra continuity
        # codes would be redundant.
        marker_color = self._active_color_code_at_end([inferred_marker]) if inferred_marker else 0
        if marker_color != 0 and marker_color == active_color:
            return kept_lines, moved_lines

        if not self._line_starts_with_color_code(moved_lines[0]):
            moved_lines[0] = f"\\C[{active_color}]{moved_lines[0]}"

        if self._TRAILING_RESET_COLOR_RE.search(kept_lines[-1] or "") is None:
            kept_lines[-1] = f"{kept_lines[-1]}\\C[0]"
        return kept_lines, moved_lines

    def _sync_source_split_color_continuity_from_translation(
        self,
        kept_source_lines: list[str],
        moved_source_lines: list[str],
        kept_translation_lines: list[str],
        moved_translation_lines: list[str],
    ) -> tuple[list[str], list[str]]:
        if not kept_source_lines or not moved_source_lines:
            return kept_source_lines, moved_source_lines
        if not kept_translation_lines or not moved_translation_lines:
            return kept_source_lines, moved_source_lines

        moved_first_tl = moved_translation_lines[0] if moved_translation_lines else ""
        start_match = self._COLOR_CODE_AT_LINE_START_RE.match(moved_first_tl or "")
        if (
            start_match is not None
            and (not self._line_starts_with_color_code(moved_source_lines[0]))
        ):
            moved_source_lines[0] = f"{start_match.group(0)}{moved_source_lines[0]}"

        kept_last_tl = kept_translation_lines[-1] if kept_translation_lines else ""
        if self._TRAILING_RESET_COLOR_RE.search(kept_last_tl or "") is not None:
            if self._TRAILING_RESET_COLOR_RE.search(kept_source_lines[-1] or "") is None:
                kept_source_lines[-1] = f"{kept_source_lines[-1]}\\C[0]"

        return kept_source_lines, moved_source_lines

    def _refresh_after_structure_change_without_full_rerender(
        self,
        session: FileSession,
        *,
        focus_uid: Optional[str] = None,
        preserve_scroll: bool = True,
    ) -> bool:
        if self.current_path != session.path:
            return False
        if self._pending_render_state is not None:
            return False
        if self.rendered_blocks_path != session.path:
            return False
        actor_mode = self._is_name_index_session(session)
        if actor_mode:
            return False

        translator_mode = self._is_translator_mode()
        display_segments_resolver = getattr(self, "_display_segments_for_session", None)
        display_segments_raw: object
        if callable(display_segments_resolver):
            display_segments_raw = display_segments_resolver(
                session,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
            )
        else:
            display_segments_raw = list(session.segments)
        if isinstance(display_segments_raw, list):
            display_segments: list[DialogueSegment] = cast(
                list[DialogueSegment], display_segments_raw
            )
        else:
            display_segments = list(session.segments)
        name_index_kind = ""
        name_index_label = self._name_index_label(session)
        target_view_meta = self._block_view_meta(
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
        )
        if self.rendered_block_view_meta != target_view_meta:
            return False

        if translator_mode:
            cached_reference_map = self.reference_summary_cache_by_path.get(
                session.path
            )
            if cached_reference_map is None:
                cached_reference_map = self._build_reference_summary_for_session(
                    session
                )
                self.reference_summary_cache_by_path[session.path] = cached_reference_map
            self.current_reference_map = cached_reference_map
        else:
            self.current_reference_map = {}

        previous_scroll_value = (
            self.scroll_area.verticalScrollBar().value() if preserve_scroll else None
        )
        self.current_segment_lookup = {
            segment.uid: segment for segment in display_segments}
        if self.selected_segment_uid and self.selected_segment_uid not in self.current_segment_lookup:
            self.selected_segment_uid = None
        if focus_uid and focus_uid in self.current_segment_lookup:
            self.selected_segment_uid = focus_uid

        self.cached_block_widgets_by_path.pop(session.path, None)
        self.cached_block_uid_order_by_path.pop(session.path, None)
        self.cached_block_view_meta_by_path.pop(session.path, None)
        cached_container = self.cached_block_containers_by_path.pop(
            session.path, None)
        if isinstance(cached_container, dict):
            container = cached_container.get("container")
            if isinstance(container, QWidget) and container is not self.scroll_container:
                container.deleteLater()

        existing_widgets = dict(self.block_widgets)
        preserve_widgets = set(
            cast(list[QWidget], list(existing_widgets.values())))
        self.rendered_blocks_path = None
        self.rendered_block_uid_order = []
        self._clear_blocks(
            preserve_widgets=preserve_widgets if preserve_widgets else None
        )
        self.block_widgets = {}

        merge_pairs = self._precompute_merge_pairs(
            session,
            translator_mode=translator_mode,
        )
        segment_count = len(display_segments)
        for idx, segment in enumerate(display_segments):
            reused = existing_widgets.pop(segment.uid, None)
            if (
                reused is not None
                and self._can_reuse_block_widget(
                    reused,
                    segment=segment,
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                    name_index_kind=name_index_kind,
                    name_index_label=name_index_label,
                )
            ):
                widget = reused
                self._sync_reused_block_widget(
                    widget,
                    segment=segment,
                    block_number=idx + 1,
                    name_index_label=name_index_label,
                )
            else:
                if reused is not None:
                    reused.deleteLater()
                widget = self._create_block_widget(
                    segment=segment,
                    block_number=idx + 1,
                    translator_mode=translator_mode,
                    actor_mode=actor_mode,
                    name_index_kind=name_index_kind,
                    name_index_label=name_index_label,
                )
            self.blocks_layout.addWidget(widget)
            widget.show()
            self.block_widgets[segment.uid] = widget
            self._apply_block_visual_state(segment.uid, widget)

            if idx < segment_count - 1:
                next_segment = display_segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_widget = self._build_merge_connector_widget(
                        session,
                        segment,
                        next_segment,
                    )
                    self.blocks_layout.addWidget(connector_widget)

        self.blocks_layout.addStretch(1)
        for leftover in existing_widgets.values():
            leftover.deleteLater()

        self.rendered_blocks_path = session.path
        self.rendered_block_uid_order = [segment.uid for segment in display_segments]
        self.rendered_block_view_meta = target_view_meta
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)

        source_dirty, tl_dirty = self._session_dirty_flags_cached(session)
        block_count = len(display_segments)
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
        self._refresh_translator_detail_panel()

        target_widget = (
            self.block_widgets.get(focus_uid)
            if focus_uid and focus_uid in self.block_widgets
            else None
        )
        self._flash_pending_audit_target(focus_uid, target_widget)
        if target_widget is not None:
            def focus_and_reveal() -> None:
                self._focus_target_widget(
                    target_widget,
                    preserve_scroll_value=previous_scroll_value if preserve_scroll else None,
                )

            QTimer.singleShot(0, focus_and_reveal)
            return True
        if preserve_scroll and previous_scroll_value is not None:
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(previous_scroll_value))
        return True

    def _refresh_after_insert_without_full_rerender(
        self,
        session: FileSession,
        *,
        inserted_uid: str,
        focus_uid: Optional[str] = None,
        preserve_scroll: bool = True,
    ) -> bool:
        if self.current_path != session.path:
            return False
        if self._pending_render_state is not None:
            return False
        if self.rendered_blocks_path != session.path:
            return False
        if not isinstance(inserted_uid, str) or not inserted_uid:
            return False

        actor_mode = self._is_name_index_session(session)
        if actor_mode:
            return False
        translator_mode = self._is_translator_mode()
        name_index_kind = ""
        name_index_label = self._name_index_label(session)
        target_view_meta = self._block_view_meta(
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
        )
        if self.rendered_block_view_meta != target_view_meta:
            return False

        display_segments_resolver = getattr(self, "_display_segments_for_session", None)
        display_segments_raw: object
        if callable(display_segments_resolver):
            display_segments_raw = display_segments_resolver(
                session,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
            )
        else:
            display_segments_raw = list(session.segments)
        if isinstance(display_segments_raw, list):
            display_segments: list[DialogueSegment] = cast(
                list[DialogueSegment], display_segments_raw
            )
        else:
            display_segments = list(session.segments)

        new_uid_order = [segment.uid for segment in display_segments]
        if inserted_uid not in new_uid_order:
            return False
        old_uid_order = list(self.rendered_block_uid_order)
        if len(new_uid_order) != len(old_uid_order) + 1:
            return False
        insert_index = new_uid_order.index(inserted_uid)
        if old_uid_order != (new_uid_order[:insert_index] + new_uid_order[insert_index + 1:]):
            return False

        existing_widgets = dict(self.block_widgets)
        if inserted_uid in existing_widgets:
            return False
        for segment in display_segments:
            if segment.uid == inserted_uid:
                continue
            widget = existing_widgets.get(segment.uid)
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
        inserted_segment = next(
            (segment for segment in display_segments if segment.uid == inserted_uid),
            None,
        )
        if inserted_segment is None:
            return False
        block_numbers = self._display_block_numbers(
            display_segments,
            actor_mode=actor_mode,
        )
        inserted_widget = self._create_block_widget(
            segment=inserted_segment,
            block_number=block_numbers.get(inserted_uid, insert_index + 1),
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
        )

        if translator_mode:
            refreshed_reference_map = self._build_reference_summary_for_session(session)
            self.reference_summary_cache_by_path[session.path] = refreshed_reference_map
            self.current_reference_map = refreshed_reference_map
        else:
            self.current_reference_map = {}

        previous_scroll_value = (
            self.scroll_area.verticalScrollBar().value() if preserve_scroll else None
        )
        self.current_segment_lookup = {
            segment.uid: segment for segment in display_segments
        }
        if self.selected_segment_uid and self.selected_segment_uid not in self.current_segment_lookup:
            self.selected_segment_uid = None
        if focus_uid and focus_uid in self.current_segment_lookup:
            self.selected_segment_uid = focus_uid

        self.cached_block_widgets_by_path.pop(session.path, None)
        self.cached_block_uid_order_by_path.pop(session.path, None)
        self.cached_block_view_meta_by_path.pop(session.path, None)
        cached_container = self.cached_block_containers_by_path.pop(
            session.path, None
        )
        if isinstance(cached_container, dict):
            container = cached_container.get("container")
            if isinstance(container, QWidget) and container is not self.scroll_container:
                container.deleteLater()

        preserve_widgets = set(cast(list[QWidget], list(existing_widgets.values())))
        preserve_widgets.add(inserted_widget)
        self._clear_blocks(preserve_widgets=preserve_widgets)
        self.block_widgets = {}

        merge_pairs = self._precompute_merge_pairs(
            session,
            translator_mode=translator_mode,
        )
        segment_count = len(display_segments)
        for idx, segment in enumerate(display_segments):
            if segment.uid == inserted_uid:
                widget = inserted_widget
            else:
                widget = existing_widgets.get(segment.uid)
                if widget is None:
                    return False
                block_number = block_numbers.get(segment.uid, idx + 1)
                if getattr(widget, "block_number", block_number) != block_number:
                    try:
                        setattr(widget, "block_number", block_number)
                    except Exception:
                        pass
                    refresh_block_style = getattr(widget, "_refresh_block_style", None)
                    if callable(refresh_block_style):
                        refresh_block_style()

            self.blocks_layout.addWidget(widget)
            widget.show()
            self.block_widgets[segment.uid] = widget
            self._apply_block_visual_state(segment.uid, widget)

            if idx < segment_count - 1:
                next_segment = display_segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_widget = self._build_merge_connector_widget(
                        session,
                        segment,
                        next_segment,
                    )
                    self.blocks_layout.addWidget(connector_widget)

        self.blocks_layout.addStretch(1)

        self.rendered_blocks_path = session.path
        self.rendered_block_uid_order = new_uid_order
        self.rendered_block_view_meta = target_view_meta
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)

        source_dirty, tl_dirty = self._session_dirty_flags_cached(session)
        block_count = len(display_segments)
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
        self._refresh_translator_detail_panel()

        target_widget = (
            self.block_widgets.get(focus_uid)
            if focus_uid and focus_uid in self.block_widgets
            else None
        )
        self._flash_pending_audit_target(focus_uid, target_widget)
        if target_widget is not None:
            def focus_and_reveal() -> None:
                self._focus_target_widget(
                    target_widget,
                    preserve_scroll_value=previous_scroll_value if preserve_scroll else None,
                )

            QTimer.singleShot(0, focus_and_reveal)
            return True
        if preserve_scroll and previous_scroll_value is not None:
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)
            )
        return True

    def _refresh_after_remove_without_full_rerender(
        self,
        session: FileSession,
        *,
        removed_uid: str,
        updated_uids: Optional[set[str]] = None,
        focus_uid: Optional[str] = None,
        preserve_scroll: bool = True,
    ) -> bool:
        if self.current_path != session.path:
            return False
        if self._pending_render_state is not None:
            return False
        if self.rendered_blocks_path != session.path:
            return False
        if not isinstance(removed_uid, str) or not removed_uid:
            return False

        actor_mode = self._is_name_index_session(session)
        if actor_mode:
            return False
        translator_mode = self._is_translator_mode()
        name_index_kind = ""
        name_index_label = self._name_index_label(session)
        target_view_meta = self._block_view_meta(
            translator_mode=translator_mode,
            actor_mode=actor_mode,
            name_index_kind=name_index_kind,
            name_index_label=name_index_label,
        )
        if self.rendered_block_view_meta != target_view_meta:
            return False

        display_segments_resolver = getattr(self, "_display_segments_for_session", None)
        display_segments_raw: object
        if callable(display_segments_resolver):
            display_segments_raw = display_segments_resolver(
                session,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
            )
        else:
            display_segments_raw = list(session.segments)
        if isinstance(display_segments_raw, list):
            display_segments: list[DialogueSegment] = cast(
                list[DialogueSegment], display_segments_raw
            )
        else:
            display_segments = list(session.segments)

        new_uid_order = [segment.uid for segment in display_segments]
        old_uid_order = list(self.rendered_block_uid_order)
        if removed_uid in new_uid_order or removed_uid not in old_uid_order:
            return False
        if len(new_uid_order) + 1 != len(old_uid_order):
            return False
        removed_index = old_uid_order.index(removed_uid)
        if new_uid_order != (old_uid_order[:removed_index] + old_uid_order[removed_index + 1:]):
            return False

        normalized_updated_uids = {
            uid
            for uid in (updated_uids or set())
            if isinstance(uid, str) and uid and uid in new_uid_order
        }
        existing_widgets = dict(self.block_widgets)
        removed_widget = existing_widgets.get(removed_uid)
        if removed_widget is None:
            return False
        for segment in display_segments:
            widget = existing_widgets.get(segment.uid)
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

        block_numbers = self._display_block_numbers(
            display_segments,
            actor_mode=actor_mode,
        )
        if translator_mode:
            refreshed_reference_map = self._build_reference_summary_for_session(session)
            self.reference_summary_cache_by_path[session.path] = refreshed_reference_map
            self.current_reference_map = refreshed_reference_map
        else:
            self.current_reference_map = {}

        previous_scroll_value = (
            self.scroll_area.verticalScrollBar().value() if preserve_scroll else None
        )
        self.current_segment_lookup = {
            segment.uid: segment for segment in display_segments
        }
        if self.selected_segment_uid and self.selected_segment_uid not in self.current_segment_lookup:
            self.selected_segment_uid = None
        if focus_uid and focus_uid in self.current_segment_lookup:
            self.selected_segment_uid = focus_uid

        self.cached_block_widgets_by_path.pop(session.path, None)
        self.cached_block_uid_order_by_path.pop(session.path, None)
        self.cached_block_view_meta_by_path.pop(session.path, None)
        cached_container = self.cached_block_containers_by_path.pop(
            session.path, None
        )
        if isinstance(cached_container, dict):
            container = cached_container.get("container")
            if isinstance(container, QWidget) and container is not self.scroll_container:
                container.deleteLater()

        preserve_widgets = set(cast(list[QWidget], list(existing_widgets.values())))
        preserve_widgets.discard(removed_widget)
        self._clear_blocks(preserve_widgets=preserve_widgets)
        self.block_widgets = {}

        merge_pairs = self._precompute_merge_pairs(
            session,
            translator_mode=translator_mode,
        )
        segment_count = len(display_segments)
        for idx, segment in enumerate(display_segments):
            widget = existing_widgets.pop(segment.uid, None)
            if widget is None:
                return False
            block_number = block_numbers.get(segment.uid, idx + 1)
            if segment.uid in normalized_updated_uids:
                self._sync_reused_block_widget(
                    widget,
                    segment=segment,
                    block_number=block_number,
                    name_index_label=name_index_label,
                )
            elif getattr(widget, "block_number", block_number) != block_number:
                try:
                    setattr(widget, "block_number", block_number)
                except Exception:
                    pass
                refresh_block_style = getattr(widget, "_refresh_block_style", None)
                if callable(refresh_block_style):
                    refresh_block_style()

            self.blocks_layout.addWidget(widget)
            widget.show()
            self.block_widgets[segment.uid] = widget
            self._apply_block_visual_state(segment.uid, widget)

            if idx < segment_count - 1:
                next_segment = display_segments[idx + 1]
                if (segment.uid, next_segment.uid) in merge_pairs:
                    connector_widget = self._build_merge_connector_widget(
                        session,
                        segment,
                        next_segment,
                    )
                    self.blocks_layout.addWidget(connector_widget)

        self.blocks_layout.addStretch(1)
        for leftover in existing_widgets.values():
            leftover.deleteLater()

        self.rendered_blocks_path = session.path
        self.rendered_block_uid_order = new_uid_order
        self.rendered_block_view_meta = target_view_meta
        self._hide_audit_progress_overlay(self.main_render_progress_overlay)

        source_dirty, tl_dirty = self._session_dirty_flags_cached(session)
        block_count = len(display_segments)
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
        self._refresh_translator_detail_panel()

        target_widget = (
            self.block_widgets.get(focus_uid)
            if focus_uid and focus_uid in self.block_widgets
            else None
        )
        self._flash_pending_audit_target(focus_uid, target_widget)
        if target_widget is not None:
            def focus_and_reveal() -> None:
                self._focus_target_widget(
                    target_widget,
                    preserve_scroll_value=previous_scroll_value if preserve_scroll else None,
                )

            QTimer.singleShot(0, focus_and_reveal)
            return True
        if preserve_scroll and previous_scroll_value is not None:
            QTimer.singleShot(
                0, lambda: self.scroll_area.verticalScrollBar().setValue(previous_scroll_value)
            )
        return True

    def _segment_line_width(self, segment: DialogueSegment) -> int:
        return self.thin_width_spin.value() if segment.has_face else self.wide_width_spin.value()

    def _inferred_line1_speaker_marker(self, segment: DialogueSegment) -> str:
        resolver = getattr(self, "_inferred_speaker_from_segment_line1", None)
        if not callable(resolver):
            return ""
        try:
            inferred = resolver(segment)
        except Exception:
            return ""
        if not isinstance(inferred, str) or not inferred.strip():
            return ""
        source_lines = self._segment_source_lines_for_display(segment)
        if len(source_lines) <= 1:
            return ""
        first_line = source_lines[0]
        return first_line if isinstance(first_line, str) else ""

    def _with_inferred_line1_marker(self, lines: list[str], marker: str) -> list[str]:
        normalized = list(lines) if lines else [""]
        marker_text = marker if isinstance(marker, str) else ""
        if not marker_text:
            return normalized
        if normalized and normalized[0] == marker_text:
            if len(normalized) == 1:
                return [marker_text, ""]
            return normalized
        return [marker_text] + normalized

    def _dedupe_leading_inferred_marker_for_merge(
        self,
        left_segment: DialogueSegment,
        right_segment: DialogueSegment,
        right_lines: list[str],
    ) -> list[str]:
        normalized_right = list(right_lines) if right_lines else [""]
        left_marker = self._inferred_line1_speaker_marker(left_segment)
        right_marker = self._inferred_line1_speaker_marker(right_segment)
        if not left_marker or left_marker != right_marker:
            return normalized_right
        if normalized_right and normalized_right[0] == right_marker:
            trimmed = normalized_right[1:]
            return trimmed if trimmed else [""]
        return normalized_right

    def _same_merge_signature(self, left: DialogueSegment, right: DialogueSegment) -> bool:
        if (not left.is_structural_dialogue) or (not right.is_structural_dialogue):
            return False
        return (
            left.segment_kind == right.segment_kind
            and
            left.context == right.context
            and left.code101.get("parameters") == right.code101.get("parameters")
        )

    def _can_merge_segments(self, session: FileSession, left: DialogueSegment, right: DialogueSegment) -> bool:
        if not self._same_merge_signature(left, right):
            return False
        left_index = self._find_segment_index_by_uid(session, left.uid)
        right_index = self._find_segment_index_by_uid(session, right.uid)
        if left_index < 0 or right_index != left_index + 1:
            return False
        left_bundle, left_token_index = self._find_segment_token(
            session, left.uid)
        right_bundle, right_token_index = self._find_segment_token(
            session, right.uid)
        if left_bundle is None or right_bundle is None:
            return False
        if left_bundle is not right_bundle:
            return False
        return right_token_index == left_token_index + 1

    def _merged_pair_line_savings(self, left: DialogueSegment, right: DialogueSegment) -> int:
        width = self._segment_line_width(left)
        before = len(left.lines) + len(right.lines)
        merged = smart_collapse_lines(
            list(left.lines) + list(right.lines),
            width,
            infer_name_from_first_line=self.infer_speaker_check.isChecked(),
        )
        return before - len(merged)

    def _build_merge_connector_widget(
        self,
        session: FileSession,
        left: DialogueSegment,
        right: DialogueSegment,
    ) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 2, 6, 2)
        row_layout.setSpacing(8)

        left_line = QFrame()
        left_line.setFrameShape(QFrame.Shape.HLine)
        left_line.setFrameShadow(QFrame.Shadow.Sunken)
        row_layout.addWidget(left_line, 1)

        button = QPushButton("Merge")
        button.setMinimumHeight(24)
        button.setToolTip("Merge these neighboring blocks.")
        savings = self._merged_pair_line_savings(left, right)
        if savings > 0:
            button.setText(f"Merge (-{savings}L)")
        button.clicked.connect(
            lambda _checked=False, left_uid=left.uid, right_uid=right.uid: self._on_merge_pair_requested(
                left_uid,
                right_uid,
            )
        )
        row_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)

        right_line = QFrame()
        right_line.setFrameShape(QFrame.Shape.HLine)
        right_line.setFrameShadow(QFrame.Shadow.Sunken)
        row_layout.addWidget(right_line, 1)
        return row

    def _on_block_text_changed(self, uid: str, lines: list[str]) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return
        segment = self.current_segment_lookup.get(uid)
        if segment is None:
            return
        if self._is_translator_mode():
            segment.translation_lines = self._normalize_translation_lines(
                lines)
        else:
            segment.lines = list(lines)
            segment.source_lines = list(segment.lines)
        self._refresh_dirty_state(session)
        if self._is_translator_mode() and self.selected_segment_uid == uid:
            self._refresh_translator_detail_panel()

    def _line1_inference_match_key(self, segment: DialogueSegment) -> str:
        if not segment.is_structural_dialogue:
            return ""
        if segment.speaker_name != NO_SPEAKER_KEY:
            return ""
        source_lines = self._segment_source_lines_for_display(segment)
        if len(source_lines) <= 1:
            return ""
        first_line = source_lines[0].strip()
        return first_line

    def _matching_line1_inference_segments(
        self,
        match_key: str,
    ) -> list[tuple[Path, FileSession, DialogueSegment]]:
        if not match_key:
            return []
        matches: list[tuple[Path, FileSession, DialogueSegment]] = []
        for path, session in self.sessions.items():
            if self._is_name_index_session(session):
                continue
            for segment in session.segments:
                if self._line1_inference_match_key(segment) == match_key:
                    matches.append((path, session, segment))
        return matches

    def _set_line1_inference_mode_for_segment(
        self,
        segment: DialogueSegment,
        *,
        disabled: bool,
        forced: bool,
    ) -> bool:
        next_disabled = bool(disabled)
        next_forced = bool(forced) and (not next_disabled)
        changed = (
            bool(segment.disable_line1_speaker_inference) != next_disabled
            or bool(segment.force_line1_speaker_inference) != next_forced
        )
        segment.disable_line1_speaker_inference = next_disabled
        segment.force_line1_speaker_inference = next_forced
        return changed

    def _prompt_line1_inference_scope(
        self,
        *,
        disabled: bool,
        forced: bool,
        match_count: int,
        line1_preview: str,
    ) -> str:
        if match_count <= 1:
            return "single"
        action_label = (
            "exclude line 1 as speaker"
            if disabled
            else "include line 1 as speaker"
        )
        preview = line1_preview.strip()
        if len(preview) > 80:
            preview = f"{preview[:77]}..."
        box = QMessageBox(cast(QWidget, self))
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Line1 Speaker Override")
        box.setText(f"Apply '{action_label}' to matching occurrences?")
        box.setInformativeText(
            f"Found {match_count} blocks with first line:\n{preview}\n\n"
            "Apply this to this block only, or all matches?"
        )
        this_button = box.addButton("This Block", QMessageBox.ButtonRole.AcceptRole)
        all_button = box.addButton("All Matches", QMessageBox.ButtonRole.YesRole)
        cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cast(QPushButton, this_button))
        box.exec()
        clicked = box.clickedButton()
        if clicked == cancel_button:
            return "cancel"
        if clicked == all_button:
            return "all"
        return "single"

    def _on_line1_inference_override_changed(
        self,
        uid: str,
        disabled: bool,
        forced: bool,
        prev_disabled: bool,
        prev_forced: bool,
    ) -> None:
        if self.current_path is None:
            return
        current_session = self.sessions.get(self.current_path)
        if current_session is None:
            return
        segment = self.current_segment_lookup.get(uid)
        if segment is None:
            return
        next_disabled = bool(disabled)
        next_forced = bool(forced) and (not next_disabled)
        line1_key = self._line1_inference_match_key(segment)
        matches = self._matching_line1_inference_segments(line1_key)
        scope = self._prompt_line1_inference_scope(
            disabled=next_disabled,
            forced=next_forced,
            match_count=len(matches),
            line1_preview=line1_key,
        )

        touched_paths: set[Path] = set()
        if scope == "cancel":
            if self._set_line1_inference_mode_for_segment(
                segment,
                disabled=bool(prev_disabled),
                forced=bool(prev_forced),
            ):
                touched_paths.add(current_session.path)
            self.statusBar().showMessage("Line-1 speaker override canceled.")
        elif scope == "all":
            changed_count = 0
            for path, _session, candidate in matches:
                if self._set_line1_inference_mode_for_segment(
                    candidate,
                    disabled=next_disabled,
                    forced=next_forced,
                ):
                    touched_paths.add(path)
                    changed_count += 1
            action_text = "not-speaker" if next_disabled else "speaker"
            self.statusBar().showMessage(
                f"Set line 1 as {action_text} for {changed_count} matching blocks."
            )
        else:
            if self._set_line1_inference_mode_for_segment(
                segment,
                disabled=next_disabled,
                forced=next_forced,
            ):
                touched_paths.add(current_session.path)
            state_label = "not-speaker" if next_disabled else "speaker"
            self.statusBar().showMessage(
                f"Set line 1 as {state_label} for block {uid}."
            )

        if not touched_paths:
            touched_paths.add(current_session.path)
        for path in touched_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            self._refresh_dirty_state(session)
        if self.current_path in touched_paths:
            self._render_session(current_session, preserve_scroll=True)
        else:
            self._refresh_translator_detail_panel()

    def _new_segment_uid(self, path: Path) -> str:
        existing_uids: set[str] = set()
        sessions_raw = getattr(self, "sessions", None)
        session = (
            sessions_raw.get(path)
            if isinstance(sessions_raw, dict)
            else None
        )
        if isinstance(session, FileSession):
            existing_uids = {
                segment.uid
                for segment in session.segments
                if isinstance(segment.uid, str) and segment.uid
            }
        while True:
            self.segment_uid_counter += 1
            candidate_uid = f"{path.name}:I:{self.segment_uid_counter}"
            if candidate_uid not in existing_uids:
                return candidate_uid

    def _find_segment_token(self, session: FileSession, uid: str) -> tuple[Optional[CommandBundle], int]:
        for bundle in session.bundles:
            for idx, token in enumerate(bundle.tokens):
                if token.kind == "dialogue" and token.segment and token.segment.uid == uid:
                    return bundle, idx
        return None, -1

    def _find_segment_index_by_uid(self, session: FileSession, uid: str) -> int:
        for idx, segment in enumerate(session.segments):
            if segment.uid == uid:
                return idx
        return -1

    def _find_bundle_token_index_by_uid(self, bundle: CommandBundle, uid: str) -> int:
        for idx, token in enumerate(bundle.tokens):
            if token.kind == "dialogue" and token.segment and token.segment.uid == uid:
                return idx
        return -1

    def _remove_segment_by_uid(self, session: FileSession, uid: str) -> bool:
        segment_index = self._find_segment_index_by_uid(session, uid)
        if segment_index < 0:
            return False
        bundle, token_index = self._find_segment_token(session, uid)
        if bundle is not None and token_index >= 0:
            del bundle.tokens[token_index]
        del session.segments[segment_index]
        return True

    def _restore_merged_segments_after(
        self,
        session: FileSession,
        anchor_uid: str,
        merged_segments: list[DialogueSegment],
    ) -> int:
        if not merged_segments:
            return 0
        bundle, token_index = self._find_segment_token(session, anchor_uid)
        if bundle is None or token_index < 0:
            return 0
        segment_index = self._find_segment_index_by_uid(session, anchor_uid)
        if segment_index < 0:
            return 0

        restored = 0
        insert_token_index = token_index + 1
        insert_segment_index = segment_index + 1
        for restored_segment in merged_segments:
            if self._find_segment_index_by_uid(session, restored_segment.uid) >= 0:
                continue
            bundle.tokens.insert(insert_token_index, CommandToken(
                kind="dialogue", segment=restored_segment))
            session.segments.insert(insert_segment_index, restored_segment)
            insert_token_index += 1
            insert_segment_index += 1
            restored += 1
        return restored

    def _structural_action_references_uids(self, action: StructuralAction, path: Path, uids: set[str]) -> bool:
        if action.path != path:
            return False
        if action.kind == "insert":
            payload = cast(InsertedBlockAction, action.data)
            return payload.uid in uids
        if action.kind == "delete":
            payload = cast(DeletedBlockAction, action.data)
            return payload.uid in uids
        if action.kind == "merge":
            payload = cast(MergeBlocksAction, action.data)
            return payload.left_uid in uids or payload.right_uid in uids
        if action.kind == "reset":
            payload = cast(ResetBlockAction, action.data)
            if payload.uid in uids:
                return True
            return any(segment.uid in uids for segment in payload.restored_segments)
        if action.kind == "split_overflow":
            payload = cast(SplitOverflowAction, action.data)
            return payload.source_uid in uids or payload.moved_uid in uids
        return False

    def _prune_structural_history_entries(self, path: Path, uids: set[str]) -> None:
        if not uids:
            return
        self.structural_undo_stack = [
            entry for entry in self.structural_undo_stack
            if not self._structural_action_references_uids(entry, path, uids)
        ]
        self.structural_redo_stack = [
            entry for entry in self.structural_redo_stack
            if not self._structural_action_references_uids(entry, path, uids)
        ]

    def _clear_structural_history_for_path(self, path: Path) -> None:
        self.structural_undo_stack = [
            entry for entry in self.structural_undo_stack if entry.path != path]
        self.structural_redo_stack = [
            entry for entry in self.structural_redo_stack if entry.path != path]

    def _on_insert_after_requested(self, uid: str) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        source_idx = self._find_segment_index_by_uid(session, uid)
        if source_idx < 0:
            return
        source_segment = session.segments[source_idx]
        if not source_segment.is_structural_dialogue:
            self.statusBar().showMessage(
                "Insert is only available for standard dialogue blocks.")
            return
        translator_mode = self._is_translator_mode()
        bundle_index = -1
        token_index = -1
        bundle: Optional[CommandBundle] = None
        if not translator_mode:
            bundle, token_index = self._find_segment_token(session, uid)
            if bundle is None or token_index < 0:
                return
            try:
                bundle_index = session.bundles.index(bundle)
            except ValueError:
                return

        inferred_marker = self._inferred_line1_speaker_marker(source_segment)
        new_source_lines = self._with_inferred_line1_marker([""], inferred_marker)
        new_translation_lines = self._with_inferred_line1_marker([""], inferred_marker)

        new_segment = DialogueSegment(
            uid=self._new_segment_uid(session.path),
            context=source_segment.context,
            code101=copy.deepcopy(source_segment.code101),
            lines=list(new_source_lines),
            original_lines=list(new_source_lines),
            source_lines=list(new_source_lines),
            code401_template=copy.deepcopy(source_segment.code401_template),
            segment_kind=source_segment.segment_kind,
            line_entry_code=source_segment.line_entry_code,
            script_entries_template=copy.deepcopy(source_segment.script_entries_template),
            script_entry_roles=list(source_segment.script_entry_roles),
            script_entry_quotes=list(source_segment.script_entry_quotes),
            tl_uid=self._new_translation_uid(),
            translation_lines=list(new_translation_lines),
            original_translation_lines=list(new_translation_lines),
            translation_speaker=self.speaker_translation_map.get(
                self._normalize_speaker_key(source_segment.speaker_name), ""),
            original_translation_speaker=self.speaker_translation_map.get(
                self._normalize_speaker_key(source_segment.speaker_name), ""),
            disable_line1_speaker_inference=source_segment.disable_line1_speaker_inference,
            original_disable_line1_speaker_inference=source_segment.disable_line1_speaker_inference,
            force_line1_speaker_inference=source_segment.force_line1_speaker_inference,
            original_force_line1_speaker_inference=source_segment.force_line1_speaker_inference,
            inserted=True,
            translation_only=translator_mode,
        )

        if bundle is not None:
            bundle.tokens.insert(
                token_index + 1, CommandToken(kind="dialogue", segment=new_segment))
        session.segments.insert(source_idx + 1, new_segment)
        insert_action = InsertedBlockAction(
            path=session.path,
            uid=new_segment.uid,
            bundle_index=bundle_index,
            token_index=token_index + 1 if token_index >= 0 else -1,
            segment_index=source_idx + 1,
            segment=new_segment,
        )
        self.structural_undo_stack.append(
            StructuralAction(kind="insert", path=session.path,
                             data=insert_action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        if not self._refresh_after_insert_without_full_rerender(
            session,
            inserted_uid=new_segment.uid,
            focus_uid=new_segment.uid,
            preserve_scroll=True,
        ):
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=new_segment.uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=new_segment.uid, preserve_scroll=True)
        if translator_mode:
            self.statusBar().showMessage("Inserted a new translation-only block.")
        else:
            self.statusBar().showMessage("Inserted a new code 101 block.")

    def _on_split_overflow_requested(self, uid: str) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        translator_mode = self._is_translator_mode()
        source_segment = self.current_segment_lookup.get(uid)
        if source_segment is None:
            return
        if not source_segment.is_structural_dialogue:
            self.statusBar().showMessage(
                "Overflow split is only available for standard dialogue blocks.")
            return

        max_rows_budget = float(max(1, self.max_lines_spin.value()))
        source_lines_before = list(source_segment.lines)
        source_tl_before = self._normalize_translation_lines(
            source_segment.translation_lines
        )
        active_lines_before = (
            source_tl_before if translator_mode else source_lines_before
        )
        if total_display_rows(active_lines_before) <= max_rows_budget:
            self.statusBar().showMessage("No overflow lines to move.")
            return

        bundle: Optional[CommandBundle] = None
        token_index = -1
        if not translator_mode:
            bundle, token_index = self._find_segment_token(session, uid)
            if bundle is None or token_index < 0:
                return
        source_index = self._find_segment_index_by_uid(session, uid)
        if source_index < 0:
            return

        kept_active_lines, moved_active_lines = split_lines_by_row_budget(
            active_lines_before,
            max_rows_budget,
        )
        if not moved_active_lines:
            self.statusBar().showMessage("No overflow lines to move.")
            return
        inferred_marker = self._inferred_line1_speaker_marker(source_segment)
        kept_active_lines, moved_active_lines = self._apply_split_overflow_color_continuity(
            list(kept_active_lines),
            list(moved_active_lines),
            inferred_marker=inferred_marker,
        )

        if translator_mode:
            kept_tl_lines = list(kept_active_lines)
            moved_tl_lines = list(moved_active_lines)
            split_index = len(kept_tl_lines)
            kept_source_lines = (
                list(source_lines_before[:split_index])
                if split_index > 0
                else [""]
            )
            moved_source_lines = list(source_lines_before[split_index:])
            if not moved_source_lines:
                moved_source_lines = [""]
            kept_source_lines, moved_source_lines = (
                self._sync_source_split_color_continuity_from_translation(
                    kept_source_lines,
                    moved_source_lines,
                    kept_tl_lines,
                    moved_tl_lines,
                )
            )
        else:
            kept_source_lines = list(kept_active_lines)
            moved_source_lines = list(moved_active_lines)
            split_index = len(kept_source_lines)
            kept_tl_lines = self._normalize_translation_lines(
                source_segment.translation_lines[:split_index]
            )
            moved_tl_lines = self._normalize_translation_lines(
                source_segment.translation_lines[split_index:]
            )

        moved_source_lines = self._with_inferred_line1_marker(
            moved_source_lines,
            inferred_marker,
        )
        moved_tl_lines = self._with_inferred_line1_marker(
            moved_tl_lines,
            inferred_marker,
        )

        new_segment = DialogueSegment(
            uid=self._new_segment_uid(session.path),
            context=source_segment.context,
            code101=copy.deepcopy(source_segment.code101),
            lines=list(moved_source_lines),
            original_lines=list(moved_source_lines),
            source_lines=list(moved_source_lines),
            code401_template=copy.deepcopy(source_segment.code401_template),
            segment_kind=source_segment.segment_kind,
            line_entry_code=source_segment.line_entry_code,
            script_entries_template=copy.deepcopy(source_segment.script_entries_template),
            script_entry_roles=list(source_segment.script_entry_roles),
            script_entry_quotes=list(source_segment.script_entry_quotes),
            tl_uid=self._new_translation_uid(),
            translation_lines=list(moved_tl_lines),
            original_translation_lines=list(moved_tl_lines),
            translation_speaker=source_segment.translation_speaker,
            original_translation_speaker=source_segment.translation_speaker,
            disable_line1_speaker_inference=source_segment.disable_line1_speaker_inference,
            original_disable_line1_speaker_inference=source_segment.disable_line1_speaker_inference,
            force_line1_speaker_inference=source_segment.force_line1_speaker_inference,
            original_force_line1_speaker_inference=source_segment.force_line1_speaker_inference,
            inserted=True,
            translation_only=translator_mode,
        )

        if translator_mode:
            source_segment.source_lines = list(kept_source_lines)
        else:
            source_segment.lines = list(kept_source_lines)
            source_segment.source_lines = list(source_segment.lines)
        source_segment.translation_lines = list(kept_tl_lines)
        if bundle is not None:
            bundle.tokens.insert(
                token_index + 1, CommandToken(kind="dialogue", segment=new_segment))
        session.segments.insert(source_index + 1, new_segment)

        split_action = SplitOverflowAction(
            path=session.path,
            source_uid=uid,
            moved_uid=new_segment.uid,
            source_lines_before=source_lines_before,
            source_lines_after=list(source_lines_before if translator_mode else kept_source_lines),
            moved_segment=new_segment,
            source_translation_before=source_tl_before,
            source_translation_after=list(source_segment.translation_lines),
        )
        self.structural_undo_stack.append(
            StructuralAction(kind="split_overflow",
                             path=session.path, data=split_action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        if not self._refresh_after_structure_change_without_full_rerender(
            session,
            focus_uid=new_segment.uid,
            preserve_scroll=True,
        ):
            self._render_session(
                session, focus_uid=new_segment.uid, preserve_scroll=True)
        line_label = "line" if len(moved_active_lines) == 1 else "lines"
        self.statusBar().showMessage(
            f"Moved {len(moved_active_lines)} overflow {line_label} to a new block below."
        )

    def _on_merge_pair_requested(self, left_uid: str, right_uid: str) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        translator_mode = self._is_translator_mode()
        left_index = self._find_segment_index_by_uid(session, left_uid)
        right_index = self._find_segment_index_by_uid(session, right_uid)
        if left_index < 0 or right_index != left_index + 1:
            return

        left_segment = session.segments[left_index]
        right_segment = session.segments[right_index]
        if (not left_segment.is_structural_dialogue) or (not right_segment.is_structural_dialogue):
            self.statusBar().showMessage(
                "Merge is only available for standard dialogue blocks.")
            return
        if translator_mode and not right_segment.translation_only:
            self.statusBar().showMessage(
                "In Translator Edit mode, merge is only allowed when removing a translation-only block."
            )
            return
        if (not translator_mode) and (not self._can_merge_segments(session, left_segment, right_segment)):
            QMessageBox.information(
                cast(QWidget, self),
                "Cannot merge",
                "These blocks cannot be merged because their command context/settings differ.",
            )
            return
        if translator_mode and not self._same_merge_signature(left_segment, right_segment):
            QMessageBox.information(
                cast(QWidget, self),
                "Cannot merge",
                "These blocks cannot be merged because their command context/settings differ.",
            )
            return

        left_bundle: Optional[CommandBundle] = None
        right_bundle: Optional[CommandBundle] = None
        left_token_index = -1
        right_token_index = -1
        if not translator_mode:
            left_bundle, left_token_index = self._find_segment_token(
                session, left_uid)
            right_bundle, right_token_index = self._find_segment_token(
                session, right_uid)
            if left_bundle is None or right_bundle is None:
                return
            if left_bundle is not right_bundle:
                return
            if right_token_index != left_token_index + 1:
                return

        left_lines_before = list(left_segment.lines)
        left_merged_before = list(left_segment.merged_segments)
        left_translation_before = self._normalize_translation_lines(
            left_segment.translation_lines)
        left_speaker_translation_before = left_segment.translation_speaker
        source_affected = not translator_mode
        right_lines_for_merge = self._dedupe_leading_inferred_marker_for_merge(
            left_segment,
            right_segment,
            right_segment.lines,
        )
        merged_lines = (
            smart_collapse_lines(
                list(left_segment.lines) + list(right_lines_for_merge),
                self._segment_line_width(left_segment),
                infer_name_from_first_line=self.infer_speaker_check.isChecked(),
            )
            if source_affected
            else list(left_segment.lines)
        )
        right_tl_lines_for_merge = self._dedupe_leading_inferred_marker_for_merge(
            left_segment,
            right_segment,
            self._normalize_translation_lines(right_segment.translation_lines),
        )
        merged_tl_lines = smart_collapse_lines(
            self._normalize_translation_lines(left_segment.translation_lines)
            + right_tl_lines_for_merge,
            self._segment_line_width(left_segment),
            infer_name_from_first_line=self.infer_speaker_check.isChecked(),
        )
        merged_speaker_translation = (
            left_segment.translation_speaker.strip() or right_segment.translation_speaker.strip()
        )
        if source_affected:
            left_segment.lines = merged_lines
            left_segment.source_lines = list(left_segment.lines)
        left_segment.translation_lines = list(merged_tl_lines)
        left_segment.translation_speaker = merged_speaker_translation
        if merged_speaker_translation:
            self.speaker_translation_map[
                self._normalize_speaker_key(left_segment.speaker_name)
            ] = merged_speaker_translation
        if source_affected:
            left_segment.merged_segments.append(right_segment)
        if left_bundle is not None and right_token_index >= 0:
            del left_bundle.tokens[right_token_index]
        del session.segments[right_index]

        merge_action = MergeBlocksAction(
            path=session.path,
            left_uid=left_uid,
            right_uid=right_uid,
            left_lines_before=left_lines_before,
            left_lines_after=list(merged_lines),
            left_merged_before=left_merged_before,
            right_segment=right_segment,
            left_translation_before=left_translation_before,
            left_translation_after=list(merged_tl_lines),
            left_speaker_translation_before=left_speaker_translation_before,
            left_speaker_translation_after=merged_speaker_translation,
            source_affected=source_affected,
        )
        self.structural_undo_stack.append(
            StructuralAction(kind="merge", path=session.path,
                             data=merge_action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        if not self._refresh_after_remove_without_full_rerender(
            session,
            removed_uid=right_uid,
            updated_uids={left_uid},
            focus_uid=left_uid,
            preserve_scroll=True,
        ):
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=left_uid,
                preserve_scroll=True,
            ):
                self._render_session(session, focus_uid=left_uid, preserve_scroll=True)
        self.statusBar().showMessage("Merged neighboring dialogue blocks.")

    def _on_reset_requested(self, uid: str) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return
        segment = self.current_segment_lookup.get(uid)
        if segment is None:
            return

        if self._is_translator_mode():
            tl_before = self._normalize_translation_lines(
                segment.translation_lines)
            speaker_before = segment.translation_speaker.strip()
            tl_after = self._normalize_translation_lines(
                segment.original_translation_lines)
            speaker_after = segment.original_translation_speaker.strip()
            if tl_before == tl_after and speaker_before == speaker_after:
                self.statusBar().showMessage("Block translation is already reset.")
                return
            segment.translation_lines = list(tl_after)
            segment.translation_speaker = speaker_after
            segment.disable_line1_speaker_inference = bool(
                segment.original_disable_line1_speaker_inference
            )
            segment.force_line1_speaker_inference = bool(
                segment.original_force_line1_speaker_inference
            )
            if speaker_after:
                self.speaker_translation_map[
                    self._normalize_speaker_key(segment.speaker_name)
                ] = speaker_after
            self._refresh_dirty_state(session)
            if not self._refresh_after_text_reset_without_full_rerender(
                session,
                uid=uid,
            ):
                if not self._refresh_after_structure_change_without_full_rerender(
                    session,
                    focus_uid=uid,
                    preserve_scroll=True,
                ):
                    self._render_session(session, focus_uid=uid, preserve_scroll=True)
            self.statusBar().showMessage("Reset translation block.")
            return

        lines_before = list(segment.lines)
        merged_before = list(segment.merged_segments)
        line1_inference_before = bool(segment.disable_line1_speaker_inference)
        line1_force_before = bool(segment.force_line1_speaker_inference)
        restored_segments = [
            merged for merged in merged_before
            if self._find_segment_index_by_uid(session, merged.uid) < 0
        ]
        restored_count = 0
        if restored_segments:
            restored_count = self._restore_merged_segments_after(
                session, uid, restored_segments)
            segment.merged_segments.clear()
        lines_after = list(segment.original_lines)
        segment.lines = list(lines_after)
        segment.source_lines = list(segment.lines)
        line1_inference_after = bool(
            segment.original_disable_line1_speaker_inference)
        segment.disable_line1_speaker_inference = line1_inference_after
        line1_force_after = bool(
            segment.original_force_line1_speaker_inference)
        segment.force_line1_speaker_inference = line1_force_after
        changed = (
            bool(merged_before)
            or lines_before != lines_after
            or line1_inference_before != line1_inference_after
            or line1_force_before != line1_force_after
        )
        if changed:
            reset_action = ResetBlockAction(
                path=session.path,
                uid=uid,
                lines_before=lines_before,
                lines_after=lines_after,
                merged_before=merged_before,
                restored_segments=restored_segments,
                line1_inference_disabled_before=line1_inference_before,
                line1_inference_disabled_after=line1_inference_after,
                line1_inference_forced_before=line1_force_before,
                line1_inference_forced_after=line1_force_after,
            )
            self.structural_undo_stack.append(
                StructuralAction(
                    kind="reset", path=session.path, data=reset_action)
            )
            self.structural_redo_stack.clear()
        self._refresh_dirty_state(session)
        fast_path_ok = (
            changed
            and (not bool(merged_before))
            and restored_count == 0
            and self._refresh_after_text_reset_without_full_rerender(
                session,
                uid=uid,
            )
        )
        if not fast_path_ok:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=uid,
                preserve_scroll=True,
            ):
                self._render_session(session, focus_uid=uid, preserve_scroll=True)
        if restored_count > 0:
            block_label = "block" if restored_count == 1 else "blocks"
            self.statusBar().showMessage(
                f"Reset block and restored {restored_count} merged {block_label}.")
        else:
            self.statusBar().showMessage("Reset block.")

    def _on_delete_requested(self, uid: str) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        translator_mode = self._is_translator_mode()
        segment_index = self._find_segment_index_by_uid(session, uid)
        if segment_index < 0:
            return
        segment = session.segments[segment_index]
        if not segment.is_structural_dialogue:
            self.statusBar().showMessage(
                "Delete is only available for standard dialogue blocks.")
            return
        if translator_mode and not (segment.inserted or segment.translation_only):
            self.statusBar().showMessage(
                "In Translator Edit mode, only translation-only blocks can be deleted."
            )
            return

        if len(session.segments) <= 1:
            QMessageBox.warning(
                cast(QWidget, self),
                "Cannot delete",
                "At least one dialogue block must remain in this file view.",
            )
            return

        button = QMessageBox.question(
            cast(QWidget, self),
            "Delete block",
            "Delete this dialogue block?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if button != QMessageBox.StandardButton.Yes:
            return

        bundle_index = -1
        token_index = -1
        bundle, found_token_index = self._find_segment_token(session, uid)
        if bundle is not None and found_token_index >= 0:
            token_index = found_token_index
            try:
                bundle_index = session.bundles.index(bundle)
            except ValueError:
                bundle_index = -1
        action = DeletedBlockAction(
            path=session.path,
            uid=uid,
            bundle_index=bundle_index,
            token_index=token_index,
            segment_index=segment_index,
            segment=segment,
        )

        if bundle is not None and token_index >= 0:
            del bundle.tokens[token_index]
        del session.segments[segment_index]

        self.structural_undo_stack.append(
            StructuralAction(kind="delete", path=session.path, data=action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        if not self._refresh_after_remove_without_full_rerender(
            session,
            removed_uid=uid,
            preserve_scroll=True,
        ):
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                preserve_scroll=True,
            ):
                self._render_session(session)
        self.statusBar().showMessage("Deleted dialogue block.")

    def _apply_undo_delete(self, action: DeletedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if self._find_segment_index_by_uid(session, action.uid) >= 0:
            return False

        segment_index = max(
            0, min(action.segment_index, len(session.segments)))
        if action.bundle_index >= 0:
            if action.bundle_index >= len(session.bundles):
                return False
            bundle = session.bundles[action.bundle_index]
            token_index = max(0, min(action.token_index, len(bundle.tokens)))
            bundle.tokens.insert(token_index, CommandToken(
                kind="dialogue", segment=action.segment))
        session.segments.insert(segment_index, action.segment)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Undo delete: restored block in {action.path.name}")
        return True

    def _apply_undo_insert(self, action: InsertedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if self._find_segment_index_by_uid(session, action.uid) < 0:
            return False
        if not self._remove_segment_by_uid(session, action.uid):
            return False

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                preserve_scroll=True,
            ):
                self._render_session(session, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Undo insert: removed block in {action.path.name}")
        return True

    def _apply_redo_insert(self, action: InsertedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if self._find_segment_index_by_uid(session, action.uid) >= 0:
            return False

        segment_index = max(
            0, min(action.segment_index, len(session.segments)))
        if action.bundle_index >= 0:
            if action.bundle_index >= len(session.bundles):
                return False
            bundle = session.bundles[action.bundle_index]
            token_index = max(0, min(action.token_index, len(bundle.tokens)))
            bundle.tokens.insert(token_index, CommandToken(
                kind="dialogue", segment=action.segment))
        session.segments.insert(segment_index, action.segment)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Redo insert: restored block in {action.path.name}")
        return True

    def _apply_redo_delete(self, action: DeletedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        segment_index = self._find_segment_index_by_uid(session, action.uid)
        if segment_index < 0:
            return False

        if action.bundle_index >= 0:
            if action.bundle_index >= len(session.bundles):
                return False
            bundle = session.bundles[action.bundle_index]
            token_index = self._find_bundle_token_index_by_uid(bundle, action.uid)
            if token_index < 0:
                return False
            del bundle.tokens[token_index]
        del session.segments[segment_index]

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                preserve_scroll=True,
            ):
                self._render_session(session, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Redo delete: removed block in {action.path.name}")
        return True

    def _apply_undo_reset(self, action: ResetBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        segment_index = self._find_segment_index_by_uid(session, action.uid)
        if segment_index < 0:
            return False

        for restored in action.restored_segments:
            if self._find_segment_index_by_uid(session, restored.uid) < 0:
                return False
        for restored in action.restored_segments:
            if not self._remove_segment_by_uid(session, restored.uid):
                return False

        segment = session.segments[segment_index]
        segment.lines = list(action.lines_before)
        segment.source_lines = list(segment.lines)
        segment.merged_segments = list(action.merged_before)
        segment.disable_line1_speaker_inference = bool(
            action.line1_inference_disabled_before
        )
        segment.force_line1_speaker_inference = bool(
            action.line1_inference_forced_before
        )

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Undo reset: restored pre-reset state in {action.path.name}")
        return True

    def _apply_redo_reset(self, action: ResetBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        segment_index = self._find_segment_index_by_uid(session, action.uid)
        if segment_index < 0:
            return False
        for restored in action.restored_segments:
            if self._find_segment_index_by_uid(session, restored.uid) >= 0:
                return False

        restored_count = self._restore_merged_segments_after(
            session, action.uid, action.merged_before)
        if restored_count < len(action.merged_before):
            return False

        segment = session.segments[segment_index]
        segment.lines = list(action.lines_after)
        segment.source_lines = list(segment.lines)
        segment.merged_segments.clear()
        segment.disable_line1_speaker_inference = bool(
            action.line1_inference_disabled_after
        )
        segment.force_line1_speaker_inference = bool(
            action.line1_inference_forced_after
        )

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Redo reset: reapplied reset in {action.path.name}")
        return True

    def _apply_undo_split_overflow(self, action: SplitOverflowAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        source_index = self._find_segment_index_by_uid(
            session, action.source_uid)
        if source_index < 0:
            return False
        if self._find_segment_index_by_uid(session, action.moved_uid) < 0:
            return False
        if not self._remove_segment_by_uid(session, action.moved_uid):
            return False

        source_index = self._find_segment_index_by_uid(
            session, action.source_uid)
        if source_index < 0:
            return False
        source_segment = session.segments[source_index]
        source_segment.lines = list(action.source_lines_before)
        source_segment.source_lines = list(source_segment.lines)
        if action.source_translation_before:
            source_segment.translation_lines = self._normalize_translation_lines(
                action.source_translation_before)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.source_uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.source_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Undo overflow split: restored block in {action.path.name}")
        return True

    def _apply_redo_split_overflow(self, action: SplitOverflowAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if self._find_segment_index_by_uid(session, action.moved_uid) >= 0:
            return False

        source_index = self._find_segment_index_by_uid(
            session, action.source_uid)
        if source_index < 0:
            return False
        source_segment = session.segments[source_index]
        bundle: Optional[CommandBundle] = None
        token_index = -1
        if not action.moved_segment.translation_only:
            bundle, token_index = self._find_segment_token(
                session, action.source_uid)
            if bundle is None or token_index < 0:
                return False

        source_segment.lines = list(action.source_lines_after)
        source_segment.source_lines = list(source_segment.lines)
        if action.source_translation_after:
            source_segment.translation_lines = self._normalize_translation_lines(
                action.source_translation_after)
        if bundle is not None:
            bundle.tokens.insert(
                token_index + 1, CommandToken(kind="dialogue", segment=action.moved_segment))
        session.segments.insert(source_index + 1, action.moved_segment)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.moved_uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.moved_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Redo overflow split: moved lines in {action.path.name}")
        return True

    def _apply_undo_merge(self, action: MergeBlocksAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        left_index = self._find_segment_index_by_uid(session, action.left_uid)
        if left_index < 0:
            return False
        if self._find_segment_index_by_uid(session, action.right_uid) >= 0:
            return False

        left_segment = session.segments[left_index]
        if action.source_affected:
            restored = self._restore_merged_segments_after(
                session, action.left_uid, [action.right_segment])
            if restored <= 0:
                return False
        else:
            session.segments.insert(left_index + 1, action.right_segment)
        if action.source_affected:
            left_segment.lines = list(action.left_lines_before)
            left_segment.source_lines = list(left_segment.lines)
        if action.left_translation_before:
            left_segment.translation_lines = self._normalize_translation_lines(
                action.left_translation_before)
        left_segment.translation_speaker = action.left_speaker_translation_before
        if left_segment.translation_speaker:
            self.speaker_translation_map[
                self._normalize_speaker_key(left_segment.speaker_name)
            ] = left_segment.translation_speaker
        left_segment.merged_segments = list(action.left_merged_before)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.left_uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.left_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Undo merge: restored block in {action.path.name}")
        return True

    def _apply_redo_merge(self, action: MergeBlocksAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        left_index = self._find_segment_index_by_uid(session, action.left_uid)
        right_index = self._find_segment_index_by_uid(
            session, action.right_uid)
        if left_index < 0 or right_index < 0:
            return False
        if right_index != left_index + 1:
            return False

        left_segment = session.segments[left_index]
        right_segment = session.segments[right_index]
        left_bundle: Optional[CommandBundle] = None
        right_bundle: Optional[CommandBundle] = None
        left_token_index = -1
        right_token_index = -1
        if action.source_affected:
            left_bundle, left_token_index = self._find_segment_token(
                session, action.left_uid)
            right_bundle, right_token_index = self._find_segment_token(
                session, action.right_uid)
            if left_bundle is None or right_bundle is None:
                return False
            if left_bundle is not right_bundle:
                return False
            if right_token_index != left_token_index + 1:
                return False

        if action.source_affected:
            left_segment.lines = list(action.left_lines_after)
            left_segment.source_lines = list(left_segment.lines)
        if action.left_translation_after:
            left_segment.translation_lines = self._normalize_translation_lines(
                action.left_translation_after)
        left_segment.translation_speaker = action.left_speaker_translation_after
        if left_segment.translation_speaker:
            self.speaker_translation_map[
                self._normalize_speaker_key(left_segment.speaker_name)
            ] = left_segment.translation_speaker
        if action.source_affected:
            left_segment.merged_segments = list(
                action.left_merged_before) + [right_segment]
        else:
            left_segment.merged_segments = list(action.left_merged_before)
        if action.source_affected and left_bundle is not None and right_token_index >= 0:
            del left_bundle.tokens[right_token_index]
        del session.segments[right_index]

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=action.left_uid,
                preserve_scroll=True,
            ):
                self._render_session(
                    session, focus_uid=action.left_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(
            f"Redo merge: merged blocks in {action.path.name}")
        return True

    def _undo_last_structural_action(self) -> bool:
        while self.structural_undo_stack:
            action = self.structural_undo_stack.pop()
            ok = False
            if action.kind == "insert":
                ok = self._apply_undo_insert(
                    cast(InsertedBlockAction, action.data))
            elif action.kind == "delete":
                ok = self._apply_undo_delete(
                    cast(DeletedBlockAction, action.data))
            elif action.kind == "reset":
                ok = self._apply_undo_reset(
                    cast(ResetBlockAction, action.data))
            elif action.kind == "split_overflow":
                ok = self._apply_undo_split_overflow(
                    cast(SplitOverflowAction, action.data))
            elif action.kind == "merge":
                ok = self._apply_undo_merge(
                    cast(MergeBlocksAction, action.data))
            if ok:
                self.structural_redo_stack.append(action)
                return True
        return False

    def _redo_last_structural_action(self) -> bool:
        while self.structural_redo_stack:
            action = self.structural_redo_stack.pop()
            ok = False
            if action.kind == "insert":
                ok = self._apply_redo_insert(
                    cast(InsertedBlockAction, action.data))
            elif action.kind == "delete":
                ok = self._apply_redo_delete(
                    cast(DeletedBlockAction, action.data))
            elif action.kind == "reset":
                ok = self._apply_redo_reset(
                    cast(ResetBlockAction, action.data))
            elif action.kind == "split_overflow":
                ok = self._apply_redo_split_overflow(
                    cast(SplitOverflowAction, action.data))
            elif action.kind == "merge":
                ok = self._apply_redo_merge(
                    cast(MergeBlocksAction, action.data))
            if ok:
                self.structural_undo_stack.append(action)
                return True
        return False
