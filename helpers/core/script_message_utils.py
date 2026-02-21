from __future__ import annotations

import re

_GAME_MESSAGE_PREFIX_RE = re.compile(
    r"^\s*\$gameMessage\.(add|setSpeakerName)\s*\(")
_GAME_MESSAGE_FACE_PREFIX_RE = re.compile(
    r"^\s*\$gameMessage\.setFaceImage\s*\(")
_GAME_MESSAGE_BACKGROUND_PREFIX_RE = re.compile(
    r"^\s*\$gameMessage\.setBackground\s*\(")
_GAME_MESSAGE_POSITION_PREFIX_RE = re.compile(
    r"^\s*\$gameMessage\.setPositionType\s*\(")
_GAME_MESSAGE_EXPR_PLACEHOLDER_RE = re.compile(r"\{\{EXPR(\d+)\}\}")
_HEX_DIGITS = set("0123456789abcdefABCDEF")


def _decode_js_string_literal(raw: str) -> str:
    chars: list[str] = []
    idx = 0
    length = len(raw)
    while idx < length:
        ch = raw[idx]
        if ch != "\\":
            chars.append(ch)
            idx += 1
            continue
        idx += 1
        if idx >= length:
            chars.append("\\")
            break
        esc = raw[idx]
        if esc in {"\\", '"', "'", "/"}:
            chars.append(esc)
            idx += 1
            continue
        if esc == "n":
            chars.append("\n")
            idx += 1
            continue
        if esc == "r":
            chars.append("\r")
            idx += 1
            continue
        if esc == "t":
            chars.append("\t")
            idx += 1
            continue
        if esc == "b":
            chars.append("\b")
            idx += 1
            continue
        if esc == "f":
            chars.append("\f")
            idx += 1
            continue
        if esc == "v":
            chars.append("\v")
            idx += 1
            continue
        if esc == "0":
            chars.append("\0")
            idx += 1
            continue
        if esc == "x" and idx + 2 < length:
            hex_value = raw[idx + 1: idx + 3]
            if all(c in _HEX_DIGITS for c in hex_value):
                chars.append(chr(int(hex_value, 16)))
                idx += 3
                continue
        if esc == "u" and idx + 4 < length:
            hex_value = raw[idx + 1: idx + 5]
            if all(c in _HEX_DIGITS for c in hex_value):
                chars.append(chr(int(hex_value, 16)))
                idx += 5
                continue
        chars.append(esc)
        idx += 1
    return "".join(chars)


def _encode_js_string_literal(text: str, quote_char: str) -> str:
    encoded: list[str] = []
    for ch in text:
        if ch == "\\":
            encoded.append("\\\\")
        elif ch == quote_char:
            encoded.append("\\" + quote_char)
        elif ch == "\n":
            encoded.append("\\n")
        elif ch == "\r":
            encoded.append("\\r")
        elif ch == "\t":
            encoded.append("\\t")
        elif ch == "\b":
            encoded.append("\\b")
        elif ch == "\f":
            encoded.append("\\f")
        elif ch == "\v":
            encoded.append("\\v")
        elif ch == "\0":
            encoded.append("\\0")
        else:
            codepoint = ord(ch)
            if codepoint < 0x20:
                encoded.append(f"\\u{codepoint:04x}")
            else:
                encoded.append(ch)
    return "".join(encoded)


def parse_game_message_call(line: str) -> tuple[str, str, str] | None:
    match = _GAME_MESSAGE_PREFIX_RE.match(line)
    if match is None:
        return None
    call_kind = match.group(1)
    idx = match.end()
    line_len = len(line)

    while idx < line_len and line[idx].isspace():
        idx += 1
    if idx >= line_len:
        return None
    quote_char = line[idx]
    if quote_char not in {'"', "'"}:
        return None

    idx += 1
    raw_value_chars: list[str] = []
    while idx < line_len:
        ch = line[idx]
        if ch == "\\":
            if idx + 1 >= line_len:
                return None
            raw_value_chars.append(ch)
            raw_value_chars.append(line[idx + 1])
            idx += 2
            continue
        if ch == quote_char:
            idx += 1
            break
        raw_value_chars.append(ch)
        idx += 1
    else:
        return None

    while idx < line_len and line[idx].isspace():
        idx += 1
    if idx >= line_len or line[idx] != ")":
        return None
    idx += 1
    while idx < line_len and line[idx].isspace():
        idx += 1
    if idx < line_len and line[idx] == ";":
        idx += 1
    while idx < line_len and line[idx].isspace():
        idx += 1
    if idx != line_len:
        return None

    raw_value = "".join(raw_value_chars)
    decoded_value = _decode_js_string_literal(raw_value)
    return call_kind, decoded_value, quote_char


def _split_top_level_plus_expression(expression: str) -> list[str]:
    terms: list[str] = []
    chars: list[str] = []
    quote_char = ""
    escape_next = False
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0

    for ch in expression:
        if escape_next:
            chars.append(ch)
            escape_next = False
            continue
        if quote_char:
            chars.append(ch)
            if ch == "\\":
                escape_next = True
                continue
            if ch == quote_char:
                quote_char = ""
            continue
        if ch in {'"', "'"}:
            quote_char = ch
            chars.append(ch)
            continue
        if ch == "(":
            paren_depth += 1
            chars.append(ch)
            continue
        if ch == ")":
            paren_depth = max(0, paren_depth - 1)
            chars.append(ch)
            continue
        if ch == "[":
            bracket_depth += 1
            chars.append(ch)
            continue
        if ch == "]":
            bracket_depth = max(0, bracket_depth - 1)
            chars.append(ch)
            continue
        if ch == "{":
            brace_depth += 1
            chars.append(ch)
            continue
        if ch == "}":
            brace_depth = max(0, brace_depth - 1)
            chars.append(ch)
            continue
        if ch == "+" and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
            part = "".join(chars).strip()
            if part:
                terms.append(part)
            chars = []
            continue
        chars.append(ch)

    tail = "".join(chars).strip()
    if tail:
        terms.append(tail)
    return terms


def _decode_js_string_term(term: str) -> tuple[str, str] | None:
    stripped = term.strip()
    if len(stripped) < 2:
        return None
    quote_char = stripped[0]
    if quote_char not in {'"', "'"}:
        return None
    if stripped[-1] != quote_char:
        return None
    return _decode_js_string_literal(stripped[1:-1]), quote_char


def _encode_js_string_term(text: str, quote_char: str) -> str:
    encoded = _encode_js_string_literal(text, quote_char)
    return f"{quote_char}{encoded}{quote_char}"


def parse_game_message_templated_call(
    line: str,
) -> tuple[str, str, str, list[str]] | None:
    match = _GAME_MESSAGE_PREFIX_RE.match(line)
    if match is None:
        return None
    call_kind = match.group(1)
    args_raw = _parse_game_message_arguments(line, _GAME_MESSAGE_PREFIX_RE)
    if not args_raw:
        return None
    if _has_top_level_comma(args_raw):
        return None

    terms = _split_top_level_plus_expression(args_raw)
    if len(terms) <= 1:
        return None

    display_parts: list[str] = []
    expression_terms: list[str] = []
    quote_char = '"'
    saw_string_literal = False
    saw_expression = False

    for term in terms:
        decoded_term = _decode_js_string_term(term)
        if decoded_term is not None:
            decoded_text, decoded_quote = decoded_term
            saw_string_literal = True
            quote_char = decoded_quote
            display_parts.append(decoded_text)
            continue
        cleaned_expression = term.strip()
        if not cleaned_expression:
            continue
        saw_expression = True
        expression_terms.append(cleaned_expression)
        display_parts.append(f"{{{{EXPR{len(expression_terms)}}}}}")

    if not saw_string_literal or not saw_expression:
        return None

    return call_kind, "".join(display_parts), quote_char, expression_terms


def parse_game_message_set_face_image_call(line: str) -> tuple[str, str] | None:
    args_raw = _parse_game_message_arguments(line, _GAME_MESSAGE_FACE_PREFIX_RE)
    if not args_raw:
        return None

    split_index = -1
    nested_depth = 0
    current_quote = ""
    escaped = False
    for arg_idx, ch in enumerate(args_raw):
        if escaped:
            escaped = False
            continue
        if current_quote:
            if ch == "\\":
                escaped = True
                continue
            if ch == current_quote:
                current_quote = ""
            continue
        if ch in {'"', "'"}:
            current_quote = ch
            continue
        if ch == "(":
            nested_depth += 1
            continue
        if ch == ")":
            nested_depth = max(0, nested_depth - 1)
            continue
        if ch == "," and nested_depth == 0:
            split_index = arg_idx
            break
    if split_index < 0:
        return None

    face_raw = args_raw[:split_index].strip()
    index_raw = args_raw[split_index + 1:].strip()
    if not face_raw:
        return None
    if not index_raw:
        return None

    if len(face_raw) >= 2 and face_raw[0] in {'"', "'"} and face_raw[-1] == face_raw[0]:
        face_name = _decode_js_string_literal(face_raw[1:-1])
    else:
        face_name = face_raw
    return face_name, index_raw


def parse_game_message_set_background_call(line: str) -> str | None:
    args_raw = _parse_game_message_arguments(line, _GAME_MESSAGE_BACKGROUND_PREFIX_RE)
    if not args_raw:
        return None
    if _has_top_level_comma(args_raw):
        return None
    return args_raw


def parse_game_message_set_position_type_call(line: str) -> str | None:
    args_raw = _parse_game_message_arguments(line, _GAME_MESSAGE_POSITION_PREFIX_RE)
    if not args_raw:
        return None
    if _has_top_level_comma(args_raw):
        return None
    return args_raw


def _parse_game_message_arguments(line: str, prefix_re: re.Pattern[str]) -> str | None:
    match = prefix_re.match(line)
    if match is None:
        return None
    idx = match.end()
    line_len = len(line)
    args_chars: list[str] = []
    depth = 1
    quote_char = ""
    escape_next = False

    while idx < line_len:
        ch = line[idx]
        idx += 1
        if escape_next:
            args_chars.append(ch)
            escape_next = False
            continue
        if quote_char:
            args_chars.append(ch)
            if ch == "\\":
                escape_next = True
                continue
            if ch == quote_char:
                quote_char = ""
            continue
        if ch in {'"', "'"}:
            quote_char = ch
            args_chars.append(ch)
            continue
        if ch == "(":
            depth += 1
            args_chars.append(ch)
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                break
            args_chars.append(ch)
            continue
        args_chars.append(ch)
    if depth != 0:
        return None

    while idx < line_len and line[idx].isspace():
        idx += 1
    if idx < line_len and line[idx] == ";":
        idx += 1
    while idx < line_len and line[idx].isspace():
        idx += 1
    if idx != line_len:
        return None

    return "".join(args_chars).strip()


def _has_top_level_comma(args_raw: str) -> bool:
    depth = 0
    quote_char = ""
    escape_next = False
    for ch in args_raw:
        if escape_next:
            escape_next = False
            continue
        if quote_char:
            if ch == "\\":
                escape_next = True
                continue
            if ch == quote_char:
                quote_char = ""
            continue
        if ch in {'"', "'"}:
            quote_char = ch
            continue
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            continue
        if ch == "," and depth == 0:
            return True
    return False


def build_game_message_call(kind: str, text: str, quote_char: str = '"') -> str:
    call_kind = kind.strip()
    if call_kind not in {"add", "setSpeakerName"}:
        call_kind = "add"
    quote = quote_char if quote_char in {'"', "'"} else '"'
    encoded_value = _encode_js_string_literal(text, quote)
    return f"$gameMessage.{call_kind}({quote}{encoded_value}{quote});"


def build_game_message_templated_call(
    kind: str,
    text: str,
    quote_char: str = '"',
    expression_terms: list[str] | None = None,
) -> str:
    call_kind = kind.strip()
    if call_kind not in {"add", "setSpeakerName"}:
        call_kind = "add"
    quote = quote_char if quote_char in {'"', "'"} else '"'
    expr_terms = [
        term.strip()
        for term in (expression_terms or [])
        if isinstance(term, str) and term.strip()
    ]
    if not expr_terms:
        return build_game_message_call(call_kind, text, quote)

    parts: list[str] = []
    used_indexes: set[int] = set()
    cursor = 0
    for match in _GAME_MESSAGE_EXPR_PLACEHOLDER_RE.finditer(text):
        literal = text[cursor: match.start()]
        if literal:
            parts.append(_encode_js_string_term(literal, quote))
        cursor = match.end()
        try:
            index = int(match.group(1)) - 1
        except Exception:
            index = -1
        if 0 <= index < len(expr_terms):
            parts.append(expr_terms[index])
            used_indexes.add(index)
        else:
            parts.append(_encode_js_string_term(match.group(0), quote))

    trailing_literal = text[cursor:]
    if trailing_literal:
        parts.append(_encode_js_string_term(trailing_literal, quote))

    # Preserve source expressions even if translator removed placeholders.
    for index, expression in enumerate(expr_terms):
        if index not in used_indexes:
            parts.append(expression)

    if not parts:
        parts.append(_encode_js_string_term("", quote))
    joined_args = " + ".join(parts)
    return f"$gameMessage.{call_kind}({joined_args});"
