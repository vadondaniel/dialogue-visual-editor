from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import (
    DialogueSegment,
    FileSession,
)
from dialogue_visual_editor.helpers.mixins.structural_editing_mixin import (
    StructuralEditingMixin,
)


class _StatusBarHarness:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _DummyWidget:
    def __init__(self, block_number: int = 1) -> None:
        self.block_number = block_number
        self.refresh_status_calls = 0

    def _refresh_status(self) -> None:
        self.refresh_status_calls += 1


class _StructuralResetHarness(StructuralEditingMixin):
    def __init__(
        self,
        *,
        translator_mode: bool,
        structure_refresh_result: bool = False,
        restore_merged_count: int = 0,
    ) -> None:
        self._translator_mode = translator_mode
        self._structure_refresh_result = structure_refresh_result
        self._restore_merged_count = restore_merged_count
        self._status_bar = _StatusBarHarness()

        self.current_path: Path | None = None
        self.selected_segment_uid: str | None = None
        self.sessions: dict[Path, FileSession] = {}
        self.current_segment_lookup: dict[str, DialogueSegment] = {}
        self.block_widgets: dict[str, _DummyWidget] = {}
        self.rendered_blocks_path: Path | None = None
        self.rendered_block_uid_order: list[str] = []
        self._pending_render_state: Any = None
        self.reference_summary_cache_by_path: dict[Path, dict[str, tuple[str, str]]] = {}
        self.current_reference_map: dict[str, tuple[str, str]] = {}
        self.speaker_translation_map: dict[str, str] = {}
        self.structural_undo_stack: list[Any] = []
        self.structural_redo_stack: list[Any] = []

        self.refresh_dirty_calls = 0
        self.sync_widget_calls = 0
        self.apply_visual_calls = 0
        self.refresh_detail_calls = 0
        self.build_reference_calls = 0
        self.structure_refresh_calls = 0
        self.render_calls = 0

    def _is_translator_mode(self) -> bool:
        return self._translator_mode

    def _is_name_index_session(self, _session: FileSession) -> bool:
        return False

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [line if isinstance(line, str) else str(line) for line in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    def _normalize_speaker_key(self, key: str) -> str:
        return key.strip().lower()

    def _name_index_label(self, _session: FileSession) -> str:
        return "Actor"

    def _sync_reused_block_widget(
        self,
        _widget: _DummyWidget,
        segment: DialogueSegment,
        block_number: int,
        name_index_label: str,
    ) -> None:
        _ = (segment, block_number, name_index_label)
        self.sync_widget_calls += 1

    def _apply_block_visual_state(self, uid: str, _widget: _DummyWidget) -> None:
        _ = uid
        self.apply_visual_calls += 1

    def _build_reference_summary_for_session(
        self, _session: FileSession
    ) -> dict[str, tuple[str, str]]:
        self.build_reference_calls += 1
        return {"ref": ("exact", "similar")}

    def _refresh_translator_detail_panel(self) -> None:
        self.refresh_detail_calls += 1

    def _refresh_dirty_state(self, _session: FileSession) -> None:
        self.refresh_dirty_calls += 1

    def _refresh_after_structure_change_without_full_rerender(
        self,
        session: FileSession,
        *,
        focus_uid: str | None = None,
        preserve_scroll: bool = True,
    ) -> bool:
        _ = (session, focus_uid, preserve_scroll)
        self.structure_refresh_calls += 1
        return self._structure_refresh_result

    def _render_session(
        self,
        _session: FileSession,
        *,
        focus_uid: str | None = None,
        preserve_scroll: bool = False,
    ) -> None:
        _ = (focus_uid, preserve_scroll)
        self.render_calls += 1

    def _restore_merged_segments_after(
        self,
        session: FileSession,
        anchor_uid: str,
        merged_segments: list[DialogueSegment],
    ) -> int:
        _ = (session, anchor_uid, merged_segments)
        return self._restore_merged_count

    def statusBar(self) -> _StatusBarHarness:
        return self._status_bar


class _UidGenerationHarness(StructuralEditingMixin):
    def __init__(self, session: FileSession, *, counter: int = 0) -> None:
        self.sessions: dict[Path, FileSession] = {session.path: session}
        self.segment_uid_counter = counter


def _dialogue_segment(uid: str, text: str, *, speaker: str = "") -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=[text],
        original_lines=[text],
        source_lines=[text],
        code401_template={"code": 401, "indent": 0, "parameters": [""]},
    )


class StructuralEditingResetFastPathTests(unittest.TestCase):
    def test_new_segment_uid_skips_existing_ids_in_target_session(self) -> None:
        path = Path("Map010.json")
        session = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[
                _dialogue_segment("Map010.json:I:1", "A"),
                _dialogue_segment("Map010.json:I:2", "B"),
            ],
        )
        harness = _UidGenerationHarness(session, counter=0)

        self.assertEqual(harness._new_segment_uid(path), "Map010.json:I:3")

    def test_new_segment_uid_skips_high_existing_id_after_reload(self) -> None:
        path = Path("Map010.json")
        session = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[
                _dialogue_segment("Map010.json:I:449", "A"),
            ],
        )
        harness = _UidGenerationHarness(session, counter=448)

        self.assertEqual(harness._new_segment_uid(path), "Map010.json:I:450")

    def test_translator_reset_uses_single_widget_fast_path(self) -> None:
        harness = _StructuralResetHarness(translator_mode=True)
        segment = _dialogue_segment("A:1", "jp line", speaker="Hero")
        segment.translation_lines = ["changed tl"]
        segment.original_translation_lines = ["original tl"]
        segment.translation_speaker = "Changed Speaker"
        segment.original_translation_speaker = "Original Speaker"
        session = FileSession(path=Path("A.json"), data={}, bundles=[], segments=[segment])
        harness.current_path = session.path
        harness.sessions[session.path] = session
        harness.current_segment_lookup = {segment.uid: segment}
        harness.block_widgets = {segment.uid: _DummyWidget()}
        harness.rendered_blocks_path = session.path
        harness.rendered_block_uid_order = [segment.uid]

        harness._on_reset_requested(segment.uid)

        self.assertEqual(segment.translation_lines, ["original tl"])
        self.assertEqual(segment.translation_speaker, "Original Speaker")
        self.assertEqual(harness.refresh_dirty_calls, 1)
        self.assertEqual(harness.sync_widget_calls, 1)
        self.assertEqual(harness.apply_visual_calls, 1)
        self.assertEqual(harness.refresh_detail_calls, 1)
        self.assertEqual(harness.build_reference_calls, 1)
        self.assertEqual(harness.structure_refresh_calls, 0)
        self.assertEqual(harness.render_calls, 0)
        self.assertEqual(
            harness.speaker_translation_map.get("hero"),
            "Original Speaker",
        )
        self.assertEqual(
            harness.statusBar().messages[-1],
            "Reset translation block.",
        )

    def test_source_reset_text_only_uses_single_widget_fast_path(self) -> None:
        harness = _StructuralResetHarness(translator_mode=False)
        segment = _dialogue_segment("A:1", "original source")
        segment.lines = ["changed source"]
        segment.source_lines = ["changed source"]
        segment.original_lines = ["original source"]
        session = FileSession(path=Path("A.json"), data={}, bundles=[], segments=[segment])
        harness.current_path = session.path
        harness.sessions[session.path] = session
        harness.current_segment_lookup = {segment.uid: segment}
        harness.block_widgets = {segment.uid: _DummyWidget()}
        harness.rendered_blocks_path = session.path
        harness.rendered_block_uid_order = [segment.uid]

        harness._on_reset_requested(segment.uid)

        self.assertEqual(segment.lines, ["original source"])
        self.assertEqual(segment.source_lines, ["original source"])
        self.assertEqual(harness.refresh_dirty_calls, 1)
        self.assertEqual(harness.sync_widget_calls, 1)
        self.assertEqual(harness.apply_visual_calls, 1)
        self.assertEqual(harness.structure_refresh_calls, 0)
        self.assertEqual(harness.render_calls, 0)
        self.assertEqual(len(harness.structural_undo_stack), 1)
        self.assertEqual(harness.statusBar().messages[-1], "Reset block.")

    def test_source_reset_with_merged_segments_falls_back_to_full_refresh(self) -> None:
        harness = _StructuralResetHarness(
            translator_mode=False,
            structure_refresh_result=False,
            restore_merged_count=1,
        )
        segment = _dialogue_segment("A:1", "original source")
        segment.lines = ["changed source"]
        segment.source_lines = ["changed source"]
        segment.original_lines = ["original source"]
        merged_segment = _dialogue_segment("A:2", "merged source")
        segment.merged_segments = [merged_segment]
        session = FileSession(path=Path("A.json"), data={}, bundles=[], segments=[segment])
        harness.current_path = session.path
        harness.sessions[session.path] = session
        harness.current_segment_lookup = {segment.uid: segment}
        harness.block_widgets = {segment.uid: _DummyWidget()}
        harness.rendered_blocks_path = session.path
        harness.rendered_block_uid_order = [segment.uid]

        harness._on_reset_requested(segment.uid)

        self.assertEqual(harness.sync_widget_calls, 0)
        self.assertEqual(harness.structure_refresh_calls, 1)
        self.assertEqual(harness.render_calls, 1)
        self.assertEqual(
            harness.statusBar().messages[-1],
            "Reset block and restored 1 merged block.",
        )

    def test_block_text_changed_refreshes_chain_widget_statuses_for_translator_mode(self) -> None:
        harness = _StructuralResetHarness(translator_mode=True)
        anchor = _dialogue_segment("A:1", "jp anchor")
        followup = _dialogue_segment("A:2", "")
        followup.translation_only = True
        session = FileSession(
            path=Path("A.json"),
            data={},
            bundles=[],
            segments=[anchor, followup],
        )
        harness.current_path = session.path
        harness.sessions[session.path] = session
        harness.current_segment_lookup = {
            anchor.uid: anchor,
            followup.uid: followup,
        }
        anchor_widget = _DummyWidget()
        followup_widget = _DummyWidget()
        harness.block_widgets = {
            anchor.uid: anchor_widget,
            followup.uid: followup_widget,
        }
        setattr(
            harness,
            "_logical_translation_chain_for_segment",
            lambda segment, session=None: [anchor, followup],
        )

        harness._on_block_text_changed(followup.uid, ["translated followup"])

        self.assertEqual(anchor_widget.refresh_status_calls, 1)
        self.assertEqual(followup_widget.refresh_status_calls, 1)

    def test_block_text_changed_refreshes_translator_panel_when_selected_uid_in_chain(self) -> None:
        harness = _StructuralResetHarness(translator_mode=True)
        anchor = _dialogue_segment("A:1", "jp anchor")
        followup = _dialogue_segment("A:2", "")
        followup.translation_only = True
        session = FileSession(
            path=Path("A.json"),
            data={},
            bundles=[],
            segments=[anchor, followup],
        )
        harness.current_path = session.path
        harness.selected_segment_uid = anchor.uid
        harness.sessions[session.path] = session
        harness.current_segment_lookup = {
            anchor.uid: anchor,
            followup.uid: followup,
        }
        harness.block_widgets = {
            anchor.uid: _DummyWidget(),
            followup.uid: _DummyWidget(),
        }
        setattr(
            harness,
            "_logical_translation_chain_for_segment",
            lambda segment, session=None: [anchor, followup],
        )

        harness._on_block_text_changed(followup.uid, ["translated followup"])

        self.assertEqual(harness.refresh_detail_calls, 1)


if __name__ == "__main__":
    unittest.main()
