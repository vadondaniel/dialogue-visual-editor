from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast

from dialogue_visual_editor.app import DialogueVisualEditor
from dialogue_visual_editor.helpers.core.models import DialogueSegment, NO_SPEAKER_KEY
from dialogue_visual_editor.helpers.ui.ui_components import SpeakerManagerDialog


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


def _call_speaker_dialog_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(SpeakerManagerDialog, name))
    return method(self_obj, *args)


def _segment_with_speaker(speaker_text: str) -> DialogueSegment:
    return DialogueSegment(
        uid="seg",
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker_text]},
        lines=["line"],
        original_lines=["line"],
        source_lines=["line"],
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


if __name__ == "__main__":
    unittest.main()
