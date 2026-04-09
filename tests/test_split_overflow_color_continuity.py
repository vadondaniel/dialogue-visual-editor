from __future__ import annotations

from pathlib import Path
import unittest
from typing import Any

from helpers.mixins.structural_editing_mixin import (
    StructuralEditingMixin,
)
from helpers.core.models import DialogueSegment, FileSession


class _Harness(StructuralEditingMixin):
    pass


class _Check:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _ProjectionHarness(StructuralEditingMixin):
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.current_path: Path | None = None
        self.infer_speaker_check = _Check(False)
        self._translator_mode = False

    def _is_translator_mode(self) -> bool:
        return self._translator_mode

    @staticmethod
    def _is_name_index_session(_session: FileSession) -> bool:
        return False

    @staticmethod
    def _segment_has_inferred_line1_speaker(_segment: DialogueSegment) -> bool:
        return False

    def _segment_line_width(self, segment: DialogueSegment) -> int:
        return 60

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    @staticmethod
    def _segment_translation_lines_for_translation(segment: DialogueSegment) -> list[str]:
        return list(segment.translation_lines or [""])

    @staticmethod
    def _compose_translation_lines_for_segment(
        _segment: DialogueSegment,
        visible_lines: list[str],
    ) -> list[str]:
        return list(visible_lines) if visible_lines else [""]


class SplitOverflowColorContinuityTests(unittest.TestCase):
    def test_smart_collapse_eligibility_includes_tyrano_dialogue(self) -> None:
        harness = _Harness()
        segment = DialogueSegment(
            uid="scene.ks:K:1",
            context="ctx",
            code101={},
            lines=["A", "B"],
            original_lines=["A", "B"],
            source_lines=["A", "B"],
            segment_kind="tyrano_dialogue",
        )

        self.assertTrue(harness._is_smart_collapse_eligible_segment(segment))

    def test_applies_continuity_when_no_inferred_marker(self) -> None:
        harness = _Harness()

        kept, moved = StructuralEditingMixin._apply_split_overflow_color_continuity(
            harness,
            [r"\C[2]Hello"],
            ["World"],
            inferred_marker="",
        )

        self.assertEqual(kept, [r"\C[2]Hello\C[0]"])
        self.assertEqual(moved, [r"\C[2]World"])

    def test_skips_extra_continuity_when_marker_already_provides_color(self) -> None:
        harness = _Harness()

        kept, moved = StructuralEditingMixin._apply_split_overflow_color_continuity(
            harness,
            [r"\C[2]Hero", "Line A"],
            ["Line B"],
            inferred_marker=r"\C[2]Hero",
        )

        self.assertEqual(kept, [r"\C[2]Hero", "Line A"])
        self.assertEqual(moved, ["Line B"])

    def test_keeps_continuity_when_marker_color_differs(self) -> None:
        harness = _Harness()

        kept, moved = StructuralEditingMixin._apply_split_overflow_color_continuity(
            harness,
            [r"\C[3]Hero", r"\C[2]Line A"],
            ["Line B"],
            inferred_marker=r"\C[3]Hero",
        )

        self.assertEqual(kept, [r"\C[3]Hero", r"\C[2]Line A\C[0]"])
        self.assertEqual(moved, [r"\C[2]Line B"])

    def test_projected_smart_collapse_count_respects_scope(self) -> None:
        harness = _ProjectionHarness()
        current_path = Path("Map001.json")
        other_path = Path("Map002.json")
        harness.current_path = current_path
        harness.sessions[current_path] = FileSession(
            path=current_path,
            data=[],
            bundles=[],
            segments=[
                DialogueSegment(
                    uid="a",
                    context="ctx",
                    code101={},
                    lines=["No punctuation here next line"],
                    original_lines=["No punctuation here next line"],
                    source_lines=["No punctuation here next line"],
                    segment_kind="dialogue",
                )
            ],
        )
        harness.sessions[other_path] = FileSession(
            path=other_path,
            data=[],
            bundles=[],
            segments=[
                DialogueSegment(
                    uid="b",
                    context="ctx",
                    code101={},
                    lines=["No punctuation here", "next line"],
                    original_lines=["No punctuation here", "next line"],
                    source_lines=["No punctuation here", "next line"],
                    segment_kind="dialogue",
                )
            ],
        )

        current_only_blocks, current_only_files = (
            harness._count_projected_smart_collapse_changes(
                allow_comma_endings=False,
                allow_colon_triplet_endings=False,
                ellipsis_lowercase_rule=False,
                collapse_if_no_punctuation=True,
                min_soft_ratio=0.5,
                apply_all_files=False,
            )
        )
        all_files_blocks, all_files_files = (
            harness._count_projected_smart_collapse_changes(
                allow_comma_endings=False,
                allow_colon_triplet_endings=False,
                ellipsis_lowercase_rule=False,
                collapse_if_no_punctuation=True,
                min_soft_ratio=0.5,
                apply_all_files=True,
            )
        )

        self.assertEqual(current_only_blocks, 0)
        self.assertEqual(current_only_files, 0)
        self.assertEqual(all_files_blocks, 1)
        self.assertEqual(all_files_files, 1)


if __name__ == "__main__":
    unittest.main()
