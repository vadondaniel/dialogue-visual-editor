from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import CommandBundle, CommandToken, DialogueSegment, FileSession
from .script_message_utils import (
    parse_game_message_call,
    parse_game_message_templated_call,
    parse_game_message_set_background_call,
    parse_game_message_set_face_image_call,
    parse_game_message_set_position_type_call,
)
from .text_utils import first_parameter_text, is_command_entry, split_lines_preserve_empty


def _name_index_spec_for_file(path_name: str) -> tuple[str, str, str, str, tuple[str, ...]] | None:
    lowered = path_name.lower()
    if lowered == "actors.json":
        return ("actor", "A", "Actor", "actor", ("name", "nickname", "profile"))
    if lowered == "classes.json":
        return ("class", "C", "Class", "class", ("name",))
    if lowered == "items.json":
        return ("item", "I", "Item", "item", ("name", "description"))
    if lowered == "armors.json":
        return ("armor", "R", "Armor", "armor", ("name", "description"))
    if lowered == "enemies.json":
        return ("enemy", "E", "Enemy", "enemy", ("name",))
    if lowered == "weapons.json":
        return ("weapon", "W", "Weapon", "weapon", ("name", "description"))
    if lowered == "mapinfos.json":
        return ("mapinfo", "M", "Map", "map", ("name",))
    if lowered == "skills.json":
        return ("skill", "K", "Skill", "skill", ("name", "description", "message1", "message2"))
    if lowered == "states.json":
        return ("state", "S", "State", "state", ("name", "message1", "message2", "message3", "message4"))
    if lowered == "tilesets.json":
        return ("tileset", "T", "Tileset", "tileset", ("name",))
    if lowered == "troops.json":
        return ("troop", "P", "Troop", "troop", ("name",))
    return None


_SYSTEM_TOP_LEVEL_STRING_FIELDS: tuple[str, ...] = (
    "gameTitle", "currencyUnit")
_SYSTEM_INDEXED_ARRAY_FIELDS: tuple[str, ...] = (
    "elements",
    "skillTypes",
    "weaponTypes",
    "armorTypes",
    "equipTypes",
    "switches",
    "variables",
)
_SYSTEM_TERMS_ARRAY_FIELDS: tuple[str, ...] = ("basic", "commands", "params")

_PLUGINS_JS_MARKER_KEY = "__dve_plugins_js_marker__"
_PLUGINS_JS_MARKER_VALUE = "plugins_js"
_PLUGINS_JS_PREFIX_KEY = "__dve_plugins_js_prefix__"
_PLUGINS_JS_SUFFIX_KEY = "__dve_plugins_js_suffix__"
_PLUGINS_JS_ARRAY_KEY = "__dve_plugins_js_array__"
_PLUGINS_JS_DEFAULT_PREFIX = "var $plugins =\n"
_PLUGINS_JS_DEFAULT_SUFFIX = ";\n"
_TYRANO_SCRIPT_MARKER_KEY = "__dve_tyrano_script_marker__"
_TYRANO_SCRIPT_MARKER_VALUE = "tyrano_script"
_TYRANO_SCRIPT_NEWLINE_KEY = "__dve_tyrano_script_newline__"
_TYRANO_SCRIPT_HAS_TRAILING_NEWLINE_KEY = "__dve_tyrano_script_has_trailing_newline__"
_TYRANO_SCRIPT_CHUNKS_KEY = "__dve_tyrano_script_chunks__"
_TYRANO_CONFIG_MARKER_KEY = "__dve_tyrano_config_marker__"
_TYRANO_CONFIG_MARKER_VALUE = "tyrano_config"
_TYRANO_CONFIG_NEWLINE_KEY = "__dve_tyrano_config_newline__"
_TYRANO_CONFIG_HAS_TRAILING_NEWLINE_KEY = "__dve_tyrano_config_has_trailing_newline__"
_TYRANO_CONFIG_LINES_KEY = "__dve_tyrano_config_lines__"
_TYRANO_CONFIG_TITLE_LINE_INDEX_KEY = "__dve_tyrano_config_title_line_index__"
_TYRANO_CONFIG_TITLE_SPAN_KEY = "__dve_tyrano_config_title_span__"
_TYRANO_CONFIG_TITLE_QUOTE_KEY = "__dve_tyrano_config_title_quote__"
_MAP_FILE_NAME_RE = re.compile(r"^map\d+\.json$", re.IGNORECASE)
_TYRANO_PAGE_BREAK_TAG_RE = re.compile(r"\[\s*p(?:\s+[^\]]*)?\s*\]", re.IGNORECASE)
_TYRANO_INLINE_LINE_BREAK_TAG_RE = re.compile(r"\[\s*r\s*\]", re.IGNORECASE)
_TYRANO_TRAILING_DIALOGUE_MARKERS_RE = re.compile(
    r"(?:\s*\[\s*(?:p|r)\s*\]\s*)+$",
    re.IGNORECASE,
)
_TYRANO_ISCRIPT_START_RE = re.compile(r"^\[\s*iscript(?:\s+[^\]]*)?\s*\]$", re.IGNORECASE)
_TYRANO_ISCRIPT_END_RE = re.compile(r"^\[\s*endscript(?:\s+[^\]]*)?\s*\]$", re.IGNORECASE)
_TYRANO_SCRIPT_ASSIGNMENT_PREFIX_RE = re.compile(r"\b(?P<lhs>[A-Za-z_$][\w$.]*)\s*=\s*")
_TYRANO_SCRIPT_OBJECT_PROPERTY_PREFIX_RE = re.compile(
    r"(?P<key>[A-Za-z_$][\w$]*|\"[^\"]+\"|'[^']+')\s*:\s*"
)
_TYRANO_JS_OBJECT_OWNER_START_RE = re.compile(
    r"(?P<owner>[A-Za-z_$][\w$]*(?:\[[^\]]+\])?)\s*=\s*\{"
)
_TYRANO_JS_TRANSLATABLE_OBJECT_KEYS: set[str] = {
    "name",
    "fullname",
    "id",
}
_TYRANO_JS_TRANSLATABLE_ASSIGNMENT_SUFFIXES: tuple[str, ...] = ()
_TYRANO_END_LIST_DECL_RE = re.compile(r"\bend_list\b\s*=", re.IGNORECASE)
_NOTE_JAPANESE_CHAR_RE = re.compile(
    r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF"
    r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF66-\uFF9F]"
)
_PLUGIN_ARG_NUMBER_RE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$"
)
_PLUGIN_ARG_HEX_COLOR_RE = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)
_PLUGIN_ARG_LITERAL_WORDS: set[str] = {
    "true",
    "false",
    "on",
    "off",
    "none",
    "null",
    "nil",
}
_PLUGIN_ARG_ALIGNMENT_WORDS: set[str] = {
    "left",
    "right",
    "center",
    "middle",
    "top",
    "bottom",
}


def is_plugins_js_path(path: Path) -> bool:
    return path.name.strip().lower() == "plugins.js"


def is_tyrano_script_path(path: Path) -> bool:
    return path.suffix.strip().lower() == ".ks"


def is_tyrano_js_path(path: Path) -> bool:
    return path.suffix.strip().lower() == ".js" and not is_plugins_js_path(path)


def is_tyrano_config_path(path: Path) -> bool:
    return path.name.strip().lower() == "config.tjs"


def _find_matching_bracket_end(source: str, start_index: int) -> int | None:
    if start_index < 0 or start_index >= len(source) or source[start_index] != "[":
        return None
    depth = 0
    in_string = False
    string_quote = ""
    escaping = False
    for idx in range(start_index, len(source)):
        char = source[idx]
        if in_string:
            if escaping:
                escaping = False
                continue
            if char == "\\":
                escaping = True
                continue
            if char == string_quote:
                in_string = False
            continue
        if char == '"' or char == "'":
            in_string = True
            string_quote = char
            continue
        if char == "[":
            depth += 1
            continue
        if char == "]":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _parse_plugins_js_source(source: str) -> dict[str, Any]:
    marker_index = source.find("$plugins")
    if marker_index < 0:
        raise ValueError("plugins.js does not contain a $plugins assignment.")
    array_start = source.find("[", marker_index)
    if array_start < 0:
        raise ValueError("plugins.js does not contain a plugin array.")
    array_end = _find_matching_bracket_end(source, array_start)
    if array_end is None:
        raise ValueError("plugins.js contains an unmatched plugin array bracket.")

    array_payload = source[array_start: array_end + 1]
    plugin_array = json.loads(array_payload)
    if not isinstance(plugin_array, list):
        raise ValueError("plugins.js plugin payload is not a JSON array.")

    return {
        _PLUGINS_JS_MARKER_KEY: _PLUGINS_JS_MARKER_VALUE,
        _PLUGINS_JS_PREFIX_KEY: source[:array_start],
        _PLUGINS_JS_SUFFIX_KEY: source[array_end + 1:],
        _PLUGINS_JS_ARRAY_KEY: plugin_array,
    }


def load_plugins_js_file(path: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    return _parse_plugins_js_source(source)


def is_plugins_js_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    marker = data.get(_PLUGINS_JS_MARKER_KEY)
    if marker != _PLUGINS_JS_MARKER_VALUE:
        return False
    return isinstance(data.get(_PLUGINS_JS_ARRAY_KEY), list)


def plugins_js_source_from_data(data: Any) -> str:
    if not is_plugins_js_data(data):
        raise ValueError("Payload is not recognized plugins.js structured data.")
    wrapper = data
    prefix_raw = wrapper.get(_PLUGINS_JS_PREFIX_KEY)
    suffix_raw = wrapper.get(_PLUGINS_JS_SUFFIX_KEY)
    array_raw = wrapper.get(_PLUGINS_JS_ARRAY_KEY)
    prefix = prefix_raw if isinstance(
        prefix_raw, str) else _PLUGINS_JS_DEFAULT_PREFIX
    suffix = suffix_raw if isinstance(
        suffix_raw, str) else _PLUGINS_JS_DEFAULT_SUFFIX
    plugin_array = array_raw if isinstance(array_raw, list) else []
    array_payload = json.dumps(plugin_array, ensure_ascii=False, indent=2)
    return f"{prefix}{array_payload}{suffix}"


def _read_text_file_with_fallback_encodings(path: Path) -> str:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise ValueError(f"Failed to decode text file: {path}")


def _is_tyrano_dialogue_block_start(line: str) -> bool:
    lowered = line.strip().lower()
    return lowered.startswith("[tb_start_text")


def _is_tyrano_dialogue_block_end(line: str) -> bool:
    lowered = line.strip().lower()
    return lowered.startswith("[_tb_end_text")


def _is_tyrano_dialogue_text_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("["):
        closing_index = stripped.find("]")
        if closing_index <= 1:
            return False
        bracket_payload = stripped[1:closing_index].strip()
        if not bracket_payload:
            return False
        # Tag-style prefixes such as `[if exp=...]`, `[emb exp=...]` and
        # `[chara_* ...]` are control commands, not dialogue text.
        if (" " in bracket_payload) or ("=" in bracket_payload):
            return False
        remainder = stripped[closing_index + 1:].strip()
        # Non-ASCII bracket tokens (e.g. `[兄]`) are variable-like inline
        # text prefixes used in dialogue and should be treated as text even
        # when they occupy the whole line.
        if any(ord(char) > 127 for char in bracket_payload):
            return True
        # ASCII-only bracket tokens are treated as dialogue only when they
        # clearly prefix actual text content.
        if remainder and (not remainder.startswith(("[", ";", "*", "@", "//"))):
            return True
        return False
    if stripped.startswith(("#", ";", "*", "@", "//")):
        return False
    return True


def _tyrano_body_item_kind_for_line(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("#"):
        return "speaker"
    if _is_tyrano_dialogue_text_line(stripped):
        return "text"
    return "raw"


def _tyrano_speaker_name_from_line(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return ""
    return stripped[1:].strip()


def _line_has_tyrano_page_break(line: str) -> bool:
    return bool(_TYRANO_PAGE_BREAK_TAG_RE.search(line))


def _line_has_tyrano_dialogue_marker(line: str) -> bool:
    return bool(
        _TYRANO_PAGE_BREAK_TAG_RE.search(line)
        or _TYRANO_INLINE_LINE_BREAK_TAG_RE.search(line)
    )


def split_tyrano_dialogue_line_and_suffix(line: str) -> tuple[str, str]:
    if not isinstance(line, str):
        return "", ""
    marker_match = _TYRANO_TRAILING_DIALOGUE_MARKERS_RE.search(line)
    if marker_match is None:
        return line, ""
    text_part = line[:marker_match.start()]
    suffix_part = line[marker_match.start():]
    return text_part, suffix_part


def _split_tyrano_inline_line_breaks(text: str) -> tuple[list[str], list[str]]:
    if not text:
        return [""], [""]
    lines: list[str] = []
    suffixes: list[str] = []
    cursor = 0
    for match in _TYRANO_INLINE_LINE_BREAK_TAG_RE.finditer(text):
        lines.append(text[cursor:match.start()])
        suffixes.append(match.group(0))
        cursor = match.end()
    lines.append(text[cursor:])
    suffixes.append("")
    return lines, suffixes


def _replace_tyrano_inline_line_breaks_with_newlines(text: str) -> str:
    if not text:
        return ""
    return _TYRANO_INLINE_LINE_BREAK_TAG_RE.sub("\n", text)


def _replace_tyrano_attribute_line_breaks_with_newlines(text: str) -> str:
    if not text:
        return ""
    inline_normalized = _replace_tyrano_inline_line_breaks_with_newlines(text)
    return inline_normalized.replace("\\n", "\n")


def _is_tyrano_iscript_start_line(line: str) -> bool:
    return bool(_TYRANO_ISCRIPT_START_RE.match(line.strip()))


def _is_tyrano_iscript_end_line(line: str) -> bool:
    return bool(_TYRANO_ISCRIPT_END_RE.match(line.strip()))


def _extract_tyrano_script_assignment_string_value(
    line: str,
) -> tuple[int, int, str, str, str, str] | None:
    if not isinstance(line, str):
        return None
    for object_property_prefix in _TYRANO_SCRIPT_OBJECT_PROPERTY_PREFIX_RE.finditer(line):
        key_raw = object_property_prefix.groupdict().get("key", "")
        key_name = _normalize_tyrano_script_string_key(key_raw)
        value_start = object_property_prefix.end()
        if value_start >= len(line):
            continue
        quote_char = line[value_start]
        if quote_char not in {'"', "'"}:
            continue
        cursor = value_start + 1
        while cursor < len(line):
            char = line[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == quote_char:
                raw_value = line[value_start + 1:cursor]
                decoded = _unescape_tyrano_tag_attribute_value(raw_value)
                return (
                    value_start + 1,
                    cursor,
                    decoded,
                    quote_char,
                    "object_property",
                    key_name,
                )
            cursor += 1
    for match in _TYRANO_SCRIPT_ASSIGNMENT_PREFIX_RE.finditer(line):
        lhs_raw = match.groupdict().get("lhs", "")
        lhs_name = lhs_raw.strip().lower()
        value_start = match.end()
        if value_start >= len(line):
            continue
        quote_char = line[value_start]
        if quote_char not in {'"', "'"}:
            continue
        cursor = value_start + 1
        while cursor < len(line):
            char = line[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == quote_char:
                raw_value = line[value_start + 1:cursor]
                decoded = _unescape_tyrano_tag_attribute_value(raw_value)
                return (
                    value_start + 1,
                    cursor,
                    decoded,
                    quote_char,
                    "assignment",
                    lhs_name,
                )
            cursor += 1
    return None


def _normalize_tyrano_script_string_key(raw_key: str) -> str:
    key = raw_key.strip()
    if len(key) >= 2 and key[0] in {'"', "'"} and key[-1] == key[0]:
        key = key[1:-1]
    return key.strip().lower()


def _should_extract_tyrano_js_script_string(
    candidate_kind: str,
    candidate_key: str,
    *,
    in_end_list_context: bool,
) -> bool:
    key = candidate_key.strip().lower()
    if not key:
        return False
    if candidate_kind == "object_property":
        if key == "id":
            return in_end_list_context
        return key in _TYRANO_JS_TRANSLATABLE_OBJECT_KEYS
    if candidate_kind == "assignment":
        return key.endswith(_TYRANO_JS_TRANSLATABLE_ASSIGNMENT_SUFFIXES)
    return False


def _js_bracket_delta_outside_strings(line: str) -> int:
    delta = 0
    in_string = False
    string_quote = ""
    escaping = False
    for char in line:
        if in_string:
            if escaping:
                escaping = False
                continue
            if char == "\\":
                escaping = True
                continue
            if char == string_quote:
                in_string = False
            continue
        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            continue
        if char == "[":
            delta += 1
            continue
        if char == "]":
            delta -= 1
    return delta


def _group_tyrano_text_items_by_page_break(
    text_items: list[tuple[int, str]],
) -> list[list[tuple[int, str]]]:
    groups: list[list[tuple[int, str]]] = []
    pending_group: list[tuple[int, str]] = []
    for text_index, text_line in text_items:
        pending_group.append((text_index, text_line))
        if _line_has_tyrano_page_break(text_line):
            groups.append(list(pending_group))
            pending_group = []
    if pending_group:
        groups.append(list(pending_group))
    return groups


def _collect_tyrano_implicit_dialogue_block(
    source_lines: list[str],
    start_index: int,
) -> tuple[list[dict[str, str]], int] | None:
    if start_index < 0 or start_index >= len(source_lines):
        return None
    start_line = source_lines[start_index]
    stripped_start = start_line.strip()
    if not stripped_start:
        return None

    # Standard Tyrano scripts often use `#speaker` followed by plain text
    # lines without wrapping `[tb_start_text]` tags.
    if stripped_start.startswith("#"):
        body_items: list[dict[str, str]] = [{"kind": "speaker", "line": start_line}]
        has_dialogue_marker = False
        next_index = start_index + 1
        while next_index < len(source_lines):
            candidate = source_lines[next_index]
            if not _is_tyrano_dialogue_text_line(candidate):
                break
            body_items.append({"kind": "text", "line": candidate})
            if _line_has_tyrano_dialogue_marker(candidate):
                has_dialogue_marker = True
            next_index += 1
        if len(body_items) <= 1 or not has_dialogue_marker:
            return None
        return body_items, next_index

    if not _is_tyrano_dialogue_text_line(start_line):
        return None
    body_items = []
    has_dialogue_marker = False
    next_index = start_index
    while next_index < len(source_lines):
        candidate = source_lines[next_index]
        if not _is_tyrano_dialogue_text_line(candidate):
            break
        body_items.append({"kind": "text", "line": candidate})
        if _line_has_tyrano_dialogue_marker(candidate):
            has_dialogue_marker = True
        next_index += 1
    if not body_items or not has_dialogue_marker:
        return None
    return body_items, next_index


def _parse_tyrano_script_source(source: str) -> dict[str, Any]:
    newline = "\r\n" if "\r\n" in source else "\n"
    has_trailing_newline = source.endswith(("\n", "\r"))
    source_lines = source.splitlines()
    chunks: list[dict[str, Any]] = []

    index = 0
    while index < len(source_lines):
        line = source_lines[index]
        if not _is_tyrano_dialogue_block_start(line):
            implicit_dialogue = _collect_tyrano_implicit_dialogue_block(
                source_lines,
                index,
            )
            if implicit_dialogue is not None:
                body_items, next_index = implicit_dialogue
                chunks.append(
                    {
                        "kind": "dialogue_block",
                        "body_items": body_items,
                    }
                )
                index = next_index
                continue
            chunks.append({"kind": "raw_line", "line": line})
            index += 1
            continue

        end_index: int | None = None
        search_index = index + 1
        while search_index < len(source_lines):
            if _is_tyrano_dialogue_block_end(source_lines[search_index]):
                end_index = search_index
                break
            search_index += 1

        if end_index is None:
            chunks.append({"kind": "raw_line", "line": line})
            index += 1
            continue

        body_items: list[dict[str, str]] = []
        for body_line in source_lines[index + 1: end_index]:
            body_items.append(
                {
                    "kind": _tyrano_body_item_kind_for_line(body_line),
                    "line": body_line,
                }
            )
        chunks.append(
            {
                "kind": "dialogue_block",
                "start_line": line,
                "body_items": body_items,
                "end_line": source_lines[end_index],
            }
        )
        index = end_index + 1

    return {
        _TYRANO_SCRIPT_MARKER_KEY: _TYRANO_SCRIPT_MARKER_VALUE,
        _TYRANO_SCRIPT_NEWLINE_KEY: newline,
        _TYRANO_SCRIPT_HAS_TRAILING_NEWLINE_KEY: has_trailing_newline,
        _TYRANO_SCRIPT_CHUNKS_KEY: chunks,
    }


def load_tyrano_script_file(path: Path) -> dict[str, Any]:
    source = _read_text_file_with_fallback_encodings(path)
    return _parse_tyrano_script_source(source)


def _extract_tyrano_config_assignment_value(
    line: str,
    assignment_key: str,
) -> tuple[int, int, str, str] | None:
    lowered = line.lower()
    key = assignment_key.strip().lower()
    if not key:
        return None
    key_index = lowered.find(key)
    if key_index < 0:
        return None
    assign_index = line.find("=", key_index + len(key))
    if assign_index < 0:
        return None
    value_start = assign_index + 1
    while value_start < len(line) and line[value_start].isspace():
        value_start += 1
    value_end = len(line)
    while value_end > value_start and line[value_end - 1].isspace():
        value_end -= 1
    if value_end < value_start:
        value_end = value_start

    quote_char = ""
    if (
        value_end - value_start >= 2
        and line[value_start] in {'"', "'"}
        and line[value_end - 1] == line[value_start]
    ):
        quote_char = line[value_start]
        raw_value = line[value_start + 1:value_end - 1]
        decoded_value = _unescape_tyrano_tag_attribute_value(raw_value)
        return value_start + 1, value_end - 1, decoded_value, quote_char
    return value_start, value_end, line[value_start:value_end], quote_char


def _parse_tyrano_config_source(source: str) -> dict[str, Any]:
    newline = "\r\n" if "\r\n" in source else "\n"
    has_trailing_newline = source.endswith(("\n", "\r"))
    source_lines = source.splitlines()
    title_line_index = -1
    title_span: tuple[int, int] = (0, 0)
    title_quote = ""
    for line_index, line in enumerate(source_lines):
        title_payload = _extract_tyrano_config_assignment_value(line, "System.title")
        if title_payload is None:
            continue
        value_start, value_end, _decoded, quote_char = title_payload
        title_line_index = line_index
        title_span = (value_start, value_end)
        title_quote = quote_char
        break
    return {
        _TYRANO_CONFIG_MARKER_KEY: _TYRANO_CONFIG_MARKER_VALUE,
        _TYRANO_CONFIG_NEWLINE_KEY: newline,
        _TYRANO_CONFIG_HAS_TRAILING_NEWLINE_KEY: has_trailing_newline,
        _TYRANO_CONFIG_LINES_KEY: source_lines,
        _TYRANO_CONFIG_TITLE_LINE_INDEX_KEY: title_line_index,
        _TYRANO_CONFIG_TITLE_SPAN_KEY: title_span,
        _TYRANO_CONFIG_TITLE_QUOTE_KEY: title_quote,
    }


def load_tyrano_config_file(path: Path) -> dict[str, Any]:
    source = _read_text_file_with_fallback_encodings(path)
    return _parse_tyrano_config_source(source)


def is_tyrano_script_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    marker = data.get(_TYRANO_SCRIPT_MARKER_KEY)
    if marker != _TYRANO_SCRIPT_MARKER_VALUE:
        return False
    return isinstance(data.get(_TYRANO_SCRIPT_CHUNKS_KEY), list)


def is_tyrano_config_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    marker = data.get(_TYRANO_CONFIG_MARKER_KEY)
    if marker != _TYRANO_CONFIG_MARKER_VALUE:
        return False
    return isinstance(data.get(_TYRANO_CONFIG_LINES_KEY), list)


def _coerce_tyrano_config_lines(data: Any) -> list[str]:
    if not is_tyrano_config_data(data):
        return []
    raw_lines = data.get(_TYRANO_CONFIG_LINES_KEY)
    if not isinstance(raw_lines, list):
        return []
    lines: list[str] = []
    for line in raw_lines:
        if isinstance(line, str):
            lines.append(line)
    return lines


def _coerce_tyrano_script_chunks(data: Any) -> list[dict[str, Any]]:
    if not is_tyrano_script_data(data):
        return []
    raw_chunks = data.get(_TYRANO_SCRIPT_CHUNKS_KEY)
    if not isinstance(raw_chunks, list):
        return []
    chunks: list[dict[str, Any]] = []
    for chunk in raw_chunks:
        if isinstance(chunk, dict):
            chunks.append(chunk)
    return chunks


def tyrano_script_source_from_data(data: Any) -> str:
    if not is_tyrano_script_data(data):
        raise ValueError("Payload is not recognized TyranoScript structured data.")

    newline_raw = data.get(_TYRANO_SCRIPT_NEWLINE_KEY)
    newline = newline_raw if isinstance(newline_raw, str) and newline_raw else "\n"
    has_trailing_newline = bool(data.get(_TYRANO_SCRIPT_HAS_TRAILING_NEWLINE_KEY, True))
    chunks = _coerce_tyrano_script_chunks(data)

    rebuilt_lines: list[str] = []
    for chunk in chunks:
        kind_raw = chunk.get("kind")
        kind = kind_raw.strip().lower() if isinstance(kind_raw, str) else ""
        if kind == "dialogue_block":
            start_line_raw = chunk.get("start_line")
            end_line_raw = chunk.get("end_line")
            start_line = start_line_raw if isinstance(start_line_raw, str) else None
            end_line = end_line_raw if isinstance(end_line_raw, str) else None
            if start_line is not None:
                rebuilt_lines.append(start_line)
            body_items_raw = chunk.get("body_items")
            if isinstance(body_items_raw, list):
                for body_item in body_items_raw:
                    if not isinstance(body_item, dict):
                        continue
                    body_line_raw = body_item.get("line")
                    body_line = body_line_raw if isinstance(body_line_raw, str) else ""
                    rebuilt_lines.append(body_line)
            if end_line is not None:
                rebuilt_lines.append(end_line)
            continue

        line_raw = chunk.get("line")
        line = line_raw if isinstance(line_raw, str) else ""
        rebuilt_lines.append(line)

    rebuilt = newline.join(rebuilt_lines)
    if has_trailing_newline and rebuilt_lines:
        rebuilt += newline
    return rebuilt


def tyrano_config_source_from_data(data: Any) -> str:
    if not is_tyrano_config_data(data):
        raise ValueError("Payload is not recognized Tyrano Config.tjs structured data.")
    newline_raw = data.get(_TYRANO_CONFIG_NEWLINE_KEY)
    newline = newline_raw if isinstance(newline_raw, str) and newline_raw else "\n"
    has_trailing_newline = bool(data.get(_TYRANO_CONFIG_HAS_TRAILING_NEWLINE_KEY, True))
    lines = _coerce_tyrano_config_lines(data)
    rebuilt = newline.join(lines)
    if has_trailing_newline and lines:
        rebuilt += newline
    return rebuilt


def tyrano_config_title_from_data(data: Any) -> str:
    if not is_tyrano_config_data(data):
        return ""
    lines = _coerce_tyrano_config_lines(data)
    line_index_raw = data.get(_TYRANO_CONFIG_TITLE_LINE_INDEX_KEY, -1)
    if not isinstance(line_index_raw, int):
        return ""
    if line_index_raw < 0 or line_index_raw >= len(lines):
        return ""
    title_line = lines[line_index_raw]
    title_payload = _extract_tyrano_config_assignment_value(title_line, "System.title")
    if title_payload is None:
        return ""
    _value_start, _value_end, title_text, _quote_char = title_payload
    return title_text.strip()


def _unescape_tyrano_tag_attribute_value(value: str) -> str:
    if not value:
        return ""
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\" or index + 1 >= len(value):
            result.append(char)
            index += 1
            continue
        next_char = value[index + 1]
        if next_char in {'\\', '"', "'"}:
            result.append(next_char)
            index += 2
            continue
        result.append(char)
        result.append(next_char)
        index += 2
    return "".join(result)


def _extract_tyrano_tag_attribute_value(
    line: str,
    attribute_name: str,
) -> tuple[int, int, str, str] | None:
    lowered = line.lower()
    attr_key = attribute_name.strip().lower()
    if not attr_key:
        return None
    search_from = 0
    while True:
        attr_index = lowered.find(attr_key, search_from)
        if attr_index < 0:
            return None
        key_start = attr_index
        key_end = attr_index + len(attr_key)
        before_char = line[key_start - 1] if key_start > 0 else ""
        after_char = line[key_end] if key_end < len(line) else ""
        if (
            (before_char and (before_char.isalnum() or before_char in {"_", "-"}))
            or (after_char and (after_char.isalnum() or after_char in {"_", "-"}))
        ):
            search_from = key_end
            continue
        index = key_end
        while index < len(line) and line[index].isspace():
            index += 1
        if index >= len(line) or line[index] != "=":
            search_from = key_end
            continue
        index += 1
        while index < len(line) and line[index].isspace():
            index += 1
        if index >= len(line):
            return None
        quote_char = line[index]
        if quote_char not in {'"', "'"}:
            search_from = key_end
            continue
        value_start = index + 1
        value_index = value_start
        while value_index < len(line):
            candidate = line[value_index]
            if candidate == "\\":
                value_index += 2
                continue
            if candidate == quote_char:
                raw_value = line[value_start:value_index]
                decoded = _unescape_tyrano_tag_attribute_value(raw_value)
                return value_start, value_index, decoded, quote_char
            value_index += 1
        return None


def _build_tyrano_dialogue_segments(path: Path, data: dict[str, Any]) -> list[DialogueSegment]:
    chunks = _coerce_tyrano_script_chunks(data)
    segments: list[DialogueSegment] = []
    block_index = 1
    for chunk_index, chunk in enumerate(chunks):
        kind_raw = chunk.get("kind")
        kind = kind_raw.strip().lower() if isinstance(kind_raw, str) else ""
        if kind != "dialogue_block":
            continue
        body_items_raw = chunk.get("body_items")
        if not isinstance(body_items_raw, list):
            continue
        speaker_item_index: int | None = None
        speaker_name = ""
        text_items: list[tuple[int, str]] = []
        for body_index, body_item in enumerate(body_items_raw):
            if not isinstance(body_item, dict):
                continue
            item_kind_raw = body_item.get("kind")
            item_kind = item_kind_raw.strip().lower() if isinstance(item_kind_raw, str) else ""
            item_line_raw = body_item.get("line")
            item_line = item_line_raw if isinstance(item_line_raw, str) else ""
            if item_kind == "speaker":
                if speaker_item_index is None:
                    speaker_item_index = body_index
                    speaker_name = _tyrano_speaker_name_from_line(item_line)
                continue
            if item_kind != "text":
                continue
            text_items.append((body_index, item_line))
        if speaker_item_index is None and not text_items:
            continue
        text_groups = _group_tyrano_text_items_by_page_break(text_items)
        if not text_groups:
            text_groups = [[]]
        for text_group in text_groups:
            text_item_indexes = [item_index for item_index, _ in text_group]
            lines: list[str] = []
            line_suffixes: list[str] = []
            for _, line in text_group:
                visible_line, line_suffix = split_tyrano_dialogue_line_and_suffix(line)
                split_lines, split_suffixes = _split_tyrano_inline_line_breaks(visible_line)
                if not split_lines:
                    split_lines = [""]
                    split_suffixes = [""]
                for split_index, split_line in enumerate(split_lines):
                    suffix = split_suffixes[split_index]
                    if split_index == len(split_lines) - 1:
                        suffix = f"{suffix}{line_suffix}"
                    lines.append(split_line)
                    line_suffixes.append(suffix)
            if not lines:
                lines = [""]
                line_suffixes = [""]
            uid = f"{path.name}:K:{block_index}"
            block_index += 1
            segment = DialogueSegment(
                uid=uid,
                context=f"{path.name} > text_block[{block_index - 1}]",
                code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker_name]},
                lines=list(lines),
                original_lines=list(lines),
                source_lines=list(lines),
                segment_kind="tyrano_dialogue",
            )
            setattr(segment, "tyrano_chunk_index", chunk_index)
            setattr(segment, "tyrano_speaker_item_index", speaker_item_index)
            setattr(segment, "tyrano_text_item_indexes", tuple(text_item_indexes))
            setattr(segment, "tyrano_line_suffixes", tuple(line_suffixes))
            # Backward-compatible alias used by older save logic paths.
            setattr(segment, "tyrano_editable_item_indexes", tuple(text_item_indexes))
            segments.append(segment)
    return segments


def _is_tyrano_choice_tag_line(line: str) -> bool:
    lowered = line.strip().lower()
    return (
        lowered.startswith("[glink")
        or lowered.startswith("[mylink")
        or lowered.startswith("@mylink")
    )


def _normalize_tyrano_choice_text_for_editor(text: str) -> str:
    if not text:
        return ""
    # Treat both classic NBSP and narrow NBSP as regular spaces in editor view.
    return text.replace("\u00A0", " ").replace("\u202F", " ")


def _build_tyrano_choice_segments(
    path: Path,
    data: dict[str, Any],
) -> tuple[list[DialogueSegment], set[int]]:
    chunks = _coerce_tyrano_script_chunks(data)
    segments: list[DialogueSegment] = []
    used_chunk_indexes: set[int] = set()
    choice_index = 1

    chunk_index = 0
    while chunk_index < len(chunks):
        chunk = chunks[chunk_index]
        kind_raw = chunk.get("kind") if isinstance(chunk, dict) else ""
        kind = kind_raw.strip().lower() if isinstance(kind_raw, str) else ""
        if kind != "raw_line":
            chunk_index += 1
            continue

        line_raw = chunk.get("line") if isinstance(chunk, dict) else ""
        line = line_raw if isinstance(line_raw, str) else ""
        if not _is_tyrano_choice_tag_line(line):
            chunk_index += 1
            continue
        if _extract_tyrano_tag_attribute_value(line, "text") is None:
            chunk_index += 1
            continue

        option_lines: list[str] = []
        option_items: list[tuple[int, int, int, str]] = []
        scan_index = chunk_index
        while scan_index < len(chunks):
            scan_chunk = chunks[scan_index]
            scan_kind_raw = scan_chunk.get("kind") if isinstance(scan_chunk, dict) else ""
            scan_kind = scan_kind_raw.strip().lower() if isinstance(scan_kind_raw, str) else ""
            if scan_kind != "raw_line":
                break
            scan_line_raw = scan_chunk.get("line") if isinstance(scan_chunk, dict) else ""
            scan_line = scan_line_raw if isinstance(scan_line_raw, str) else ""
            if not _is_tyrano_choice_tag_line(scan_line):
                break
            attr_payload = _extract_tyrano_tag_attribute_value(scan_line, "text")
            if attr_payload is None:
                break
            value_start, value_end, decoded_value, quote_char = attr_payload
            normalized_choice_text = _normalize_tyrano_choice_text_for_editor(
                decoded_value
            )
            option_lines.append(
                _replace_tyrano_attribute_line_breaks_with_newlines(
                    normalized_choice_text
                )
            )
            option_items.append((scan_index, value_start, value_end, quote_char))
            used_chunk_indexes.add(scan_index)
            scan_index += 1

        if option_items:
            uid = f"{path.name}:KQ:{choice_index}"
            segment = DialogueSegment(
                uid=uid,
                context=f"{path.name} > choice[{choice_index}]",
                code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
                lines=list(option_lines),
                original_lines=list(option_lines),
                source_lines=list(option_lines),
                segment_kind="choice",
                line_entry_code=402,
            )
            setattr(segment, "tyrano_chunk_index", option_items[0][0])
            setattr(segment, "tyrano_choice_items", tuple(option_items))
            segments.append(segment)
            choice_index += 1
            chunk_index = scan_index
            continue

        chunk_index += 1

    return segments, used_chunk_indexes


def _build_tyrano_tag_text_segments(
    path: Path,
    data: dict[str, Any],
    *,
    excluded_chunk_indexes: set[int] | None = None,
) -> list[DialogueSegment]:
    chunks = _coerce_tyrano_script_chunks(data)
    segments: list[DialogueSegment] = []
    excluded_indexes = excluded_chunk_indexes or set()
    tag_index = 1
    for chunk_index, chunk in enumerate(chunks):
        if chunk_index in excluded_indexes:
            continue
        kind_raw = chunk.get("kind")
        kind = kind_raw.strip().lower() if isinstance(kind_raw, str) else ""
        if kind != "raw_line":
            continue
        line_raw = chunk.get("line")
        line = line_raw if isinstance(line_raw, str) else ""
        stripped = line.strip()
        if not stripped.startswith("["):
            continue
        attr_payload = _extract_tyrano_tag_attribute_value(line, "text")
        if attr_payload is None:
            continue
        value_start, value_end, decoded_value, quote_char = attr_payload
        normalized_text = _replace_tyrano_attribute_line_breaks_with_newlines(
            decoded_value
        )
        lines = split_lines_preserve_empty(normalized_text)
        uid = f"{path.name}:KT:{tag_index}"
        segment = DialogueSegment(
            uid=uid,
            context=f"{path.name} > tag_text[{tag_index}]",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=list(lines),
            original_lines=list(lines),
            source_lines=list(lines),
            segment_kind="tyrano_tag_text",
        )
        setattr(segment, "tyrano_chunk_index", chunk_index)
        setattr(segment, "tyrano_tag_text_span", (value_start, value_end))
        setattr(segment, "tyrano_tag_text_quote", quote_char)
        segments.append(segment)
        tag_index += 1
    return segments


def _build_tyrano_script_string_segments(
    path: Path,
    data: dict[str, Any],
    *,
    excluded_chunk_indexes: set[int] | None = None,
) -> list[DialogueSegment]:
    chunks = _coerce_tyrano_script_chunks(data)
    segments: list[DialogueSegment] = []
    excluded_indexes = excluded_chunk_indexes or set()
    text_index = 1
    is_js_file = is_tyrano_js_path(path)
    in_iscript_block = is_js_file
    end_list_depth = 0
    end_list_id_counter = 0
    js_owner_hint = ""
    for chunk_index, chunk in enumerate(chunks):
        if chunk_index in excluded_indexes:
            continue
        kind_raw = chunk.get("kind")
        kind = kind_raw.strip().lower() if isinstance(kind_raw, str) else ""
        if kind != "raw_line":
            continue
        line_raw = chunk.get("line")
        line = line_raw if isinstance(line_raw, str) else ""
        if is_js_file:
            owner_match = _TYRANO_JS_OBJECT_OWNER_START_RE.search(line)
            if owner_match is not None:
                owner_raw = owner_match.groupdict().get("owner", "")
                js_owner_hint = owner_raw.strip()
            elif "};" in line:
                # Best-effort owner reset after object block close.
                js_owner_hint = ""
        is_end_list_line = False
        if is_js_file:
            is_end_list_line = end_list_depth > 0
            if _TYRANO_END_LIST_DECL_RE.search(line):
                is_end_list_line = True
        if not is_js_file:
            if _is_tyrano_iscript_start_line(line):
                in_iscript_block = True
                continue
            if _is_tyrano_iscript_end_line(line):
                in_iscript_block = False
                continue
        if not in_iscript_block:
            continue
        attr_payload = _extract_tyrano_script_assignment_string_value(line)
        if attr_payload is None:
            if is_js_file and is_end_list_line:
                end_list_depth += _js_bracket_delta_outside_strings(line)
                if end_list_depth < 0:
                    end_list_depth = 0
            continue
        value_start, value_end, decoded_value, quote_char, candidate_kind, candidate_key = attr_payload
        should_collect = True
        if is_js_file:
            should_collect = _should_extract_tyrano_js_script_string(
                candidate_kind,
                candidate_key,
                in_end_list_context=is_end_list_line,
            )
            if should_collect and not decoded_value.strip():
                should_collect = False
        else:
            if candidate_kind == "assignment" and candidate_key.endswith(".ending"):
                should_collect = bool(decoded_value.strip())
            else:
                should_collect = bool(_NOTE_JAPANESE_CHAR_RE.search(decoded_value))
        if should_collect:
            normalized_text = _replace_tyrano_attribute_line_breaks_with_newlines(
                decoded_value
            )
            lines = split_lines_preserve_empty(normalized_text)
            descriptor = candidate_key
            if is_js_file and candidate_kind == "object_property" and candidate_key == "id" and is_end_list_line:
                end_list_id_counter += 1
                descriptor = f"END_LIST[{end_list_id_counter}].id"
            is_end_id_ref = (
                candidate_kind == "assignment"
                and candidate_key.endswith(".ending")
            )
            if is_end_id_ref:
                descriptor = f"{candidate_key} -> END_LIST.id"
            if (
                candidate_kind == "object_property"
                and js_owner_hint
                and candidate_key
                and descriptor == candidate_key
            ):
                descriptor = f"{js_owner_hint}.{candidate_key}"
            if not descriptor:
                descriptor = "script_text"
            uid = f"{path.name}:KS:{text_index}"
            segment = DialogueSegment(
                uid=uid,
                context=f"{path.name} > script_text[{text_index}] ({descriptor})",
                code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
                lines=list(lines),
                original_lines=list(lines),
                source_lines=list(lines),
                segment_kind="tyrano_tag_text",
            )
            setattr(segment, "tyrano_chunk_index", chunk_index)
            setattr(segment, "tyrano_tag_text_span", (value_start, value_end))
            setattr(segment, "tyrano_tag_text_quote", quote_char)
            setattr(segment, "tyrano_tag_text_join_mode", "script_string")
            if is_js_file and candidate_kind == "object_property" and candidate_key == "id" and is_end_list_line:
                # Keep END_LIST ids as stable keys and apply translation via display map.
                setattr(segment, "tyrano_script_end_list_id_source", decoded_value)
                setattr(segment, "tyrano_tag_text_join_mode", "script_string_end_id")
            elif is_end_id_ref:
                # END key references (e.g. f.ending = '双子') should stay stable and
                # resolve through END_LIST ids, not be rewritten directly.
                setattr(segment, "tyrano_script_end_list_id_source", decoded_value)
                setattr(segment, "tyrano_tag_text_join_mode", "script_string_end_id_ref")
            segments.append(segment)
            text_index += 1
        if is_js_file and is_end_list_line:
            end_list_depth += _js_bracket_delta_outside_strings(line)
            if end_list_depth < 0:
                end_list_depth = 0
    return segments


def _build_plugins_text_segments(path: Path, data: dict[str, Any]) -> list[DialogueSegment]:
    if not is_plugins_js_data(data):
        return []
    plugin_rows = data.get(_PLUGINS_JS_ARRAY_KEY)
    if not isinstance(plugin_rows, list):
        return []

    segments: list[DialogueSegment] = []
    for idx, row in enumerate(plugin_rows):
        if not isinstance(row, dict):
            continue
        row_number = idx + 1
        plugin_name_raw = row.get("name")
        plugin_name = plugin_name_raw if isinstance(plugin_name_raw, str) and plugin_name_raw.strip(
        ) else f"Plugin{row_number}"
        description_raw = row.get("description")
        if isinstance(description_raw, str) and description_raw.strip():
            description_lines = split_lines_preserve_empty(description_raw)
            uid = f"{path.name}:J:{row_number}:description"
            code101 = {"code": 101, "indent": 0,
                       "parameters": ["", 0, 0, 2, plugin_name]}
            segment = DialogueSegment(
                uid=uid,
                context=f"{path.name} > plugin[{row_number}].description",
                code101=code101,
                lines=list(description_lines),
                original_lines=list(description_lines),
                source_lines=list(description_lines),
                segment_kind="plugin_text",
            )
            setattr(
                segment,
                "plugin_text_path",
                (_PLUGINS_JS_ARRAY_KEY, idx, "description"),
            )
            segments.append(segment)

        parameters_raw = row.get("parameters")
        if not isinstance(parameters_raw, dict):
            continue
        for param_index, (param_key, param_value) in enumerate(parameters_raw.items(), start=1):
            if not isinstance(param_key, str) or not isinstance(param_value, str):
                continue
            if not param_value.strip():
                continue
            lines = split_lines_preserve_empty(param_value)
            safe_key = _safe_system_field_slug(param_key)
            uid = f"{path.name}:J:{row_number}:param_{param_index}_{safe_key}"
            code101 = {"code": 101, "indent": 0,
                       "parameters": ["", 0, 0, 2, plugin_name]}
            segment = DialogueSegment(
                uid=uid,
                context=f"{path.name} > plugin[{row_number}].parameters.{param_key}",
                code101=code101,
                lines=list(lines),
                original_lines=list(lines),
                source_lines=list(lines),
                segment_kind="plugin_text",
            )
            setattr(
                segment,
                "plugin_text_path",
                (_PLUGINS_JS_ARRAY_KEY, idx, "parameters", param_key),
            )
            segments.append(segment)
    return segments


def _build_map_display_name_segment(path: Path, data: Any) -> DialogueSegment | None:
    if not isinstance(data, dict):
        return None
    if not _MAP_FILE_NAME_RE.fullmatch(path.name.strip()):
        return None
    display_name_raw = data.get("displayName")
    if not isinstance(display_name_raw, str):
        return None

    lines = split_lines_preserve_empty(display_name_raw)
    code101 = {
        "code": 101,
        "indent": 0,
        "parameters": ["", 0, 0, 2, ""],
    }
    segment = DialogueSegment(
        uid=f"{path.name}:map_display_name",
        context=f"{path.name} > displayName",
        code101=code101,
        lines=list(lines),
        original_lines=list(lines),
        source_lines=list(lines),
        segment_kind="map_display_name",
    )
    setattr(segment, "map_display_name_path", ("displayName",))
    return segment


def _choice_lines_from_code102(entry: dict[str, Any]) -> list[str]:
    params = entry.get("parameters")
    if not isinstance(params, list) or not params:
        return [""]
    raw_choices = params[0]
    if not isinstance(raw_choices, list):
        return [""]
    lines: list[str] = []
    for item in raw_choices:
        if isinstance(item, str):
            lines.append(item)
        elif item is None:
            lines.append("")
        else:
            lines.append(str(item))
    return lines or [""]


def _collect_choice_branch_entries(
    commands: list[Any],
    code102_index: int,
) -> list[dict[str, Any]]:
    entry = commands[code102_index]
    if not isinstance(entry, dict):
        return []
    base_indent_raw = entry.get("indent", 0)
    base_indent = base_indent_raw if isinstance(base_indent_raw, int) else 0
    branch_entries: list[dict[str, Any]] = []
    idx = code102_index + 1
    while idx < len(commands):
        candidate = commands[idx]
        if not is_command_entry(candidate):
            idx += 1
            continue
        if not isinstance(candidate, dict):
            idx += 1
            continue
        code = candidate.get("code")
        indent_raw = candidate.get("indent", base_indent)
        indent = indent_raw if isinstance(indent_raw, int) else base_indent
        if code == 404 and indent == base_indent:
            break
        if code == 402 and indent == base_indent:
            branch_entries.append(candidate)
        idx += 1
    return branch_entries


def _collect_script_block_entries(
    commands: list[Any],
    start_index: int,
) -> tuple[list[dict[str, Any]], int]:
    block_entries: list[dict[str, Any]] = []
    idx = start_index
    while idx < len(commands):
        candidate = commands[idx]
        if not is_command_entry(candidate) or not isinstance(candidate, dict):
            break
        code = candidate.get("code")
        if idx == start_index:
            if code != 355:
                break
        elif code != 655:
            break
        block_entries.append(candidate)
        idx += 1
    return block_entries, idx


def _build_plugin_command_text_segments_for_entry(
    *,
    path: Path,
    context: str,
    list_id: str,
    list_path_tokens: list[Any],
    command_index: int,
    command_entry: dict[str, Any],
) -> list[DialogueSegment]:
    params = command_entry.get("parameters")
    if not isinstance(params, list) or len(params) <= 3:
        return []
    args_raw = params[3]
    if not isinstance(args_raw, dict):
        return []

    plugin_name_raw = params[0] if len(params) > 0 else ""
    command_display_name_raw = params[2] if len(params) > 2 else ""
    plugin_name = (
        plugin_name_raw.strip()
        if isinstance(plugin_name_raw, str) and plugin_name_raw.strip()
        else "Plugin Command"
    )
    command_display_name = (
        command_display_name_raw.strip()
        if isinstance(command_display_name_raw, str) and command_display_name_raw.strip()
        else ""
    )
    speaker = plugin_name
    if command_display_name:
        speaker = f"{plugin_name} | {command_display_name}"

    indent_raw = command_entry.get("indent", 0)
    indent = indent_raw if isinstance(indent_raw, int) else 0
    segments: list[DialogueSegment] = []
    for arg_key, arg_value_raw in args_raw.items():
        if not isinstance(arg_key, str):
            continue
        if not isinstance(arg_value_raw, str):
            continue
        if not arg_value_raw.strip():
            continue
        if _plugin_command_argument_value_is_non_meaningful(arg_value_raw):
            continue
        lines = split_lines_preserve_empty(arg_value_raw)
        uid = (
            f"{path.name}:{list_id}:G:{command_index}:"
            f"{_safe_system_field_slug(arg_key)}"
        )
        segment = DialogueSegment(
            uid=uid,
            context=(
                f"{context} | plugin_command[{command_index}]"
                f".{plugin_name}.{command_display_name or 'command'}.{arg_key}"
            ),
            code101={
                "code": 101,
                "indent": indent,
                "parameters": ["", 0, 0, 2, speaker],
            },
            lines=list(lines),
            original_lines=list(lines),
            source_lines=list(lines),
            segment_kind="plugin_command_text",
        )
        setattr(
            segment,
            "plugin_command_text_path",
            tuple(list_path_tokens + [command_index, "parameters", 3, arg_key]),
        )
        setattr(
            segment,
            "json_text_path",
            tuple(list_path_tokens + [command_index, "parameters", 3, arg_key]),
        )
        segments.append(segment)
    return segments


def _plugin_command_argument_part_is_non_meaningful(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    if lowered in _PLUGIN_ARG_LITERAL_WORDS:
        return True
    if lowered in _PLUGIN_ARG_ALIGNMENT_WORDS:
        return True
    if bool(_PLUGIN_ARG_NUMBER_RE.fullmatch(lowered)):
        return True
    if bool(_PLUGIN_ARG_HEX_COLOR_RE.fullmatch(lowered)):
        return True
    if lowered.startswith(("rgb(", "rgba(", "hsl(", "hsla(")) and lowered.endswith(")"):
        return True
    return False


def _plugin_command_argument_value_is_non_meaningful(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _plugin_command_argument_part_is_non_meaningful(stripped):
        return True
    candidate = stripped
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1].strip()
    if "," not in candidate:
        return False
    parts = [part.strip() for part in candidate.split(",")]
    if not parts or any(not part for part in parts):
        return False
    return all(_plugin_command_argument_part_is_non_meaningful(part) for part in parts)


def _text_is_translatable_for_misc_extraction(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_NOTE_JAPANESE_CHAR_RE.search(stripped))


def _json_path_label(path_tokens: tuple[Any, ...]) -> str:
    label = ""
    for token in path_tokens:
        if isinstance(token, int):
            label += f"[{token}]"
            continue
        token_text = str(token)
        if label:
            label += "."
        label += token_text
    return label


def _build_json_text_segment(
    *,
    path: Path,
    uid: str,
    context: str,
    text: str,
    path_tokens: tuple[Any, ...],
    speaker: str = "",
    segment_kind: str = "note_text",
) -> DialogueSegment:
    lines = split_lines_preserve_empty(text)
    segment = DialogueSegment(
        uid=uid,
        context=context,
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=list(lines),
        original_lines=list(lines),
        source_lines=list(lines),
        segment_kind=segment_kind,
    )
    setattr(segment, "json_text_path", path_tokens)
    return segment


def _build_note_text_segments(path: Path, data: Any) -> list[DialogueSegment]:
    segments: list[DialogueSegment] = []

    def walk(node: Any, path_tokens: list[Any]) -> None:
        if isinstance(node, dict):
            note_raw = node.get("note")
            if (
                isinstance(note_raw, str)
                and _text_is_translatable_for_misc_extraction(note_raw)
            ):
                note_path_tokens = tuple(path_tokens + ["note"])
                note_path_key = "|".join(str(token) for token in note_path_tokens)
                digest = hashlib.sha1(note_path_key.encode("utf-8")).hexdigest()[:12]
                segment = _build_json_text_segment(
                    path=path,
                    uid=f"{path.name}:N:{digest}",
                    context=f"{path.name} > {_json_path_label(note_path_tokens)}",
                    text=note_raw,
                    path_tokens=note_path_tokens,
                    segment_kind="note_text",
                )
                setattr(segment, "note_text_path", note_path_tokens)
                segments.append(segment)
            for key, value in node.items():
                walk(value, path_tokens + [key])
            return
        if isinstance(node, list):
            for idx, value in enumerate(node):
                walk(value, path_tokens + [idx])

    walk(data, [])
    return segments


def _safe_system_field_slug(field_path: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", field_path)
    collapsed = re.sub(r"_+", "_", cleaned).strip("_")
    return collapsed or "field"


def _build_system_text_segments(path: Path, data: dict[str, Any]) -> list[DialogueSegment]:
    segments: list[DialogueSegment] = []
    entry_index = 1

    def add_segment(path_tokens: tuple[Any, ...], field_path: str, text: str) -> None:
        nonlocal entry_index
        lines = split_lines_preserve_empty(text)
        uid = f"{path.name}:Y:{entry_index}:{_safe_system_field_slug(field_path)}"
        entry_index += 1
        code101 = {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]}
        segment = DialogueSegment(
            uid=uid,
            context=f"{path.name} > system.{field_path}",
            code101=code101,
            lines=list(lines),
            original_lines=list(lines),
            source_lines=list(lines),
            segment_kind="system_text",
        )
        setattr(segment, "system_text_path", path_tokens)
        segments.append(segment)

    for field_name in _SYSTEM_TOP_LEVEL_STRING_FIELDS:
        raw_value = data.get(field_name)
        if isinstance(raw_value, str):
            add_segment((field_name,), field_name, raw_value)

    for field_name in _SYSTEM_INDEXED_ARRAY_FIELDS:
        raw_list = data.get(field_name)
        if not isinstance(raw_list, list):
            continue
        for idx, item in enumerate(raw_list):
            if not isinstance(item, str) or not item.strip():
                continue
            add_segment((field_name, idx), f"{field_name}[{idx}]", item)

    terms_raw = data.get("terms")
    if isinstance(terms_raw, dict):
        for field_name in _SYSTEM_TERMS_ARRAY_FIELDS:
            raw_list = terms_raw.get(field_name)
            if not isinstance(raw_list, list):
                continue
            for idx, item in enumerate(raw_list):
                if not isinstance(item, str) or not item.strip():
                    continue
                add_segment(("terms", field_name, idx),
                            f"terms.{field_name}[{idx}]", item)

        messages_raw = terms_raw.get("messages")
        if isinstance(messages_raw, dict):
            for key, value in messages_raw.items():
                if isinstance(key, str) and isinstance(value, str) and value.strip():
                    add_segment(("terms", "messages", key),
                                f"terms.messages.{key}", value)

    return segments


def parse_dialogue_data(path: Path, data: Any) -> FileSession:
    if is_tyrano_config_data(data):
        title_text = tyrano_config_title_from_data(data)
        segments: list[DialogueSegment] = []
        if title_text:
            lines = split_lines_preserve_empty(title_text)
            segment = DialogueSegment(
                uid=f"{path.name}:Y:1:gameTitle",
                context=f"{path.name} > System.title",
                code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
                lines=list(lines),
                original_lines=list(lines),
                source_lines=list(lines),
                segment_kind="system_text",
            )
            setattr(segment, "system_text_path", ("gameTitle",))
            setattr(segment, "tyrano_config_key", "System.title")
            segments.append(segment)
        config_session = FileSession(
            path=path,
            data=data,
            bundles=[],
            segments=segments,
        )
        setattr(config_session, "is_name_index_session", True)
        setattr(config_session, "name_index_kind", "system")
        setattr(config_session, "name_index_uid_prefix", "Y")
        setattr(config_session, "name_index_label", "System")
        return config_session

    if is_plugins_js_data(data):
        plugin_segments = _build_plugins_text_segments(path, data)
        plugin_session = FileSession(
            path=path,
            data=data,
            bundles=[],
            segments=plugin_segments,
        )
        setattr(plugin_session, "is_name_index_session", True)
        setattr(plugin_session, "name_index_kind", "plugin")
        setattr(plugin_session, "name_index_uid_prefix", "J")
        setattr(plugin_session, "name_index_label", "Plugin")
        return plugin_session

    if is_tyrano_script_data(data):
        dialogue_segments = _build_tyrano_dialogue_segments(path, data)
        choice_segments, choice_chunk_indexes = _build_tyrano_choice_segments(path, data)
        tag_text_segments = _build_tyrano_tag_text_segments(
            path,
            data,
            excluded_chunk_indexes=choice_chunk_indexes,
        )
        script_string_segments = _build_tyrano_script_string_segments(
            path,
            data,
            excluded_chunk_indexes=choice_chunk_indexes,
        )
        tyrano_segments = (
            dialogue_segments
            + choice_segments
            + tag_text_segments
            + script_string_segments
        )
        tyrano_segments.sort(
            key=lambda segment: (
                int(getattr(segment, "tyrano_chunk_index", 0)),
                0 if segment.segment_kind == "tyrano_dialogue" else (
                    1 if segment.segment_kind == "choice" else 2
                ),
            )
        )
        tyrano_session = FileSession(
            path=path,
            data=data,
            bundles=[],
            segments=tyrano_segments,
        )
        return tyrano_session

    bundles: list[CommandBundle] = []
    segments: list[DialogueSegment] = []
    list_counter = 0
    segment_counter = 0

    def walk(value: Any, breadcrumb: list[str], path_tokens: list[Any]) -> None:
        nonlocal list_counter, segment_counter
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, breadcrumb + [str(key)], path_tokens + [key])
            return

        if isinstance(value, list):
            if any(is_command_entry(item) for item in value):
                context = " > ".join(breadcrumb) if breadcrumb else "<root>"
                context = f"{path.name} > {context}"
                list_id = f"L{list_counter}"
                list_counter += 1

                tokens: list[CommandToken] = []
                i = 0
                while i < len(value):
                    entry = value[i]
                    if is_command_entry(entry) and entry.get("code") == 101:
                        base_cmd = copy.deepcopy(entry)
                        lines: list[str] = []
                        code401_template: dict[str, Any] = {}
                        j = i + 1
                        while (
                            j < len(value)
                            and is_command_entry(value[j])
                            and value[j].get("code") == 401
                        ):
                            current_line_entry = value[j]
                            if not code401_template and isinstance(current_line_entry, dict):
                                code401_template = copy.deepcopy(
                                    current_line_entry)
                            lines.append(first_parameter_text(current_line_entry))
                            j += 1
                        if not lines:
                            lines = [""]

                        uid = f"{path.name}:{list_id}:{segment_counter}"
                        segment_counter += 1
                        segment = DialogueSegment(
                            uid=uid,
                            context=context,
                            code101=base_cmd,
                            lines=list(lines),
                            original_lines=list(lines),
                            source_lines=list(lines),
                            code401_template=code401_template,
                        )
                        tokens.append(CommandToken(
                            kind="dialogue", segment=segment))
                        segments.append(segment)
                        i = j
                        continue
                    if is_command_entry(entry) and entry.get("code") == 102:
                        base_cmd = copy.deepcopy(entry)
                        lines = _choice_lines_from_code102(entry)
                        branch_entries = _collect_choice_branch_entries(value, i)
                        line_template: dict[str, Any] = {}
                        if branch_entries:
                            line_template = copy.deepcopy(branch_entries[0])
                        if not line_template:
                            indent_raw = entry.get("indent", 0)
                            indent = indent_raw if isinstance(
                                indent_raw, int) else 0
                            line_template = {
                                "code": 402,
                                "indent": indent,
                                "parameters": [0, ""],
                            }
                        uid = f"{path.name}:{list_id}:{segment_counter}"
                        segment_counter += 1
                        segment = DialogueSegment(
                            uid=uid,
                            context=f"{context} | choices",
                            code101=base_cmd,
                            lines=list(lines),
                            original_lines=list(lines),
                            source_lines=list(lines),
                            code401_template=line_template,
                            segment_kind="choice",
                            line_entry_code=402,
                            choice_branch_entries=list(branch_entries),
                        )
                        tokens.append(CommandToken(
                            kind="dialogue", segment=segment))
                        segments.append(segment)
                        i += 1
                        continue
                    if is_command_entry(entry) and entry.get("code") == 355:
                        script_entries, j = _collect_script_block_entries(
                            value, i)
                        if script_entries:
                            script_templates = [
                                copy.deepcopy(script_entry)
                                for script_entry in script_entries
                            ]
                            script_roles: list[str] = []
                            script_quotes: list[str] = []
                            script_expression_templates: list[dict[str, Any] | None] = []
                            script_lines: list[str] = []
                            speaker_text = ""
                            face_name = ""
                            face_index = 0
                            background = 0
                            position = 2
                            line_template: dict[str, Any] = {}
                            for script_entry in script_entries:
                                text = first_parameter_text(script_entry)
                                parsed = parse_game_message_call(text)
                                if parsed is None:
                                    templated_parsed = parse_game_message_templated_call(
                                        text
                                    )
                                    if templated_parsed is not None:
                                        call_kind, decoded_text, quote_char, expr_terms = templated_parsed
                                        template_payload: dict[str, Any] = {
                                            "kind": call_kind,
                                            "expr_terms": list(expr_terms),
                                        }
                                        if call_kind == "add":
                                            script_roles.append("add")
                                            script_quotes.append(quote_char)
                                            script_expression_templates.append(template_payload)
                                            script_lines.append(decoded_text)
                                            if not line_template:
                                                line_template = copy.deepcopy(
                                                    script_entry)
                                        else:
                                            script_roles.append("speaker")
                                            script_quotes.append(quote_char)
                                            script_expression_templates.append(template_payload)
                                            speaker_text = decoded_text
                                        continue
                                    face_parsed = parse_game_message_set_face_image_call(
                                        text
                                    )
                                    if face_parsed is not None:
                                        script_roles.append("face")
                                        script_quotes.append('"')
                                        script_expression_templates.append(None)
                                        parsed_face_name, parsed_face_index_raw = face_parsed
                                        face_name = parsed_face_name.strip()
                                        try:
                                            face_index = int(parsed_face_index_raw)
                                        except Exception:
                                            face_index = 0
                                        continue
                                    background_parsed = parse_game_message_set_background_call(
                                        text
                                    )
                                    if background_parsed is not None:
                                        script_roles.append("background")
                                        script_quotes.append('"')
                                        script_expression_templates.append(None)
                                        try:
                                            background = int(background_parsed)
                                        except Exception:
                                            background = 0
                                        continue
                                    position_parsed = parse_game_message_set_position_type_call(
                                        text
                                    )
                                    if position_parsed is not None:
                                        script_roles.append("position")
                                        script_quotes.append('"')
                                        script_expression_templates.append(None)
                                        try:
                                            position = int(position_parsed)
                                        except Exception:
                                            position = 2
                                        continue
                                    script_roles.append("other")
                                    script_quotes.append('"')
                                    script_expression_templates.append(None)
                                    continue
                                call_kind, decoded_text, quote_char = parsed
                                if call_kind == "add":
                                    script_roles.append("add")
                                    script_quotes.append(quote_char)
                                    script_expression_templates.append(None)
                                    script_lines.append(decoded_text)
                                    if not line_template:
                                        line_template = copy.deepcopy(
                                            script_entry)
                                else:
                                    script_roles.append("speaker")
                                    script_quotes.append(quote_char)
                                    script_expression_templates.append(None)
                                    speaker_text = decoded_text
                            if script_lines:
                                if not line_template:
                                    indent_raw = entry.get("indent", 0)
                                    indent = indent_raw if isinstance(
                                        indent_raw, int) else 0
                                    line_template = {
                                        "code": 655,
                                        "indent": indent,
                                        "parameters": [""],
                                    }
                                indent_raw = entry.get("indent", 0)
                                indent = indent_raw if isinstance(
                                    indent_raw, int) else 0
                                line_code_raw = line_template.get("code")
                                line_code = line_code_raw if isinstance(
                                    line_code_raw, int) else 655
                                synthetic_code101 = {
                                    "code": 101,
                                    "indent": indent,
                                    "parameters": [face_name, face_index, background, position, speaker_text],
                                }
                                uid = f"{path.name}:{list_id}:{segment_counter}"
                                segment_counter += 1
                                segment = DialogueSegment(
                                    uid=uid,
                                    context=context,
                                    code101=synthetic_code101,
                                    lines=list(script_lines),
                                    original_lines=list(script_lines),
                                    source_lines=list(script_lines),
                                    code401_template=line_template,
                                    segment_kind="script_message",
                                    line_entry_code=line_code,
                                    script_entries_template=script_templates,
                                    script_entry_roles=script_roles,
                                    script_entry_quotes=script_quotes,
                                    script_entry_expression_templates=script_expression_templates,
                                )
                                tokens.append(CommandToken(
                                    kind="dialogue", segment=segment))
                                segments.append(segment)
                                i = j
                                continue
                    if is_command_entry(entry) and entry.get("code") == 357:
                        plugin_command_segments = _build_plugin_command_text_segments_for_entry(
                            path=path,
                            context=context,
                            list_id=list_id,
                            list_path_tokens=path_tokens,
                            command_index=i,
                            command_entry=entry,
                        )
                        if plugin_command_segments:
                            segments.extend(plugin_command_segments)
                    if is_command_entry(entry):
                        tokens.append(CommandToken(
                            kind="raw", raw_entry=entry))
                        i += 1
                    else:
                        tokens.append(CommandToken(
                            kind="raw", raw_entry=entry))
                        i += 1

                bundles.append(CommandBundle(context=context,
                               commands_ref=value, tokens=tokens))
                return

            for idx, child in enumerate(value):
                walk(child, breadcrumb + [f"[{idx}]"], path_tokens + [idx])

    walk(data, [], [])
    session = FileSession(path=path, data=data,
                          bundles=bundles, segments=segments)

    # Special-case index files so names can be translated in block form.
    name_index_spec = _name_index_spec_for_file(path.name)
    if name_index_spec is not None and isinstance(data, list):
        kind, uid_prefix, label, context_key, fields = name_index_spec
        index_segments: list[DialogueSegment] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            entry_id = row.get("id")
            if not isinstance(entry_id, int) or entry_id <= 0:
                continue
            if kind in {"item", "armor", "weapon"}:
                name_raw = row.get("name")
                description_raw = row.get("description")
                name_text = name_raw if isinstance(name_raw, str) else ""
                description_text = description_raw if isinstance(
                    description_raw, str) else ""
                description_lines = split_lines_preserve_empty(
                    description_text)
                combined_lines = [name_text, ""]
                if description_lines != [""]:
                    combined_lines.extend(description_lines)
                uid = f"{path.name}:{uid_prefix}:{entry_id}"
                code101 = {
                    "code": 101,
                    "indent": 0,
                    "parameters": ["", 0, 0, 2, name_text],
                }
                segment = DialogueSegment(
                    uid=uid,
                    context=f"{path.name} > {context_key}[{entry_id}]",
                    code101=code101,
                    lines=list(combined_lines),
                    original_lines=list(combined_lines),
                    source_lines=list(combined_lines),
                    segment_kind="name_index",
                )
                setattr(segment, "name_index_combined_fields",
                        ("name", "description"))
                index_segments.append(segment)
                continue
            for field_name in fields:
                if field_name not in row:
                    continue
                entry_text_raw = row.get(field_name)
                entry_text = entry_text_raw if isinstance(
                    entry_text_raw, str) else ""
                lines = split_lines_preserve_empty(entry_text)
                uid_suffix = "" if field_name == "name" else f":{field_name}"
                context_suffix = "" if field_name == "name" else f".{field_name}"
                uid = f"{path.name}:{uid_prefix}:{entry_id}{uid_suffix}"
                code101 = {
                    "code": 101,
                    "indent": 0,
                    "parameters": ["", 0, 0, 2, entry_text],
                }
                index_segments.append(
                    DialogueSegment(
                        uid=uid,
                        context=f"{path.name} > {context_key}[{entry_id}]{context_suffix}",
                        code101=code101,
                        lines=list(lines),
                        original_lines=list(lines),
                        source_lines=list(lines),
                        segment_kind="name_index",
                    )
                )
        if index_segments:
            has_dialogue_segments = any(
                segment.segment_kind in {"dialogue", "choice", "script_message"}
                for segment in session.segments
            )
            if has_dialogue_segments:
                session.segments = list(session.segments) + index_segments
                setattr(session, "has_mixed_dialogue_misc_segments", True)
                setattr(session, "has_name_index_segments", True)
                setattr(session, "name_index_uid_prefix", uid_prefix)
                setattr(session, "name_index_label", label)
            else:
                session.segments = index_segments
                setattr(session, "is_name_index_session", True)
                setattr(session, "name_index_kind", kind)
                setattr(session, "name_index_uid_prefix", uid_prefix)
                setattr(session, "name_index_label", label)
                if kind == "actor":
                    setattr(session, "is_actor_index_session", True)

    if path.name.lower() == "system.json" and isinstance(data, dict):
        system_segments = _build_system_text_segments(path, data)
        if system_segments:
            session.segments = system_segments
            setattr(session, "is_name_index_session", True)
            setattr(session, "name_index_kind", "system")
            setattr(session, "name_index_uid_prefix", "Y")
            setattr(session, "name_index_label", "System")
            return session

    map_display_name_segment = _build_map_display_name_segment(path, data)
    if map_display_name_segment is not None:
        session.segments.insert(0, map_display_name_segment)
    note_text_segments = _build_note_text_segments(path, data)
    if note_text_segments:
        session.segments.extend(note_text_segments)

    return session


def parse_dialogue_file(path: Path) -> FileSession:
    if is_plugins_js_path(path):
        data = load_plugins_js_file(path)
        return parse_dialogue_data(path, data)
    if is_tyrano_script_path(path) or is_tyrano_js_path(path):
        data = load_tyrano_script_file(path)
        return parse_dialogue_data(path, data)
    if is_tyrano_config_path(path):
        data = load_tyrano_config_file(path)
        return parse_dialogue_data(path, data)
    with path.open("r", encoding="utf-8") as src:
        data = json.load(src)
    return parse_dialogue_data(path, data)
