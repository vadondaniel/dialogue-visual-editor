from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .models import CommandBundle, CommandToken, DialogueSegment, FileSession
from .script_message_utils import parse_game_message_call
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
                            line_template: dict[str, Any] = {}
                            for script_entry in script_entries:
                                text = first_parameter_text(script_entry)
                                parsed = parse_game_message_call(text)
                                if parsed is None:
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
                                    "parameters": ["", 0, 0, 2, speaker_text],
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
                    )
                )
        if index_segments:
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


def parse_dialogue_file(path: Path) -> FileSession:
    with path.open("r", encoding="utf-8") as src:
        data = json.load(src)
    return parse_dialogue_data(path, data)
