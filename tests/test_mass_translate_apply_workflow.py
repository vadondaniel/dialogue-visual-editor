from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import DialogueSegment
from dialogue_visual_editor.helpers.ui.mass_translate_dialog import MassTranslateDialog


class _ApplyWorkflowEditorMeta:
    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value]
        if isinstance(value, str):
            return value.split("\n")
        return []

    @staticmethod
    def _segment_source_lines_for_display(segment: DialogueSegment) -> list[str]:
        if segment.source_lines:
            return list(segment.source_lines)
        return list(segment.lines)

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()


class _ApplyWorkflowHarness:
    _default_prompt_template = classmethod(MassTranslateDialog._default_prompt_template.__func__)
    _normalize_prompt_language_code = staticmethod(
        MassTranslateDialog._normalize_prompt_language_code
    )
    _language_field_prefix = staticmethod(MassTranslateDialog._language_field_prefix)
    _target_translation_field_name = MassTranslateDialog._target_translation_field_name
    _translation_prompt_metadata = MassTranslateDialog._translation_prompt_metadata
    _extract_dialogue_translation_lines = MassTranslateDialog._extract_dialogue_translation_lines
    _segment_source_lines_for_mass_translate = (
        MassTranslateDialog._segment_source_lines_for_mass_translate
    )
    _preview_text_for_lines = staticmethod(MassTranslateDialog._preview_text_for_lines)
    _counter_summary_text = staticmethod(MassTranslateDialog._counter_summary_text)
    _control_tokens = staticmethod(MassTranslateDialog._control_tokens)
    _warning_level_mode = MassTranslateDialog._warning_level_mode
    _line_warning_should_flag = MassTranslateDialog._line_warning_should_flag
    _control_warning_enabled = MassTranslateDialog._control_warning_enabled
    _entry_primary_target_for_id = MassTranslateDialog._entry_primary_target_for_id
    _expected_source_line_count = MassTranslateDialog._expected_source_line_count
    _collect_apply_warning_issues = MassTranslateDialog._collect_apply_warning_issues
    _set_scope_value = MassTranslateDialog._set_scope_value
    _scope_has_pending_entries_for_value = (
        MassTranslateDialog._scope_has_pending_entries_for_value
    )
    _next_incomplete_scope_value = MassTranslateDialog._next_incomplete_scope_value
    _next_chunk_index_after_apply = staticmethod(
        MassTranslateDialog._next_chunk_index_after_apply
    )

    def __init__(self, editor: Any) -> None:
        self.editor = editor
        self.dialogue_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.misc_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.speaker_segment_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.warning_level_combo = _ComboStub("all_line_and_control_mismatches")
        self.scope_combo = _ScopeComboStub(
            [
                ("All Files", "all"),
                ("Map001.json", "file:Map001.json"),
            ],
            current_index=1,
        )
        self._scope_counts: dict[str, tuple[int, int]] = {
            "all": (0, 1),
            "file:Map001.json": (0, 1),
        }

    def _scope_completion_counts(self, scope_value: str) -> tuple[int, int]:
        return self._scope_counts.get(scope_value, (0, 0))


class _ComboStub:
    def __init__(self, value: str) -> None:
        self._value = value

    def currentData(self) -> str:
        return self._value


class _ScopeComboStub:
    def __init__(
        self,
        items: list[tuple[str, str]],
        current_index: int = 0,
    ) -> None:
        self._items = list(items)
        self._current_index = max(0, min(current_index, len(self._items) - 1))

    def count(self) -> int:
        return len(self._items)

    def itemData(self, index: int) -> str:
        return self._items[index][1]

    def itemText(self, index: int) -> str:
        return self._items[index][0]

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = index

    def currentData(self) -> str:
        return self._items[self._current_index][1]


def _segment(uid: str, lines: list[str]) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(lines),
        original_lines=list(lines),
        source_lines=list(lines),
    )


class MassTranslateApplyWorkflowTests(unittest.TestCase):
    def test_collect_apply_warning_issues_includes_line_warning_and_previews(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        segment = _segment("Map001.json:1", ["src-a", "src-b"])
        harness.dialogue_targets["D:1"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:1"}]
        updates_by_id = {"D:1": {"id": "D:1", "translation": "one-line"}}

        issues = harness._collect_apply_warning_issues(chunk_entries, updates_by_id)

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.entry_id, "D:1")
        self.assertTrue(
            any("Collapsed to 1 line" in reason for reason in issue.warning_reasons)
        )
        self.assertIn("src-a", issue.source_preview)
        self.assertIn("one-line", issue.translation_preview)

    def test_collect_apply_warning_issues_skips_matching_and_speaker_ids(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        segment = _segment("Map001.json:2", ["src-a", "src-b"])
        harness.dialogue_targets["D:2"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:2"}, {"id": "S:hero"}]
        updates_by_id = {
            "D:2": {"id": "D:2", "translation": ["line-a", "line-b"]},
            "S:hero": {"id": "S:hero", "translation": "Hero"},
        }

        issues = harness._collect_apply_warning_issues(chunk_entries, updates_by_id)

        self.assertEqual(issues, [])

    def test_collapsed_warning_mode_ignores_noncollapsed_line_count_mismatch(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.warning_level_combo = _ComboStub("collapsed_lines_only")
        segment = _segment("Map001.json:3", ["src-a", "src-b"])
        harness.dialogue_targets["D:3"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:3"}]
        updates_by_id = {"D:3": {"id": "D:3", "translation_lines": ["a", "b", "c"]}}

        issues = harness._collect_apply_warning_issues(chunk_entries, updates_by_id)

        self.assertEqual(issues, [])

    def test_all_line_warning_mode_flags_noncollapsed_line_count_mismatch(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.warning_level_combo = _ComboStub("all_line_mismatches")
        segment = _segment("Map001.json:3", ["src-a", "src-b"])
        harness.dialogue_targets["D:3"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:3"}]
        updates_by_id = {"D:3": {"id": "D:3", "translation_lines": ["a", "b", "c"]}}

        issues = harness._collect_apply_warning_issues(chunk_entries, updates_by_id)

        self.assertEqual(len(issues), 1)
        self.assertTrue(
            any("Line count 3 lines" in reason for reason in issues[0].warning_reasons)
        )

    def test_collect_apply_warning_issues_warns_on_control_code_mismatch(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.warning_level_combo = _ComboStub("all_line_and_control_mismatches")
        segment = _segment("Map001.json:4", [r"\C[2]src-a", r"src-b\C[0]"])
        harness.dialogue_targets["D:4"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:4"}]
        updates_by_id = {
            "D:4": {"id": "D:4", "translation_lines": [r"\C[2]tl-a", "tl-b"]}
        }

        issues = harness._collect_apply_warning_issues(chunk_entries, updates_by_id)

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertTrue(
            any("Control-code mismatch" in reason for reason in issue.warning_reasons)
        )

    def test_all_line_warning_mode_does_not_flag_control_code_only_mismatch(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.warning_level_combo = _ComboStub("all_line_mismatches")
        segment = _segment("Map001.json:5", [r"\C[2]src-a", r"src-b\C[0]"])
        harness.dialogue_targets["D:5"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:5"}]
        updates_by_id = {
            "D:5": {"id": "D:5", "translation_lines": [r"\C[2]tl-a", "tl-b"]}
        }

        issues = harness._collect_apply_warning_issues(chunk_entries, updates_by_id)

        self.assertEqual(issues, [])

    def test_next_chunk_index_after_apply_prefers_copy_next(self) -> None:
        idx = _ApplyWorkflowHarness._next_chunk_index_after_apply(
            1,
            4,
            clear_paste_after_apply=False,
            copy_next_prompt=True,
        )
        self.assertEqual(idx, 2)

    def test_next_chunk_index_after_apply_only_advances_on_clean_apply(self) -> None:
        same_idx = _ApplyWorkflowHarness._next_chunk_index_after_apply(
            1,
            4,
            clear_paste_after_apply=False,
            copy_next_prompt=False,
        )
        self.assertEqual(same_idx, 1)

        next_idx = _ApplyWorkflowHarness._next_chunk_index_after_apply(
            1,
            4,
            clear_paste_after_apply=True,
            copy_next_prompt=False,
        )
        self.assertEqual(next_idx, 2)

    def test_next_incomplete_scope_value_picks_next_pending_scope(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.scope_combo = _ScopeComboStub(
            [
                ("All Files", "all"),
                ("Map001.json", "file:Map001.json"),
                ("Map002.json", "file:Map002.json"),
                ("Map003.json", "file:Map003.json"),
            ],
            current_index=1,
        )
        harness._scope_counts = {
            "all": (2, 6),
            "file:Map001.json": (2, 2),
            "file:Map002.json": (1, 2),
            "file:Map003.json": (3, 3),
        }

        next_scope = harness._next_incomplete_scope_value("file:Map001.json")

        self.assertEqual(next_scope, "file:Map002.json")

    def test_next_incomplete_scope_value_wraps_around_scope_list(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.scope_combo = _ScopeComboStub(
            [
                ("All Files", "all"),
                ("Map001.json", "file:Map001.json"),
                ("Map002.json", "file:Map002.json"),
                ("Map003.json", "file:Map003.json"),
            ],
            current_index=3,
        )
        harness._scope_counts = {
            "all": (2, 6),
            "file:Map001.json": (1, 2),
            "file:Map002.json": (2, 2),
            "file:Map003.json": (2, 2),
        }

        next_scope = harness._next_incomplete_scope_value("file:Map003.json")

        self.assertEqual(next_scope, "file:Map001.json")


if __name__ == "__main__":
    unittest.main()
