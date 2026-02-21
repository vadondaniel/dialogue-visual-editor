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
    _entry_primary_target_for_id = MassTranslateDialog._entry_primary_target_for_id
    _expected_source_line_count = MassTranslateDialog._expected_source_line_count
    _collect_line_mismatch_issues = MassTranslateDialog._collect_line_mismatch_issues
    _next_chunk_index_after_apply = staticmethod(
        MassTranslateDialog._next_chunk_index_after_apply
    )

    def __init__(self, editor: Any) -> None:
        self.editor = editor
        self.dialogue_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.misc_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.speaker_segment_targets: dict[str, tuple[Path, DialogueSegment]] = {}


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
    def test_collect_line_mismatch_issues_includes_previews(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        segment = _segment("Map001.json:1", ["src-a", "src-b"])
        harness.dialogue_targets["D:1"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:1"}]
        updates_by_id = {"D:1": {"id": "D:1", "translation": "one-line"}}

        issues = harness._collect_line_mismatch_issues(chunk_entries, updates_by_id)

        self.assertEqual(len(issues), 1)
        issue = issues[0]
        self.assertEqual(issue.entry_id, "D:1")
        self.assertEqual(issue.expected_lines, 2)
        self.assertEqual(issue.actual_lines, 1)
        self.assertIn("src-a", issue.source_preview)
        self.assertIn("one-line", issue.translation_preview)

    def test_collect_line_mismatch_issues_skips_matching_and_speaker_ids(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        segment = _segment("Map001.json:2", ["src-a", "src-b"])
        harness.dialogue_targets["D:2"] = (Path("Map001.json"), segment)
        chunk_entries = [{"id": "D:2"}, {"id": "S:hero"}]
        updates_by_id = {
            "D:2": {"id": "D:2", "translation": ["line-a", "line-b"]},
            "S:hero": {"id": "S:hero", "translation": "Hero"},
        }

        issues = harness._collect_line_mismatch_issues(chunk_entries, updates_by_id)

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


if __name__ == "__main__":
    unittest.main()
