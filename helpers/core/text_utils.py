from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import wrap_dialogs as _wrap_dialogs
except Exception:
    _wrap_dialogs = None


NATURAL_KEY_RE = re.compile(r"(\d+)")
CONTROL_TOKEN_RE = re.compile(
    r"""
    \\[A-Za-z]+\d*<[^>]*>        |
    \\[A-Za-z]+\d*\[[^\]]*\]     |
    \\[\.\!\|\{\}\^]             |
    \\[ntr]
    """,
    re.VERBOSE,
)
SIMILARITY_PUNCT_RE = re.compile(
    r"[\s\.,!?\"'`~:;()\[\]{}<>\/\\\-_|\+\*&\^%$#@=。、，．？！：；「」『』（）［］｛｝【】〈〉《》…・～〜]+"
)


def visible_length(text: str) -> int:
    if _wrap_dialogs is not None:
        fn = getattr(_wrap_dialogs, "visible_length", None)
        if callable(fn):
            try:
                value = fn(text)
                if isinstance(value, int):
                    return max(0, value)
            except Exception:
                pass
    return len(text)


def looks_like_name_line(line: str) -> bool:
    if _wrap_dialogs is not None:
        fn = getattr(_wrap_dialogs, "is_name_line", None)
        if callable(fn):
            try:
                return bool(fn(line))
            except Exception:
                pass
    return False


def parse_units_for_measure(text: str) -> list[dict[str, Any]]:
    if _wrap_dialogs is not None:
        fn = getattr(_wrap_dialogs, "parse_units", None)
        if callable(fn):
            try:
                raw_units = fn(text)
                if isinstance(raw_units, list):
                    normalized: list[dict[str, Any]] = []
                    for unit in raw_units:
                        if isinstance(unit, dict):
                            normalized.append(unit)
                    if normalized:
                        return normalized
            except Exception:
                pass
    units: list[dict[str, Any]] = []
    for ch in text:
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


def wrap_text_to_width(text: str, width: int) -> list[str]:
    safe_width = max(1, width)
    if _wrap_dialogs is not None:
        fn = getattr(_wrap_dialogs, "wrap_text", None)
        if callable(fn):
            try:
                wrapped = fn(text, safe_width)
                if isinstance(wrapped, list):
                    normalized: list[str] = []
                    for item in wrapped:
                        if isinstance(item, str):
                            normalized.append(item)
                        else:
                            normalized.append(str(item))
                    if normalized:
                        return normalized
            except Exception:
                pass
    lines = split_lines_preserve_empty(text)
    if not lines:
        return [""]
    return lines


def wrap_lines_keep_breaks(lines: list[str], width: int) -> list[str]:
    if not lines:
        return [""]
    wrapped: list[str] = []
    for line in lines:
        wrapped_line = wrap_text_to_width(line, width)
        wrapped.extend(wrapped_line or [""])
    return wrapped or [""]


def collapse_lines_force(lines: list[str], width: int) -> list[str]:
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
            wrapped.extend(wrap_text_to_width(merged, safe_width))
            paragraph = []
        if not wrapped or wrapped[-1] != "":
            wrapped.append("")

    if paragraph:
        merged = " ".join(paragraph)
        wrapped.extend(wrap_text_to_width(merged, safe_width))

    return wrapped or [""]


def smart_collapse_lines_space_efficient(lines: list[str], width: int) -> list[str]:
    safe_width = max(1, width)
    if _wrap_dialogs is not None:
        fn = getattr(_wrap_dialogs, "wrap_lines", None)
        if callable(fn):
            try:
                wrapped_result = fn(lines, safe_width)
                if isinstance(wrapped_result, list):
                    normalized: list[str] = []
                    for item in wrapped_result:
                        if isinstance(item, str):
                            normalized.append(item)
                        else:
                            normalized.append(str(item))
                    if normalized:
                        return normalized
            except Exception:
                pass
    return collapse_lines_force(lines, safe_width)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
