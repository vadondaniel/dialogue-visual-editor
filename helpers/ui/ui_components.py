from __future__ import annotations

from difflib import SequenceMatcher
import html
import re
from typing import Any, Callable, Literal, Optional, Protocol, cast

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QPalette,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QToolTip,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.models import NO_SPEAKER_KEY, DialogueSegment
from ..core.text_utils import (
    CONTROL_TOKEN_RE,
    collapse_lines_join_paragraphs,
    first_overflow_char_index,
    looks_like_name_line,
    split_lines_by_row_budget,
    smart_collapse_lines,
    split_lines_preserve_empty,
    strip_control_tokens,
    total_display_rows,
    visible_length,
    wrap_lines_hard_break,
)

NAME_INDEX_UID_RE = re.compile(r":[A-Za-z]:(\d+)(?::([A-Za-z0-9_]+))?$")
VARIABLE_TOKEN_RE = re.compile(r"\\[Vv]\[(\d+)\]")
ControlMismatchStatus = Literal["matched", "missing", "extra"]
ControlMismatchSpan = tuple[int, int, ControlMismatchStatus]

_CONTROL_MISMATCH_BG_DARK: dict[ControlMismatchStatus, str] = {
    "matched": "#14532d",
    "missing": "#7f1d1d",
    "extra": "#78350f",
}
_CONTROL_MISMATCH_BG_LIGHT: dict[ControlMismatchStatus, str] = {
    "matched": "#dcfce7",
    "missing": "#fee2e2",
    "extra": "#fef3c7",
}


def _extract_control_token_matches(text: str) -> list[tuple[str, int, int]]:
    if not text:
        return []
    return [
        (match.group(0), match.start(), match.end())
        for match in CONTROL_TOKEN_RE.finditer(text)
    ]


def control_mismatch_token_spans(
    source_text: str,
    translation_text: str,
) -> tuple[list[ControlMismatchSpan], list[ControlMismatchSpan]]:
    source_matches = _extract_control_token_matches(source_text or "")
    translation_matches = _extract_control_token_matches(translation_text or "")
    source_tokens = [token for token, _start, _end in source_matches]
    translation_tokens = [
        token for token, _start, _end in translation_matches]
    source_statuses: list[ControlMismatchStatus] = [
        "missing"] * len(source_matches)
    translation_statuses: list[ControlMismatchStatus] = [
        "extra"] * len(translation_matches)
    matcher = SequenceMatcher(
        a=source_tokens,
        b=translation_tokens,
        autojunk=False,
    )
    for tag, source_start, source_end, tl_start, tl_end in matcher.get_opcodes():
        if tag != "equal":
            continue
        for source_idx in range(source_start, source_end):
            source_statuses[source_idx] = "matched"
        for tl_idx in range(tl_start, tl_end):
            translation_statuses[tl_idx] = "matched"

    source_spans: list[ControlMismatchSpan] = []
    for idx, (_token, start, end) in enumerate(source_matches):
        source_spans.append((start, end, source_statuses[idx]))
    translation_spans: list[ControlMismatchSpan] = []
    for idx, (_token, start, end) in enumerate(translation_matches):
        translation_spans.append((start, end, translation_statuses[idx]))

    return source_spans, translation_spans


def build_control_mismatch_selections(
    editor: QPlainTextEdit,
    source_text: str,
    translation_text: str,
    *,
    highlight_side: Literal["source", "translation"],
    dark_theme: bool,
) -> list[QTextEdit.ExtraSelection]:
    source_spans, translation_spans = control_mismatch_token_spans(
        source_text,
        translation_text,
    )
    if highlight_side == "source":
        spans = source_spans
    else:
        spans = translation_spans
    if not spans:
        return []

    palette = _CONTROL_MISMATCH_BG_DARK if dark_theme else _CONTROL_MISMATCH_BG_LIGHT
    alpha = 164 if dark_theme else 128
    doc_len = len(editor.toPlainText())
    selections: list[QTextEdit.ExtraSelection] = []
    for start, end, status in spans:
        if end <= start or start >= doc_len:
            continue
        color_hex = palette.get(status, "")
        color = QColor(color_hex)
        if not color.isValid():
            continue
        color.setAlpha(alpha)
        cursor = QTextCursor(editor.document())
        cursor.setPosition(max(0, start))
        cursor.setPosition(min(end, doc_len), QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        fmt.setBackground(color)
        selection_any = cast(Any, selection)
        selection_any.format = fmt
        selection_any.cursor = cursor
        selections.append(selection)
    return selections


class SpeakerManagerHost(Protocol):
    speaker_custom_colors: dict[str, str]

    def _collect_speaker_keys(self) -> list[str]: ...
    def _speaker_color_for_key(self, speaker_key: str) -> str: ...
    def _speaker_translation_for_key(self, speaker_key: str) -> str: ...
    def _normalize_speaker_key(self, value: str) -> str: ...

    def _rename_speaker_everywhere(
        self, old_key: str, new_key: str) -> int: ...

    def _set_speaker_translation_everywhere(
        self, speaker_key: str, translated_name: str) -> int: ...
    def _set_custom_speaker_color(
        self, speaker_key: str, color_hex: str) -> None: ...

    def _clear_custom_speaker_color(self, speaker_key: str) -> None: ...


class VariableLengthManagerHost(Protocol):
    def _collect_variable_ids_for_manager(self) -> list[int]: ...
    def _variable_label_for_rpgm_index(self, variable_id: int) -> str: ...
    def _default_variable_length_for_manager(self) -> int: ...
    def _variable_length_estimate_for_id(self, variable_id: int) -> int: ...
    def _variable_length_override_exists(self, variable_id: int) -> bool: ...
    def _set_default_variable_length_estimate(self, value: int) -> int: ...
    def _set_variable_length_override(self, variable_id: int, length: int) -> int: ...
    def _clear_variable_length_override(self, variable_id: int) -> bool: ...


def is_dark_palette() -> bool:
    core_app = QApplication.instance()
    if core_app is None:
        return False
    app = cast(QApplication, core_app)
    try:
        return app.palette().color(QPalette.ColorRole.Window).lightness() < 128
    except Exception:
        return False


def _set_hard_newline_markers(editor: QPlainTextEdit, enabled: bool) -> None:
    text_option = editor.document().defaultTextOption()
    flags = text_option.flags()
    marker_flag = QTextOption.Flag.ShowLineAndParagraphSeparators
    if enabled:
        flags = flags | marker_flag
    else:
        flags = flags & ~marker_flag
    text_option.setFlags(flags)
    editor.document().setDefaultTextOption(text_option)


def _split_masked_text_and_spans(
    masked_text: str,
    spans: list[tuple[int, int, str, float]],
) -> tuple[list[str], list[list[tuple[int, int, str, float]]]]:
    lines = split_lines_preserve_empty(masked_text)
    if not lines:
        return [""], [[]]

    line_starts: list[int] = []
    cursor = 0
    line_count = len(lines)
    for idx, line in enumerate(lines):
        line_starts.append(cursor)
        cursor += len(line)
        if idx < line_count - 1:
            cursor += 1

    spans_per_line: list[list[tuple[int, int, str, float]]] = [[] for _ in lines]
    for span_start, span_end, color_hex, font_scale in spans:
        if span_end <= span_start:
            continue
        for idx, line in enumerate(lines):
            line_start = line_starts[idx]
            line_end = line_start + len(line)
            start = max(span_start, line_start)
            end = min(span_end, line_end)
            if end <= start:
                continue
            spans_per_line[idx].append(
                (start - line_start, end - line_start, color_hex, font_scale)
            )
    return lines, spans_per_line


def _variable_token_id_at_editor_position(
    editor: QPlainTextEdit,
    pos: QPoint,
) -> Optional[int]:
    cursor = editor.cursorForPosition(pos)
    block = cursor.block()
    if not block.isValid():
        return None
    line_text = block.text()
    in_block_pos = cursor.position() - block.position()
    for match in VARIABLE_TOKEN_RE.finditer(line_text):
        if match.start() <= in_block_pos <= match.end():
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


class ControlCodeHighlighter(QSyntaxHighlighter):
    _COLOR_CODE_RE = re.compile(r"\\[Cc]\[(\d+)\]")

    def __init__(
        self,
        parent: Any,
        dark_theme: bool,
        color_code_resolver: Optional[Callable[[int], str]] = None,
    ):
        super().__init__(parent)
        self._color_code_resolver = color_code_resolver
        if dark_theme:
            command_color = "#fbbf24"
            symbol_color = "#93c5fd"
            variable_placeholder_color = "#86efac"
            name_placeholder_color = "#67e8f9"
        else:
            command_color = "#9a3412"
            symbol_color = "#1d4ed8"
            variable_placeholder_color = "#166534"
            name_placeholder_color = "#0e7490"

        command_format = QTextCharFormat()
        command_format.setForeground(QColor(command_color))
        command_format.setFontWeight(QFont.Weight.DemiBold)

        symbol_format = QTextCharFormat()
        symbol_format.setForeground(QColor(symbol_color))
        symbol_format.setFontWeight(QFont.Weight.DemiBold)

        variable_placeholder_format = QTextCharFormat()
        variable_placeholder_format.setForeground(
            QColor(variable_placeholder_color))
        variable_placeholder_format.setFontWeight(QFont.Weight.DemiBold)

        name_placeholder_format = QTextCharFormat()
        name_placeholder_format.setForeground(QColor(name_placeholder_color))
        name_placeholder_format.setFontWeight(QFont.Weight.DemiBold)

        self._rules: list[tuple[re.Pattern[str], QTextCharFormat]] = [
            (re.compile(r"\\[A-Za-z]+\[[^\]\r\n]*\]"), command_format),
            (re.compile(r"\\[A-Za-z]+"), command_format),
            (re.compile(r"\\[\\{}.$|!><^]"), symbol_format),
            (re.compile(r"<(?:VAR:|V)\d+>"), variable_placeholder_format),
            (re.compile(r"<(?:NAME:|N)\d+>"), name_placeholder_format),
        ]

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
        if self._color_code_resolver is None:
            return
        for match in self._COLOR_CODE_RE.finditer(text):
            try:
                color_code = int(match.group(1))
            except Exception:
                continue
            color_hex = self._color_code_resolver(color_code)
            color = QColor(color_hex)
            if not color.isValid():
                continue
            color_fmt = QTextCharFormat()
            color_fmt.setForeground(color)
            color_fmt.setFontWeight(QFont.Weight.DemiBold)
            self.setFormat(match.start(), match.end() -
                           match.start(), color_fmt)


class SpeakerManagerDialog(QDialog):
    def __init__(self, editor: QWidget):
        super().__init__(editor)
        self.editor: SpeakerManagerHost = cast(SpeakerManagerHost, editor)
        self.setWindowTitle("Speaker Manager")
        self.resize(460, 420)

        root = QVBoxLayout(self)
        info = QLabel(
            "Manage speakers globally: rename, set EN translation, pick custom colors, or revert to auto colors.\n"
            "Blank names are treated as '(none)'."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self.list_widget = QListWidget()
        root.addWidget(self.list_widget, 1)
        self.list_widget.currentItemChanged.connect(
            lambda _current, _previous: self._sync_action_buttons()
        )

        actions = QHBoxLayout()
        self.rename_btn = QPushButton("Rename...")
        self.translate_btn = QPushButton("Set EN...")
        self.clear_translate_btn = QPushButton("Clear EN")
        self.color_btn = QPushButton("Pick Color...")
        self.auto_btn = QPushButton("Auto Color")
        self.rename_btn.clicked.connect(self._on_rename_clicked)
        self.translate_btn.clicked.connect(self._on_translate_clicked)
        self.clear_translate_btn.clicked.connect(
            self._on_clear_translation_clicked)
        self.color_btn.clicked.connect(self._on_color_clicked)
        self.auto_btn.clicked.connect(self._on_auto_color_clicked)
        actions.addWidget(self.rename_btn)
        actions.addWidget(self.translate_btn)
        actions.addWidget(self.clear_translate_btn)
        actions.addWidget(self.color_btn)
        actions.addWidget(self.auto_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)
        root.addWidget(close_box)

        self._refresh_list()

    def _selected_speaker_key(self) -> Optional[str]:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        key = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(key, str):
            return key
        return None

    def _refresh_list(self, select_key: Optional[str] = None) -> None:
        speakers = self.editor._collect_speaker_keys()
        self.list_widget.clear()
        dark_theme = is_dark_palette()
        for speaker_key in speakers:
            color_hex = self.editor._speaker_color_for_key(speaker_key)
            color = QColor(color_hex)
            chip = QColor(color)
            chip.setAlpha(80 if dark_theme else 56)
            text_color = QColor(
                "#f8fafc" if color.lightness() < 128 else "#0f172a")

            is_custom = speaker_key in self.editor.speaker_custom_colors
            speaker_en = self.editor._speaker_translation_for_key(speaker_key)
            label = speaker_key
            if speaker_en:
                label += f" -> {speaker_en}"
            if is_custom:
                label += " [custom]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, speaker_key)
            item.setBackground(chip)
            item.setForeground(text_color)
            self.list_widget.addItem(item)

        if self.list_widget.count() == 0:
            self._sync_action_buttons()
            return

        row_to_select = 0
        if select_key is not None:
            for row in range(self.list_widget.count()):
                key = self.list_widget.item(row).data(Qt.ItemDataRole.UserRole)
                if key == select_key:
                    row_to_select = row
                    break
        self.list_widget.setCurrentRow(row_to_select)
        self._sync_action_buttons()

    def _sync_action_buttons(self) -> None:
        selected_key = self._selected_speaker_key()
        has_selection = selected_key is not None
        has_custom = bool(
            selected_key and selected_key in self.editor.speaker_custom_colors)
        has_translation = bool(
            selected_key and self.editor._speaker_translation_for_key(selected_key))
        self.rename_btn.setEnabled(has_selection)
        self.translate_btn.setEnabled(has_selection)
        self.clear_translate_btn.setEnabled(has_translation)
        self.color_btn.setEnabled(has_selection)
        self.auto_btn.setEnabled(has_custom)

    def _rename_prefill_text(self, speaker_key: str) -> str:
        if speaker_key == NO_SPEAKER_KEY:
            return ""
        return speaker_key

    def _translation_prefill_text(self, speaker_key: str) -> str:
        existing = self.editor._speaker_translation_for_key(speaker_key)
        if existing.strip():
            return existing
        if speaker_key == NO_SPEAKER_KEY:
            return ""
        return speaker_key

    def _on_rename_clicked(self) -> None:
        current = self._selected_speaker_key()
        if current is None:
            return
        default_text = self._rename_prefill_text(current)
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Speaker",
            f"Rename speaker '{current}' to:",
            text=default_text,
        )
        if not ok:
            return
        new_key = self.editor._normalize_speaker_key(new_name)
        if new_key == current:
            return
        self.editor._rename_speaker_everywhere(current, new_key)
        self._refresh_list(select_key=new_key)

    def _on_color_clicked(self) -> None:
        current = self._selected_speaker_key()
        if current is None:
            return
        initial = QColor(self.editor._speaker_color_for_key(current))
        picked = QColorDialog.getColor(
            initial, self, f"Pick color for '{current}'")
        if not picked.isValid():
            return
        self.editor._set_custom_speaker_color(
            current, picked.name(QColor.NameFormat.HexRgb))
        self._refresh_list(select_key=current)

    def _on_auto_color_clicked(self) -> None:
        current = self._selected_speaker_key()
        if current is None:
            return
        self.editor._clear_custom_speaker_color(current)
        self._refresh_list(select_key=current)

    def _on_translate_clicked(self) -> None:
        current = self._selected_speaker_key()
        if current is None:
            return
        existing = self._translation_prefill_text(current)
        translated_name, ok = QInputDialog.getText(
            self,
            "Set Speaker EN",
            f"Set EN translation for '{current}':",
            text=existing,
        )
        if not ok:
            return
        self.editor._set_speaker_translation_everywhere(
            current, translated_name)
        self._refresh_list(select_key=current)

    def _on_clear_translation_clicked(self) -> None:
        current = self._selected_speaker_key()
        if current is None:
            return
        self.editor._set_speaker_translation_everywhere(current, "")
        self._refresh_list(select_key=current)


class VariableLengthManagerDialog(QDialog):
    def __init__(self, editor: QWidget):
        super().__init__(editor)
        self.editor: VariableLengthManagerHost = cast(
            VariableLengthManagerHost, editor
        )
        self.setWindowTitle("Variable Lengths")
        self.resize(520, 430)

        root = QVBoxLayout(self)
        info = QLabel(
            "Set expected visible length for \\V[n] tokens used by wrap/overflow checks.\n"
            "Per-variable overrides apply first, otherwise the default length is used."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self.default_label = QLabel("")
        self.default_label.setObjectName("MetaDim")
        root.addWidget(self.default_label)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(
            lambda _current, _previous: self._sync_action_buttons()
        )
        root.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        self.set_length_btn = QPushButton("Set Length...")
        self.reset_btn = QPushButton("Reset Override")
        self.default_btn = QPushButton("Set Default...")
        self.set_length_btn.clicked.connect(self._on_set_length_clicked)
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        self.default_btn.clicked.connect(self._on_set_default_clicked)
        actions.addWidget(self.set_length_btn)
        actions.addWidget(self.reset_btn)
        actions.addWidget(self.default_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        close_box.accepted.connect(self.accept)
        root.addWidget(close_box)

        self._refresh_list()

    def _selected_variable_id(self) -> Optional[int]:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(raw, int):
            return raw
        return None

    def _refresh_default_label(self) -> None:
        default_length = self.editor._default_variable_length_for_manager()
        self.default_label.setText(
            f"Default visible length: {default_length} chars"
        )

    def _refresh_list(self, select_variable_id: Optional[int] = None) -> None:
        variable_ids = self.editor._collect_variable_ids_for_manager()
        self.list_widget.clear()
        default_length = self.editor._default_variable_length_for_manager()
        for variable_id in variable_ids:
            estimate = self.editor._variable_length_estimate_for_id(variable_id)
            has_override = self.editor._variable_length_override_exists(variable_id)
            override_tag = "[override]" if has_override else "[default]"
            label = self.editor._variable_label_for_rpgm_index(variable_id).strip()
            item_text = (
                f"V[{variable_id}] {override_tag} len={estimate} - {label}"
                if label
                else f"V[{variable_id}] {override_tag} len={estimate}"
            )
            if not has_override and estimate != default_length:
                item_text += f" (default {default_length})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, variable_id)
            self.list_widget.addItem(item)

        if self.list_widget.count() > 0:
            selected_row = 0
            if select_variable_id is not None:
                for row in range(self.list_widget.count()):
                    current_id = self.list_widget.item(row).data(
                        Qt.ItemDataRole.UserRole
                    )
                    if current_id == select_variable_id:
                        selected_row = row
                        break
            self.list_widget.setCurrentRow(selected_row)

        self._refresh_default_label()
        self._sync_action_buttons()

    def _sync_action_buttons(self) -> None:
        selected_id = self._selected_variable_id()
        has_selection = selected_id is not None
        has_override = (
            has_selection
            and selected_id is not None
            and self.editor._variable_length_override_exists(selected_id)
        )
        self.set_length_btn.setEnabled(has_selection)
        self.reset_btn.setEnabled(bool(has_override))
        self.default_btn.setEnabled(True)

    def _on_set_length_clicked(self) -> None:
        variable_id = self._selected_variable_id()
        if variable_id is None:
            return
        current_length = self.editor._variable_length_estimate_for_id(variable_id)
        new_length, ok = QInputDialog.getInt(
            self,
            f"Set V[{variable_id}] Length",
            "Expected visible length (chars):",
            current_length,
            1,
            64,
            1,
        )
        if not ok:
            return
        self.editor._set_variable_length_override(variable_id, int(new_length))
        self._refresh_list(select_variable_id=variable_id)

    def _on_reset_clicked(self) -> None:
        variable_id = self._selected_variable_id()
        if variable_id is None:
            return
        if self.editor._clear_variable_length_override(variable_id):
            self._refresh_list(select_variable_id=variable_id)

    def _on_set_default_clicked(self) -> None:
        current_default = self.editor._default_variable_length_for_manager()
        new_default, ok = QInputDialog.getInt(
            self,
            "Set Default Variable Length",
            "Default expected visible length for \\V[n] (chars):",
            current_default,
            1,
            64,
            1,
        )
        if not ok:
            return
        self.editor._set_default_variable_length_estimate(int(new_default))
        selected_id = self._selected_variable_id()
        self._refresh_list(select_variable_id=selected_id)


class ItemNameDescriptionWidget(QFrame):
    activated = Signal(str)
    text_changed = Signal(str, object)
    insert_after_requested = Signal(str)
    delete_requested = Signal(str)
    reset_requested = Signal(str)
    split_overflow_requested = Signal(str)

    def __init__(
        self,
        segment: DialogueSegment,
        block_number: int,
        hide_control_codes_when_unfocused: bool,
        hidden_control_line_transform: Optional[Callable[[str], str]],
        hidden_control_colored_line_resolver: Optional[
            Callable[[str], tuple[str, list[tuple[int, int, str, float]]]]
        ],
        color_code_resolver: Optional[Callable[[int], str]],
        variable_label_resolver: Optional[Callable[[int], str]],
        translator_mode: bool,
        name_index_label: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.segment = segment
        self.block_number = block_number
        self.hide_control_codes_when_unfocused = hide_control_codes_when_unfocused
        self.hidden_control_line_transform = hidden_control_line_transform
        self.hidden_control_colored_line_resolver = hidden_control_colored_line_resolver
        self.color_code_resolver = color_code_resolver
        self.variable_label_resolver = variable_label_resolver
        self.translator_mode = translator_mode
        self.name_index_label = name_index_label.strip() or "Item"
        self._dark_theme = is_dark_palette()
        self._actor_id = self._actor_id_from_uid()
        self._suppress_name_changed = False
        self._suppress_desc_changed = False
        self._showing_raw_name = True
        self._showing_raw_desc = True
        self._selected = False
        self._audit_pinned = False
        self._flash_timer: Optional[QTimer] = None
        self._flash_step = 0
        self._flash_level = 0

        edited_lines = segment.translation_lines if translator_mode else segment.lines
        if not edited_lines:
            edited_lines = [""]
        source_lines = segment.source_lines or segment.original_lines or segment.lines or [
            ""]
        name_lines, desc_lines = self._split_combined_lines(edited_lines)
        source_name_lines, source_desc_lines = self._split_combined_lines(
            source_lines)
        self._raw_name_lines = list(name_lines)
        self._raw_desc_lines = list(desc_lines)
        self._source_name_text = "\n".join(source_name_lines).strip()
        self._source_desc_text = "\n".join(source_desc_lines).strip()

        self.setObjectName("DialogueBlock")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        self.title_label = QLabel("")
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        top_row.addWidget(self.title_label)
        top_row.addStretch(1)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(
            lambda: self.reset_requested.emit(self.segment.uid))
        top_row.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(top_row)

        self.context_label = QLabel(self.segment.context)
        self.context_label.setObjectName("MetaDim")
        root.addWidget(self.context_label)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("MetaDim")
        root.addWidget(self.meta_label)

        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)

        root.addWidget(QLabel("Name"))
        self.name_editor = QPlainTextEdit()
        self.name_editor.setFont(mono)
        self.name_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        _set_hard_newline_markers(self.name_editor, False)
        self.name_editor.setFixedHeight(
            max(52, QFontMetrics(mono).lineSpacing() * 2 + 16))
        self.name_editor.installEventFilter(self)
        self.name_editor.viewport().setMouseTracking(True)
        self.name_editor.viewport().installEventFilter(self)
        self.name_editor.textChanged.connect(self._on_name_text_changed)
        self._name_highlighter = ControlCodeHighlighter(
            self.name_editor.document(),
            self._dark_theme,
            color_code_resolver=self.color_code_resolver,
        )
        root.addWidget(self.name_editor)

        root.addWidget(QLabel("Description"))
        self.desc_editor = QPlainTextEdit()
        self.desc_editor.setFont(mono)
        self.desc_editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth)
        _set_hard_newline_markers(self.desc_editor, False)
        self.desc_editor.setFixedHeight(
            max(130, QFontMetrics(mono).lineSpacing() * 7 + 18))
        self.desc_editor.installEventFilter(self)
        self.desc_editor.viewport().setMouseTracking(True)
        self.desc_editor.viewport().installEventFilter(self)
        self.desc_editor.textChanged.connect(self._on_desc_text_changed)
        self._desc_highlighter = ControlCodeHighlighter(
            self.desc_editor.document(),
            self._dark_theme,
            color_code_resolver=self.color_code_resolver,
        )
        root.addWidget(self.desc_editor)

        self.status_label = QLabel("")
        self.status_label.setObjectName("MetaDim")
        root.addWidget(self.status_label)

        self._refresh_block_style()
        self._apply_editor_style()
        self._sync_control_code_visibility(force=True)
        self._refresh_meta_label()
        self._refresh_status()

    def _actor_id_from_uid(self) -> Optional[int]:
        match = NAME_INDEX_UID_RE.search(self.segment.uid)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _split_combined_lines(self, lines: list[str]) -> tuple[list[str], list[str]]:
        if not lines:
            return [""], [""]
        name_value = lines[0] if lines else ""
        desc_lines = list(lines[1:]) if len(lines) > 1 else []
        if desc_lines and desc_lines[0] == "":
            desc_lines = desc_lines[1:]
        if not desc_lines:
            desc_lines = [""]
        return [name_value], desc_lines

    def _merge_combined_lines(self) -> list[str]:
        name_value = self._raw_name_lines[0] if self._raw_name_lines else ""
        merged = [name_value, ""]
        if self._raw_desc_lines and not (len(self._raw_desc_lines) == 1 and self._raw_desc_lines[0] == ""):
            merged.extend(self._raw_desc_lines)
        return merged

    def _masked_lines_from_raw(self, lines: list[str]) -> list[str]:
        source_lines = lines or [""]
        if self.hidden_control_colored_line_resolver is not None:
            joined = "\n".join(source_lines)
            masked_text, _spans = self.hidden_control_colored_line_resolver(
                joined)
            return split_lines_preserve_empty(masked_text) or [""]
        masked: list[str] = []
        for line in source_lines:
            if self.hidden_control_line_transform is not None:
                masked.append(self.hidden_control_line_transform(line))
            else:
                masked.append(strip_control_tokens(line))
        return masked or [""]

    def _set_editor_lines(self, editor: QPlainTextEdit, lines: list[str], suppress_name: bool) -> None:
        text = "\n".join(lines or [""])
        if editor.toPlainText() == text:
            return
        if suppress_name:
            self._suppress_name_changed = True
        else:
            self._suppress_desc_changed = True
        editor.setPlainText(text)
        if suppress_name:
            self._suppress_name_changed = False
        else:
            self._suppress_desc_changed = False

    def _sync_single_editor_visibility(self, editor: QPlainTextEdit, force: bool = False) -> None:
        if editor is self.name_editor:
            show_raw = (
                not self.hide_control_codes_when_unfocused) or self.name_editor.hasFocus()
            _set_hard_newline_markers(self.name_editor, self.name_editor.hasFocus())
            if (not force) and show_raw == self._showing_raw_name:
                return
            self._showing_raw_name = show_raw
            lines = self._raw_name_lines if show_raw else self._masked_lines_from_raw(
                self._raw_name_lines)
            self._set_editor_lines(self.name_editor, lines, suppress_name=True)
            return

        show_raw = (
            not self.hide_control_codes_when_unfocused) or self.desc_editor.hasFocus()
        _set_hard_newline_markers(self.desc_editor, self.desc_editor.hasFocus())
        if (not force) and show_raw == self._showing_raw_desc:
            return
        self._showing_raw_desc = show_raw
        lines = self._raw_desc_lines if show_raw else self._masked_lines_from_raw(
            self._raw_desc_lines)
        self._set_editor_lines(self.desc_editor, lines, suppress_name=False)

    def _sync_control_code_visibility(self, force: bool = False) -> None:
        self._sync_single_editor_visibility(self.name_editor, force=force)
        self._sync_single_editor_visibility(self.desc_editor, force=force)
        self._refresh_status()

    def set_hide_control_codes_when_unfocused(self, enabled: bool) -> None:
        new_value = bool(enabled)
        if self.hide_control_codes_when_unfocused == new_value:
            return
        self.hide_control_codes_when_unfocused = new_value
        self._sync_control_code_visibility(force=True)

    def focus_editor(self) -> None:
        self.name_editor.setFocus()

    def set_selected_state(self, selected: bool) -> None:
        new_value = bool(selected)
        if self._selected == new_value:
            return
        self._selected = new_value
        self._refresh_block_style()
        self._apply_editor_style()

    def set_audit_pinned_state(self, pinned: bool) -> None:
        new_value = bool(pinned)
        if self._audit_pinned == new_value:
            return
        self._audit_pinned = new_value
        self._refresh_block_style()
        self._apply_editor_style()

    def flash_highlight(self) -> None:
        if self._flash_timer is None:
            self._flash_timer = QTimer(self)
            self._flash_timer.setInterval(95)
            self._flash_timer.timeout.connect(self._advance_flash_highlight)
        self._flash_timer.stop()
        self._flash_step = 0
        self._advance_flash_highlight()
        if self._flash_timer is not None and self._flash_level > 0:
            self._flash_timer.start()

    def _clear_flash_highlight(self) -> None:
        self._flash_level = 0
        self._refresh_block_style()
        self._apply_editor_style()

    def _advance_flash_highlight(self) -> None:
        levels = (2, 1, 2, 0)
        if self._flash_step >= len(levels):
            if self._flash_timer is not None:
                self._flash_timer.stop()
            self._clear_flash_highlight()
            return
        self._flash_level = int(levels[self._flash_step])
        self._flash_step += 1
        self._refresh_block_style()
        self._apply_editor_style()
        if self._flash_level == 0 and self._flash_timer is not None:
            self._flash_timer.stop()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.name_editor or watched is self.desc_editor:
            if event.type() == QEvent.Type.FocusIn:
                self._sync_single_editor_visibility(
                    cast(QPlainTextEdit, watched), force=True)
                self.activated.emit(self.segment.uid)
            elif event.type() == QEvent.Type.FocusOut:
                self._sync_single_editor_visibility(
                    cast(QPlainTextEdit, watched), force=True)
            elif event.type() == QEvent.Type.MouseButtonPress:
                self.activated.emit(self.segment.uid)
        elif watched is self.name_editor.viewport():
            if self._handle_variable_tooltip_event(self.name_editor, event):
                return True
        elif watched is self.desc_editor.viewport():
            if self._handle_variable_tooltip_event(self.desc_editor, event):
                return True
        return super().eventFilter(watched, event)

    def _variable_tooltip_text(self, editor: QPlainTextEdit, event_pos: QPoint) -> str:
        variable_id = _variable_token_id_at_editor_position(editor, event_pos)
        if variable_id is None:
            return ""
        details = (
            self.variable_label_resolver(variable_id).strip()
            if self.variable_label_resolver is not None
            else ""
        )
        if details:
            return f"\\V[{variable_id}] -> {details}"
        return f"\\V[{variable_id}] -> system.variables[{variable_id}]"

    def _handle_variable_tooltip_event(self, editor: QPlainTextEdit, event: QEvent) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return False
        help_event = cast(QHelpEvent, event)
        text = self._variable_tooltip_text(editor, help_event.pos())
        if not text:
            QToolTip.hideText()
            return False
        QToolTip.showText(help_event.globalPos(), text, editor.viewport())
        return True

    def _refresh_block_style(self) -> None:
        block_bg = "#13293d" if self._dark_theme else "#e9f6ff"
        block_border = "#0ea5e9" if self._dark_theme else "#0284c7"
        meta_color = "#7dd3fc" if self._dark_theme else "#075985"
        border_width = 2
        if self._selected:
            block_bg = "#14362e" if self._dark_theme else "#dcfce7"
            meta_color = "#bbf7d0" if self._dark_theme else "#166534"
        if self._flash_level > 0 and not self._audit_pinned:
            block_bg = "#5b3f00" if self._dark_theme else "#fef08a"
            meta_color = "#fde68a" if self._dark_theme else "#854d0e"
            if self._flash_level == 1:
                block_bg = "#4b3500" if self._dark_theme else "#fef9c3"
        if self._audit_pinned:
            block_bg = "#3f1d1d" if self._dark_theme else "#fee2e2"
            block_border = "#ef4444" if self._dark_theme else "#b91c1c"
            meta_color = "#fecaca" if self._dark_theme else "#7f1d1d"
        self.title_label.setText(
            f"{self.name_index_label} {self._actor_id}"
            if self._actor_id is not None
            else f"{self.name_index_label} Entry {self.block_number}"
        )
        self.setStyleSheet(
            f"""
            QFrame#DialogueBlock {{
                background: {block_bg};
                border: {border_width}px solid {block_border};
                border-radius: 8px;
            }}
            QLabel#MetaDim {{
                color: {meta_color};
            }}
            """
        )

    def _apply_editor_style(self) -> None:
        bg = "#0b1e2d" if self._dark_theme else "#f8fcff"
        fg = "#e2e8f0" if self._dark_theme else "#0f172a"
        border = "#38bdf8" if self._dark_theme else "#0284c7"
        if self._selected:
            bg = "#0f2d22" if self._dark_theme else "#f0fdf4"
        if self._flash_level > 0 and not self._audit_pinned:
            bg = "#3b2a00" if self._dark_theme else "#fefce8"
        if self._audit_pinned:
            bg = "#2a1515" if self._dark_theme else "#fff1f2"
            border = "#ef4444" if self._dark_theme else "#b91c1c"
        style = (
            "QPlainTextEdit {"
            f"background: {bg}; color: {fg}; border: 2px solid {border}; border-radius: 6px;"
            "}"
        )
        self.name_editor.setStyleSheet(style)
        self.desc_editor.setStyleSheet(style)

    def _refresh_meta_label(self) -> None:
        actor_id_text = str(
            self._actor_id) if self._actor_id is not None else "?"
        mode_text = "EN text" if self.translator_mode else "JP text"
        self.meta_label.setText(
            f"{self.name_index_label} ID: {actor_id_text} | Fields: name + description | View: {mode_text}"
        )

    def _refresh_status(self) -> None:
        name_chars = sum(len(line) for line in self._raw_name_lines)
        desc_chars = sum(len(line) for line in self._raw_desc_lines)
        name_label = "char" if name_chars == 1 else "chars"
        desc_label = "char" if desc_chars == 1 else "chars"
        self.status_label.setText(
            f"name: {name_chars} {name_label} | description: {desc_chars} {desc_label}")
        current = self._merge_combined_lines()
        if self.translator_mode:
            current_tl = current if current else [""]
            original_tl = (
                self.segment.original_translation_lines
                if self.segment.original_translation_lines
                else [""]
            )
            self.reset_button.setEnabled(
                current_tl != original_tl)
        else:
            self.reset_button.setEnabled(
                current != self.segment.original_lines)
        if self.translator_mode:
            if not any(line.strip() for line in self._raw_name_lines) and self._source_name_text:
                self.name_editor.setPlaceholderText(self._source_name_text)
            else:
                self.name_editor.setPlaceholderText("")
            if not any(line.strip() for line in self._raw_desc_lines) and self._source_desc_text:
                self.desc_editor.setPlaceholderText(self._source_desc_text)
            else:
                self.desc_editor.setPlaceholderText("")

    def _commit_lines(self) -> None:
        combined = self._merge_combined_lines()
        if self.translator_mode:
            self.segment.translation_lines = list(combined)
        else:
            self.segment.lines = list(combined)
        self._refresh_status()
        self.text_changed.emit(self.segment.uid, list(combined))

    def _on_name_text_changed(self) -> None:
        if self._suppress_name_changed or not self._showing_raw_name:
            return
        self._raw_name_lines = split_lines_preserve_empty(
            self.name_editor.toPlainText())
        if not self._raw_name_lines:
            self._raw_name_lines = [""]
        if len(self._raw_name_lines) > 1:
            self._raw_name_lines = [
                " ".join(line for line in self._raw_name_lines if line)]
        self._set_editor_lines(
            self.name_editor, self._raw_name_lines, suppress_name=True)
        self._commit_lines()

    def _on_desc_text_changed(self) -> None:
        if self._suppress_desc_changed or not self._showing_raw_desc:
            return
        self._raw_desc_lines = split_lines_preserve_empty(
            self.desc_editor.toPlainText())
        if not self._raw_desc_lines:
            self._raw_desc_lines = [""]
        self._commit_lines()


class DialogueBlockWidget(QFrame):
    activated = Signal(str)
    text_changed = Signal(str, object)
    insert_after_requested = Signal(str)
    delete_requested = Signal(str)
    reset_requested = Signal(str)
    split_overflow_requested = Signal(str)
    line1_inference_override_changed = Signal(str, bool, bool, bool, bool)

    def __init__(
        self,
        segment: DialogueSegment,
        block_number: int,
        thin_width: int,
        wide_width: int,
        max_lines: int,
        infer_name_from_first_line: bool,
        hide_control_codes_when_unfocused: bool,
        hidden_control_line_transform: Optional[Callable[[str], str]],
        hidden_control_colored_line_resolver: Optional[
            Callable[[str], tuple[str, list[tuple[int, int, str, float]]]]
        ],
        speaker_display_resolver: Optional[Callable[[str], str]],
        speaker_display_html_resolver: Optional[Callable[[str], str]],
        hint_display_html_resolver: Optional[Callable[[str], str]],
        color_code_resolver: Optional[Callable[[int], str]],
        variable_label_resolver: Optional[Callable[[int], str]],
        speaker_tint_color: str,
        translator_mode: bool,
        highlight_control_mismatch: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
        allow_structural_actions: bool,
        inferred_speaker_name_resolver: Optional[Callable[[DialogueSegment], str]],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.segment = segment
        self.block_number = block_number
        self.thin_width = max(1, thin_width)
        self.wide_width = max(1, wide_width)
        self.max_lines = max(1, max_lines)
        self.infer_name_from_first_line = infer_name_from_first_line
        self.hide_control_codes_when_unfocused = hide_control_codes_when_unfocused
        self.hidden_control_line_transform = hidden_control_line_transform
        self.hidden_control_colored_line_resolver = hidden_control_colored_line_resolver
        self.speaker_display_resolver = speaker_display_resolver
        self.speaker_display_html_resolver = speaker_display_html_resolver
        self.hint_display_html_resolver = hint_display_html_resolver
        self.color_code_resolver = color_code_resolver
        self.variable_label_resolver = variable_label_resolver
        self.speaker_tint_color = speaker_tint_color
        self.translator_mode = translator_mode
        self.control_mismatch_highlighting_enabled = bool(
            highlight_control_mismatch
        )
        self.actor_mode = actor_mode
        self.name_index_kind = name_index_kind.strip().lower()
        self.name_index_label = name_index_label.strip(
        ) if name_index_label.strip() else "Entry"
        self.allow_structural_actions = allow_structural_actions
        self.inferred_speaker_name_resolver = inferred_speaker_name_resolver
        self._actor_id = self._actor_id_from_uid()
        self._name_index_field = self._name_index_field_from_uid()
        self._suppress_text_changed = False
        self._displaying_masked_text = False
        self._masked_color_spans: list[list[tuple[int, int, str, float]]] = []
        self._source_hint_lines: list[str] = []
        self._source_hint_overlay: Optional[QLabel] = None
        self._selected = False
        self._audit_pinned = False
        self._flash_timer: Optional[QTimer] = None
        self._flash_step = 0
        self._flash_level = 0
        self._dark_theme = is_dark_palette()
        if self._dark_theme:
            self._meta_dim_color = "#cbd5e1"
            self._status_ok_color = "#cbd5e1"
            self._status_warn_color = "#fca5a5"
            self._overflow_bg = "#7f1d1d"
            self._overflow_fg = "#fecaca"
            self._block_bg = "#1f2937"
            self._block_border = "#475569"
            self._editor_bg = "#0f172a"
            self._editor_bg_changed = "#162826"
            self._editor_bg_inserted = "#102337"
            self._editor_bg_warning = "#3f1d1d"
            self._editor_fg = "#e2e8f0"
            self._editor_border_thin = "#f59e0b"
            self._editor_border_wide = "#38bdf8"
            self._editor_border_warn = "#f87171"
            self._actor_block_bg = "#13293d"
            self._actor_block_border = "#0ea5e9"
            self._actor_meta_color = "#7dd3fc"
            self._actor_editor_bg = "#0b1e2d"
            self._actor_editor_bg_changed = "#103147"
            self._actor_editor_border = "#38bdf8"
        else:
            self._meta_dim_color = "#475569"
            self._status_ok_color = "#475569"
            self._status_warn_color = "#b91c1c"
            self._overflow_bg = "#fee2e2"
            self._overflow_fg = "#991b1b"
            self._block_bg = "#f8fafc"
            self._block_border = "#cbd5e1"
            self._editor_bg = "#ffffff"
            self._editor_bg_changed = "#f0fdf4"
            self._editor_bg_inserted = "#ecfeff"
            self._editor_bg_warning = "#fff1f2"
            self._editor_fg = "#0f172a"
            self._editor_border_thin = "#ea580c"
            self._editor_border_wide = "#0284c7"
            self._editor_border_warn = "#b91c1c"
            self._actor_block_bg = "#e9f6ff"
            self._actor_block_border = "#0284c7"
            self._actor_meta_color = "#075985"
            self._actor_editor_bg = "#f8fcff"
            self._actor_editor_bg_changed = "#dff3ff"
            self._actor_editor_border = "#0284c7"

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("DialogueBlock")
        self._has_warning = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top_row = QHBoxLayout()
        self.title_label = QLabel("")
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        top_row.addWidget(self.title_label)
        top_row.addStretch(1)

        self._collapse_button_text = "Collapse"
        self._smart_collapse_button_text = "Smart Collapse"
        self._wrap_button_text = "Wrap"
        self.collapse_button = QPushButton("Collapse")
        self.smart_collapse_button = QPushButton("Smart Collapse")
        self.wrap_button = QPushButton("Wrap")
        self.insert_button = QPushButton("Insert Below")
        self.delete_button = QPushButton("Delete")
        self.collapse_button.setToolTip(
            "Force-collapse lines and refill width without sentence heuristics.")
        self.smart_collapse_button.setToolTip(
            "Collapse with sentence heuristics.")
        self.wrap_button.setToolTip("Wrap each existing line to fit width.")
        self.collapse_button.clicked.connect(self._on_collapse_clicked)
        self.smart_collapse_button.clicked.connect(
            self._on_smart_collapse_clicked)
        self.wrap_button.clicked.connect(self._on_wrap_clicked)
        self.insert_button.clicked.connect(
            lambda: self.insert_after_requested.emit(self.segment.uid))
        self.delete_button.clicked.connect(
            lambda: self.delete_requested.emit(self.segment.uid))
        top_row.addWidget(self.collapse_button)
        top_row.addWidget(self.smart_collapse_button)
        top_row.addWidget(self.wrap_button)
        top_row.addWidget(self.insert_button)
        top_row.addWidget(self.delete_button)
        self.insert_button.setEnabled(self.allow_structural_actions)
        self.delete_button.setEnabled(
            self.allow_structural_actions
            and (
                (not self.translator_mode)
                or self.segment.inserted
                or self.segment.translation_only
            )
        )
        if self.actor_mode:
            self.collapse_button.setVisible(False)
            self.smart_collapse_button.setVisible(False)
            self.wrap_button.setVisible(False)
            self.insert_button.setVisible(False)
            self.delete_button.setVisible(False)
        elif not self._is_standard_dialogue_block():
            self.collapse_button.setVisible(False)
            self.smart_collapse_button.setVisible(False)
            self.wrap_button.setVisible(False)
            self.insert_button.setVisible(False)
            self.delete_button.setVisible(False)
        root.addLayout(top_row)

        self.context_label = QLabel(self.segment.context)
        self.context_label.setObjectName("MetaDim")
        root.addWidget(self.context_label)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("MetaDim")
        root.addWidget(self.meta_label)

        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.setSpacing(8)

        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)

        self.editor = QPlainTextEdit()
        self.editor.setFont(mono)
        _set_hard_newline_markers(self.editor, False)
        self._raw_lines = [""]
        self._load_editor_lines_from_segment()
        self._set_editor_text_lines(self._raw_lines)
        if self.translator_mode:
            source_lines = self.segment.source_lines or self.segment.original_lines or self.segment.lines or [
                ""]
            self._source_hint_lines = list(source_lines)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._control_code_highlighter = ControlCodeHighlighter(
            self.editor.document(),
            self._dark_theme,
            color_code_resolver=self.color_code_resolver,
        )
        self._source_hint_overlay = QLabel(self.editor.viewport())
        self._source_hint_overlay.setTextFormat(Qt.TextFormat.RichText)
        self._source_hint_overlay.setWordWrap(True)
        self._source_hint_overlay.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._source_hint_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        self._source_hint_overlay.setStyleSheet("background: transparent;")
        self._source_hint_overlay.setFont(mono)
        self.editor.viewport().setMouseTracking(True)
        self.editor.viewport().installEventFilter(self)
        self._apply_editor_width()
        self.editor.installEventFilter(self)
        self.editor.textChanged.connect(self._on_text_changed)
        editor_row.addWidget(self.editor)
        editor_row.addStretch(1)
        root.addLayout(editor_row)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(8)
        self.status_label = QLabel("")
        self.status_label.setObjectName("MetaDim")
        footer_row.addWidget(self.status_label, 1)
        self.line1_not_speaker_button = QPushButton("Line1 Not Speaker")
        self.line1_not_speaker_button.setCheckable(True)
        self.line1_not_speaker_button.setToolTip(
            "Checked: treat line 1 as dialogue text. Unchecked: infer line 1 as speaker."
        )
        self.line1_not_speaker_button.clicked.connect(
            self._on_line1_not_speaker_clicked
        )
        footer_row.addWidget(
            self.line1_not_speaker_button,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        self.move_overflow_button = QPushButton("Move Overflow Down")
        self.move_overflow_button.setToolTip(
            "Create a new block below and move overflow lines into it.")
        self.move_overflow_button.clicked.connect(
            self._on_move_overflow_clicked)
        self.move_overflow_button.setVisible(False)
        if not self.allow_structural_actions:
            self.move_overflow_button.setEnabled(False)
            self.move_overflow_button.setVisible(False)
        footer_row.addWidget(self.move_overflow_button, 0,
                             Qt.AlignmentFlag.AlignRight)
        self.reset_button = QPushButton("Reset")
        if self.translator_mode:
            self.reset_button.setToolTip(
                "Reset this translation block to its last saved translation text.")
        else:
            self.reset_button.setToolTip(
                "Reset this block to its last saved text.")
        self.reset_button.clicked.connect(self._on_reset_clicked)
        footer_row.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(footer_row)

        self._sync_control_code_visibility(force=True)
        self._refresh_meta_label()
        self._refresh_status()

    def focus_editor(self) -> None:
        self.editor.setFocus()

    def set_selected_state(self, selected: bool) -> None:
        new_value = bool(selected)
        if self._selected == new_value:
            return
        self._selected = new_value
        self._refresh_block_style()
        self._apply_editor_style(self._has_warning)

    def set_audit_pinned_state(self, pinned: bool) -> None:
        new_value = bool(pinned)
        if self._audit_pinned == new_value:
            return
        self._audit_pinned = new_value
        self._refresh_block_style()
        self._apply_editor_style(self._has_warning)

    def flash_highlight(self) -> None:
        if self._flash_timer is None:
            self._flash_timer = QTimer(self)
            self._flash_timer.setInterval(95)
            self._flash_timer.timeout.connect(self._advance_flash_highlight)
        self._flash_timer.stop()
        self._flash_step = 0
        self._advance_flash_highlight()
        if self._flash_timer is not None and self._flash_level > 0:
            self._flash_timer.start()

    def _clear_flash_highlight(self) -> None:
        self._flash_level = 0
        self._refresh_block_style()
        self._apply_editor_style(self._has_warning)

    def _advance_flash_highlight(self) -> None:
        levels = (2, 1, 2, 0)
        if self._flash_step >= len(levels):
            if self._flash_timer is not None:
                self._flash_timer.stop()
            self._clear_flash_highlight()
            return
        self._flash_level = int(levels[self._flash_step])
        self._flash_step += 1
        self._refresh_block_style()
        self._apply_editor_style(self._has_warning)
        if self._flash_level == 0 and self._flash_timer is not None:
            self._flash_timer.stop()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.editor:
            if event.type() == QEvent.Type.FocusIn:
                self._sync_control_code_visibility(force=True)
                self.activated.emit(self.segment.uid)
            elif event.type() == QEvent.Type.FocusOut:
                self._sync_control_code_visibility(force=True)
            elif event.type() == QEvent.Type.MouseButtonPress:
                self.activated.emit(self.segment.uid)
        elif watched is self.editor.viewport():
            if self._handle_variable_tooltip_event(event):
                return True
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self._refresh_source_hint_overlay()
        return super().eventFilter(watched, event)

    def _variable_tooltip_text(self, event_pos: QPoint) -> str:
        variable_id = _variable_token_id_at_editor_position(self.editor, event_pos)
        if variable_id is None:
            return ""
        details = (
            self.variable_label_resolver(variable_id).strip()
            if self.variable_label_resolver is not None
            else ""
        )
        if details:
            return f"\\V[{variable_id}] -> {details}"
        return f"\\V[{variable_id}] -> system.variables[{variable_id}]"

    def _handle_variable_tooltip_event(self, event: QEvent) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return False
        help_event = cast(QHelpEvent, event)
        text = self._variable_tooltip_text(help_event.pos())
        if not text:
            QToolTip.hideText()
            return False
        QToolTip.showText(help_event.globalPos(), text, self.editor.viewport())
        return True

    def mousePressEvent(self, event: Any) -> None:
        self.activated.emit(self.segment.uid)
        super().mousePressEvent(event)

    def refresh_metadata(self) -> None:
        self._refresh_meta_label()
        self._refresh_status()

    def _actor_id_from_uid(self) -> Optional[int]:
        match = NAME_INDEX_UID_RE.search(self.segment.uid)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _name_index_field_from_uid(self) -> str:
        match = NAME_INDEX_UID_RE.search(self.segment.uid)
        if not match:
            return "name"
        raw_field = match.group(2)
        if isinstance(raw_field, str):
            cleaned = raw_field.strip()
            if cleaned:
                return cleaned
        return "name"

    def _width_chars(self) -> int:
        if self.actor_mode:
            return 4096
        return self.thin_width if self.segment.has_face else self.wide_width

    def _width_mode_name(self) -> str:
        return "thin" if self.segment.has_face else "wide"

    def _is_standard_dialogue_block(self) -> bool:
        return self.segment.segment_kind in {"dialogue", "script_message"}

    def _is_choice_block(self) -> bool:
        return self.segment.segment_kind == "choice"

    def _line1_inference_is_disabled(self) -> bool:
        return bool(getattr(self.segment, "disable_line1_speaker_inference", False))

    def _line1_inference_is_forced(self) -> bool:
        return bool(getattr(self.segment, "force_line1_speaker_inference", False)) and (
            not self._line1_inference_is_disabled()
        )

    def _segment_storage_lines(self) -> list[str]:
        lines = self.segment.translation_lines if self.translator_mode else self.segment.lines
        if lines:
            return list(lines)
        return [""]

    def _line1_inference_active(self) -> bool:
        if self._line1_inference_is_disabled():
            return False
        if not self._is_standard_dialogue_block():
            return False
        if not self.infer_name_from_first_line:
            return False
        if self.segment.speaker_name != NO_SPEAKER_KEY:
            return False
        lines = self._segment_storage_lines()
        if len(lines) <= 1:
            return False
        if self.inferred_speaker_name_resolver is None:
            return False
        try:
            inferred = self.inferred_speaker_name_resolver(self.segment)
        except Exception:
            return False
        return bool(inferred.strip())

    def _line1_inference_prefix_text(self) -> str:
        if self.translator_mode:
            source_lines = self.segment.source_lines or self.segment.original_lines or self.segment.lines or [
                ""]
            return source_lines[0] if source_lines else ""
        source_lines = self.segment.lines or [""]
        return source_lines[0] if source_lines else ""

    def _line1_inference_source_lines(self) -> list[str]:
        if self.translator_mode:
            source_lines = self.segment.source_lines or self.segment.original_lines or self.segment.lines or [
                ""]
            return list(source_lines) if source_lines else [""]
        source_lines = self.segment.lines or [""]
        return list(source_lines) if source_lines else [""]

    def _editor_lines_from_storage_lines(self, storage_lines: list[str]) -> list[str]:
        lines = list(storage_lines) if storage_lines else [""]
        if self._line1_inference_active():
            if len(lines) > 1:
                return list(lines[1:])
            return [""]
        return lines

    def _storage_lines_from_editor_lines(self, editor_lines: list[str]) -> list[str]:
        lines = list(editor_lines) if editor_lines else [""]
        if not self._line1_inference_active():
            return lines
        return [self._line1_inference_prefix_text()] + lines

    def _load_editor_lines_from_segment(self) -> None:
        self._raw_lines = self._editor_lines_from_storage_lines(
            self._segment_storage_lines()
        )

    def _line1_inference_override_available(self) -> bool:
        return (
            (not self.actor_mode)
            and self._is_standard_dialogue_block()
            and self.infer_name_from_first_line
            and self.segment.speaker_name == NO_SPEAKER_KEY
            and len(self._line1_inference_source_lines()) > 1
        )

    def _refresh_line1_inference_override_button(self) -> None:
        available = self._line1_inference_override_available()
        self.line1_not_speaker_button.setVisible(available)
        self.line1_not_speaker_button.setEnabled(available)
        checked = not self._line1_inference_active()
        if self.line1_not_speaker_button.isChecked() == checked:
            return
        self.line1_not_speaker_button.blockSignals(True)
        try:
            self.line1_not_speaker_button.setChecked(checked)
        finally:
            self.line1_not_speaker_button.blockSignals(False)

    def _on_line1_not_speaker_clicked(self, checked: bool) -> None:
        prev_disabled = self._line1_inference_is_disabled()
        prev_forced = self._line1_inference_is_forced()
        disabled = bool(checked)
        forced = not disabled
        if (
            prev_disabled == disabled
            and prev_forced == forced
        ):
            return
        self.segment.disable_line1_speaker_inference = disabled
        self.segment.force_line1_speaker_inference = forced
        self._load_editor_lines_from_segment()
        self._sync_control_code_visibility(force=True)
        self.line1_inference_override_changed.emit(
            self.segment.uid,
            disabled,
            forced,
            prev_disabled,
            prev_forced,
        )
        self.refresh_metadata()

    def _is_changed(self) -> bool:
        line1_override_changed = (
            bool(self.segment.disable_line1_speaker_inference)
            != bool(self.segment.original_disable_line1_speaker_inference)
            or bool(self.segment.force_line1_speaker_inference)
            != bool(self.segment.original_force_line1_speaker_inference)
        )
        if self.translator_mode:
            speaker_changed = self.segment.translation_speaker.strip(
            ) != self.segment.original_translation_speaker.strip()
            current_tl = (
                self.segment.translation_lines
                if self.segment.translation_lines
                else [""]
            )
            original_tl = (
                self.segment.original_translation_lines
                if self.segment.original_translation_lines
                else [""]
            )
            return current_tl != original_tl or speaker_changed or line1_override_changed
        return (
            self.segment.inserted
            or self.segment.lines != self.segment.original_lines
            or line1_override_changed
        )

    def _apply_editor_width(self) -> None:
        if self.actor_mode:
            metrics = QFontMetrics(self.editor.font())
            self.editor.setMinimumWidth(
                max(420, metrics.horizontalAdvance("M") * 24))
            self.editor.setMaximumWidth(16777215)
            if self.name_index_kind == "item" and self._name_index_field == "description":
                self.editor.setFixedHeight(max(164, metrics.lineSpacing() * 8))
            else:
                self.editor.setFixedHeight(max(96, metrics.lineSpacing() * 3))
            return
        char_width = self._width_chars()
        metrics = QFontMetrics(self.editor.font())
        pixel_width = metrics.horizontalAdvance("M") * (char_width + 2)
        self.editor.setMinimumWidth(pixel_width)
        self.editor.setMaximumWidth(pixel_width + 36)
        self.editor.setFixedHeight(
            max(130, metrics.lineSpacing() * (self.max_lines + 2)))

    def _refresh_block_style(self) -> None:
        tags: list[str] = []
        if self.segment.inserted:
            tags.append("new")
        elif self._is_changed():
            tags.append("edited")
        if self._has_warning:
            tags.append("warning")

        if self.actor_mode:
            block_bg = self._actor_block_bg
            block_border = self._actor_block_border
            meta_color = self._actor_meta_color
            if self._has_warning:
                block_border = self._editor_border_warn
        else:
            block_bg = self._block_bg
            speaker_border = QColor(self.speaker_tint_color)
            block_border = self.speaker_tint_color if speaker_border.isValid() else self._block_border
            meta_color = self._meta_dim_color
            if self._is_choice_block():
                block_bg = "#2f2a1d" if self._dark_theme else "#fef3c7"
                block_border = "#f59e0b" if self._dark_theme else "#d97706"
                meta_color = "#fde68a" if self._dark_theme else "#92400e"
        border_width = 2
        if self._selected:
            block_bg = "#14362e" if self._dark_theme else "#dcfce7"
            meta_color = "#bbf7d0" if self._dark_theme else "#166534"
        if self._flash_level > 0 and not self._audit_pinned:
            block_bg = "#5b3f00" if self._dark_theme else "#fef08a"
            meta_color = "#fde68a" if self._dark_theme else "#854d0e"
            if self._flash_level == 1:
                block_bg = "#4b3500" if self._dark_theme else "#fef9c3"
        if self._audit_pinned:
            block_bg = "#3f1d1d" if self._dark_theme else "#fee2e2"
            block_border = "#ef4444" if self._dark_theme else "#b91c1c"
            meta_color = "#fecaca" if self._dark_theme else "#7f1d1d"
        title_suffix = f" ({', '.join(tags)})" if tags else ""

        if self.actor_mode:
            label = (
                f"{self.name_index_label} {self._actor_id}"
                if self._actor_id is not None
                else f"{self.name_index_label} Entry {self.block_number}"
            )
            self.title_label.setText(f"{label}{title_suffix}")
        else:
            block_prefix = "Block"
            if self._is_choice_block():
                block_prefix = "Choice"
            self.title_label.setText(
                f"{block_prefix} {self.block_number}{title_suffix}")
        self.setStyleSheet(
            f"""
            QFrame#DialogueBlock {{
                background: {block_bg};
                border: {border_width}px solid {block_border};
                border-radius: 8px;
            }}
            QLabel#MetaDim {{
                color: {meta_color};
            }}
            """
        )

    def _apply_editor_style(self, has_warning: bool) -> None:
        if self.actor_mode:
            bg = self._actor_editor_bg
            if has_warning:
                bg = self._editor_bg_warning
            elif self._is_changed():
                bg = self._actor_editor_bg_changed
            border = self._actor_editor_border
            if has_warning:
                border = self._editor_border_warn
        else:
            bg = self._editor_bg
            if has_warning:
                bg = self._editor_bg_warning
            elif self.segment.inserted:
                bg = self._editor_bg_inserted
            elif self._is_changed():
                bg = self._editor_bg_changed

            border = self._editor_border_thin if self.segment.has_face else self._editor_border_wide
            if has_warning:
                border = self._editor_border_warn
        if self._selected and not has_warning:
            bg = "#0f2d22" if self._dark_theme else "#f0fdf4"
        if self._flash_level > 0 and not self._audit_pinned:
            bg = "#3b2a00" if self._dark_theme else "#fefce8"
        if self._audit_pinned:
            bg = "#2a1515" if self._dark_theme else "#fff1f2"
            border = "#ef4444" if self._dark_theme else "#b91c1c"
        editor_fg = (
            "transparent"
            if self._should_show_masked_preview_overlay()
            else self._editor_fg
        )
        self.editor.setStyleSheet(
            f"""
            QPlainTextEdit {{
                background: {bg};
                color: {editor_fg};
                border: 2px solid {border};
                border-radius: 6px;
            }}
            """
        )

    def _set_editor_text_lines(self, lines: list[str]) -> None:
        text = "\n".join(lines or [""])
        if self.editor.toPlainText() == text:
            return
        self._suppress_text_changed = True
        self.editor.setPlainText(text)
        self._suppress_text_changed = False

    def _source_hint_html(self) -> str:
        if not self._source_hint_lines:
            return ""
        if self.hint_display_html_resolver is not None:
            full_text = "\n".join(self._source_hint_lines)
            rendered = self.hint_display_html_resolver(full_text).strip()
            if rendered:
                return rendered

        rows: list[str] = []
        for line in self._source_hint_lines:
            rows.append(html.escape(line) if line else "&nbsp;")
        return "<br/>".join(rows)

    def _should_show_masked_preview_overlay(self) -> bool:
        return (
            self._displaying_masked_text
            and self.hidden_control_colored_line_resolver is not None
        )

    def _masked_preview_html(self) -> str:
        lines = self._raw_lines or [""]
        full_text = "\n".join(lines)
        if self.speaker_display_html_resolver is not None:
            rendered = self.speaker_display_html_resolver(full_text).strip()
            if rendered:
                return rendered
        rows: list[str] = []
        for line in lines:
            rows.append(html.escape(line) if line else "&nbsp;")
        return "<br/>".join(rows)

    def _refresh_source_hint_overlay(self) -> None:
        if self._source_hint_overlay is None:
            return
        has_user_text = any(line.strip() for line in self._raw_lines)
        show_masked_preview = self._should_show_masked_preview_overlay()
        show_source_hint = (
            self.translator_mode
            and not has_user_text
            and bool(self._source_hint_lines)
        )
        should_show = show_masked_preview or show_source_hint
        if should_show:
            if show_masked_preview:
                self._source_hint_overlay.setText(self._masked_preview_html())
            else:
                self._source_hint_overlay.setText(self._source_hint_html())
            self._source_hint_overlay.setGeometry(
                self.editor.viewport().rect().adjusted(6, 4, -6, -4)
            )
            self._source_hint_overlay.raise_()
        self._source_hint_overlay.setVisible(should_show)

    def _masked_lines_from_raw(self, lines: list[str]) -> list[str]:
        source_lines = lines or [""]
        if self.hidden_control_colored_line_resolver is not None:
            joined = "\n".join(source_lines)
            masked_text, spans = self.hidden_control_colored_line_resolver(
                joined)
            split_lines, spans_per_line = _split_masked_text_and_spans(
                masked_text, list(spans)
            )
            self._masked_color_spans = spans_per_line
            return split_lines or [""]

        masked: list[str] = []
        spans_per_line: list[list[tuple[int, int, str, float]]] = []
        for line in source_lines:
            if self.hidden_control_line_transform is not None:
                masked.append(self.hidden_control_line_transform(line))
                spans_per_line.append([])
            else:
                masked.append(strip_control_tokens(line))
                spans_per_line.append([])
        self._masked_color_spans = spans_per_line
        return masked or [""]

    def _should_show_raw_codes(self) -> bool:
        if not self.hide_control_codes_when_unfocused:
            return True
        return self.editor.hasFocus()

    def set_hide_control_codes_when_unfocused(self, enabled: bool) -> None:
        new_value = bool(enabled)
        if self.hide_control_codes_when_unfocused == new_value:
            return
        self.hide_control_codes_when_unfocused = new_value
        self._sync_control_code_visibility(force=True)

    def set_control_mismatch_highlighting_enabled(self, enabled: bool) -> None:
        new_value = bool(enabled)
        if self.control_mismatch_highlighting_enabled == new_value:
            return
        self.control_mismatch_highlighting_enabled = new_value
        self._refresh_status()

    def _source_lines_for_control_mismatch(self) -> list[str]:
        source_lines = self.segment.source_lines or self.segment.original_lines or self.segment.lines or [
            ""
        ]
        resolved = list(source_lines) if source_lines else [""]
        if self._line1_inference_active():
            if len(resolved) > 1:
                return list(resolved[1:])
            return [""]
        return resolved

    def _translation_lines_for_control_mismatch(self) -> list[str]:
        translation_lines = (
            self.segment.translation_lines
            if self.segment.translation_lines
            else [""]
        )
        resolved = list(translation_lines) if translation_lines else [""]
        if self._line1_inference_active():
            if len(resolved) > 1:
                return list(resolved[1:])
            return [""]
        return resolved

    def _has_control_mismatch_problem(self) -> bool:
        if not self.control_mismatch_highlighting_enabled:
            return False
        if self.actor_mode:
            return False
        source_text = "\n".join(self._source_lines_for_control_mismatch())
        translation_text = "\n".join(
            self._translation_lines_for_control_mismatch())
        if not translation_text.strip():
            return False
        source_spans, translation_spans = control_mismatch_token_spans(
            source_text,
            translation_text,
        )
        return any(
            status != "matched"
            for _start, _end, status in source_spans
        ) or any(
            status != "matched"
            for _start, _end, status in translation_spans
        )

    def _control_mismatch_selections(self) -> list[QTextEdit.ExtraSelection]:
        if not self.translator_mode:
            return []
        if not self.control_mismatch_highlighting_enabled:
            return []
        if self._displaying_masked_text:
            return []
        translation_text = "\n".join(self._raw_lines or [""])
        if not translation_text.strip():
            return []
        source_text = "\n".join(self._source_lines_for_control_mismatch())
        return build_control_mismatch_selections(
            self.editor,
            source_text=source_text,
            translation_text=translation_text,
            highlight_side="translation",
            dark_theme=self._dark_theme,
        )

    def _sync_control_code_visibility(self, force: bool = False) -> None:
        show_raw = self._should_show_raw_codes()
        _set_hard_newline_markers(self.editor, self.editor.hasFocus())
        currently_showing_raw = not self._displaying_masked_text
        if not force and show_raw == currently_showing_raw:
            return

        if show_raw:
            self._displaying_masked_text = False
            self._masked_color_spans = []
            self._set_editor_text_lines(self._raw_lines)
        else:
            self._displaying_masked_text = True
            self._set_editor_text_lines(
                self._masked_lines_from_raw(self._raw_lines))
        self._refresh_source_hint_overlay()
        self._refresh_status()

    def _masked_color_selections(self) -> list[QTextEdit.ExtraSelection]:
        if not self._masked_color_spans:
            return []
        selections: list[QTextEdit.ExtraSelection] = []
        base_point_size = self.editor.font().pointSizeF()
        if base_point_size <= 0:
            fallback_point_size = self.editor.font().pointSize()
            base_point_size = float(fallback_point_size if fallback_point_size > 0 else 10)
        block = self.editor.document().firstBlock()
        line_idx = 0
        while block.isValid() and line_idx < len(self._masked_color_spans):
            spans = self._masked_color_spans[line_idx]
            for start, end, color_hex, font_scale in spans:
                if end <= start:
                    continue
                color = QColor(color_hex)
                if (not color.isValid()) and abs(font_scale - 1.0) <= 0.01:
                    continue
                cursor = QTextCursor(block)
                cursor.setPosition(block.position() + start)
                cursor.setPosition(block.position() + end,
                                   QTextCursor.MoveMode.KeepAnchor)
                selection = QTextEdit.ExtraSelection()
                fmt = QTextCharFormat()
                if color.isValid():
                    fmt.setForeground(color)
                if font_scale > 0:
                    fmt.setFontPointSize(max(1.0, base_point_size * font_scale))
                selection_any = cast(Any, selection)
                selection_any.format = fmt
                selection_any.cursor = cursor
                selections.append(selection)
            block = block.next()
            line_idx += 1
        return selections

    def _current_lines(self) -> list[str]:
        if self._displaying_masked_text:
            return list(self._raw_lines)
        return split_lines_preserve_empty(self.editor.toPlainText())

    def _speaker_display_name(self) -> str:
        if self.translator_mode:
            translated = self.segment.translation_speaker.strip()
            if translated:
                return translated
        explicit = self.segment.speaker_name
        if explicit != NO_SPEAKER_KEY:
            if self.speaker_display_resolver is not None:
                resolved = self.speaker_display_resolver(explicit)
                if resolved.strip():
                    return resolved
            return explicit
        if not self._line1_inference_active():
            return NO_SPEAKER_KEY
        if self.translator_mode:
            lines = self._segment_storage_lines()
        else:
            lines = self._segment_storage_lines()
        if not lines:
            return NO_SPEAKER_KEY
        first_line = lines[0].strip()
        if not first_line:
            return NO_SPEAKER_KEY

        display_name = first_line
        if self.speaker_display_resolver is not None:
            resolved = self.speaker_display_resolver(first_line).strip()
            if resolved:
                display_name = resolved

        if (
            self._line1_inference_is_forced()
            or looks_like_name_line(first_line)
            or (display_name != first_line and looks_like_name_line(display_name))
        ):
            return f"{display_name} (line 1)"
        return NO_SPEAKER_KEY

    def _speaker_display_name_html(self) -> str:
        if self.translator_mode:
            translated = self.segment.translation_speaker.strip()
            if translated:
                return html.escape(translated)

        explicit = self.segment.speaker_name
        if explicit != NO_SPEAKER_KEY:
            if self.speaker_display_html_resolver is not None:
                rendered = self.speaker_display_html_resolver(explicit).strip()
                if rendered:
                    return rendered
            if self.speaker_display_resolver is not None:
                resolved = self.speaker_display_resolver(explicit).strip()
                if resolved:
                    return html.escape(resolved)
            return html.escape(explicit)

        if not self._line1_inference_active():
            return html.escape(NO_SPEAKER_KEY)
        lines = self._segment_storage_lines()
        if not lines:
            return html.escape(NO_SPEAKER_KEY)
        first_line = lines[0].strip()
        if not first_line:
            return html.escape(NO_SPEAKER_KEY)

        display_name = first_line
        display_html = html.escape(first_line)
        if self.speaker_display_resolver is not None:
            resolved = self.speaker_display_resolver(first_line).strip()
            if resolved:
                display_name = resolved
                display_html = html.escape(resolved)
        if self.speaker_display_html_resolver is not None:
            rendered = self.speaker_display_html_resolver(first_line).strip()
            if rendered:
                display_html = rendered

        if (
            self._line1_inference_is_forced()
            or looks_like_name_line(first_line)
            or (display_name != first_line and looks_like_name_line(display_name))
        ):
            return f"{display_html} (line 1)"
        return html.escape(NO_SPEAKER_KEY)

    def _refresh_meta_label(self) -> None:
        if self.actor_mode:
            actor_id_text = str(
                self._actor_id) if self._actor_id is not None else "?"
            field_text = self._name_index_field
            if field_text == "name":
                mode_text = "EN name" if self.translator_mode else "JP name"
            else:
                mode_text = "EN text" if self.translator_mode else "JP text"
            meta_html = (
                f"{html.escape(self.name_index_label)} ID: {html.escape(actor_id_text)} | "
                f"Field: {html.escape(field_text)} | "
                f"View: {html.escape(mode_text)}"
            )
            self.meta_label.setTextFormat(Qt.TextFormat.RichText)
            self.meta_label.setText(meta_html)
            return

        if self._is_choice_block():
            lines = self._current_lines()
            option_count = len(lines) if lines else 0
            option_label = "option" if option_count == 1 else "options"
            view_text = "EN choices" if self.translator_mode else "JP choices"
            meta_html = (
                f"Type: Choice (code 102/402) | "
                f"{option_count} {option_label} | "
                f"View: {html.escape(view_text)}"
            )
            self.meta_label.setTextFormat(Qt.TextFormat.RichText)
            self.meta_label.setText(meta_html)
            return

        speaker_html = self._speaker_display_name_html()
        face_text = self.segment.face_name or "(none)"
        meta_html = (
            f"Speaker: {speaker_html} | "
            f"Face: {html.escape(face_text)} [{self.segment.face_index}] | "
            f"BG: {html.escape(str(self.segment.background))} | "
            f"Pos: {html.escape(str(self.segment.position))}"
        )
        self.meta_label.setTextFormat(Qt.TextFormat.RichText)
        self.meta_label.setText(meta_html)

    def _apply_overflow_highlighting(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        can_highlight_overflow = (
            (not self.actor_mode)
            and self._is_standard_dialogue_block()
            and (not self._displaying_masked_text)
        )
        if can_highlight_overflow:
            width_chars = self._width_chars()
            block = self.editor.document().firstBlock()
            while block.isValid():
                line_text = block.text()
                overflow_idx = first_overflow_char_index(line_text, width_chars)
                if overflow_idx is not None and overflow_idx < len(line_text):
                    cursor = QTextCursor(block)
                    start = block.position() + overflow_idx
                    end = block.position() + len(line_text)
                    cursor.setPosition(start)
                    cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
                    selection = QTextEdit.ExtraSelection()
                    fmt = QTextCharFormat()
                    fmt.setBackground(QColor(self._overflow_bg))
                    fmt.setForeground(QColor(self._overflow_fg))
                    selection_any = cast(Any, selection)
                    selection_any.format = fmt
                    selection_any.cursor = cursor
                    selections.append(selection)
                block = block.next()
        selections.extend(self._control_mismatch_selections())
        self.editor.setExtraSelections(selections)

    def _refresh_status(self) -> None:
        lines = self._current_lines()
        storage_lines = self._storage_lines_from_editor_lines(lines)
        max_rows_budget = float(max(1, self.max_lines))
        control_mismatch_problem = self._has_control_mismatch_problem()
        line1_override_changed = (
            bool(self.segment.disable_line1_speaker_inference)
            != bool(self.segment.original_disable_line1_speaker_inference)
            or bool(self.segment.force_line1_speaker_inference)
            != bool(self.segment.original_force_line1_speaker_inference)
        )
        if self.actor_mode:
            char_count = sum(len(line) for line in lines)
            line_label = "line" if len(lines) == 1 else "lines"
            char_label = "char" if char_count == 1 else "chars"
            self.status_label.setText(
                f"{len(lines)} {line_label}, {char_count} {char_label}")
            self._has_warning = False
            self.status_label.setStyleSheet(f"color: {self._status_ok_color};")
            self.move_overflow_button.setVisible(False)
            self.move_overflow_button.setEnabled(False)
            if self.translator_mode:
                speaker_changed = self.segment.translation_speaker.strip(
                ) != self.segment.original_translation_speaker.strip()
                original_tl = (
                    self.segment.original_translation_lines
                    if self.segment.original_translation_lines
                    else [""]
                )
                current_tl = storage_lines if storage_lines else [""]
                self.reset_button.setEnabled(
                    current_tl != original_tl
                    or speaker_changed
                    or line1_override_changed
                )
            else:
                self.reset_button.setEnabled(
                    storage_lines != self.segment.original_lines
                    or bool(self.segment.merged_segments)
                    or line1_override_changed
                )
            self._refresh_action_button_state(lines, self._width_chars())
            self._refresh_line1_inference_override_button()
            self._apply_overflow_highlighting()
            self._apply_editor_style(False)
            self._refresh_block_style()
            self._refresh_source_hint_overlay()
            return

        if not self._is_standard_dialogue_block():
            char_count = sum(len(line) for line in lines)
            line_count = len(lines)
            if self._is_choice_block():
                entry_label = "option" if line_count == 1 else "options"
            else:
                entry_label = "line" if line_count == 1 else "lines"
            char_label = "char" if char_count == 1 else "chars"
            text = f"{line_count} {entry_label}, {char_count} {char_label}"
            if control_mismatch_problem:
                text += ", control mismatch"
            self.status_label.setText(text)
            self._has_warning = control_mismatch_problem
            if control_mismatch_problem:
                self.status_label.setStyleSheet(
                    f"color: {self._status_warn_color}; font-weight: 600;"
                )
            else:
                self.status_label.setStyleSheet(f"color: {self._status_ok_color};")
            self.move_overflow_button.setVisible(False)
            self.move_overflow_button.setEnabled(False)
            if self.translator_mode:
                speaker_changed = self.segment.translation_speaker.strip(
                ) != self.segment.original_translation_speaker.strip()
                original_tl = (
                    self.segment.original_translation_lines
                    if self.segment.original_translation_lines
                    else [""]
                )
                current_tl = storage_lines if storage_lines else [""]
                self.reset_button.setEnabled(
                    current_tl != original_tl
                    or speaker_changed
                    or line1_override_changed
                )
            else:
                self.reset_button.setEnabled(
                    storage_lines != self.segment.original_lines
                    or bool(self.segment.merged_segments)
                    or line1_override_changed
                )
            self._refresh_action_button_state(lines, self._width_chars())
            self._refresh_line1_inference_override_button()
            self._apply_overflow_highlighting()
            self._apply_editor_style(control_mismatch_problem)
            self._refresh_block_style()
            self._refresh_source_hint_overlay()
            return

        width_chars = self._width_chars()
        width_mode = self._width_mode_name()

        over_width = []
        for idx, line in enumerate(lines, start=1):
            if visible_length(line) > width_chars:
                over_width.append(idx)

        line_label = "line" if len(lines) == 1 else "lines"
        text = f"{len(lines)} {line_label}, width hint: {width_chars} chars ({width_mode})"
        if over_width:
            over_width_label = "line" if len(over_width) == 1 else "lines"
            text += f", over width on {over_width_label}: {', '.join(str(i) for i in over_width[:6])}"
            if len(over_width) > 6:
                text += "..."
        kept_storage_lines, moved_storage_lines = split_lines_by_row_budget(
            storage_lines,
            max_rows_budget,
        )
        if self._line1_inference_active():
            kept_visible_count = max(0, len(kept_storage_lines) - 1)
        else:
            kept_visible_count = len(kept_storage_lines)
        overflow_count = max(0, len(lines) - kept_visible_count)
        max_lines_over = overflow_count > 0
        if max_lines_over:
            used_rows = total_display_rows(storage_lines)
            text += f", exceeds max lines ({int(max_rows_budget)}, row-aware {used_rows:.2f} rows)"
            if self._line1_inference_active() and moved_storage_lines:
                text += " incl. inferred speaker line budget"
            if self.allow_structural_actions:
                overflow_line_label = "line" if overflow_count == 1 else "lines"
                text += f" -> move {overflow_count} {overflow_line_label} below"
        if control_mismatch_problem:
            text += ", control mismatch"

        self.status_label.setText(text)
        has_warning = bool(over_width) or max_lines_over or control_mismatch_problem
        self._has_warning = has_warning
        if has_warning:
            self.status_label.setStyleSheet(
                f"color: {self._status_warn_color}; font-weight: 600;")
        else:
            self.status_label.setStyleSheet(f"color: {self._status_ok_color};")
        can_move_overflow = max_lines_over and self.allow_structural_actions
        self.move_overflow_button.setVisible(can_move_overflow)
        self.move_overflow_button.setEnabled(can_move_overflow)
        if can_move_overflow:
            label = "Move Overflow Down" if overflow_count == 1 else f"Move {overflow_count} Lines Down"
            self.move_overflow_button.setText(label)
        if self.translator_mode:
            speaker_changed = self.segment.translation_speaker.strip(
            ) != self.segment.original_translation_speaker.strip()
            original_tl = (
                self.segment.original_translation_lines
                if self.segment.original_translation_lines
                else [""]
            )
            current_tl = storage_lines if storage_lines else [""]
            self.reset_button.setEnabled(
                current_tl != original_tl
                or speaker_changed
                or line1_override_changed
            )
        else:
            self.reset_button.setEnabled(
                storage_lines != self.segment.original_lines
                or bool(self.segment.merged_segments)
                or line1_override_changed
            )
        self._refresh_action_button_state(lines, width_chars)
        self._refresh_line1_inference_override_button()
        self._apply_overflow_highlighting()
        self._apply_editor_style(has_warning)
        self._refresh_block_style()
        self._refresh_source_hint_overlay()

    def _refresh_action_button_state(self, lines: list[str], width_chars: int) -> None:
        if self.actor_mode:
            self.collapse_button.setEnabled(False)
            self.smart_collapse_button.setEnabled(False)
            self.wrap_button.setEnabled(False)
            self.insert_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        if not self._is_standard_dialogue_block():
            self.collapse_button.setEnabled(False)
            self.smart_collapse_button.setEnabled(False)
            self.wrap_button.setEnabled(False)
            self.insert_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        can_collapse = collapse_lines_join_paragraphs(lines, width_chars) != lines
        infer_name_in_editor_lines = (
            self.infer_name_from_first_line and (not self._line1_inference_active())
        )
        can_smart_collapse = smart_collapse_lines(
            lines,
            width_chars,
            infer_name_from_first_line=infer_name_in_editor_lines,
        ) != lines
        can_wrap = wrap_lines_hard_break(lines, width_chars) != lines
        can_insert = self.allow_structural_actions
        can_delete = (
            self.allow_structural_actions
            and (
                (not self.translator_mode)
                or self.segment.inserted
                or self.segment.translation_only
            )
        )

        self.collapse_button.setEnabled(can_collapse)
        self.smart_collapse_button.setEnabled(can_smart_collapse)
        self.wrap_button.setEnabled(can_wrap)
        self.insert_button.setEnabled(can_insert)
        self.delete_button.setEnabled(can_delete)
        self.collapse_button.setStyleSheet("")
        self.smart_collapse_button.setStyleSheet("")
        self.wrap_button.setStyleSheet("")

    def _set_editor_lines(self, lines: list[str]) -> None:
        final_lines = lines or [""]
        self._raw_lines = list(final_lines)
        display_lines = self._raw_lines if self._should_show_raw_codes(
        ) else self._masked_lines_from_raw(self._raw_lines)
        self._set_editor_text_lines(display_lines)
        storage_lines = self._storage_lines_from_editor_lines(self._raw_lines)
        if self.translator_mode:
            self.segment.translation_lines = list(storage_lines)
        else:
            self.segment.lines = list(storage_lines)
            self.segment.source_lines = list(storage_lines)
        self._refresh_meta_label()
        self._refresh_status()
        self.text_changed.emit(self.segment.uid, list(storage_lines))

    def _on_collapse_clicked(self) -> None:
        collapsed = collapse_lines_join_paragraphs(
            self._current_lines(), self._width_chars())
        self._set_editor_lines(collapsed)

    def _on_smart_collapse_clicked(self) -> None:
        infer_name_in_editor_lines = (
            self.infer_name_from_first_line and (not self._line1_inference_active())
        )
        collapsed = smart_collapse_lines(
            self._current_lines(),
            self._width_chars(),
            infer_name_from_first_line=infer_name_in_editor_lines,
        )
        self._set_editor_lines(collapsed)

    def _on_wrap_clicked(self) -> None:
        wrapped = wrap_lines_hard_break(
            self._current_lines(), self._width_chars())
        self._set_editor_lines(wrapped)

    def _on_reset_clicked(self) -> None:
        self.reset_requested.emit(self.segment.uid)

    def _on_move_overflow_clicked(self) -> None:
        self.split_overflow_requested.emit(self.segment.uid)

    def _on_text_changed(self) -> None:
        if self._suppress_text_changed:
            return
        if self._displaying_masked_text:
            return
        lines = self._current_lines()
        self._raw_lines = list(lines)
        storage_lines = self._storage_lines_from_editor_lines(lines)
        if self.translator_mode:
            self.segment.translation_lines = list(storage_lines)
        else:
            self.segment.lines = list(storage_lines)
            self.segment.source_lines = list(storage_lines)
        self._refresh_meta_label()
        self._refresh_status()
        self.text_changed.emit(self.segment.uid, list(storage_lines))
