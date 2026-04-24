from __future__ import annotations

from concurrent.futures import Future
import copy
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
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
    CONTROL_TOKEN_RE,
    smart_collapse_lines,
    split_lines_by_sentence_boundary_row_budget,
    total_display_rows,
    visible_length,
)

class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


_SMART_COLLAPSE_RULE_COUNTER_KEYS = (
    "soft_rule",
    "comma",
    "colon_triplet",
    "ellipsis_lowercase",
    "no_punctuation",
)

_SMART_COLLAPSE_PROJECTION_MODE_PRIORITY = {
    "none": 0,
    "soft_only": 1,
    "all": 2,
}


def _normalize_smart_collapse_projection_mode(value: Any) -> str:
    mode = str(value).strip().lower()
    if mode in _SMART_COLLAPSE_PROJECTION_MODE_PRIORITY:
        return mode
    return "none"


def _merge_smart_collapse_projection_modes(current: str, incoming: str) -> str:
    current_mode = _normalize_smart_collapse_projection_mode(current)
    incoming_mode = _normalize_smart_collapse_projection_mode(incoming)
    if (
        _SMART_COLLAPSE_PROJECTION_MODE_PRIORITY[incoming_mode]
        > _SMART_COLLAPSE_PROJECTION_MODE_PRIORITY[current_mode]
    ):
        return incoming_mode
    return current_mode


def _coerce_smart_collapse_rule_counts(
    raw_rule_counts: dict[str, Any],
    *,
    fallback_counts: Optional[dict[str, int]] = None,
) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key in _SMART_COLLAPSE_RULE_COUNTER_KEYS:
        raw_value: Any
        if key in raw_rule_counts:
            raw_value = raw_rule_counts.get(key)
        elif fallback_counts is not None:
            raw_value = fallback_counts.get(key, 0)
        else:
            raw_value = 0
        try:
            parsed_value = int(raw_value)
        except (TypeError, ValueError):
            parsed_value = 0
        normalized[key] = max(0, parsed_value)
    return normalized


class StructuralEditingMixin(_EditorHostTypingFallback):
    _COLOR_CODE_RE = re.compile(r"\\[Cc]\[(\d+)\]")
    _LEADING_COLOR_CODE_PREFIX_RE = re.compile(r"^\s*(?:\\[Cc]\[\d+\])+")
    _COLOR_CODE_AT_LINE_START_RE = re.compile(r"^\s*\\[Cc]\[(\d+)\]")
    _TRAILING_RESET_COLOR_RE = re.compile(r"\\[Cc]\[0\]\s*$")
    _DOUBLE_QUOTE_OPENERS = frozenset(('"', "“"))
    _DOUBLE_QUOTE_CLOSERS = frozenset(('"', "”"))
    _SINGLE_QUOTE_OPENERS = frozenset(("'", "‘"))
    _SINGLE_QUOTE_CLOSERS = frozenset(("'", "’"))
    _SPLIT_WRAPPER_VARIANTS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
        (_DOUBLE_QUOTE_OPENERS, _DOUBLE_QUOTE_CLOSERS),
        (_SINGLE_QUOTE_OPENERS, _SINGLE_QUOTE_CLOSERS),
        (frozenset(("(", "（")), frozenset((")", "）"))),
        (frozenset(("[", "［")), frozenset(("]", "］"))),
        (frozenset(("{", "｛")), frozenset(("}", "｝"))),
        (frozenset(("「",)), frozenset(("」",))),
        (frozenset(("『",)), frozenset(("』",))),
        (frozenset(("【",)), frozenset(("】",))),
        (frozenset(("〈",)), frozenset(("〉",))),
        (frozenset(("《",)), frozenset(("》",))),
        (frozenset(("〔",)), frozenset(("〕",))),
        (frozenset(("<",)), frozenset((">",))),
        (frozenset(("«",)), frozenset(("»",))),
    )

    def _advance_undo_pipeline_revision(self) -> int:
        raw_revision = getattr(self, "_undo_pipeline_revision", 0)
        try:
            revision = int(raw_revision)
        except Exception:
            revision = 0
        revision += 1
        setattr(self, "_undo_pipeline_revision", revision)
        return revision

    def _reset_undo_pipeline_state(self) -> None:
        setattr(self, "_undo_pipeline_revision", 0)
        setattr(self, "_last_text_edit_revision", 0)
        setattr(self, "_last_structural_edit_revision", 0)
        setattr(self, "_last_undo_pipeline_domain", "")
        setattr(self, "_undo_pipeline_text_stack_operation", False)

    def _mark_text_edit_for_undo_pipeline(self) -> None:
        setattr(
            self,
            "_last_text_edit_revision",
            self._advance_undo_pipeline_revision(),
        )
        if not bool(getattr(self, "_undo_pipeline_text_stack_operation", False)):
            setattr(self, "_last_undo_pipeline_domain", "")

    def _mark_text_undo_for_undo_pipeline(self) -> None:
        setattr(self, "_last_undo_pipeline_domain", "text")

    def _mark_text_redo_for_undo_pipeline(self) -> None:
        setattr(self, "_last_undo_pipeline_domain", "")

    def _mark_structural_edit_for_undo_pipeline(self) -> None:
        setattr(
            self,
            "_last_structural_edit_revision",
            self._advance_undo_pipeline_revision(),
        )
        setattr(self, "_last_undo_pipeline_domain", "")

    def _mark_structural_undo_for_undo_pipeline(self) -> None:
        setattr(self, "_last_undo_pipeline_domain", "structural")

    def _mark_structural_redo_for_undo_pipeline(self) -> None:
        self._mark_structural_edit_for_undo_pipeline()

    def _text_edit_blocks_structural_undo_fallback(self) -> bool:
        try:
            last_text = int(getattr(self, "_last_text_edit_revision", 0))
        except Exception:
            last_text = 0
        try:
            last_structural = int(
                getattr(self, "_last_structural_edit_revision", 0)
            )
        except Exception:
            last_structural = 0
        return last_text >= last_structural

    def _push_structural_undo_action(self, action: StructuralAction) -> None:
        self.structural_undo_stack.append(action)
        self.structural_redo_stack.clear()
        self._mark_structural_edit_for_undo_pipeline()

    def _structure_fast_rerender_supported(self) -> bool:
        # Structural fast-refresh logic predates pagination and assumes that
        # rendered UID order mirrors the full display list. With pagination
        # enabled this assumption breaks, so fall back to the canonical
        # paginated render path for correctness.
        return not hasattr(self, "_pagination_page_by_scope_key")

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
            self._refresh_translation_chain_widget_statuses(
                session,
                segment,
            )
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
        max_lines_limit: Optional[int] = None,
        only_overflowing_blocks: bool = False,
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
        max_lines_spin = getattr(self, "max_lines_spin", None)
        max_lines_default = (
            int(max_lines_spin.value())
            if max_lines_spin is not None and hasattr(max_lines_spin, "value")
            else 4
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
        max_lines = (
            max_lines_default
            if max_lines_limit is None
            else int(max_lines_limit)
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
                if only_overflowing_blocks and not self._smart_collapse_lines_overflow(
                    segment,
                    current_lines,
                    line_width=line_width,
                    max_lines=max_lines,
                ):
                    continue
                if collapsed_lines == current_lines:
                    continue
                projected_blocks += 1
                session_will_change = True
            if session_will_change:
                projected_files += 1
        return projected_blocks, projected_files

    def _smart_collapse_lines_overflow(
        self,
        segment: DialogueSegment,
        lines: list[str],
        *,
        line_width: int,
        max_lines: int,
    ) -> bool:
        normalizer = getattr(self, "_normalize_problem_lines_for_segment", None)
        normalized: list[str]
        if callable(normalizer):
            try:
                normalized_raw = normalizer(segment, lines)
            except Exception:
                normalized_raw = self._normalize_translation_lines(lines)
            normalized = self._normalize_translation_lines(normalized_raw)
        else:
            normalized = self._normalize_translation_lines(lines)
        if any(visible_length(line) > max(1, int(line_width)) for line in normalized):
            return True
        return total_display_rows(normalized) > float(max(1, int(max_lines)))

    def _prompt_smart_collapse_all_options(
        self,
    ) -> Optional[tuple[bool, bool, bool, bool, float, bool, bool]]:
        dialog = QDialog(cast(QWidget, self))
        dialog.setWindowTitle("Smart Collapse All")
        dialog.resize(500, 330)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        soft_rule_base_text = "Collapse if previous line is shorter than threshold"
        comma_rule_base_text = "Collapse if previous line ends with comma (, 、 ，)"
        colon_rule_base_text = "Collapse if previous line ends with ..."
        ellipsis_rule_base_text = (
            "Collapse if previous line ends with ... and next starts lowercase"
        )
        no_punct_rule_base_text = "Collapse if previous line ends without punctuation"

        soft_rule_check = QCheckBox(soft_rule_base_text)
        soft_rule_check.setChecked(
            bool(getattr(self, "smart_collapse_soft_ratio_rule_enabled", True))
        )

        allow_comma_check = QCheckBox(comma_rule_base_text)
        allow_comma_check.setChecked(
            bool(getattr(self, "smart_collapse_allow_comma_endings", False))
        )

        allow_colon_triplet_check = QCheckBox(colon_rule_base_text)
        allow_colon_triplet_check.setChecked(
            bool(getattr(self, "smart_collapse_allow_colon_triplet_endings", False))
        )

        ellipsis_lowercase_rule_check = QCheckBox(ellipsis_rule_base_text)
        ellipsis_lowercase_rule_check.setChecked(
            bool(getattr(self, "smart_collapse_ellipsis_lowercase_rule", False))
        )

        no_punctuation_check = QCheckBox(no_punct_rule_base_text)
        no_punctuation_check.setChecked(
            bool(getattr(self, "smart_collapse_collapse_if_no_punctuation", True))
        )

        threshold_spin = QSpinBox(dialog)
        threshold_spin.setRange(0, 100)
        threshold_spin.setSuffix("%")
        threshold_spin.setValue(
            int(getattr(self, "smart_collapse_soft_ratio_percent", 50))
        )
        threshold_spin.setEnabled(soft_rule_check.isChecked())
        soft_rule_check.toggled.connect(threshold_spin.setEnabled)

        scope_all_files_check = QCheckBox("Apply to all dialogue files")
        scope_all_files_check.setChecked(False)
        only_overflowing_check = QCheckBox("Only collapse currently overflowing blocks")
        only_overflowing_check.setChecked(False)

        def _build_section_title(text: str) -> QLabel:
            title = QLabel(text, dialog)
            title.setStyleSheet("font-weight: 600; color: #4b5563;")
            return title

        def _build_section_divider() -> QFrame:
            divider = QFrame(dialog)
            divider.setFrameShape(QFrame.Shape.HLine)
            divider.setFrameShadow(QFrame.Shadow.Sunken)
            return divider

        layout.addWidget(_build_section_title("Rules"))

        rules_container = QWidget(dialog)
        rules_layout = QVBoxLayout(rules_container)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        rules_layout.setSpacing(6)
        rules_layout.addWidget(soft_rule_check)

        threshold_row = QWidget(rules_container)
        threshold_row_layout = QHBoxLayout(threshold_row)
        threshold_row_layout.setContentsMargins(22, 0, 0, 0)
        threshold_row_layout.setSpacing(8)
        threshold_label = QLabel("Short-line threshold", threshold_row)
        threshold_label.setEnabled(soft_rule_check.isChecked())
        soft_rule_check.toggled.connect(threshold_label.setEnabled)
        threshold_row_layout.addWidget(threshold_label)
        threshold_row_layout.addWidget(threshold_spin, 0, Qt.AlignmentFlag.AlignLeft)
        threshold_row_layout.addStretch(1)
        rules_layout.addWidget(threshold_row)
        rules_layout.addWidget(allow_comma_check)
        rules_layout.addWidget(allow_colon_triplet_check)
        rules_layout.addWidget(ellipsis_lowercase_rule_check)
        rules_layout.addWidget(no_punctuation_check)
        layout.addWidget(rules_container)

        layout.addWidget(_build_section_divider())

        layout.addWidget(_build_section_title("Scope"))
        layout.addWidget(scope_all_files_check)
        layout.addWidget(only_overflowing_check)

        layout.addWidget(_build_section_divider())

        layout.addWidget(_build_section_title("Projected"))
        projected_row = QWidget(dialog)
        projected_row_layout = QHBoxLayout(projected_row)
        projected_row_layout.setContentsMargins(0, 0, 0, 0)
        projected_row_layout.setSpacing(8)
        projected_label = QLabel("Projected fixes", projected_row)
        projected_count_label = QLabel("", projected_row)
        projected_count_label.setWordWrap(True)
        projected_count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        projected_row_layout.addWidget(projected_label, 0)
        projected_row_layout.addWidget(projected_count_label, 1)
        layout.addWidget(projected_row)

        projection_timer = QTimer(dialog)
        projection_timer.setSingleShot(True)
        projection_timer.setInterval(80)
        projection_poll_timer = QTimer(dialog)
        projection_poll_timer.setSingleShot(True)
        projection_poll_timer.setInterval(24)
        projection_executor = getattr(self, "audit_worker_executor", None)
        projection_future: Optional[Future[dict[str, Any]]] = None
        projection_future_request_id = 0
        pending_projection_request: Optional[dict[str, Any]] = None
        pending_projection_request_id = 0
        latest_projection_request_id = 0
        latest_projected_count_text = "0 blocks in 0 files"
        cached_rule_counts: dict[str, int] = {}
        rule_counter_cache: dict[tuple[bool, int, bool], dict[str, int]] = {}
        pending_recompute_rule_counts_mode = "none"

        def _counter_suffix(value: int) -> str:
            safe_value = max(0, int(value))
            return f"({safe_value})"

        def _projection_cache_key(
            *,
            apply_all_files: bool,
            soft_ratio_percent: int,
            only_overflowing_blocks: bool,
        ) -> tuple[bool, int, bool]:
            normalized_percent = max(0, min(100, int(soft_ratio_percent)))
            return (
                bool(apply_all_files),
                normalized_percent,
                bool(only_overflowing_blocks),
            )

        def _current_projection_cache_key() -> tuple[bool, int, bool]:
            return _projection_cache_key(
                apply_all_files=bool(scope_all_files_check.isChecked()),
                soft_ratio_percent=int(threshold_spin.value()),
                only_overflowing_blocks=bool(only_overflowing_check.isChecked()),
            )

        def _set_rule_counter_texts(rule_counts: dict[str, int]) -> None:
            soft_count = int(rule_counts.get("soft_rule", 0))
            comma_count = int(rule_counts.get("comma", 0))
            colon_count = int(rule_counts.get("colon_triplet", 0))
            ellipsis_count = int(rule_counts.get("ellipsis_lowercase", 0))
            no_punctuation_count = int(rule_counts.get("no_punctuation", 0))
            soft_rule_check.setText(
                f"{soft_rule_base_text} {_counter_suffix(soft_count)}"
            )
            allow_comma_check.setText(
                f"{comma_rule_base_text} {_counter_suffix(comma_count)}"
            )
            allow_colon_triplet_check.setText(
                f"{colon_rule_base_text} {_counter_suffix(colon_count)}"
            )
            ellipsis_lowercase_rule_check.setText(
                f"{ellipsis_rule_base_text} {_counter_suffix(ellipsis_count)}"
            )
            no_punctuation_check.setText(
                f"{no_punct_rule_base_text} {_counter_suffix(no_punctuation_count)}"
            )

        _set_rule_counter_texts(cached_rule_counts)

        def _set_projected_count_label_result(
            projected_blocks: int,
            projected_files: int,
        ) -> None:
            nonlocal latest_projected_count_text
            block_label = "block" if projected_blocks == 1 else "blocks"
            file_label = "file" if projected_files == 1 else "files"
            latest_projected_count_text = (
                f"{projected_blocks} {block_label} in {projected_files} {file_label}"
            )
            projected_count_label.setStyleSheet("")
            projected_count_label.setText(latest_projected_count_text)

        def _set_projected_count_label_calculating() -> None:
            base_text = latest_projected_count_text.strip()
            if not base_text:
                base_text = "0 blocks in 0 files"
            projected_count_label.setStyleSheet("color: #9ca3af;")
            projected_count_label.setText(f"{base_text}...")

        def _build_projection_request(
            *,
            recompute_rule_counts_mode: str,
        ) -> dict[str, Any]:
            normalized_mode = _normalize_smart_collapse_projection_mode(
                recompute_rule_counts_mode
            )
            return {
                "recompute_rule_counts_mode": normalized_mode,
                "soft_rule_enabled": bool(soft_rule_check.isChecked()),
                "soft_ratio_percent": int(threshold_spin.value()),
                "allow_comma_endings": bool(allow_comma_check.isChecked()),
                "allow_colon_triplet_endings": bool(
                    allow_colon_triplet_check.isChecked()
                ),
                "ellipsis_lowercase_rule": bool(
                    ellipsis_lowercase_rule_check.isChecked()
                ),
                "collapse_if_no_punctuation": bool(no_punctuation_check.isChecked()),
                "apply_all_files": bool(scope_all_files_check.isChecked()),
                "only_overflowing_blocks": bool(only_overflowing_check.isChecked()),
                "infer_speaker_enabled": bool(self.infer_speaker_check.isChecked()),
                "thin_width_limit": int(self.thin_width_spin.value()),
                "wide_width_limit": int(self.wide_width_spin.value()),
                "max_lines_limit": int(self.max_lines_spin.value()),
            }

        def _compute_projection_request(
            request: dict[str, Any],
        ) -> dict[str, Any]:
            soft_ratio_percent = max(0, min(100, int(request["soft_ratio_percent"])))
            infer_speaker_enabled = bool(request["infer_speaker_enabled"])
            thin_width_limit = int(request["thin_width_limit"])
            wide_width_limit = int(request["wide_width_limit"])
            max_lines_limit = int(request["max_lines_limit"])
            apply_all_files = bool(request["apply_all_files"])
            only_overflowing_blocks = bool(request["only_overflowing_blocks"])
            recompute_rule_counts_mode = _normalize_smart_collapse_projection_mode(
                request.get("recompute_rule_counts_mode", "none")
            )

            def _count_for_options(
                *,
                soft_rule_enabled: bool,
                allow_comma_endings: bool,
                allow_colon_triplet_endings: bool,
                ellipsis_lowercase_rule: bool,
                collapse_if_no_punctuation: bool,
            ) -> tuple[int, int]:
                min_soft_ratio = (
                    float(soft_ratio_percent) / 100.0 if soft_rule_enabled else 0.0
                )
                return self._count_projected_smart_collapse_changes(
                    allow_comma_endings=allow_comma_endings,
                    allow_colon_triplet_endings=allow_colon_triplet_endings,
                    ellipsis_lowercase_rule=ellipsis_lowercase_rule,
                    collapse_if_no_punctuation=collapse_if_no_punctuation,
                    min_soft_ratio=min_soft_ratio,
                    apply_all_files=apply_all_files,
                    infer_speaker_enabled=infer_speaker_enabled,
                    thin_width_limit=thin_width_limit,
                    wide_width_limit=wide_width_limit,
                    max_lines_limit=max_lines_limit,
                    only_overflowing_blocks=only_overflowing_blocks,
                )

            soft_rule_enabled = bool(request["soft_rule_enabled"])
            allow_comma_endings = bool(request["allow_comma_endings"])
            allow_colon_triplet_endings = bool(request["allow_colon_triplet_endings"])
            ellipsis_lowercase_rule = bool(request["ellipsis_lowercase_rule"])
            collapse_if_no_punctuation = bool(request["collapse_if_no_punctuation"])

            base_blocks, base_files = _count_for_options(
                soft_rule_enabled=soft_rule_enabled,
                allow_comma_endings=allow_comma_endings,
                allow_colon_triplet_endings=allow_colon_triplet_endings,
                ellipsis_lowercase_rule=ellipsis_lowercase_rule,
                collapse_if_no_punctuation=collapse_if_no_punctuation,
            )
            payload: dict[str, Any] = {
                "base_blocks": base_blocks,
                "base_files": base_files,
                "recompute_rule_counts_mode": recompute_rule_counts_mode,
                "scope_all_files": apply_all_files,
                "soft_ratio_percent": soft_ratio_percent,
                "only_overflowing_blocks": only_overflowing_blocks,
            }
            if recompute_rule_counts_mode == "none":
                return payload

            soft_only_blocks, _soft_only_files = _count_for_options(
                soft_rule_enabled=True,
                allow_comma_endings=False,
                allow_colon_triplet_endings=False,
                ellipsis_lowercase_rule=False,
                collapse_if_no_punctuation=False,
            )
            rule_counts: dict[str, int] = {"soft_rule": max(0, soft_only_blocks)}

            if recompute_rule_counts_mode == "all":
                comma_only_blocks, _comma_only_files = _count_for_options(
                    soft_rule_enabled=False,
                    allow_comma_endings=True,
                    allow_colon_triplet_endings=False,
                    ellipsis_lowercase_rule=False,
                    collapse_if_no_punctuation=False,
                )
                colon_only_blocks, _colon_only_files = _count_for_options(
                    soft_rule_enabled=False,
                    allow_comma_endings=False,
                    allow_colon_triplet_endings=True,
                    ellipsis_lowercase_rule=False,
                    collapse_if_no_punctuation=False,
                )
                ellipsis_only_blocks, _ellipsis_only_files = _count_for_options(
                    soft_rule_enabled=False,
                    allow_comma_endings=False,
                    allow_colon_triplet_endings=False,
                    ellipsis_lowercase_rule=True,
                    collapse_if_no_punctuation=False,
                )
                no_punctuation_only_blocks, _no_punctuation_only_files = _count_for_options(
                    soft_rule_enabled=False,
                    allow_comma_endings=False,
                    allow_colon_triplet_endings=False,
                    ellipsis_lowercase_rule=False,
                    collapse_if_no_punctuation=True,
                )
                rule_counts["comma"] = max(0, comma_only_blocks)
                rule_counts["colon_triplet"] = max(0, colon_only_blocks)
                rule_counts["ellipsis_lowercase"] = max(0, ellipsis_only_blocks)
                rule_counts["no_punctuation"] = max(0, no_punctuation_only_blocks)

            payload["rule_counts"] = rule_counts
            return payload

        def _apply_projection_payload(payload: dict[str, Any]) -> None:
            nonlocal cached_rule_counts
            base_blocks = int(payload.get("base_blocks", 0))
            base_files = int(payload.get("base_files", 0))
            _set_projected_count_label_result(base_blocks, base_files)
            recompute_rule_counts_mode = _normalize_smart_collapse_projection_mode(
                payload.get("recompute_rule_counts_mode", "none")
            )
            if recompute_rule_counts_mode == "none":
                return
            raw_rule_counts = payload.get("rule_counts")
            if isinstance(raw_rule_counts, dict):
                cache_key = _projection_cache_key(
                    apply_all_files=bool(payload.get("scope_all_files", False)),
                    soft_ratio_percent=int(payload.get("soft_ratio_percent", 0)),
                    only_overflowing_blocks=bool(
                        payload.get("only_overflowing_blocks", False)
                    ),
                )
                if recompute_rule_counts_mode == "all":
                    parsed_rule_counts = _coerce_smart_collapse_rule_counts(
                        raw_rule_counts
                    )
                else:
                    cached_for_key = rule_counter_cache.get(cache_key)
                    if isinstance(cached_for_key, dict):
                        fallback_counts = cached_for_key
                    else:
                        fallback_counts = cached_rule_counts
                    parsed_rule_counts = _coerce_smart_collapse_rule_counts(
                        raw_rule_counts,
                        fallback_counts=fallback_counts,
                    )
                cached_rule_counts = dict(parsed_rule_counts)
                rule_counter_cache[cache_key] = dict(parsed_rule_counts)
                _set_rule_counter_texts(cached_rule_counts)

        def _start_projection_request(
            request: dict[str, Any],
            request_id: int,
        ) -> None:
            nonlocal projection_future, projection_future_request_id
            projection_submit = getattr(projection_executor, "submit", None)
            if callable(projection_submit):
                try:
                    projection_future = cast(
                        Future[dict[str, Any]],
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
            projection_payload = _compute_projection_request(request)
            if request_id == latest_projection_request_id:
                _apply_projection_payload(projection_payload)

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
                projection_payload = current_future.result()
            except Exception:
                projection_payload = {
                    "base_blocks": 0,
                    "base_files": 0,
                    "recompute_rule_counts_mode": "none",
                }
            if completed_request_id == latest_projection_request_id:
                _apply_projection_payload(projection_payload)
            if pending_projection_request is None:
                return
            next_request = pending_projection_request
            next_request_id = pending_projection_request_id
            pending_projection_request = None
            pending_projection_request_id = 0
            _start_projection_request(next_request, next_request_id)

        projection_poll_timer.timeout.connect(_poll_projection_future)

        def _dispatch_projected_count_refresh() -> None:
            nonlocal latest_projection_request_id, pending_projection_request, pending_projection_request_id, pending_recompute_rule_counts_mode
            latest_projection_request_id += 1
            request_id = latest_projection_request_id
            recompute_mode = pending_recompute_rule_counts_mode
            pending_recompute_rule_counts_mode = "none"
            request = _build_projection_request(
                recompute_rule_counts_mode=recompute_mode
            )
            _set_projected_count_label_calculating()
            if projection_future is not None:
                pending_projection_request = request
                pending_projection_request_id = request_id
                return
            _start_projection_request(request, request_id)

        projection_timer.timeout.connect(_dispatch_projected_count_refresh)

        def _schedule_projected_count_refresh(
            *,
            recompute_rule_counts_mode: str = "none",
        ) -> None:
            nonlocal pending_recompute_rule_counts_mode
            pending_recompute_rule_counts_mode = _merge_smart_collapse_projection_modes(
                pending_recompute_rule_counts_mode,
                recompute_rule_counts_mode,
            )
            _set_projected_count_label_calculating()
            projection_timer.start()

        def _restore_cached_rule_counts_for_current_scope_threshold() -> bool:
            nonlocal cached_rule_counts
            cache_key = _current_projection_cache_key()
            cached_for_scope = rule_counter_cache.get(cache_key)
            if not isinstance(cached_for_scope, dict):
                return False
            cached_rule_counts = _coerce_smart_collapse_rule_counts(cached_for_scope)
            _set_rule_counter_texts(cached_rule_counts)
            return True

        def _on_scope_or_overflow_toggled(_checked: bool) -> None:
            if _restore_cached_rule_counts_for_current_scope_threshold():
                _schedule_projected_count_refresh(recompute_rule_counts_mode="none")
                return
            _schedule_projected_count_refresh(recompute_rule_counts_mode="all")

        def _on_threshold_changed(_value: int) -> None:
            if _restore_cached_rule_counts_for_current_scope_threshold():
                _schedule_projected_count_refresh(recompute_rule_counts_mode="none")
                return
            _schedule_projected_count_refresh(recompute_rule_counts_mode="soft_only")

        soft_rule_check.toggled.connect(
            lambda _checked: _schedule_projected_count_refresh()
        )
        allow_comma_check.toggled.connect(
            lambda _checked: _schedule_projected_count_refresh()
        )
        allow_colon_triplet_check.toggled.connect(
            lambda _checked: _schedule_projected_count_refresh()
        )
        ellipsis_lowercase_rule_check.toggled.connect(
            lambda _checked: _schedule_projected_count_refresh()
        )
        no_punctuation_check.toggled.connect(
            lambda _checked: _schedule_projected_count_refresh()
        )
        scope_all_files_check.toggled.connect(_on_scope_or_overflow_toggled)
        only_overflowing_check.toggled.connect(_on_scope_or_overflow_toggled)
        threshold_spin.valueChanged.connect(_on_threshold_changed)

        def _cancel_projection_refresh() -> None:
            nonlocal latest_projection_request_id, pending_projection_request, pending_projection_request_id, pending_recompute_rule_counts_mode
            latest_projection_request_id += 1
            pending_projection_request = None
            pending_projection_request_id = 0
            pending_recompute_rule_counts_mode = "none"
            projection_timer.stop()
            projection_poll_timer.stop()

        dialog.finished.connect(lambda _result: _cancel_projection_refresh())
        _schedule_projected_count_refresh(recompute_rule_counts_mode="all")

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
            bool(only_overflowing_check.isChecked()),
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
            only_overflowing_blocks,
        ) = options
        translator_mode = self._is_translator_mode()
        changed_count = 0
        changed_sessions: list[FileSession] = []
        target_sessions = self._smart_collapse_target_sessions(apply_all_files)
        if not target_sessions:
            return
        max_lines_spin = getattr(self, "max_lines_spin", None)
        max_lines = (
            int(max_lines_spin.value())
            if max_lines_spin is not None and hasattr(max_lines_spin, "value")
            else 4
        )
        for session in target_sessions:
            if self._is_name_index_session(session):
                continue
            session_changed = False
            for segment in session.segments:
                if not self._is_smart_collapse_eligible_segment(segment):
                    continue
                line_width = self._segment_line_width(segment)
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
                        line_width=line_width,
                    )
                    if collapsed_lines == current_lines:
                        continue
                    if only_overflowing_blocks and not self._smart_collapse_lines_overflow(
                        segment,
                        current_lines,
                        line_width=line_width,
                        max_lines=max_lines,
                    ):
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
                        line_width=line_width,
                    )
                    if collapsed_lines == current_lines:
                        continue
                    if only_overflowing_blocks and not self._smart_collapse_lines_overflow(
                        segment,
                        current_lines,
                        line_width=line_width,
                        max_lines=max_lines,
                    ):
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

    def _line_first_visible_content_char_index(self, line: str) -> Optional[int]:
        idx = 0
        text = line or ""
        length = len(text)
        while idx < length:
            char = text[idx]
            if char.isspace():
                idx += 1
                continue
            token_match = CONTROL_TOKEN_RE.match(text, idx)
            if token_match is not None and token_match.start() == idx:
                idx = token_match.end()
                continue
            return idx
        return None

    def _line_last_visible_content_char_index(self, line: str) -> Optional[int]:
        text = line or ""
        end = len(text)
        while end > 0:
            while end > 0 and text[end - 1].isspace():
                end -= 1
            if end <= 0:
                return None

            trailing_token: Optional[re.Match[str]] = None
            for token_match in CONTROL_TOKEN_RE.finditer(text, 0, end):
                if token_match.end() == end:
                    trailing_token = token_match
            if trailing_token is not None:
                end = trailing_token.start()
                continue
            return end - 1
        return None

    def _first_visible_content_char_position(
        self,
        lines: list[str],
        *,
        ignored_exact_lines: Optional[set[str]] = None,
    ) -> Optional[tuple[int, int, str]]:
        ignored = ignored_exact_lines or set()
        for line_idx, line in enumerate(lines):
            if line in ignored:
                continue
            char_idx = self._line_first_visible_content_char_index(line)
            if char_idx is None:
                continue
            return line_idx, char_idx, line[char_idx]
        return None

    def _last_visible_content_char_position(
        self,
        lines: list[str],
        *,
        ignored_exact_lines: Optional[set[str]] = None,
    ) -> Optional[tuple[int, int, str]]:
        ignored = ignored_exact_lines or set()
        for line_idx in range(len(lines) - 1, -1, -1):
            line = lines[line_idx]
            if line in ignored:
                continue
            char_idx = self._line_last_visible_content_char_index(line)
            if char_idx is None:
                continue
            return line_idx, char_idx, line[char_idx]
        return None

    def _insert_opening_quote_into_line(self, line: str, quote_char: str) -> str:
        insert_at = self._line_first_visible_content_char_index(line)
        if insert_at is None:
            return f"{line}{quote_char}"
        return f"{line[:insert_at]}{quote_char}{line[insert_at:]}"

    def _insert_closing_quote_into_line(self, line: str, quote_char: str) -> str:
        insert_after = self._line_last_visible_content_char_index(line)
        if insert_after is None:
            return f"{line}{quote_char}"
        insert_at = insert_after + 1
        return f"{line[:insert_at]}{quote_char}{line[insert_at:]}"

    def _apply_split_overflow_quote_continuity(
        self,
        kept_lines: list[str],
        moved_lines: list[str],
        *,
        ignored_leading_markers: tuple[str, ...] = (),
    ) -> tuple[list[str], list[str]]:
        if not kept_lines or not moved_lines:
            return kept_lines, moved_lines

        ignored = {marker for marker in ignored_leading_markers if marker}
        combined_lines = list(kept_lines) + list(moved_lines)
        opening_boundary = self._first_visible_content_char_position(
            combined_lines,
            ignored_exact_lines=ignored,
        )
        closing_boundary = self._last_visible_content_char_position(
            combined_lines,
            ignored_exact_lines=ignored,
        )
        if opening_boundary is None or closing_boundary is None:
            return kept_lines, moved_lines

        opening_char = opening_boundary[2]
        closing_char = closing_boundary[2]
        opening_set: frozenset[str]
        closing_set: frozenset[str]
        wrapper_variant = next(
            (
                (candidate_openers, candidate_closers)
                for candidate_openers, candidate_closers in self._SPLIT_WRAPPER_VARIANTS
                if (opening_char in candidate_openers and closing_char in candidate_closers)
            ),
            None,
        )
        if wrapper_variant is None:
            return kept_lines, moved_lines
        opening_set, closing_set = wrapper_variant

        kept_boundary = self._last_visible_content_char_position(
            kept_lines,
            ignored_exact_lines=ignored,
        )
        moved_boundary = self._first_visible_content_char_position(
            moved_lines,
            ignored_exact_lines=ignored,
        )
        if kept_boundary is None or moved_boundary is None:
            return kept_lines, moved_lines

        kept_line_idx, _, kept_tail_char = kept_boundary
        moved_line_idx, _, moved_head_char = moved_boundary
        if kept_tail_char not in closing_set:
            kept_lines[kept_line_idx] = self._insert_closing_quote_into_line(
                kept_lines[kept_line_idx],
                closing_char,
            )
        if moved_head_char not in opening_set:
            moved_lines[moved_line_idx] = self._insert_opening_quote_into_line(
                moved_lines[moved_line_idx],
                opening_char,
            )
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
        if not self._structure_fast_rerender_supported():
            return False
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
        if not self._structure_fast_rerender_supported():
            return False
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
        if not self._structure_fast_rerender_supported():
            return False
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
        translated_marker = self._translated_inferred_marker_for_segment(
            right_segment,
            right_marker,
        ) or self._translated_inferred_marker_for_segment(
            left_segment,
            left_marker,
        )
        if (
            translated_marker
            and normalized_right
            and normalized_right[0] == translated_marker
        ):
            trimmed = normalized_right[1:]
            return trimmed if trimmed else [""]
        return normalized_right

    def _translated_inferred_marker_for_segment(
        self,
        segment: DialogueSegment,
        source_marker: str,
    ) -> str:
        marker_text = source_marker if isinstance(source_marker, str) else ""
        if not marker_text:
            return ""
        translated_speaker = segment.translation_speaker.strip()
        if not translated_speaker:
            speaker_key = self._speaker_key_for_segment(segment)
            if speaker_key != NO_SPEAKER_KEY:
                translated_speaker = self._speaker_translation_for_key(speaker_key).strip()
        if not translated_speaker:
            return ""
        leading_match = self._LEADING_COLOR_CODE_PREFIX_RE.match(marker_text)
        prefix = marker_text[:leading_match.end()] if leading_match is not None else ""
        has_trailing_reset = bool(self._TRAILING_RESET_COLOR_RE.search(marker_text))
        translated_line = (
            f"{prefix}{translated_speaker}" if prefix else translated_speaker
        )
        if has_trailing_reset and not self._TRAILING_RESET_COLOR_RE.search(translated_line):
            translated_line = f"{translated_line}\\C[0]"
        return translated_line

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
        self._mark_text_edit_for_undo_pipeline()
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
            sync_actor_duplicates = getattr(
                self,
                "_sync_duplicate_actor_name_translations_for_segment",
                None,
            )
            if callable(sync_actor_duplicates):
                try:
                    sync_actor_duplicates(session, segment)
                except Exception:
                    pass
        else:
            segment.lines = list(lines)
            segment.source_lines = list(segment.lines)
        self._refresh_dirty_state(session)
        if self._is_translator_mode():
            self._refresh_translation_chain_widget_statuses(
                session,
                segment,
            )
            if self._selected_segment_in_translation_chain(
                session,
                segment,
            ):
                self._refresh_translator_detail_panel()

    def _translation_chain_uids_for_segment(
        self,
        segment: DialogueSegment,
        *,
        session: Optional[FileSession] = None,
    ) -> set[str]:
        chain_resolver = getattr(
            self,
            "_logical_translation_chain_for_segment",
            None,
        )
        if not callable(chain_resolver):
            return {segment.uid}
        chain_value: Any = None
        try:
            chain_value = chain_resolver(segment, session=session)
        except TypeError:
            try:
                chain_value = chain_resolver(segment)
            except Exception:
                chain_value = None
        except Exception:
            chain_value = None
        if not isinstance(chain_value, list):
            return {segment.uid}
        uids = {
            candidate.uid
            for candidate in chain_value
            if isinstance(getattr(candidate, "uid", None), str)
        }
        if not uids:
            return {segment.uid}
        return uids

    def _selected_segment_in_translation_chain(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> bool:
        selected_uid = getattr(self, "selected_segment_uid", None)
        if not isinstance(selected_uid, str) or (not selected_uid):
            return False
        return selected_uid in self._translation_chain_uids_for_segment(
            segment,
            session=session,
        )

    def _refresh_translation_chain_widget_statuses(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> None:
        for chain_uid in self._translation_chain_uids_for_segment(
            segment,
            session=session,
        ):
            widget = self.block_widgets.get(chain_uid)
            if widget is None:
                continue
            refresh_status = getattr(widget, "_refresh_status", None)
            if callable(refresh_status):
                try:
                    refresh_status()
                except Exception:
                    continue

    def _line1_inference_match_key(self, segment: DialogueSegment) -> str:
        if not segment.is_structural_dialogue:
            return ""
        if segment.speaker_name != NO_SPEAKER_KEY:
            return ""
        source_lines: list[str]
        source_lines_resolver = cast(
            Callable[[DialogueSegment], list[str]] | None,
            getattr(self, "_source_lines_for_line1_inference", None),
        )
        if callable(source_lines_resolver):
            try:
                source_lines = source_lines_resolver(segment)
            except Exception:
                source_lines = self._segment_source_lines_for_display(segment)
        else:
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
        self._push_structural_undo_action(
            StructuralAction(
                kind="insert", path=session.path, data=insert_action)
        )

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

        inferred_marker = self._inferred_line1_speaker_marker(source_segment)
        translated_marker = self._translated_inferred_marker_for_segment(
            source_segment,
            inferred_marker,
        )
        preserve_first_active_line = (
            bool(active_lines_before)
            and bool(inferred_marker)
            and (
                active_lines_before[0] == inferred_marker
                or (
                    bool(translated_marker)
                    and active_lines_before[0] == translated_marker
                )
            )
        )
        kept_active_lines, moved_active_lines = split_lines_by_sentence_boundary_row_budget(
            active_lines_before,
            max_rows_budget,
            preserve_first_line=preserve_first_active_line,
        )
        if not moved_active_lines:
            self.statusBar().showMessage("No overflow lines to move.")
            return
        ignored_leading_markers = tuple(
            marker
            for marker in (inferred_marker, translated_marker)
            if marker
        )
        kept_active_lines, moved_active_lines = self._apply_split_overflow_quote_continuity(
            list(kept_active_lines),
            list(moved_active_lines),
            ignored_leading_markers=ignored_leading_markers,
        )
        kept_active_lines, moved_active_lines = self._apply_split_overflow_color_continuity(
            list(kept_active_lines),
            list(moved_active_lines),
            inferred_marker=inferred_marker,
        )

        if translator_mode:
            kept_tl_lines = list(kept_active_lines)
            moved_tl_lines = list(moved_active_lines)
            # Translator-mode overflow split must not split JP source storage.
            kept_source_lines = list(source_segment.lines) if source_segment.lines else [""]
            moved_source_lines = [""]
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
        source_inference_disabled = bool(
            source_segment.disable_line1_speaker_inference
        )
        source_inference_forced = bool(
            source_segment.force_line1_speaker_inference
        )
        # Preserve inferred-speaker behavior on the moved block when split-down
        # carries line-1 speaker storage from the source anchor.
        moved_inference_force = source_inference_forced or (
            bool(inferred_marker) and (not source_inference_disabled)
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
            disable_line1_speaker_inference=source_inference_disabled,
            original_disable_line1_speaker_inference=source_inference_disabled,
            force_line1_speaker_inference=moved_inference_force,
            original_force_line1_speaker_inference=moved_inference_force,
            inserted=True,
            translation_only=translator_mode,
        )

        if translator_mode:
            source_segment.source_lines = list(
                source_segment.lines
                if source_segment.lines
                else (source_lines_before if source_lines_before else [""])
            )
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
        self._push_structural_undo_action(
            StructuralAction(kind="split_overflow",
                             path=session.path, data=split_action)
        )

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
            speaker_key = self._speaker_key_for_segment(left_segment)
            if speaker_key != NO_SPEAKER_KEY:
                self.speaker_translation_map[
                    self._normalize_speaker_key(speaker_key)
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
        self._push_structural_undo_action(
            StructuralAction(kind="merge", path=session.path, data=merge_action)
        )

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
                speaker_key = self._speaker_key_for_segment(segment)
                if speaker_key != NO_SPEAKER_KEY:
                    self.speaker_translation_map[
                        self._normalize_speaker_key(speaker_key)
                    ] = speaker_after
            sync_actor_duplicates = getattr(
                self,
                "_sync_duplicate_actor_name_translations_for_segment",
                None,
            )
            if callable(sync_actor_duplicates):
                try:
                    sync_actor_duplicates(session, segment)
                except Exception:
                    pass
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
            self._push_structural_undo_action(
                StructuralAction(
                    kind="reset", path=session.path, data=reset_action)
            )
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
        focus_uid_after_delete: Optional[str] = None
        if segment_index > 0:
            candidate_uid = getattr(session.segments[segment_index - 1], "uid", None)
            if isinstance(candidate_uid, str) and candidate_uid:
                focus_uid_after_delete = candidate_uid
        elif segment_index < len(session.segments):
            candidate_uid = getattr(session.segments[segment_index], "uid", None)
            if isinstance(candidate_uid, str) and candidate_uid:
                focus_uid_after_delete = candidate_uid

        self._push_structural_undo_action(
            StructuralAction(kind="delete", path=session.path, data=action)
        )

        self._refresh_dirty_state(session)
        if not self._refresh_after_remove_without_full_rerender(
            session,
            removed_uid=uid,
            focus_uid=focus_uid_after_delete,
            preserve_scroll=True,
        ):
            if not self._refresh_after_structure_change_without_full_rerender(
                session,
                focus_uid=focus_uid_after_delete,
                preserve_scroll=True,
            ):
                self._render_session(
                    session,
                    focus_uid=focus_uid_after_delete,
                    preserve_scroll=True,
                )
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
                self._mark_structural_undo_for_undo_pipeline()
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
                self._mark_structural_redo_for_undo_pipeline()
                return True
        return False
