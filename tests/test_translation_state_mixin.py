from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession, NO_SPEAKER_KEY
from dialogue_visual_editor.helpers.mixins.translation_state_mixin import (
    TranslationStateMixin,
)


def _segment(uid: str, text: str, speaker: str = "") -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=[text],
        original_lines=[text],
        source_lines=[text],
    )


class _ModeComboStub:
    def __init__(self, values: list[str], current_index: int) -> None:
        self._values = list(values)
        self._current_index = current_index
        self.set_index_calls: list[int] = []

    def currentData(self) -> str:
        return self._values[self._current_index]

    def findData(self, value: str) -> int:
        try:
            return self._values.index(value)
        except ValueError:
            return -1

    def setCurrentIndex(self, index: int) -> None:
        self.set_index_calls.append(index)
        self._current_index = index


class _TextControlStub:
    def __init__(self) -> None:
        self.values: list[str] = []

    def setText(self, value: str) -> None:
        self.values.append(value)


class _TooltipControlStub:
    def __init__(self) -> None:
        self.values: list[str] = []

    def setToolTip(self, value: str) -> None:
        self.values.append(value)


class _Harness(TranslationStateMixin):
    def __init__(self) -> None:
        self.translation_state: dict[str, Any] = {
            "version": 1,
            "uid_counter": 0,
            "speaker_map": {},
            "files": {},
        }
        self.active_translation_profile_id = "default"
        self.translation_profiles_meta: dict[str, dict[str, Any]] = {
            "default": {
                "name": "Default",
                "target_language_code": "en",
                "prompt_template": self._default_translation_prompt_template(),
            }
        }
        self.translation_state_path: Path | None = None
        self.speaker_translation_map: dict[str, str] = {}
        self.translation_uid_counter = 0
        self.sessions: dict[Path, FileSession] = {}
        self.bg1_means_thoughts = False

    def _relative_path(self, path: Path) -> str:
        return path.name

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        return segment.speaker_name

    def _segment_prompt_type(
        self,
        segment: DialogueSegment,
        default_type: str = "dialogue",
    ) -> str:
        if default_type.strip().lower() != "dialogue":
            return default_type
        if not self.bg1_means_thoughts:
            return default_type
        try:
            background = int(segment.background)
        except Exception:
            return default_type
        return "thought" if background == 1 else default_type

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        return (
            text.replace("\\N[1]", "Alice")
            .replace("\\n[1]", "Alice")
            .replace("\\N[2]", "Bob")
            .replace("\\n[2]", "Bob")
        )


class TranslationStateMixinTests(unittest.TestCase):
    def test_update_mode_controls_for_translator_mode(self) -> None:
        harness = _Harness()
        combo = _ModeComboStub(["translator", "editor"], 0)
        save_btn = _TextControlStub()
        save_all_btn = _TextControlStub()
        reset_btn = _TextControlStub()
        auto_split = _TooltipControlStub()
        harness.editor_mode_combo = cast(Any, combo)
        harness.save_btn = cast(Any, save_btn)
        harness.save_all_btn = cast(Any, save_all_btn)
        harness.reset_json_btn = cast(Any, reset_btn)
        harness.auto_split_check = cast(Any, auto_split)

        self.assertTrue(harness._is_translator_mode())
        harness._update_mode_controls()

        self.assertEqual(save_btn.values[-1], "Save")
        self.assertEqual(save_all_btn.values[-1], "Save All")
        self.assertEqual(reset_btn.values[-1], "Reset JSON")
        self.assertEqual(
            auto_split.values[-1],
            "Used when building translated snapshot data.",
        )
        self.assertEqual(getattr(harness, "_editor_mode_last_data", ""), "translator")

    def test_update_mode_controls_for_editor_mode(self) -> None:
        harness = _Harness()
        combo = _ModeComboStub(["translator", "editor"], 1)
        save_btn = _TextControlStub()
        save_all_btn = _TextControlStub()
        reset_btn = _TextControlStub()
        auto_split = _TooltipControlStub()
        harness.editor_mode_combo = cast(Any, combo)
        harness.save_btn = cast(Any, save_btn)
        harness.save_all_btn = cast(Any, save_all_btn)
        harness.reset_json_btn = cast(Any, reset_btn)
        harness.auto_split_check = cast(Any, auto_split)

        self.assertFalse(harness._is_translator_mode())
        harness._update_mode_controls()

        self.assertEqual(
            auto_split.values[-1],
            "Auto-split long dialogue on save.",
        )
        self.assertEqual(getattr(harness, "_editor_mode_last_data", ""), "editor")

    def test_on_editor_mode_changed_reverts_when_user_cancels_with_dirty_state(self) -> None:
        harness = _Harness()
        combo = _ModeComboStub(["translator", "editor"], 1)
        harness.editor_mode_combo = cast(Any, combo)
        harness.sessions = {
            Path("Map001.json"): FileSession(path=Path("Map001.json"), data=[], bundles=[], segments=[])
        }
        harness.sessions[Path("Map001.json")].dirty = True
        setattr(harness, "_editor_mode_last_data", "translator")

        with patch(
            "dialogue_visual_editor.helpers.mixins.translation_state_mixin.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.No,
        ) as warning_mock:
            harness._on_editor_mode_changed(1)

        warning_mock.assert_called_once()
        self.assertEqual(combo.set_index_calls, [0])
        self.assertFalse(bool(getattr(harness, "_editor_mode_reverting", False)))

    def test_on_editor_mode_changed_applies_callbacks_and_rerenders(self) -> None:
        harness = _Harness()
        combo = _ModeComboStub(["translator", "editor"], 1)
        save_btn = _TextControlStub()
        save_all_btn = _TextControlStub()
        reset_btn = _TextControlStub()
        auto_split = _TooltipControlStub()
        harness.editor_mode_combo = cast(Any, combo)
        harness.save_btn = cast(Any, save_btn)
        harness.save_all_btn = cast(Any, save_all_btn)
        harness.reset_json_btn = cast(Any, reset_btn)
        harness.auto_split_check = cast(Any, auto_split)
        harness.sessions = {
            Path("Map001.json"): FileSession(path=Path("Map001.json"), data=[], bundles=[], segments=[])
        }
        harness.sessions[Path("Map001.json")].dirty = True
        setattr(harness, "_editor_mode_last_data", "translator")
        call_order: list[str] = []
        harness._refresh_all_file_item_text = lambda: call_order.append("refresh")  # type: ignore[attr-defined]
        harness._sync_translator_mode_ui = lambda: call_order.append("sync")  # type: ignore[attr-defined]
        harness._update_window_title = lambda: call_order.append("title")  # type: ignore[attr-defined]
        harness._rerender_current_file = lambda: call_order.append("rerender")  # type: ignore[method-assign]

        with patch(
            "dialogue_visual_editor.helpers.mixins.translation_state_mixin.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Yes,
        ) as warning_mock:
            harness._on_editor_mode_changed(1)

        warning_mock.assert_called_once()
        self.assertEqual(call_order, ["refresh", "sync", "title", "rerender"])

    def test_on_editor_mode_changed_uses_current_mode_when_last_mode_invalid(self) -> None:
        harness = _Harness()
        combo = _ModeComboStub(["translator"], 0)
        save_btn = _TextControlStub()
        save_all_btn = _TextControlStub()
        reset_btn = _TextControlStub()
        auto_split = _TooltipControlStub()
        harness.editor_mode_combo = cast(Any, combo)
        harness.save_btn = cast(Any, save_btn)
        harness.save_all_btn = cast(Any, save_all_btn)
        harness.reset_json_btn = cast(Any, reset_btn)
        harness.auto_split_check = cast(Any, auto_split)
        harness.sessions = {}
        setattr(harness, "_editor_mode_last_data", 123)
        rerender_calls: list[int] = []
        harness._rerender_current_file = lambda: rerender_calls.append(1)  # type: ignore[method-assign]

        with patch(
            "dialogue_visual_editor.helpers.mixins.translation_state_mixin.QMessageBox.warning"
        ) as warning_mock:
            harness._on_editor_mode_changed(0)

        warning_mock.assert_not_called()
        self.assertEqual(rerender_calls, [1])

    def test_normalize_translation_lines_handles_list_str_none_and_other(self) -> None:
        harness = _Harness()
        self.assertEqual(harness._normalize_translation_lines(["a", None, 3]), ["a", "", "3"])
        self.assertEqual(harness._normalize_translation_lines("x\ny"), ["x", "y"])
        self.assertEqual(harness._normalize_translation_lines(123), [""])

    def test_legacy_tyrano_dialogue_source_text_for_hash_handles_prefix_shapes(self) -> None:
        segment = _segment("Map001.json:L0:0", "A")
        self.assertEqual(
            _Harness._legacy_tyrano_dialogue_source_text_for_hash(segment),
            "",
        )

        segment.segment_kind = "tyrano_dialogue"
        setattr(segment, "tyrano_line_prefixes", "invalid")
        self.assertEqual(
            _Harness._legacy_tyrano_dialogue_source_text_for_hash(segment),
            "",
        )

        setattr(segment, "tyrano_line_prefixes", ["", ""])
        self.assertEqual(
            _Harness._legacy_tyrano_dialogue_source_text_for_hash(segment),
            "",
        )

        cast(Any, segment).lines = ["A", None]
        setattr(segment, "tyrano_line_prefixes", ["[w]", 9])
        self.assertEqual(
            _Harness._legacy_tyrano_dialogue_source_text_for_hash(segment),
            "[w]A\n",
        )

    def test_set_profile_prompt_settings_normalizes_values(self) -> None:
        harness = _Harness()

        harness._set_translation_profile_prompt_settings(
            target_language_code=" EN-US ",
            prompt_template="   ",
            profile_id=" ALT ",
        )

        profile_state = harness._ensure_translation_profile("ALT")
        self.assertEqual(profile_state.get("target_language_code"), "en-us")
        self.assertEqual(
            profile_state.get("prompt_template"),
            harness._default_translation_prompt_template(),
        )
        self.assertEqual(
            harness._translation_profile_prompt_instructions("ALT"),
            harness._default_translation_prompt_template(),
        )

    def test_active_profile_files_state_initializes_files_dict(self) -> None:
        harness = _Harness()
        harness.active_translation_profile_id = "   "
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "custom",
            "profiles": {
                "custom": {
                    "name": "Custom",
                    "uid_counter": 0,
                    "target_language_code": "en",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": [],
                }
            },
        }

        files_state = harness._active_profile_files_state()

        self.assertEqual(harness.active_translation_profile_id, "custom")
        self.assertIsInstance(files_state, dict)
        self.assertEqual(files_state, {})

    def test_load_translation_state_returns_early_for_missing_path(self) -> None:
        harness = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            harness.translation_state_path = Path(tmpdir) / "missing_translation_state.json"
            harness._load_translation_state()

        self.assertEqual(harness.active_translation_profile_id, "default")
        self.assertEqual(harness.translation_uid_counter, 0)

    def test_load_translation_state_shows_warning_on_invalid_payload(self) -> None:
        harness = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "translation_state.json"
            state_path.write_text("{invalid json", encoding="utf-8")
            harness.translation_state_path = state_path

            with patch(
                "dialogue_visual_editor.helpers.mixins.translation_state_mixin.QMessageBox.warning"
            ) as warning_mock:
                harness._load_translation_state()

        warning_mock.assert_called_once()

    def test_load_translation_state_ignores_invalid_entry_shapes(self) -> None:
        harness = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "translation_state.json"
            payload = {
                "version": 2,
                "active_profile_id": "default",
                "profiles": {
                    "default": {
                        "name": "Default",
                        "uid_counter": 1,
                        "target_language_code": "en",
                        "prompt_template": harness._default_translation_prompt_template(),
                        "speaker_map": {"Hero": "Aki"},
                        "files": {
                            "Map001.json": {"entries": []},
                            "Map002.json": {
                                "entries": {
                                    "T0003": {"source_uid": "Map002.json:L0:0"},
                                    "Tbad": {"source_uid": "Map002.json:L0:1"},
                                }
                            },
                        },
                    }
                },
            }
            state_path.write_text(json.dumps(payload), encoding="utf-8")
            harness.translation_state_path = state_path
            harness._load_translation_state()

        self.assertEqual(harness.translation_uid_counter, 3)
        self.assertEqual(harness.speaker_translation_map.get("Hero"), "Aki")

    def test_save_translation_state_returns_true_without_path(self) -> None:
        harness = _Harness()
        harness.translation_state_path = None
        self.assertTrue(harness._save_translation_state())

    def test_save_translation_state_handles_write_failure(self) -> None:
        harness = _Harness()
        harness.translation_state_path = Path("translation_state.json")

        with patch.object(Path, "open", side_effect=OSError("disk full")):
            with patch(
                "dialogue_visual_editor.helpers.mixins.translation_state_mixin.QMessageBox.critical"
            ) as critical_mock:
                saved = harness._save_translation_state()

        self.assertFalse(saved)
        critical_mock.assert_called_once()

    def test_session_has_source_changes_detects_all_sources(self) -> None:
        harness = _Harness()
        segment = _segment("Map001.json:L0:0", "line")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[segment],
        )
        self.assertFalse(harness._session_has_source_changes(session))

        setattr(session, "_has_external_source_edits", True)
        self.assertTrue(harness._session_has_source_changes(session))
        setattr(session, "_has_external_source_edits", False)

        segment.inserted = True
        self.assertTrue(harness._session_has_source_changes(session))
        segment.inserted = False

        segment.merged_segments = [segment]
        self.assertTrue(harness._session_has_source_changes(session))
        segment.merged_segments = []

        segment.lines = ["changed"]
        segment.original_lines = ["original"]
        self.assertTrue(harness._session_has_source_changes(session))

    def test_session_has_translation_changes_detects_order_and_values(self) -> None:
        harness = _Harness()
        segment = _segment("Map001.json:L0:0", "line")
        segment.tl_uid = "T1"
        segment.translation_lines = ["TL"]
        segment.original_translation_lines = ["TL"]
        segment.translation_speaker = "Hero"
        segment.original_translation_speaker = "Hero"
        segment.disable_line1_speaker_inference = False
        segment.original_disable_line1_speaker_inference = False
        segment.force_line1_speaker_inference = False
        segment.original_force_line1_speaker_inference = False
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[segment],
        )

        setattr(session, "_original_tl_order", ["OTHER"])
        self.assertTrue(harness._session_has_translation_changes(session))

        setattr(session, "_original_tl_order", ["T1"])
        self.assertFalse(harness._session_has_translation_changes(session))

        segment.translation_lines = ["NEW"]
        self.assertTrue(harness._session_has_translation_changes(session))
        segment.translation_lines = ["TL"]

        segment.translation_speaker = "Mage"
        self.assertTrue(harness._session_has_translation_changes(session))
        segment.translation_speaker = "Hero"

        segment.disable_line1_speaker_inference = True
        self.assertTrue(harness._session_has_translation_changes(session))
        segment.disable_line1_speaker_inference = False

        segment.force_line1_speaker_inference = True
        self.assertTrue(harness._session_has_translation_changes(session))

    def test_mark_session_translation_saved_normalizes_and_clears_inserted_translation_only(self) -> None:
        harness = _Harness()
        base = _segment("Map001.json:L0:0", "line")
        base.tl_uid = "T1"
        cast(Any, base).translation_lines = "joined\ntext"
        base.translation_speaker = "  Hero  "
        base.disable_line1_speaker_inference = True
        base.force_line1_speaker_inference = False

        tl_only = _segment("Map001.json:TI:T2", "", "")
        tl_only.translation_only = True
        tl_only.inserted = True
        tl_only.tl_uid = "T2"
        tl_only.translation_lines = ["TL only"]

        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[base, tl_only],
        )

        harness._mark_session_translation_saved(session)

        self.assertEqual(base.translation_lines, ["joined", "text"])
        self.assertEqual(base.original_translation_lines, ["joined", "text"])
        self.assertEqual(base.translation_speaker, "Hero")
        self.assertEqual(base.original_translation_speaker, "Hero")
        self.assertFalse(tl_only.inserted)
        self.assertEqual(getattr(session, "_original_tl_order", []), ["T1", "T2"])

    def test_exact_reference_candidates_prefers_cross_file_rows(self) -> None:
        harness = _Harness()
        own_source = "same"
        own_path = Path("Map001.json")
        own_uid = "Map001.json:L0:0"
        exact_groups = {
            own_source: [
                {"path": own_path, "uid": own_uid},
                {"path": own_path, "uid": "Map001.json:L0:1"},
                {"path": Path("Map002.json"), "uid": "Map002.json:L0:0"},
            ]
        }

        rows, cross = harness._exact_reference_candidates(
            own_source=own_source,
            own_path=own_path,
            own_uid=own_uid,
            exact_groups=exact_groups,
        )
        self.assertTrue(cross)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], Path("Map002.json"))

        no_cross_rows, no_cross = harness._exact_reference_candidates(
            own_source=own_source,
            own_path=own_path,
            own_uid=own_uid,
            exact_groups={own_source: [{"path": own_path, "uid": "Map001.json:L0:1"}]},
        )
        self.assertFalse(no_cross)
        self.assertEqual(len(no_cross_rows), 1)

    def test_build_exact_reference_summary_handles_empty_variants_and_counts(self) -> None:
        harness = _Harness()
        own_source = "JP"
        own_path = Path("Map001.json")
        own_uid = "Map001.json:L0:0"

        none_summary = harness._build_exact_reference_summary(
            own_source=own_source,
            own_path=own_path,
            own_uid=own_uid,
            exact_groups={},
        )
        self.assertIn("Exact JA matches: none.", none_summary)

        unfilled_summary = harness._build_exact_reference_summary(
            own_source=own_source,
            own_path=own_path,
            own_uid=own_uid,
            exact_groups={
                own_source: [
                    {
                        "path": Path("Map002.json"),
                        "uid": "Map002.json:L0:1",
                        "file": "Map002.json",
                        "block_number": 2,
                        "translation_text": "",
                    }
                ]
            },
        )
        self.assertIn("No EN translations in matches yet.", unfilled_summary)

        filled_summary = harness._build_exact_reference_summary(
            own_source=own_source,
            own_path=own_path,
            own_uid=own_uid,
            exact_groups={
                own_source: [
                    {
                        "path": Path("Map002.json"),
                        "uid": "Map002.json:L0:1",
                        "file": "Map002.json",
                        "block_number": 2,
                        "translation_text": "Hello",
                    },
                    {
                        "path": Path("Map003.json"),
                        "uid": "Map003.json:L0:1",
                        "file": "Map003.json",
                        "block_number": 5,
                        "translation_text": "Hello",
                    },
                    {
                        "path": Path("Map004.json"),
                        "uid": "Map004.json:L0:1",
                        "file": "Map004.json",
                        "block_number": 7,
                        "translation_text": "Hi",
                    },
                    {
                        "path": Path("Map005.json"),
                        "uid": "Map005.json:L0:1",
                        "file": "Map005.json",
                        "block_number": 8,
                        "translation_text": "",
                    },
                ]
            },
        )
        self.assertIn("Filled EN: 3/4.", filled_summary)
        self.assertIn("2 variants.", filled_summary)
        self.assertIn("Empty EN: 1 entry.", filled_summary)

    def test_other_profile_translation_rows_uses_hash_fallback_and_skips_same_text(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:0", "JP")
        current.translation_lines = ["Current TL"]
        source_hash = harness._segment_source_hash(current)
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )
        harness.active_translation_profile_id = "jp"
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "jp",
            "profiles": {
                "jp": {
                    "name": "Japanese",
                    "uid_counter": 0,
                    "target_language_code": "ja",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {},
                },
                "en": {
                    "name": "English",
                    "uid_counter": 1,
                    "target_language_code": "en",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {
                        "Map001.json": {
                            "entries": {
                                "T_en": {
                                    "source_uid": "Map001.json:L0:9",
                                    "source_hash": source_hash,
                                    "translation_lines": ["Hello"],
                                }
                            }
                        }
                    },
                },
            },
        }

        rows = harness._other_profile_translation_rows_for_segment(session, current)
        self.assertEqual(rows, [("en", "English", "Hello")])

        current.translation_lines = ["Hello"]
        same_rows = harness._other_profile_translation_rows_for_segment(session, current)
        self.assertEqual(same_rows, [])

    def test_translation_state_for_session_includes_translation_only_payload_fields(self) -> None:
        harness = _Harness()
        segment = _segment("Map001.json:TI:T1", "", "")
        segment.translation_only = True
        segment.tl_uid = "T1"
        segment.translation_lines = ["Inserted TL"]
        segment.source_lines = ["Inserted source"]
        segment.original_lines = ["Inserted source"]
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[segment],
        )

        state = harness._translation_state_for_session(session)
        entry = state["entries"]["T1"]
        self.assertEqual(entry["segment_uid"], segment.uid)
        self.assertEqual(entry["context"], segment.context)
        self.assertIn("code101", entry)
        self.assertIn("code401_template", entry)
        self.assertEqual(entry["source_lines"], ["Inserted source"])
        self.assertEqual(entry["original_lines"], ["Inserted source"])

    def test_reference_summary_collapses_translation_only_followups_into_anchor_match(self) -> None:
        harness = _Harness()
        session_a_path = Path("Map001.json")
        session_b_path = Path("Map002.json")

        a_anchor = _segment("Map001.json:L0:0", "同一文")
        a_followup = _segment("Map001.json:TI:T0001", "")
        a_followup.translation_only = True
        a_followup.source_lines = ["同一文"]
        a_followup.original_lines = ["同一文"]

        b_anchor = _segment("Map002.json:L0:0", "同一文")
        b_followup = _segment("Map002.json:TI:T0002", "")
        b_followup.translation_only = True
        b_followup.source_lines = ["同一文"]
        b_followup.original_lines = ["同一文"]

        session_a = FileSession(
            path=session_a_path,
            data=[],
            bundles=[],
            segments=[a_anchor, a_followup],
        )
        session_b = FileSession(
            path=session_b_path,
            data=[],
            bundles=[],
            segments=[b_anchor, b_followup],
        )
        harness.sessions = {
            session_a_path: session_a,
            session_b_path: session_b,
        }

        summary_map = harness._build_reference_summary_for_session(session_a)
        anchor_exact, _anchor_similar = summary_map[a_anchor.uid]
        followup_exact, _followup_similar = summary_map[a_followup.uid]

        self.assertIn("1 block", anchor_exact)
        self.assertEqual(anchor_exact, followup_exact)

    def test_build_human_translation_reference_prompt_marks_thoughts(self) -> None:
        harness = _Harness()
        harness.bg1_means_thoughts = True
        thought_segment = _segment("Map001.json:L0:1", "Inner thought", "Hero")
        thought_segment.code101["parameters"][2] = 1
        normal_segment = _segment("Map001.json:L0:2", "Spoken line", "Hero")
        normal_segment.code101["parameters"][2] = 0
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[thought_segment, normal_segment],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            thought_segment,
            1,
        )

        self.assertIn("Hero: (Inner thought)", prompt)
        self.assertIn('Hero: "Spoken line"', prompt)
        self.assertNotIn("[THOUGHT]", prompt)

    def test_build_human_translation_reference_prompt_resolves_name_tokens(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:1", "\\N[1] says hi", "\\N[2]")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            current,
            0,
        )

        self.assertIn('Bob: "Alice says hi"', prompt)
        self.assertNotIn("\\N[1]", prompt)
        self.assertNotIn("\\N[2]", prompt)

    def test_build_human_translation_reference_prompt_includes_neighbors(self) -> None:
        harness = _Harness()
        before_segment = _segment("Map001.json:L0:0", "Before line", "Hero")
        before_segment.translation_speaker = "Hero EN"
        current = _segment("Map001.json:L0:1", "Current line", "Mage")
        current.translation_speaker = "Mage EN"
        current.translation_lines = ["Existing TL"]
        after_segment = _segment("Map001.json:L0:2", "After line", "Villain")
        after_segment.translation_speaker = "Villain EN"
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[before_segment, current, after_segment],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            current,
            1,
        )

        self.assertIn(
            "Translate the following dialogue from JA to EN.",
            prompt,
        )
        self.assertIn(
            "Write natural, fluent game dialogue.",
            prompt,
        )
        self.assertIn("Preserve intent, tone, and character voice.", prompt)
        self.assertIn("Transcript:", prompt)
        self.assertNotIn("context", prompt.lower())
        self.assertNotIn("selected line", prompt.lower())
        self.assertNotIn("chunk", prompt.lower())
        self.assertNotIn("same number of lines", prompt.lower())
        self.assertNotIn("same `{speaker}", prompt.lower())
        self.assertIn('Hero EN: "Before line"', prompt)
        self.assertIn('Mage EN: "Current line"', prompt)
        self.assertIn('Villain EN: "After line"', prompt)

    def test_build_human_translation_reference_prompt_zero_neighbors(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:1", "Current line", "Mage")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            current,
            0,
        )

        self.assertIn('Mage: "Current line"', prompt)
        self.assertNotIn("[CURRENT]", prompt)

    def test_build_human_translation_reference_prompt_uses_anchor_for_translation_only_selection(self) -> None:
        harness = _Harness()
        anchor = _segment("Map001.json:L0:1", "Anchor line", "Mage")
        followup = _segment("Map001.json:TI:T0001", "", "")
        followup.translation_only = True
        followup.source_lines = [""]
        followup.original_lines = [""]
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[anchor, followup],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            followup,
            0,
        )

        self.assertIn('Mage: "Anchor line"', prompt)
        self.assertNotIn('(empty)', prompt)

    def test_build_human_translation_reference_prompt_collapses_followups_in_neighbors(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:1", "Current line", "Mage")
        split_followup = _segment("Map001.json:TI:T0001", "", "")
        split_followup.translation_only = True
        split_followup.source_lines = ["SPLIT FOLLOWUP SHOULD NOT APPEAR"]
        split_followup.original_lines = ["SPLIT FOLLOWUP SHOULD NOT APPEAR"]
        next_segment = _segment("Map001.json:L0:2", "Next line", "Villain")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current, split_followup, next_segment],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            current,
            1,
        )

        self.assertIn('Mage: "Current line"', prompt)
        self.assertIn('Villain: "Next line"', prompt)
        self.assertNotIn("SPLIT FOLLOWUP SHOULD NOT APPEAR", prompt)

    def test_build_human_translation_reference_prompt_returns_empty_for_missing_segment(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:1", "Current line", "Mage")
        missing = _segment("Map001.json:L0:999", "Missing", "Ghost")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )

        prompt = harness._build_human_translation_reference_prompt(
            session,
            missing,
            2,
        )

        self.assertEqual(prompt, "")

    def test_other_profile_translations_include_other_profiles_for_same_segment(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:0", "JP line")
        current.translation_lines = ["Szia"]
        source_hash = harness._segment_source_hash(current)
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current],
        )
        harness.sessions = {session.path: session}
        harness.active_translation_profile_id = "hu"
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "hu",
            "profiles": {
                "hu": {
                    "name": "Hungarian",
                    "uid_counter": 1,
                    "target_language_code": "hu",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {
                        "Map001.json": {
                            "order": ["T_hu"],
                            "entries": {
                                "T_hu": {
                                    "source_uid": current.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Szia"],
                                }
                            },
                        }
                    },
                },
                "en": {
                    "name": "English",
                    "uid_counter": 1,
                    "target_language_code": "en",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {
                        "Map001.json": {
                            "order": ["T_en"],
                            "entries": {
                                "T_en": {
                                    "source_uid": current.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Hello"],
                                }
                            },
                        }
                    },
                },
            },
        }

        rows = harness._other_profile_translation_rows_for_segment(
            session,
            current,
        )

        self.assertEqual(rows, [("en", "English", "Hello")])

    def test_other_profile_translations_include_other_profiles_for_non_dialogue(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:M:1:displayName", "JP map name")
        current.segment_kind = "map_display_name"
        current.translation_lines = ["HU map name"]
        source_hash = harness._segment_source_hash(current)
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[current],
        )
        harness.sessions = {session.path: session}
        harness.active_translation_profile_id = "hu"
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "hu",
            "profiles": {
                "hu": {
                    "name": "Hungarian",
                    "uid_counter": 1,
                    "target_language_code": "hu",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {"Map001.json": {"order": [], "entries": {}}},
                },
                "en": {
                    "name": "English",
                    "uid_counter": 1,
                    "target_language_code": "en",
                    "prompt_template": harness._default_translation_prompt_template(),
                    "speaker_map": {},
                    "files": {
                        "Map001.json": {
                            "order": ["T_en_map"],
                            "entries": {
                                "T_en_map": {
                                    "source_uid": current.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["EN map name"],
                                }
                            },
                        }
                    },
                },
            },
        }

        rows = harness._other_profile_translation_rows_for_segment(
            session,
            current,
        )

        self.assertEqual(rows, [("en", "English", "EN map name")])

    def test_other_profile_translations_ignore_same_profile_matches(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:0", "JP line")
        current.translation_lines = ["Current TL"]
        same_source_other = _segment("Map001.json:L0:1", "JP line")
        same_source_other.translation_lines = ["Alt TL A"]

        session_current = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current, same_source_other],
        )
        harness.sessions = {
            session_current.path: session_current,
        }

        rows = harness._other_profile_translation_rows_for_segment(
            session_current,
            current,
        )

        self.assertEqual(rows, [])

    def test_other_profile_translations_none_when_no_alternatives(self) -> None:
        harness = _Harness()
        current = _segment("Map001.json:L0:0", "JP line")
        current.translation_lines = ["Same TL"]
        same_translation = _segment("Map001.json:L0:1", "JP line")
        same_translation.translation_lines = ["Same TL"]

        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[current, same_translation],
        )
        harness.sessions = {session.path: session}

        rows = harness._other_profile_translation_rows_for_segment(
            session,
            current,
        )

        self.assertEqual(rows, [])

    def test_apply_state_script_message_legacy_hash_still_matches(self) -> None:
        harness = _Harness()
        segment = _segment("Map010.json:L0:0", "JP line", "Narrator")
        segment.segment_kind = "script_message"
        segment.code101["parameters"] = ["face", 0, 0, 2, "Narrator"]
        session = FileSession(
            path=Path("Map010.json"),
            data=[],
            bundles=[],
            segments=[segment],
        )
        legacy_payload = "\n".join(
            [
                segment.segment_kind,
                segment.context,
                str(segment.background),
                str(segment.position),
                "",
                "0",
                segment.speaker_name,
                "\n".join(segment.lines),
            ]
        )
        legacy_hash = hashlib.sha1(legacy_payload.encode("utf-8")).hexdigest()
        harness.translation_state["files"] = {
            "Map010.json": {
                "order": ["T_legacy"],
                "entries": {
                    "T_legacy": {
                        "source_uid": segment.uid,
                        "source_hash": legacy_hash,
                        "translation_lines": ["TL line"],
                    }
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["TL line"])
        self.assertEqual(session.segments[0].tl_uid, "T_legacy")

    def test_apply_state_tyrano_dialogue_legacy_indented_hash_still_matches(self) -> None:
        harness = _Harness()
        segment = _segment("scene.ks:K:1", "You are not done yet?", "Narrator")
        segment.segment_kind = "tyrano_dialogue"
        setattr(segment, "tyrano_line_prefixes", ("    ",))
        session = FileSession(
            path=Path("scene.ks"),
            data=[],
            bundles=[],
            segments=[segment],
        )
        legacy_payload = "\n".join(
            [
                segment.segment_kind,
                segment.context,
                str(segment.background),
                str(segment.position),
                segment.face_name,
                str(segment.face_index),
                segment.speaker_name,
                "    You are not done yet?",
            ]
        )
        legacy_hash = hashlib.sha1(legacy_payload.encode("utf-8")).hexdigest()
        harness.translation_state["files"] = {
            "scene.ks": {
                "order": ["T_tyrano_legacy"],
                "entries": {
                    "T_tyrano_legacy": {
                        "source_uid": segment.uid,
                        "source_hash": legacy_hash,
                        "translation_lines": ["TL line"],
                    }
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["TL line"])
        self.assertEqual(session.segments[0].tl_uid, "T_tyrano_legacy")

    def test_apply_state_name_index_prefers_source_uid_mapping(self) -> None:
        harness = _Harness()
        seg_a = _segment("States.json:S:1:message1", "JP A")
        seg_b = _segment("States.json:S:1:message2", "JP B")
        session = FileSession(
            path=Path("States.json"),
            data=[],
            bundles=[],
            segments=[seg_a, seg_b],
        )
        setattr(session, "is_name_index_session", True)

        harness.translation_state["files"] = {
            "States.json": {
                "order": ["T_B", "T_A"],
                "entries": {
                    "T_A": {
                        "source_uid": "States.json:S:1:message1",
                        "source_hash": "old-a",
                        "translation_lines": ["TL A"],
                    },
                    "T_B": {
                        "source_uid": "States.json:S:1:message2",
                        "source_hash": "old-b",
                        "translation_lines": ["TL B"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["TL A"])
        self.assertEqual(session.segments[1].translation_lines, ["TL B"])
        self.assertEqual(session.segments[0].translation_speaker, "")
        self.assertEqual(session.segments[1].translation_speaker, "")
        self.assertEqual([seg.uid for seg in session.segments], [seg_a.uid, seg_b.uid])

    def test_apply_state_dialogue_falls_back_to_source_uid_when_hash_mismatches(self) -> None:
        harness = _Harness()
        session_segment = _segment("scene.ks:K:1", "EN source", "Hero")
        session = FileSession(
            path=Path("scene.ks"),
            data=[],
            bundles=[],
            segments=[session_segment],
        )
        legacy_segment = _segment("scene.ks:K:1", "JP source", "Hero")
        legacy_hash = harness._segment_source_hash(legacy_segment)
        harness.translation_state["files"] = {
            "scene.ks": {
                "order": ["T_uid_fallback"],
                "entries": {
                    "T_uid_fallback": {
                        "source_uid": "scene.ks:K:1",
                        "source_hash": legacy_hash,
                        "translation_lines": ["TL line"],
                    }
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].tl_uid, "T_uid_fallback")
        self.assertEqual(session.segments[0].translation_lines, ["TL line"])

    def test_apply_state_legacy_list_direct_uid_match_uses_source_preview_not_translation_text(self) -> None:
        harness = _Harness()
        session_segment = _segment(
            "CommonEvents.json:L2:0",
            "\\C[2]\\N[1]\\C[0]\n\\{なっ、なんだこの身体！？",
            "",
        )
        session = FileSession(
            path=Path("CommonEvents.json"),
            data=[],
            bundles=[],
            segments=[session_segment],
        )
        harness.translation_state["files"] = {
            "CommonEvents.json": {
                "order": ["T_src_preview"],
                "entries": {
                    "T_src_preview": {
                        "source_uid": "CommonEvents.json:L2:0",
                        "source_hash": "legacy-mismatch",
                        "source_preview": "\\\\C[2]\\\\N[1]\\\\C[0]\\\\n\\\\{なっ、なんだこの身体！？",
                        "translation_lines": ["\\C[2]\\N[1]\\C[0]", "\\{W-What is this body!?"],
                    }
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].tl_uid, "T_src_preview")
        self.assertEqual(
            session.segments[0].translation_lines,
            ["\\C[2]\\N[1]\\C[0]", "\\{W-What is this body!?"],
        )

    def test_apply_state_recovers_shifted_legacy_list_uid_entries_by_text_similarity(self) -> None:
        harness = _Harness()
        session_segments = [
            _segment("Map005.json:L46:0", "EN block A", "Hero"),
            _segment("Map005.json:L46:1", "EN inserted block", "Hero"),
            _segment("Map005.json:L46:2", "EN block C", "Hero"),
            _segment("Map005.json:L46:3", "EN block D", "Hero"),
        ]
        session = FileSession(
            path=Path("Map005.json"),
            data=[],
            bundles=[],
            segments=session_segments,
        )

        legacy_a = _segment("Map005.json:L46:0", "JP old A", "Hero")
        legacy_b = _segment("Map005.json:L46:1", "JP old B", "Hero")
        legacy_c = _segment("Map005.json:L46:2", "JP old C", "Hero")
        hash_a = harness._segment_source_hash(legacy_a)
        hash_b = harness._segment_source_hash(legacy_b)
        hash_c = harness._segment_source_hash(legacy_c)

        harness.translation_state["files"] = {
            "Map005.json": {
                "order": ["T0", "T1", "T2"],
                "entries": {
                    "T0": {
                        "source_uid": "Map005.json:L46:0",
                        "source_hash": hash_a,
                        "source_preview": "EN block A",
                        "translation_lines": ["EN block A"],
                    },
                    "T1": {
                        "source_uid": "Map005.json:L46:1",
                        "source_hash": hash_b,
                        "source_preview": "EN block C",
                        "translation_lines": ["EN block C"],
                    },
                    "T2": {
                        "source_uid": "Map005.json:L46:2",
                        "source_hash": hash_c,
                        "source_preview": "EN block D",
                        "translation_lines": ["EN block D"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].tl_uid, "T0")
        self.assertEqual(session.segments[0].translation_lines, ["EN block A"])
        self.assertEqual(session.segments[2].tl_uid, "T1")
        self.assertEqual(session.segments[2].translation_lines, ["EN block C"])
        self.assertEqual(session.segments[3].tl_uid, "T2")
        self.assertEqual(session.segments[3].translation_lines, ["EN block D"])
        self.assertNotIn(session.segments[1].tl_uid, {"T0", "T1", "T2"})
        self.assertEqual(session.segments[1].translation_lines, [""])

    def test_apply_state_inserts_translation_only_segments_in_saved_order(self) -> None:
        harness = _Harness()
        seg_1 = _segment("Map001.json:L0:0", "JP 1", "Hero")
        seg_2 = _segment("Map001.json:L0:1", "JP 2", "Hero")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[seg_1, seg_2],
        )
        hash_1 = harness._segment_source_hash(seg_1)
        hash_2 = harness._segment_source_hash(seg_2)
        harness.translation_state["files"] = {
            "Map001.json": {
                "order": ["T1", "T_INSERT", "T2"],
                "entries": {
                    "T1": {
                        "source_uid": seg_1.uid,
                        "source_hash": hash_1,
                        "translation_lines": ["TL 1"],
                    },
                    "T_INSERT": {
                        "source_uid": "",
                        "source_hash": "",
                        "translation_only": True,
                        "translation_lines": ["TL insert"],
                        "source_lines": [""],
                        "original_lines": [""],
                    },
                    "T2": {
                        "source_uid": seg_2.uid,
                        "source_hash": hash_2,
                        "translation_lines": ["TL 2"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(len(session.segments), 3)
        self.assertFalse(session.segments[0].translation_only)
        self.assertTrue(session.segments[1].translation_only)
        self.assertFalse(session.segments[2].translation_only)
        self.assertEqual(session.segments[1].translation_lines, ["TL insert"])
        original_order = getattr(session, "_original_tl_order", [])
        self.assertEqual(len(original_order), 3)

    def test_apply_state_reassigns_duplicate_translation_only_segment_uid(self) -> None:
        harness = _Harness()
        seg_1 = _segment("Map010.json:L0:0", "JP 1", "Hero")
        seg_2 = _segment("Map010.json:L0:1", "JP 2", "Hero")
        session = FileSession(
            path=Path("Map010.json"),
            data=[],
            bundles=[],
            segments=[seg_1, seg_2],
        )
        hash_1 = harness._segment_source_hash(seg_1)
        hash_2 = harness._segment_source_hash(seg_2)
        harness.translation_state["files"] = {
            "Map010.json": {
                "order": ["T1", "T_INSERT", "T2"],
                "entries": {
                    "T1": {
                        "source_uid": seg_1.uid,
                        "source_hash": hash_1,
                        "translation_lines": ["TL 1"],
                    },
                    "T_INSERT": {
                        "source_uid": "",
                        "source_hash": "",
                        "translation_only": True,
                        "segment_uid": seg_1.uid,
                        "translation_lines": ["TL insert"],
                        "source_lines": [""],
                        "original_lines": [""],
                    },
                    "T2": {
                        "source_uid": seg_2.uid,
                        "source_hash": hash_2,
                        "translation_lines": ["TL 2"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        resulting_uids = [segment.uid for segment in session.segments]
        self.assertEqual(len(resulting_uids), len(set(resulting_uids)))
        inserted_segment = next(
            segment for segment in session.segments if segment.translation_only
        )
        self.assertNotEqual(inserted_segment.uid, seg_1.uid)
        self.assertTrue(inserted_segment.uid.startswith("Map010.json:TI:"))

    def test_apply_state_keeps_source_order_when_saved_order_lacks_new_middle_segment(self) -> None:
        harness = _Harness()
        seg_1 = _segment("Map020.json:L0:0", "JP 1", "Hero")
        seg_new = _segment("Map020.json:L0:1", "JP NEW", "Hero")
        seg_2 = _segment("Map020.json:L0:2", "JP 2", "Hero")
        session = FileSession(
            path=Path("Map020.json"),
            data=[],
            bundles=[],
            segments=[seg_1, seg_new, seg_2],
        )
        hash_1 = harness._segment_source_hash(seg_1)
        hash_2 = harness._segment_source_hash(seg_2)
        harness.translation_state["files"] = {
            "Map020.json": {
                "order": ["T1", "T2"],
                "entries": {
                    "T1": {
                        "source_uid": seg_1.uid,
                        "source_hash": hash_1,
                        "translation_lines": ["TL 1"],
                    },
                    "T2": {
                        "source_uid": seg_2.uid,
                        "source_hash": hash_2,
                        "translation_lines": ["TL 2"],
                    },
                },
            }
        }

        harness._apply_translation_state_to_session(session)

        self.assertEqual(
            [segment.uid for segment in session.segments if not segment.translation_only],
            [seg_1.uid, seg_new.uid, seg_2.uid],
        )
        self.assertEqual(session.segments[0].translation_lines, ["TL 1"])
        self.assertEqual(session.segments[1].translation_lines, [""])
        self.assertEqual(session.segments[2].translation_lines, ["TL 2"])

    def test_translation_state_for_name_index_clears_speaker_fields(self) -> None:
        harness = _Harness()
        segment = _segment("System.json:Y:1:gameTitle", "JP title", r"\C[2]\N[1]\C[0]")
        segment.translation_lines = ["EN title"]
        segment.translation_speaker = "Should Not Persist"
        session = FileSession(
            path=Path("System.json"),
            data={},
            bundles=[],
            segments=[segment],
        )
        setattr(session, "is_name_index_session", True)

        state = harness._translation_state_for_session(session)
        self.assertEqual(len(state["order"]), 1)
        entry = state["entries"][state["order"][0]]
        self.assertEqual(entry["speaker_jp"], NO_SPEAKER_KEY)
        self.assertEqual(entry["speaker_en"], "")

    def test_load_translation_state_migrates_v1_to_v2(self) -> None:
        harness = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "translation_state.json"
            payload = {
                "version": 1,
                "uid_counter": 12,
                "speaker_map": {"Hero": "Aki"},
                "files": {
                    "Map001.json": {
                        "order": ["T00000012"],
                        "entries": {
                            "T00000012": {
                                "source_uid": "Map001.json:L0:0",
                                "source_hash": "abc",
                                "translation_lines": ["TL line"],
                            }
                        },
                    }
                },
            }
            state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            harness.translation_state_path = state_path
            harness._load_translation_state()

        self.assertEqual(harness.translation_state.get("version"), 2)
        self.assertEqual(harness.active_translation_profile_id, "default")
        self.assertEqual(harness.translation_state.get("source_language_code"), "ja")
        profiles = harness.translation_state.get("profiles")
        self.assertIsInstance(profiles, dict)
        default_profile = profiles.get("default") if isinstance(profiles, dict) else None
        self.assertIsInstance(default_profile, dict)
        if isinstance(default_profile, dict):
            self.assertEqual(default_profile.get("uid_counter"), 12)
            self.assertEqual(default_profile.get("speaker_map"), {"Hero": "Aki"})
            self.assertEqual(default_profile.get("target_language_code"), "en")
            prompt_template = default_profile.get("prompt_template")
            self.assertTrue(isinstance(prompt_template, str))
            if isinstance(prompt_template, str):
                self.assertIn("{payload_json}", prompt_template)
            files = default_profile.get("files")
            self.assertTrue(isinstance(files, dict) and "Map001.json" in files)

    def test_language_and_prompt_settings_normalization(self) -> None:
        harness = _Harness()
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "default",
            "source_language_code": "JA_JP",
            "profiles": {
                "default": {
                    "name": "Default",
                    "uid_counter": 0,
                    "target_language_code": "EN-US",
                    "prompt_template": "  Keep honorifics.  ",
                    "speaker_map": {},
                    "files": {},
                }
            },
        }
        source_lang = harness._translation_project_source_language_code()
        target_lang = harness._translation_profile_target_language_code("default")
        prompt_template = harness._translation_profile_prompt_template("default")
        self.assertEqual(source_lang, "ja-jp")
        self.assertEqual(target_lang, "en-us")
        self.assertEqual(prompt_template, "Keep honorifics.")

    def test_apply_state_uses_active_profile_and_keeps_speaker_map_isolated(self) -> None:
        harness = _Harness()
        seg = _segment("Map001.json:L0:0", "JP line", "Hero")
        session = FileSession(
            path=Path("Map001.json"),
            data=[],
            bundles=[],
            segments=[seg],
        )
        source_hash = harness._segment_source_hash(seg)
        harness.translation_state = {
            "version": 2,
            "active_profile_id": "alt",
            "profiles": {
                "default": {
                    "name": "Default",
                    "uid_counter": 1,
                    "speaker_map": {"Hero": "Default Hero"},
                    "files": {
                        "Map001.json": {
                            "order": ["T_default"],
                            "entries": {
                                "T_default": {
                                    "source_uid": seg.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Default TL"],
                                }
                            },
                        }
                    },
                },
                "alt": {
                    "name": "Alt",
                    "uid_counter": 2,
                    "speaker_map": {"Hero": "Alt Hero"},
                    "files": {
                        "Map001.json": {
                            "order": ["T_alt"],
                            "entries": {
                                "T_alt": {
                                    "source_uid": seg.uid,
                                    "source_hash": source_hash,
                                    "translation_lines": ["Alt TL"],
                                }
                            },
                        }
                    },
                },
            },
        }
        harness.active_translation_profile_id = "alt"
        profile_state = harness._active_profile_state()
        speaker_map_raw = profile_state.get("speaker_map")
        harness.speaker_translation_map = (
            dict(speaker_map_raw) if isinstance(speaker_map_raw, dict) else {}
        )
        harness._apply_translation_state_to_session(session)

        self.assertEqual(session.segments[0].translation_lines, ["Alt TL"])
        self.assertEqual(session.segments[0].translation_speaker, "Alt Hero")
        self.assertEqual(harness.speaker_translation_map.get("Hero"), "Alt Hero")

    def test_save_translation_state_updates_only_active_profile(self) -> None:
        harness = _Harness()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "translation_state.json"
            harness.translation_state_path = state_path

            seg = _segment("Map001.json:L0:0", "JP", "Hero")
            seg.tl_uid = "T_alt"
            seg.translation_lines = ["Alt TL"]
            seg.translation_speaker = "Alt Hero"
            session = FileSession(
                path=Path("Map001.json"),
                data=[],
                bundles=[],
                segments=[seg],
            )
            harness.sessions = {session.path: session}
            harness.speaker_translation_map = {"Hero": "Alt Hero"}
            harness.translation_uid_counter = 7
            harness.active_translation_profile_id = "alt"
            harness.translation_state = {
                "version": 2,
                "active_profile_id": "alt",
                "profiles": {
                    "default": {
                        "name": "Default",
                        "uid_counter": 1,
                        "speaker_map": {"Hero": "Default Hero"},
                        "files": {"Map001.json": {"order": ["T_default"], "entries": {}}},
                    },
                    "alt": {
                        "name": "Alt",
                        "uid_counter": 3,
                        "speaker_map": {},
                        "files": {},
                    },
                },
            }

            saved = harness._save_translation_state([session.path])
            self.assertTrue(saved)

            profiles = harness.translation_state.get("profiles")
            self.assertIsInstance(profiles, dict)
            if isinstance(profiles, dict):
                default_profile = profiles.get("default")
                alt_profile = profiles.get("alt")
                self.assertIsInstance(default_profile, dict)
                self.assertIsInstance(alt_profile, dict)
                if isinstance(default_profile, dict):
                    self.assertEqual(default_profile.get("uid_counter"), 1)
                    self.assertEqual(default_profile.get("speaker_map"), {"Hero": "Default Hero"})
                if isinstance(alt_profile, dict):
                    self.assertEqual(alt_profile.get("uid_counter"), 7)
                    self.assertEqual(alt_profile.get("speaker_map"), {"Hero": "Alt Hero"})
                    files = alt_profile.get("files")
                    self.assertTrue(isinstance(files, dict) and "Map001.json" in files)

            written = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(written.get("version"), 2)
            self.assertEqual(written.get("active_profile_id"), "alt")


if __name__ == "__main__":
    unittest.main()
