from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.audit.audit_name_consistency_mixin import (
    AuditNameConsistencyMixin,
)
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


class _Harness(AuditNameConsistencyMixin):
    def __init__(self) -> None:
        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}

    def _audit_path_sessions_snapshot(self) -> list[tuple[Path, FileSession]]:
        return [(path, session) for path, session in self.sessions.items()]

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

    @staticmethod
    def _is_name_index_session(session: FileSession) -> bool:
        return bool(getattr(session, "is_name_index_session", False))

    @staticmethod
    def _name_index_label(session: FileSession | None) -> str:
        if session is None:
            return "Entry"
        raw = getattr(session, "name_index_label", "")
        return raw if isinstance(raw, str) and raw.strip() else "Entry"

    @staticmethod
    def _actor_id_from_uid(_uid: str) -> None:
        return None

    @staticmethod
    def _name_index_field_from_uid(uid: str) -> str:
        suffix = uid.rsplit(":", 1)[-1] if ":" in uid else "name"
        return suffix if suffix in {"name", "description"} else "name"

    @staticmethod
    def _audit_entry_text_for_segment(
        _session: FileSession,
        _segment: DialogueSegment,
        index: int,
    ) -> str:
        return f"Block {index}"


class AuditNameConsistencyMixinTests(unittest.TestCase):
    def test_replace_name_consistency_case_insensitive(self) -> None:
        harness = _Harness()

        replaced, count = harness._replace_name_consistency_case_insensitive(
            "Use leather armor and Leather Armor now.",
            "leather armor",
            "Leather Vest",
        )

        self.assertEqual(count, 2)
        self.assertEqual(replaced, "Use Leather Vest and Leather Vest now.")

    def test_collect_groups_uses_misc_entry_translation_as_expected_tl(self) -> None:
        harness = _Harness()
        misc_path = Path("Armors.json")
        misc_session = FileSession(
            path=misc_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Armors.json:R:2:name", "レザーベスト", "Leather Vest", segment_kind="name_index"),
            ],
        )
        setattr(misc_session, "is_name_index_session", True)
        setattr(misc_session, "name_index_label", "Armor")

        map_path = Path("Map001.json")
        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Map001.json:L0:0", "レザーベストを装備した", "Equipped leather armor."),
                _segment("Map001.json:L1:0", "レザーベストは丈夫だ", "The Leather Vest is durable."),
            ],
        )
        harness.file_paths = [misc_path, map_path]
        harness.sessions[misc_path] = misc_session
        harness.sessions[map_path] = map_session

        groups = harness._collect_audit_name_consistency_groups(dialogue_only=True)

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(str(group["source_term"]), "レザーベスト")
        self.assertEqual(str(group["expected_tl"]), "Leather Vest")
        self.assertEqual(str(group["misc_uid"]), "Armors.json:R:2:name")
        self.assertEqual(int(group["checked_count"]), 2)
        self.assertEqual(int(group["entry_count"]), 1)

    def test_collect_groups_hides_entries_without_missing_hits(self) -> None:
        harness = _Harness()
        misc_path = Path("Classes.json")
        misc_session = FileSession(
            path=misc_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Classes.json:C:1:name", "剣士", "Swordsman", segment_kind="name_index"),
            ],
        )
        setattr(misc_session, "is_name_index_session", True)
        setattr(misc_session, "name_index_label", "Class")

        map_path = Path("Map002.json")
        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Map002.json:L0:0", "剣士が来た", "A Swordsman has arrived."),
                _segment("Map002.json:L1:0", "剣士は強い", "The Swordsman is strong."),
            ],
        )
        harness.file_paths = [misc_path, map_path]
        harness.sessions[misc_path] = misc_session
        harness.sessions[map_path] = map_session

        groups = harness._collect_audit_name_consistency_groups(dialogue_only=True)

        self.assertEqual(groups, [])

    def test_collect_groups_can_include_non_discrepant_terms(self) -> None:
        harness = _Harness()
        misc_path = Path("Classes.json")
        misc_session = FileSession(
            path=misc_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Classes.json:C:1:name", "剣士", "Swordsman", segment_kind="name_index"),
            ],
        )
        setattr(misc_session, "is_name_index_session", True)
        setattr(misc_session, "name_index_label", "Class")

        map_path = Path("Map002.json")
        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Map002.json:L0:0", "剣士が来た", "A Swordsman has arrived."),
                _segment("Map002.json:L1:0", "剣士は強い", "The Swordsman is strong."),
            ],
        )
        harness.file_paths = [misc_path, map_path]
        harness.sessions[misc_path] = misc_session
        harness.sessions[map_path] = map_session

        groups = harness._collect_audit_name_consistency_groups(
            dialogue_only=True,
            only_discrepancies=False,
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(str(groups[0]["source_term"]), "剣士")
        self.assertEqual(bool(groups[0]["has_discrepancy"]), False)
        self.assertEqual(int(groups[0]["entry_count"]), 0)
        self.assertEqual(int(groups[0]["checked_count"]), 2)

    def test_collect_groups_ranks_by_missing_hits(self) -> None:
        harness = _Harness()
        misc_path = Path("Items.json")
        misc_session = FileSession(
            path=misc_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Items.json:I:1:name", "ポーション", "Potion", segment_kind="name_index"),
                _segment("Items.json:I:2:name", "エーテル", "Ether", segment_kind="name_index"),
            ],
        )
        setattr(misc_session, "is_name_index_session", True)
        setattr(misc_session, "name_index_label", "Item")

        map_path = Path("Map003.json")
        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Map003.json:L0:0", "ポーションが必要だ", "Need medicine."),
                _segment("Map003.json:L1:0", "ポーションを使え", "Use medicine now."),
                _segment("Map003.json:L2:0", "エーテルが必要だ", "Need mana restore."),
            ],
        )
        harness.file_paths = [misc_path, map_path]
        harness.sessions[misc_path] = misc_session
        harness.sessions[map_path] = map_session

        groups = harness._collect_audit_name_consistency_groups(
            dialogue_only=True,
            sort_mode="hits_desc",
        )

        self.assertEqual(len(groups), 2)
        self.assertEqual(str(groups[0]["source_term"]), "ポーション")
        self.assertEqual(int(groups[0]["entry_count"]), 2)
        self.assertEqual(str(groups[1]["source_term"]), "エーテル")
        self.assertEqual(int(groups[1]["entry_count"]), 1)

    def test_collect_groups_applies_filter_text(self) -> None:
        harness = _Harness()
        misc_path = Path("Armors.json")
        misc_session = FileSession(
            path=misc_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Armors.json:R:2:name", "レザーベスト", "Leather Vest", segment_kind="name_index"),
            ],
        )
        setattr(misc_session, "is_name_index_session", True)
        setattr(misc_session, "name_index_label", "Armor")

        map_path = Path("Map004.json")
        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Map004.json:L0:0", "レザーベストを装備した", "Equipped leather armor."),
            ],
        )
        harness.file_paths = [misc_path, map_path]
        harness.sessions[misc_path] = misc_session
        harness.sessions[map_path] = map_session

        matched = harness._collect_audit_name_consistency_groups(
            dialogue_only=True,
            filter_text="leather",
        )
        filtered_out = harness._collect_audit_name_consistency_groups(
            dialogue_only=True,
            filter_text="ether",
        )

        self.assertEqual(len(matched), 1)
        self.assertEqual(filtered_out, [])

    def test_collect_groups_ignores_inferred_speaker_line_for_glossary_checks(self) -> None:
        harness = _Harness()
        misc_path = Path("Actors.json")
        misc_session = FileSession(
            path=misc_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Actors.json:A:1:name", "ユウカ", "Yuka", segment_kind="name_index"),
            ],
        )
        setattr(misc_session, "is_name_index_session", True)
        setattr(misc_session, "name_index_label", "Actor")

        map_path = Path("Map020.json")
        dialogue = _segment("Map020.json:L0:0", "ユウカ\nこんにちは", "ユウカ\nHello")
        setattr(dialogue, "consistency_inferred_speaker", True)
        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[dialogue],
        )
        harness.file_paths = [misc_path, map_path]
        harness.sessions[misc_path] = misc_session
        harness.sessions[map_path] = map_session

        groups = harness._collect_audit_name_consistency_groups(dialogue_only=True)

        self.assertEqual(groups, [])

    def test_collect_groups_uses_translation_only_followups_as_same_dialogue_block(self) -> None:
        harness = _Harness()
        misc_path = Path("Items.json")
        misc_session = FileSession(
            path=misc_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Items.json:I:1:name", "魔王", "Demon Lord", segment_kind="name_index"),
            ],
        )
        setattr(misc_session, "is_name_index_session", True)
        setattr(misc_session, "name_index_label", "Item")

        map_path = Path("Map099.json")
        map_session = FileSession(
            path=map_path,
            data=[],
            bundles=[],
            segments=[
                _segment("Map099.json:L0:0", "魔王が現れた", "Demon"),
                _segment(
                    "Map099.json:TI:1",
                    "",
                    "Lord",
                    translation_only=True,
                ),
            ],
        )
        harness.file_paths = [misc_path, map_path]
        harness.sessions[misc_path] = misc_session
        harness.sessions[map_path] = map_session

        groups = harness._collect_audit_name_consistency_groups(dialogue_only=True)

        self.assertEqual(groups, [])


if __name__ == "__main__":
    unittest.main()
