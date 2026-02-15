from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import (
    CommandBundle,
    CommandToken,
    DialogueSegment,
    FileSession,
)
from dialogue_visual_editor.helpers.mixins.persistence_export_mixin import (
    PersistenceExportMixin,
)


class _BoolControl:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _SpinControl:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _Harness(PersistenceExportMixin):
    def __init__(self) -> None:
        self.auto_split_check = _BoolControl(False)
        self.max_lines_spin = _SpinControl(4)
        self.problem_missing_translation_check = _BoolControl(False)

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [
                item if isinstance(item, str) else ("" if item is None else str(item))
                for item in value
            ] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]


def _dialogue_segment(uid: str, text: str) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[text],
        original_lines=[text],
        source_lines=[text],
        code401_template={"code": 401, "indent": 0, "parameters": [""]},
    )


class PersistenceExportMixinTests(unittest.TestCase):
    def test_set_json_value_by_path(self) -> None:
        harness = _Harness()
        payload = {"a": {"b": ["x", "y"]}}
        changed = harness._set_json_value_by_path(payload, ("a", "b", 1), "z")
        unchanged = harness._set_json_value_by_path(payload, ("a", "c"), "z")
        self.assertTrue(changed)
        self.assertFalse(unchanged)
        self.assertEqual(payload["a"]["b"][1], "z")

    def test_apply_session_to_json_updates_map_display_name(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:map_display_name", "Village")
        setattr(segment, "map_display_name_path", ("displayName",))
        segment.segment_kind = "map_display_name"
        session = FileSession(
            path=Path("Map001.json"),
            data={"displayName": "Old"},
            bundles=[],
            segments=[segment],
        )

        harness._apply_session_to_json(session)
        self.assertEqual(session.data["displayName"], "Village")

    def test_apply_session_to_json_updates_name_index_combined_fields(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Items.json:I:1", "Potion")
        segment.lines = ["Potion", "", "Heals HP"]
        segment.original_lines = list(segment.lines)
        setattr(segment, "name_index_combined_fields", ("name", "description"))
        session = FileSession(
            path=Path("Items.json"),
            data=[{"id": 1, "name": "Old", "description": "Old desc"}],
            bundles=[],
            segments=[segment],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_uid_prefix", "I")

        harness._apply_session_to_json(session)
        row = session.data[0]
        self.assertEqual(row["name"], "Potion")
        self.assertEqual(row["description"], "Heals HP")

    def test_apply_session_to_json_rebuilds_command_list(self) -> None:
        harness = _Harness()
        commands_ref: list[Any] = []
        segment = _dialogue_segment("Map001.json:L0:0", "Line 1")
        segment.lines = ["Line 1", "Line 2"]
        segment.original_lines = list(segment.lines)
        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[
                CommandToken(kind="dialogue", segment=segment),
                CommandToken(kind="raw", raw_entry={"code": 0, "indent": 0, "parameters": []}),
            ],
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={"list": commands_ref},
            bundles=[bundle],
            segments=[segment],
        )

        harness._apply_session_to_json(session)
        rebuilt_codes = [entry.get("code") for entry in session.data["list"]]
        self.assertEqual(rebuilt_codes, [101, 401, 401, 0])
        self.assertEqual(session.data["list"][1]["parameters"][0], "Line 1")
        self.assertEqual(session.data["list"][2]["parameters"][0], "Line 2")

    def test_export_translated_data_inserts_translation_only_followups(self) -> None:
        harness = _Harness()
        commands_ref: list[Any] = []
        source = _dialogue_segment("src", "JP line")
        source.translation_lines = ["TL main"]
        source.original_translation_lines = [""]
        followup = _dialogue_segment("followup", "")
        followup.translation_only = True
        followup.translation_lines = ["TL extra"]
        followup.original_translation_lines = [""]

        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[CommandToken(kind="dialogue", segment=source)],
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={"list": commands_ref},
            bundles=[bundle],
            segments=[source, followup],
        )

        exported = harness._export_translated_data_for_session(session)
        rebuilt = exported["list"]
        self.assertEqual([entry["code"] for entry in rebuilt], [101, 401, 101, 401])
        self.assertEqual(rebuilt[1]["parameters"][0], "TL main")
        self.assertEqual(rebuilt[3]["parameters"][0], "TL extra")

    def test_missing_translation_problem_detects_empty_translation(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", "JP line")
        segment.translation_lines = [""]
        self.assertTrue(
            harness._segment_has_missing_translation_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_missing_translation_problem_ignores_filled_translation(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", "JP line")
        segment.translation_lines = ["EN line"]
        self.assertFalse(
            harness._segment_has_missing_translation_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_missing_translation_problem_ignores_source_without_visible_text(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", r"\!")
        segment.translation_lines = [""]
        self.assertFalse(
            harness._segment_has_missing_translation_problem(
                segment,
                translator_mode=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
