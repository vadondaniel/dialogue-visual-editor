from __future__ import annotations

from collections import Counter
import html
import math
import re
from typing import Any, Callable, Literal, Optional, Protocol, cast

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QMouseEvent,
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
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
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
    parse_units_for_measure,
    split_lines_by_row_budget,
    smart_collapse_lines,
    split_lines_preserve_empty,
    strip_control_tokens,
    total_display_rows,
    visible_length,
    wrap_lines_hard_break,
)

NAME_INDEX_UID_RE = re.compile(r":[A-Za-z]:(\d+)(?::([A-Za-z0-9_]+))?$")
VARIABLE_TOKEN_RE = re.compile(r"\\[Vv]\[(\d+)(?:,[^\]]*)?\]")
ICON_TOKEN_RE = re.compile(r"\\[Ii]\[(\d+)\]")
PARTY_TOKEN_RE = re.compile(r"\\[Pp]\[(\d+)\]")
CURRENCY_TOKEN_RE = re.compile(r"\\[Gg](?![A-Za-z0-9_])")
VARIABLE_PLACEHOLDER_TOKEN_RE = re.compile(
    r"<(?:VAR:|V)(\d+)>", re.IGNORECASE)
ICON_PLACEHOLDER_TOKEN_RE = re.compile(r"<(?:ICON:|I)(\d+)>", re.IGNORECASE)
PARTY_PLACEHOLDER_TOKEN_RE = re.compile(
    r"<(?:PARTY:|P)(\d+)>", re.IGNORECASE)
CURRENCY_PLACEHOLDER_TOKEN_RE = re.compile(
    r"<(?:CUR:|G)>", re.IGNORECASE)
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
_JAPANESE_CHAR_RE = re.compile(
    r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF"
    r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]"
)
_JAPANESE_PROBLEM_BG_DARK = "#7c2d12"
_JAPANESE_PROBLEM_BG_LIGHT = "#ffedd5"
_JAPANESE_PROBLEM_FG_DARK = "#fdba74"
_JAPANESE_PROBLEM_FG_LIGHT = "#9a3412"
_JAPANESE_PROBLEM_UNDERLINE_DARK = "#fb923c"
_JAPANESE_PROBLEM_UNDERLINE_LIGHT = "#c2410c"


def _extract_control_token_matches(text: str) -> list[tuple[str, int, int]]:
    if not text:
        return []
    return [
        (match.group(0), match.start(), match.end())
        for match in CONTROL_TOKEN_RE.finditer(text)
    ]


def _html_escape_line_preserve_indent(line: str) -> str:
    if not line:
        return "&nbsp;"
    idx = 0
    indent_parts: list[str] = []
    while idx < len(line):
        ch = line[idx]
        if ch == " ":
            indent_parts.append("&nbsp;")
            idx += 1
            continue
        if ch == "\t":
            indent_parts.append("&nbsp;&nbsp;&nbsp;&nbsp;")
            idx += 1
            continue
        break
    return "".join(indent_parts) + html.escape(line[idx:])


def control_mismatch_token_spans(
    source_text: str,
    translation_text: str,
) -> tuple[list[ControlMismatchSpan], list[ControlMismatchSpan]]:
    source_matches = _extract_control_token_matches(source_text or "")
    translation_matches = _extract_control_token_matches(translation_text or "")
    source_spans: list[ControlMismatchSpan] = []
    translation_spans: list[ControlMismatchSpan] = []
    source_counts = Counter(token for token, _start, _end in source_matches)
    translation_counts = Counter(
        token for token, _start, _end in translation_matches)
    shared_counts = source_counts & translation_counts

    source_seen: Counter[str] = Counter()
    for token, start, end in source_matches:
        status: ControlMismatchStatus = (
            "matched" if source_seen[token] < shared_counts[token] else "missing"
        )
        source_seen[token] += 1
        source_spans.append((start, end, status))

    translation_seen: Counter[str] = Counter()
    for token, start, end in translation_matches:
        status = "matched" if translation_seen[token] < shared_counts[token] else "extra"
        translation_seen[token] += 1
        translation_spans.append((start, end, status))

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


def japanese_character_spans(text: str) -> list[tuple[int, int]]:
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for control_match in CONTROL_TOKEN_RE.finditer(text):
        if control_match.start() > cursor:
            chunk = text[cursor:control_match.start()]
            for match in _JAPANESE_CHAR_RE.finditer(chunk):
                spans.append((cursor + match.start(), cursor + match.end()))
        cursor = control_match.end()
    if cursor < len(text):
        chunk = text[cursor:]
        for match in _JAPANESE_CHAR_RE.finditer(chunk):
            spans.append((cursor + match.start(), cursor + match.end()))
    return spans


def build_japanese_character_problem_selections(
    editor: QPlainTextEdit,
    text: str,
    *,
    dark_theme: bool,
) -> list[QTextEdit.ExtraSelection]:
    spans = japanese_character_spans(text)
    if not spans:
        return []

    bg = QColor(_JAPANESE_PROBLEM_BG_DARK if dark_theme else _JAPANESE_PROBLEM_BG_LIGHT)
    if not bg.isValid():
        return []
    bg.setAlpha(172 if dark_theme else 160)
    fg = QColor(_JAPANESE_PROBLEM_FG_DARK if dark_theme else _JAPANESE_PROBLEM_FG_LIGHT)
    underline = QColor(
        _JAPANESE_PROBLEM_UNDERLINE_DARK if dark_theme else _JAPANESE_PROBLEM_UNDERLINE_LIGHT
    )

    doc_len = len(editor.toPlainText())
    selections: list[QTextEdit.ExtraSelection] = []
    for start, end in spans:
        if end <= start or start >= doc_len:
            continue
        cursor = QTextCursor(editor.document())
        cursor.setPosition(max(0, start))
        cursor.setPosition(min(end, doc_len), QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        fmt.setBackground(bg)
        if fg.isValid():
            fmt.setForeground(fg)
        if underline.isValid():
            fmt.setUnderlineColor(underline)
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        selection_any = cast(Any, selection)
        selection_any.format = fmt
        selection_any.cursor = cursor
        selections.append(selection)
    return selections


class SpeakerManagerHost(Protocol):
    speaker_custom_colors: dict[str, str]
    speaker_translation_map: dict[str, str]

    def _collect_speaker_keys(self) -> list[str]: ...
    def _speaker_color_for_key(self, speaker_key: str) -> str: ...
    def _speaker_translation_for_key(self, speaker_key: str) -> str: ...
    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str: ...
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


def _preview_dialog_text(value: str, limit: int = 76) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 3:
        return cleaned[:limit]
    return cleaned[: limit - 3] + "..."


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


def _cursor_line_col(cursor: QTextCursor) -> tuple[int, int]:
    block = cursor.block()
    if not block.isValid():
        return 0, 0
    line_index = max(0, int(block.blockNumber()))
    col = max(0, cursor.position() - block.position())
    return line_index, col


def _raw_col_for_masked_col(raw_line: str, masked_col: int) -> int:
    target = max(0, int(masked_col))
    masked_seen = 0
    cursor = 0
    for match in CONTROL_TOKEN_RE.finditer(raw_line):
        start, end = match.span()
        plain_len = max(0, start - cursor)
        if masked_seen + plain_len >= target:
            return cursor + (target - masked_seen)
        masked_seen += plain_len
        cursor = end
    tail_len = max(0, len(raw_line) - cursor)
    if masked_seen + tail_len >= target:
        return cursor + (target - masked_seen)
    return len(raw_line)


def _doc_pos_from_line_col(lines: list[str], line_index: int, col: int) -> int:
    if not lines:
        return 0
    safe_line = max(0, min(len(lines) - 1, int(line_index)))
    pos = 0
    for idx in range(safe_line):
        pos += len(lines[idx]) + 1
    line_len = len(lines[safe_line])
    safe_col = max(0, min(line_len, int(col)))
    return pos + safe_col


def _token_id_at_editor_position(
    editor: QPlainTextEdit,
    pos: QPoint,
    token_pattern: re.Pattern[str],
) -> Optional[int]:
    cursor = editor.cursorForPosition(pos)
    block = cursor.block()
    if not block.isValid():
        return None
    line_text = block.text()
    in_block_pos = cursor.position() - block.position()
    for match in token_pattern.finditer(line_text):
        if match.start() <= in_block_pos <= match.end():
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def _token_id_at_editor_position_for_patterns(
    editor: QPlainTextEdit,
    pos: QPoint,
    token_patterns: tuple[re.Pattern[str], ...],
) -> Optional[int]:
    for token_pattern in token_patterns:
        token_id = _token_id_at_editor_position(editor, pos, token_pattern)
        if token_id is not None:
            return token_id
    return None


def _token_present_at_editor_position(
    editor: QPlainTextEdit,
    pos: QPoint,
    token_pattern: re.Pattern[str],
) -> bool:
    cursor = editor.cursorForPosition(pos)
    block = cursor.block()
    if not block.isValid():
        return False
    line_text = block.text()
    in_block_pos = cursor.position() - block.position()
    for match in token_pattern.finditer(line_text):
        if match.start() <= in_block_pos <= match.end():
            return True
    return False


def _variable_token_id_at_editor_position(
    editor: QPlainTextEdit,
    pos: QPoint,
) -> Optional[int]:
    return _token_id_at_editor_position_for_patterns(
        editor,
        pos,
        (VARIABLE_TOKEN_RE, VARIABLE_PLACEHOLDER_TOKEN_RE),
    )


def _icon_token_id_at_editor_position(
    editor: QPlainTextEdit,
    pos: QPoint,
) -> Optional[int]:
    return _token_id_at_editor_position_for_patterns(
        editor,
        pos,
        (ICON_TOKEN_RE, ICON_PLACEHOLDER_TOKEN_RE),
    )


def _party_token_id_at_editor_position(
    editor: QPlainTextEdit,
    pos: QPoint,
) -> Optional[int]:
    return _token_id_at_editor_position_for_patterns(
        editor,
        pos,
        (PARTY_TOKEN_RE, PARTY_PLACEHOLDER_TOKEN_RE),
    )


def _currency_token_at_editor_position(
    editor: QPlainTextEdit,
    pos: QPoint,
) -> bool:
    return _token_present_at_editor_position(
        editor,
        pos,
        CURRENCY_TOKEN_RE,
    ) or _token_present_at_editor_position(
        editor,
        pos,
        CURRENCY_PLACEHOLDER_TOKEN_RE,
    )


class ControlCodeHighlighter(QSyntaxHighlighter):
    _COLOR_CODE_RE = re.compile(r"\\[Cc]\[(\d+)\]")

    def __init__(
        self,
        parent: Any,
        dark_theme: bool,
        color_code_resolver: Optional[Callable[[int], str]] = None,
        resolve_color_flow: bool = False,
    ):
        super().__init__(parent)
        self._color_code_resolver = color_code_resolver
        self._resolve_color_flow = bool(resolve_color_flow)
        self._initial_active_color_code = 0
        self._dark_theme = bool(dark_theme)
        self._rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []
        self._rebuild_rules()

    def _rebuild_rules(self) -> None:
        if self._dark_theme:
            command_color = "#fbbf24"
            symbol_color = "#93c5fd"
        else:
            command_color = "#9a3412"
            symbol_color = "#1d4ed8"

        command_format = QTextCharFormat()
        command_format.setForeground(QColor(command_color))
        command_format.setFontWeight(QFont.Weight.DemiBold)

        symbol_format = QTextCharFormat()
        symbol_format.setForeground(QColor(symbol_color))
        symbol_format.setFontWeight(QFont.Weight.DemiBold)

        self._rules = [
            (re.compile(r"\\[A-Za-z]+\[[^\]\r\n]*\]"), command_format),
            (re.compile(r"\\[A-Za-z]+"), command_format),
            (re.compile(r"\\[\\{}.$|!><^]"), symbol_format),
        ]

    def set_dark_theme(self, dark_theme: bool) -> None:
        next_theme = bool(dark_theme)
        if self._dark_theme == next_theme:
            return
        self._dark_theme = next_theme
        self._rebuild_rules()
        self.rehighlight()

    def set_initial_active_color_code(self, color_code: int) -> None:
        try:
            parsed = int(color_code)
        except Exception:
            parsed = 0
        self._initial_active_color_code = max(0, parsed)

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
        color_resolver = self._color_code_resolver
        if color_resolver is None:
            self.setCurrentBlockState(-1)
            return
        if not self._resolve_color_flow:
            for match in self._COLOR_CODE_RE.finditer(text):
                try:
                    color_code = int(match.group(1))
                except Exception:
                    continue
                color_hex = color_resolver(color_code)
                color = QColor(color_hex)
                if not color.isValid():
                    continue
                color_fmt = QTextCharFormat()
                color_fmt.setForeground(color)
                color_fmt.setFontWeight(QFont.Weight.DemiBold)
                self.setFormat(match.start(), match.end() - match.start(), color_fmt)
            self.setCurrentBlockState(-1)
            return

        def apply_active_color(start: int, length: int, color_code: int, *, bold: bool) -> None:
            if length <= 0 or color_code <= 0:
                return
            color_hex = color_resolver(color_code)
            color = QColor(color_hex)
            if not color.isValid():
                return
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            if bold:
                fmt.setFontWeight(QFont.Weight.DemiBold)
            self.setFormat(start, length, fmt)

        prev_state = self.previousBlockState()
        if prev_state >= 0:
            active_color = prev_state
        else:
            block_number = self.currentBlock().blockNumber()
            active_color = self._initial_active_color_code if block_number == 0 else 0

        cursor = 0
        for match in self._COLOR_CODE_RE.finditer(text):
            start = match.start()
            end = match.end()
            if start > cursor and active_color > 0:
                apply_active_color(cursor, start - cursor, active_color, bold=False)
            try:
                next_color = int(match.group(1))
            except Exception:
                next_color = 0
            if next_color > 0:
                apply_active_color(start, end - start, next_color, bold=True)
            active_color = max(0, next_color)
            cursor = end
        if cursor < len(text) and active_color > 0:
            apply_active_color(cursor, len(text) - cursor, active_color, bold=False)
        self.setCurrentBlockState(active_color)


class SpeakerManagerDialog(QDialog):
    def __init__(
        self,
        editor: QWidget,
        *,
        source_language_code: str = "JP",
        target_language_code: str = "EN",
    ):
        super().__init__(editor)
        self.editor: SpeakerManagerHost = cast(SpeakerManagerHost, editor)
        self.source_language_code = source_language_code.strip() or "JP"
        self.target_language_code = target_language_code.strip() or "EN"
        self.setWindowTitle("Speaker Manager")
        self.resize(460, 420)

        root = QVBoxLayout(self)
        info = QLabel(
            f"Manage {self.source_language_code} speakers globally: rename, set "
            f"{self.target_language_code} translation, pick custom colors, or revert to auto colors.\n"
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
        self.translate_btn = QPushButton(f"Set {self.target_language_code}...")
        self.clear_translate_btn = QPushButton(f"Clear {self.target_language_code}")
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
            label = speaker_key
            speaker_en = self._raw_translation_for_key(speaker_key)
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
            selected_key and self._raw_translation_for_key(selected_key))
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
        existing = self._raw_translation_for_key(speaker_key)
        if existing.strip():
            return existing
        if speaker_key == NO_SPEAKER_KEY:
            return ""
        return speaker_key

    def _raw_translation_for_key(self, speaker_key: str) -> str:
        normalized = self.editor._normalize_speaker_key(speaker_key)
        if normalized == NO_SPEAKER_KEY:
            return ""

        direct = self.editor.speaker_translation_map.get(normalized, "")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()

        # Backward compatibility for older state that stored resolved token keys.
        resolved_key = self.editor._normalize_speaker_key(
            self.editor._resolve_name_tokens_in_text(
                normalized,
                prefer_translated=False,
            )
        )
        if resolved_key != normalized:
            legacy = self.editor.speaker_translation_map.get(resolved_key, "")
            if isinstance(legacy, str) and legacy.strip():
                return legacy.strip()
        return ""

    def _on_rename_clicked(self) -> None:
        current = self._selected_speaker_key()
        if current is None:
            return
        default_text = self._rename_prefill_text(current)
        new_name, ok = QInputDialog.getText(
            self,
            f"Rename Speaker {self.source_language_code}",
            f"Rename {self.source_language_code} speaker '{current}' to:",
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
            f"Set Speaker {self.target_language_code}",
            f"Set {self.target_language_code} translation for '{current}':",
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


class ExactMatchReviewDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        current_block_label: str,
        current_snapshot: dict[str, str],
        match_rows: list[dict[str, Any]],
        color_code_resolver: Optional[Callable[[int], str]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Exact Match Review")
        self.resize(920, 680)
        self.match_rows = list(match_rows)
        self.selected_match_row: Optional[dict[str, Any]] = None
        self.selected_action: str = ""

        root = QVBoxLayout(self)
        info = QLabel(
            "Inspect exact JP matches with neighboring blocks before reusing translations."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        self.current_block_label = QLabel(current_block_label)
        self.current_block_label.setObjectName("MetaDim")
        root.addWidget(self.current_block_label)

        self.current_preview = QPlainTextEdit()
        self.current_preview.setReadOnly(True)
        self.current_preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        preview_font = QFont("Consolas")
        if not preview_font.exactMatch():
            preview_font = QFont("Courier New")
        preview_font.setStyleHint(QFont.StyleHint.Monospace)
        preview_font.setPointSize(10)
        self.current_preview.setFont(preview_font)
        self.current_preview_highlighter = ControlCodeHighlighter(
            self.current_preview.document(),
            is_dark_palette(),
            color_code_resolver=color_code_resolver,
        )
        root.addWidget(self.current_preview, 1)

        self.match_tree = QTreeWidget()
        self.match_tree.setRootIsDecorated(True)
        self.match_tree.setUniformRowHeights(True)
        self.match_tree.setAlternatingRowColors(True)
        self.match_tree.setColumnCount(5)
        self.match_tree.setHeaderLabels(
            ["EN Variant", "Count", "File", "Block", "Neighbors"]
        )
        self.match_tree.currentItemChanged.connect(
            lambda _current, _previous: self._on_selected_match_changed()
        )
        self.match_tree.setSortingEnabled(False)
        self.match_tree.header().setStretchLastSection(False)
        self.match_tree.setColumnWidth(0, 420)
        self.match_tree.setColumnWidth(1, 70)
        self.match_tree.setColumnWidth(2, 210)
        self.match_tree.setColumnWidth(3, 70)
        self.match_tree.setColumnWidth(4, 100)
        root.addWidget(self.match_tree, 1)

        self.match_preview = QPlainTextEdit()
        self.match_preview.setReadOnly(True)
        self.match_preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.match_preview.setFont(preview_font)
        self.match_preview_highlighter = ControlCodeHighlighter(
            self.match_preview.document(),
            is_dark_palette(),
            color_code_resolver=color_code_resolver,
        )
        root.addWidget(self.match_preview, 1)

        actions = QHBoxLayout()
        self.selected_to_current_btn = QPushButton("Use Selected -> Current")
        self.selected_to_all_btn = QPushButton("Use Selected -> All Listed")
        self.current_to_selected_btn = QPushButton("Use Current -> Selected")
        self.current_to_all_btn = QPushButton("Use Current -> All Listed")
        close_btn = QPushButton("Close")

        self.selected_to_current_btn.clicked.connect(self._accept_selected_to_current)
        self.selected_to_all_btn.clicked.connect(self._accept_selected_to_all)
        self.current_to_selected_btn.clicked.connect(self._accept_current_to_selected)
        self.current_to_all_btn.clicked.connect(self._accept_current_to_all)
        close_btn.clicked.connect(self.reject)

        actions.addWidget(self.selected_to_current_btn)
        actions.addWidget(self.selected_to_all_btn)
        actions.addWidget(self.current_to_selected_btn)
        actions.addWidget(self.current_to_all_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        root.addLayout(actions)

        self.current_preview.setPlainText(
            self._build_snapshot_text("Current block", current_snapshot)
        )
        self._populate_list()
        self._sync_action_buttons()

    def _build_snapshot_text(self, title: str, snapshot: dict[str, str]) -> str:
        prev_source = snapshot.get("prev_source", "").strip()
        curr_source = snapshot.get("current_source", "").strip()
        next_source = snapshot.get("next_source", "").strip()
        prev_tl = snapshot.get("prev_tl", "").strip()
        curr_tl = snapshot.get("current_tl", "").strip()
        next_tl = snapshot.get("next_tl", "").strip()
        lines = [
            title,
            "",
            f"Prev JP: {prev_source or '-'}",
            f"Curr JP: {curr_source or '-'}",
            f"Next JP: {next_source or '-'}",
            "",
            f"Prev EN: {prev_tl or '-'}",
            f"Curr EN: {curr_tl or '-'}",
            f"Next EN: {next_tl or '-'}",
        ]
        return "\n".join(lines)

    def _populate_list(self) -> None:
        self.match_tree.clear()
        grouped_rows: dict[str, list[dict[str, Any]]] = {}
        for row in self.match_rows:
            variant = str(row.get("current_tl", "")).strip() or "(empty)"
            grouped_rows.setdefault(variant, []).append(row)

        sorted_groups = sorted(
            grouped_rows.items(),
            key=lambda entry: (-len(entry[1]), entry[0]),
        )

        first_child_to_select: Optional[QTreeWidgetItem] = None
        for variant, rows in sorted_groups:
            group_item = QTreeWidgetItem(
                [
                    _preview_dialog_text(variant),
                    str(len(rows)),
                    "",
                    "",
                    "",
                ]
            )
            group_item.setData(0, Qt.ItemDataRole.UserRole, None)
            self.match_tree.addTopLevelItem(group_item)
            for row in sorted(
                rows,
                key=lambda value: (
                    str(value.get("file", "")),
                    int(value.get("block_number", 0)),
                ),
            ):
                file_name = str(row.get("file", ""))
                block_number = int(row.get("block_number", 0))
                same_neighbors = bool(row.get("same_neighbors", False))
                child = QTreeWidgetItem(
                    [
                        _preview_dialog_text(str(row.get("current_tl", "")).strip() or "(empty)"),
                        "",
                        file_name,
                        str(block_number),
                        "same" if same_neighbors else "diff",
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, row)
                group_item.addChild(child)
                if first_child_to_select is None:
                    first_child_to_select = child
            group_item.setExpanded(True)

        if first_child_to_select is not None:
            self.match_tree.setCurrentItem(first_child_to_select)
        else:
            self.match_preview.setPlainText("No exact matches available.")

    def _selected_row(self) -> Optional[dict[str, Any]]:
        item = self.match_tree.currentItem()
        if item is None:
            return None
        row = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(row, dict):
            return row
        return None

    def _on_selected_match_changed(self) -> None:
        row = self._selected_row()
        if row is None:
            self.match_preview.setPlainText(
                "Select a specific match row to inspect neighbors."
            )
        else:
            file_name = str(row.get("file", ""))
            block_number = int(row.get("block_number", 0))
            title = f"Match block {file_name}#{block_number}"
            self.match_preview.setPlainText(self._build_snapshot_text(title, row))
        self._sync_action_buttons()

    def _sync_action_buttons(self) -> None:
        has_selection = self._selected_row() is not None
        has_rows = len(self.match_rows) > 0
        self.selected_to_current_btn.setEnabled(has_selection)
        self.selected_to_all_btn.setEnabled(has_selection and has_rows)
        self.current_to_selected_btn.setEnabled(has_selection)
        self.current_to_all_btn.setEnabled(has_rows)

    def _accept_selected_to_current(self) -> None:
        selected = self._selected_row()
        if selected is None:
            return
        self.selected_match_row = selected
        self.selected_action = "selected_to_current"
        self.accept()

    def _accept_current_to_selected(self) -> None:
        selected = self._selected_row()
        if selected is None:
            return
        self.selected_match_row = selected
        self.selected_action = "current_to_selected"
        self.accept()

    def _accept_selected_to_all(self) -> None:
        selected = self._selected_row()
        if selected is None:
            return
        self.selected_match_row = selected
        self.selected_action = "selected_to_all"
        self.accept()

    def _accept_current_to_all(self) -> None:
        self.selected_match_row = None
        self.selected_action = "current_to_all"
        self.accept()


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
        self._pending_mouse_reveal_name = False
        self._pending_mouse_reveal_desc = False
        self._masked_name_color_spans: list[list[tuple[int, int, str, float]]] = []
        self._masked_desc_color_spans: list[list[tuple[int, int, str, float]]] = []
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
        self.context_label.setVisible(False)
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

    def _masked_lines_and_spans_from_raw(
        self,
        lines: list[str],
    ) -> tuple[list[str], list[list[tuple[int, int, str, float]]]]:
        source_lines = lines or [""]
        if self.hidden_control_colored_line_resolver is not None:
            joined = "\n".join(source_lines)
            masked_text, spans = self.hidden_control_colored_line_resolver(
                joined)
            split_lines, spans_per_line = _split_masked_text_and_spans(
                masked_text,
                list(spans),
            )
            normalized_lines = split_lines if split_lines else [""]
            normalized_spans = spans_per_line
            if len(normalized_spans) < len(normalized_lines):
                normalized_spans.extend(
                    [[] for _ in range(len(normalized_lines) - len(normalized_spans))]
                )
            elif len(normalized_spans) > len(normalized_lines):
                normalized_spans = normalized_spans[: len(normalized_lines)]
            return normalized_lines, normalized_spans
        masked: list[str] = []
        for line in source_lines:
            if self.hidden_control_line_transform is not None:
                masked.append(self.hidden_control_line_transform(line))
            else:
                masked.append(strip_control_tokens(line))
        normalized = masked or [""]
        return normalized, [[] for _ in normalized]

    def _masked_lines_from_raw(self, lines: list[str]) -> list[str]:
        masked_lines, _spans = self._masked_lines_and_spans_from_raw(lines)
        return masked_lines

    def _masked_color_selections_for_editor(
        self,
        editor: QPlainTextEdit,
        spans_per_line: list[list[tuple[int, int, str, float]]],
    ) -> list[QTextEdit.ExtraSelection]:
        if not spans_per_line:
            return []
        selections: list[QTextEdit.ExtraSelection] = []
        base_point_size = editor.font().pointSizeF()
        if base_point_size <= 0:
            fallback_point_size = editor.font().pointSize()
            base_point_size = float(
                fallback_point_size if fallback_point_size > 0 else 10
            )
        block = editor.document().firstBlock()
        line_idx = 0
        while block.isValid() and line_idx < len(spans_per_line):
            spans = spans_per_line[line_idx]
            for start, end, color_hex, font_scale in spans:
                if end <= start:
                    continue
                color = QColor(color_hex)
                if not color.isValid():
                    continue
                cursor = QTextCursor(block)
                block_start = block.position()
                cursor.setPosition(block_start + max(0, start))
                cursor.setPosition(
                    block_start + max(0, end),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                selection = QTextEdit.ExtraSelection()
                fmt = QTextCharFormat()
                fmt.setForeground(color)
                try:
                    scale = float(font_scale)
                except Exception:
                    scale = 1.0
                if abs(scale - 1.0) > 0.001:
                    fmt.setFontPointSize(base_point_size * scale)
                selection_any = cast(Any, selection)
                selection_any.format = fmt
                selection_any.cursor = cursor
                selections.append(selection)
            block = block.next()
            line_idx += 1
        return selections

    def _apply_masked_color_selections(
        self,
        editor: QPlainTextEdit,
        spans_per_line: list[list[tuple[int, int, str, float]]],
    ) -> None:
        editor.setExtraSelections(
            self._masked_color_selections_for_editor(editor, spans_per_line)
        )

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

    def _pending_mouse_reveal_for_editor(self, editor: QPlainTextEdit) -> bool:
        if editor is self.name_editor:
            return bool(self._pending_mouse_reveal_name)
        return bool(self._pending_mouse_reveal_desc)

    def _set_pending_mouse_reveal_for_editor(self, editor: QPlainTextEdit, pending: bool) -> None:
        if editor is self.name_editor:
            self._pending_mouse_reveal_name = bool(pending)
            return
        self._pending_mouse_reveal_desc = bool(pending)

    def _editor_shows_raw_codes(self, editor: QPlainTextEdit) -> bool:
        if editor is self.name_editor:
            return bool(self._showing_raw_name)
        return bool(self._showing_raw_desc)

    def _raw_lines_for_editor(self, editor: QPlainTextEdit) -> list[str]:
        if editor is self.name_editor:
            return list(self._raw_name_lines if self._raw_name_lines else [""])
        return list(self._raw_desc_lines if self._raw_desc_lines else [""])

    def _reveal_raw_editor_now(self, editor: QPlainTextEdit) -> None:
        if editor is self.name_editor:
            self._showing_raw_name = True
            _set_hard_newline_markers(editor, True)
            self._set_editor_lines(editor, self._raw_name_lines, suppress_name=True)
            return
        self._showing_raw_desc = True
        _set_hard_newline_markers(editor, True)
        self._set_editor_lines(editor, self._raw_desc_lines, suppress_name=False)

    def _should_defer_mouse_focus_reveal(self, editor: QPlainTextEdit, event: QEvent) -> bool:
        if not self.hide_control_codes_when_unfocused:
            return False
        if self._editor_shows_raw_codes(editor):
            return False
        if event.type() != QEvent.Type.FocusIn:
            return False
        try:
            focus_event = cast(QFocusEvent, event)
            return focus_event.reason() == Qt.FocusReason.MouseFocusReason
        except Exception:
            return False

    def _apply_deferred_mouse_reveal_for_editor(self, editor: QPlainTextEdit) -> None:
        if not self._pending_mouse_reveal_for_editor(editor):
            return
        cursor = editor.textCursor()
        line_index, masked_col = _cursor_line_col(cursor)
        self._set_pending_mouse_reveal_for_editor(editor, False)
        self._reveal_raw_editor_now(editor)
        if not self._editor_shows_raw_codes(editor):
            return
        raw_lines = self._raw_lines_for_editor(editor)
        if not raw_lines:
            return
        safe_line = max(0, min(len(raw_lines) - 1, line_index))
        raw_col = _raw_col_for_masked_col(raw_lines[safe_line], masked_col)
        target_pos = _doc_pos_from_line_col(raw_lines, safe_line, raw_col)
        remapped = editor.textCursor()
        remapped.setPosition(target_pos)
        editor.setTextCursor(remapped)
        self._refresh_status()

    def _sync_single_editor_visibility(self, editor: QPlainTextEdit, force: bool = False) -> None:
        if editor is self.name_editor:
            show_raw = (
                not self.hide_control_codes_when_unfocused) or self.name_editor.hasFocus()
            if self._pending_mouse_reveal_name:
                show_raw = False
            _set_hard_newline_markers(self.name_editor, self.name_editor.hasFocus())
            if (not force) and show_raw == self._showing_raw_name:
                return
            self._showing_raw_name = show_raw
            if show_raw:
                lines = list(self._raw_name_lines)
                self._masked_name_color_spans = []
                self._set_editor_lines(self.name_editor, lines, suppress_name=True)
                self._apply_masked_color_selections(self.name_editor, [])
                return
            lines, spans = self._masked_lines_and_spans_from_raw(self._raw_name_lines)
            self._masked_name_color_spans = spans
            self._set_editor_lines(self.name_editor, lines, suppress_name=True)
            self._apply_masked_color_selections(self.name_editor, spans)
            return

        show_raw = (
            not self.hide_control_codes_when_unfocused) or self.desc_editor.hasFocus()
        if self._pending_mouse_reveal_desc:
            show_raw = False
        _set_hard_newline_markers(self.desc_editor, self.desc_editor.hasFocus())
        if (not force) and show_raw == self._showing_raw_desc:
            return
        self._showing_raw_desc = show_raw
        if show_raw:
            lines = list(self._raw_desc_lines)
            self._masked_desc_color_spans = []
            self._set_editor_lines(self.desc_editor, lines, suppress_name=False)
            self._apply_masked_color_selections(self.desc_editor, [])
            return
        lines, spans = self._masked_lines_and_spans_from_raw(self._raw_desc_lines)
        self._masked_desc_color_spans = spans
        self._set_editor_lines(self.desc_editor, lines, suppress_name=False)
        self._apply_masked_color_selections(self.desc_editor, spans)

    def _sync_control_code_visibility(self, force: bool = False) -> None:
        self._sync_single_editor_visibility(self.name_editor, force=force)
        self._sync_single_editor_visibility(self.desc_editor, force=force)
        self._refresh_status()

    def set_hide_control_codes_when_unfocused(self, enabled: bool) -> None:
        new_value = bool(enabled)
        if self.hide_control_codes_when_unfocused == new_value:
            return
        self.hide_control_codes_when_unfocused = new_value
        self._pending_mouse_reveal_name = False
        self._pending_mouse_reveal_desc = False
        self._sync_control_code_visibility(force=True)

    def refresh_theme_palette(self) -> None:
        dark_theme = is_dark_palette()
        if self._dark_theme == dark_theme:
            return
        self._dark_theme = dark_theme
        self._name_highlighter.set_dark_theme(dark_theme)
        self._desc_highlighter.set_dark_theme(dark_theme)
        self._refresh_block_style()
        self._apply_editor_style()
        self._refresh_status()

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
            editor = cast(QPlainTextEdit, watched)
            if event.type() == QEvent.Type.FocusIn:
                if self._should_defer_mouse_focus_reveal(editor, event):
                    self._set_pending_mouse_reveal_for_editor(editor, True)
                    _set_hard_newline_markers(editor, True)
                else:
                    self._set_pending_mouse_reveal_for_editor(editor, False)
                    self._reveal_raw_editor_now(editor)
                    self._refresh_status()
                self.activated.emit(self.segment.uid)
            elif event.type() == QEvent.Type.FocusOut:
                self._set_pending_mouse_reveal_for_editor(editor, False)
                self._sync_single_editor_visibility(editor, force=True)
            elif event.type() == QEvent.Type.MouseButtonPress:
                self.activated.emit(self.segment.uid)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._apply_deferred_mouse_reveal_for_editor(editor)
            elif event.type() == QEvent.Type.KeyPress:
                self._apply_deferred_mouse_reveal_for_editor(editor)
        elif watched is self.name_editor.viewport():
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._apply_deferred_mouse_reveal_for_editor(self.name_editor)
            if self._handle_variable_tooltip_event(self.name_editor, event):
                return True
        elif watched is self.desc_editor.viewport():
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._apply_deferred_mouse_reveal_for_editor(self.desc_editor)
            if self._handle_variable_tooltip_event(self.desc_editor, event):
                return True
        return super().eventFilter(watched, event)

    def _variable_tooltip_text(self, editor: QPlainTextEdit, event_pos: QPoint) -> str:
        variable_id = _variable_token_id_at_editor_position(editor, event_pos)
        if variable_id is not None:
            details = (
                self.variable_label_resolver(variable_id).strip()
                if self.variable_label_resolver is not None
                else ""
            )
            if details:
                return f"\\V[{variable_id}] -> {details}"
            return f"\\V[{variable_id}] -> system.variables[{variable_id}]"
        icon_id = _icon_token_id_at_editor_position(editor, event_pos)
        if icon_id is not None:
            return f"\\I[{icon_id}] -> icon[{icon_id}]"
        party_id = _party_token_id_at_editor_position(editor, event_pos)
        if party_id is not None:
            return f"\\P[{party_id}] -> party member[{party_id}]"
        if _currency_token_at_editor_position(editor, event_pos):
            return r"\G -> currency unit"
        return ""

    def _handle_variable_tooltip_event(self, editor: QPlainTextEdit, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            mouse_event = cast(QMouseEvent, event)
            local_pos = mouse_event.position().toPoint()
            text = self._variable_tooltip_text(editor, local_pos)
            if not text:
                QToolTip.hideText()
                return False
            global_pos = editor.viewport().mapToGlobal(local_pos)
            QToolTip.showText(global_pos, text, editor.viewport())
            return False
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
            block_bg = "#0f2233" if self._dark_theme else "#e0f2fe"
            block_border = "#38bdf8" if self._dark_theme else "#0369a1"
            meta_color = "#bae6fd" if self._dark_theme else "#075985"
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
            bg = "#0b2233" if self._dark_theme else "#f0f9ff"
            border = "#38bdf8" if self._dark_theme else "#0369a1"
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
        smart_collapse_allow_comma_endings: bool,
        smart_collapse_allow_colon_triplet_endings: bool,
        smart_collapse_ellipsis_lowercase_rule: bool,
        smart_collapse_collapse_if_no_punctuation: bool,
        smart_collapse_min_soft_ratio: float,
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
        highlight_contains_japanese: bool,
        actor_mode: bool,
        name_index_kind: str,
        name_index_label: str,
        allow_structural_actions: bool,
        inferred_speaker_name_resolver: Optional[Callable[[DialogueSegment], str]],
        segment_prompt_type_resolver: Optional[Callable[..., str]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.segment = segment
        self.block_number = block_number
        self.thin_width = max(1, thin_width)
        self.wide_width = max(1, wide_width)
        self.max_lines = max(1, max_lines)
        self.infer_name_from_first_line = infer_name_from_first_line
        self.smart_collapse_allow_comma_endings = bool(
            smart_collapse_allow_comma_endings
        )
        self.smart_collapse_allow_colon_triplet_endings = bool(
            smart_collapse_allow_colon_triplet_endings
        )
        self.smart_collapse_ellipsis_lowercase_rule = bool(
            smart_collapse_ellipsis_lowercase_rule
        )
        self.smart_collapse_collapse_if_no_punctuation = bool(
            smart_collapse_collapse_if_no_punctuation
        )
        self.smart_collapse_min_soft_ratio = max(
            0.0, min(1.0, float(smart_collapse_min_soft_ratio))
        )
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
        self.japanese_char_problem_enabled = bool(highlight_contains_japanese)
        self.actor_mode = actor_mode
        self.name_index_kind = name_index_kind.strip().lower()
        self.name_index_label = name_index_label.strip(
        ) if name_index_label.strip() else "Entry"
        self.allow_structural_actions = allow_structural_actions
        self.inferred_speaker_name_resolver = inferred_speaker_name_resolver
        self.segment_prompt_type_resolver = segment_prompt_type_resolver
        self.source_hint_lines_resolver: Optional[
            Callable[[DialogueSegment], list[str]]
        ] = None
        self.control_mismatch_source_lines_resolver: Optional[
            Callable[[DialogueSegment], list[str]]
        ] = None
        self.control_mismatch_translation_lines_resolver: Optional[
            Callable[[DialogueSegment], list[str]]
        ] = None
        self._actor_id = self._actor_id_from_uid()
        self._name_index_field = self._name_index_field_from_uid()
        self._suppress_text_changed = False
        self._displaying_masked_text = False
        self._masked_color_spans: list[list[tuple[int, int, str, float]]] = []
        self._source_hint_lines: list[str] = []
        self._source_hint_overlay: Optional[QLabel] = None
        self._width_limit_marker: Optional[QFrame] = None
        self.editor: Optional[QPlainTextEdit] = None
        self._control_code_highlighter: Optional[ControlCodeHighlighter] = None
        self._pending_mouse_reveal = False
        self._selected = False
        self._audit_pinned = False
        self._flash_timer: Optional[QTimer] = None
        self._flash_step = 0
        self._flash_level = 0
        self._dark_theme = is_dark_palette()
        self._apply_theme_palette_colors(self._dark_theme)

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
        self.context_label.setVisible(False)
        root.addWidget(self.context_label)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("MetaDim")
        root.addWidget(self.meta_label)

        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.setSpacing(8)
        self._editor_row = editor_row

        self._raw_lines = [""]
        self._load_editor_lines_from_segment()
        if self._uses_translation_storage():
            source_lines = self.segment.source_lines or self.segment.original_lines or self.segment.lines or [
                ""]
            self._source_hint_lines = list(source_lines)

        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._editor_font = mono

        self._editor_container = QWidget(self)
        self._editor_layout = QHBoxLayout(self._editor_container)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._preview = QLabel(self._editor_container)
        self._preview.setWordWrap(True)
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        self._preview.setObjectName("EditorPreview")
        self._preview.setFont(self._editor_font)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._preview.installEventFilter(self)
        self._editor_container.installEventFilter(self)
        self._editor_layout.addWidget(self._preview, 1)
        editor_row.addWidget(self._editor_container, 1)
        editor_row.addStretch(1)
        root.addLayout(editor_row)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(8)
        self.status_label = QLabel("")
        self.status_label.setObjectName("MetaDim")
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.status_label.setMinimumWidth(0)
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
        if self._uses_translation_storage():
            self.reset_button.setToolTip(
                "Reset this translation block to its last saved translation text.")
        else:
            self.reset_button.setToolTip(
                "Reset this block to its last saved text.")
        self.reset_button.clicked.connect(self._on_reset_clicked)
        footer_row.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(footer_row)

        self._preview.setText(self._preview_text())
        self._apply_editor_width()
        self._sync_control_code_visibility(force=True)
        self._refresh_meta_label()
        self._refresh_status()

    def focus_editor(self) -> None:
        self._mount_editor()
        if self.editor is not None:
            self.editor.setFocus()

    def set_editor_active(self, active: bool) -> None:
        if active:
            self._mount_editor()
            return
        self._unmount_editor()

    def _preview_text(self) -> str:
        lines = self._raw_lines if self._raw_lines else self._segment_storage_lines()
        if self.hide_control_codes_when_unfocused:
            lines = self._masked_lines_from_raw(lines)
        if not lines:
            return ""
        visible = lines[: self.max_lines]
        preview = "\n".join(visible)
        if len(lines) > self.max_lines:
            preview += "\n..."
        return preview

    def _mount_editor(self) -> None:
        if self.editor is not None:
            return
        ed = QPlainTextEdit(self._editor_container)
        ed.setFont(self._editor_font)
        _set_hard_newline_markers(ed, False)
        self._load_editor_lines_from_segment()
        self._suppress_text_changed = True
        ed.setPlainText("\n".join(self._raw_lines or [""]))
        self._suppress_text_changed = False
        ed.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._control_code_highlighter = ControlCodeHighlighter(
            ed.document(),
            self._dark_theme,
            color_code_resolver=self.color_code_resolver,
        )

        overlay = QLabel(ed.viewport())
        overlay.setTextFormat(Qt.TextFormat.RichText)
        overlay.setWordWrap(True)
        overlay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        overlay.setStyleSheet("background: transparent;")
        overlay.setFont(self._editor_font)
        width_limit_marker = QFrame(ed.viewport())
        width_limit_marker.setFrameShape(QFrame.Shape.NoFrame)
        width_limit_marker.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        ed.viewport().setMouseTracking(True)
        ed.viewport().installEventFilter(self)
        ed.installEventFilter(self)
        ed.textChanged.connect(self._on_text_changed)

        self.editor = ed
        self._source_hint_overlay = overlay
        self._width_limit_marker = width_limit_marker
        self._preview.setVisible(False)
        self._editor_layout.addWidget(ed, 1)
        self._apply_editor_width()
        self._apply_editor_style(self._has_warning)
        self._sync_control_code_visibility(force=True)
        self._refresh_source_hint_overlay()
        self._refresh_width_limit_marker()
        self._apply_overflow_highlighting()

    def _unmount_editor(self) -> None:
        ed = self.editor
        if ed is None:
            return
        if ed.hasFocus():
            return
        if not self._displaying_masked_text:
            self._raw_lines = split_lines_preserve_empty(ed.toPlainText())
            storage_lines = self._storage_lines_from_editor_lines(self._raw_lines)
            if self._uses_translation_storage():
                self.segment.translation_lines = list(storage_lines)
            else:
                self.segment.lines = list(storage_lines)
                self.segment.source_lines = list(storage_lines)
        try:
            ed.textChanged.disconnect(self._on_text_changed)
        except (RuntimeError, TypeError):
            pass
        ed.removeEventFilter(self)
        ed.viewport().removeEventFilter(self)
        self._editor_layout.removeWidget(ed)

        if self._source_hint_overlay is not None:
            self._source_hint_overlay.setParent(None)
            self._source_hint_overlay.deleteLater()
            self._source_hint_overlay = None
        if self._width_limit_marker is not None:
            self._width_limit_marker.setParent(None)
            self._width_limit_marker.deleteLater()
            self._width_limit_marker = None

        ed.setParent(None)
        ed.deleteLater()
        self.editor = None
        self._control_code_highlighter = None
        self._displaying_masked_text = False
        self._pending_mouse_reveal = False
        self._masked_color_spans = []
        self._preview.setText(self._preview_text())
        self._preview.setVisible(True)
        self._apply_editor_width()
        self._refresh_status()

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

    def _reveal_raw_now(self) -> None:
        editor = self.editor
        if editor is None:
            return
        self._displaying_masked_text = False
        self._masked_color_spans = []
        _set_hard_newline_markers(editor, True)
        self._set_editor_text_lines(self._raw_lines)
        self._refresh_source_hint_overlay()
        self._refresh_status()

    def _should_defer_mouse_focus_reveal(self, event: QEvent) -> bool:
        if not self.hide_control_codes_when_unfocused:
            return False
        if not self._displaying_masked_text:
            return False
        if event.type() != QEvent.Type.FocusIn:
            return False
        try:
            focus_event = cast(QFocusEvent, event)
            return focus_event.reason() == Qt.FocusReason.MouseFocusReason
        except Exception:
            return False

    def _apply_deferred_mouse_reveal(self) -> None:
        editor = self.editor
        if editor is None:
            self._pending_mouse_reveal = False
            return
        if not self._pending_mouse_reveal:
            return
        cursor = editor.textCursor()
        line_index, masked_col = _cursor_line_col(cursor)
        self._pending_mouse_reveal = False
        self._reveal_raw_now()
        editor = self.editor
        if editor is None or self._displaying_masked_text:
            return
        raw_lines = list(self._raw_lines if self._raw_lines else [""])
        if not raw_lines:
            return
        safe_line = max(0, min(len(raw_lines) - 1, line_index))
        raw_col = _raw_col_for_masked_col(raw_lines[safe_line], masked_col)
        target_pos = _doc_pos_from_line_col(raw_lines, safe_line, raw_col)
        remapped = editor.textCursor()
        remapped.setPosition(target_pos)
        editor.setTextCursor(remapped)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        editor = self.editor
        if watched is self._preview or watched is self._editor_container:
            if event.type() == QEvent.Type.MouseButtonPress:
                self._mount_editor()
                self.activated.emit(self.segment.uid)
                if self.editor is not None:
                    self.editor.setFocus()
                return True
            return super().eventFilter(watched, event)
        if editor is not None and watched is editor:
            if event.type() == QEvent.Type.FocusIn:
                if self._should_defer_mouse_focus_reveal(event):
                    self._pending_mouse_reveal = True
                    _set_hard_newline_markers(editor, True)
                else:
                    self._pending_mouse_reveal = False
                    self._reveal_raw_now()
                self.activated.emit(self.segment.uid)
            elif event.type() == QEvent.Type.FocusOut:
                self._pending_mouse_reveal = False
                self._sync_control_code_visibility(force=True)
            elif event.type() == QEvent.Type.MouseButtonPress:
                self.activated.emit(self.segment.uid)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self._apply_deferred_mouse_reveal()
            elif event.type() == QEvent.Type.KeyPress:
                self._apply_deferred_mouse_reveal()
        elif editor is not None and watched is editor.viewport():
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._apply_deferred_mouse_reveal()
            if self._handle_variable_tooltip_event(event):
                return True
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self._refresh_source_hint_overlay()
                self._refresh_width_limit_marker()
        return super().eventFilter(watched, event)

    def _variable_tooltip_text(self, event_pos: QPoint) -> str:
        editor = self.editor
        if editor is None:
            return ""
        variable_id = _variable_token_id_at_editor_position(editor, event_pos)
        if variable_id is not None:
            details = (
                self.variable_label_resolver(variable_id).strip()
                if self.variable_label_resolver is not None
                else ""
            )
            if details:
                return f"\\V[{variable_id}] -> {details}"
            return f"\\V[{variable_id}] -> system.variables[{variable_id}]"
        icon_id = _icon_token_id_at_editor_position(editor, event_pos)
        if icon_id is not None:
            return f"\\I[{icon_id}] -> icon[{icon_id}]"
        party_id = _party_token_id_at_editor_position(editor, event_pos)
        if party_id is not None:
            return f"\\P[{party_id}] -> party member[{party_id}]"
        if _currency_token_at_editor_position(editor, event_pos):
            return r"\G -> currency unit"
        return ""

    def _handle_variable_tooltip_event(self, event: QEvent) -> bool:
        editor = self.editor
        if editor is None:
            return False
        if event.type() == QEvent.Type.MouseMove:
            mouse_event = cast(QMouseEvent, event)
            local_pos = mouse_event.position().toPoint()
            text = self._variable_tooltip_text(local_pos)
            if not text:
                QToolTip.hideText()
                return False
            global_pos = editor.viewport().mapToGlobal(local_pos)
            QToolTip.showText(global_pos, text, editor.viewport())
            return False
        if event.type() != QEvent.Type.ToolTip:
            return False
        help_event = cast(QHelpEvent, event)
        text = self._variable_tooltip_text(help_event.pos())
        if not text:
            QToolTip.hideText()
            return False
        QToolTip.showText(help_event.globalPos(), text, editor.viewport())
        return True

    def mousePressEvent(self, event: Any) -> None:
        self._mount_editor()
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
        return self.segment.segment_kind in {"dialogue", "script_message", "tyrano_dialogue"}

    def _is_choice_block(self) -> bool:
        return self.segment.segment_kind == "choice"

    def _is_map_display_name_block(self) -> bool:
        return self.segment.segment_kind == "map_display_name"

    def _is_tyrano_dialogue_block(self) -> bool:
        return self.segment.segment_kind == "tyrano_dialogue"

    def _is_tyrano_tag_text_block(self) -> bool:
        return self.segment.segment_kind == "tyrano_tag_text"

    def _segment_entry_type(self, default_type: str = "dialogue") -> str:
        resolver = self.segment_prompt_type_resolver
        if callable(resolver):
            try:
                resolved = resolver(self.segment, default_type)
            except TypeError:
                try:
                    resolved = resolver(self.segment)
                except Exception:
                    resolved = default_type
            except Exception:
                resolved = default_type
            if isinstance(resolved, str) and resolved.strip():
                return resolved.strip().lower()
        normalized_default = default_type.strip().lower() if isinstance(default_type, str) else ""
        if normalized_default:
            return normalized_default
        return "dialogue"

    def _is_thought_block(self) -> bool:
        if not self._is_standard_dialogue_block():
            return False
        return self._segment_entry_type("dialogue") == "thought"

    def _uses_translation_storage(self) -> bool:
        return self.translator_mode

    def _flatten_embedded_newlines(self, lines: list[str]) -> list[str]:
        if not lines:
            return [""]
        flattened: list[str] = []
        for line in lines:
            if not isinstance(line, str):
                normalized_line = "" if line is None else str(line)
            else:
                normalized_line = line
            split_lines = split_lines_preserve_empty(normalized_line)
            if split_lines:
                flattened.extend(split_lines)
            else:
                flattened.append("")
        return flattened if flattened else [""]

    def _line1_inference_is_disabled(self) -> bool:
        return bool(getattr(self.segment, "disable_line1_speaker_inference", False))

    def _line1_inference_is_forced(self) -> bool:
        return bool(getattr(self.segment, "force_line1_speaker_inference", False)) and (
            not self._line1_inference_is_disabled()
        )

    def _segment_storage_lines(self) -> list[str]:
        raw_lines = self.segment.translation_lines if self._uses_translation_storage() else self.segment.lines
        if not raw_lines:
            return [""]
        return self._flatten_embedded_newlines(list(raw_lines))

    def _line1_inference_active(self) -> bool:
        return bool(self._resolved_inferred_speaker_name())

    def _resolved_inferred_speaker_name(self) -> str:
        if self._line1_inference_is_disabled():
            return ""
        if not self._is_standard_dialogue_block():
            return ""
        if not self.infer_name_from_first_line:
            return ""
        if self.segment.speaker_name != NO_SPEAKER_KEY:
            return ""
        if self.inferred_speaker_name_resolver is None:
            return ""
        try:
            inferred = self.inferred_speaker_name_resolver(self.segment)
        except Exception:
            return ""
        return inferred.strip()

    def _line1_inference_prefix_text(self) -> str:
        if self._uses_translation_storage():
            source_lines = self.segment.source_lines or self.segment.original_lines or self.segment.lines or [
                ""]
            normalized_source = self._flatten_embedded_newlines(list(source_lines))
            return normalized_source[0] if normalized_source else ""
        source_lines = self.segment.lines or [""]
        normalized_source = self._flatten_embedded_newlines(list(source_lines))
        return normalized_source[0] if normalized_source else ""

    def _line1_inference_source_lines(self) -> list[str]:
        if self._uses_translation_storage():
            source_lines = self.segment.source_lines or self.segment.original_lines or self.segment.lines or [
                ""]
            if not source_lines:
                return [""]
            return self._flatten_embedded_newlines(list(source_lines))
        source_lines = self.segment.lines or [""]
        if not source_lines:
            return [""]
        return self._flatten_embedded_newlines(list(source_lines))

    def _source_hint_lines_for_overlay(self) -> list[str]:
        if not self._uses_translation_storage():
            return list(self._source_hint_lines)
        source_hint_resolver = self.source_hint_lines_resolver
        if callable(source_hint_resolver):
            try:
                resolved_hint = source_hint_resolver(self.segment)
            except Exception:
                resolved_hint = None
            if isinstance(resolved_hint, list):
                normalized_hint = [
                    line if isinstance(line, str) else ("" if line is None else str(line))
                    for line in resolved_hint
                ]
                return normalized_hint if normalized_hint else [""]
        source_lines = self._line1_inference_source_lines()
        return self._editor_lines_from_storage_lines(source_lines)

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
        if self._uses_translation_storage():
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

    def _max_editor_target_width(self) -> Optional[int]:
        parent = self.parentWidget()
        scroll_area: Optional[QScrollArea] = None
        while parent is not None:
            if isinstance(parent, QScrollArea):
                scroll_area = parent
                break
            parent = parent.parentWidget()
        if scroll_area is None:
            return None
        viewport_width = int(scroll_area.viewport().width())
        if viewport_width <= 0:
            return None

        available = viewport_width
        container = self.parentWidget()
        if container is not None:
            container_layout = container.layout()
            if container_layout is not None:
                margins = container_layout.contentsMargins()
                available -= margins.left() + margins.right()
        root_layout = self.layout()
        if root_layout is not None:
            root_margins = root_layout.contentsMargins()
            available -= root_margins.left() + root_margins.right()
        row_margins = self._editor_row.contentsMargins()
        available -= row_margins.left() + row_margins.right()
        available -= max(0, int(self._editor_row.spacing()))
        available -= max(0, int(self.frameWidth()) * 2)
        return max(1, available)

    def _apply_editor_width(self) -> None:
        editor = self.editor
        target_widgets: list[QWidget] = [self._editor_container]
        if editor is not None:
            target_widgets.append(editor)
        width_cap = self._max_editor_target_width()
        if self.actor_mode:
            metrics = QFontMetrics(self._editor_font)
            min_width = max(420, metrics.horizontalAdvance("M") * 24)
            if width_cap is not None:
                min_width = min(min_width, width_cap)
            for widget in target_widgets:
                widget.setMinimumWidth(min_width)
                widget.setMaximumWidth(width_cap if width_cap is not None else 16777215)
            if self.name_index_kind == "item" and self._name_index_field == "description":
                target_height = max(164, metrics.lineSpacing() * 8)
            else:
                target_height = max(96, metrics.lineSpacing() * 3)
            for widget in target_widgets:
                widget.setFixedHeight(target_height)
            return
        char_width = self._width_chars()
        metrics = QFontMetrics(self._editor_font)
        pixel_width = metrics.horizontalAdvance("M") * (char_width + 2)
        char_pixel = metrics.horizontalAdvance("M")
        expand_chars = self._dynamic_expand_width_chars(char_width)
        target_width = pixel_width + (char_pixel * expand_chars)
        if width_cap is not None:
            target_width = min(target_width, width_cap)
        target_height = max(130, metrics.lineSpacing() * (self.max_lines + 2))
        for widget in target_widgets:
            widget.setMinimumWidth(target_width)
            widget.setMaximumWidth(target_width)
            widget.setFixedHeight(target_height)
        if expand_chars > 0:
            self._editor_row.setStretch(0, 100)
            self._editor_row.setStretch(1, 0)
        else:
            self._editor_row.setStretch(0, 1)
            self._editor_row.setStretch(1, 1)
        self._refresh_width_limit_marker()

    def _dynamic_expand_width_chars(self, width_chars: int) -> int:
        if self.actor_mode:
            return 0
        if not self._is_standard_dialogue_block():
            return 0
        max_visible = self._max_display_width_units()
        if max_visible <= float(width_chars):
            return 0
        # Grow to fit longer lines, but cap to avoid unbounded widths.
        overflow_chars = int(math.ceil(max_visible - float(width_chars)))
        return max(0, min(120, overflow_chars + 2))

    def _line_display_width_units(
        self,
        line: str,
        spans: Optional[list[tuple[int, int, str, float]]] = None,
    ) -> float:
        if not line:
            return 0.0
        metrics = QFontMetrics(self._editor_font)
        base_char_px = float(max(1, metrics.horizontalAdvance("M")))
        if not spans:
            return float(metrics.horizontalAdvance(line)) / base_char_px

        units = 0.0
        cursor = 0
        sorted_spans = sorted(spans, key=lambda item: (item[0], item[1]))
        line_len = len(line)
        for start, end, _color_hex, font_scale in sorted_spans:
            safe_start = max(0, min(line_len, int(start)))
            safe_end = max(safe_start, min(line_len, int(end)))
            if safe_start > cursor:
                units += float(metrics.horizontalAdvance(line[cursor:safe_start])) / base_char_px
            if safe_end > safe_start:
                chunk = line[safe_start:safe_end]
                chunk_units = float(metrics.horizontalAdvance(chunk)) / base_char_px
                scale = float(font_scale) if isinstance(font_scale, (int, float)) else 1.0
                units += chunk_units * max(0.1, scale)
            cursor = max(cursor, safe_end)
        if cursor < line_len:
            units += float(metrics.horizontalAdvance(line[cursor:])) / base_char_px
        return units

    def _max_display_width_units(self) -> float:
        editor = self.editor
        if editor is not None:
            display_lines = split_lines_preserve_empty(editor.toPlainText())
        else:
            if self._displaying_masked_text:
                display_lines = self._masked_lines_from_raw(self._raw_lines)
            else:
                display_lines = list(self._raw_lines if self._raw_lines else [""])
        if not display_lines:
            return 0.0

        if not self._displaying_masked_text:
            return max(self._line_display_width_units(line) for line in display_lines)

        spans_per_line = self._masked_color_spans
        if len(spans_per_line) != len(display_lines):
            display_lines = self._masked_lines_from_raw(self._raw_lines)
            spans_per_line = self._masked_color_spans
        if len(spans_per_line) != len(display_lines):
            spans_per_line = [[] for _ in display_lines]
        return max(
            self._line_display_width_units(
                line,
                spans_per_line[idx] if idx < len(spans_per_line) else None,
            )
            for idx, line in enumerate(display_lines)
        )

    def _refresh_width_limit_marker(self) -> None:
        editor = self.editor
        marker = self._width_limit_marker
        if editor is None or marker is None:
            return
        if self.actor_mode or not self._is_standard_dialogue_block():
            marker.setVisible(False)
            return
        viewport = editor.viewport()
        width_chars = self._width_chars()
        metrics = QFontMetrics(self._editor_font)
        char_pixel = metrics.horizontalAdvance("M")
        margin = int(editor.document().documentMargin())
        marker_x = margin + (char_pixel * width_chars)
        if marker_x <= 0 or marker_x >= viewport.width():
            marker.setVisible(False)
            return
        marker_color = "#ef4444" if self._dark_theme else "#b91c1c"
        marker.setStyleSheet(f"background: {marker_color}; border: none;")
        marker.setGeometry(marker_x, 1, 1, max(1, viewport.height() - 2))
        width_mode = self._width_mode_name()
        marker.setToolTip(f"Recommended width limit: {width_chars} chars ({width_mode})")
        marker.raise_()
        marker.setVisible(True)

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
            elif self._is_map_display_name_block():
                block_bg = "#1d2f2a" if self._dark_theme else "#ecfdf5"
                block_border = "#10b981" if self._dark_theme else "#059669"
                meta_color = "#86efac" if self._dark_theme else "#065f46"
            elif self._is_thought_block():
                block_bg = "#1f2a44" if self._dark_theme else "#dbeafe"
                block_border = "#60a5fa" if self._dark_theme else "#2563eb"
                meta_color = "#bfdbfe" if self._dark_theme else "#1e3a8a"
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
            block_bg = "#0f2233" if self._dark_theme else "#e0f2fe"
            block_border = "#38bdf8" if self._dark_theme else "#0369a1"
            meta_color = "#bae6fd" if self._dark_theme else "#075985"
        title_suffix = f" ({', '.join(tags)})" if tags else ""
        context_text = self.segment.context.strip()
        self.context_label.setVisible(False)

        def set_title_text(base_text: str) -> None:
            escaped_base = html.escape(base_text)
            if self._selected and context_text:
                escaped_context = html.escape(context_text)
                self.title_label.setTextFormat(Qt.TextFormat.RichText)
                self.title_label.setText(
                    f"<b>{escaped_base}</b>"
                    f"<span style=\"font-weight:400;\"> | {escaped_context}</span>"
                )
                return
            self.title_label.setTextFormat(Qt.TextFormat.RichText)
            self.title_label.setText(f"<b>{escaped_base}</b>")

        if self.actor_mode:
            if self._is_tyrano_tag_text_block():
                set_title_text(f"Script Text {self.block_number}{title_suffix}")
            else:
                label = (
                    f"{self.name_index_label} {self._actor_id}"
                    if self._actor_id is not None
                    else f"{self.name_index_label} Entry {self.block_number}"
                )
                set_title_text(f"{label}{title_suffix}")
        else:
            label = (
                "Block"
            )
            block_prefix = label
            if self._is_choice_block():
                block_prefix = "Choice"
            elif self._is_map_display_name_block():
                block_prefix = "Map Display Name"
            elif self._is_thought_block():
                block_prefix = "Thought"
            if self._is_map_display_name_block():
                set_title_text(f"{block_prefix}{title_suffix}")
            else:
                set_title_text(f"{block_prefix} {self.block_number}{title_suffix}")
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
        if self.editor is None:
            return
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
            bg = "#0b2233" if self._dark_theme else "#f0f9ff"
            border = "#38bdf8" if self._dark_theme else "#0369a1"
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
        if self.editor is None:
            self._preview.setText(self._preview_text())
            return
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
            rows.append(_html_escape_line_preserve_indent(line))
        return "<br/>".join(rows)

    def _should_show_masked_preview_overlay(self) -> bool:
        return bool(
            self._displaying_masked_text
            and self.editor is not None
            and self.speaker_display_html_resolver is not None
        )

    @staticmethod
    def _escape_chunk_for_masked_html(chunk: str, *, at_line_start: bool) -> str:
        if not chunk:
            return ""
        if not at_line_start:
            return html.escape(chunk)
        idx = 0
        indent_parts: list[str] = []
        while idx < len(chunk):
            ch = chunk[idx]
            if ch == " ":
                indent_parts.append("&nbsp;")
                idx += 1
                continue
            if ch == "\t":
                indent_parts.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                idx += 1
                continue
            break
        return "".join(indent_parts) + html.escape(chunk[idx:])

    def _masked_lines_with_spans_html(
        self,
        lines: list[str],
        spans_per_line: list[list[tuple[int, int, str, float]]],
    ) -> str:
        if not lines:
            return ""
        base_point_size = self._editor_font.pointSizeF()
        if base_point_size <= 0:
            fallback_point_size = self._editor_font.pointSize()
            base_point_size = float(fallback_point_size if fallback_point_size > 0 else 10)
        rows: list[str] = []
        for line_idx, line in enumerate(lines):
            line_len = len(line)
            spans = (
                spans_per_line[line_idx]
                if line_idx < len(spans_per_line)
                else []
            )
            safe_spans = sorted(
                (
                    max(0, min(line_len, int(start))),
                    max(0, min(line_len, int(end))),
                    color_hex,
                    float(font_scale) if isinstance(font_scale, (int, float)) else 1.0,
                )
                for start, end, color_hex, font_scale in spans
            )
            parts: list[str] = []
            cursor = 0
            at_line_start = True

            def append_span(
                chunk: str,
                color_hex: str,
                font_scale: float,
            ) -> None:
                nonlocal at_line_start
                if not chunk:
                    return
                escaped = self._escape_chunk_for_masked_html(
                    chunk,
                    at_line_start=at_line_start,
                )
                at_line_start = False
                style_parts: list[str] = []
                color = QColor(color_hex)
                if color.isValid():
                    style_parts.append(f"color: {color.name()};")
                if abs(font_scale - 1.0) > 0.01:
                    point_size = max(1.0, base_point_size * font_scale)
                    style_parts.append(f"font-size: {point_size:.1f}pt;")
                if style_parts:
                    parts.append(f"<span style=\"{' '.join(style_parts)}\">{escaped}</span>")
                    return
                parts.append(escaped)

            for start, end, color_hex, font_scale in safe_spans:
                if end <= start:
                    continue
                if start > cursor:
                    append_span(line[cursor:start], "", 1.0)
                if end > cursor:
                    append_span(line[start:end], color_hex, font_scale)
                cursor = max(cursor, end)
            if cursor < line_len:
                append_span(line[cursor:], "", 1.0)
            rows.append("".join(parts) if parts else "&nbsp;")
        return "<br/>".join(rows)

    def _masked_preview_html(self) -> str:
        lines = self._raw_lines or [""]
        if self.hidden_control_colored_line_resolver is not None:
            masked_lines = self._masked_lines_from_raw(lines)
            return self._masked_lines_with_spans_html(masked_lines, self._masked_color_spans)
        full_text = "\n".join(lines)
        if self.speaker_display_html_resolver is not None:
            rendered = self.speaker_display_html_resolver(full_text).strip()
            if rendered:
                return rendered
        lines = self._masked_lines_from_raw(lines)
        rows: list[str] = []
        for line in lines:
            rows.append(_html_escape_line_preserve_indent(line))
        return "<br/>".join(rows)

    def _refresh_source_hint_overlay(self) -> None:
        editor = self.editor
        if self._source_hint_overlay is None or editor is None:
            return
        self._source_hint_lines = self._source_hint_lines_for_overlay()
        has_user_text = any(line.strip() for line in self._raw_lines)
        show_source_hint = (
            self._uses_translation_storage()
            and not has_user_text
            and bool(self._source_hint_lines)
        )
        show_masked_preview = (
            self._should_show_masked_preview_overlay()
            and (not show_source_hint)
        )
        should_show = show_masked_preview or show_source_hint
        if should_show:
            if show_source_hint:
                self._source_hint_overlay.setText(self._source_hint_html())
            else:
                self._source_hint_overlay.setText(self._masked_preview_html())
            self._source_hint_overlay.setGeometry(
                editor.viewport().rect().adjusted(6, 4, -6, -4)
            )
            self._source_hint_overlay.raise_()
        self._source_hint_overlay.setVisible(should_show)

    def _masked_lines_from_raw(self, lines: list[str]) -> list[str]:
        source_lines = lines or [""]
        if self.hidden_control_colored_line_resolver is not None:
            joined = "\n".join(source_lines)
            prefix_text = ""
            if self._line1_inference_active():
                prefix_text = self._line1_inference_prefix_text()
            if prefix_text:
                joined = f"{prefix_text}\n{joined}"
            masked_text, spans = self.hidden_control_colored_line_resolver(joined)
            split_lines, spans_per_line = _split_masked_text_and_spans(masked_text, list(spans))
            if prefix_text:
                split_lines = split_lines[1:] if len(split_lines) > 1 else [""]
                spans_per_line = spans_per_line[1:] if len(spans_per_line) > 1 else [[]]
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
        if self.editor is None:
            return True
        return self.editor.hasFocus()

    def set_hide_control_codes_when_unfocused(self, enabled: bool) -> None:
        new_value = bool(enabled)
        if self.hide_control_codes_when_unfocused == new_value:
            return
        self.hide_control_codes_when_unfocused = new_value
        self._pending_mouse_reveal = False
        self._sync_control_code_visibility(force=True)

    def _apply_theme_palette_colors(self, dark_theme: bool) -> None:
        self._dark_theme = bool(dark_theme)
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
            return
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

    def refresh_theme_palette(self) -> None:
        dark_theme = is_dark_palette()
        if self._dark_theme == dark_theme:
            return
        self._apply_theme_palette_colors(dark_theme)
        if self._control_code_highlighter is not None:
            self._control_code_highlighter.set_dark_theme(dark_theme)
        self._refresh_block_style()
        self._apply_editor_style(self._has_warning)
        self._refresh_width_limit_marker()
        self._refresh_status()

    def set_control_mismatch_highlighting_enabled(self, enabled: bool) -> None:
        new_value = bool(enabled)
        if self.control_mismatch_highlighting_enabled == new_value:
            return
        self.control_mismatch_highlighting_enabled = new_value
        self._refresh_status()

    def set_japanese_char_problem_enabled(self, enabled: bool) -> None:
        new_value = bool(enabled)
        if self.japanese_char_problem_enabled == new_value:
            return
        self.japanese_char_problem_enabled = new_value
        self._refresh_status()

    def _source_lines_for_control_mismatch(self) -> list[str]:
        source_resolver = self.control_mismatch_source_lines_resolver
        use_local_only = bool(self._uses_translation_storage() and self.segment.translation_only)
        if (not use_local_only) and self._uses_translation_storage() and callable(source_resolver):
            try:
                resolved_source = source_resolver(self.segment)
            except Exception:
                resolved_source = None
            if isinstance(resolved_source, list):
                normalized = [
                    line if isinstance(line, str) else ("" if line is None else str(line))
                    for line in resolved_source
                ]
                return normalized if normalized else [""]
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
        translation_resolver = self.control_mismatch_translation_lines_resolver
        use_local_only = bool(self._uses_translation_storage() and self.segment.translation_only)
        if (not use_local_only) and self._uses_translation_storage() and callable(translation_resolver):
            try:
                resolved_translation = translation_resolver(self.segment)
            except Exception:
                resolved_translation = None
            if isinstance(resolved_translation, list):
                normalized = [
                    line if isinstance(line, str) else ("" if line is None else str(line))
                    for line in resolved_translation
                ]
                return normalized if normalized else [""]
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
        if not self._uses_translation_storage():
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

    def _japanese_problem_spans(self) -> list[tuple[int, int]]:
        if not self.japanese_char_problem_enabled:
            return []
        if not self._uses_translation_storage():
            return []
        if self.actor_mode:
            return []
        if not self._is_standard_dialogue_block():
            return []
        tl_lines = list(self._raw_lines if self._raw_lines else [""])
        if not any(visible_length(line) > 0 for line in tl_lines):
            return []
        tl_text = "\n".join(tl_lines)
        return japanese_character_spans(tl_text)

    def _has_japanese_text_problem(self) -> bool:
        return bool(self._japanese_problem_spans())

    def _control_mismatch_selections(self) -> list[QTextEdit.ExtraSelection]:
        editor = self.editor
        if editor is None:
            return []
        if not self._uses_translation_storage():
            return []
        if not self.control_mismatch_highlighting_enabled:
            return []
        if self._displaying_masked_text:
            return []
        translation_text = "\n".join(
            self._translation_lines_for_control_mismatch()
        )
        if not translation_text.strip():
            return []
        source_text = "\n".join(self._source_lines_for_control_mismatch())
        return build_control_mismatch_selections(
            editor,
            source_text=source_text,
            translation_text=translation_text,
            highlight_side="translation",
            dark_theme=self._dark_theme,
        )

    def _japanese_problem_selections(self) -> list[QTextEdit.ExtraSelection]:
        editor = self.editor
        if editor is None:
            return []
        if self._displaying_masked_text:
            return []
        if not self._has_japanese_text_problem():
            return []
        tl_text = "\n".join(self._raw_lines if self._raw_lines else [""])
        return build_japanese_character_problem_selections(
            editor,
            tl_text,
            dark_theme=self._dark_theme,
        )

    def _sync_control_code_visibility(self, force: bool = False) -> None:
        if self.editor is None:
            self._displaying_masked_text = False
            self._masked_color_spans = []
            self._preview.setText(self._preview_text())
            self._refresh_source_hint_overlay()
            self._refresh_status()
            return
        show_raw = self._should_show_raw_codes()
        if self._pending_mouse_reveal:
            show_raw = False
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
        if self.editor is None:
            return []
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

    def _raw_font_scale_selections(self) -> list[QTextEdit.ExtraSelection]:
        editor = self.editor
        if editor is None:
            return []
        if self._displaying_masked_text:
            return []
        text = editor.toPlainText()
        if not text:
            return []
        base_point_size = editor.font().pointSizeF()
        if base_point_size <= 0:
            fallback_point_size = editor.font().pointSize()
            base_point_size = float(fallback_point_size if fallback_point_size > 0 else 10)

        selections: list[QTextEdit.ExtraSelection] = []
        span_start: Optional[int] = None
        span_scale = 1.0
        cursor_pos = 0

        for unit in parse_units_for_measure(text):
            token_text = unit.get("text")
            token = token_text if isinstance(token_text, str) else ""
            token_len = len(token)
            is_newline = bool(unit.get("is_newline"))

            if token_len == 0:
                continue
            if is_newline:
                if span_start is not None and cursor_pos > span_start:
                    selection = QTextEdit.ExtraSelection()
                    fmt = QTextCharFormat()
                    fmt.setFontPointSize(max(1.0, base_point_size * span_scale))
                    sel_cursor = QTextCursor(editor.document())
                    sel_cursor.setPosition(span_start)
                    sel_cursor.setPosition(cursor_pos, QTextCursor.MoveMode.KeepAnchor)
                    selection_any = cast(Any, selection)
                    selection_any.format = fmt
                    selection_any.cursor = sel_cursor
                    selections.append(selection)
                span_start = None
                span_scale = 1.0
                cursor_pos += token_len
                continue

            if token_len != 1:
                if span_start is not None and cursor_pos > span_start:
                    selection = QTextEdit.ExtraSelection()
                    fmt = QTextCharFormat()
                    fmt.setFontPointSize(max(1.0, base_point_size * span_scale))
                    sel_cursor = QTextCursor(editor.document())
                    sel_cursor.setPosition(span_start)
                    sel_cursor.setPosition(cursor_pos, QTextCursor.MoveMode.KeepAnchor)
                    selection_any = cast(Any, selection)
                    selection_any.format = fmt
                    selection_any.cursor = sel_cursor
                    selections.append(selection)
                span_start = None
                span_scale = 1.0
                cursor_pos += token_len
                continue

            raw_visible = unit.get("visible", 0.0)
            if isinstance(raw_visible, (int, float)):
                unit_scale = float(raw_visible)
            else:
                try:
                    unit_scale = float(raw_visible)
                except Exception:
                    unit_scale = 1.0
            unit_scale = max(0.1, unit_scale)

            if abs(unit_scale - 1.0) <= 0.01:
                if span_start is not None and cursor_pos > span_start:
                    selection = QTextEdit.ExtraSelection()
                    fmt = QTextCharFormat()
                    fmt.setFontPointSize(max(1.0, base_point_size * span_scale))
                    sel_cursor = QTextCursor(editor.document())
                    sel_cursor.setPosition(span_start)
                    sel_cursor.setPosition(cursor_pos, QTextCursor.MoveMode.KeepAnchor)
                    selection_any = cast(Any, selection)
                    selection_any.format = fmt
                    selection_any.cursor = sel_cursor
                    selections.append(selection)
                span_start = None
                span_scale = 1.0
                cursor_pos += token_len
                continue

            if span_start is None:
                span_start = cursor_pos
                span_scale = unit_scale
            elif abs(unit_scale - span_scale) > 0.01:
                if cursor_pos > span_start:
                    selection = QTextEdit.ExtraSelection()
                    fmt = QTextCharFormat()
                    fmt.setFontPointSize(max(1.0, base_point_size * span_scale))
                    sel_cursor = QTextCursor(editor.document())
                    sel_cursor.setPosition(span_start)
                    sel_cursor.setPosition(cursor_pos, QTextCursor.MoveMode.KeepAnchor)
                    selection_any = cast(Any, selection)
                    selection_any.format = fmt
                    selection_any.cursor = sel_cursor
                    selections.append(selection)
                span_start = cursor_pos
                span_scale = unit_scale
            cursor_pos += token_len

        if span_start is not None and cursor_pos > span_start:
            selection = QTextEdit.ExtraSelection()
            fmt = QTextCharFormat()
            fmt.setFontPointSize(max(1.0, base_point_size * span_scale))
            sel_cursor = QTextCursor(editor.document())
            sel_cursor.setPosition(span_start)
            sel_cursor.setPosition(cursor_pos, QTextCursor.MoveMode.KeepAnchor)
            selection_any = cast(Any, selection)
            selection_any.format = fmt
            selection_any.cursor = sel_cursor
            selections.append(selection)
        return selections

    def _current_lines(self) -> list[str]:
        if self.editor is None:
            return list(self._raw_lines if self._raw_lines else [""])
        if self._displaying_masked_text:
            return list(self._raw_lines)
        return split_lines_preserve_empty(self.editor.toPlainText())

    def _speaker_display_name(self) -> str:
        inferred_name = self._resolved_inferred_speaker_name()
        if self._uses_translation_storage():
            translated = ""
            if (
                self.segment.speaker_name != NO_SPEAKER_KEY
                and self.speaker_display_resolver is not None
            ):
                translated = self.speaker_display_resolver(
                    self.segment.speaker_name
                ).strip()
            if not translated and inferred_name and self.speaker_display_resolver is not None:
                translated = self.speaker_display_resolver(inferred_name).strip()
            if not translated and (self.segment.speaker_name != NO_SPEAKER_KEY or inferred_name):
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
        if not inferred_name:
            return NO_SPEAKER_KEY
        display_name = inferred_name
        if self.speaker_display_resolver is not None:
            resolved = self.speaker_display_resolver(inferred_name).strip()
            if resolved:
                display_name = resolved
        first_line = self._line1_inference_prefix_text().strip()

        if (
            self._line1_inference_is_forced()
            or (first_line and looks_like_name_line(first_line))
            or (display_name != inferred_name and looks_like_name_line(display_name))
        ):
            return f"{display_name} (line 1)"
        return NO_SPEAKER_KEY

    def _speaker_display_name_html(self) -> str:
        inferred_name = self._resolved_inferred_speaker_name()
        if self._uses_translation_storage():
            translated = ""
            if (
                self.segment.speaker_name != NO_SPEAKER_KEY
                and self.speaker_display_resolver is not None
            ):
                translated = self.speaker_display_resolver(
                    self.segment.speaker_name
                ).strip()
            if not translated and inferred_name and self.speaker_display_resolver is not None:
                translated = self.speaker_display_resolver(inferred_name).strip()
            if not translated and (self.segment.speaker_name != NO_SPEAKER_KEY or inferred_name):
                translated = self.segment.translation_speaker.strip()
            if translated:
                if self.speaker_display_html_resolver is not None:
                    rendered = self.speaker_display_html_resolver(translated).strip()
                    if rendered:
                        return rendered
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

        if not inferred_name:
            return html.escape(NO_SPEAKER_KEY)
        display_name = inferred_name
        display_html = html.escape(inferred_name)
        if self.speaker_display_resolver is not None:
            resolved = self.speaker_display_resolver(inferred_name).strip()
            if resolved:
                display_name = resolved
                display_html = html.escape(resolved)
        if self.speaker_display_html_resolver is not None:
            rendered = self.speaker_display_html_resolver(inferred_name).strip()
            if rendered:
                display_html = rendered
        first_line = self._line1_inference_prefix_text().strip()

        if (
            self._line1_inference_is_forced()
            or (first_line and looks_like_name_line(first_line))
            or (display_name != inferred_name and looks_like_name_line(display_name))
        ):
            return f"{display_html} (line 1)"
        return html.escape(NO_SPEAKER_KEY)

    def _refresh_meta_label(self) -> None:
        if self.actor_mode:
            if self._is_tyrano_tag_text_block():
                view_text = "EN script text" if self.translator_mode else "JP script text"
                meta_html = f"Script text | View: {html.escape(view_text)}"
                self.meta_label.setTextFormat(Qt.TextFormat.RichText)
                self.meta_label.setText(meta_html)
                return
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

        if self._is_map_display_name_block():
            view_text = "EN displayName" if self._uses_translation_storage() else "Map displayName"
            meta_html = f"Type: Map Display Name | View: {html.escape(view_text)}"
            self.meta_label.setTextFormat(Qt.TextFormat.RichText)
            self.meta_label.setText(meta_html)
            return

        if self._is_choice_block():
            lines = self._current_lines()
            option_count = len(lines) if lines else 0
            option_label = "option" if option_count == 1 else "options"
            view_text = "EN choices" if self.translator_mode else "JP choices"
            meta_html = (
                f"Type: Choice | "
                f"{option_count} {option_label} | "
                f"View: {html.escape(view_text)}"
            )
            self.meta_label.setTextFormat(Qt.TextFormat.RichText)
            self.meta_label.setText(meta_html)
            return

        if self._is_tyrano_tag_text_block():
            view_text = "EN tag text" if self.translator_mode else "JP tag text"
            meta_html = f"Tag text | View: {html.escape(view_text)}"
            self.meta_label.setTextFormat(Qt.TextFormat.RichText)
            self.meta_label.setText(meta_html)
            return

        if self._is_tyrano_dialogue_block():
            view_text = "EN dialogue" if self.translator_mode else "JP dialogue"
            speaker_html = self._speaker_display_name_html()
            meta_html = (
                f"Speaker: {speaker_html} | "
                f"View: {html.escape(view_text)}"
            )
            self.meta_label.setTextFormat(Qt.TextFormat.RichText)
            self.meta_label.setText(meta_html)
            return

        speaker_html = self._speaker_display_name_html()
        face_text = self.segment.face_name or "(none)"
        thought_type_suffix = " | Type: Thought" if self._is_thought_block() else ""
        meta_html = (
            f"Speaker: {speaker_html} | "
            f"Face: {html.escape(face_text)} [{self.segment.face_index}] | "
            f"BG: {html.escape(str(self.segment.background))} | "
            f"Pos: {html.escape(str(self.segment.position))}"
            f"{thought_type_suffix}"
        )
        self.meta_label.setTextFormat(Qt.TextFormat.RichText)
        self.meta_label.setText(meta_html)

    def _apply_overflow_highlighting(self) -> None:
        if self.editor is None:
            return
        selections: list[QTextEdit.ExtraSelection] = []
        masked_overlay_active = self._should_show_masked_preview_overlay()
        if self._displaying_masked_text:
            if not masked_overlay_active:
                selections.extend(self._masked_color_selections())
        else:
            selections.extend(self._raw_font_scale_selections())
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
        selections.extend(self._japanese_problem_selections())
        selections.extend(self._control_mismatch_selections())
        self.editor.setExtraSelections(selections)

    def _set_status_text(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setToolTip(text)

    def _refresh_status(self) -> None:
        lines = self._current_lines()
        if self.editor is None:
            self._preview.setText(self._preview_text())
        self._apply_editor_width()
        storage_lines = self._storage_lines_from_editor_lines(lines)
        max_rows_budget = float(max(1, self.max_lines))
        control_mismatch_problem = self._has_control_mismatch_problem()
        japanese_text_problem = self._has_japanese_text_problem()
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
            self._set_status_text(
                f"{len(lines)} {line_label}, {char_count} {char_label}")
            self._has_warning = False
            self.status_label.setStyleSheet(f"color: {self._status_ok_color};")
            self.move_overflow_button.setVisible(False)
            self.move_overflow_button.setEnabled(False)
            if self._uses_translation_storage():
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
            if japanese_text_problem:
                text += ", contains Japanese"
            self._set_status_text(text)
            has_warning = control_mismatch_problem or japanese_text_problem
            self._has_warning = has_warning
            if has_warning:
                self.status_label.setStyleSheet(
                    f"color: {self._status_warn_color}; font-weight: 600;"
                )
            else:
                self.status_label.setStyleSheet(f"color: {self._status_ok_color};")
            self.move_overflow_button.setVisible(False)
            self.move_overflow_button.setEnabled(False)
            if self._uses_translation_storage():
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
            self._apply_editor_style(has_warning)
            self._refresh_block_style()
            self._refresh_source_hint_overlay()
            return

        width_chars = self._width_chars()
        line_char_counts = [visible_length(line) for line in lines]

        over_width = []
        for idx, line in enumerate(lines, start=1):
            if visible_length(line) > width_chars:
                over_width.append(idx)

        line_label = "line" if len(lines) == 1 else "lines"
        text = f"{len(lines)} {line_label}"
        if line_char_counts:
            char_count_preview = ", ".join(
                str(count) for count in line_char_counts[:6]
            )
            if len(line_char_counts) > 6:
                char_count_preview += "..."
            text += f", chars: {char_count_preview}"
        if over_width:
            over_width_label = "line" if len(over_width) == 1 else "lines"
            text += f", over width {over_width_label}: {', '.join(str(i) for i in over_width[:6])}"
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
            text += f", rows {used_rows:.2f}/{int(max_rows_budget)}"
            if self._line1_inference_active() and moved_storage_lines:
                text += " (+line1)"
            if self.allow_structural_actions:
                text += f", move {overflow_count} down"
        if control_mismatch_problem:
            text += ", control mismatch"
        if japanese_text_problem:
            text += ", contains Japanese"

        self._set_status_text(text)
        has_warning = (
            bool(over_width)
            or max_lines_over
            or control_mismatch_problem
            or japanese_text_problem
        )
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
        if self._uses_translation_storage():
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
            allow_comma_endings=self.smart_collapse_allow_comma_endings,
            allow_colon_triplet_endings=self.smart_collapse_allow_colon_triplet_endings,
            allow_ellipsis_lowercase_continuation=self.smart_collapse_ellipsis_lowercase_rule,
            collapse_if_no_punctuation=self.smart_collapse_collapse_if_no_punctuation,
            min_soft_ratio=self.smart_collapse_min_soft_ratio,
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
        if self._uses_translation_storage():
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
            allow_comma_endings=self.smart_collapse_allow_comma_endings,
            allow_colon_triplet_endings=self.smart_collapse_allow_colon_triplet_endings,
            allow_ellipsis_lowercase_continuation=self.smart_collapse_ellipsis_lowercase_rule,
            collapse_if_no_punctuation=self.smart_collapse_collapse_if_no_punctuation,
            min_soft_ratio=self.smart_collapse_min_soft_ratio,
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
        if self._uses_translation_storage():
            self.segment.translation_lines = list(storage_lines)
        else:
            self.segment.lines = list(storage_lines)
            self.segment.source_lines = list(storage_lines)
        self._refresh_meta_label()
        self._refresh_status()
        self.text_changed.emit(self.segment.uid, list(storage_lines))
