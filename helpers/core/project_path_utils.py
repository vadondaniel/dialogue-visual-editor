from __future__ import annotations

import re
from pathlib import Path

_MAP_FILE_NAME_RE = re.compile(r"^map\d+\.json$", re.IGNORECASE)
_RPG_MARKER_FILES = frozenset(
    {
        "system.json",
        "mapinfos.json",
        "actors.json",
        "items.json",
    }
)


def _dedup_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _folder_file_names_lower(folder: Path) -> set[str]:
    names: set[str] = set()
    try:
        for child in folder.iterdir():
            if child.is_file():
                names.add(child.name.lower())
    except Exception:
        return set()
    return names


def looks_like_rpg_data_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    file_names = _folder_file_names_lower(folder)
    if not file_names:
        return False
    if file_names.intersection(_RPG_MARKER_FILES):
        return True
    return any(_MAP_FILE_NAME_RE.fullmatch(name) is not None for name in file_names)


def _contains_ks_files(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    try:
        next(folder.rglob("*.ks"))
        return True
    except StopIteration:
        return False
    except Exception:
        return False


def looks_like_tyrano_data_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    scenario_dir = folder / "scenario"
    if not scenario_dir.is_dir():
        return False
    return _contains_ks_files(scenario_dir)


def candidate_project_data_folders(selected_folder: Path) -> list[Path]:
    try:
        selected = selected_folder.resolve()
    except Exception:
        selected = selected_folder

    candidates: list[Path] = [
        selected,
        selected / "data",
        selected / "www" / "data",
        selected / "resources" / "app" / "data",
        selected / "app" / "data",
    ]

    if selected.name.strip().lower() == "www":
        candidates.insert(1, selected / "data")
    if selected.name.strip().lower() == "scenario":
        candidates.insert(1, selected.parent)

    return _dedup_paths(candidates)


def resolve_project_data_folder(selected_folder: Path) -> Path:
    candidates = candidate_project_data_folders(selected_folder)

    for candidate in candidates:
        if looks_like_rpg_data_folder(candidate):
            return candidate

    for candidate in candidates:
        if looks_like_tyrano_data_folder(candidate):
            return candidate

    try:
        return selected_folder.resolve()
    except Exception:
        return selected_folder
