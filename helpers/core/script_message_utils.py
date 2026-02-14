from __future__ import annotations

import re

_GAME_MESSAGE_PREFIX_RE = re.compile(
    r"^\s*\$gameMessage\.(add|setSpeakerName)\s*\(")
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


def build_game_message_call(kind: str, text: str, quote_char: str = '"') -> str:
    call_kind = kind.strip()
    if call_kind not in {"add", "setSpeakerName"}:
        call_kind = "add"
    quote = quote_char if quote_char in {'"', "'"} else '"'
    encoded_value = _encode_js_string_literal(text, quote)
    return f"$gameMessage.{call_kind}({quote}{encoded_value}{quote});"
