from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.mixins.structural_editing_mixin import (
    StructuralEditingMixin,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment


class _Harness(StructuralEditingMixin):
    pass


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


if __name__ == "__main__":
    unittest.main()
