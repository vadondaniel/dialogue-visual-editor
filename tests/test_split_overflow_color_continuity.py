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


class _Spin:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _Check:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _StatusBar:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _ProjectionHarness(StructuralEditingMixin):
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.current_path: Path | None = None
        self.infer_speaker_check = _Check(False)
        self._translator_mode = False
        self.line_width = 60
        self.selected_segment_uid: str | None = None
        self._status_bar = _StatusBar()
        self._prompt_options: (
            tuple[bool, bool, bool, bool, float, bool, bool] | None
        ) = None

    def _is_translator_mode(self) -> bool:
        return self._translator_mode

    @staticmethod
    def _is_name_index_session(_session: FileSession) -> bool:
        return False

    @staticmethod
    def _segment_has_inferred_line1_speaker(_segment: DialogueSegment) -> bool:
        return False

    def _segment_line_width(self, segment: DialogueSegment) -> int:
        return self.line_width

    def _prompt_smart_collapse_all_options(
        self,
    ) -> tuple[bool, bool, bool, bool, float, bool, bool] | None:
        return self._prompt_options

    def statusBar(self) -> _StatusBar:
        return self._status_bar

    def _refresh_dirty_state(self, _session: FileSession) -> None:
        return None

    def _refresh_after_structure_change_without_full_rerender(
        self,
        _session: FileSession,
        *,
        focus_uid: str | None,
        preserve_scroll: bool,
    ) -> bool:
        return True

    def _render_session(
        self,
        _session: FileSession,
        *,
        focus_uid: str | None,
        preserve_scroll: bool,
    ) -> None:
        return None

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


class _SplitOverflowHarness(StructuralEditingMixin):
    def __init__(self) -> None:
        self.current_path: Path | None = Path("Map001.json")
        self.sessions: dict[Path, FileSession] = {}
        self.current_segment_lookup: dict[str, DialogueSegment] = {}
        self.infer_speaker_check = _Check(False)
        self.max_lines_spin = _Spin(3)
        self.structural_undo_stack: list[Any] = []
        self.structural_redo_stack: list[Any] = []
        self.segment_uid_counter = 0
        self.translation_uid_counter = 0
        self._status_bar = _StatusBar()

    @staticmethod
    def _is_translator_mode() -> bool:
        return True

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    @staticmethod
    def _segment_source_lines_for_display(segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    @staticmethod
    def _inferred_speaker_from_segment_line1(_segment: DialogueSegment) -> str:
        return ""

    @staticmethod
    def _speaker_key_for_segment(_segment: DialogueSegment) -> str:
        return "(none)"

    @staticmethod
    def _speaker_translation_for_key(_speaker_key: str) -> str:
        return ""

    def _new_translation_uid(self) -> str:
        self.translation_uid_counter += 1
        return f"TL:{self.translation_uid_counter}"

    @staticmethod
    def _refresh_dirty_state(_session: FileSession) -> None:
        return None

    def _refresh_after_structure_change_without_full_rerender(
        self,
        _session: FileSession,
        *,
        focus_uid: str | None,
        preserve_scroll: bool,
    ) -> bool:
        _ = (focus_uid, preserve_scroll)
        return True

    @staticmethod
    def _render_session(
        _session: FileSession,
        *,
        focus_uid: str | None,
        preserve_scroll: bool,
    ) -> None:
        _ = (focus_uid, preserve_scroll)
        return None

    def statusBar(self) -> _StatusBar:
        return self._status_bar


class SplitOverflowColorContinuityTests(unittest.TestCase):
    def test_translator_split_overflow_keeps_anchor_source_lines_unsplit(self) -> None:
        harness = _SplitOverflowHarness()
        source_lines = ["JP line 1", "JP line 2", "JP line 3", "JP line 4"]
        translation_lines = ["TL line 1", "TL line 2", "TL line 3", "TL line 4"]
        anchor = DialogueSegment(
            uid="Map001.json:L0:0",
            context="ctx",
            code101={},
            lines=list(source_lines),
            original_lines=list(source_lines),
            source_lines=list(source_lines),
            code401_template={},
            translation_lines=list(translation_lines),
            original_translation_lines=list(translation_lines),
            segment_kind="dialogue",
        )
        assert harness.current_path is not None
        session = FileSession(
            path=harness.current_path,
            data={},
            bundles=[],
            segments=[anchor],
        )
        harness.sessions[session.path] = session
        harness.current_segment_lookup = {anchor.uid: anchor}

        harness._on_split_overflow_requested(anchor.uid)

        self.assertEqual(len(session.segments), 2)
        kept = session.segments[0]
        moved = session.segments[1]
        self.assertEqual(kept.lines, source_lines)
        self.assertEqual(kept.source_lines, source_lines)
        self.assertTrue(moved.translation_only)
        self.assertEqual(moved.lines, [""])
        self.assertEqual(moved.source_lines, [""])
        self.assertEqual(
            kept.translation_lines + moved.translation_lines,
            translation_lines,
        )

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

    def test_projected_smart_collapse_count_can_filter_to_overflowing_blocks(self) -> None:
        harness = _ProjectionHarness()
        current_path = Path("Map001.json")
        harness.current_path = current_path
        harness.sessions[current_path] = FileSession(
            path=current_path,
            data=[],
            bundles=[],
            segments=[
                DialogueSegment(
                    uid="fits",
                    context="ctx",
                    code101={},
                    lines=["No punctuation", "here"],
                    original_lines=["No punctuation", "here"],
                    source_lines=["No punctuation", "here"],
                    segment_kind="dialogue",
                ),
                DialogueSegment(
                    uid="overflow",
                    context="ctx",
                    code101={},
                    lines=["This line is way too long", "next"],
                    original_lines=["This line is way too long", "next"],
                    source_lines=["This line is way too long", "next"],
                    segment_kind="dialogue",
                ),
            ],
        )

        all_blocks, all_files = harness._count_projected_smart_collapse_changes(
            allow_comma_endings=False,
            allow_colon_triplet_endings=False,
            ellipsis_lowercase_rule=False,
            collapse_if_no_punctuation=True,
            min_soft_ratio=0.5,
            apply_all_files=False,
            wide_width_limit=20,
            max_lines_limit=4,
            only_overflowing_blocks=False,
        )
        overflow_blocks, overflow_files = harness._count_projected_smart_collapse_changes(
            allow_comma_endings=False,
            allow_colon_triplet_endings=False,
            ellipsis_lowercase_rule=False,
            collapse_if_no_punctuation=True,
            min_soft_ratio=0.5,
            apply_all_files=False,
            wide_width_limit=20,
            max_lines_limit=4,
            only_overflowing_blocks=True,
        )

        self.assertEqual((all_blocks, all_files), (2, 1))
        self.assertEqual((overflow_blocks, overflow_files), (1, 1))

    def test_smart_collapse_all_can_only_apply_to_overflowing_blocks(self) -> None:
        harness = _ProjectionHarness()
        harness.line_width = 20
        current_path = Path("Map001.json")
        harness.current_path = current_path
        harness._prompt_options = (
            False,
            False,
            False,
            True,
            0.5,
            False,
            True,
        )
        harness.sessions[current_path] = FileSession(
            path=current_path,
            data=[],
            bundles=[],
            segments=[
                DialogueSegment(
                    uid="fits",
                    context="ctx",
                    code101={},
                    lines=["No punctuation", "here"],
                    original_lines=["No punctuation", "here"],
                    source_lines=["No punctuation", "here"],
                    segment_kind="dialogue",
                ),
                DialogueSegment(
                    uid="overflow",
                    context="ctx",
                    code101={},
                    lines=["This line is way too long", "next"],
                    original_lines=["This line is way too long", "next"],
                    source_lines=["This line is way too long", "next"],
                    segment_kind="dialogue",
                ),
            ],
        )

        harness._smart_collapse_all_dialogue_blocks()

        segments = harness.sessions[current_path].segments
        self.assertEqual(segments[0].lines, ["No punctuation", "here"])
        self.assertEqual(segments[0].source_lines, ["No punctuation", "here"])
        self.assertEqual(segments[1].lines, ["This line is way", "too long next"])
        self.assertEqual(segments[1].source_lines, ["This line is way", "too long next"])


if __name__ == "__main__":
    unittest.main()
