from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional, Protocol, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
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
    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str: ...
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


class MassTranslateDialog(QDialog):
    _JSON_FENCE_RE = re.compile(
        r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)

    def __init__(self, editor: QWidget):
        super().__init__(editor)
        self.editor: MassTranslateHost = cast(MassTranslateHost, editor)
        self.setWindowTitle("Mass Translate (LLM)")
        self.resize(1320, 860)

        self.chunk_payloads: list[dict[str, Any]] = []
        self.chunk_expected_ids: list[set[str]] = []
        self.chunk_status: dict[int, str] = {}
        self.chunk_drafts: dict[int, str] = {}
        self.dialogue_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.misc_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.speaker_segment_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.dialogue_block_refs: dict[str, tuple[Path, int]] = {}
        self.speaker_targets: dict[str, str] = {}
        self._active_chunk_index = -1
        self._updating_paste_box = False

        self._build_ui()
        self._refresh_scope_items()
        self._build_chunks()
        self._update_chunk_controls()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Scope"))
        self.scope_combo = QComboBox()
        options_row.addWidget(self.scope_combo)

        options_row.addWidget(QLabel("Content"))
        self.content_scope_combo = QComboBox()
        self.content_scope_combo.addItem("All Content", "all_content")
        self.content_scope_combo.addItem("Speakers", "speakers")
        self.content_scope_combo.addItem("Misc", "misc")
        self.content_scope_combo.addItem("Dialogues", "dialogues")
        self.content_scope_combo.setToolTip(
            "Filter translatable entries by category."
        )
        options_row.addWidget(self.content_scope_combo)

        self.only_untranslated_check = QCheckBox("Only Untranslated")
        self.only_untranslated_check.setChecked(True)
        options_row.addWidget(self.only_untranslated_check)
        self.scope_combo.currentIndexChanged.connect(
            lambda _idx: self._build_chunks())
        self.content_scope_combo.currentIndexChanged.connect(
            lambda _idx: self._on_scope_or_filters_changed())
        self.only_untranslated_check.toggled.connect(
            lambda _checked: self._on_scope_or_filters_changed())

        options_row.addWidget(QLabel("Context boxes/side"))
        self.context_boxes_spin = QSpinBox()
        self.context_boxes_spin.setRange(0, 32)
        self.context_boxes_spin.setValue(2)
        self.context_boxes_spin.setToolTip(
            "How many neighboring dialogue boxes to include before/after each chunk."
        )
        options_row.addWidget(self.context_boxes_spin)

        options_row.addWidget(QLabel("Max chars/chunk"))
        self.max_chunk_chars_spin = QSpinBox()
        self.max_chunk_chars_spin.setRange(500, 200000)
        self.max_chunk_chars_spin.setValue(9000)
        options_row.addWidget(self.max_chunk_chars_spin)

        options_row.addStretch(1)
        self.build_chunks_btn = QPushButton("Build Chunks")
        self.build_chunks_btn.clicked.connect(self._build_chunks)
        options_row.addWidget(self.build_chunks_btn)
        root.addLayout(options_row)

        nav_row = QHBoxLayout()
        self.prev_chunk_btn = QPushButton("Previous")
        self.prev_chunk_btn.clicked.connect(self._on_prev_chunk)
        nav_row.addWidget(self.prev_chunk_btn)

        self.next_chunk_btn = QPushButton("Next")
        self.next_chunk_btn.clicked.connect(self._on_next_chunk)
        nav_row.addWidget(self.next_chunk_btn)

        nav_row.addWidget(QLabel("Chunk"))
        self.chunk_combo = QComboBox()
        self.chunk_combo.currentIndexChanged.connect(self._on_chunk_changed)
        nav_row.addWidget(self.chunk_combo, 1)

        self.copy_chunk_btn = QPushButton("Copy Chunk JSON")
        self.copy_chunk_btn.clicked.connect(self._copy_active_chunk_json)
        nav_row.addWidget(self.copy_chunk_btn)

        self.copy_prompt_btn = QPushButton("Copy Prompt")
        self.copy_prompt_btn.clicked.connect(self._copy_active_chunk_prompt)
        nav_row.addWidget(self.copy_prompt_btn)

        root.addLayout(nav_row)

        self.chunk_summary_label = QLabel(
            "Build chunks, copy prompt+chunk to your LLM, then paste the JSON output back here."
        )
        self.chunk_summary_label.setWordWrap(True)
        root.addWidget(self.chunk_summary_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(QLabel("Selected Chunk JSON"))
        self.chunk_preview = QPlainTextEdit()
        self.chunk_preview.setReadOnly(True)
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
        right_layout.addWidget(QLabel("Paste LLM Output"))
        self.paste_box = QPlainTextEdit()
        self.paste_box.textChanged.connect(self._on_paste_changed)
        right_layout.addWidget(self.paste_box, 1)

        apply_row = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Pasted To Translations")
        self.apply_btn.clicked.connect(self._apply_pasted_chunk)
        apply_row.addWidget(self.apply_btn)
        apply_row.addStretch(1)
        right_layout.addLayout(apply_row)

        right_layout.addWidget(QLabel("Parse / Apply Result"))
        self.result_box = QPlainTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setMaximumBlockCount(800)
        right_layout.addWidget(self.result_box, 1)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

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

    def _content_mode_flags(self) -> tuple[bool, bool, bool]:
        mode = str(self.content_scope_combo.currentData())
        if mode == "all_content":
            return True, True, True
        if mode == "speakers":
            return False, False, True
        if mode == "misc":
            return False, True, False
        if mode == "dialogues":
            return True, False, False
        return True, True, True

    def _on_scope_or_filters_changed(self) -> None:
        self._refresh_scope_items()
        self._build_chunks()

    def _segment_content_type(self, path: Path, session: FileSession, segment: DialogueSegment) -> str:
        _ = path
        _ = segment
        if bool(getattr(session, "is_name_index_session", False)):
            kind = str(getattr(session, "name_index_kind", "")).strip().lower()
            if kind == "actor":
                return "speaker_segment"
            return "misc"
        return "dialogue"

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

    def _segment_has_translation(self, segment: DialogueSegment) -> bool:
        existing_lines = self.editor._normalize_translation_lines(
            segment.translation_lines)
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
        for path, session in self._scope_session_items_from_value(scope_value):
            for segment in session.segments:
                content_type = self._segment_content_type(path, session, segment)
                if content_type == "dialogue" and not include_dialogue:
                    continue
                if content_type == "misc" and not include_misc:
                    continue
                if content_type == "speaker_segment" and not include_speakers:
                    continue
                translated = self._segment_has_translation(segment)
                total += 1
                if translated:
                    done += 1
                if include_speakers:
                    speaker_key = self.editor._speaker_key_for_segment(segment)
                    if speaker_key != NO_SPEAKER_KEY:
                        speaker_keys.add(speaker_key)
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

        items = list(self.editor.sessions.items())
        items.sort(key=lambda item: natural_sort_key(
            self.editor._relative_path(item[0])))
        for path, _session in items:
            key = f"file:{path}"
            done, total = self._scope_completion_counts(key)
            if total <= 0:
                continue
            rate = (done * 100.0 / total) if total > 0 else 0.0
            self.scope_combo.addItem(
                f"{self.editor._relative_path(path)} ({done}/{total}, {rate:.1f}%)",
                key,
            )
        index_to_select = 0
        for idx in range(self.scope_combo.count()):
            if str(self.scope_combo.itemData(idx)) == previous:
                index_to_select = idx
                break
        self.scope_combo.setCurrentIndex(index_to_select)
        self.scope_combo.blockSignals(False)

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

        blocks: list[dict[str, str]] = []
        for idx in indexes:
            neighbor = session.segments[idx]
            speaker_key = self.editor._speaker_key_for_segment(neighbor)
            speaker_display = self.editor._speaker_translation_for_key(
                speaker_key).strip()
            if not speaker_display:
                speaker_display = speaker_key
            jp_text = "\n".join(
                self.editor._segment_source_lines_for_display(neighbor)).strip()
            if not jp_text:
                jp_text = "(empty)"
            blocks.append({"speaker": speaker_display, "jp_text": jp_text})
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
        self.dialogue_block_refs.clear()
        self.speaker_targets.clear()
        entries: list[dict[str, Any]] = []
        session_items = self._scoped_session_items()
        speaker_keys: set[str] = set()

        for path, session in session_items:
            for idx, segment in enumerate(session.segments):
                source_lines = self.editor._segment_source_lines_for_display(
                    segment)
                existing_lines = self.editor._normalize_translation_lines(
                    segment.translation_lines)
                existing_text = "\n".join(existing_lines).strip()
                speaker_key = self.editor._speaker_key_for_segment(segment)
                content_type = self._segment_content_type(path, session, segment)

                if include_speakers and speaker_key != NO_SPEAKER_KEY:
                    speaker_keys.add(speaker_key)

                include_segment = (
                    (content_type == "dialogue" and include_dialogue)
                    or (content_type == "misc" and include_misc)
                    or (content_type == "speaker_segment" and include_speakers)
                )
                if not include_segment:
                    continue
                if only_untranslated and existing_text:
                    continue

                tl_uid = self._ensure_segment_translation_uid(segment)
                if content_type == "dialogue":
                    entry_id = f"D:{tl_uid}"
                    entry_type = "dialogue"
                elif content_type == "speaker_segment":
                    entry_id = f"P:{tl_uid}"
                    entry_type = "speaker_text"
                else:
                    entry_id = f"M:{tl_uid}"
                    entry_type = self._segment_specific_type_label(path, segment)
                speaker_for_prompt = self.editor._speaker_translation_for_key(
                    speaker_key).strip()
                if not speaker_for_prompt:
                    speaker_for_prompt = speaker_key
                entries.append(
                    {
                        "id": entry_id,
                        "type": entry_type,
                        **({"speaker": speaker_for_prompt}
                           if content_type == "dialogue" else {}),
                        "jp_text": "\n".join(source_lines),
                        "en_translation": existing_text,
                    }
                )
                if content_type == "dialogue":
                    self.dialogue_targets[entry_id] = (path, segment)
                    self.dialogue_block_refs[entry_id] = (path, idx)
                elif content_type == "speaker_segment":
                    self.speaker_segment_targets[entry_id] = (path, segment)
                else:
                    self.misc_targets[entry_id] = (path, segment)

        if include_speakers:
            for speaker_key in sorted(speaker_keys, key=natural_sort_key):
                existing_speaker = self.editor._speaker_translation_for_key(
                    speaker_key)
                if only_untranslated and existing_speaker:
                    continue
                entry_id = f"S:{speaker_key}"
                entries.append(
                    {
                        "id": entry_id,
                        "type": "speaker_name",
                        "jp_text": speaker_key,
                        "en_translation": existing_speaker,
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

    def _set_paste_text(self, text: str) -> None:
        self._updating_paste_box = True
        self.paste_box.setPlainText(text)
        self._updating_paste_box = False

    def _set_chunk_combo_items(self) -> None:
        self.chunk_combo.blockSignals(True)
        self.chunk_combo.clear()
        total = len(self.chunk_payloads)
        for idx, payload in enumerate(self.chunk_payloads):
            status = self.chunk_status.get(idx, "ready").upper()
            entries_raw = payload.get("entries")
            entry_count = len(entries_raw) if isinstance(
                entries_raw, list) else 0
            char_count = len(json.dumps(payload, ensure_ascii=False, indent=2))
            self.chunk_combo.addItem(
                f"Chunk {idx + 1}/{total} ({entry_count} entries, {char_count} chars) [{status}]"
            )
        self.chunk_combo.blockSignals(False)

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

    def _build_prompt_for_payload(self, payload: dict[str, Any]) -> str:
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
        lines = [
            "Translate `jp_text` into `en_translation` for each entry.",
            "Keep JSON structure and IDs unchanged.",
            "Do not change `speaker`, `jp_text`, `context_before`, or `context_after`.",
            "Return JSON only.",
            "",
            "```json",
            payload_json,
            "```",
        ]
        return "\n".join(lines)

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
        self.chunk_summary_label.setText(
            f"Built {len(self.chunk_payloads)} chunk(s) from {len(entries)} entries."
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
                converted.append({"id": key, "translation_lines_en": value})
            else:
                converted.append({"id": key, "translation_en": value})
        if converted:
            return converted

        for value in payload.values():
            if isinstance(value, dict):
                nested = self._entries_from_payload(value)
                if nested:
                    return nested
        return []

    def _extract_dialogue_translation_lines(self, entry: dict[str, Any]) -> Optional[list[str]]:
        line_fields = [
            "translation_lines_en",
            "translated_lines_en",
            "translation_lines",
            "translated_lines",
            "lines_en",
        ]
        text_fields = [
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
        fields = [
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
                target = self.dialogue_targets.get(entry_id)
                if target is None:
                    continue
                lines = self._extract_dialogue_translation_lines(update)
                if lines is None:
                    missing_translation_field_ids.append(entry_id)
                    continue
                path, segment = target
                expected_line_count = len(
                    self.editor._segment_source_lines_for_display(segment))
                if len(lines) != expected_line_count:
                    line_count_mismatches.append(
                        f"{entry_id} ({len(lines)} line(s), expected {expected_line_count})"
                    )
                current_lines = self.editor._normalize_translation_lines(
                    segment.translation_lines)
                if current_lines != lines:
                    segment.translation_lines = list(lines)
                    touched_paths.add(path)
                    dialogue_applied += 1
                continue

            if entry_id.startswith("M:") or entry_id.startswith("P:"):
                target: Optional[tuple[Path, DialogueSegment]] = None
                if entry_id.startswith("M:"):
                    target = self.misc_targets.get(entry_id)
                else:
                    target = self.speaker_segment_targets.get(entry_id)
                if target is None:
                    continue
                lines = self._extract_dialogue_translation_lines(update)
                if lines is None:
                    missing_translation_field_ids.append(entry_id)
                    continue
                path, segment = target
                current_lines = self.editor._normalize_translation_lines(
                    segment.translation_lines)
                if current_lines != lines:
                    segment.translation_lines = list(lines)
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
                        if self.editor._speaker_key_for_segment(segment) != speaker_key:
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
        self.chunk_status[idx] = "warning" if has_warnings else "applied"
        self._set_chunk_combo_items()
        if idx < self.chunk_combo.count():
            self.chunk_combo.setCurrentIndex(idx)
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

        # After a successful speaker-only pass, move workflow to dialogue translation.
        current_mode = str(self.content_scope_combo.currentData())
        if current_mode == "speakers" and speaker_keys_applied > 0:
            for idx in range(self.content_scope_combo.count()):
                if str(self.content_scope_combo.itemData(idx)) == "dialogues":
                    self.content_scope_combo.setCurrentIndex(idx)
                    break
            self.result_box.appendPlainText(
                "\nSwitched content scope to 'Dialogues'."
            )
