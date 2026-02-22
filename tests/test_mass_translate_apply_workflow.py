from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession
from dialogue_visual_editor.helpers.ui.mass_translate_dialog import MassTranslateDialog


class _ApplyWorkflowEditorMeta:
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}

    @staticmethod
    def _normalize_speaker_key(value: str) -> str:
        return value.strip()

    @staticmethod
    def _speaker_key_for_segment(segment: DialogueSegment) -> str:
        raw = getattr(segment, "speaker_name", "")
        return raw.strip() if isinstance(raw, str) else ""

    @staticmethod
    def _resolve_name_tokens_in_text(
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = (prefer_translated, unresolved_placeholder)
        return text

    @staticmethod
    def _resolve_speaker_display_name(raw_speaker: str) -> str:
        return raw_speaker

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

    @staticmethod
    def _speaker_translation_for_key(speaker_key: str) -> str:
        _ = speaker_key
        return ""


class _ApplyWorkflowHarness:
    _default_prompt_template = classmethod(MassTranslateDialog._default_prompt_template.__func__)
    _normalize_prompt_language_code = staticmethod(
        MassTranslateDialog._normalize_prompt_language_code
    )
    _language_field_prefix = staticmethod(MassTranslateDialog._language_field_prefix)
    _source_text_field_name = MassTranslateDialog._source_text_field_name
    _target_translation_field_name = MassTranslateDialog._target_translation_field_name
    _translation_prompt_metadata = MassTranslateDialog._translation_prompt_metadata
    _speaker_display_for_prompt = MassTranslateDialog._speaker_display_for_prompt
    _resolve_name_tokens_for_prompt = MassTranslateDialog._resolve_name_tokens_for_prompt
    _actor_source_name_map_for_prompt = MassTranslateDialog._actor_source_name_map_for_prompt
    _context_blocks_for_anchor = MassTranslateDialog._context_blocks_for_anchor
    _chunk_entry_runs = MassTranslateDialog._chunk_entry_runs
    _chunk_entry_windows = MassTranslateDialog._chunk_entry_windows
    _context_payload_for_chunk = MassTranslateDialog._context_payload_for_chunk
    _entries_from_entry_windows = staticmethod(
        MassTranslateDialog._entries_from_entry_windows
    )
    _chunk_entries_from_payload = MassTranslateDialog._chunk_entries_from_payload
    _entries_from_payload = MassTranslateDialog._entries_from_payload
    _extract_dialogue_translation_lines = MassTranslateDialog._extract_dialogue_translation_lines
    _normalize_translation_lines_for_segment = (
        MassTranslateDialog._normalize_translation_lines_for_segment
    )
    _has_translatable_source_lines = staticmethod(MassTranslateDialog._has_translatable_source_lines)
    _segment_content_type = MassTranslateDialog._segment_content_type
    _should_collect_global_speaker_key = staticmethod(
        MassTranslateDialog._should_collect_global_speaker_key
    )
    _segment_has_translation = MassTranslateDialog._segment_has_translation
    _segments_for_session_mass_translate = (
        MassTranslateDialog._segments_for_session_mass_translate
    )
    _segment_source_lines_for_mass_translate = (
        MassTranslateDialog._segment_source_lines_for_mass_translate
    )
    _persistent_speaker_key_for_segment = (
        MassTranslateDialog._persistent_speaker_key_for_segment
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
    _apply_warning_translation_overrides = (
        MassTranslateDialog._apply_warning_translation_overrides
    )
    _overall_translation_progress_counts = (
        MassTranslateDialog._overall_translation_progress_counts
    )
    _default_chunk_result_message = staticmethod(
        MassTranslateDialog._default_chunk_result_message
    )
    _result_message_for_chunk = MassTranslateDialog._result_message_for_chunk
    _set_result_message_for_chunk = MassTranslateDialog._set_result_message_for_chunk
    _append_result_message_for_chunk = (
        MassTranslateDialog._append_result_message_for_chunk
    )
    _set_scope_value = MassTranslateDialog._set_scope_value
    _scope_has_pending_entries_for_value = (
        MassTranslateDialog._scope_has_pending_entries_for_value
    )
    _next_incomplete_scope_value = MassTranslateDialog._next_incomplete_scope_value
    _copy_prompt_for_current_chunk = MassTranslateDialog._copy_prompt_for_current_chunk
    _next_chunk_index_after_apply = staticmethod(
        MassTranslateDialog._next_chunk_index_after_apply
    )

    def __init__(self, editor: Any) -> None:
        self.editor = editor
        self.dialogue_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.misc_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.speaker_segment_targets: dict[str, tuple[Path, DialogueSegment]] = {}
        self.entry_block_refs: dict[str, tuple[Path, int]] = {}
        self.warning_level_combo = _ComboStub("all_line_and_control_mismatches")
        self.chunk_result_messages: dict[int, str] = {}
        self.chunk_combo = _ChunkComboStub(0)
        self.result_box = _TextBoxStub()
        self.copied_prompt_indices: list[int] = []
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

    def _copy_prompt_for_chunk_index(self, index: int) -> bool:
        if index < 0:
            return False
        self.copied_prompt_indices.append(index)
        return True


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


class _ChunkComboStub:
    def __init__(self, current_index: int) -> None:
        self._current_index = current_index

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        self._current_index = index


class _TextBoxStub:
    def __init__(self) -> None:
        self.text = ""

    def setPlainText(self, text: str) -> None:
        self.text = text

    def appendPlainText(self, text: str) -> None:
        if self.text:
            self.text = f"{self.text}\n{text}"
        else:
            self.text = text


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
    def test_context_payload_for_chunk_uses_top_level_context_for_continuous_run(self) -> None:
        editor = _ApplyWorkflowEditorMeta()
        path = Path("Map001.json")
        segments = [_segment(f"Map001.json:{idx}", [f"line-{idx}"]) for idx in range(5)]
        editor.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=segments,
        )
        harness = _ApplyWorkflowHarness(editor)
        harness.entry_block_refs = {
            "D:1": (path, 1),
            "D:2": (path, 2),
        }

        payload = harness._context_payload_for_chunk(
            [{"id": "D:1"}, {"id": "D:2"}],
            1,
        )

        self.assertNotIn("entry_windows", payload)
        self.assertEqual(payload["context_before"][0]["ja_text"], "line-0")
        self.assertEqual(payload["context_after"][0]["ja_text"], "line-3")

    def test_context_payload_for_chunk_uses_entry_windows_for_gapped_runs(self) -> None:
        editor = _ApplyWorkflowEditorMeta()
        path = Path("Map001.json")
        segments = [_segment(f"Map001.json:{idx}", [f"line-{idx}"]) for idx in range(7)]
        editor.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=segments,
        )
        harness = _ApplyWorkflowHarness(editor)
        harness.entry_block_refs = {
            "D:1": (path, 1),
            "D:2": (path, 2),
            "D:5": (path, 5),
        }

        payload = harness._context_payload_for_chunk(
            [{"id": "D:1"}, {"id": "D:2"}, {"id": "D:5"}],
            1,
        )

        self.assertNotIn("context_before", payload)
        self.assertNotIn("context_after", payload)
        windows = payload["entry_windows"]
        self.assertEqual(len(windows), 2)
        self.assertEqual([entry["id"] for entry in windows[0]["entries"]], ["D:1", "D:2"])
        self.assertEqual(windows[0]["context_before"][0]["ja_text"], "line-0")
        self.assertEqual(windows[0]["context_after"][0]["ja_text"], "line-3")
        self.assertEqual([entry["id"] for entry in windows[1]["entries"]], ["D:5"])
        self.assertEqual(windows[1]["context_before"][0]["ja_text"], "line-4")
        self.assertEqual(windows[1]["context_after"][0]["ja_text"], "line-6")

    def test_context_payload_keeps_both_sides_when_window_context_matches(self) -> None:
        editor = _ApplyWorkflowEditorMeta()
        path = Path("Map001.json")
        segments = [_segment(f"Map001.json:{idx}", [f"line-{idx}"]) for idx in range(5)]
        editor.sessions[path] = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=segments,
        )
        harness = _ApplyWorkflowHarness(editor)
        harness.entry_block_refs = {
            "D:1": (path, 1),
            "D:3": (path, 3),
        }

        payload = harness._context_payload_for_chunk(
            [{"id": "D:1"}, {"id": "D:3"}],
            1,
        )

        windows = payload["entry_windows"]
        self.assertEqual(windows[0]["context_after"][0]["ja_text"], "line-2")
        self.assertEqual(windows[1]["context_before"][0]["ja_text"], "line-2")

    def test_entries_from_payload_flattens_entry_windows(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        payload = {
            "entry_windows": [
                {"entries": [{"id": "D:1", "translation": "one"}]},
                {"entries": [{"id": "D:2", "translation": "two"}]},
            ]
        }

        parsed = harness._entries_from_payload(payload)

        self.assertEqual([entry["id"] for entry in parsed], ["D:1", "D:2"])

    def test_chunk_entries_from_payload_flattens_entry_windows(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        payload = {
            "entry_windows": [
                {"entries": [{"id": "D:1"}]},
                {"entries": [{"id": "D:2"}]},
            ]
        }

        parsed = harness._chunk_entries_from_payload(payload)

        self.assertEqual([entry["id"] for entry in parsed], ["D:1", "D:2"])

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

    def test_collect_apply_warning_issues_treats_tyrano_inline_r_as_newlines(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.warning_level_combo = _ComboStub("all_line_mismatches")
        segment = _segment("scene.ks:K:1", ["src-a", "src-b"])
        segment.segment_kind = "tyrano_dialogue"
        harness.dialogue_targets["D:TYRANO:1"] = (Path("scene.ks"), segment)
        chunk_entries = [{"id": "D:TYRANO:1"}]
        updates_by_id = {
            "D:TYRANO:1": {"id": "D:TYRANO:1", "translation": "tl-a[r]tl-b"}
        }

        issues = harness._collect_apply_warning_issues(chunk_entries, updates_by_id)

        self.assertEqual(issues, [])

    def test_apply_warning_translation_overrides_updates_target_field(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        updates_by_id = {
            "D:1": {"id": "D:1", "translation": "old"},
            "D:2": {"id": "D:2", "translation": "same"},
        }

        harness._apply_warning_translation_overrides(
            updates_by_id,
            {"D:1"},
            {"D:1": "edited", "D:2": "should-not-apply"},
        )

        self.assertEqual(updates_by_id["D:1"]["en_translation"], "edited")
        self.assertEqual(updates_by_id["D:2"].get("en_translation"), None)

    def test_normalize_translation_lines_for_segment_strips_tyrano_p_and_splits_r(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        segment = _segment("scene.ks:KQ:1", ["src"])
        segment.segment_kind = "choice"

        normalized = harness._normalize_translation_lines_for_segment(
            segment,
            ["Alpha[p][r]Beta"],
        )

        self.assertEqual(normalized, ["Alpha", "Beta"])

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

    def test_overall_translation_progress_counts_ignore_warning_level(self) -> None:
        editor = _ApplyWorkflowEditorMeta()
        translated_misc = _segment("Map001.json:N:1", ["src-a"])
        translated_misc.segment_kind = "note_text"
        translated_misc.translation_lines = ["tl-a"]
        untranslated_misc = _segment("Map001.json:N:2", ["src-b"])
        untranslated_misc.segment_kind = "note_text"
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[translated_misc, untranslated_misc],
        )
        editor.sessions[session.path] = session
        harness = _ApplyWorkflowHarness(editor)

        harness.warning_level_combo = _ComboStub("collapsed_lines_only")
        done_collapsed, total_collapsed = harness._overall_translation_progress_counts()

        harness.warning_level_combo = _ComboStub("all_line_and_control_mismatches")
        done_strict, total_strict = harness._overall_translation_progress_counts()

        self.assertEqual((done_collapsed, total_collapsed), (1, 2))
        self.assertEqual((done_strict, total_strict), (1, 2))

    def test_next_chunk_index_after_apply_prefers_copy_next(self) -> None:
        idx = _ApplyWorkflowHarness._next_chunk_index_after_apply(
            1,
            4,
            clear_paste_after_apply=False,
            copy_next_prompt=True,
        )
        self.assertEqual(idx, 2)

    def test_copy_prompt_for_current_chunk_copies_active_chunk_prompt(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.chunk_combo = _ChunkComboStub(3)

        copied = harness._copy_prompt_for_current_chunk()

        self.assertTrue(copied)
        self.assertEqual(harness.copied_prompt_indices, [3])

    def test_copy_prompt_for_current_chunk_fails_for_invalid_index(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.chunk_combo = _ChunkComboStub(-1)

        copied = harness._copy_prompt_for_current_chunk()

        self.assertFalse(copied)
        self.assertEqual(harness.copied_prompt_indices, [])

    def test_set_result_message_for_chunk_keeps_per_chunk_values(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.chunk_combo = _ChunkComboStub(0)

        harness._set_result_message_for_chunk(0, "chunk0 status")
        harness._set_result_message_for_chunk(1, "chunk1 status")

        self.assertEqual(harness._result_message_for_chunk(0), "chunk0 status")
        self.assertEqual(harness._result_message_for_chunk(1), "chunk1 status")
        self.assertEqual(harness.result_box.text, "chunk0 status")

    def test_append_result_message_for_chunk_appends_lines(self) -> None:
        harness = _ApplyWorkflowHarness(_ApplyWorkflowEditorMeta())
        harness.chunk_combo = _ChunkComboStub(2)

        harness._set_result_message_for_chunk(2, "line1")
        harness._append_result_message_for_chunk(2, "line2")

        self.assertEqual(harness._result_message_for_chunk(2), "line1\nline2")
        self.assertEqual(harness.result_box.text, "line1\nline2")

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
