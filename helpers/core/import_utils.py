from __future__ import annotations

from difflib import SequenceMatcher

from .models import DialogueSegment


def _uid_group(uid: str) -> str:
    if ":" not in uid:
        return uid
    return uid.rsplit(":", 1)[0]


def segment_alignment_key(segment: DialogueSegment) -> tuple[object, ...]:
    script_roles = tuple(
        role for role in segment.script_entry_roles if isinstance(role, str)
    )
    return (
        _uid_group(segment.uid),
        segment.segment_kind,
        segment.context,
        segment.face_name,
        int(segment.face_index),
        str(segment.background),
        str(segment.position),
        int(segment.line_entry_code),
        len(segment.choice_branch_entries),
        script_roles,
    )


def align_source_translated_segments(
    source_segments: list[DialogueSegment],
    translated_segments: list[DialogueSegment],
) -> tuple[list[tuple[int, int]], dict[int, list[int]]]:
    if not source_segments or not translated_segments:
        return [], {}

    translated_index_by_uid: dict[str, int] = {}
    duplicate_uid = False
    for idx, segment in enumerate(translated_segments):
        if segment.uid in translated_index_by_uid:
            duplicate_uid = True
            break
        translated_index_by_uid[segment.uid] = idx
    if not duplicate_uid and len(source_segments) == len(translated_segments):
        direct_pairs: list[tuple[int, int]] = []
        for source_idx, source_segment in enumerate(source_segments):
            translated_idx = translated_index_by_uid.get(source_segment.uid)
            if translated_idx is None:
                direct_pairs = []
                break
            direct_pairs.append((source_idx, translated_idx))
        if direct_pairs and len(direct_pairs) == len(source_segments):
            return direct_pairs, {}

    source_keys = [segment_alignment_key(segment) for segment in source_segments]
    translated_keys = [
        segment_alignment_key(segment) for segment in translated_segments
    ]
    matcher = SequenceMatcher(None, source_keys, translated_keys, autojunk=False)

    mapped_pairs: list[tuple[int, int]] = []
    translated_inserts: dict[int, list[int]] = {}
    used_translated: set[int] = set()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                source_idx = i1 + offset
                translated_idx = j1 + offset
                mapped_pairs.append((source_idx, translated_idx))
                used_translated.add(translated_idx)
            continue

        if tag == "insert":
            anchor = i1 - 1
            anchor = max(-1, min(anchor, len(source_segments) - 1))
            translated_inserts.setdefault(anchor, []).extend(range(j1, j2))
            continue

        if tag == "replace":
            overlap = min(i2 - i1, j2 - j1)
            for offset in range(overlap):
                source_idx = i1 + offset
                translated_idx = j1 + offset
                mapped_pairs.append((source_idx, translated_idx))
                used_translated.add(translated_idx)
            if j2 - j1 > overlap:
                anchor = i1 + overlap - 1 if overlap > 0 else i1 - 1
                anchor = max(-1, min(anchor, len(source_segments) - 1))
                translated_inserts.setdefault(anchor, []).extend(
                    range(j1 + overlap, j2)
                )
            continue

        # delete: source-only rows have no translated counterpart.

    mapped_pairs.sort(key=lambda pair: pair[0])
    inserted_translated: set[int] = set()
    for translated_indexes in translated_inserts.values():
        inserted_translated.update(translated_indexes)
    unassigned = [
        idx
        for idx in range(len(translated_segments))
        if idx not in used_translated and idx not in inserted_translated
    ]
    if unassigned:
        tail_anchor = len(source_segments) - 1
        translated_inserts.setdefault(tail_anchor, []).extend(unassigned)

    if not mapped_pairs:
        count = min(len(source_segments), len(translated_segments))
        mapped_pairs = [(idx, idx) for idx in range(count)]
        if len(translated_segments) > count:
            fallback_anchor = count - 1
            translated_inserts.setdefault(fallback_anchor, []).extend(
                range(count, len(translated_segments))
            )

    return mapped_pairs, translated_inserts
