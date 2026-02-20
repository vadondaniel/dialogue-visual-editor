from __future__ import annotations

import unittest

from dialogue_visual_editor.helpers.mixins.presentation_mixins import (
    PresentationHelpersMixin,
)


class _Harness(PresentationHelpersMixin):
    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        return text

    def _color_for_rpgm_code(self, color_code: int) -> str:
        return "#22aa22" if int(color_code) == 2 else ""


class PresentationColorCodeHtmlTests(unittest.TestCase):
    def test_default_render_hides_style_tokens(self) -> None:
        harness = _Harness()

        rendered = harness._render_text_with_color_codes_html(r"\C[2]Hero\C[0]")

        self.assertIn("Hero", rendered)
        self.assertNotIn(r"\C[2]", rendered)
        self.assertNotIn(r"\C[0]", rendered)

    def test_visible_render_keeps_color_tokens(self) -> None:
        harness = _Harness()

        rendered = harness._render_text_with_visible_color_codes_html(
            r"\C[2]Hero\C[0]"
        )

        self.assertIn("Hero", rendered)
        self.assertIn(r"\C[2]", rendered)
        self.assertIn(r"\C[0]", rendered)
        self.assertIn("color: #22aa22;", rendered)


if __name__ == "__main__":
    unittest.main()
