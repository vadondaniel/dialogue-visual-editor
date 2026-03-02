from __future__ import annotations

import unittest
from typing import Any, cast

from dialogue_visual_editor.app import DialogueVisualEditor
from dialogue_visual_editor.helpers.core.models import DialogueSegment


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


def _segment(uid: str, translation_lines: list[str]) -> DialogueSegment:
    segment = DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[""],
        original_lines=[""],
        source_lines=[""],
    )
    segment.translation_lines = list(translation_lines)
    return segment


class _LogicalProblemNormalizationHarness:
    def __init__(self, chain: list[DialogueSegment]) -> None:
        self._chain = chain

    def _logical_translation_chain_for_segment(
        self,
        _segment: DialogueSegment,
        *,
        session: Any = None,
    ) -> list[DialogueSegment]:
        _ = session
        return list(self._chain)

    def _segment_translation_lines_for_translation(
        self,
        segment: DialogueSegment,
        *,
        infer_speaker_enabled: Any = None,
    ) -> list[str]:
        _ = infer_speaker_enabled
        return list(segment.translation_lines or [""])

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [
                item if isinstance(item, str) else ("" if item is None else str(item))
                for item in value
            ] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]


class LogicalProblemChainNormalizationTests(unittest.TestCase):
    def test_followup_trailing_reset_is_kept_without_leading_wrapper_strip(self) -> None:
        anchor = _segment(
            "A:1",
            [
                r"\C[2]Villager\C[0]",
                r"the \C[14]cooking\C[0]!",
            ],
        )
        followup = _segment(
            "A:2",
            [
                r"\C[2]Villager\C[0]",
                r"Perfect \C[23]man\C[0]...\C[27]♡\C[0]",
            ],
        )
        followup.translation_only = True
        harness = _LogicalProblemNormalizationHarness([anchor, followup])

        normalized = cast(
            list[str],
            _call_editor_method(
                "_logical_translation_lines_for_problem_checks",
                harness,
                anchor,
            ),
        )

        self.assertTrue(normalized[-1].endswith(r"\C[0]"))
        self.assertIn(r"\C[27]♡\C[0]", normalized[-1])

    def test_followup_trailing_reset_is_dropped_when_leading_wrapper_is_stripped(self) -> None:
        anchor = _segment("A:1", [r"\C[14]Press confirm\C[0]"])
        followup = _segment("A:2", [r"\C[27]Second line\C[0]"])
        followup.translation_only = True
        harness = _LogicalProblemNormalizationHarness([anchor, followup])

        normalized = cast(
            list[str],
            _call_editor_method(
                "_logical_translation_lines_for_problem_checks",
                harness,
                anchor,
            ),
        )

        self.assertEqual(normalized, [r"\C[14]Press confirm\C[0]", "Second line"])


if __name__ == "__main__":
    unittest.main()
