from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional, Protocol, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.models import DialogueSegment, FileSession, NO_SPEAKER_KEY
from ..core.text_utils import natural_sort_key


class MassTranslateHost(Protocol):
    current_path: Optional[Path]
    sessions: dict[Path, FileSession]
    speaker_translation_map: dict[str, str]

    def _relative_path(self, path: Path) -> str: ...
    def _new_translation_uid(self) -> str: ...
    def _normalize_speaker_key(self, value: str) -> str: ...
    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str: ...
    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str: ...
    def _segment_source_lines_for_display(
        self, segment: DialogueSegment) -> list[str]: ...

    def _normalize_translation_lines(self, value: Any) -> list[str]: ...
    def _speaker_translation_for_key(self, speaker_key: str) -> str: ...
    def _refresh_dirty_state(self, session: FileSession) -> None: ...

    def _render_session(
        self,
        session: FileSession,
        focus_uid: Optional[str] = None,
        preserve_scroll: bool = False,
    ) -> None: ...
    def _refresh_translator_detail_panel(self) -> None: ...
    def statusBar(self) -> Any: ...
    def _translation_project_source_language_code(self) -> str: ...
    def _translation_profile_target_language_code(
        self,
        profile_id: Optional[str] = None,
    ) -> str: ...
    def _translation_profile_prompt_template(
        self,
        profile_id: Optional[str] = None,
    ) -> str: ...


class MassTranslateDialog(QDialog):
    _JSON_FENCE_RE = re.compile(
        r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
    _WORKFLOW_CONTENT_MODES: tuple[str, ...] = ("speakers", "misc", "dialogues")

    def __init__(self, editor: QWidget):
        super().__init__(editor)
        self.editor: MassTranslateHost = cast(MassTranslateHost, editor)
        self.setWindowTitle("Mass Translate (LLM)")
        self.resize(1320, 860)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)

        self.chunk_payloads: list[dict[str, Any]] = []
        self.chunk_expected_ids: list[set[str]] = []
        self.chunk_status: dict[int, str] = {}
        self.chunk_drafts: dict[int, str] = {}
        self.dialogue_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.misc_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.speaker_segment_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.dialogue_duplicate_targets: dict[str, list[tuple[Path, DialogueSegment]]] = {}
        self.misc_duplicate_targets: dict[str, list[tuple[Path, DialogueSegment]]] = {}
        self.speaker_segment_duplicate_targets: dict[str, list[tuple[Path, DialogueSegment]]] = {}
        self.dialogue_block_refs: dict[str, tuple[Path, int]] = {}
        self.speaker_targets: dict[str, str] = {}
        self._dedupe_collapsed_entries = 0
        self._active_chunk_index = -1
        self._updating_paste_box = False

        self._build_ui()
        self._refresh_scope_items()
        self._build_chunks()
        self._update_chunk_controls()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        intro_label = QLabel(
            "Build chunks from selected content, send to your LLM, then paste JSON output and apply."
        )
        intro_label.setWordWrap(True)
        root.addWidget(intro_label)

        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        options_row = QHBoxLayout()
        options_row.setSpacing(6)
        options_row.addWidget(QLabel("Scope"))
        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(260)
        options_row.addWidget(self.scope_combo, 2)

        options_row.addWidget(QLabel("Content"))
        self.content_scope_combo = QComboBox()
        self.content_scope_combo.addItem("All Content", "all_content")
        self.content_scope_combo.addItem("Speakers", "speakers")
        self.content_scope_combo.addItem("Misc", "misc")
        self.content_scope_combo.addItem("Dialogues", "dialogues")
        self.content_scope_combo.setToolTip(
            "Filter translatable entries by category."
        )
        self.content_scope_combo.setMinimumWidth(130)
        options_row.addWidget(self.content_scope_combo)

        self.only_untranslated_check = QCheckBox("Only Untranslated")
        self.only_untranslated_check.setChecked(True)
        options_row.addWidget(self.only_untranslated_check)
        self.scope_combo.currentIndexChanged.connect(
            lambda _idx: self._build_chunks())
        self.scope_combo.currentIndexChanged.connect(
            lambda _idx: self._apply_combo_current_text_color(self.scope_combo)
        )
        self.content_scope_combo.currentIndexChanged.connect(
            lambda _idx: self._on_scope_or_filters_changed())
        self.only_untranslated_check.toggled.connect(
            lambda _checked: self._on_scope_or_filters_changed())

        self.deduplicate_blocks_check = QCheckBox("Deduplicate Repeats")
        self.deduplicate_blocks_check.setChecked(False)
        self.deduplicate_blocks_check.setToolTip(
            "Include duplicate source blocks once, then apply the result to all duplicates."
        )
        self.deduplicate_blocks_check.toggled.connect(
            self._on_deduplicate_blocks_toggled
        )
        options_row.addWidget(self.deduplicate_blocks_check)

        options_row.addWidget(QLabel("Context / side"))
        self.context_boxes_spin = QSpinBox()
        self.context_boxes_spin.setRange(0, 32)
        self.context_boxes_spin.setValue(2)
        self.context_boxes_spin.setFixedWidth(64)
        self.context_boxes_spin.setToolTip(
            "How many neighboring dialogue boxes to include before/after each chunk."
        )
        options_row.addWidget(self.context_boxes_spin)

        options_row.addWidget(QLabel("Chars / chunk"))
        self.max_chunk_chars_spin = QSpinBox()
        self.max_chunk_chars_spin.setRange(500, 200000)
        self.max_chunk_chars_spin.setSingleStep(500)
        self.max_chunk_chars_spin.setValue(9000)
        self.max_chunk_chars_spin.setFixedWidth(92)
        options_row.addWidget(self.max_chunk_chars_spin)

        options_row.addStretch(1)
        self.build_chunks_btn = QPushButton("Rebuild Chunks")
        self.build_chunks_btn.clicked.connect(self._build_chunks)
        options_row.addWidget(self.build_chunks_btn)
        controls_layout.addLayout(options_row)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self.prev_chunk_btn = QPushButton("Prev")
        self.prev_chunk_btn.clicked.connect(self._on_prev_chunk)
        nav_row.addWidget(self.prev_chunk_btn)

        self.next_chunk_btn = QPushButton("Next")
        self.next_chunk_btn.clicked.connect(self._on_next_chunk)
        nav_row.addWidget(self.next_chunk_btn)

        nav_row.addWidget(QLabel("Chunk"))
        self.chunk_combo = QComboBox()
        self.chunk_combo.setMinimumWidth(280)
        self.chunk_combo.currentIndexChanged.connect(self._on_chunk_changed)
        nav_row.addWidget(self.chunk_combo, 1)

        self.copy_chunk_btn = QPushButton("Copy JSON")
        self.copy_chunk_btn.clicked.connect(self._copy_active_chunk_json)
        nav_row.addWidget(self.copy_chunk_btn)

        self.copy_prompt_btn = QPushButton("Copy Prompt")
        self.copy_prompt_btn.clicked.connect(self._copy_active_chunk_prompt)
        nav_row.addWidget(self.copy_prompt_btn)

        controls_layout.addLayout(nav_row)
        root.addWidget(controls_widget)

        self.chunk_summary_label = QLabel(
            "Build chunks to begin."
        )
        self.chunk_summary_label.setWordWrap(True)
        root.addWidget(self.chunk_summary_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(QLabel("Chunk Payload"))
        self.chunk_preview = QPlainTextEdit()
        self.chunk_preview.setReadOnly(True)
        self.chunk_preview.setPlaceholderText("Built chunk JSON appears here.")
        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.chunk_preview.setFont(mono)
        left_layout.addWidget(self.chunk_preview, 1)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(QLabel("LLM Output"))
        self.paste_box = QPlainTextEdit()
        self.paste_box.setPlaceholderText(
            "Paste translated JSON output for the selected chunk."
        )
        self.paste_box.setFont(mono)
        self.paste_box.textChanged.connect(self._on_paste_changed)
        right_layout.addWidget(self.paste_box, 1)

        apply_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply To Translations")
        self.apply_btn.clicked.connect(self._apply_pasted_chunk)
        apply_row.addWidget(self.apply_btn)
        apply_row.addStretch(1)
        right_layout.addLayout(apply_row)

        right_layout.addWidget(QLabel("Status"))
        self.result_box = QPlainTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("Parse and apply results appear here.")
        self.result_box.setFont(mono)
        self.result_box.setMaximumBlockCount(800)
        right_layout.addWidget(self.result_box, 1)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 680])

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)
        root.addLayout(bottom_row)

    def _on_paste_changed(self) -> None:
        if self._updating_paste_box:
            return
        idx = self.chunk_combo.currentIndex()
        if idx < 0:
            return
        text = self.paste_box.toPlainText()
        if text.strip():
            self.chunk_drafts[idx] = text
        elif idx in self.chunk_drafts:
            del self.chunk_drafts[idx]

    @staticmethod
    def _content_mode_flags_for_mode(mode: str) -> tuple[bool, bool, bool]:
        if mode == "all_content":
            return True, True, True
        if mode == "speakers":
            return False, False, True
        if mode == "misc":
            return False, True, False
        if mode == "dialogues":
            return True, False, False
        return True, True, True

    def _content_mode_flags(self) -> tuple[bool, bool, bool]:
        mode = str(self.content_scope_combo.currentData())
        return self._content_mode_flags_for_mode(mode)

    def _segment_source_lines_for_mass_translate(
        self,
        segment: DialogueSegment,
        source_lines_resolver: Optional[Any] = None,
    ) -> list[str]:
        resolver = source_lines_resolver
        if resolver is None:
            resolver = getattr(self.editor, "_segment_source_lines_for_translation", None)
        if callable(resolver):
            try:
                resolved_source = resolver(segment)
            except Exception:
                resolved_source = self.editor._segment_source_lines_for_display(segment)
            if isinstance(resolved_source, list):
                return resolved_source
        return self.editor._segment_source_lines_for_display(segment)

    @staticmethod
    def _has_translatable_source_lines(lines: list[str]) -> bool:
        source_text = "\n".join(lines)
        return bool(source_text.strip())

    def _persistent_speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        # Persistence keys must come from explicit source speaker fields only.
        raw = segment.speaker_name
        if not isinstance(raw, str):
            return NO_SPEAKER_KEY
        normalized = self.editor._normalize_speaker_key(raw)
        return normalized if normalized else NO_SPEAKER_KEY

    def _mode_has_pending_entries(self, mode: str) -> bool:
        include_dialogue, include_misc, include_speakers = self._content_mode_flags_for_mode(
            mode
        )
        if not include_dialogue and not include_misc and not include_speakers:
            return False

        speaker_keys: set[str] = set()
        source_lines_resolver = getattr(
            self.editor, "_segment_source_lines_for_translation", None
        )
        for path, session in self._scoped_session_items():
            for segment in session.segments:
                content_type = self._segment_content_type(path, session, segment)
                if include_speakers and self._should_collect_global_speaker_key(session, content_type):
                    speaker_key = self._persistent_speaker_key_for_segment(segment)
                    if speaker_key != NO_SPEAKER_KEY:
                        speaker_keys.add(speaker_key)
                include_segment = (
                    (content_type == "dialogue" and include_dialogue)
                    or (content_type == "misc" and include_misc)
                    or (content_type == "speaker_segment" and include_speakers)
                )
                if not include_segment:
                    continue
                source_lines = self._segment_source_lines_for_mass_translate(
                    segment,
                    source_lines_resolver,
                )
                if not self._has_translatable_source_lines(source_lines):
                    continue
                if not self._segment_has_translation(segment):
                    return True

        if include_speakers:
            for speaker_key in speaker_keys:
                if not self.editor._speaker_translation_for_key(speaker_key).strip():
                    return True
        return False

    def _next_incomplete_content_mode(self, current_mode: str) -> Optional[str]:
        if current_mode not in self._WORKFLOW_CONTENT_MODES:
            return None
        start = self._WORKFLOW_CONTENT_MODES.index(current_mode) + 1
        for mode in self._WORKFLOW_CONTENT_MODES[start:]:
            if self._mode_has_pending_entries(mode):
                return mode
        return None

    def _set_content_scope_mode(self, mode: str) -> Optional[str]:
        for idx in range(self.content_scope_combo.count()):
            if str(self.content_scope_combo.itemData(idx)) != mode:
                continue
            label = self.content_scope_combo.itemText(idx)
            self.content_scope_combo.setCurrentIndex(idx)
            return label
        return None

    def _on_scope_or_filters_changed(self) -> None:
        self._refresh_scope_items()
        self._build_chunks()

    def _dedupe_key_for_entry(
        self,
        *,
        content_type: str,
        entry_type: str,
        speaker_value: str,
        source_text: str,
    ) -> tuple[str, str, str, str]:
        return (
            content_type.strip(),
            entry_type.strip(),
            speaker_value.strip(),
            source_text.strip(),
        )

    def _on_deduplicate_blocks_toggled(self, checked: bool) -> None:
        if not checked:
            self._on_scope_or_filters_changed()
            return

        response = QMessageBox.question(
            self,
            "Deduplicate Duplicates",
            (
                "Deduplicating sends only one entry for repeated source blocks.\n"
                "This reduces token usage, but can lose per-context nuance.\n\n"
                "When enabled, applying a translation also updates every duplicate block.\n"
                "Existing translated duplicates will be propagated retroactively to empty matches.\n\n"
                "Enable this mode?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            self.deduplicate_blocks_check.blockSignals(True)
            self.deduplicate_blocks_check.setChecked(False)
            self.deduplicate_blocks_check.blockSignals(False)
            return

        (
            retro_groups,
            retro_blocks,
            retro_files,
        ) = self._apply_duplicate_translations_retroactively()
        self._refresh_scope_items()
        self._build_chunks()
        if retro_blocks > 0:
            self.result_box.setPlainText(
                (
                    "Deduplicate mode enabled.\n"
                    f"Retroactive groups resolved: {retro_groups}\n"
                    f"Retroactive blocks updated: {retro_blocks}\n"
                    f"Touched files: {retro_files}"
                )
            )
            self.editor.statusBar().showMessage(
                f"Deduplicate mode: filled {retro_blocks} duplicate blocks from existing translations."
            )
        else:
            self.result_box.setPlainText(
                "Deduplicate mode enabled. No retroactive duplicate updates were needed."
            )

    def _apply_duplicate_translations_retroactively(self) -> tuple[int, int, int]:
        include_dialogue, include_misc, include_speakers = self._content_mode_flags()
        if not include_dialogue and not include_misc and not include_speakers:
            return 0, 0, 0

        groups: dict[
            tuple[str, str, str, str],
            dict[str, Any],
        ] = {}
        translation_lines_resolver = getattr(
            self.editor, "_segment_translation_lines_for_translation", None
        )
        source_lines_resolver = getattr(
            self.editor, "_segment_source_lines_for_translation", None
        )
        compose_resolver = getattr(
            self.editor, "_compose_translation_lines_for_segment", None
        )

        for path, session in self._scoped_session_items():
            for segment in session.segments:
                content_type = self._segment_content_type(path, session, segment)
                include_segment = (
                    (content_type == "dialogue" and include_dialogue)
                    or (content_type == "misc" and include_misc)
                    or (content_type == "speaker_segment" and include_speakers)
                )
                if not include_segment:
                    continue

                speaker_key = self.editor._speaker_key_for_segment(segment)
                speaker_for_prompt = self.editor._speaker_translation_for_key(
                    speaker_key
                ).strip()
                if not speaker_for_prompt:
                    speaker_for_prompt = self.editor._resolve_name_tokens_in_text(
                        speaker_key,
                        prefer_translated=False,
                    ).strip()
                if not speaker_for_prompt:
                    speaker_for_prompt = speaker_key
                is_choice_segment = segment.segment_kind == "choice"
                include_speaker_field = (
                    content_type == "dialogue" and not is_choice_segment
                )
                speaker_field_value = speaker_for_prompt if include_speaker_field else ""

                source_lines = self._segment_source_lines_for_mass_translate(
                    segment,
                    source_lines_resolver,
                )
                if not self._has_translatable_source_lines(source_lines):
                    continue
                source_text = "\n".join(source_lines)

                if content_type == "dialogue":
                    entry_type = "choice" if is_choice_segment else "dialogue"
                elif content_type == "speaker_segment":
                    entry_type = "speaker_text"
                else:
                    entry_type = self._segment_specific_type_label(path, segment)
                dedupe_key = self._dedupe_key_for_entry(
                    content_type=content_type,
                    entry_type=entry_type,
                    speaker_value=speaker_field_value,
                    source_text=source_text,
                )

                existing_lines = self._segment_existing_lines_for_mass_translate(
                    segment,
                    translation_lines_resolver,
                )

                group = groups.setdefault(
                    dedupe_key,
                    {
                        "targets": [],
                        "reference_lines": None,
                    },
                )
                targets = cast(list[tuple[Path, DialogueSegment]], group["targets"])
                targets.append((path, segment))

                if "\n".join(existing_lines).strip() and group["reference_lines"] is None:
                    group["reference_lines"] = list(existing_lines)

        touched_paths: set[Path] = set()
        groups_resolved = 0
        updated_blocks = 0
        for group in groups.values():
            targets = cast(list[tuple[Path, DialogueSegment]], group.get("targets", []))
            reference_lines_raw = group.get("reference_lines")
            if not isinstance(reference_lines_raw, list):
                continue
            if len(targets) <= 1:
                continue

            reference_lines = self.editor._normalize_translation_lines(
                reference_lines_raw
            )
            if not "\n".join(reference_lines).strip():
                continue

            group_updated = False
            for path, segment in targets:
                current_lines = self._segment_current_target_lines(segment)
                if "\n".join(current_lines).strip():
                    continue

                stored_lines = list(reference_lines)
                if callable(compose_resolver) and self._segment_uses_translation_storage(segment):
                    try:
                        resolved_stored = compose_resolver(segment, reference_lines)
                        if isinstance(resolved_stored, list):
                            stored_lines = self.editor._normalize_translation_lines(
                                resolved_stored
                            )
                    except Exception:
                        pass

                if current_lines == stored_lines:
                    continue
                self._set_segment_target_lines(segment, stored_lines)
                touched_paths.add(path)
                group_updated = True
                updated_blocks += 1

            if group_updated:
                groups_resolved += 1

        for path in touched_paths:
            session = self.editor.sessions.get(path)
            if session is None:
                continue
            self.editor._refresh_dirty_state(session)

        current_touched = bool(
            self.editor.current_path and self.editor.current_path in touched_paths
        )
        if current_touched and self.editor.current_path is not None:
            current_session = self.editor.sessions.get(self.editor.current_path)
            if current_session is not None:
                self.editor._render_session(current_session, preserve_scroll=True)
        else:
            self.editor._refresh_translator_detail_panel()

        return groups_resolved, updated_blocks, len(touched_paths)

    def _segment_content_type(self, path: Path, session: FileSession, segment: DialogueSegment) -> str:
        _ = path
        if segment.segment_kind == "map_display_name":
            return "misc"
        if bool(getattr(session, "is_name_index_session", False)):
            kind = str(getattr(session, "name_index_kind", "")).strip().lower()
            if kind == "actor":
                return "speaker_segment"
            return "misc"
        return "dialogue"

    @staticmethod
    def _should_collect_global_speaker_key(session: FileSession, content_type: str) -> bool:
        if content_type != "dialogue":
            return False
        return not bool(getattr(session, "is_name_index_session", False))

    def _segment_specific_type_label(self, path: Path, segment: DialogueSegment) -> str:
        context = segment.context.strip()
        prefix = f"{path.name} > "
        if context.startswith(prefix):
            detail = context[len(prefix):].strip()
            if detail:
                return detail
        if context:
            return context
        return "unknown"

    @staticmethod
    def _segment_uses_translation_storage(segment: DialogueSegment) -> bool:
        _ = segment
        return True

    def _segment_existing_lines_for_mass_translate(
        self,
        segment: DialogueSegment,
        translation_lines_resolver: Optional[Any] = None,
    ) -> list[str]:
        if not self._segment_uses_translation_storage(segment):
            return self.editor._normalize_translation_lines(segment.lines)

        resolver = translation_lines_resolver
        if resolver is None:
            resolver = getattr(
                self.editor, "_segment_translation_lines_for_translation", None
            )
        if callable(resolver):
            try:
                resolved_translation = resolver(segment)
            except Exception:
                resolved_translation = self.editor._normalize_translation_lines(
                    segment.translation_lines
                )
            if isinstance(resolved_translation, list):
                return self.editor._normalize_translation_lines(resolved_translation)
        return self.editor._normalize_translation_lines(segment.translation_lines)

    def _segment_current_target_lines(self, segment: DialogueSegment) -> list[str]:
        if self._segment_uses_translation_storage(segment):
            return self.editor._normalize_translation_lines(segment.translation_lines)
        return self.editor._normalize_translation_lines(segment.lines)

    def _set_segment_target_lines(
        self,
        segment: DialogueSegment,
        lines: list[str],
    ) -> None:
        normalized = self.editor._normalize_translation_lines(lines)
        if self._segment_uses_translation_storage(segment):
            segment.translation_lines = list(normalized)
            return
        segment.lines = list(normalized)
        segment.source_lines = list(normalized)

    def _segment_has_translation(self, segment: DialogueSegment) -> bool:
        existing_lines = self.editor._normalize_translation_lines(segment.translation_lines)
        return bool("\n".join(existing_lines).strip())

    def _scope_session_items_from_value(self, scope_value: str) -> list[tuple[Path, FileSession]]:
        if scope_value.startswith("file:"):
            raw_path = scope_value[5:]
            target_path = Path(raw_path)
            session = self.editor.sessions.get(target_path)
            if session is None:
                return []
            return [(target_path, session)]
        items = list(self.editor.sessions.items())
        items.sort(key=lambda item: natural_sort_key(
            self.editor._relative_path(item[0])))
        return items

    def _scope_completion_counts(self, scope_value: str) -> tuple[int, int]:
        include_dialogue, include_misc, include_speakers = self._content_mode_flags()
        done = 0
        total = 0
        speaker_keys: set[str] = set()
        source_lines_resolver = getattr(
            self.editor, "_segment_source_lines_for_translation", None
        )
        for path, session in self._scope_session_items_from_value(scope_value):
            for segment in session.segments:
                content_type = self._segment_content_type(path, session, segment)
                if include_speakers and self._should_collect_global_speaker_key(session, content_type):
                    speaker_key = self._persistent_speaker_key_for_segment(segment)
                    if speaker_key != NO_SPEAKER_KEY:
                        speaker_keys.add(speaker_key)
                if content_type == "dialogue" and not include_dialogue:
                    continue
                if content_type == "misc" and not include_misc:
                    continue
                if content_type == "speaker_segment" and not include_speakers:
                    continue
                source_lines = self._segment_source_lines_for_mass_translate(
                    segment,
                    source_lines_resolver,
                )
                if not self._has_translatable_source_lines(source_lines):
                    continue
                translated = self._segment_has_translation(segment)
                total += 1
                if translated:
                    done += 1
        if include_speakers:
            for speaker_key in speaker_keys:
                speaker_translated = bool(
                    self.editor._speaker_translation_for_key(speaker_key).strip())
                total += 1
                if speaker_translated:
                    done += 1
        return done, total

    def _refresh_scope_items(self) -> None:
        previous = str(self.scope_combo.currentData()
                       ) if self.scope_combo.count() > 0 else "all"
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()

        all_done, all_total = self._scope_completion_counts("all")
        all_rate = (all_done * 100.0 / all_total) if all_total > 0 else 0.0
        self.scope_combo.addItem(
            f"All Files ({all_done}/{all_total}, {all_rate:.1f}%)", "all")
        self.scope_combo.setItemData(
            0,
            self._scope_progress_color(all_done, all_total),
            Qt.ItemDataRole.ForegroundRole,
        )

        items = list(self.editor.sessions.items())
        items.sort(key=lambda item: natural_sort_key(
            self.editor._relative_path(item[0])))
        for path, session in items:
            key = f"file:{path}"
            done, total = self._scope_completion_counts(key)
            if total <= 0 and not self._should_force_scope_visibility(path, session):
                continue
            rate = (done * 100.0 / total) if total > 0 else 0.0
            next_index = self.scope_combo.count()
            self.scope_combo.addItem(
                f"{self.editor._relative_path(path)} ({done}/{total}, {rate:.1f}%)",
                key,
            )
            self.scope_combo.setItemData(
                next_index,
                self._scope_progress_color(done, total),
                Qt.ItemDataRole.ForegroundRole,
            )
        index_to_select = 0
        for idx in range(self.scope_combo.count()):
            if str(self.scope_combo.itemData(idx)) == previous:
                index_to_select = idx
                break
        self.scope_combo.setCurrentIndex(index_to_select)
        self.scope_combo.blockSignals(False)
        self._apply_combo_current_text_color(self.scope_combo)

    @staticmethod
    def _should_force_scope_visibility(path: Path, session: FileSession) -> bool:
        if path.name.strip().lower() == "plugins.js":
            return True
        if not bool(getattr(session, "is_name_index_session", False)):
            return False
        kind = str(getattr(session, "name_index_kind", "")).strip().lower()
        return kind == "plugin"

    def _scoped_session_items(self) -> list[tuple[Path, FileSession]]:
        scope = str(self.scope_combo.currentData())
        return self._scope_session_items_from_value(scope)

    def _ensure_segment_translation_uid(self, segment: DialogueSegment) -> str:
        if segment.tl_uid:
            return segment.tl_uid
        segment.tl_uid = self.editor._new_translation_uid()
        return segment.tl_uid

    def _context_blocks_for_anchor(
        self,
        path: Path,
        segment_index: int,
        direction: int,
        box_limit: int,
    ) -> list[dict[str, str]]:
        if box_limit <= 0:
            return []
        session = self.editor.sessions.get(path)
        if session is None:
            return []
        if segment_index < 0 or segment_index >= len(session.segments):
            return []

        if direction < 0:
            indexes = range(segment_index - 1, -1, -1)
        else:
            indexes = range(segment_index + 1, len(session.segments))

        source_field = self._source_text_field_name()
        blocks: list[dict[str, str]] = []
        for idx in indexes:
            neighbor = session.segments[idx]
            speaker_key = self.editor._speaker_key_for_segment(neighbor)
            speaker_display = self.editor._speaker_translation_for_key(
                speaker_key).strip()
            if not speaker_display:
                speaker_display = speaker_key
            source_text = "\n".join(
                self.editor._segment_source_lines_for_display(neighbor)).strip()
            if not source_text:
                source_text = "(empty)"
            blocks.append({"speaker": speaker_display, source_field: source_text})
            if len(blocks) >= box_limit:
                break

        if direction < 0:
            blocks.reverse()
        return blocks

    def _chunk_context_blocks(
        self,
        chunk_entries: list[dict[str, Any]],
        box_limit: int,
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        if box_limit <= 0:
            return [], []

        dialogue_ids: list[str] = []
        for entry in chunk_entries:
            entry_id = entry.get("id")
            if isinstance(entry_id, str) and entry_id.startswith("D:"):
                dialogue_ids.append(entry_id)
        if not dialogue_ids:
            return [], []

        first_ref = self.dialogue_block_refs.get(dialogue_ids[0])
        last_ref = self.dialogue_block_refs.get(dialogue_ids[-1])
        before = (
            self._context_blocks_for_anchor(
                first_ref[0], first_ref[1], -1, box_limit)
            if first_ref
            else []
        )
        after = (
            self._context_blocks_for_anchor(
                last_ref[0], last_ref[1], +1, box_limit)
            if last_ref
            else []
        )
        return before, after

    def _collect_chunk_entries(
        self,
        include_dialogue: bool,
        include_misc: bool,
        include_speakers: bool,
        only_untranslated: bool,
        _context_boxes: int,
    ) -> list[dict[str, Any]]:
        self.dialogue_targets.clear()
        self.misc_targets.clear()
        self.speaker_segment_targets.clear()
        self.dialogue_duplicate_targets.clear()
        self.misc_duplicate_targets.clear()
        self.speaker_segment_duplicate_targets.clear()
        self.dialogue_block_refs.clear()
        self.speaker_targets.clear()
        self._dedupe_collapsed_entries = 0
        entries: list[dict[str, Any]] = []
        source_field = self._source_text_field_name()
        target_field = self._target_translation_field_name()
        session_items = self._scoped_session_items()
        speaker_keys: set[str] = set()
        dedupe_enabled = bool(self.deduplicate_blocks_check.isChecked())
        dedupe_key_to_entry_id: dict[tuple[str, str, str, str], str] = {}
        source_lines_resolver = getattr(
            self.editor, "_segment_source_lines_for_translation", None
        )
        translation_lines_resolver = getattr(
            self.editor, "_segment_translation_lines_for_translation", None
        )

        for path, session in session_items:
            for idx, segment in enumerate(session.segments):
                source_lines = self._segment_source_lines_for_mass_translate(
                    segment,
                    source_lines_resolver,
                )
                existing_lines = self._segment_existing_lines_for_mass_translate(
                    segment,
                    translation_lines_resolver,
                )
                existing_text = "\n".join(existing_lines).strip()
                speaker_key = self.editor._speaker_key_for_segment(segment)
                content_type = self._segment_content_type(path, session, segment)
                is_choice_segment = segment.segment_kind == "choice"

                if include_speakers and self._should_collect_global_speaker_key(session, content_type):
                    persistent_speaker_key = self._persistent_speaker_key_for_segment(segment)
                    if persistent_speaker_key != NO_SPEAKER_KEY:
                        speaker_keys.add(persistent_speaker_key)

                include_segment = (
                    (content_type == "dialogue" and include_dialogue)
                    or (content_type == "misc" and include_misc)
                    or (content_type == "speaker_segment" and include_speakers)
                )
                if not include_segment:
                    continue
                if (
                    only_untranslated
                    and existing_text
                    and self._segment_uses_translation_storage(segment)
                ):
                    continue
                if not self._has_translatable_source_lines(source_lines):
                    continue

                tl_uid = self._ensure_segment_translation_uid(segment)
                if content_type == "dialogue":
                    entry_id = f"D:{tl_uid}"
                    entry_type = "choice" if is_choice_segment else "dialogue"
                elif content_type == "speaker_segment":
                    entry_id = f"P:{tl_uid}"
                    entry_type = "speaker_text"
                else:
                    entry_id = f"M:{tl_uid}"
                    entry_type = self._segment_specific_type_label(path, segment)
                speaker_for_prompt = self.editor._speaker_translation_for_key(
                    speaker_key).strip()
                if not speaker_for_prompt:
                    speaker_for_prompt = self.editor._resolve_name_tokens_in_text(
                        speaker_key,
                        prefer_translated=False,
                    ).strip()
                if not speaker_for_prompt:
                    speaker_for_prompt = speaker_key
                include_speaker_field = (
                    content_type == "dialogue" and not is_choice_segment
                )
                source_text = "\n".join(source_lines)
                speaker_field_value = speaker_for_prompt if include_speaker_field else ""

                if dedupe_enabled:
                    dedupe_key = self._dedupe_key_for_entry(
                        content_type=content_type,
                        entry_type=entry_type,
                        speaker_value=speaker_field_value,
                        source_text=source_text,
                    )
                    canonical_entry_id = dedupe_key_to_entry_id.get(dedupe_key)
                    if canonical_entry_id is not None:
                        if content_type == "dialogue":
                            self.dialogue_duplicate_targets.setdefault(
                                canonical_entry_id, []
                            ).append((path, segment))
                        elif content_type == "speaker_segment":
                            self.speaker_segment_duplicate_targets.setdefault(
                                canonical_entry_id, []
                            ).append((path, segment))
                        else:
                            self.misc_duplicate_targets.setdefault(
                                canonical_entry_id, []
                            ).append((path, segment))
                        self._dedupe_collapsed_entries += 1
                        continue
                    dedupe_key_to_entry_id[dedupe_key] = entry_id

                entries.append(
                    {
                        "id": entry_id,
                        "type": entry_type,
                        **({"speaker": speaker_for_prompt} if include_speaker_field else {}),
                        source_field: source_text,
                        target_field: existing_text,
                    }
                )
                if content_type == "dialogue":
                    self.dialogue_targets[entry_id] = (path, segment)
                    self.dialogue_duplicate_targets[entry_id] = []
                    self.dialogue_block_refs[entry_id] = (path, idx)
                elif content_type == "speaker_segment":
                    self.speaker_segment_targets[entry_id] = (path, segment)
                    self.speaker_segment_duplicate_targets[entry_id] = []
                else:
                    self.misc_targets[entry_id] = (path, segment)
                    self.misc_duplicate_targets[entry_id] = []

        if include_speakers:
            used_entry_ids: set[str] = set()
            for entry in entries:
                raw_entry_id = entry.get("id")
                if isinstance(raw_entry_id, str):
                    used_entry_ids.add(raw_entry_id)
            for speaker_key in sorted(speaker_keys, key=natural_sort_key):
                existing_speaker = self.editor._speaker_translation_for_key(
                    speaker_key)
                if only_untranslated and existing_speaker:
                    continue
                digest = hashlib.sha1(speaker_key.encode("utf-8")).hexdigest()[:12]
                entry_id = f"S:{digest}"
                duplicate_suffix = 2
                while entry_id in used_entry_ids:
                    entry_id = f"S:{digest}:{duplicate_suffix}"
                    duplicate_suffix += 1
                used_entry_ids.add(entry_id)
                entries.append(
                    {
                        "id": entry_id,
                        "type": "speaker_name",
                        source_field: speaker_key,
                        target_field: existing_speaker,
                    }
                )
                self.speaker_targets[entry_id] = speaker_key

        return entries

    def _chunkify_entries(self, entries: list[dict[str, Any]], max_chars: int) -> list[list[dict[str, Any]]]:
        if not entries:
            return []
        safe_max = max(500, max_chars)
        chunks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for entry in entries:
            candidate = current + [entry]
            probe_size = len(
                json.dumps(
                    {"entries": candidate},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if current and probe_size > safe_max:
                chunks.append(current)
                current = [entry]
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _chunk_status_color(status: str) -> QColor:
        normalized = status.strip().lower()
        if normalized == "applied":
            return QColor("#15803d")
        if normalized == "warning":
            return QColor("#b45309")
        if normalized == "ready":
            return QColor("#1d4ed8")
        return QColor("#475569")

    @staticmethod
    def _scope_progress_color(done: int, total: int) -> QColor:
        if total <= 0:
            return QColor("#64748b")
        ratio = done / total
        if ratio >= 1.0:
            return QColor("#15803d")
        if ratio > 0.0:
            return QColor("#b45309")
        return QColor("#b91c1c")

    @staticmethod
    def _combo_current_color(combo: QComboBox) -> Optional[QColor]:
        color_data = combo.currentData(Qt.ItemDataRole.ForegroundRole)
        if isinstance(color_data, QColor) and color_data.isValid():
            return color_data
        return None

    def _apply_combo_current_text_color(self, combo: QComboBox) -> None:
        color = self._combo_current_color(combo)
        if color is None:
            combo.setStyleSheet("")
            return
        combo.setStyleSheet(f"QComboBox {{ color: {color.name()}; }}")

    def _set_paste_text(self, text: str) -> None:
        self._updating_paste_box = True
        self.paste_box.setPlainText(text)
        self._updating_paste_box = False

    def _set_chunk_combo_items(self) -> None:
        self.chunk_combo.blockSignals(True)
        self.chunk_combo.clear()
        total = len(self.chunk_payloads)
        for idx, payload in enumerate(self.chunk_payloads):
            status_raw = self.chunk_status.get(idx, "ready")
            status = status_raw.upper()
            entries_raw = payload.get("entries")
            entry_count = len(entries_raw) if isinstance(
                entries_raw, list) else 0
            char_count = len(json.dumps(payload, ensure_ascii=False, indent=2))
            self.chunk_combo.addItem(
                f"Chunk {idx + 1}/{total} ({entry_count} entries, {char_count} chars) [{status}]"
            )
            self.chunk_combo.setItemData(
                idx,
                self._chunk_status_color(status_raw),
                Qt.ItemDataRole.ForegroundRole,
            )
        self.chunk_combo.blockSignals(False)
        self._apply_combo_current_text_color(self.chunk_combo)

    def _update_chunk_controls(self) -> None:
        idx = self.chunk_combo.currentIndex()
        has_chunks = bool(self.chunk_payloads)
        has_active = has_chunks and 0 <= idx < len(self.chunk_payloads)
        self.chunk_combo.setEnabled(has_chunks)
        self.prev_chunk_btn.setEnabled(has_active and idx > 0)
        self.next_chunk_btn.setEnabled(
            has_active and idx < len(self.chunk_payloads) - 1)
        self.copy_chunk_btn.setEnabled(has_active)
        self.copy_prompt_btn.setEnabled(has_active)
        self.apply_btn.setEnabled(has_active)

    def _on_chunk_changed(self, index: int) -> None:
        if self._active_chunk_index >= 0 and self._active_chunk_index < len(self.chunk_payloads):
            text = self.paste_box.toPlainText()
            if text.strip():
                self.chunk_drafts[self._active_chunk_index] = text
            elif self._active_chunk_index in self.chunk_drafts:
                del self.chunk_drafts[self._active_chunk_index]

        self._active_chunk_index = index
        self._apply_combo_current_text_color(self.chunk_combo)
        if index < 0 or index >= len(self.chunk_payloads):
            self.chunk_preview.setPlainText("")
            self._set_paste_text("")
            self._update_chunk_controls()
            return

        payload = self.chunk_payloads[index]
        self.chunk_preview.setPlainText(json.dumps(
            payload, ensure_ascii=False, indent=2))
        self._set_paste_text(self.chunk_drafts.get(index, ""))
        entries_raw = payload.get("entries")
        entry_count = len(entries_raw) if isinstance(entries_raw, list) else 0
        self.chunk_summary_label.setText(
            f"Chunk {index + 1}/{len(self.chunk_payloads)} loaded. "
            f"Entries: {entry_count}. Paste output and apply."
        )
        self._update_chunk_controls()

    def _on_prev_chunk(self) -> None:
        idx = self.chunk_combo.currentIndex()
        if idx > 0:
            self.chunk_combo.setCurrentIndex(idx - 1)

    def _on_next_chunk(self) -> None:
        idx = self.chunk_combo.currentIndex()
        if 0 <= idx < len(self.chunk_payloads) - 1:
            self.chunk_combo.setCurrentIndex(idx + 1)

    def _copy_active_chunk_json(self) -> None:
        idx = self.chunk_combo.currentIndex()
        if idx < 0 or idx >= len(self.chunk_payloads):
            return
        QApplication.clipboard().setText(
            json.dumps(self.chunk_payloads[idx], ensure_ascii=False, indent=2)
        )
        self.result_box.setPlainText(
            "Copied selected chunk JSON to clipboard.")

    @staticmethod
    def _normalize_prompt_language_code(raw_value: Any, default: str) -> str:
        if isinstance(raw_value, str):
            cleaned = raw_value.strip().replace("_", "-").lower()
            if cleaned:
                return cleaned
        return default

    @classmethod
    def _default_prompt_template(cls) -> str:
        return (
            "Translate `{source_field}` from {source_language_code} into "
            "{target_language_code} for each entry, writing output to `{target_field}`.\n"
            "Keep JSON structure and IDs unchanged.\n"
            "Do not change `speaker`, `{source_field}`, `context_before`, or `context_after`.\n"
            "Preserve all control codes and symbols exactly (`\\C[]` `\\V[]` `\\N[]` `\\I[]` `\\{` `♡`).\n"
            "Keep \\n line breaks from `{source_field}`.\n"
            "Use natural game dialogue in {target_language_code}; keep the same tone "
            "(taunts/flirting/insults) without sanitizing.\n"
            "`{target_field}` is the output text field.\n"
            "Return JSON only.\n\n"
            "```json\n"
            "{payload_json}\n"
            "```"
        )

    @staticmethod
    def _language_field_prefix(language_code: str, default_prefix: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", language_code.lower()).strip("_")
        if not normalized:
            return default_prefix
        return normalized

    def _source_text_field_name(self) -> str:
        source_language_code, _, _ = self._translation_prompt_metadata()
        return (
            f"{self._language_field_prefix(source_language_code, 'source')}_text"
        )

    def _target_translation_field_name(self) -> str:
        _, target_language_code, _ = self._translation_prompt_metadata()
        return (
            f"{self._language_field_prefix(target_language_code, 'target')}_translation"
        )

    def _translation_prompt_metadata(self) -> tuple[str, str, str]:
        source_language_code = "ja"
        target_language_code = "en"
        prompt_template = self._default_prompt_template()

        source_language_resolver = getattr(
            self.editor,
            "_translation_project_source_language_code",
            None,
        )
        if callable(source_language_resolver):
            try:
                resolved_source = source_language_resolver()
            except Exception:
                resolved_source = None
            source_language_code = self._normalize_prompt_language_code(
                resolved_source,
                "ja",
            )

        target_language_resolver = getattr(
            self.editor,
            "_translation_profile_target_language_code",
            None,
        )
        if callable(target_language_resolver):
            try:
                resolved_target = target_language_resolver()
            except Exception:
                resolved_target = None
            target_language_code = self._normalize_prompt_language_code(
                resolved_target,
                "en",
            )

        prompt_template_resolver = getattr(
            self.editor,
            "_translation_profile_prompt_template",
            None,
        )
        if callable(prompt_template_resolver):
            try:
                resolved_prompt_template = prompt_template_resolver()
            except Exception:
                resolved_prompt_template = None
            if isinstance(resolved_prompt_template, str) and resolved_prompt_template.strip():
                prompt_template = resolved_prompt_template.strip()

        return source_language_code, target_language_code, prompt_template

    def _build_prompt_for_payload(self, payload: dict[str, Any]) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        (
            source_language_code,
            target_language_code,
            prompt_template,
        ) = self._translation_prompt_metadata()
        source_field = self._source_text_field_name()
        target_field = self._target_translation_field_name()
        rendered_prompt = prompt_template
        replacements = {
            "source_language_code": source_language_code,
            "target_language_code": target_language_code,
            "source_field": source_field,
            "target_field": target_field,
            "payload_json": payload_json,
        }
        for key, value in replacements.items():
            rendered_prompt = rendered_prompt.replace(f"{{{key}}}", value)
        return rendered_prompt

    def _copy_active_chunk_prompt(self) -> None:
        idx = self.chunk_combo.currentIndex()
        if idx < 0 or idx >= len(self.chunk_payloads):
            return
        QApplication.clipboard().setText(
            self._build_prompt_for_payload(self.chunk_payloads[idx]))
        self.result_box.setPlainText(
            "Copied prompt + selected chunk JSON to clipboard.")

    def _build_chunks(self) -> None:
        include_dialogue, include_misc, include_speakers = self._content_mode_flags()
        if not include_dialogue and not include_misc and not include_speakers:
            QMessageBox.warning(
                self,
                "No targets selected",
                "Choose a content scope before building chunks.",
            )
            return

        if self.deduplicate_blocks_check.isChecked():
            self._apply_duplicate_translations_retroactively()

        entries = self._collect_chunk_entries(
            include_dialogue=include_dialogue,
            include_misc=include_misc,
            include_speakers=include_speakers,
            only_untranslated=self.only_untranslated_check.isChecked(),
            _context_boxes=self.context_boxes_spin.value(),
        )
        if not entries:
            self.chunk_payloads = []
            self.chunk_expected_ids = []
            self.chunk_status = {}
            self.chunk_drafts = {}
            self._set_chunk_combo_items()
            self.chunk_preview.setPlainText("")
            self._set_paste_text("")
            self.result_box.setPlainText(
                "No matching entries for current filters.")
            self.chunk_summary_label.setText(
                "No entries matched the selected options.")
            self._update_chunk_controls()
            return

        groups = self._chunkify_entries(
            entries, self.max_chunk_chars_spin.value())
        context_boxes = self.context_boxes_spin.value()
        self.chunk_payloads = []
        self.chunk_expected_ids = []
        self.chunk_status = {}
        self.chunk_drafts = {}

        for idx, group in enumerate(groups, start=1):
            context_before, context_after = self._chunk_context_blocks(
                group, context_boxes)
            if context_before and context_after and context_before == context_after:
                context_after = []
            payload: dict[str, Any] = {}
            if context_before:
                payload["context_before"] = context_before
            payload["entries"] = group
            if context_after:
                payload["context_after"] = context_after
            self.chunk_payloads.append(payload)
            self.chunk_expected_ids.append(
                {
                    cast(str, entry.get("id"))
                    for entry in group
                    if isinstance(entry.get("id"), str)
                }
            )
            self.chunk_status[idx - 1] = "ready"

        self._set_chunk_combo_items()
        if self.chunk_combo.count() > 0:
            self.chunk_combo.setCurrentIndex(0)
            self._on_chunk_changed(0)
        chunk_count = len(self.chunk_payloads)
        chunk_label = "chunk" if chunk_count == 1 else "chunks"
        entry_count = len(entries)
        entry_label = "entry" if entry_count == 1 else "entries"
        dedupe_suffix = ""
        if self.deduplicate_blocks_check.isChecked() and self._dedupe_collapsed_entries > 0:
            collapsed_label = (
                "duplicate"
                if self._dedupe_collapsed_entries == 1
                else "duplicates"
            )
            dedupe_suffix = (
                f" Collapsed {self._dedupe_collapsed_entries} {collapsed_label}."
            )
        self.chunk_summary_label.setText(
            f"Built {chunk_count} {chunk_label} from {entry_count} {entry_label}.{dedupe_suffix}"
        )
        self.result_box.setPlainText(
            "Chunks built. Use Copy Prompt, send to your LLM, then paste JSON output and apply."
        )
        self._update_chunk_controls()

    @classmethod
    def _strip_code_fence(cls, text: str) -> str:
        stripped = text.strip()
        match = cls._JSON_FENCE_RE.search(stripped)
        if match:
            return match.group(1).strip()
        return stripped

    def _parse_json_payload(self, raw: str) -> Any:
        cleaned = self._strip_code_fence(raw)
        candidates: list[str] = []
        if cleaned:
            candidates.append(cleaned)

        obj_start = cleaned.find("{")
        obj_end = cleaned.rfind("}")
        if obj_start >= 0 and obj_end > obj_start:
            candidates.append(cleaned[obj_start: obj_end + 1])

        arr_start = cleaned.find("[")
        arr_end = cleaned.rfind("]")
        if arr_start >= 0 and arr_end > arr_start:
            candidates.append(cleaned[arr_start: arr_end + 1])

        tried: set[str] = set()
        last_exc: Optional[Exception] = None
        for candidate in candidates:
            snippet = candidate.strip()
            if not snippet or snippet in tried:
                continue
            tried.add(snippet)
            try:
                return json.loads(snippet)
            except Exception as exc:
                last_exc = exc
        raise ValueError(f"Could not parse pasted output as JSON: {last_exc}")

    def _entries_from_payload(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []

        entries_raw = payload.get("entries")
        if isinstance(entries_raw, list):
            return [item for item in entries_raw if isinstance(item, dict)]
        items_raw = payload.get("items")
        if isinstance(items_raw, list):
            return [item for item in items_raw if isinstance(item, dict)]

        translations_raw = payload.get("translations")
        if isinstance(translations_raw, dict):
            return self._entries_from_payload(translations_raw)

        target_field = self._target_translation_field_name()
        converted: list[dict[str, Any]] = []
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            if key == "meta":
                continue
            if not (
                key.startswith("D:")
                or key.startswith("S:")
                or key.startswith("M:")
                or key.startswith("P:")
            ):
                continue
            if isinstance(value, dict):
                row = dict(value)
                row["id"] = key
                converted.append(row)
            elif isinstance(value, list):
                converted.append({"id": key, target_field: value})
            else:
                converted.append({"id": key, target_field: value})
        if converted:
            return converted

        for value in payload.values():
            if isinstance(value, dict):
                nested = self._entries_from_payload(value)
                if nested:
                    return nested
        return []

    def _extract_dialogue_translation_lines(self, entry: dict[str, Any]) -> Optional[list[str]]:
        target_field = self._target_translation_field_name()
        line_fields = [
            target_field,
            "translation_lines_en",
            "translated_lines_en",
            "translation_lines",
            "translated_lines",
            "lines_en",
        ]
        text_fields = [
            target_field,
            "en_translation",
            "translation_en",
            "translated_en",
            "translation",
            "text_en",
            "en",
        ]

        for field in line_fields:
            value = entry.get(field)
            if isinstance(value, list):
                normalized = [
                    str(item) if item is not None else "" for item in value]
                return self.editor._normalize_translation_lines(normalized)
            if isinstance(value, str):
                return self.editor._normalize_translation_lines(value)

        for field in text_fields:
            value = entry.get(field)
            if isinstance(value, str):
                return self.editor._normalize_translation_lines(value)
        return None

    def _extract_speaker_translation(self, entry: dict[str, Any]) -> Optional[str]:
        target_field = self._target_translation_field_name()
        fields = [
            target_field,
            "en_translation",
            "translation_en",
            "speaker_en",
            "translated_speaker_en",
            "translation",
            "name_en",
            "en",
        ]
        for field in fields:
            value = entry.get(field)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return " ".join(str(item) for item in value if item is not None).strip()
        return None

    def _apply_pasted_chunk(self) -> None:
        idx = self.chunk_combo.currentIndex()
        if idx < 0 or idx >= len(self.chunk_payloads):
            QMessageBox.warning(self, "No chunk selected",
                                "Build and select a chunk first.")
            return

        raw = self.paste_box.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "Missing paste",
                                "Paste the LLM JSON output first.")
            return

        try:
            payload = self._parse_json_payload(raw)
        except Exception as exc:
            self.result_box.setPlainText(str(exc))
            return

        parsed_entries = self._entries_from_payload(payload)
        if not parsed_entries:
            self.result_box.setPlainText(
                "No entries found. Expected `entries`, a list of entry objects, or an `id -> translation` map."
            )
            return

        updates_by_id: dict[str, dict[str, Any]] = {}
        duplicate_ids: list[str] = []
        for entry in parsed_entries:
            entry_id = entry.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                continue
            if entry_id in updates_by_id:
                duplicate_ids.append(entry_id)
            updates_by_id[entry_id] = entry

        chunk_entries_raw = self.chunk_payloads[idx].get("entries")
        chunk_entries = chunk_entries_raw if isinstance(
            chunk_entries_raw, list) else []
        positional_fallback_used = False
        if not updates_by_id:
            if len(parsed_entries) == len(chunk_entries):
                for raw_entry, base_entry in zip(parsed_entries, chunk_entries):
                    if not isinstance(raw_entry, dict) or not isinstance(base_entry, dict):
                        continue
                    base_id = base_entry.get("id")
                    if not isinstance(base_id, str) or not base_id:
                        continue
                    mapped = dict(raw_entry)
                    mapped["id"] = base_id
                    updates_by_id[base_id] = mapped
                positional_fallback_used = bool(updates_by_id)
            if not updates_by_id:
                self.result_box.setPlainText(
                    "No usable `id` fields found in pasted entries.")
                return

        expected_ids = self.chunk_expected_ids[idx] if idx < len(
            self.chunk_expected_ids) else set()
        unknown_ids = sorted(
            [entry_id for entry_id in updates_by_id if entry_id not in expected_ids],
            key=natural_sort_key,
        )
        missing_ids = sorted(
            [entry_id for entry_id in expected_ids if entry_id not in updates_by_id],
            key=natural_sort_key,
        )

        touched_paths: set[Path] = set()
        dialogue_applied = 0
        misc_applied = 0
        speaker_segments_applied = 0
        speaker_keys_applied = 0
        speaker_blocks_applied = 0
        missing_translation_field_ids: list[str] = []
        line_count_mismatches: list[str] = []
        for base_entry in chunk_entries:
            if not isinstance(base_entry, dict):
                continue
            entry_id = base_entry.get("id")
            if not isinstance(entry_id, str):
                continue
            update = updates_by_id.get(entry_id)
            if update is None:
                continue

            if entry_id.startswith("D:"):
                primary_target = self.dialogue_targets.get(entry_id)
                if primary_target is None:
                    continue
                lines = self._extract_dialogue_translation_lines(update)
                if lines is None:
                    missing_translation_field_ids.append(entry_id)
                    continue
                targets = [primary_target]
                targets.extend(self.dialogue_duplicate_targets.get(entry_id, []))
                source_lines_resolver = getattr(
                    self.editor, "_segment_source_lines_for_translation", None
                )
                compose_resolver = getattr(
                    self.editor, "_compose_translation_lines_for_segment", None
                )
                for path, segment in targets:
                    if callable(source_lines_resolver):
                        try:
                            resolved_source = source_lines_resolver(segment)
                        except Exception:
                            resolved_source = self.editor._segment_source_lines_for_display(
                                segment
                            )
                        if isinstance(resolved_source, list):
                            expected_line_count = len(resolved_source)
                        else:
                            expected_line_count = len(
                                self.editor._segment_source_lines_for_display(segment)
                            )
                    else:
                        expected_line_count = len(
                            self.editor._segment_source_lines_for_display(segment)
                        )
                    if len(lines) != expected_line_count:
                        line_label = "line" if len(lines) == 1 else "lines"
                        line_count_mismatches.append(
                            (
                                f"{entry_id} @ {self.editor._relative_path(path)} "
                                f"({len(lines)} {line_label}, expected {expected_line_count})"
                            )
                        )
                    stored_lines = list(lines)
                    if callable(compose_resolver) and self._segment_uses_translation_storage(segment):
                        try:
                            resolved_stored = compose_resolver(segment, lines)
                            if isinstance(resolved_stored, list):
                                stored_lines = self.editor._normalize_translation_lines(
                                    resolved_stored
                                )
                        except Exception:
                            pass
                    current_lines = self._segment_current_target_lines(segment)
                    if current_lines != stored_lines:
                        self._set_segment_target_lines(segment, stored_lines)
                        touched_paths.add(path)
                        dialogue_applied += 1
                continue

            if entry_id.startswith("M:") or entry_id.startswith("P:"):
                primary_target: Optional[tuple[Path, DialogueSegment]] = None
                if entry_id.startswith("M:"):
                    primary_target = self.misc_targets.get(entry_id)
                else:
                    primary_target = self.speaker_segment_targets.get(entry_id)
                if primary_target is None:
                    continue
                lines = self._extract_dialogue_translation_lines(update)
                if lines is None:
                    missing_translation_field_ids.append(entry_id)
                    continue
                targets = [primary_target]
                if entry_id.startswith("M:"):
                    targets.extend(self.misc_duplicate_targets.get(entry_id, []))
                else:
                    targets.extend(
                        self.speaker_segment_duplicate_targets.get(entry_id, [])
                    )
                for path, segment in targets:
                    current_lines = self._segment_current_target_lines(segment)
                    if current_lines != lines:
                        self._set_segment_target_lines(segment, lines)
                        touched_paths.add(path)
                        if entry_id.startswith("M:"):
                            misc_applied += 1
                        else:
                            speaker_segments_applied += 1
                continue

            if entry_id.startswith("S:"):
                speaker_key = self.speaker_targets.get(entry_id)
                if speaker_key is None:
                    continue
                translated_name = self._extract_speaker_translation(update)
                if translated_name is None:
                    missing_translation_field_ids.append(entry_id)
                    continue
                cleaned = translated_name.strip()
                current_name = self.editor._speaker_translation_for_key(
                    speaker_key)
                if current_name == cleaned:
                    continue

                if cleaned:
                    self.editor.speaker_translation_map[speaker_key] = cleaned
                else:
                    self.editor.speaker_translation_map.pop(speaker_key, None)
                speaker_keys_applied += 1

                for path, session in self.editor.sessions.items():
                    session_touched = False
                    for segment in session.segments:
                        if self._persistent_speaker_key_for_segment(segment) != speaker_key:
                            continue
                        if segment.translation_speaker.strip() == cleaned:
                            continue
                        segment.translation_speaker = cleaned
                        session_touched = True
                        speaker_blocks_applied += 1
                    if session_touched:
                        touched_paths.add(path)

        for path in touched_paths:
            session = self.editor.sessions.get(path)
            if session is None:
                continue
            self.editor._refresh_dirty_state(session)

        current_touched = bool(
            self.editor.current_path and self.editor.current_path in touched_paths)
        if current_touched and self.editor.current_path is not None:
            current_session = self.editor.sessions.get(
                self.editor.current_path)
            if current_session is not None:
                self.editor._render_session(
                    current_session, preserve_scroll=True)
        else:
            self.editor._refresh_translator_detail_panel()

        has_warnings = bool(
            missing_ids
            or unknown_ids
            or missing_translation_field_ids
            or line_count_mismatches
            or duplicate_ids
        )
        clear_paste_after_apply = not has_warnings
        self.chunk_status[idx] = "warning" if has_warnings else "applied"
        self._set_chunk_combo_items()
        if clear_paste_after_apply:
            self.chunk_drafts.pop(idx, None)
            self._set_paste_text("")

        next_chunk_index = idx
        if clear_paste_after_apply and (idx + 1) < self.chunk_combo.count():
            next_chunk_index = idx + 1
        if next_chunk_index < self.chunk_combo.count():
            self.chunk_combo.setCurrentIndex(next_chunk_index)
        self._update_chunk_controls()

        summary_lines: list[str] = [
            f"Parsed entries: {len(updates_by_id)}",
            f"Applied dialogue entries: {dialogue_applied}",
            f"Applied misc entries: {misc_applied}",
            f"Applied speaker text entries: {speaker_segments_applied}",
            f"Applied speaker names: {speaker_keys_applied}",
            f"Speaker blocks updated: {speaker_blocks_applied}",
            f"Touched files: {len(touched_paths)}",
        ]
        if missing_ids:
            summary_lines.append(f"Missing expected IDs: {len(missing_ids)}")
            summary_lines.extend(missing_ids[:10])
            if len(missing_ids) > 10:
                summary_lines.append("...")
        if unknown_ids:
            summary_lines.append(f"Unknown IDs ignored: {len(unknown_ids)}")
            summary_lines.extend(unknown_ids[:10])
            if len(unknown_ids) > 10:
                summary_lines.append("...")
        if duplicate_ids:
            summary_lines.append(
                f"Duplicate IDs in paste: {len(duplicate_ids)} (last one used)")
        if positional_fallback_used:
            summary_lines.append(
                "Used positional mapping because pasted entries had no IDs.")
        if missing_translation_field_ids:
            summary_lines.append(
                f"Entries missing translation field: {len(missing_translation_field_ids)}"
            )
        if line_count_mismatches:
            summary_lines.append(
                f"Line-count mismatches: {len(line_count_mismatches)}")
            summary_lines.extend(line_count_mismatches[:8])
            if len(line_count_mismatches) > 8:
                summary_lines.append("...")

        self.result_box.setPlainText("\n".join(summary_lines))
        self.editor.statusBar().showMessage(
            "Mass translate apply: "
            f"{dialogue_applied} dialogues, {misc_applied} misc, "
            f"{speaker_segments_applied} speaker text, {speaker_keys_applied} speaker names."
        )
        self._refresh_scope_items()

        current_mode = str(self.content_scope_combo.currentData())
        if (
            current_mode in self._WORKFLOW_CONTENT_MODES
            and not self._mode_has_pending_entries(current_mode)
        ):
            next_mode = self._next_incomplete_content_mode(current_mode)
            if next_mode is not None:
                next_label = self._set_content_scope_mode(next_mode)
                if next_label:
                    self.result_box.appendPlainText(
                        f"\nSwitched content scope to '{next_label}' (next incomplete section)."
                    )
