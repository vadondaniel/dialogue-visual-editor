from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .models import CommandBundle, CommandToken, DialogueSegment, FileSession
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
