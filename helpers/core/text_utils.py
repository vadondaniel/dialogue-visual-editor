from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

NATURAL_KEY_RE = re.compile(r"(\d+)")
CONTROL_TOKEN_RE = re.compile(
    r"""
    \\[A-Za-z]+\d*<[^>]*>        |
    \\[A-Za-z]+\d*\[[^\]]*\]     |
    \\[A-Za-z]+\d*               |
    \\[^A-Za-z0-9\s]
    """,
    re.VERBOSE,
)
CONTROL_CODE_WORD_CASE_RE = re.compile(r"\\([A-Za-z]+)(?=[\[<])")
SIMILARITY_PUNCT_RE = re.compile(
    r"[\s\.,!?\"'`~:;()\[\]{}<>\/\\\-_|\+\*&\^%$#@=。、，．？！：；「」『』（）［］｛｝【】〈〉《》…・～〜]+"
)
NAME_MACRO_LINE_RE = re.compile(
    r"^\s*(?:\\[Cc]\[\d+\]\s*)*\\N\[\d+\](?:\s*(?:\\[Cc]\[\d+\])\s*)*(?:[:：])?\s*$"
)
SENTENCE_ENDINGS = set(
    ".!?！？。♪〜~…♡"
    "()[]{}"
    "\"'“”‘’"
    "（）［］｛｝"
    "「」『』【】〈〉《》〔〕"
)
SOFT_SENTENCE_ENDINGS = set(".!?！？。♪〜~…♡")
CAPITAL_START_FORCE_BREAK = False
NAME_CONNECTOR_WORDS = {
    "of",
    "the",
    "and",
    "to",
    "for",
    "in",
    "on",
    "at",
    "de",
    "la",
    "da",
    "di",
    "van",
    "von",
    "der",
}


def visible_length(text: str) -> int:
    visible = 0
    for unit in parse_units_for_measure(text):
        if unit.get("is_newline"):
            continue
        raw_visible = unit.get("visible", 0)
        if isinstance(raw_visible, int) and raw_visible > 0:
            visible += raw_visible
    return visible


def looks_like_name_line(line: str) -> bool:
    if not line:
        return False
    if NAME_MACRO_LINE_RE.match(line):
        return True

    cleaned = CONTROL_TOKEN_RE.sub("", line).replace("\u3000", " ").strip()
    if not cleaned:
        return False

    cleaned = cleaned.rstrip("：:")
    if not cleaned:
        return False
    if len(cleaned) > 40:
        return False
    if any(ch in cleaned for ch in ".!?！？。…"):
        return False
    if not any(ch.isalpha() for ch in cleaned):
        return False

    words = [part for part in cleaned.split() if part]
    if not words or len(words) > 4:
        return False

    for word in words:
        core = word.strip("'’.-")
        if not core:
            continue
        if len(core) > 20:
            return False
        if core.lower() in NAME_CONNECTOR_WORDS:
            continue
        first = core[0]
        if first.isalpha() and not first.isupper():
            return False
        for ch in core:
            if ch.isalnum() or ch in "'’-.":
                continue
            return False
    return True


def parse_units_for_measure(text: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    cursor = 0
    for match in CONTROL_TOKEN_RE.finditer(text):
        if match.start() > cursor:
            for ch in text[cursor:match.start()]:
                units.append(
                    {
                        "text": ch,
                        "visible": 0 if ch == "\n" else 1,
                        "is_newline": ch == "\n",
                    }
                )
        token = match.group(0)
        units.append({"text": token, "visible": 0, "is_newline": False})
        cursor = match.end()
    if cursor < len(text):
        for ch in text[cursor:]:
            units.append(
                {
                    "text": ch,
                    "visible": 0 if ch == "\n" else 1,
                    "is_newline": ch == "\n",
                }
            )
    return units


def first_overflow_char_index(text: str, width: int) -> Optional[int]:
    if width <= 0:
        return 0 if text else None

    visible = 0
    char_index = 0
    for unit in parse_units_for_measure(text):
        token_text = unit.get("text")
        token = token_text if isinstance(token_text, str) else ""
        token_len = len(token)

        if unit.get("is_newline"):
            continue

        raw_visible = unit.get("visible", 0)
        if not isinstance(raw_visible, int):
            try:
                raw_visible = int(raw_visible)
            except Exception:
                raw_visible = 0
        unit_visible = max(0, raw_visible)

        if unit_visible == 0:
            char_index += token_len
            continue

        if visible + unit_visible > width:
            return char_index

        visible += unit_visible
        char_index += token_len

    return None


def natural_sort_key(text: str) -> list[Any]:
    parts = NATURAL_KEY_RE.split(text.lower())
    key: list[Any] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part)
    return key


def strip_control_tokens(text: str) -> str:
    if not text:
        return ""
    return CONTROL_TOKEN_RE.sub("", text)


def normalize_control_code_word_case(text: str) -> tuple[str, int]:
    if not text:
        return "", 0

    replacements = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal replacements
        word = match.group(1)
        upper_word = word.upper()
        if word == upper_word:
            return match.group(0)
        replacements += 1
        return f"\\{upper_word}"

    normalized = CONTROL_CODE_WORD_CASE_RE.sub(_replace, text)
    return normalized, replacements


def similarity_signature(text: str) -> str:
    cleaned = strip_control_tokens(text).lower().replace("\u3000", " ")
    return SIMILARITY_PUNCT_RE.sub("", cleaned)


def fuzzy_compare_text(text: str) -> str:
    base = strip_control_tokens(text).lower().replace("\u3000", " ")
    spaced = SIMILARITY_PUNCT_RE.sub(" ", base)
    return " ".join(spaced.split())


def preview_text(text: str, limit: int = 66) -> str:
    compact = (text or "").replace("\r", "\\r").replace(
        "\n", "\\n").replace("\t", "\\t")
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)] + "..."


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def is_command_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and "code" in entry and "parameters" in entry


def first_parameter_text(entry: dict[str, Any], default: str = "") -> str:
    params = entry.get("parameters")
    if isinstance(params, list) and params:
        value = params[0]
        if isinstance(value, str):
            return value
    return default


def split_lines_preserve_empty(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines:
        return [""]
    return lines


def chunk_lines(lines: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [lines or [""]]
    if not lines:
        return [[""]]
    chunks = [lines[i: i + size] for i in range(0, len(lines), size)]
    return chunks or [[""]]


def wrap_text_word_aware(text: str, width: int) -> list[str]:
    safe_width = max(1, width)
    return _wrap_text_word_aware_fallback(text, safe_width)


def _unit_visible_value(unit: dict[str, Any]) -> int:
    raw_visible = unit.get("visible", 0)
    if isinstance(raw_visible, int):
        return max(0, raw_visible)
    try:
        return max(0, int(raw_visible))
    except Exception:
        return 0


def _unit_is_space(unit: dict[str, Any]) -> bool:
    if _unit_visible_value(unit) <= 0:
        return False
    token_text = unit.get("text")
    token = token_text if isinstance(token_text, str) else ""
    return token in (" ", "\t", "\u3000")


def _units_visible_length(units: list[dict[str, Any]]) -> int:
    return sum(_unit_visible_value(unit) for unit in units)


def _find_last_visible_space_idx(units: list[dict[str, Any]]) -> Optional[int]:
    idx: Optional[int] = None
    for pos, unit in enumerate(units, start=1):
        if _unit_is_space(unit):
            idx = pos
    return idx


def _units_to_text(units: list[dict[str, Any]]) -> str:
    text_parts: list[str] = []
    for unit in units:
        token_text = unit.get("text")
        text_parts.append(token_text if isinstance(token_text, str) else "")
    return "".join(text_parts)


def _has_visible_nonspace_characters(text: str) -> bool:
    for unit in parse_units_for_measure(text):
        if unit.get("is_newline"):
            continue
        if _unit_visible_value(unit) <= 0:
            continue
        if _unit_is_space(unit):
            continue
        return True
    return False


def _last_visible_nonspace_character(text: str) -> Optional[str]:
    units = parse_units_for_measure(text)
    for unit in reversed(units):
        if unit.get("is_newline"):
            continue
        if _unit_visible_value(unit) <= 0:
            continue
        if _unit_is_space(unit):
            continue
        token_text = unit.get("text")
        token = token_text if isinstance(token_text, str) else ""
        if token:
            return token
    return None


def _starts_with_capital_visible_letter(text: str) -> bool:
    for unit in parse_units_for_measure(text):
        if unit.get("is_newline"):
            break
        if _unit_visible_value(unit) <= 0:
            continue
        if _unit_is_space(unit):
            continue
        token_text = unit.get("text")
        token = token_text if isinstance(token_text, str) else ""
        if len(token) == 1 and token.isalpha() and token.isupper():
            return True
        return False
    return False


def _should_force_break_after_line(line: str, line_width: int) -> bool:
    if not _has_visible_nonspace_characters(line):
        return True
    last_char = _last_visible_nonspace_character(line)
    if last_char is None:
        return False
    if last_char not in SENTENCE_ENDINGS:
        return False
    if last_char not in SOFT_SENTENCE_ENDINGS:
        return True
    return visible_length(line) >= (line_width / 2)


def _build_smart_collapse_body_text(lines: list[str], line_width: int) -> str:
    parts: list[str] = []
    previous_line: Optional[str] = None
    for line in lines:
        if previous_line is not None:
            joiner = "\n" if _should_force_break_after_line(previous_line, line_width) else " "
            if (
                joiner == " "
                and CAPITAL_START_FORCE_BREAK
                and _starts_with_capital_visible_letter(line)
                and _last_visible_nonspace_character(previous_line) not in SENTENCE_ENDINGS
            ):
                joiner = "\n"
            parts.append(joiner)
        parts.append(line)
        previous_line = line
    return "".join(parts)


def _wrap_text_word_aware_fallback(text: str, width: int) -> list[str]:
    units = parse_units_for_measure(text)
    if not units:
        return [""]

    lines: list[str] = []
    current_units: list[dict[str, Any]] = []
    current_visible = 0
    last_space_idx: Optional[int] = None

    def flush_current() -> None:
        nonlocal current_units, current_visible, last_space_idx
        line_text = _units_to_text(current_units).rstrip(" \t\u3000")
        lines.append(line_text)
        current_units = []
        current_visible = 0
        last_space_idx = None

    for unit in units:
        if unit.get("is_newline"):
            flush_current()
            continue

        unit_visible = _unit_visible_value(unit)
        unit_is_space = _unit_is_space(unit)
        reprocess = True
        while reprocess:
            reprocess = False
            if unit_visible == 0:
                current_units.append(unit)
                continue

            if current_visible + unit_visible <= width:
                current_units.append(unit)
                current_visible += unit_visible
                if unit_is_space:
                    last_space_idx = len(current_units)
                continue

            if not current_units:
                current_units.append(unit)
                current_visible += unit_visible
                if unit_is_space:
                    last_space_idx = len(current_units)
                continue

            if last_space_idx is not None:
                line_units = current_units[:last_space_idx]
                remainder_units = current_units[last_space_idx:]
                while remainder_units and _unit_is_space(remainder_units[0]):
                    remainder_units.pop(0)
                line_text = _units_to_text(line_units).rstrip(" \t\u3000")
                lines.append(line_text)
                current_units = remainder_units
                current_visible = _units_visible_length(current_units)
                last_space_idx = _find_last_visible_space_idx(current_units)
            else:
                line_text = _units_to_text(current_units).rstrip(" \t\u3000")
                lines.append(line_text)
                current_units = []
                current_visible = 0
                last_space_idx = None
            reprocess = True

    if current_units:
        lines.append(_units_to_text(current_units).rstrip(" \t\u3000"))

    return lines or [""]


def wrap_lines_hard_break(lines: list[str], width: int) -> list[str]:
    if not lines:
        return [""]
    wrapped: list[str] = []
    for line in lines:
        wrapped_line = _wrap_text_hard_break(line, width)
        wrapped.extend(wrapped_line or [""])
    return wrapped or [""]


def _wrap_text_hard_break(text: str, width: int) -> list[str]:
    safe_width = max(1, width)
    units = parse_units_for_measure(text)
    if not units:
        return [""]

    lines: list[str] = []
    current_units: list[dict[str, Any]] = []
    current_visible = 0

    def flush_current() -> None:
        nonlocal current_units, current_visible
        lines.append(_units_to_text(current_units).rstrip(" \t\u3000"))
        current_units = []
        current_visible = 0

    for unit in units:
        if unit.get("is_newline"):
            flush_current()
            continue

        unit_visible = _unit_visible_value(unit)
        if unit_visible == 0:
            current_units.append(unit)
            continue

        if _unit_is_space(unit):
            if current_visible == 0:
                continue
            if current_visible + unit_visible >= safe_width:
                continue

        if current_visible + unit_visible > safe_width and current_units:
            flush_current()
            if _unit_is_space(unit):
                continue

        current_units.append(unit)
        current_visible += unit_visible

    if current_units:
        flush_current()

    return lines or [""]


def collapse_lines_join_paragraphs(lines: list[str], width: int) -> list[str]:
    safe_width = max(1, width)

    if not lines:
        return [""]

    wrapped: list[str] = []
    paragraph: list[str] = []
    for line in lines:
        if line.strip():
            paragraph.append(line.strip())
            continue
        if paragraph:
            merged = " ".join(paragraph)
            wrapped.extend(wrap_text_word_aware(merged, safe_width))
            paragraph = []
        if not wrapped or wrapped[-1] != "":
            wrapped.append("")

    if paragraph:
        merged = " ".join(paragraph)
        wrapped.extend(wrap_text_word_aware(merged, safe_width))

    return wrapped or [""]


def smart_collapse_lines(
    lines: list[str],
    width: int,
    *,
    infer_name_from_first_line: bool = False,
) -> list[str]:
    safe_width = max(1, width)
    if not lines:
        return [""]

    body_lines = list(lines)
    result_prefix: list[str] = []
    if infer_name_from_first_line and len(body_lines) > 1:
        first_line = body_lines[0].strip()
        if first_line and looks_like_name_line(first_line):
            result_prefix.append(first_line)
            body_lines = body_lines[1:]

    if not body_lines:
        return result_prefix or [""]

    body_text = _build_smart_collapse_body_text(body_lines, safe_width)
    wrapped_body = wrap_text_word_aware(body_text, safe_width)
    return (result_prefix + wrapped_body) or [""]


def wrap_text_to_width(text: str, width: int) -> list[str]:
    return wrap_text_word_aware(text, width)


def wrap_lines_keep_breaks(lines: list[str], width: int) -> list[str]:
    return wrap_lines_hard_break(lines, width)


def collapse_lines_force(lines: list[str], width: int) -> list[str]:
    return collapse_lines_join_paragraphs(lines, width)


def smart_collapse_lines_space_efficient(
    lines: list[str],
    width: int,
    *,
    infer_name_from_first_line: bool = False,
) -> list[str]:
    return smart_collapse_lines(
        lines,
        width,
        infer_name_from_first_line=infer_name_from_first_line,
    )


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
