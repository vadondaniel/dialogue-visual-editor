from __future__ import annotations

import unittest
from pathlib import Path
import re
from typing import Any

from dialogue_visual_editor.helpers.audit.audit_consistency_mixin import (
    AuditConsistencyMixin,
)
from dialogue_visual_editor.helpers.audit.audit_core_mixin import AuditCoreMixin
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(
    uid: str,
    source_text: str,
    tl_text: str,
    *,
    segment_kind: str = "dialogue",
) -> DialogueSegment:
    source_lines = source_text.split("\n") if source_text else [""]
    tl_lines = tl_text.split("\n") if tl_text else [""]
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(source_lines),
        original_lines=list(source_lines),
        source_lines=list(source_lines),
        segment_kind=segment_kind,
        translation_lines=list(tl_lines),
        original_translation_lines=list(tl_lines),
    )


class _Harness(AuditConsistencyMixin):
    _NAME_INDEX_UID_RE = re.compile(r":[A-Za-z]:(\d+)(?::([A-Za-z0-9_]+))?$")
    _normalize_audit_translation_lines_for_segment = (
        AuditCoreMixin._normalize_audit_translation_lines_for_segment
    )

    def __init__(self) -> None:
        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}
        self._speaker_map: dict[str, str] = {}
        self.audit_consistency_entries_list: Any = None
        self.audit_consistency_neighbors_check: Any = None
        self.audit_consistency_neighbors_edit: Any = None
        self.audit_consistency_target_edit: Any = None
        self._source_label = "JA"
        self._target_label = "EN-US"

    @staticmethod
    def _segment_source_lines_for_display(segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    @staticmethod
    def _is_name_index_session(session: FileSession) -> bool:
        return bool(getattr(session, "is_name_index_session", False))

    @staticmethod
    def _name_index_kind(session: FileSession) -> str:
        raw = getattr(session, "name_index_kind", "")
        if isinstance(raw, str):
            return raw.strip().lower()
        return ""

    def _name_index_label(self, session: FileSession) -> str:
        raw = getattr(session, "name_index_label", "")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        kind = self._name_index_kind(session)
        if kind == "actor":
            return "Actor"
        if kind == "mapinfo":
            return "Map"
        return "Entry"

    def _actor_id_from_uid(self, uid: str) -> int | None:
        match = self._NAME_INDEX_UID_RE.search(uid)
        if match is None:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def _name_index_field_from_uid(self, uid: str) -> str:
        match = self._NAME_INDEX_UID_RE.search(uid)
        if match is None:
            return "name"
        raw_field = match.group(2)
        if isinstance(raw_field, str) and raw_field.strip():
            return raw_field.strip().lower()
        return "name"

    def _actor_name_maps(self) -> tuple[dict[int, str], dict[int, str]]:
        jp_by_id: dict[int, str] = {}
        en_by_id: dict[int, str] = {}
        for session in self.sessions.values():
            if not self._is_name_index_session(session):
                continue
            if self._name_index_kind(session) != "actor":
                continue
            for segment in session.segments:
                actor_id = self._actor_id_from_uid(segment.uid)
                if actor_id is None:
                    continue
                field_name = self._name_index_field_from_uid(segment.uid)
                if field_name != "name":
                    continue
                source = "\n".join(self._segment_source_lines_for_display(segment)).strip()
                if source:
                    jp_by_id[actor_id] = source
                translation = "\n".join(self._normalize_translation_lines(segment.translation_lines)).strip()
                if translation:
                    en_by_id[actor_id] = translation
        return jp_by_id, en_by_id

    def _audit_entry_text_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
        index: int,
    ) -> str:
        if self._is_name_index_session(session):
            name_index_label = self._name_index_label(session)
            actor_id = self._actor_id_from_uid(segment.uid)
            if actor_id is not None:
                return f"{name_index_label} ID {actor_id}"
            return f"{name_index_label} {index}"
        if segment.segment_kind == "map_display_name":
            return "Map displayName"
        block_index = 0
        for candidate in session.segments:
            if candidate.segment_kind == "map_display_name":
                continue
            block_index += 1
            if candidate.uid == segment.uid:
                return f"Block {block_index}"
        return f"Block {index}"

    @staticmethod
    def _normalize_speaker_key(value: str) -> str:
        cleaned = (value or "").strip()
        return cleaned if cleaned else "(none)"

    def _speaker_translation_for_key(self, speaker_key: str) -> str:
        return self._speaker_map.get(speaker_key, "")

    @staticmethod
    def _speaker_key_for_segment(segment: DialogueSegment) -> str:
        return segment.speaker_name

    @staticmethod
    def _relative_path(path: Path) -> str:
        return str(path)

    def _translation_project_source_language_label(self) -> str:
        return self._source_label

    def _translation_profile_target_language_label(self) -> str:
        return self._target_label


class AuditConsistencyMixinTests(unittest.TestCase):
    def test_collect_groups_normalizes_tyrano_inline_r_markers(self) -> None:
        harness = _Harness()
        path = Path("scene.ks")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("scene.ks:K:1", "同一文", "Line A[r]Line B", segment_kind="tyrano_dialogue"),
                _segment("scene.ks:K:2", "同一文", "Line A\nLine B", segment_kind="tyrano_dialogue"),
            ],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(groups, [])

    def test_dialogue_only_excludes_non_dialogue_sources(self) -> None:
        harness = _Harness()
        path = Path("Mixed.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "重複語", "Alpha", segment_kind="dialogue"),
                _segment("d2", "重複語", "Beta", segment_kind="dialogue"),
                _segment("n1", "重複語", "Gamma", segment_kind="name_index"),
            ],
        )

        groups_dialogue_only = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=True,
            sort_mode="source_order",
        )
        groups_all = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups_dialogue_only), 1)
        self.assertEqual(int(groups_dialogue_only[0]["entry_count"]), 2)
        self.assertEqual(len(groups_all), 1)
        self.assertEqual(int(groups_all[0]["entry_count"]), 3)

    def test_dialogue_only_can_hide_non_dialogue_only_duplicates(self) -> None:
        harness = _Harness()
        path = Path("System.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("s1", "通貨単位", "Gold", segment_kind="system_text"),
                _segment("s2", "通貨単位", "Coin", segment_kind="system_text"),
            ],
        )

        groups_dialogue_only = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=True,
            sort_mode="source_order",
        )
        groups_all = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(groups_dialogue_only, [])
        self.assertEqual(len(groups_all), 1)

    def test_entry_labels_skip_map_display_name_in_block_numbering(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("map", "共通語", "Village", segment_kind="map_display_name"),
                _segment("d1", "共通語", "Village A", segment_kind="dialogue"),
                _segment("d2", "共通語", "Village B", segment_kind="dialogue"),
            ],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        entries = [str(entry["entry"]) for entry in groups[0]["entries"]]
        self.assertIn("Map displayName", entries)
        self.assertIn("Block 1", entries)
        self.assertIn("Block 2", entries)
        self.assertNotIn("Block 3", entries)

    def test_collect_groups_includes_speaker_fields(self) -> None:
        harness = _Harness()
        harness._speaker_map["勇者"] = "Hero"
        path = Path("Map001.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "共通語", "Alpha"),
                _segment("d2", "共通語", "Beta"),
            ],
        )
        harness.sessions[path].segments[0].code101["parameters"][4] = "勇者"
        harness.sessions[path].segments[1].code101["parameters"][4] = "勇者"

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        first_entry = groups[0]["entries"][0]
        self.assertEqual(first_entry["speaker_jp"], "勇者")
        self.assertEqual(first_entry["speaker_en"], "Hero")

    def test_collect_groups_merge_name_index_kinds_for_same_source_and_keep_labels(self) -> None:
        harness = _Harness()
        actor_path = Path("Actors.json")
        map_path = Path("MapInfos.json")
        harness.file_paths = [actor_path, map_path]

        actor_session = FileSession(
            path=actor_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Actors.json:A:1", "ユウヤ", "Yuya", segment_kind="name_index"),
                _segment("Actors.json:A:2", "ユウヤ", "", segment_kind="name_index"),
            ],
        )
        setattr(actor_session, "is_name_index_session", True)
        setattr(actor_session, "name_index_kind", "actor")
        setattr(actor_session, "name_index_label", "Actor")
        harness.sessions[actor_path] = actor_session

        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("MapInfos.json:M:21", "ユウヤ", "Yuya", segment_kind="name_index"),
                _segment("MapInfos.json:M:22", "ユウヤ", "Yuya", segment_kind="name_index"),
            ],
        )
        setattr(map_session, "is_name_index_session", True)
        setattr(map_session, "name_index_kind", "mapinfo")
        setattr(map_session, "name_index_label", "Map")
        harness.sessions[map_path] = map_session

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        label_hint = str(groups[0].get("label_hint", ""))
        self.assertIn("Actor", label_hint)
        self.assertIn("Map", label_hint)

    def test_collect_groups_treats_inherited_actor_alias_translation_as_non_empty(self) -> None:
        harness = _Harness()
        actor_path = Path("Actors.json")
        harness.file_paths = [actor_path]
        session = FileSession(
            path=actor_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Actors.json:A:1", "ユウヤ", "Yuya", segment_kind="name_index"),
                _segment("Actors.json:A:1:alt_1", "ユウヤ", "", segment_kind="actor_name_alias"),
            ],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_kind", "actor")
        setattr(session, "name_index_label", "Actor")
        setattr(session.segments[1], "is_actor_name_alias", True)
        setattr(session.segments[1], "actor_alias_actor_id", 1)
        harness.sessions[actor_path] = session

        groups_inconsistent = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=False,
            sort_mode="source_order",
        )
        groups_all = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(groups_inconsistent, [])
        self.assertEqual(len(groups_all), 1)
        self.assertEqual(int(groups_all[0]["variant_count"]), 1)
        translations = {str(entry["translation"]) for entry in groups_all[0]["entries"]}
        self.assertEqual(translations, {"Yuya"})

    def test_collect_groups_treats_peer_actor_alias_translation_as_non_empty(self) -> None:
        harness = _Harness()
        actor_path = Path("Actors.json")
        harness.file_paths = [actor_path]
        session = FileSession(
            path=actor_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Actors.json:A:1:alt_1", "ユウカ", "Yuka", segment_kind="actor_name_alias"),
                _segment("Actors.json:A:1:alt_2", "ユウカ", "", segment_kind="actor_name_alias"),
                _segment("Actors.json:A:1:alt_3", "ユウカ", "", segment_kind="actor_name_alias"),
            ],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_kind", "actor")
        setattr(session, "name_index_label", "Actor")
        for segment in session.segments:
            setattr(segment, "is_actor_name_alias", True)
            setattr(segment, "actor_alias_actor_id", 1)
        harness.sessions[actor_path] = session

        groups_inconsistent = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=False,
            sort_mode="source_order",
        )
        groups_all = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=False,
            sort_mode="source_order",
        )

        self.assertEqual(groups_inconsistent, [])
        self.assertEqual(len(groups_all), 1)
        self.assertEqual(int(groups_all[0]["variant_count"]), 1)
        translations = {str(entry["translation"]) for entry in groups_all[0]["entries"]}
        self.assertEqual(translations, {"Yuka"})

    def test_dialogue_groups_share_group_across_map_and_common_events(self) -> None:
        harness = _Harness()
        map_path = Path("Map0027.json")
        common_events_path = Path("CommonEvents.json")
        harness.file_paths = [map_path, common_events_path]
        harness.sessions[map_path] = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Map0027.json:1:10", "同一台詞", "One", segment_kind="dialogue"),
            ],
        )
        harness.sessions[common_events_path] = FileSession(
            path=common_events_path,
            data=[],
            bundles=[],
            segments=[
                _segment("CommonEvents.json:3:4", "同一台詞", "Two", segment_kind="dialogue"),
            ],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=True,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(int(groups[0]["entry_count"]), 2)
        self.assertEqual(str(groups[0].get("label_hint", "")), "")

    def test_consistency_entry_label_includes_non_name_field_suffix(self) -> None:
        harness = _Harness()
        path = Path("Actors.json")
        session = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("Actors.json:A:1", "ユウヤ", "Yuya", segment_kind="name_index"),
                _segment("Actors.json:A:1:nickname", "ユウヤ", "", segment_kind="name_index"),
            ],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_kind", "actor")
        setattr(session, "name_index_label", "Actor")

        name_label = harness._consistency_entry_label(session, session.segments[0], 1)
        nickname_label = harness._consistency_entry_label(session, session.segments[1], 2)

        self.assertEqual(name_label, "Actor ID 1")
        self.assertEqual(nickname_label, "Actor ID 1 (nickname)")

    def test_selecting_empty_entry_keeps_non_empty_target_draft(self) -> None:
        harness = _Harness()

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeList:
            def __init__(self, item: _FakeItem) -> None:
                self._item = item

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTextEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        harness.audit_consistency_entries_list = _FakeList(
            _FakeItem({"translation": ""})
        )
        harness.audit_consistency_target_edit = _FakeTextEdit("Yuya")
        harness._refresh_audit_consistency_target_overflow_status = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_neighbors_preview = lambda: None  # type: ignore[method-assign]

        harness._on_audit_consistency_entry_selected()

        self.assertEqual(harness.audit_consistency_target_edit.toPlainText(), "Yuya")

    def test_selecting_empty_entry_sets_target_when_current_target_is_empty(self) -> None:
        harness = _Harness()

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeList:
            def __init__(self, item: _FakeItem) -> None:
                self._item = item

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTextEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        harness.audit_consistency_entries_list = _FakeList(
            _FakeItem({"translation": ""})
        )
        harness.audit_consistency_target_edit = _FakeTextEdit("")
        harness._refresh_audit_consistency_target_overflow_status = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_neighbors_preview = lambda: None  # type: ignore[method-assign]

        harness._on_audit_consistency_entry_selected()

        self.assertEqual(harness.audit_consistency_target_edit.toPlainText(), "")

    def test_neighbor_preview_includes_neighbor_lines_and_speakers(self) -> None:
        harness = _Harness()
        harness._speaker_map["勇者"] = "Hero"
        path = Path("Map002.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "前", "Before"),
                _segment("d2", "中", "Middle"),
                _segment("d3", "後", "After"),
            ],
        )
        harness.sessions[path].segments[0].code101["parameters"][4] = "村人"
        harness.sessions[path].segments[0].translation_speaker = "Villager"
        harness.sessions[path].segments[1].code101["parameters"][4] = "勇者"
        harness.sessions[path].segments[2].code101["parameters"][4] = "魔王"

        preview = harness._build_consistency_neighbor_preview_text(
            {
                "path": str(path),
                "uid": "d2",
                "entry": "Block 2",
            }
        )

        self.assertIn("Prev", preview)
        self.assertIn("Current", preview)
        self.assertIn("Next", preview)
        self.assertIn("Speaker (JA): 勇者", preview)
        self.assertIn("Speaker (EN-US): Hero", preview)
        self.assertIn("Text (JA): 前", preview)
        self.assertIn("Text (EN-US): After", preview)

    def test_entry_display_label_uses_file_stem_and_block_number(self) -> None:
        harness = _Harness()

        label = harness._consistency_entry_display_label(
            "folder/Map003.json",
            "Block 12",
            "Hello there",
        )

        self.assertTrue(label.startswith("Map003:12"))
        self.assertTrue(label.endswith("| Hello there"))
        self.assertIn(" | ", label)

    def test_entry_display_label_keeps_long_file_stem(self) -> None:
        harness = _Harness()

        label = harness._consistency_entry_display_label(
            "folder/ThisIsAnAbsurdlyLongFilenameForMap003.json",
            "Block 9",
            "Line",
        )

        self.assertIn("ThisIsAnAbsurdlyLongFilenameForMap003:9 |", label)
        self.assertNotIn("..", label.split(":")[0])


if __name__ == "__main__":
    unittest.main()
