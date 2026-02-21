from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActorNameChangeEntry:
    actor_id: int
    name: str
    path_tokens: tuple[Any, ...]


def collect_actor_name_change_entries(data: Any) -> list[ActorNameChangeEntry]:
    entries: list[ActorNameChangeEntry] = []

    def walk(node: Any, path_tokens: tuple[Any, ...]) -> None:
        if isinstance(node, dict):
            code_raw = node.get("code")
            parameters = node.get("parameters")
            if code_raw == 320 and isinstance(parameters, list) and len(parameters) >= 2:
                actor_id_raw = parameters[0]
                name_raw = parameters[1]
                if isinstance(actor_id_raw, int) and actor_id_raw > 0 and isinstance(name_raw, str):
                    entries.append(
                        ActorNameChangeEntry(
                            actor_id=actor_id_raw,
                            name=name_raw,
                            path_tokens=path_tokens + ("parameters", 1),
                        )
                    )
            for key, value in node.items():
                walk(value, path_tokens + (key,))
            return

        if isinstance(node, list):
            for idx, value in enumerate(node):
                walk(value, path_tokens + (idx,))

    walk(data, ())
    return entries
