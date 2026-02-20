from __future__ import annotations

import os
import re
import unittest
from typing import Any, Callable, Optional, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dialogue_visual_editor.helpers.core.models import DialogueSegment
from dialogue_visual_editor.helpers.ui.ui_components import DialogueBlockWidget


def _segment(lines: list[str] | None = None) -> DialogueSegment:
    resolved = list(lines) if lines else ["hello"]
    return DialogueSegment(
        uid="Map001:0",
        context="Map001 > Event 1",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(resolved),
        original_lines=list(resolved),
        source_lines=list(resolved),
    )


def _widget(segment: DialogueSegment) -> DialogueBlockWidget:
    return DialogueBlockWidget(
        segment=segment,
        block_number=1,
        thin_width=34,
        wide_width=44,
        max_lines=4,
        infer_name_from_first_line=True,
        smart_collapse_allow_comma_endings=True,
        smart_collapse_allow_colon_triplet_endings=True,
        smart_collapse_ellipsis_lowercase_rule=True,
        smart_collapse_collapse_if_no_punctuation=False,
        smart_collapse_min_soft_ratio=0.5,
        hide_control_codes_when_unfocused=False,
        hidden_control_line_transform=None,
        hidden_control_colored_line_resolver=None,
        speaker_display_resolver=None,
        speaker_display_html_resolver=None,
        hint_display_html_resolver=None,
        color_code_resolver=None,
        variable_label_resolver=None,
        speaker_tint_color="#0284c7",
        translator_mode=False,
        highlight_control_mismatch=False,
        highlight_contains_japanese=False,
        actor_mode=False,
        name_index_kind="",
        name_index_label="Entry",
        allow_structural_actions=True,
        inferred_speaker_name_resolver=None,
        segment_prompt_type_resolver=None,
    )


def _widget_with_options(
    segment: DialogueSegment,
    *,
    translator_mode: bool,
    speaker_display_resolver: Optional[Callable[[str], str]],
    inferred_speaker_name_resolver: Optional[Callable[[DialogueSegment], str]],
    speaker_display_html_resolver: Optional[Callable[[str], str]] = None,
    segment_prompt_type_resolver: Optional[Callable[..., str]] = None,
    hidden_control_colored_line_resolver: Optional[
        Callable[[str], tuple[str, list[tuple[int, int, str, float]]]]
    ] = None,
    highlight_contains_japanese: bool = False,
) -> DialogueBlockWidget:
    return DialogueBlockWidget(
        segment=segment,
        block_number=1,
        thin_width=34,
        wide_width=44,
        max_lines=4,
        infer_name_from_first_line=True,
        smart_collapse_allow_comma_endings=True,
        smart_collapse_allow_colon_triplet_endings=True,
        smart_collapse_ellipsis_lowercase_rule=True,
        smart_collapse_collapse_if_no_punctuation=False,
        smart_collapse_min_soft_ratio=0.5,
        hide_control_codes_when_unfocused=False,
        hidden_control_line_transform=None,
        hidden_control_colored_line_resolver=hidden_control_colored_line_resolver,
        speaker_display_resolver=speaker_display_resolver,
        speaker_display_html_resolver=speaker_display_html_resolver,
        hint_display_html_resolver=None,
        color_code_resolver=None,
        variable_label_resolver=None,
        speaker_tint_color="#0284c7",
        translator_mode=translator_mode,
        highlight_control_mismatch=False,
        highlight_contains_japanese=highlight_contains_japanese,
        actor_mode=False,
        name_index_kind="",
        name_index_label="Entry",
        allow_structural_actions=True,
        inferred_speaker_name_resolver=inferred_speaker_name_resolver,
        segment_prompt_type_resolver=segment_prompt_type_resolver,
    )


class DialogueBlockWidgetLazyEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_editor_mount_and_unmount_toggle_preview(self) -> None:
        segment = _segment(["line one", "line two"])
        widget = _widget(segment)
        self.assertIsNone(widget.editor)
        self.assertFalse(widget._preview.isHidden())
        self.assertIn("line one", widget._preview.text())

        widget.set_editor_active(True)
        self.assertIsNotNone(widget.editor)
        self.assertTrue(widget._preview.isHidden())

        widget.set_editor_active(False)
        self.assertIsNone(widget.editor)
        self.assertFalse(widget._preview.isHidden())
        widget.deleteLater()

    def test_set_editor_lines_while_unmounted_updates_segment(self) -> None:
        segment = _segment(["before"])
        widget = _widget(segment)
        self.assertIsNone(widget.editor)

        widget._set_editor_lines(["after", "next"])

        self.assertEqual(segment.lines, ["after", "next"])
        self.assertIn("after", widget._preview.text())
        self.assertIn("next", widget._preview.text())
        widget.deleteLater()

    def test_editor_shows_width_limit_marker_tooltip(self) -> None:
        segment = _segment(["This is a test line."])
        widget = _widget(segment)
        widget.resize(1100, 260)
        widget.set_editor_active(True)
        self._app.processEvents()
        marker = widget._width_limit_marker
        self.assertIsNotNone(marker)
        assert marker is not None
        self.assertIn("Recommended width limit:", marker.toolTip())
        self.assertIn("chars", marker.toolTip())
        widget.deleteLater()

    def test_editor_width_expands_only_for_overflow_content(self) -> None:
        segment = _segment(["Short line"])
        widget = _widget(segment)
        widget.resize(1400, 260)
        widget.set_editor_active(True)
        self._app.processEvents()
        editor = widget.editor
        assert editor is not None
        base_width = editor.maximumWidth()

        long_line = "W" * 120
        widget._set_editor_lines([long_line])
        self._app.processEvents()
        expanded_width = editor.maximumWidth()
        self.assertGreater(expanded_width, base_width)

        widget._set_editor_lines(["Short again"])
        self._app.processEvents()
        shrunk_width = editor.maximumWidth()
        self.assertEqual(shrunk_width, base_width)
        widget.deleteLater()

    def test_raw_editor_applies_font_scale_for_brace_tokens(self) -> None:
        segment = _segment([r"\{BIG text"])
        widget = _widget(segment)
        widget.set_editor_active(True)
        self._app.processEvents()
        editor = widget.editor
        assert editor is not None
        widget._apply_overflow_highlighting()
        base_point_size = editor.font().pointSizeF()
        if base_point_size <= 0:
            fallback_point_size = editor.font().pointSize()
            base_point_size = float(fallback_point_size if fallback_point_size > 0 else 10)
        has_scaled_selection = False
        for selection in editor.extraSelections():
            selection_any = cast(Any, selection)
            point_size = selection_any.format.fontPointSize()
            if point_size > (base_point_size + 0.25):
                has_scaled_selection = True
                break
        self.assertTrue(has_scaled_selection)
        widget.deleteLater()

    def test_expand_width_accounts_for_shown_vs_hidden_control_codes(self) -> None:
        heavy_codes = (r"\C[2]" * 20) + "Hi"
        segment = _segment([heavy_codes])
        widget = _widget(segment)
        widget.resize(1400, 260)
        widget.set_editor_active(True)
        self._app.processEvents()

        raw_expand = widget._dynamic_expand_width_chars(widget._width_chars())
        self.assertGreater(raw_expand, 0)

        widget.set_hide_control_codes_when_unfocused(True)
        editor = widget.editor
        assert editor is not None
        editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self._app.processEvents()

        hidden_expand = widget._dynamic_expand_width_chars(widget._width_chars())
        self.assertLess(hidden_expand, raw_expand)
        widget.deleteLater()

    def test_unfocused_hidden_mode_uses_html_overlay_for_brace_scaling(self) -> None:
        segment = _segment([r"\{Big thought"])

        def render_html(value: str) -> str:
            if r"\{" in value:
                return '<span style="font-size: 16pt;">Big thought</span>'
            return value

        widget = _widget_with_options(
            segment,
            translator_mode=False,
            speaker_display_resolver=None,
            speaker_display_html_resolver=render_html,
            hidden_control_colored_line_resolver=None,
            inferred_speaker_name_resolver=None,
        )
        widget.set_editor_active(True)
        editor = widget.editor
        assert editor is not None
        editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        widget.set_hide_control_codes_when_unfocused(True)
        editor.clearFocus()
        widget._sync_control_code_visibility(force=True)
        self._app.processEvents()

        overlay = widget._source_hint_overlay
        self.assertIsNotNone(overlay)
        assert overlay is not None
        self.assertFalse(overlay.isHidden())
        self.assertIn("font-size", overlay.text())
        widget.deleteLater()

    def test_thought_block_has_title_and_meta_indicator(self) -> None:
        segment = _segment(["Inner thought"])
        segment.code101["parameters"][2] = 1

        def resolve_type(current: DialogueSegment, default_type: str = "dialogue") -> str:
            if default_type.strip().lower() != "dialogue":
                return default_type
            return "thought" if int(current.background) == 1 else default_type

        widget = _widget_with_options(
            segment,
            translator_mode=False,
            speaker_display_resolver=None,
            speaker_display_html_resolver=None,
            hidden_control_colored_line_resolver=None,
            inferred_speaker_name_resolver=None,
            segment_prompt_type_resolver=resolve_type,
        )

        self.assertTrue(widget.title_label.text().startswith("Thought 1"))
        self.assertIn("Type: Thought", widget.meta_label.text())
        widget.deleteLater()

    def test_translator_mode_inferred_speaker_uses_translation_map(self) -> None:
        segment = _segment(["Hero", "こんにちは"])
        segment.translation_lines = [""]

        def resolve_speaker(value: str) -> str:
            return "Aki" if value.strip() == "Hero" else ""

        def infer_speaker(_: DialogueSegment) -> str:
            return "Hero"

        widget = _widget_with_options(
            segment,
            translator_mode=True,
            speaker_display_resolver=resolve_speaker,
            speaker_display_html_resolver=None,
            hidden_control_colored_line_resolver=None,
            inferred_speaker_name_resolver=infer_speaker,
        )

        self.assertEqual(widget._speaker_display_name(), "Aki")
        self.assertEqual(widget._speaker_display_name_html(), "Aki")
        widget.deleteLater()

    def test_translator_mode_speaker_html_resolver_applies_to_translated_name(self) -> None:
        segment = _segment(["Hero", "こんにちは"])
        segment.translation_lines = [""]

        def resolve_speaker(value: str) -> str:
            return r"\C[2]Aki\C[0]" if value.strip() == "Hero" else ""

        def resolve_speaker_html(value: str) -> str:
            return f"HTML:{value}"

        def infer_speaker(_: DialogueSegment) -> str:
            return "Hero"

        widget = _widget_with_options(
            segment,
            translator_mode=True,
            speaker_display_resolver=resolve_speaker,
            speaker_display_html_resolver=resolve_speaker_html,
            hidden_control_colored_line_resolver=None,
            inferred_speaker_name_resolver=infer_speaker,
        )

        self.assertEqual(widget._speaker_display_name_html(), r"HTML:\C[2]Aki\C[0]")
        widget.deleteLater()

    def test_line1_inference_prefix_color_carries_into_visible_lines(self) -> None:
        segment = _segment([r"\C[2]Hero", "Line one", "Line two"])

        color_token_re = re.compile(r"\\[Cc]\[(\d+)\]")

        def colored_mask(value: str) -> tuple[str, list[tuple[int, int, str, float]]]:
            output: list[str] = []
            spans: list[tuple[int, int, str, float]] = []
            cursor = 0
            out_pos = 0
            active_color = ""
            for match in color_token_re.finditer(value):
                chunk = value[cursor:match.start()]
                if chunk:
                    output.append(chunk)
                    next_pos = out_pos + len(chunk)
                    spans.append((out_pos, next_pos, active_color, 1.0))
                    out_pos = next_pos
                color_code = int(match.group(1))
                active_color = "#22aa22" if color_code == 2 else ""
                cursor = match.end()
            tail = value[cursor:]
            if tail:
                output.append(tail)
                next_pos = out_pos + len(tail)
                spans.append((out_pos, next_pos, active_color, 1.0))
            return "".join(output), spans

        def infer_speaker(_: DialogueSegment) -> str:
            return "Hero"

        widget = _widget_with_options(
            segment,
            translator_mode=False,
            speaker_display_resolver=None,
            speaker_display_html_resolver=None,
            hidden_control_colored_line_resolver=colored_mask,
            inferred_speaker_name_resolver=infer_speaker,
        )

        masked_lines = widget._masked_lines_from_raw(["Line one", "Line two"])

        self.assertEqual(masked_lines, ["Line one", "Line two"])
        self.assertEqual(len(widget._masked_color_spans), 2)
        self.assertTrue(
            any(color == "#22aa22" for _s, _e, color, _scale in widget._masked_color_spans[0])
        )
        self.assertTrue(
            any(color == "#22aa22" for _s, _e, color, _scale in widget._masked_color_spans[1])
        )

        widget.set_editor_active(True)
        widget.set_hide_control_codes_when_unfocused(True)
        widget._apply_overflow_highlighting()
        self.assertIsNotNone(widget.editor)
        editor = widget.editor
        assert editor is not None
        selections = editor.extraSelections()
        colored = 0
        for selection in selections:
            selection_any = cast(Any, selection)
            color = selection_any.format.foreground().color()
            if color.isValid() and color.name().lower() == "#22aa22":
                colored += 1
        self.assertGreaterEqual(colored, 2)
        widget.deleteLater()

    def test_translator_mode_japanese_problem_updates_warning_text(self) -> None:
        segment = _segment(["Source only"])
        segment.translation_lines = ["Alpha あ Beta"]
        widget = _widget_with_options(
            segment,
            translator_mode=True,
            speaker_display_resolver=None,
            inferred_speaker_name_resolver=None,
            highlight_contains_japanese=True,
        )

        self.assertTrue(widget._has_japanese_text_problem())
        self.assertTrue(widget._has_warning)
        self.assertIn("contains Japanese", widget.status_label.text())
        widget.deleteLater()

    def test_translator_mode_japanese_problem_highlights_character(self) -> None:
        segment = _segment(["Source only"])
        segment.translation_lines = ["A\\C[2]xあB"]
        widget = _widget_with_options(
            segment,
            translator_mode=True,
            speaker_display_resolver=None,
            inferred_speaker_name_resolver=None,
            highlight_contains_japanese=True,
        )

        widget.set_editor_active(True)
        widget._apply_overflow_highlighting()
        self.assertIsNotNone(widget.editor)
        editor = widget.editor
        assert editor is not None
        selected_texts = [
            cast(Any, selection).cursor.selectedText()
            for selection in editor.extraSelections()
            if cast(Any, selection).cursor.selectedText()
        ]
        self.assertIn("あ", selected_texts)
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
