from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.audit.audit_sanitize_apply_mixin import (
    AuditSanitizeApplyMixin,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


class _StatusBarStub:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _RulesListStub:
    def __init__(self, item: Any = None) -> None:
        self._item = item

    def currentItem(self) -> Any:
        return self._item


class _Harness(AuditSanitizeApplyMixin):
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.file_paths: list[Path] = []
        self.current_path: Path | None = None
        self.selected_segment_uid = ""
        self.audit_sanitize_rules_list: _RulesListStub | None = None
        self.scope = "original"
        self.ignored_entries: set[tuple[str, str, str]] = set()
        self.status_bar = _StatusBarStub()
        self.refresh_dirty_calls = 0
        self.render_calls = 0
        self.translator_panel_refresh_calls = 0
        self.invalidate_cache_calls = 0
        self.sanitize_panel_refresh_calls = 0
        self.control_panel_refresh_calls = 0
        self.collision_panel_refresh_calls = 0
        self.name_panel_refresh_calls = 0
        self.normalize_for_segment_raises = False

    def statusBar(self) -> _StatusBarStub:
        return self.status_bar

    def _is_audit_sanitize_entry_ignored(self, rule_id: str, path_raw: str, uid: str) -> bool:
        return (rule_id, path_raw, uid) in self.ignored_entries

    def _audit_sanitize_scope(self) -> str:
        return self.scope

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    def _normalize_audit_translation_lines_for_segment(
        self,
        _segment: DialogueSegment,
        lines: list[str],
    ) -> list[str]:
        if self.normalize_for_segment_raises:
            raise RuntimeError("normalize failed")
        return list(lines)

    def _refresh_dirty_state(self, _session: FileSession) -> None:
        self.refresh_dirty_calls += 1

    def _render_session(self, _session: FileSession, *, focus_uid: str, preserve_scroll: bool) -> None:
        self.render_calls += 1
        self.selected_segment_uid = focus_uid
        self._last_render_preserve_scroll = preserve_scroll

    def _refresh_translator_detail_panel(self) -> None:
        self.translator_panel_refresh_calls += 1

    def _invalidate_audit_caches(self) -> None:
        self.invalidate_cache_calls += 1

    def _refresh_audit_sanitize_panel(self) -> None:
        self.sanitize_panel_refresh_calls += 1

    def _refresh_audit_control_mismatch_panel(self) -> None:
        self.control_panel_refresh_calls += 1

    def _refresh_audit_translation_collision_panel(self) -> None:
        self.collision_panel_refresh_calls += 1

    def _refresh_audit_name_consistency_panel(self) -> None:
        self.name_panel_refresh_calls += 1

    @staticmethod
    def _audit_sanitize_rule_payload(item: Any) -> dict[str, str] | None:
        return item if isinstance(item, dict) else None


def _segment(
    uid: str,
    *,
    source: str = "",
    translation: str = "",
) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[source],
        original_lines=[source],
        source_lines=[source],
        translation_lines=[translation],
        original_translation_lines=[translation],
    )


class AuditSanitizeApplyMixinTests(unittest.TestCase):
    def test_apply_rules_to_lines_counts_replacements(self) -> None:
        harness = _Harness()
        lines, replacements = harness._apply_sanitize_rules_to_lines(
            ["「A」", "「B」"],
            [
                {"find_text": "「", "replace_text": '"'},
                {"find_text": "」", "replace_text": '"'},
            ],
        )
        self.assertEqual(lines, ['"A"', '"B"'])
        self.assertEqual(replacements, 4)

    def test_apply_rules_to_lines_skips_empty_find_text(self) -> None:
        harness = _Harness()
        lines, replacements = harness._apply_sanitize_rules_to_lines(
            ["abc"],
            [{"find_text": "", "replace_text": "x"}],
        )
        self.assertEqual(lines, ["abc"])
        self.assertEqual(replacements, 0)

    def test_apply_single_entry_handles_missing_session_segment_and_ignored(self) -> None:
        harness = _Harness()
        rule = {"rule_id": "r", "find_text": "a", "replace_text": "b"}

        harness._apply_audit_sanitize_rule_to_entry(rule, "Map001.json", "uid-1")
        self.assertIn("Entry not loaded", harness.status_bar.messages[-1])

        path = Path("Map001.json")
        harness.sessions[path] = FileSession(path=path, data={}, bundles=[], segments=[])
        harness._apply_audit_sanitize_rule_to_entry(rule, "Map001.json", "uid-1")
        self.assertEqual(harness.status_bar.messages[-1], "Entry no longer exists.")

        segment = _segment("uid-1", source="aaa")
        harness.sessions[path].segments = [segment]
        harness.ignored_entries.add(("r", str(path), "uid-1"))
        harness._apply_audit_sanitize_rule_to_entry(rule, "Map001.json", "uid-1")
        self.assertEqual(harness.status_bar.messages[-1], "Entry is ignored for this rule.")

    def test_apply_single_entry_updates_original_and_translation(self) -> None:
        harness = _Harness()
        harness.scope = "both"
        path = Path("Map001.json")
        segment = _segment("uid-1", source="aa", translation="aa")
        session = FileSession(path=path, data={}, bundles=[], segments=[segment])
        harness.sessions[path] = session
        harness.current_path = path
        rule = {"rule_id": "r", "find_text": "a", "replace_text": "b"}

        harness._apply_audit_sanitize_rule_to_entry(rule, str(path), "uid-1")

        self.assertEqual(segment.lines, ["bb"])
        self.assertEqual(segment.source_lines, ["bb"])
        self.assertEqual(segment.translation_lines, ["bb"])
        self.assertEqual(harness.refresh_dirty_calls, 1)
        self.assertEqual(harness.render_calls, 1)
        self.assertEqual(harness.invalidate_cache_calls, 1)
        self.assertIn("Applied sanitize rule to entry", harness.status_bar.messages[-1])

    def test_apply_single_entry_translation_uses_fallback_when_normalizer_raises(self) -> None:
        harness = _Harness()
        harness.scope = "translation"
        harness.normalize_for_segment_raises = True
        path = Path("Map001.json")
        segment = _segment("uid-1", translation="aa")
        harness.sessions[path] = FileSession(path=path, data={}, bundles=[], segments=[segment])
        harness.current_path = None
        rule = {"rule_id": "r", "find_text": "a", "replace_text": "b"}

        harness._apply_audit_sanitize_rule_to_entry(rule, str(path), "uid-1")

        self.assertEqual(segment.translation_lines, ["bb"])
        self.assertEqual(harness.translator_panel_refresh_calls, 1)

    def test_apply_single_entry_translation_without_segment_normalizer(self) -> None:
        harness = _Harness()
        harness.scope = "translation"
        path = Path("Map001.json")
        segment = _segment("uid-1", translation="aa")
        harness.sessions[path] = FileSession(path=path, data={}, bundles=[], segments=[segment])
        harness.current_path = None
        harness._normalize_audit_translation_lines_for_segment = None
        rule = {"rule_id": "r", "find_text": "a", "replace_text": "b"}

        harness._apply_audit_sanitize_rule_to_entry(rule, str(path), "uid-1")

        self.assertEqual(segment.translation_lines, ["bb"])
        self.assertEqual(harness.translator_panel_refresh_calls, 1)

    def test_apply_single_entry_reports_no_replacements(self) -> None:
        harness = _Harness()
        harness.scope = "original"
        path = Path("Map001.json")
        segment = _segment("uid-1", source="xyz")
        harness.sessions[path] = FileSession(path=path, data={}, bundles=[], segments=[segment])
        rule = {"rule_id": "r", "find_text": "a", "replace_text": "b"}

        harness._apply_audit_sanitize_rule_to_entry(rule, str(path), "uid-1")

        self.assertEqual(
            harness.status_bar.messages[-1],
            "No replacements applied for selected entry.",
        )

    def test_apply_rules_bulk_handles_empty_rules_and_no_sessions(self) -> None:
        harness = _Harness()
        harness._apply_audit_sanitize_rules([])
        self.assertEqual(harness.status_bar.messages[-1], "No sanitize rules selected.")

        harness._apply_audit_sanitize_rules([{"rule_id": "r", "find_text": "a", "replace_text": "b"}])
        self.assertEqual(harness.status_bar.messages[-1], "No data loaded.")

    def test_apply_rules_bulk_updates_segments_and_reports_counts(self) -> None:
        harness = _Harness()
        harness.scope = "both"
        path = Path("Map001.json")
        segment = _segment("uid-1", source="aa", translation="aa")
        session = FileSession(path=path, data={}, bundles=[], segments=[segment])
        harness.sessions[path] = session
        harness.file_paths = [path]
        harness.current_path = path
        harness.selected_segment_uid = "uid-1"

        harness._apply_audit_sanitize_rules(
            [{"rule_id": "r", "find_text": "a", "replace_text": "b"}]
        )

        self.assertEqual(segment.lines, ["bb"])
        self.assertEqual(segment.translation_lines, ["bb"])
        self.assertEqual(harness.render_calls, 1)
        self.assertIn("Applied sanitize rules", harness.status_bar.messages[-1])

    def test_apply_rules_bulk_no_changes_refreshes_panels(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        missing_path = Path("Missing.json")
        segment = _segment("uid-1", source="aa", translation="aa")
        harness.sessions[path] = FileSession(path=path, data={}, bundles=[], segments=[segment])
        harness.file_paths = [missing_path, path]
        harness.ignored_entries.add(("r", str(path), "uid-1"))

        harness._apply_audit_sanitize_rules(
            [{"rule_id": "r", "find_text": "a", "replace_text": "b"}]
        )

        self.assertEqual(harness.status_bar.messages[-1], "No replacements applied.")
        self.assertEqual(harness.sanitize_panel_refresh_calls, 1)
        self.assertEqual(harness.control_panel_refresh_calls, 1)
        self.assertEqual(harness.collision_panel_refresh_calls, 1)
        self.assertEqual(harness.name_panel_refresh_calls, 1)
        self.assertEqual(harness.invalidate_cache_calls, 0)

    def test_apply_rules_bulk_translation_normalizer_raises_then_refreshes_translator_panel(self) -> None:
        harness = _Harness()
        harness.scope = "translation"
        harness.normalize_for_segment_raises = True
        path = Path("Map001.json")
        segment = _segment("uid-1", source="x", translation="aa")
        harness.sessions[path] = FileSession(path=path, data={}, bundles=[], segments=[segment])
        harness.file_paths = [path]
        harness.current_path = Path("Other.json")

        harness._apply_audit_sanitize_rules(
            [{"rule_id": "r", "find_text": "a", "replace_text": "b"}]
        )

        self.assertEqual(segment.translation_lines, ["bb"])
        self.assertEqual(harness.translator_panel_refresh_calls, 1)
        self.assertEqual(harness.invalidate_cache_calls, 1)

    def test_apply_rules_bulk_without_segment_normalizer_uses_global_normalize(self) -> None:
        harness = _Harness()
        harness.scope = "translation"
        path = Path("Map001.json")
        segment = _segment("uid-1", source="x", translation="aa")
        harness.sessions[path] = FileSession(path=path, data={}, bundles=[], segments=[segment])
        harness.file_paths = [path]
        harness.current_path = None
        harness._normalize_audit_translation_lines_for_segment = None

        harness._apply_audit_sanitize_rules(
            [{"rule_id": "r", "find_text": "a", "replace_text": "b"}]
        )

        self.assertEqual(segment.translation_lines, ["bb"])
        self.assertEqual(harness.translator_panel_refresh_calls, 1)

    def test_apply_selected_rule_requires_selection(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_rules_list = _RulesListStub(item=None)
        harness._apply_selected_audit_sanitize_rule()
        self.assertEqual(harness.status_bar.messages[-1], "Select a sanitize rule first.")

        harness.audit_sanitize_rules_list = _RulesListStub(
            item={"rule_id": "r", "label": "L", "find_text": "a", "replace_text": "b"}
        )
        harness._apply_selected_audit_sanitize_rule()
        self.assertEqual(harness.status_bar.messages[-1], "No data loaded.")

    def test_apply_selected_rule_no_list_is_noop(self) -> None:
        harness = _Harness()
        harness.audit_sanitize_rules_list = None
        harness._apply_selected_audit_sanitize_rule()
        self.assertEqual(harness.status_bar.messages, [])


if __name__ == "__main__":
    unittest.main()
