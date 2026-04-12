from __future__ import annotations

import unittest
from typing import Any, cast

from app import DialogueVisualEditor


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


class _ComboStub:
    def __init__(self, data: Any) -> None:
        self._data = data

    def currentData(self) -> Any:
        return self._data


class _SpinStub:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _CheckStub:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _Harness:
    def __init__(self) -> None:
        self.editor_mode_combo = _ComboStub("translator")
        self.apply_version_combo = _ComboStub("translated")
        self.thin_width_spin = _SpinStub(44)
        self.wide_width_spin = _SpinStub(56)
        self.max_lines_spin = _SpinStub(4)
        self.auto_split_check = _CheckStub(False)
        self.infer_speaker_check = _CheckStub(True)
        self.bg1_thoughts_check = _CheckStub(True)
        self.default_variable_length_estimate = 6
        self.variable_length_overrides = {5: 11}

        self.smart_collapse_soft_ratio_rule_enabled = True
        self.smart_collapse_allow_comma_endings = False
        self.smart_collapse_allow_colon_triplet_endings = True
        self.smart_collapse_ellipsis_lowercase_rule = False
        self.smart_collapse_collapse_if_no_punctuation = True
        self.smart_collapse_soft_ratio_percent = 65
        self.hide_control_codes_check = _CheckStub(True)
        self.backup_check = _CheckStub(True)
        self.problem_char_limit_check = _CheckStub(True)
        self.problem_line_limit_check = _CheckStub(True)
        self.problem_control_mismatch_check = _CheckStub(False)
        self.problem_trailing_color_code_check = _CheckStub(False)
        self.problem_missing_translation_check = _CheckStub(True)
        self.problem_contains_japanese_check = _CheckStub(False)
        self.hide_non_meaningful_entries_check = _CheckStub(True)
        self.show_empty_files_check = _CheckStub(False)

    def _pagination_page_size(self) -> int:
        return 70


class ProjectSettingsSplitTests(unittest.TestCase):
    def test_collect_project_ui_settings_includes_only_project_keys(self) -> None:
        harness = _Harness()

        payload = cast(
            dict[str, Any],
            _call_editor_method("_collect_project_ui_settings", harness),
        )

        self.assertIn("editor_mode", payload)
        self.assertIn("apply_version", payload)
        self.assertIn("thin_width", payload)
        self.assertIn("variable_length_overrides", payload)
        self.assertNotIn("smart_collapse_soft_rule_enabled", payload)
        self.assertNotIn("problem_char_limit", payload)
        self.assertNotIn("hide_control_codes", payload)

    def test_collect_global_ui_settings_includes_only_global_keys(self) -> None:
        harness = _Harness()

        payload = cast(
            dict[str, Any],
            _call_editor_method("_collect_global_ui_settings", harness),
        )

        self.assertIn("smart_collapse_soft_rule_enabled", payload)
        self.assertIn("problem_missing_translation", payload)
        self.assertIn("pagination_page_size", payload)
        self.assertNotIn("editor_mode", payload)
        self.assertNotIn("apply_version", payload)
        self.assertNotIn("thin_width", payload)
        self.assertNotIn("infer_speaker", payload)

    def test_layout_defaults_are_engine_specific(self) -> None:
        harness = _Harness()

        self.assertEqual(
            _call_editor_method("_project_layout_defaults_for_engine", harness, "mz"),
            (47, 60, 4),
        )
        self.assertEqual(
            _call_editor_method("_project_layout_defaults_for_engine", harness, "mv"),
            (44, 56, 4),
        )
        self.assertEqual(
            _call_editor_method("_project_layout_defaults_for_engine", harness, "tyrano"),
            (64, 84, 4),
        )

    def test_subset_extractors_respect_split(self) -> None:
        harness = _Harness()
        mixed = {
            "editor_mode": "translator",
            "apply_version": "translated",
            "thin_width": 44,
            "smart_collapse_soft_rule_enabled": True,
            "problem_missing_translation": True,
        }

        project_subset = cast(
            dict[str, Any],
            _call_editor_method("_project_settings_subset_from_mapping", harness, mixed),
        )
        global_subset = cast(
            dict[str, Any],
            _call_editor_method("_global_settings_subset_from_mapping", harness, mixed),
        )

        self.assertIn("editor_mode", project_subset)
        self.assertIn("apply_version", project_subset)
        self.assertIn("thin_width", project_subset)
        self.assertNotIn("smart_collapse_soft_rule_enabled", project_subset)
        self.assertIn("smart_collapse_soft_rule_enabled", global_subset)
        self.assertIn("problem_missing_translation", global_subset)
        self.assertNotIn("editor_mode", global_subset)


if __name__ == "__main__":
    unittest.main()
