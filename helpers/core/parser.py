from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .models import CommandBundle, CommandToken, DialogueSegment, FileSession
from .script_message_utils import (
    parse_game_message_call,
    parse_game_message_set_background_call,
    parse_game_message_set_face_image_call,
    parse_game_message_set_position_type_call,
)
from .text_utils import first_parameter_text, is_command_entry, split_lines_preserve_empty


def _name_index_spec_for_file(path_name: str) -> tuple[str, str, str, str, tuple[str, ...]] | None:
    lowered = path_name.lower()
    if lowered == "actors.json":
        return ("actor", "A", "Actor", "actor", ("name",))
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
_MAP_FILE_NAME_RE = re.compile(r"^map\d+\.json$", re.IGNORECASE)


def is_plugins_js_path(path: Path) -> bool:
    return path.name.strip().lower() == "plugins.js"


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

    bundles: list[CommandBundle] = []
    segments: list[DialogueSegment] = []
    list_counter = 0
    segment_counter = 0

    def walk(value: Any, breadcrumb: list[str]) -> None:
        nonlocal list_counter, segment_counter
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, breadcrumb + [str(key)])
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
                                    face_parsed = parse_game_message_set_face_image_call(
                                        text
                                    )
                                    if face_parsed is not None:
                                        script_roles.append("face")
                                        script_quotes.append('"')
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
                                        try:
                                            position = int(position_parsed)
                                        except Exception:
                                            position = 2
                                        continue
                                    script_roles.append("other")
                                    script_quotes.append('"')
                                    continue
                                call_kind, decoded_text, quote_char = parsed
                                if call_kind == "add":
                                    script_roles.append("add")
                                    script_quotes.append(quote_char)
                                    script_lines.append(decoded_text)
                                    if not line_template:
                                        line_template = copy.deepcopy(
                                            script_entry)
                                else:
                                    script_roles.append("speaker")
                                    script_quotes.append(quote_char)
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
                                )
                                tokens.append(CommandToken(
                                    kind="dialogue", segment=segment))
                                segments.append(segment)
                                i = j
                                continue
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
                walk(child, breadcrumb + [f"[{idx}]"])

    walk(data, [])
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

    return session


def parse_dialogue_file(path: Path) -> FileSession:
    if is_plugins_js_path(path):
        data = load_plugins_js_file(path)
        return parse_dialogue_data(path, data)
    with path.open("r", encoding="utf-8") as src:
        data = json.load(src)
    return parse_dialogue_data(path, data)
