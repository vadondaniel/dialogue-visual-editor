from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.mixins.structural_editing_mixin import (
    _coerce_smart_collapse_rule_counts,
    _merge_smart_collapse_projection_modes,
    _normalize_smart_collapse_projection_mode,
)


class SmartCollapseProjectionModeTests(unittest.TestCase):
    def test_normalize_projection_mode(self) -> None:
        self.assertEqual(_normalize_smart_collapse_projection_mode("all"), "all")
        self.assertEqual(
            _normalize_smart_collapse_projection_mode("SOFT_ONLY"), "soft_only"
        )
        self.assertEqual(
            _normalize_smart_collapse_projection_mode("  none  "), "none"
        )
        self.assertEqual(
            _normalize_smart_collapse_projection_mode("unknown-mode"), "none"
        )

    def test_merge_projection_modes_prefers_higher_priority(self) -> None:
        self.assertEqual(
            _merge_smart_collapse_projection_modes("none", "soft_only"),
            "soft_only",
        )
        self.assertEqual(
            _merge_smart_collapse_projection_modes("soft_only", "none"),
            "soft_only",
        )
        self.assertEqual(
            _merge_smart_collapse_projection_modes("soft_only", "all"),
            "all",
        )
        self.assertEqual(
            _merge_smart_collapse_projection_modes("all", "soft_only"),
            "all",
        )

    def test_coerce_rule_counts_uses_fallback_for_missing_keys(self) -> None:
        fallback = {
            "soft_rule": 9,
            "comma": 4,
            "colon_triplet": 3,
            "ellipsis_lowercase": 2,
            "no_punctuation": 1,
        }
        parsed = _coerce_smart_collapse_rule_counts(
            {"soft_rule": "7", "comma": -3},
            fallback_counts=fallback,
        )

        self.assertEqual(parsed["soft_rule"], 7)
        self.assertEqual(parsed["comma"], 0)
        self.assertEqual(parsed["colon_triplet"], 3)
        self.assertEqual(parsed["ellipsis_lowercase"], 2)
        self.assertEqual(parsed["no_punctuation"], 1)


if __name__ == "__main__":
    unittest.main()
