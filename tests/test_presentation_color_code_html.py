from __future__ import annotations

import unittest

from helpers.mixins.presentation_mixins import (
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


class _VariableResolverHarness(_Harness):
    def _variable_label_for_rpgm_index(self, variable_id: int) -> str:
        if int(variable_id) == 5:
            return "system.variables[5]: Hero Name"
        return ""


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

    def test_render_applies_font_size_style_for_brace_tokens(self) -> None:
        harness = _Harness()

        rendered = harness._render_text_with_color_codes_html(r"\{BIG\} normal")

        self.assertIn("BIG", rendered)
        self.assertIn("normal", rendered)
        self.assertIn("font-size:", rendered)

    def test_hidden_control_spans_apply_font_scale_for_brace_tokens(self) -> None:
        harness = _Harness()

        masked, spans = harness._hidden_control_line_with_color_spans(r"\{BIG text")

        self.assertEqual(masked, "BIG text")
        self.assertTrue(spans)
        self.assertGreater(spans[0][3], 1.0)

    def test_hidden_control_spans_render_variable_token_with_extra_args(self) -> None:
        harness = _Harness()

        masked, _spans = harness._hidden_control_line_with_color_spans(
            r"\V[5,4] apples"
        )

        self.assertEqual(masked, "<V5> apples")

    def test_hidden_control_spans_keep_compact_placeholder_even_with_resolver(self) -> None:
        harness = _VariableResolverHarness()

        masked, _spans = harness._hidden_control_line_with_color_spans(
            r"\V[5,4] apples"
        )

        self.assertEqual(masked, "<V5> apples")

    def test_hidden_control_spans_strip_angle_speed_tokens(self) -> None:
        harness = _Harness()

        masked, _spans = harness._hidden_control_line_with_color_spans(
            r"Start\> fast \<slow end"
        )

        self.assertEqual(masked, "Start fast slow end")

    def test_visible_render_keeps_angle_speed_tokens(self) -> None:
        harness = _Harness()

        rendered = harness._render_text_with_visible_color_codes_html(
            r"Start\> fast \<slow end"
        )

        self.assertIn(r"\&gt;", rendered)
        self.assertIn(r"\&lt;", rendered)
        self.assertIn("Start", rendered)
        self.assertIn("end", rendered)


if __name__ == "__main__":
    unittest.main()
