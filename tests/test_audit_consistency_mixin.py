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
    translation_only: bool = False,
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
        translation_only=translation_only,
    )


class _Harness(AuditConsistencyMixin):
    _NAME_INDEX_UID_RE = re.compile(r":[A-Za-z]:(\d+)(?::([A-Za-z0-9_]+))?$")
    _AUDIT_TAB_SANITIZE = 1
    _AUDIT_TAB_CONTROL_MISMATCH = 2
    _AUDIT_TAB_CONSISTENCY = 3
    _AUDIT_TAB_NAME_CONSISTENCY = 5
    _normalize_audit_translation_lines_for_segment = (
        AuditCoreMixin._normalize_audit_translation_lines_for_segment
    )

    def __init__(self) -> None:
        class _StatusBarStub:
            def __init__(self) -> None:
                self.messages: list[str] = []

            def showMessage(self, text: str) -> None:
                self.messages.append(str(text))

        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}
        self._speaker_map: dict[str, str] = {}
        self.audit_consistency_entries_list: Any = None
        self.audit_consistency_neighbors_check: Any = None
        self.audit_consistency_neighbors_edit: Any = None
        self.audit_consistency_groups_list: Any = None
        self.audit_consistency_target_edit: Any = None
        self._source_label = "JA"
        self._target_label = "EN-US"
        self.current_path: Path | None = None
        self.selected_segment_uid: str | None = None
        self._status_bar = _StatusBarStub()

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

    def _segment_source_lines_for_translation(self, segment: DialogueSegment) -> list[str]:
        lines = self._segment_source_lines_for_display(segment)
        if bool(getattr(segment, "consistency_inferred_speaker", False)):
            if len(lines) > 1:
                return list(lines[1:])
            return [""]
        return list(lines) if lines else [""]

    def _segment_translation_lines_for_translation(self, segment: DialogueSegment) -> list[str]:
        lines = self._normalize_translation_lines(segment.translation_lines)
        if bool(getattr(segment, "consistency_inferred_speaker", False)):
            if len(lines) > 1:
                return list(lines[1:])
            return [""]
        return list(lines) if lines else [""]

    def _compose_translation_lines_for_segment(
        self,
        segment: DialogueSegment,
        visible_lines: list[str],
    ) -> list[str]:
        normalized_visible = self._normalize_translation_lines(visible_lines)
        if not bool(getattr(segment, "consistency_inferred_speaker", False)):
            return normalized_visible
        source_lines = self._segment_source_lines_for_display(segment)
        prefix = source_lines[0] if source_lines else ""
        return [prefix] + normalized_visible

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

    def statusBar(self) -> Any:
        return self._status_bar


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

    def test_collect_groups_excludes_inferred_speaker_from_source_and_translation(self) -> None:
        harness = _Harness()
        path = Path("Map010.json")
        harness.file_paths = [path]
        first = _segment("d1", "ユウカ\nこんにちは", "Yuka\nHello", segment_kind="dialogue")
        second = _segment("d2", "タロウ\nこんにちは", "Taro\nHello", segment_kind="dialogue")
        setattr(first, "consistency_inferred_speaker", True)
        setattr(second, "consistency_inferred_speaker", True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[first, second],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(str(groups[0].get("source_text", "")), "こんにちは")
        translations = {str(entry.get("translation", "")) for entry in groups[0]["entries"]}
        self.assertEqual(translations, {"Hello"})

    def test_collect_groups_merges_split_followup_entry_under_anchor_source(self) -> None:
        harness = _Harness()
        path = Path("Map020.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("a1", "同一文", "Part 1"),
                _segment("a1f", "", "Part 2", translation_only=True),
                _segment("a2", "同一文", "Other"),
            ],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(int(groups[0]["entry_count"]), 2)
        entries = groups[0]["entries"]
        split_entry = next(entry for entry in entries if str(entry.get("uid")) == "a1")
        self.assertEqual(split_entry.get("segment_uids"), ["a1", "a1f"])

    def test_variant_count_treats_split_vs_unsplit_as_different(self) -> None:
        harness = _Harness()
        path = Path("Map021.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("a1", "同一文", "Line 1"),
                _segment("a1f", "", "Line 2", translation_only=True),
                _segment("a2", "同一文", "Line 1\nLine 2"),
            ],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(int(groups[0]["variant_count"]), 2)
        translations = {str(entry.get("translation", "")) for entry in groups[0]["entries"]}
        self.assertEqual(translations, {"Line 1\nLine 2"})

    def test_variant_count_treats_different_chunk_layouts_as_different(self) -> None:
        harness = _Harness()
        path = Path("Map022.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("a1", "同一文", "Alpha"),
                _segment("a1f", "", "Beta", translation_only=True),
                _segment("a2", "同一文", "Alpha\nBeta"),
                _segment("a2f", "", "", translation_only=True),
            ],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(int(groups[0]["variant_count"]), 2)
        translations = {str(entry.get("translation", "")) for entry in groups[0]["entries"]}
        self.assertEqual(translations, {"Alpha\nBeta"})

    def test_variant_count_treats_leading_whitespace_as_different(self) -> None:
        harness = _Harness()
        path = Path("Map023.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment(
                    "a1",
                    "同一文",
                    "\\C[14]Press the confirm button.\\C[0]",
                ),
                _segment(
                    "a2",
                    "同一文",
                    "              \\C[14]Press the confirm button.\\C[0]",
                ),
            ],
        )

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(int(groups[0]["variant_count"]), 2)

    def test_variant_color_map_treats_split_layout_as_distinct(self) -> None:
        harness = _Harness()

        unsplit_key = harness._consistency_variant_key(["Line 1\nLine 2"])
        split_key = harness._consistency_variant_key(["Line 1", "Line 2"])

        color_map = harness._consistency_variant_color_map({unsplit_key, split_key})

        self.assertEqual(len(color_map), 2)
        self.assertIn(unsplit_key, color_map)
        self.assertIn(split_key, color_map)
        self.assertNotEqual(color_map[unsplit_key].name(), color_map[split_key].name())

    def test_target_overflow_metrics_counts_inferred_speaker_storage_budget(self) -> None:
        harness = _Harness()

        class _Spin:
            def __init__(self, value: int) -> None:
                self._value = value

            def value(self) -> int:
                return self._value

        setattr(harness, "thin_width_spin", _Spin(99))
        setattr(harness, "wide_width_spin", _Spin(99))
        setattr(harness, "max_lines_spin", _Spin(4))

        inferred = _segment("d1", "ユウカ\nこんにちは", "Yuka\nHi")
        setattr(inferred, "consistency_inferred_speaker", True)
        normal = _segment("d2", "こんにちは", "Hi")
        target_lines = ["L1", "L2", "L3", "L4"]

        inferred_metrics = harness._consistency_target_overflow_metrics_for_segment(
            inferred,
            target_lines,
        )
        normal_metrics = harness._consistency_target_overflow_metrics_for_segment(
            normal,
            target_lines,
        )

        self.assertFalse(bool(normal_metrics["has_row_over"]))
        self.assertTrue(bool(inferred_metrics["has_row_over"]))
        self.assertEqual(int(inferred_metrics["overflow_start_visible"]), 3)

    def test_target_display_text_for_chunks_adds_divider_padding(self) -> None:
        harness = _Harness()

        rendered = harness._consistency_target_display_text_for_chunks(
            ["Line A", "Line B"]
        )

        self.assertEqual(
            rendered,
            "Line A\n\n\n\n\nLine B",
        )

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

    def test_apply_group_preserves_inferred_speaker_storage_line(self) -> None:
        harness = _Harness()
        path = Path("Map011.json")
        segment = _segment("d1", "ユウカ\nこんにちは", "Yuka\nHi", segment_kind="dialogue")
        setattr(segment, "consistency_inferred_speaker", True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[segment],
        )
        harness.current_path = None
        harness.selected_segment_uid = ""

        class _StatusBar:
            def __init__(self) -> None:
                self.messages: list[str] = []

            def showMessage(self, message: str) -> None:
                self.messages.append(message)

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, item: _FakeItem) -> None:
                self._item = item

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        payload = {
            "source_text": "こんにちは",
            "entries": [
                {"path": str(path), "uid": "d1", "entry": "Block 1", "translation": "Hi"},
            ],
        }
        harness.audit_consistency_groups_list = _FakeGroups(_FakeItem(payload))
        harness.audit_consistency_target_edit = _FakeTargetEdit("Hello")
        harness.audit_consistency_entries_list = None
        status_bar = _StatusBar()
        harness.statusBar = lambda: status_bar  # type: ignore[method-assign]
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = lambda preferred_source=None, preferred_row=None: None  # type: ignore[method-assign]
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._render_session = lambda _session, **_kwargs: None  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(segment.translation_lines, ["ユウカ", "Hello"])

    def test_apply_group_uses_selected_entry_pattern_across_chain(self) -> None:
        harness = _Harness()
        path = Path("Map031.json")
        harness.file_paths = [path]
        anchor_a = _segment("a1", "同一文", "x1\nx2")
        followup_a = _segment("a1f", "", "x3", translation_only=True)
        anchor_b = _segment("a2", "同一文", "y1")
        followup_b = _segment("a2f", "", "y2\ny3", translation_only=True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[anchor_a, followup_a, anchor_b, followup_b],
        )
        harness.current_path = None
        harness.selected_segment_uid = ""

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeEntries:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )
        self.assertEqual(len(groups), 1)
        entries = groups[0]["entries"]
        selected_entry = next(
            entry for entry in entries if str(entry.get("uid", "")) == "a1"
        )

        harness.audit_consistency_groups_list = _FakeGroups(groups[0])
        harness.audit_consistency_entries_list = _FakeEntries(selected_entry)
        harness.audit_consistency_target_edit = _FakeTargetEdit("N1\nN2\nN3")
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: None
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._render_session = lambda _session, **_kwargs: None  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(anchor_a.translation_lines, ["N1", "N2"])
        self.assertEqual(followup_a.translation_lines, ["N3"])
        self.assertEqual(anchor_b.translation_lines, ["N1", "N2"])
        self.assertEqual(followup_b.translation_lines, ["N3"])

    def test_apply_group_parses_divider_text_into_split_chunks(self) -> None:
        harness = _Harness()
        path = Path("Map031b.json")
        harness.file_paths = [path]
        anchor_a = _segment("a1", "同一文", "x1\nx2")
        followup_a = _segment("a1f", "", "x3", translation_only=True)
        anchor_b = _segment("a2", "同一文", "y1")
        followup_b = _segment("a2f", "", "y2", translation_only=True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[anchor_a, followup_a, anchor_b, followup_b],
        )
        harness.current_path = None
        harness.selected_segment_uid = ""

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeEntries:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )
        self.assertEqual(len(groups), 1)
        selected_entry = groups[0]["entries"][0]

        harness.audit_consistency_groups_list = _FakeGroups(groups[0])
        harness.audit_consistency_entries_list = _FakeEntries(selected_entry)
        harness.audit_consistency_target_edit = _FakeTargetEdit(
            "N1\nN2\n\n\n\nN3"
        )
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: None
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._render_session = lambda _session, **_kwargs: None  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(anchor_a.translation_lines, ["N1", "N2"])
        self.assertEqual(followup_a.translation_lines, ["N3"])
        self.assertEqual(anchor_b.translation_lines, ["N1", "N2"])
        self.assertEqual(followup_b.translation_lines, ["N3"])

    def test_apply_group_parses_single_blank_separator_after_line_limit(self) -> None:
        harness = _Harness()
        path = Path("Map031d.json")
        harness.file_paths = [path]
        anchor_a = _segment("a1", "同一文", "x1\nx2\nx3\nx4")
        followup_a = _segment("a1f", "", "x5", translation_only=True)
        anchor_b = _segment("a2", "同一文", "y1")
        followup_b = _segment("a2f", "", "y2", translation_only=True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[anchor_a, followup_a, anchor_b, followup_b],
        )
        harness.current_path = None
        harness.selected_segment_uid = ""

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeEntries:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )
        self.assertEqual(len(groups), 1)
        selected_entry = groups[0]["entries"][0]

        harness.audit_consistency_groups_list = _FakeGroups(groups[0])
        harness.audit_consistency_entries_list = _FakeEntries(selected_entry)
        harness.audit_consistency_target_edit = _FakeTargetEdit(
            "N1\nN2\nN3\nN4\n\nN5"
        )
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: None
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._render_session = lambda _session, **_kwargs: None  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(anchor_a.translation_lines, ["N1", "N2", "N3", "N4"])
        self.assertEqual(followup_a.translation_lines, ["N5"])
        self.assertEqual(anchor_b.translation_lines, ["N1", "N2", "N3", "N4"])
        self.assertEqual(followup_b.translation_lines, ["N5"])

    def test_apply_group_parses_legacy_block_divider_text_into_split_chunks(self) -> None:
        harness = _Harness()
        path = Path("Map031c.json")
        harness.file_paths = [path]
        anchor_a = _segment("a1", "同一文", "x1\nx2")
        followup_a = _segment("a1f", "", "x3", translation_only=True)
        anchor_b = _segment("a2", "同一文", "y1")
        followup_b = _segment("a2f", "", "y2", translation_only=True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[anchor_a, followup_a, anchor_b, followup_b],
        )
        harness.current_path = None
        harness.selected_segment_uid = ""

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeEntries:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )
        self.assertEqual(len(groups), 1)
        selected_entry = groups[0]["entries"][0]

        harness.audit_consistency_groups_list = _FakeGroups(groups[0])
        harness.audit_consistency_entries_list = _FakeEntries(selected_entry)
        harness.audit_consistency_target_edit = _FakeTargetEdit(
            "N1\nN2\n\n----- Block 2 -----\n\nN3"
        )
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: None
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._render_session = lambda _session, **_kwargs: None  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(anchor_a.translation_lines, ["N1", "N2"])
        self.assertEqual(followup_a.translation_lines, ["N3"])
        self.assertEqual(anchor_b.translation_lines, ["N1", "N2"])
        self.assertEqual(followup_b.translation_lines, ["N3"])

    def test_apply_group_preserves_inferred_speaker_storage_with_chain(self) -> None:
        harness = _Harness()
        path = Path("Map032.json")
        anchor = _segment("d1", "ユウカ\nこんにちは", "Yuka\nHi", segment_kind="dialogue")
        setattr(anchor, "consistency_inferred_speaker", True)
        followup = _segment("d1f", "", "Next", translation_only=True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[anchor, followup],
        )
        harness.current_path = None
        harness.selected_segment_uid = ""

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeEntries:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        entry_payload = {
            "path": str(path),
            "uid": "d1",
            "entry": "Block 1",
            "translation": "Hi\nNext",
            "segment_uids": ["d1", "d1f"],
            "translation_chunks": ["Hi", "Next"],
            "chunk_line_counts": [1, 1],
        }
        group_payload = {
            "source_text": "こんにちは",
            "entries": [entry_payload],
        }

        harness.audit_consistency_groups_list = _FakeGroups(group_payload)
        harness.audit_consistency_entries_list = _FakeEntries(entry_payload)
        harness.audit_consistency_target_edit = _FakeTargetEdit("Hello\nWorld")
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: None
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._render_session = lambda _session, **_kwargs: None  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(anchor.translation_lines, ["ユウカ", "Hello"])
        self.assertEqual(followup.translation_lines, ["World"])

    def test_apply_group_selected_unsplit_collapses_split_followups(self) -> None:
        harness = _Harness()
        path = Path("Map033.json")
        harness.file_paths = [path]
        selected_anchor = _segment("s1", "同一文", "A1\nA2\nA3\nA4")
        split_anchor = _segment("t1", "同一文", "B1\nB2\nB3")
        split_followup = _segment("t1f", "", "B4\nB5", translation_only=True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[selected_anchor, split_anchor, split_followup],
        )
        harness.current_path = None
        harness.selected_segment_uid = ""

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeEntries:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )
        self.assertEqual(len(groups), 1)
        entries = groups[0]["entries"]
        selected_entry = next(
            entry for entry in entries if str(entry.get("uid", "")) == "s1"
        )

        harness.audit_consistency_groups_list = _FakeGroups(groups[0])
        harness.audit_consistency_entries_list = _FakeEntries(selected_entry)
        harness.audit_consistency_target_edit = _FakeTargetEdit("N1\nN2\nN3\nN4")
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: None
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._render_session = lambda _session, **_kwargs: None  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(selected_anchor.translation_lines, ["N1", "N2", "N3", "N4"])
        self.assertEqual(split_anchor.translation_lines, ["N1", "N2", "N3", "N4"])
        remaining_uids = [segment.uid for segment in harness.sessions[path].segments]
        self.assertNotIn("t1f", remaining_uids)

    def test_apply_group_structure_change_on_current_file_uses_structural_refresh(self) -> None:
        harness = _Harness()
        path = Path("Map034.json")
        harness.file_paths = [path]
        selected_anchor = _segment("s1", "同一文", "A1\nA2\nA3\nA4")
        split_anchor = _segment("t1", "同一文", "B1\nB2\nB3")
        split_followup = _segment("t1f", "", "B4\nB5", translation_only=True)
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[selected_anchor, split_anchor, split_followup],
        )
        harness.current_path = path
        harness.selected_segment_uid = "t1"

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeGroups:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _index: int) -> _FakeItem:
                return self._item

        class _FakeEntries:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

        class _FakeTargetEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        groups = harness._collect_audit_consistency_groups(
            only_inconsistent=False,
            dialogue_only=True,
            sort_mode="source_order",
        )
        self.assertEqual(len(groups), 1)
        entries = groups[0]["entries"]
        selected_entry = next(
            entry for entry in entries if str(entry.get("uid", "")) == "s1"
        )

        harness.audit_consistency_groups_list = _FakeGroups(groups[0])
        harness.audit_consistency_entries_list = _FakeEntries(selected_entry)
        harness.audit_consistency_target_edit = _FakeTargetEdit("N1\nN2\nN3\nN4")
        harness._refresh_dirty_state = lambda _session: None  # type: ignore[method-assign]
        harness._invalidate_audit_caches = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_sanitize_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_control_mismatch_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_name_consistency_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_translator_detail_panel = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: None
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]

        calls = {"structure_refresh": 0, "rerender": 0, "render": 0}
        harness._refresh_after_structure_change_without_full_rerender = (  # type: ignore[method-assign]
            lambda _session, focus_uid=None, preserve_scroll=True: calls.__setitem__(
                "structure_refresh",
                calls["structure_refresh"] + 1,
            ) or True
        )
        harness._rerender_blocks_near_viewport = (  # type: ignore[method-assign]
            lambda overscan_px=240: calls.__setitem__("rerender", calls["rerender"] + 1)
        )
        harness._render_session = lambda _session, **_kwargs: calls.__setitem__(  # type: ignore[method-assign]
            "render",
            calls["render"] + 1,
        )

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(calls["structure_refresh"], 1)
        self.assertEqual(calls["rerender"], 0)
        self.assertEqual(calls["render"], 0)

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

    def test_apply_target_avoids_unrelated_panel_refresh_and_full_render(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        session = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[_segment("Map001:0", "Hello", "Old TL")],
        )
        harness.file_paths = [path]
        harness.sessions[path] = session
        harness.current_path = path

        class _FakeItem:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def data(self, _role: object) -> object:
                return self._payload

        class _FakeList:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._item = _FakeItem(payload)

            def currentItem(self) -> _FakeItem:
                return self._item

            def currentRow(self) -> int:
                return 0

            def count(self) -> int:
                return 1

            def item(self, _row: int) -> _FakeItem:
                return self._item

        class _FakeTextEdit:
            def __init__(self, value: str) -> None:
                self._value = value

            def toPlainText(self) -> str:
                return self._value

            def setPlainText(self, value: str) -> None:
                self._value = value

        harness.audit_consistency_groups_list = _FakeList(
            {
                "source_text": "Hello",
                "entries": [{"path": str(path), "uid": "Map001:0"}],
            }
        )
        harness.audit_consistency_target_edit = _FakeTextEdit("New TL")

        calls: dict[str, int] = {
            "dirty": 0,
            "invalidate": 0,
            "sanitize": 0,
            "control": 0,
            "name": 0,
            "render": 0,
            "rerender": 0,
            "detail": 0,
            "consistency": 0,
        }

        harness._refresh_dirty_state = lambda _session: calls.__setitem__(  # type: ignore[method-assign]
            "dirty", calls["dirty"] + 1
        )
        harness._invalidate_audit_caches = lambda: calls.__setitem__(  # type: ignore[method-assign]
            "invalidate", calls["invalidate"] + 1
        )
        harness._refresh_audit_sanitize_panel = lambda: calls.__setitem__(  # type: ignore[method-assign]
            "sanitize", calls["sanitize"] + 1
        )
        harness._refresh_audit_control_mismatch_panel = lambda: calls.__setitem__(  # type: ignore[method-assign]
            "control", calls["control"] + 1
        )
        harness._refresh_audit_name_consistency_panel = lambda: calls.__setitem__(  # type: ignore[method-assign]
            "name", calls["name"] + 1
        )
        harness._render_session = lambda *_args, **_kwargs: calls.__setitem__(  # type: ignore[method-assign]
            "render", calls["render"] + 1
        )
        harness._rerender_blocks_near_viewport = (  # type: ignore[method-assign]
            lambda overscan_px=800: calls.__setitem__("rerender", calls["rerender"] + 1)
        )
        harness._refresh_translator_detail_panel = lambda: calls.__setitem__(  # type: ignore[method-assign]
            "detail", calls["detail"] + 1
        )
        harness._focus_audit_consistency_groups_list = lambda: None  # type: ignore[method-assign]
        harness._refresh_audit_consistency_panel = (  # type: ignore[method-assign]
            lambda preferred_source=None, preferred_row=None: calls.__setitem__(
                "consistency", calls["consistency"] + 1
            )
        )
        harness._current_audit_tab_index = lambda: harness._AUDIT_TAB_CONSISTENCY  # type: ignore[method-assign]

        harness._apply_audit_consistency_target_to_group(advance_to_next=False)

        self.assertEqual(session.segments[0].translation_lines, ["New TL"])
        self.assertEqual(calls["dirty"], 1)
        self.assertEqual(calls["invalidate"], 1)
        self.assertEqual(calls["sanitize"], 0)
        self.assertEqual(calls["control"], 0)
        self.assertEqual(calls["name"], 0)
        self.assertEqual(calls["render"], 0)
        self.assertEqual(calls["rerender"], 1)
        self.assertEqual(calls["detail"], 1)
        self.assertEqual(calls["consistency"], 1)


if __name__ == "__main__":
    unittest.main()
