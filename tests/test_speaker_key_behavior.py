from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from dialogue_visual_editor.app import DialogueVisualEditor
from dialogue_visual_editor.helpers.core.models import (
    DialogueSegment,
    FileSession,
    NO_SPEAKER_KEY,
)
from dialogue_visual_editor.helpers.ui.ui_components import SpeakerManagerDialog


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


def _call_speaker_dialog_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(SpeakerManagerDialog, name))
    return method(self_obj, *args)


def _segment_with_speaker(
    speaker_text: str,
    *,
    segment_kind: str = "dialogue",
) -> DialogueSegment:
    return DialogueSegment(
        uid="seg",
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker_text]},
        lines=["line"],
        original_lines=["line"],
        source_lines=["line"],
        segment_kind=segment_kind,
    )


class _SpeakerKeyHarness:
    def __init__(self) -> None:
        self.resolve_calls = 0

    def _normalize_speaker_key(self, value: str) -> str:
        return cast(str, _call_editor_method("_normalize_speaker_key", self, value))

    def _inferred_speaker_from_segment_line1(self, segment: DialogueSegment) -> str:
        _ = segment
        return ""

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        self.resolve_calls += 1
        return text


class _SpeakerTranslationHarness:
    def __init__(self) -> None:
        self.speaker_translation_map: dict[str, str] = {}
        self._resolved_lookup: dict[str, str] = {}

    def _normalize_speaker_key(self, value: str) -> str:
        return cast(str, _call_editor_method("_normalize_speaker_key", self, value))

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        return self._resolved_lookup.get(text, text)

    def _actor_name_maps(self) -> tuple[dict[int, str], dict[int, str]]:
        return {}, {}


class _Line1InferenceHarness:
    def __init__(self, enabled: bool = True) -> None:
        self.infer_speaker_check = SimpleNamespace(isChecked=lambda: enabled)

    def _segment_source_lines_for_display(self, segment: DialogueSegment) -> list[str]:
        lines = segment.source_lines or segment.original_lines or segment.lines
        return list(lines) if lines else [""]

    def _flatten_embedded_newlines(self, lines: list[str]) -> list[str]:
        flattened: list[str] = []
        for raw in lines:
            text = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            flattened.extend(normalized.split("\n"))
        return flattened or [""]

    def _source_lines_for_line1_inference(self, segment: DialogueSegment) -> list[str]:
        return self._flatten_embedded_newlines(
            self._segment_source_lines_for_display(segment)
        )

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        return text

    def _matches_name_token(self, text: str) -> bool:
        return cast(bool, _call_editor_method("_matches_name_token", self, text))

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [item if isinstance(item, str) else ("" if item is None else str(item)) for item in value] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    def _segment_has_inferred_line1_speaker(
        self,
        segment: DialogueSegment,
        *,
        infer_speaker_enabled: Any = None,
    ) -> bool:
        _ = infer_speaker_enabled
        inferred = cast(
            str,
            _call_editor_method("_inferred_speaker_from_segment_line1", self, segment),
        )
        return bool(inferred)


class _SpeakerInferenceCandidateHarness:
    def __init__(self) -> None:
        self.infer_speaker_check = SimpleNamespace(isChecked=lambda: True)
        self.current_path: Path | None = None
        self.open_calls: list[tuple[Path, str, str]] = []
        self.render_calls = 0
        self._status_messages: list[str] = []
        self.speaker_translation_map: dict[str, str] = {}
        segment_a = DialogueSegment(
            uid="Map001:1",
            context="Map001 > Event 1",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=["Hero", "Line A"],
            original_lines=["Hero", "Line A"],
            source_lines=["Hero", "Line A"],
        )
        segment_b = DialogueSegment(
            uid="Map001:2",
            context="Map001 > Event 2",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=["Hero", "Line B"],
            original_lines=["Hero", "Line B"],
            source_lines=["Hero", "Line B"],
        )
        segment_c = DialogueSegment(
            uid="Map001:3",
            context="Map001 > Event 3",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=["Rival", "Line C"],
            original_lines=["Rival", "Line C"],
            source_lines=["Rival", "Line C"],
        )
        segment_d = DialogueSegment(
            uid="Map001:4",
            context="Map001 > Event 4",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Hero"]},
            lines=["Line D"],
            original_lines=["Line D"],
            source_lines=["Line D"],
            translation_speaker="Aki",
        )
        self.path_a = Path("Map001.json")
        self.path_b = Path("Map002.json")
        self.sessions: dict[Path, FileSession] = {
            self.path_a: FileSession(
                path=self.path_a,
                data=[],
                bundles=[],
                segments=[segment_a, segment_b, segment_c, segment_d],
            ),
            self.path_b: FileSession(
                path=self.path_b,
                data=[],
                bundles=[],
                segments=[],
            ),
        }

    def _speaker_inference_enabled_for_manager(self) -> bool:
        return bool(self.infer_speaker_check.isChecked())

    def _is_name_index_session(self, _session: FileSession) -> bool:
        return False

    def _normalize_speaker_key(self, value: str) -> str:
        return cast(str, _call_editor_method("_normalize_speaker_key", self, value))

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        return text

    def _segment_source_lines_for_display(self, segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    def _flatten_embedded_newlines(self, lines: list[str]) -> list[str]:
        flattened: list[str] = []
        for raw in lines:
            text = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            flattened.extend(normalized.split("\n"))
        return flattened or [""]

    def _source_lines_for_line1_inference(self, segment: DialogueSegment) -> list[str]:
        return self._flatten_embedded_newlines(
            self._segment_source_lines_for_display(segment)
        )

    def _normalize_translation_lines(self, lines: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in lines:
            if isinstance(raw, str):
                normalized.append(raw)
            elif raw is None:
                normalized.append("")
            else:
                normalized.append(str(raw))
        return normalized or [""]

    def _matches_name_token(self, text: str) -> bool:
        return cast(bool, _call_editor_method("_matches_name_token", self, text))

    def _inferred_speaker_from_segment_line1(
        self,
        segment: DialogueSegment,
        *,
        infer_speaker_enabled: Any = None,
    ) -> str:
        _ = infer_speaker_enabled
        return cast(
            str,
            _call_editor_method("_inferred_speaker_from_segment_line1", self, segment),
        )

    def _speaker_translation_for_key(self, speaker_key: str) -> str:
        return cast(
            str,
            _call_editor_method("_speaker_translation_for_key", self, speaker_key),
        )

    def _actor_name_maps(self) -> tuple[dict[int, str], dict[int, str]]:
        return ({}, {})

    def _normalized_view_scope_for_path(
        self,
        _path: Path,
        _session: FileSession,
        requested_scope: str | None = None,
    ) -> str:
        if isinstance(requested_scope, str) and requested_scope.strip():
            return requested_scope.strip().lower()
        return "dialogue"

    def _open_file(
        self,
        path: Path,
        force_reload: bool = False,
        focus_uid: str | None = None,
        view_scope: str | None = None,
    ) -> None:
        _ = force_reload
        self.open_calls.append((path, focus_uid or "", view_scope or ""))

    def _render_session(
        self,
        _session: FileSession,
        focus_uid: str | None = None,
        preserve_scroll: bool = False,
        start_at_top: bool = False,
    ) -> None:
        _ = focus_uid
        _ = preserve_scroll
        _ = start_at_top
        self.render_calls += 1

    def statusBar(self) -> Any:
        return SimpleNamespace(showMessage=lambda message: self._status_messages.append(message))


class SpeakerKeyBehaviorTests(unittest.TestCase):
    def test_speaker_key_keeps_raw_name_tokens(self) -> None:
        harness = _SpeakerKeyHarness()
        segment = _segment_with_speaker(r"\C[2]\N[1]\C[0]")

        key = cast(str, _call_editor_method("_speaker_key_for_segment", harness, segment))

        self.assertIn(r"\N[1]", key)
        self.assertEqual(harness.resolve_calls, 0)

    def test_speaker_translation_uses_legacy_resolved_key_fallback(self) -> None:
        harness = _SpeakerTranslationHarness()
        raw_key = r"\C[2]\N[1]\C[0]"
        legacy_resolved_key = r"\C[2]Masatoki\C[0]"
        harness._resolved_lookup[raw_key] = legacy_resolved_key
        harness.speaker_translation_map[legacy_resolved_key] = "Masa"

        result = cast(
            str,
            _call_editor_method("_speaker_translation_for_key", harness, raw_key),
        )

        self.assertEqual(result, "Masa")

    def test_speaker_translation_returns_empty_for_none_key(self) -> None:
        harness = _SpeakerTranslationHarness()

        result = cast(
            str,
            _call_editor_method("_speaker_translation_for_key", harness, NO_SPEAKER_KEY),
        )

        self.assertEqual(result, "")

    def test_tyrano_dialogue_segment_keeps_explicit_speaker_key(self) -> None:
        harness = _SpeakerKeyHarness()
        segment = _segment_with_speaker("NPC", segment_kind="tyrano_dialogue")

        key = cast(str, _call_editor_method("_speaker_key_for_segment", harness, segment))

        self.assertEqual(key, "NPC")

    def test_speaker_manager_reads_raw_map_with_legacy_fallback(self) -> None:
        raw_key = r"\C[2]\N[1]\C[0]"
        legacy_resolved_key = r"\C[2]Masatoki\C[0]"
        editor = _SpeakerTranslationHarness()
        editor._resolved_lookup[raw_key] = legacy_resolved_key
        editor.speaker_translation_map[legacy_resolved_key] = "Masatoki"
        dialog_like = SimpleNamespace(editor=editor)

        result = cast(
            str,
            _call_speaker_dialog_method("_raw_translation_for_key", dialog_like, raw_key),
        )

        self.assertEqual(result, "Masatoki")

    def test_line1_inference_uses_quote_on_second_line(self) -> None:
        harness = _Line1InferenceHarness(enabled=True)
        quoted_line = r"\C[2]" + chr(0x300C) + "Lets go" + chr(0x300D)
        segment = DialogueSegment(
            uid="seg",
            context="ctx",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=["???", quoted_line],
            original_lines=["???", quoted_line],
            source_lines=["???", quoted_line],
        )

        inferred = cast(
            str,
            _call_editor_method("_inferred_speaker_from_segment_line1", harness, segment),
        )

        self.assertEqual(inferred, "???")

    def test_line1_inference_splits_embedded_newlines_in_source_line(self) -> None:
        harness = _Line1InferenceHarness(enabled=True)
        segment = DialogueSegment(
            uid="seg",
            context="ctx",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=["ユウキ\n「行こう」"],
            original_lines=["ユウキ\n「行こう」"],
            source_lines=["ユウキ\n「行こう」"],
        )

        inferred = cast(
            str,
            _call_editor_method("_inferred_speaker_from_segment_line1", harness, segment),
        )
        visible_source = cast(
            list[str],
            _call_editor_method("_segment_source_lines_for_translation", harness, segment),
        )
        segment.translation_lines = ["ユウキ\nLet's go"]
        visible_tl = cast(
            list[str],
            _call_editor_method("_segment_translation_lines_for_translation", harness, segment),
        )

        self.assertEqual(inferred, "ユウキ")
        self.assertEqual(visible_source, ["「行こう」"])
        self.assertEqual(visible_tl, ["Let's go"])

    def test_collect_inferred_speaker_candidates_ranks_by_occurrence(self) -> None:
        harness = _SpeakerInferenceCandidateHarness()

        rows = cast(
            list[dict[str, Any]],
            _call_editor_method("_collect_inferred_speaker_candidates_for_manager", harness),
        )

        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0]["speaker_key"], "Hero")
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["suggested_translation"], "Aki")
        self.assertEqual(rows[0]["sample_path"], str(harness.path_a))
        self.assertEqual(rows[0]["sample_uid"], "Map001:1")
        self.assertIn("inferred_count", rows[0])

    def test_collect_candidates_includes_non_inferred_first_lines(self) -> None:
        harness = _SpeakerInferenceCandidateHarness()
        non_inferred = DialogueSegment(
            uid="Map001:5",
            context="Map001 > Event 5",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=["Not a speaker line", "Still dialogue text"],
            original_lines=["Not a speaker line", "Still dialogue text"],
            source_lines=["Not a speaker line", "Still dialogue text"],
        )
        harness.sessions[harness.path_a].segments.append(non_inferred)

        inferred = cast(
            str,
            _call_editor_method(
                "_inferred_speaker_from_segment_line1",
                harness,
                non_inferred,
            ),
        )
        self.assertEqual(inferred, "")

        rows = cast(
            list[dict[str, Any]],
            _call_editor_method("_collect_inferred_speaker_candidates_for_manager", harness),
        )
        keys = {str(row.get("speaker_key", "")) for row in rows}
        self.assertIn("Not a speaker line", keys)

    def test_accept_inferred_speaker_candidate_forces_matching_segments(self) -> None:
        harness = _SpeakerInferenceCandidateHarness()
        segments = harness.sessions[harness.path_a].segments
        segments[0].disable_line1_speaker_inference = True
        segments[1].disable_line1_speaker_inference = True
        harness.current_path = harness.path_a

        changed = cast(
            int,
            _call_editor_method(
                "_accept_inferred_speaker_candidate_for_manager",
                harness,
                "Hero",
            ),
        )

        self.assertEqual(changed, 2)
        self.assertTrue(segments[0].force_line1_speaker_inference)
        self.assertFalse(segments[0].disable_line1_speaker_inference)
        self.assertTrue(segments[1].force_line1_speaker_inference)
        self.assertFalse(segments[1].disable_line1_speaker_inference)
        self.assertEqual(harness.render_calls, 1)

    def test_jump_to_speaker_candidate_entry_opens_target_file(self) -> None:
        harness = _SpeakerInferenceCandidateHarness()

        jumped = cast(
            bool,
            _call_editor_method(
                "_jump_to_speaker_candidate_entry_for_manager",
                harness,
                str(harness.path_a),
                "Map001:2",
            ),
        )

        self.assertTrue(jumped)
        self.assertEqual(len(harness.open_calls), 1)
        target_path, target_uid, target_scope = harness.open_calls[0]
        self.assertEqual(target_path, harness.path_a)
        self.assertEqual(target_uid, "Map001:2")
        self.assertEqual(target_scope, "dialogue")


if __name__ == "__main__":
    unittest.main()
