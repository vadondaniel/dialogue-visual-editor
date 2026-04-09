from __future__ import annotations

import unittest
from typing import Any, cast

from app import DialogueVisualEditor


def _call_editor_method(name: str, self_obj: object, *args: Any) -> Any:
    method = cast(Any, getattr(DialogueVisualEditor, name))
    return method(self_obj, *args)


class _ToolsMenuHarness:
    def _open_speaker_manager(self) -> None:
        return None

    def _open_mass_translate_dialog(self) -> None:
        return None

    def _open_normalizations_dialog(self) -> None:
        return None

    def _open_audit_window(self) -> None:
        return None

    def _open_translation_settings_dialog(self) -> None:
        return None


class ToolsMenuConfigTests(unittest.TestCase):
    def test_tools_menu_action_order_and_shortcuts(self) -> None:
        harness = _ToolsMenuHarness()

        specs = _call_editor_method("_tools_menu_action_specs", harness)
        labels = [str(spec[0]) for spec in specs]
        shortcuts_by_label = {str(spec[0]): str(spec[1]) for spec in specs}

        self.assertEqual(
            labels,
            [
                "Speakers...",
                "Mass Translate...",
                "Normalizations...",
                "Audit...",
                "Translations...",
            ],
        )
        self.assertEqual(shortcuts_by_label["Speakers..."], "F1")
        self.assertEqual(shortcuts_by_label["Mass Translate..."], "F2")
        self.assertEqual(shortcuts_by_label["Normalizations..."], "F3")
        self.assertEqual(shortcuts_by_label["Audit..."], "F4")
        self.assertEqual(shortcuts_by_label["Translations..."], "F6")

    def test_pagination_buttons_show_all_pages_when_total_is_small(self) -> None:
        harness = _ToolsMenuHarness()

        tokens = _call_editor_method("_pagination_visible_page_buttons", harness, 6, 7)

        self.assertEqual(tokens, ["1", "2", "3", "4", "5", "6", "7"])

    def test_pagination_buttons_show_ellipsis_when_total_is_large(self) -> None:
        harness = _ToolsMenuHarness()

        tokens = _call_editor_method("_pagination_visible_page_buttons", harness, 8, 20)

        self.assertEqual(tokens, ["1", "...", "6", "7", "8", "9", "10", "...", "20"])


if __name__ == "__main__":
    unittest.main()
