from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

NO_SPEAKER_KEY = "(none)"


@dataclass
class DialogueSegment:
    uid: str
    context: str
    code101: dict[str, Any]
    lines: list[str]
    original_lines: list[str]
    source_lines: list[str] = field(default_factory=list)
    tl_uid: str = ""
    translation_lines: list[str] = field(default_factory=list)
    original_translation_lines: list[str] = field(default_factory=list)
    translation_speaker: str = ""
    original_translation_speaker: str = ""
    inserted: bool = False
    merged_segments: list["DialogueSegment"] = field(default_factory=list)

    @property
    def params(self) -> list[Any]:
        value = self.code101.get("parameters")
        return value if isinstance(value, list) else []

    @property
    def face_name(self) -> str:
        if len(self.params) > 0 and isinstance(self.params[0], str):
            return self.params[0]
        return ""

    @property
    def face_index(self) -> int:
        if len(self.params) > 1 and isinstance(self.params[1], int):
            return self.params[1]
        return 0

    @property
    def background(self) -> Any:
        return self.params[2] if len(self.params) > 2 else "-"

    @property
    def position(self) -> Any:
        return self.params[3] if len(self.params) > 3 else "-"

    @property
    def speaker_name(self) -> str:
        if len(self.params) > 4 and isinstance(self.params[4], str) and self.params[4].strip():
            return self.params[4].strip()
        return NO_SPEAKER_KEY

    @property
    def has_face(self) -> bool:
        return bool(self.face_name)

    def text_joined(self) -> str:
        return "\n".join(self.lines)

    def original_text_joined(self) -> str:
        return "\n".join(self.original_lines)

    def source_text_joined(self) -> str:
        if self.source_lines:
            return "\n".join(self.source_lines)
        return self.original_text_joined()

    def translation_text_joined(self) -> str:
        return "\n".join(self.translation_lines)


@dataclass
class CommandToken:
    kind: str
    raw_entry: Any = None
    segment: Optional[DialogueSegment] = None


@dataclass
class CommandBundle:
    context: str
    commands_ref: list[Any]
    tokens: list[CommandToken]


@dataclass
class FileSession:
    path: Path
    data: Any
    bundles: list[CommandBundle]
    segments: list[DialogueSegment]
    dirty: bool = False


@dataclass
class DeletedBlockAction:
    path: Path
    uid: str
    bundle_index: int
    token_index: int
    segment_index: int
    segment: DialogueSegment


@dataclass
class InsertedBlockAction:
    path: Path
    uid: str
    bundle_index: int
    token_index: int
    segment_index: int
    segment: DialogueSegment


@dataclass
class MergeBlocksAction:
    path: Path
    left_uid: str
    right_uid: str
    left_lines_before: list[str]
    left_lines_after: list[str]
    left_merged_before: list[DialogueSegment]
    right_segment: DialogueSegment
    left_translation_before: list[str] = field(default_factory=list)
    left_translation_after: list[str] = field(default_factory=list)
    left_speaker_translation_before: str = ""
    left_speaker_translation_after: str = ""


@dataclass
class ResetBlockAction:
    path: Path
    uid: str
    lines_before: list[str]
    lines_after: list[str]
    merged_before: list[DialogueSegment]
    restored_segments: list[DialogueSegment]


@dataclass
class SplitOverflowAction:
    path: Path
    source_uid: str
    moved_uid: str
    source_lines_before: list[str]
    source_lines_after: list[str]
    moved_segment: DialogueSegment
    source_translation_before: list[str] = field(default_factory=list)
    source_translation_after: list[str] = field(default_factory=list)


@dataclass
class StructuralAction:
    kind: str
    path: Path
    data: Any
