from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from dialogue_visual_editor.helpers.core.models import (
    CommandBundle,
    CommandToken,
    DialogueSegment,
    FileSession,
    NO_SPEAKER_KEY,
)
from dialogue_visual_editor.helpers.core.parser import (
    parse_dialogue_file,
    tyrano_config_source_from_data,
    tyrano_script_source_from_data,
)
from dialogue_visual_editor.helpers.mixins.persistence_export_mixin import (
    PersistenceExportMixin,
)
from dialogue_visual_editor.helpers.mixins.render_mixin import RenderMixin


class _BoolControl:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _SpinControl:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _Harness(PersistenceExportMixin):
    def __init__(self) -> None:
        self.auto_split_check = _BoolControl(False)
        self.max_lines_spin = _SpinControl(4)
        self.problem_char_limit_check = _BoolControl(False)
        self.problem_line_limit_check = _BoolControl(False)
        self.problem_control_mismatch_check = _BoolControl(False)
        self.problem_trailing_color_code_check = _BoolControl(False)
        self.problem_missing_translation_check = _BoolControl(False)
        self.problem_contains_japanese_check = _BoolControl(False)
        self.speaker_translation_map: dict[str, str] = {}

    def _is_name_index_session(self, session: FileSession) -> bool:
        return bool(getattr(session, "is_name_index_session", False))

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [
                item if isinstance(item, str) else ("" if item is None else str(item))
                for item in value
            ] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        if segment.speaker_name != NO_SPEAKER_KEY:
            return segment.speaker_name
        source_lines = list(segment.source_lines or segment.original_lines or segment.lines or [""])
        if (
            bool(getattr(segment, "force_line1_speaker_inference", False))
            and not bool(getattr(segment, "disable_line1_speaker_inference", False))
            and len(source_lines) > 1
            and source_lines[0].strip()
        ):
            return source_lines[0].strip()
        return NO_SPEAKER_KEY

    def _speaker_translation_for_key(self, speaker_key: str) -> str:
        return self.speaker_translation_map.get(speaker_key, "")


class _StatusBarHarness:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def showMessage(self, message: str) -> None:
        self.messages.append(message)


class _ListItemHarness:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _BatchSaveHarness(PersistenceExportMixin):
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.current_path: Path | None = None
        self.version_db = object()
        self.index_db = None
        self._dirty_source_paths: set[Path] = set()
        self._dirty_tl_paths: set[Path] = set()
        self.translation_state_calls: list[list[Path]] = []
        self.save_session_calls: list[dict[str, Any]] = []
        self.translation_state_result = True
        self._status_bar = _StatusBarHarness()

    def _is_translator_mode(self) -> bool:
        return True

    def _session_has_source_changes(self, session: FileSession) -> bool:
        return session.path in self._dirty_source_paths

    def _session_has_translation_changes(self, session: FileSession) -> bool:
        return session.path in self._dirty_tl_paths

    def _save_translation_state(self, changed_paths: list[Path] | None = None) -> bool:
        self.translation_state_calls.append(list(changed_paths or []))
        return self.translation_state_result

    def _save_session(
        self,
        session: FileSession,
        refresh_current_view: bool = False,
        *,
        save_translation_state: bool = True,
        show_status_message: bool = True,
    ) -> bool:
        self.save_session_calls.append(
            {
                "path": session.path,
                "refresh_current_view": refresh_current_view,
                "save_translation_state": save_translation_state,
                "show_status_message": show_status_message,
            }
        )
        return True

    def _create_save_all_progress_dialog(self, total_files: int) -> Any:
        _ = total_files
        return None

    def _update_save_all_progress_dialog(
        self,
        dialog: Any,
        value: int,
        label_text: str,
    ) -> None:
        _ = (dialog, value, label_text)

    def statusBar(self) -> _StatusBarHarness:
        return self._status_bar


class _VersionDbStub:
    def __init__(self) -> None:
        self.working_calls: list[tuple[str, Any]] = []
        self.translated_calls: list[tuple[str, Any, str]] = []

    def save_working_snapshot(self, rel_path: str, data: Any) -> None:
        self.working_calls.append((rel_path, data))

    def save_translated_snapshot(self, rel_path: str, data: Any, profile_id: str) -> None:
        self.translated_calls.append((rel_path, data, profile_id))


class _SaveSessionHarness(PersistenceExportMixin):
    def __init__(self) -> None:
        self.version_db = _VersionDbStub()
        self.index_db = None
        self.current_path: Path | None = None
        self.active_translation_profile_id = "default"
        self._status_bar = _StatusBarHarness()
        self.render_session_calls = 0
        self.refresh_visual_calls = 0
        self.refresh_detail_calls = 0
        self.rerender_nearby_calls = 0
        self.translation_state_calls: list[list[Path]] = []
        self.session_source_dirty = False

    def _is_translator_mode(self) -> bool:
        return True

    def _save_translation_state(self, changed_paths: list[Path] | None = None) -> bool:
        self.translation_state_calls.append(list(changed_paths or []))
        return True

    def _session_has_source_changes(self, session: FileSession) -> bool:
        _ = session
        return self.session_source_dirty

    def _collect_change_log(self, session: FileSession) -> list[tuple[str, str, str]]:
        _ = session
        return []

    def _build_source_data_for_session(self, session: FileSession) -> Any:
        _ = session
        return {"working": True}

    def _export_translated_data_for_session(self, session: FileSession) -> Any:
        _ = session
        return {"translated": True}

    def _relative_path(self, path: Path) -> str:
        return path.name

    def _mark_session_source_saved(self, session: FileSession) -> None:
        _ = session
        return

    def _mark_session_translation_saved(self, session: FileSession) -> None:
        _ = session
        return

    def _clear_structural_history_for_path(self, _path: Path) -> None:
        return

    def _refresh_dirty_state(self, session: FileSession) -> None:
        _ = session
        return

    def _render_session(self, session: FileSession, preserve_scroll: bool = False) -> None:
        _ = (session, preserve_scroll)
        self.render_session_calls += 1

    def _refresh_block_visual_states(self) -> None:
        self.refresh_visual_calls += 1

    def _refresh_translator_detail_panel(self) -> None:
        self.refresh_detail_calls += 1

    def _rerender_blocks_near_viewport(self, overscan_px: int = 800) -> None:
        _ = overscan_px
        self.rerender_nearby_calls += 1

    def statusBar(self) -> _StatusBarHarness:
        return self._status_bar


class _ResetCurrentFileHarness(PersistenceExportMixin):
    def __init__(self) -> None:
        self.current_path: Path | None = None
        self.sessions: dict[Path, FileSession] = {}
        self._status_bar = _StatusBarHarness()
        self.refresh_dirty_calls = 0
        self.rerender_nearby_calls = 0
        self.render_session_calls = 0

    def _is_translator_mode(self) -> bool:
        return True

    def _session_has_translation_changes(self, session: FileSession) -> bool:
        _ = session
        return True

    def _refresh_dirty_state(self, session: FileSession) -> None:
        _ = session
        self.refresh_dirty_calls += 1

    def _rerender_blocks_near_viewport(self, overscan_px: int = 800) -> None:
        _ = overscan_px
        self.rerender_nearby_calls += 1

    def _render_session(self, session: FileSession) -> None:
        _ = session
        self.render_session_calls += 1

    def statusBar(self) -> _StatusBarHarness:
        return self._status_bar


class _ActorAliasSaveHarness(PersistenceExportMixin):
    def __init__(self) -> None:
        self.version_db = _VersionDbStub()
        self.index_db = None
        self.current_path: Path | None = None
        self.active_translation_profile_id = "default"
        self.sessions: dict[Path, FileSession] = {}
        self.translation_state_calls: list[list[Path]] = []
        self._status_bar = _StatusBarHarness()

    def _is_translator_mode(self) -> bool:
        return True

    def _save_translation_state(self, changed_paths: list[Path] | None = None) -> bool:
        self.translation_state_calls.append(list(changed_paths or []))
        return True

    def _session_has_source_changes(self, session: FileSession) -> bool:
        if bool(getattr(session, "_has_external_source_edits", False)):
            return True
        for segment in session.segments:
            if segment.translation_only:
                continue
            if segment.lines != segment.original_lines:
                return True
        return False

    def _collect_change_log(self, session: FileSession) -> list[tuple[str, str, str]]:
        _ = session
        return []

    def _build_source_data_for_session(self, session: FileSession) -> Any:
        return {"working": session.path.name}

    def _export_translated_data_for_session(self, session: FileSession) -> Any:
        return super()._export_translated_data_for_session(session)

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [
                item if isinstance(item, str) else ("" if item is None else str(item))
                for item in value
            ] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    def _relative_path(self, path: Path) -> str:
        return path.name

    def _mark_session_translation_saved(self, session: FileSession) -> None:
        _ = session
        return

    def _clear_structural_history_for_path(self, _path: Path) -> None:
        return

    def _refresh_dirty_state(self, session: FileSession) -> None:
        _ = session
        return

    def statusBar(self) -> _StatusBarHarness:
        return self._status_bar


class _ScopedWarningBadgeHarness(PersistenceExportMixin, RenderMixin):
    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}
        self.file_items: dict[Path, _ListItemHarness] = {}
        self.file_items_scoped: dict[tuple[Path, str], _ListItemHarness] = {}
        self.problem_char_limit_check = _BoolControl(True)
        self.problem_line_limit_check = _BoolControl(False)
        self.problem_control_mismatch_check = _BoolControl(False)
        self.problem_trailing_color_code_check = _BoolControl(False)
        self.problem_missing_translation_check = _BoolControl(False)
        self.problem_contains_japanese_check = _BoolControl(False)
        self.thin_width_spin = _SpinControl(1)
        self.wide_width_spin = _SpinControl(1)
        self.max_lines_spin = _SpinControl(4)
        self.hide_non_meaningful_entries_check = _BoolControl(False)

    def _is_translator_mode(self) -> bool:
        return False

    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [item if isinstance(item, str) else "" for item in value] or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    def _is_name_index_session(self, session: FileSession) -> bool:
        return bool(getattr(session, "is_name_index_session", False))

    def _file_list_items_for_path(self, path: Path) -> list[tuple[str, _ListItemHarness]]:
        items: list[tuple[str, _ListItemHarness]] = []
        for (candidate_path, scope), item in self.file_items_scoped.items():
            if candidate_path == path:
                items.append((scope, item))
        items.sort(key=lambda row: 0 if row[0] == "dialogue" else 1)
        return items


def _dialogue_segment(uid: str, text: str) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[text],
        original_lines=[text],
        source_lines=[text],
        code401_template={"code": 401, "indent": 0, "parameters": [""]},
    )


class PersistenceExportMixinTests(unittest.TestCase):
    def test_set_json_value_by_path(self) -> None:
        harness = _Harness()
        payload = {"a": {"b": ["x", "y"]}}
        changed = harness._set_json_value_by_path(payload, ("a", "b", 1), "z")
        unchanged = harness._set_json_value_by_path(payload, ("a", "c"), "z")
        self.assertTrue(changed)
        self.assertFalse(unchanged)
        self.assertEqual(payload["a"]["b"][1], "z")

    def test_apply_session_to_json_updates_map_display_name(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:map_display_name", "Village")
        setattr(segment, "map_display_name_path", ("displayName",))
        segment.segment_kind = "map_display_name"
        session = FileSession(
            path=Path("Map001.json"),
            data={"displayName": "Old"},
            bundles=[],
            segments=[segment],
        )

        harness._apply_session_to_json(session)
        self.assertEqual(session.data["displayName"], "Village")

    def test_apply_session_to_json_updates_name_index_combined_fields(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Items.json:I:1", "Potion")
        segment.lines = ["Potion", "", "Heals HP"]
        segment.original_lines = list(segment.lines)
        setattr(segment, "name_index_combined_fields", ("name", "description"))
        session = FileSession(
            path=Path("Items.json"),
            data=[{"id": 1, "name": "Old", "description": "Old desc"}],
            bundles=[],
            segments=[segment],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_uid_prefix", "I")

        harness._apply_session_to_json(session)
        row = session.data[0]
        self.assertEqual(row["name"], "Potion")
        self.assertEqual(row["description"], "Heals HP")

    def test_apply_session_to_json_updates_name_index_fields_in_mixed_session(self) -> None:
        harness = _Harness()
        dialogue_segment = _dialogue_segment("Troops.json:L0:0", "Hello")
        name_segment = _dialogue_segment("Troops.json:P:1", "Troop Updated")
        name_segment.segment_kind = "name_index"
        session = FileSession(
            path=Path("Troops.json"),
            data=[{"id": 1, "name": "Troop Old"}],
            bundles=[],
            segments=[dialogue_segment, name_segment],
        )
        setattr(session, "name_index_uid_prefix", "P")

        harness._apply_session_to_json(session)

        self.assertEqual(session.data[0]["name"], "Troop Updated")

    def test_apply_session_to_json_rebuilds_dialogue_in_mixed_name_index_session(self) -> None:
        harness = _Harness()
        commands_ref: list[Any] = [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            {"code": 401, "indent": 0, "parameters": ["Old troop line"]},
            {"code": 0, "indent": 0, "parameters": []},
        ]
        dialogue_segment = _dialogue_segment("Troops.json:L0:0", "New troop line")
        name_segment = _dialogue_segment("Troops.json:P:1", "Troop Updated")
        name_segment.segment_kind = "name_index"
        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[
                CommandToken(kind="dialogue", segment=dialogue_segment),
                CommandToken(kind="raw", raw_entry={"code": 0, "indent": 0, "parameters": []}),
            ],
        )
        session = FileSession(
            path=Path("Troops.json"),
            data=[
                {
                    "id": 1,
                    "name": "Troop Old",
                    "pages": [{"list": commands_ref}],
                }
            ],
            bundles=[bundle],
            segments=[dialogue_segment, name_segment],
        )
        setattr(session, "name_index_uid_prefix", "P")

        harness._apply_session_to_json(session)

        self.assertEqual(session.data[0]["name"], "Troop Updated")
        rebuilt_list = session.data[0]["pages"][0]["list"]
        rebuilt_codes = [entry.get("code") for entry in rebuilt_list]
        self.assertEqual(rebuilt_codes, [101, 401, 0])
        self.assertEqual(rebuilt_list[1]["parameters"][0], "New troop line")

    def test_apply_session_to_json_updates_plugin_command_argument_path(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:G:0:text", "old")
        segment.segment_kind = "plugin_command_text"
        segment.lines = ["new value"]
        segment.original_lines = ["old"]
        setattr(
            segment,
            "json_text_path",
            ("events", 0, "pages", 0, "list", 0, "parameters", 3, "text"),
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={
                "events": [
                    {
                        "pages": [
                            {
                                "list": [
                                    {
                                        "code": 357,
                                        "indent": 0,
                                        "parameters": [
                                            "DTextPicture",
                                            "dText",
                                            "Label",
                                            {"text": "old"},
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            bundles=[],
            segments=[segment],
        )

        harness._apply_session_to_json(session)

        self.assertEqual(
            session.data["events"][0]["pages"][0]["list"][0]["parameters"][3]["text"],
            "new value",
        )

    def test_apply_session_to_json_updates_event_note_path(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:N:abc", "<LB:\\i[150]あずみさん>")
        segment.segment_kind = "note_text"
        segment.lines = ["<LB:\\i[150]アズミさん>"]
        segment.original_lines = ["<LB:\\i[150]あずみさん>"]
        setattr(segment, "json_text_path", ("events", 1, "note"))
        session = FileSession(
            path=Path("Map001.json"),
            data={
                "events": [
                    None,
                    {"id": 3, "note": "<LB:\\i[150]あずみさん>", "pages": []},
                ]
            },
            bundles=[],
            segments=[segment],
        )

        harness._apply_session_to_json(session)

        self.assertEqual(
            session.data["events"][1]["note"],
            "<LB:\\i[150]アズミさん>",
        )

    def test_apply_session_to_json_updates_tyrano_dialogue_choice_and_tag_text(self) -> None:
        harness = _Harness()
        source = (
            "[tb_start_text mode=1 ]\n"
            "#NPC\n"
            "こんにちは[p]\n"
            "[_tb_end_text]\n"
            "[glink text=\"選択肢A\" target=\"*A\"]\n"
            "[button text=\"補助ラベル\" target=\"*B\"]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        tag_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
        )
        params = dialogue_segment.params
        while len(params) <= 4:
            params.append("")
        params[4] = "Narrator"
        dialogue_segment.code101["parameters"] = params
        dialogue_segment.lines = ["Hello", "World"]
        choice_segment.lines = ["Choice A"]
        tag_segment.lines = ["Label B"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("#Narrator", rebuilt)
        self.assertIn("Hello[r]", rebuilt)
        self.assertIn("World[p]", rebuilt)
        self.assertIn('text="Choice\u202FA"', rebuilt)
        self.assertIn('text="Label B"', rebuilt)

    def test_apply_session_to_json_updates_plain_tyrano_hash_speaker_dialogue(self) -> None:
        harness = _Harness()
        source = (
            "#NPC\n"
            "こんにちは[r]\n"
            "よろしくね[p]\n"
            "@jump target=\"*A\"\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_plain.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        dialogue_segment.lines = ["Hello", "World"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("#NPC", rebuilt)
        self.assertIn("Hello[r]", rebuilt)
        self.assertIn("World[p]", rebuilt)
        self.assertNotIn("[tb_start_text", rebuilt)
        self.assertNotIn("[_tb_end_text]", rebuilt)

    def test_apply_session_to_json_preserves_tyrano_dialogue_line_indentation_prefixes(self) -> None:
        harness = _Harness()
        source = (
            "#妹\n"
            "    You're not done yet?[r]\n"
            "\tWhat, still going?[p]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_plain_indented.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        self.assertEqual(dialogue_segment.lines, ["You're not done yet?", "What, still going?"])

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("    You're not done yet?[r]", rebuilt)
        self.assertIn("\tWhat, still going?[p]", rebuilt)

    def test_apply_session_to_json_updates_markerless_conditional_dialogue_branch_text(self) -> None:
        harness = _Harness()
        source = (
            "#妹\n"
            "A[r]\n"
            "B[p]\n"
            "C\n"
            "[if exp=\"flag\"]\n"
            "も\n"
            "[endif]\n"
            "D[p]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_if_branch_text_save.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        conditional_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
            and "も" in segment.lines
        )
        conditional_segment.lines = [
            "too" if line == "も" else line
            for line in conditional_segment.lines
        ]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("[if exp=\"flag\"]", rebuilt)
        self.assertIn("[endif]", rebuilt)
        self.assertIn("too", rebuilt)
        self.assertNotIn("\nも\n", rebuilt)

    def test_apply_session_to_json_preserves_conditional_branch_text_when_editing_neighbor_segments(self) -> None:
        harness = _Harness()
        source = (
            "#妹\n"
            "女の子にされちゃっても、おっぱいの事考えてるなんて…[r]\n"
            "お兄ちゃんって本当におっぱい大好きなのね。[p]\n"
            "そんなにおっぱいが好きなら、[r]\n"
            "お兄ちゃんのおっぱい\n"
            "[if exp=\"getStoryFlag('妹変化')\"]\n"
            "    も\n"
            "[endif]\n"
            "大きくしてあげようか？[p]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_conditional_neighbor_edit.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        non_conditional_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
            and "も" not in segment.lines
        ]
        self.assertTrue(non_conditional_segments)
        for segment in non_conditional_segments:
            segment.lines = [line.replace("おっぱい", "boobs") for line in segment.lines]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("[if exp=\"getStoryFlag('妹変化')\"]", rebuilt)
        self.assertIn("[endif]", rebuilt)
        self.assertIn("\n    も\n", rebuilt)

    def test_apply_session_to_json_updates_tyrano_iscript_assignment_text_string(self) -> None:
        harness = _Harness()
        source = (
            "[iscript]\n"
            "mp.text = 'はじめから';\n"
            "mp.storage = 'opening.ks';\n"
            "[endscript]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_script_text.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        script_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
            and "script_text[" in segment.context
        )
        script_segment.lines = ["Start", "From Beginning"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("mp.text = 'Start\\nFrom Beginning';", rebuilt)
        self.assertIn("mp.storage = 'opening.ks';", rebuilt)
        self.assertNotIn("mp.text = 'はじめから';", rebuilt)

    def test_apply_session_to_json_updates_tyrano_iscript_object_property_name_string(self) -> None:
        harness = _Harness()
        source = (
            "[iscript]\n"
            "CHARA_LIST['兄'] = {\n"
            "    name        : '璃久'\n"
            "  , fullName    : '天宮 璃久'\n"
            "};\n"
            "[endscript]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_script_names.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        name_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
            and "script_text[" in segment.context
            and segment.lines == ["璃久"]
        )
        full_name_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
            and "script_text[" in segment.context
            and segment.lines == ["天宮 璃久"]
        )
        name_segment.lines = ["Riku"]
        full_name_segment.lines = ["Amamiya Riku"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("name        : 'Riku'", rebuilt)
        self.assertIn("fullName    : 'Amamiya Riku'", rebuilt)
        self.assertNotIn("name        : '璃久'", rebuilt)
        self.assertNotIn("fullName    : '天宮 璃久'", rebuilt)

    def test_apply_session_to_json_updates_tyrano_js_const_object_strings(self) -> None:
        harness = _Harness()
        source = (
            "const CHARA_LIST = {};\n"
            "CHARA_LIST['兄'] = {\n"
            "    name        : '璃久'\n"
            "  , fullName    : '天宮 璃久'\n"
            "};\n"
            "const END_LIST = [{ id: '双子' }];\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "const.js"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
            and "script_text[" in segment.context
        ]
        self.assertEqual([segment.lines[0] for segment in segments], ["璃久", "天宮 璃久", "双子"])
        segments[0].lines = ["Riku"]
        segments[1].lines = ["Amamiya Riku"]
        segments[2].lines = ["Twins"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("name        : 'Riku'", rebuilt)
        self.assertIn("fullName    : 'Amamiya Riku'", rebuilt)
        self.assertIn("id: '双子'", rebuilt)
        self.assertNotIn("name        : '璃久'", rebuilt)
        self.assertNotIn("fullName    : '天宮 璃久'", rebuilt)
        self.assertIn("// __DVE_END_NAME_MAP_START__", rebuilt)
        self.assertIn("'双子': 'Twins'", rebuilt)
        self.assertIn("getEndName = function(id)", rebuilt)

    def test_apply_session_to_json_removes_tyrano_end_name_override_when_no_end_id_translation(self) -> None:
        harness = _Harness()
        source = (
            "const END_LIST = [{ id: '双子' }];\n"
            "\n"
            "// __DVE_END_NAME_MAP_START__\n"
            "const DVE_END_NAME_MAP = {\n"
            "    '双子': 'Twins',\n"
            "};\n"
            "// __DVE_END_NAME_MAP_END__\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "const.js"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
            and "script_text[" in segment.context
        ]
        self.assertEqual(len(segments), 1)
        segments[0].lines = ["双子"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertNotIn("__DVE_END_NAME_MAP_START__", rebuilt)
        self.assertNotIn("DVE_END_NAME_MAP", rebuilt)

    def test_apply_session_to_json_keeps_tyrano_end_key_reference_assignments_stable(self) -> None:
        harness = _Harness()
        source = (
            "[iscript]\n"
            "f.ending = '双子';\n"
            "[endscript]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "end_refs.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        ref_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
            and "script_text[" in segment.context
        )
        self.assertEqual(
            getattr(ref_segment, "tyrano_tag_text_join_mode", ""),
            "script_string_end_id_ref",
        )
        ref_segment.lines = ["Twins"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("f.ending = '双子';", rebuilt)
        self.assertNotIn("f.ending = 'Twins';", rebuilt)

    def test_apply_session_to_json_updates_tyrano_multi_page_chunk(self) -> None:
        harness = _Harness()
        source = (
            "[tb_start_text mode=3 ]\n"
            "#NPC\n"
            "「前半」[r]\n"
            "「後半」[p][r]\n"
            "「次のページ」[p][r]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_split.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        ]
        self.assertEqual(len(dialogue_segments), 2)
        dialogue_segments[0].lines = ["First page"]
        dialogue_segments[1].lines = ["Second page"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("First page[p][r]", rebuilt)
        self.assertIn("Second page[p][r]", rebuilt)
        self.assertNotIn("「前半」[r]", rebuilt)
        self.assertNotIn("「次のページ」[p][r]", rebuilt)

    def test_apply_session_to_json_writes_inline_r_for_tyrano_dialogue_newlines(self) -> None:
        harness = _Harness()
        source = (
            "[tb_start_text mode=3 ]\n"
            "#NPC\n"
            "A[r]B[p][r]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_inline_r.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        dialogue_segment.lines = ["First line", "Second line"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("First line[r]", rebuilt)
        self.assertIn("Second line[p][r]", rebuilt)

    def test_apply_session_to_json_tyrano_extra_lines_use_r_not_page_break_fallback(self) -> None:
        harness = _Harness()
        source = (
            "[tb_start_text mode=3 ]\n"
            "#NPC\n"
            "A[r]\n"
            "B[p][r]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_dialogue_page_suffix_fallback.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        dialogue_segment.lines = ["First line", "Second line", "Third line"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("Third line[r]", rebuilt)
        self.assertNotIn("Third line[p][r]", rebuilt)

    def test_render_tyrano_dialogue_lines_strips_page_break_from_nonterminal_suffix(self) -> None:
        segment = _dialogue_segment("scene.ks:K:99", "unused")
        segment.segment_kind = "tyrano_dialogue"
        setattr(segment, "tyrano_line_suffixes", ("[p][r]", "[p][r]"))

        rendered, used = _Harness._render_tyrano_segment_lines_for_save(
            segment,
            ["Besides, there are only a handful of routes where you actually get to live happily ever", 'after."'],
        )

        self.assertEqual(rendered[0], "Besides, there are only a handful of routes where you actually get to live happily ever[r]")
        self.assertEqual(rendered[1], 'after."[p][r]')
        self.assertEqual(used, ["[r]", "[p][r]"])

    def test_apply_session_to_json_tyrano_splits_embedded_newline_before_suffix_assignment(self) -> None:
        harness = _Harness()
        source = (
            "[tb_start_text mode=3 ]\n"
            "#NPC\n"
            "Orig[p][r]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_dialogue_embedded_newline_suffix.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        dialogue_segment.lines = [
            'Besides, there are only a handful of routes where you actually get to live happily ever\nafter."'
        ]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("happily ever[r]", rebuilt)
        self.assertIn('after."[p][r]', rebuilt)
        self.assertNotIn("happily ever[p][r]", rebuilt)

    def test_apply_session_to_json_tyrano_strips_leaked_trailing_markers_from_nonterminal_line_text(self) -> None:
        harness = _Harness()
        source = (
            "[tb_start_text mode=3 ]\n"
            "#NPC\n"
            "Orig[p][r]\n"
            "[_tb_end_text]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_dialogue_marker_leak_nonterminal.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        dialogue_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_dialogue"
        )
        dialogue_segment.lines = [
            'Besides, there are only a handful of routes where you actually get to live happily ever[p][r]\nafter."'
        ]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn("happily ever[r]", rebuilt)
        self.assertIn('after."[p][r]', rebuilt)
        self.assertNotIn("happily ever[p][r]", rebuilt)

    def test_apply_session_to_json_writes_inline_r_for_tyrano_choice_newlines(self) -> None:
        harness = _Harness()
        source = '[glink text="A[r]B" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_choice_inline_r.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        choice_segment.lines = ["Choice\nLine"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn('text="Choice[r]Line"', rebuilt)

    def test_apply_session_to_json_updates_tyrano_mylink_choice_text(self) -> None:
        harness = _Harness()
        source = (
            '@mylink text="元に戻せ！" target="*A"\n'
            '@mylink text="胸が小さいな…" target="*B"\n'
            "[s]\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_choice_mylink.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        choice_segment.lines = ["Change me back!", "Your chest is kind of small..."]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn('@mylink text="Change\u202fme\u202fback!" target="*A"', rebuilt)
        self.assertIn('@mylink text="Your\u202fchest\u202fis\u202fkind\u202fof\u202fsmall..." target="*B"', rebuilt)

    def test_apply_session_to_json_preserves_tyrano_choice_intentional_spaces(self) -> None:
        harness = _Harness()
        source = '[glink text="A B" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_choice_spaces.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        choice_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "choice"
        )
        choice_segment.lines = ["  A   B  "]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn('text="\u202F\u202FA\u202F\u202F\u202FB\u202F\u202F"', rebuilt)

    def test_apply_session_to_json_writes_inline_r_for_tyrano_tag_text_newlines(self) -> None:
        harness = _Harness()
        source = '[button text="A" target="*A"]\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_tag_text_newlines.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        tag_segment = next(
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
        )
        tag_segment.lines = ["Line A\nLine B"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn('text="Line A[r]Line B"', rebuilt)

    def test_apply_session_to_json_updates_tyrano_at_command_tag_text(self) -> None:
        harness = _Harness()
        source = (
            '@titlebutton text="兄編" target="*A"\n'
            '@titlebutton text="妹編" target="*B"\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "scene_at_tag_text_save.ks"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        tag_segments = [
            segment
            for segment in session.segments
            if segment.segment_kind == "tyrano_tag_text"
        ]
        self.assertEqual([segment.lines for segment in tag_segments], [["兄編"], ["妹編"]])
        tag_segments[0].lines = ["Brother Route"]
        tag_segments[1].lines = ["Sister Route"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_script_source_from_data(session.data)

        self.assertIn('@titlebutton text="Brother Route" target="*A"', rebuilt)
        self.assertIn('@titlebutton text="Sister Route" target="*B"', rebuilt)
        self.assertNotIn('@titlebutton text="兄編" target="*A"', rebuilt)
        self.assertNotIn('@titlebutton text="妹編" target="*B"', rebuilt)

    def test_apply_session_to_json_updates_tyrano_config_system_title(self) -> None:
        harness = _Harness()
        source = (
            ";debugMenu.visible=false\n"
            ";System.title=せんていトランス\n"
            ";game_version=0.0\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "Config.tjs"
            path.write_text(source, encoding="utf-8")
            session = parse_dialogue_file(path)

        title_segment = session.segments[0]
        title_segment.lines = ["Sentei Trans"]

        harness._apply_session_to_json(session)
        rebuilt = tyrano_config_source_from_data(session.data)

        self.assertIn(";System.title=Sentei Trans", rebuilt)
        self.assertNotIn(";System.title=せんていトランス", rebuilt)

    def test_apply_session_to_json_rebuilds_command_list(self) -> None:
        harness = _Harness()
        commands_ref: list[Any] = []
        segment = _dialogue_segment("Map001.json:L0:0", "Line 1")
        segment.lines = ["Line 1", "Line 2"]
        segment.original_lines = list(segment.lines)
        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[
                CommandToken(kind="dialogue", segment=segment),
                CommandToken(kind="raw", raw_entry={"code": 0, "indent": 0, "parameters": []}),
            ],
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={"list": commands_ref},
            bundles=[bundle],
            segments=[segment],
        )

        harness._apply_session_to_json(session)
        rebuilt_codes = [entry.get("code") for entry in session.data["list"]]
        self.assertEqual(rebuilt_codes, [101, 401, 401, 0])
        self.assertEqual(session.data["list"][1]["parameters"][0], "Line 1")
        self.assertEqual(session.data["list"][2]["parameters"][0], "Line 2")

    def test_build_entries_for_script_message_segment_preserves_face_bg_and_pos_calls(self) -> None:
        harness = _Harness()
        segment = DialogueSegment(
            uid="Map010.json:L0:0",
            context="ctx",
            code101={"code": 101, "indent": 5, "parameters": ["face", 0, 0, 2, r"\C[2]\N[1]\C[0]"]},
            lines=["JP 1", "JP 2"],
            original_lines=["JP 1", "JP 2"],
            source_lines=["JP 1", "JP 2"],
            code401_template={"code": 655, "indent": 5, "parameters": ["$gameMessage.add(\"\");"]},
            segment_kind="script_message",
            line_entry_code=655,
            script_entries_template=[
                {"code": 655, "indent": 5, "parameters": ["$gameMessage.setFaceImage(face,$gameVariables.value(37));"]},
                {"code": 655, "indent": 5, "parameters": ["$gameMessage.setBackground(0);"]},
                {"code": 655, "indent": 5, "parameters": ["$gameMessage.setPositionType(2);"]},
                {"code": 655, "indent": 5, "parameters": ['$gameMessage.setSpeakerName("\\\\C[2]\\\\N[1]\\\\C[0]");']},
                {"code": 655, "indent": 5, "parameters": ['$gameMessage.add("JP 1");']},
                {"code": 655, "indent": 5, "parameters": ['$gameMessage.add("JP 2");']},
                {"code": 655, "indent": 5, "parameters": ["this.setWaitMode('message');"]},
            ],
            script_entry_roles=["face", "background", "position", "speaker", "add", "add", "other"],
            script_entry_quotes=['"', '"', '"', '"', '"', '"', '"'],
        )

        rebuilt = harness._build_entries_for_script_message_segment(
            segment,
            ["TL 1", "TL 2"],
        )

        rebuilt_lines = [entry["parameters"][0] for entry in rebuilt]
        self.assertEqual(rebuilt_lines[0], "$gameMessage.setFaceImage(face,$gameVariables.value(37));")
        self.assertEqual(rebuilt_lines[1], "$gameMessage.setBackground(0);")
        self.assertEqual(rebuilt_lines[2], "$gameMessage.setPositionType(2);")
        self.assertEqual(rebuilt_lines[4], '$gameMessage.add("TL 1");')
        self.assertEqual(rebuilt_lines[5], '$gameMessage.add("TL 2");')
        self.assertEqual(rebuilt_lines[6], "this.setWaitMode('message');")

    def test_build_entries_for_script_message_segment_preserves_expression_terms(self) -> None:
        harness = _Harness()
        segment = DialogueSegment(
            uid="Map011.json:L0:0",
            context="ctx",
            code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            lines=["A{{EXPR1}}B"],
            original_lines=["A{{EXPR1}}B"],
            source_lines=["A{{EXPR1}}B"],
            code401_template={"code": 655, "indent": 0, "parameters": ["$gameMessage.add(\"\");"]},
            segment_kind="script_message",
            line_entry_code=655,
            script_entries_template=[
                {"code": 355, "indent": 0, "parameters": ["var seed = 1;"]},
                {"code": 655, "indent": 0, "parameters": ['$gameMessage.add("A" + m + "B");']},
            ],
            script_entry_roles=["other", "add"],
            script_entry_quotes=['"', '"'],
            script_entry_expression_templates=[None, {"kind": "add", "expr_terms": ["m"]}],
        )

        rebuilt = harness._build_entries_for_script_message_segment(
            segment,
            ["TL {{EXPR1}} done"],
        )

        rebuilt_lines = [entry["parameters"][0] for entry in rebuilt]
        self.assertEqual(rebuilt_lines[0], "var seed = 1;")
        self.assertEqual(rebuilt_lines[1], '$gameMessage.add("TL " + m + " done");')

    def test_build_source_data_for_session_rebuilds_without_mutating_original(self) -> None:
        harness = _Harness()
        commands_ref: list[Any] = [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            {"code": 401, "indent": 0, "parameters": ["Old"]},
        ]
        segment = _dialogue_segment("Map001.json:L0:0", "Old")
        segment.lines = ["New 1", "New 2"]
        segment.original_lines = ["Old"]
        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[CommandToken(kind="dialogue", segment=segment)],
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={"list": commands_ref},
            bundles=[bundle],
            segments=[segment],
        )

        source_data = harness._build_source_data_for_session(session)

        self.assertEqual([entry["code"] for entry in source_data["list"]], [101, 401, 401])
        self.assertEqual(source_data["list"][1]["parameters"][0], "New 1")
        self.assertEqual(source_data["list"][2]["parameters"][0], "New 2")
        self.assertEqual(commands_ref[1]["parameters"][0], "Old")

    def test_build_source_data_for_name_index_session(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Items.json:I:1", "Potion")
        segment.lines = ["Potion", "", "Heals HP"]
        segment.original_lines = list(segment.lines)
        setattr(segment, "name_index_combined_fields", ("name", "description"))
        session = FileSession(
            path=Path("Items.json"),
            data=[{"id": 1, "name": "Old", "description": "Old desc"}],
            bundles=[],
            segments=[segment],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_uid_prefix", "I")

        source_data = harness._build_source_data_for_session(session)

        self.assertEqual(source_data[0]["name"], "Potion")
        self.assertEqual(source_data[0]["description"], "Heals HP")

    def test_apply_session_to_json_skips_actor_alias_rows(self) -> None:
        harness = _Harness()
        actor_segment = _dialogue_segment("Actors.json:A:1", "Harold")
        alias_segment = _dialogue_segment("Actors.json:A:1:alt_1", "ヒナタ")
        alias_segment.segment_kind = "actor_name_alias"
        setattr(alias_segment, "is_actor_name_alias", True)
        session = FileSession(
            path=Path("Actors.json"),
            data=[{"id": 1, "name": "Old"}],
            bundles=[],
            segments=[actor_segment, alias_segment],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_uid_prefix", "A")

        harness._apply_session_to_json(session)

        row = session.data[0]
        self.assertEqual(row["name"], "Harold")
        self.assertNotIn("alt_1", row)

    def test_export_translated_data_inserts_translation_only_followups(self) -> None:
        harness = _Harness()
        commands_ref: list[Any] = []
        source = _dialogue_segment("src", "JP line")
        source.translation_lines = ["TL main"]
        source.original_translation_lines = [""]
        followup = _dialogue_segment("followup", "")
        followup.translation_only = True
        followup.translation_lines = ["TL extra"]
        followup.original_translation_lines = [""]

        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[CommandToken(kind="dialogue", segment=source)],
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={"list": commands_ref},
            bundles=[bundle],
            segments=[source, followup],
        )

        exported = harness._export_translated_data_for_session(session)
        rebuilt = exported["list"]
        self.assertEqual([entry["code"] for entry in rebuilt], [101, 401, 101, 401])
        self.assertEqual(rebuilt[1]["parameters"][0], "TL main")
        self.assertEqual(rebuilt[3]["parameters"][0], "TL extra")

    def test_export_translated_data_does_not_write_101_speaker_for_forced_line1_inference(self) -> None:
        harness = _Harness()
        commands_ref: list[Any] = [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            {"code": 401, "indent": 0, "parameters": ["Hero"]},
            {"code": 401, "indent": 0, "parameters": ["JP line"]},
        ]
        source = DialogueSegment(
            uid="src",
            context="ctx",
            code101=commands_ref[0],
            lines=["Hero", "JP line"],
            original_lines=["Hero", "JP line"],
            source_lines=["Hero", "JP line"],
            code401_template={"code": 401, "indent": 0, "parameters": [""]},
            translation_lines=["EN line"],
            original_translation_lines=[""],
            translation_speaker="Yuki",
            force_line1_speaker_inference=True,
            original_force_line1_speaker_inference=True,
        )

        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[CommandToken(kind="dialogue", segment=source)],
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={"list": commands_ref},
            bundles=[bundle],
            segments=[source],
        )

        exported = harness._export_translated_data_for_session(session)
        rebuilt = exported["list"]
        self.assertEqual(rebuilt[0]["parameters"][4], "")
        self.assertEqual(rebuilt[1]["parameters"][0], "EN line")

    def test_export_translated_data_uses_saved_speaker_map_for_forced_line1_inference(self) -> None:
        harness = _Harness()
        harness.speaker_translation_map["勇者"] = "Hero"
        commands_ref: list[Any] = [
            {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
            {"code": 401, "indent": 0, "parameters": ["勇者"]},
            {"code": 401, "indent": 0, "parameters": ["JP line"]},
        ]
        source = DialogueSegment(
            uid="src",
            context="ctx",
            code101=commands_ref[0],
            lines=["勇者", "JP line"],
            original_lines=["勇者", "JP line"],
            source_lines=["勇者", "JP line"],
            code401_template={"code": 401, "indent": 0, "parameters": [""]},
            translation_lines=["EN line"],
            original_translation_lines=[""],
            translation_speaker="",
            force_line1_speaker_inference=True,
            original_force_line1_speaker_inference=True,
        )

        bundle = CommandBundle(
            context="ctx",
            commands_ref=commands_ref,
            tokens=[CommandToken(kind="dialogue", segment=source)],
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={"list": commands_ref},
            bundles=[bundle],
            segments=[source],
        )

        exported = harness._export_translated_data_for_session(session)
        rebuilt = exported["list"]
        self.assertEqual(rebuilt[0]["parameters"][4], "")
        self.assertEqual(rebuilt[1]["parameters"][0], "EN line")

    def test_missing_translation_problem_detects_empty_translation(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", "JP line")
        segment.translation_lines = [""]
        self.assertTrue(
            harness._segment_has_missing_translation_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_missing_translation_problem_ignores_filled_translation(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", "JP line")
        segment.translation_lines = ["EN line"]
        self.assertFalse(
            harness._segment_has_missing_translation_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_missing_translation_problem_ignores_source_without_visible_text(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", r"\!")
        segment.translation_lines = [""]
        self.assertFalse(
            harness._segment_has_missing_translation_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_japanese_text_problem_detects_hiragana_or_kanji_in_translation(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", "JP line")
        segment.translation_lines = ["Knight sama です"]
        self.assertTrue(
            harness._segment_has_japanese_text_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_japanese_text_problem_ignores_non_japanese_translation(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", "JP line")
        segment.translation_lines = [r"\N[3]-sama"]
        self.assertFalse(
            harness._segment_has_japanese_text_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_japanese_text_problem_only_applies_in_translator_mode(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("Map001.json:L0:0", "JP line")
        segment.translation_lines = ["です"]
        self.assertFalse(
            harness._segment_has_japanese_text_problem(
                segment,
                translator_mode=False,
            )
        )

    def test_layout_problem_detects_missing_translation_for_misc_segment(self) -> None:
        harness = _Harness()
        harness.problem_missing_translation_check = _BoolControl(True)
        segment = _dialogue_segment("Map001.json:L0:G:0:text", "JP line")
        segment.segment_kind = "plugin_command_text"
        segment.translation_lines = [""]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[segment],
        )

        self.assertTrue(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )

    def test_missing_translation_problem_ignores_tyrano_r_p_only_source(self) -> None:
        harness = _Harness()
        segment = _dialogue_segment("scene.ks:K:1", "[p][r]")
        segment.segment_kind = "tyrano_dialogue"
        segment.translation_lines = [""]
        self.assertFalse(
            harness._segment_has_missing_translation_problem(
                segment,
                translator_mode=True,
            )
        )

    def test_layout_problem_detects_control_mismatch_for_misc_segment(self) -> None:
        harness = _Harness()
        harness.problem_control_mismatch_check = _BoolControl(True)
        segment = _dialogue_segment("Map001.json:N:abc", r"\C[2]JP line")
        segment.segment_kind = "note_text"
        segment.translation_lines = ["JP line"]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[segment],
        )

        self.assertTrue(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )

    def test_layout_problem_control_mismatch_uses_logical_chain_for_split_translation(self) -> None:
        harness = _Harness()
        harness.problem_control_mismatch_check = _BoolControl(True)
        anchor = _dialogue_segment("Map001.json:L0:0", r"\C[14]Press confirm\C[0]")
        anchor.translation_lines = [r"\C[14]Press confirm"]
        followup = _dialogue_segment("Map001.json:TI:T0001", "")
        followup.translation_only = True
        followup.translation_lines = [r"\C[0]"]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor, followup],
        )
        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            lambda _segment, session=None: [r"\C[14]Press confirm\C[0]"],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_segment",
            lambda _segment, session=None: [r"\C[14]Press confirm", r"\C[0]"],
        )

        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                anchor,
                translator_mode=True,
            )
        )
        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                followup,
                translator_mode=True,
            )
        )

    def test_layout_problem_control_mismatch_prefers_problem_chain_resolver(self) -> None:
        harness = _Harness()
        harness.problem_control_mismatch_check = _BoolControl(True)
        anchor = _dialogue_segment("Map001.json:L0:0", r"\C[2]JP\C[0]")
        anchor.translation_lines = [r"\C[2]JP\C[0]"]
        followup = _dialogue_segment("Map001.json:TI:T0001", "")
        followup.translation_only = True
        followup.translation_lines = [r"\C[2]JP\C[0]"]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor, followup],
        )
        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            lambda _segment, session=None: [r"\C[2]JP\C[0]"],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_segment",
            lambda _segment, session=None: [r"\C[2]JP\C[0]", r"\C[2]JP\C[0]"],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            lambda _segment, session=None: [r"\C[2]JP\C[0]"],
        )

        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                anchor,
                translator_mode=True,
            )
        )
        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                followup,
                translator_mode=True,
            )
        )

    def test_layout_problem_control_mismatch_can_be_ignored_until_content_changes(self) -> None:
        harness = _Harness()
        harness.problem_control_mismatch_check = _BoolControl(True)
        segment = _dialogue_segment("Map001.json:L0:0", r"\C[2]JP\C[0]")
        segment.translation_lines = [r"\C[2]TL"]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[segment],
        )

        self.assertTrue(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )
        self.assertEqual(
            harness._set_control_mismatch_ignored_for_segment(session, segment),
            1,
        )
        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )

        segment.translation_lines = [r"\C[2]TL\C[3]"]
        self.assertTrue(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )

    def test_set_control_mismatch_ignore_can_apply_to_identical_anchors(self) -> None:
        harness = _Harness()
        harness.problem_control_mismatch_check = _BoolControl(True)
        first = _dialogue_segment("Map001.json:L0:0", r"\C[2]JP\C[0]")
        first.translation_lines = [r"\C[2]TL"]
        second = _dialogue_segment("Map002.json:L0:0", r"\C[2]JP\C[0]")
        second.translation_lines = [r"\C[2]TL"]
        path_a = Path("Map001.json")
        path_b = Path("Map002.json")
        session_a = FileSession(path=path_a, data={}, bundles=[], segments=[first])
        session_b = FileSession(path=path_b, data={}, bundles=[], segments=[second])
        setattr(
            harness,
            "sessions",
            {
                path_a: session_a,
                path_b: session_b,
            },
        )

        changed = harness._set_control_mismatch_ignored_for_segment(
            session_a,
            first,
            include_identical=True,
        )

        self.assertEqual(changed, 2)
        self.assertFalse(
            harness._segment_has_layout_problem(
                session_b,
                second,
                translator_mode=True,
            )
        )

    def test_layout_problem_trailing_color_uses_logical_chain_for_split_translation(self) -> None:
        harness = _Harness()
        harness.problem_trailing_color_code_check = _BoolControl(True)
        anchor = _dialogue_segment("Map001.json:L0:0", r"\C[14]Press confirm\C[0]")
        anchor.translation_lines = [r"\C[14]Press confirm"]
        followup = _dialogue_segment("Map001.json:TI:T0001", "")
        followup.translation_only = True
        followup.translation_lines = [r"\C[0]"]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor, followup],
        )
        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            lambda _segment, session=None: [r"\C[14]Press confirm\C[0]"],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_segment",
            lambda _segment, session=None: [r"\C[14]Press confirm", r"\C[0]"],
        )

        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                anchor,
                translator_mode=True,
            )
        )
        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                followup,
                translator_mode=True,
            )
        )

    def test_layout_problem_trailing_color_respects_control_mismatch_ignore(self) -> None:
        harness = _Harness()
        harness.problem_trailing_color_code_check = _BoolControl(True)
        segment = _dialogue_segment("Map001.json:L0:0", r"\C[14]Press\C[0]")
        segment.translation_lines = [r"\C[14]Press"]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[segment],
        )

        self.assertTrue(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )
        self.assertEqual(
            harness._set_control_mismatch_ignored_for_segment(session, segment),
            1,
        )
        self.assertFalse(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )

    def test_layout_problem_detects_japanese_text_for_misc_segment(self) -> None:
        harness = _Harness()
        harness.problem_contains_japanese_check = _BoolControl(True)
        segment = _dialogue_segment("Map001.json:L0:G:1:text", "JP line")
        segment.segment_kind = "plugin_command_text"
        segment.translation_lines = ["これはテストです"]
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[segment],
        )

        self.assertTrue(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )

    def test_layout_problem_detects_tyrano_inline_r_as_line_overflow(self) -> None:
        harness = _Harness()
        harness.problem_line_limit_check = _BoolControl(True)
        harness.max_lines_spin = _SpinControl(1)
        segment = _dialogue_segment("scene.ks:K:2", "JP line")
        segment.segment_kind = "tyrano_dialogue"
        segment.translation_lines = ["Line A[r]Line B"]
        session = FileSession(
            path=Path("scene.ks"),
            data={},
            bundles=[],
            segments=[segment],
        )

        self.assertTrue(
            harness._segment_has_layout_problem(
                session,
                segment,
                translator_mode=True,
            )
        )

    def test_save_all_files_saves_translation_state_once_per_batch(self) -> None:
        harness = _BatchSaveHarness()
        session_a = FileSession(path=Path("A.json"), data={}, bundles=[], segments=[])
        session_b = FileSession(path=Path("B.json"), data={}, bundles=[], segments=[])
        session_c = FileSession(path=Path("C.json"), data={}, bundles=[], segments=[])
        harness.sessions = {
            session_a.path: session_a,
            session_b.path: session_b,
            session_c.path: session_c,
        }
        harness.current_path = session_c.path
        harness._dirty_source_paths = {session_a.path}
        harness._dirty_tl_paths = {session_c.path}

        ok = harness._save_all_files()

        self.assertTrue(ok)
        self.assertEqual(harness.translation_state_calls, [[session_a.path, session_c.path]])
        self.assertEqual(len(harness.save_session_calls), 2)
        self.assertEqual(harness.save_session_calls[0]["path"], session_a.path)
        self.assertFalse(harness.save_session_calls[0]["save_translation_state"])
        self.assertFalse(harness.save_session_calls[0]["show_status_message"])
        self.assertFalse(harness.save_session_calls[0]["refresh_current_view"])
        self.assertEqual(harness.save_session_calls[1]["path"], session_c.path)
        self.assertFalse(harness.save_session_calls[1]["save_translation_state"])
        self.assertFalse(harness.save_session_calls[1]["show_status_message"])
        self.assertTrue(harness.save_session_calls[1]["refresh_current_view"])

    def test_save_all_files_stops_when_batch_translation_state_fails(self) -> None:
        harness = _BatchSaveHarness()
        session_a = FileSession(path=Path("A.json"), data={}, bundles=[], segments=[])
        harness.sessions = {session_a.path: session_a}
        harness._dirty_tl_paths = {session_a.path}
        harness.translation_state_result = False

        ok = harness._save_all_files()

        self.assertFalse(ok)
        self.assertEqual(harness.translation_state_calls, [[session_a.path]])
        self.assertEqual(harness.save_session_calls, [])

    def test_save_session_refreshes_nearby_blocks_for_current_view(self) -> None:
        harness = _SaveSessionHarness()
        session = FileSession(path=Path("A.json"), data={}, bundles=[], segments=[])
        harness.current_path = session.path

        ok = harness._save_session(session, refresh_current_view=True)

        self.assertTrue(ok)
        self.assertEqual(harness.render_session_calls, 0)
        self.assertEqual(harness.rerender_nearby_calls, 1)
        self.assertEqual(harness.refresh_visual_calls, 1)
        self.assertEqual(harness.refresh_detail_calls, 1)

    def test_save_session_persists_linked_actor_alias_targets(self) -> None:
        harness = _ActorAliasSaveHarness()
        actor_path = Path("Actors.json")
        map_path = Path("Map001.json")
        actor_segment = _dialogue_segment("Actors.json:A:1", "Harold")
        alias_segment = _dialogue_segment("Actors.json:A:1:alt_1", "ヒナタ")
        alias_segment.lines = ["Hinata"]
        alias_segment.original_lines = ["ヒナタ"]
        alias_segment.segment_kind = "actor_name_alias"
        setattr(alias_segment, "is_actor_name_alias", True)
        setattr(
            alias_segment,
            "actor_alias_target_refs",
            [(map_path, ("events", 0, "pages", 0, "list", 0, "parameters", 1))],
        )
        actor_session = FileSession(
            path=actor_path,
            data=[{"id": 1, "name": "Harold"}],
            bundles=[],
            segments=[actor_segment, alias_segment],
        )
        setattr(actor_session, "is_name_index_session", True)
        setattr(actor_session, "name_index_uid_prefix", "A")

        map_session = FileSession(
            path=map_path,
            data={
                "events": [
                    {
                        "pages": [
                            {
                                "list": [
                                    {"code": 320, "indent": 0, "parameters": [1, "ヒナタ"]},
                                ]
                            }
                        ]
                    }
                ]
            },
            bundles=[],
            segments=[],
        )

        harness.sessions = {actor_path: actor_session, map_path: map_session}
        harness.current_path = actor_path

        ok = harness._save_session(actor_session, refresh_current_view=False)

        self.assertTrue(ok)
        self.assertEqual(
            map_session.data["events"][0]["pages"][0]["list"][0]["parameters"][1],
            "Hinata",
        )
        self.assertEqual(harness.translation_state_calls, [[actor_path]])
        self.assertEqual(
            [rel_path for rel_path, _data in harness.version_db.working_calls],
            ["Actors.json", "Map001.json"],
        )

    def test_save_session_updates_translated_actor_alias_targets_for_apply(self) -> None:
        harness = _ActorAliasSaveHarness()
        actor_path = Path("Actors.json")
        map_path = Path("Map001.json")
        actor_segment = _dialogue_segment("Actors.json:A:1", "Harold")
        alias_segment = _dialogue_segment("Actors.json:A:1:alt_1", "ヒナタ")
        alias_segment.lines = ["ヒナタ"]
        alias_segment.original_lines = ["ヒナタ"]
        alias_segment.translation_lines = ["Hinata"]
        alias_segment.original_translation_lines = [""]
        alias_segment.segment_kind = "actor_name_alias"
        setattr(alias_segment, "is_actor_name_alias", True)
        setattr(
            alias_segment,
            "actor_alias_target_refs",
            [(map_path, ("events", 0, "pages", 0, "list", 0, "parameters", 1))],
        )
        actor_session = FileSession(
            path=actor_path,
            data=[{"id": 1, "name": "Harold"}],
            bundles=[],
            segments=[actor_segment, alias_segment],
        )
        setattr(actor_session, "is_name_index_session", True)
        setattr(actor_session, "name_index_uid_prefix", "A")

        map_session = FileSession(
            path=map_path,
            data={
                "events": [
                    {
                        "pages": [
                            {
                                "list": [
                                    {"code": 320, "indent": 0, "parameters": [1, "ヒナタ"]},
                                ]
                            }
                        ]
                    }
                ]
            },
            bundles=[],
            segments=[],
        )

        harness.sessions = {actor_path: actor_session, map_path: map_session}

        ok = harness._save_session(actor_session, refresh_current_view=False)

        self.assertTrue(ok)
        # Translation-only alias edits should not mutate in-memory source JSON.
        self.assertEqual(
            map_session.data["events"][0]["pages"][0]["list"][0]["parameters"][1],
            "ヒナタ",
        )
        self.assertEqual(
            [rel_path for rel_path, _data in harness.version_db.working_calls],
            [],
        )
        translated_by_path = {
            rel_path: data
            for rel_path, data, _profile_id in harness.version_db.translated_calls
        }
        self.assertIn("Map001.json", translated_by_path)
        self.assertEqual(
            translated_by_path["Map001.json"]["events"][0]["pages"][0]["list"][0]["parameters"][1],
            "Hinata",
        )

    def test_save_session_updates_translated_actor_alias_targets_when_target_path_is_relative(
        self,
    ) -> None:
        harness = _ActorAliasSaveHarness()
        actor_path = Path("Actors.json").resolve()
        map_path = Path("Map001.json").resolve()
        actor_segment = _dialogue_segment("Actors.json:A:1", "Harold")
        alias_segment = _dialogue_segment("Actors.json:A:1:alt_1", "ヒナタ")
        alias_segment.lines = ["ヒナタ"]
        alias_segment.original_lines = ["ヒナタ"]
        alias_segment.translation_lines = ["Hinata"]
        alias_segment.original_translation_lines = [""]
        alias_segment.segment_kind = "actor_name_alias"
        setattr(alias_segment, "is_actor_name_alias", True)
        setattr(
            alias_segment,
            "actor_alias_target_refs",
            [(Path("Map001.json"), ("events", 0, "pages", 0, "list", 0, "parameters", 1))],
        )
        actor_session = FileSession(
            path=actor_path,
            data=[{"id": 1, "name": "Harold"}],
            bundles=[],
            segments=[actor_segment, alias_segment],
        )
        setattr(actor_session, "is_name_index_session", True)
        setattr(actor_session, "name_index_uid_prefix", "A")

        map_session = FileSession(
            path=map_path,
            data={
                "events": [
                    {
                        "pages": [
                            {
                                "list": [
                                    {"code": 320, "indent": 0, "parameters": [1, "ヒナタ"]},
                                ]
                            }
                        ]
                    }
                ]
            },
            bundles=[],
            segments=[],
        )

        harness.sessions = {actor_path: actor_session, map_path: map_session}

        ok = harness._save_session(actor_session, refresh_current_view=False)

        self.assertTrue(ok)
        translated_by_path = {
            rel_path: data
            for rel_path, data, _profile_id in harness.version_db.translated_calls
        }
        self.assertIn("Map001.json", translated_by_path)
        self.assertEqual(
            translated_by_path["Map001.json"]["events"][0]["pages"][0]["list"][0]["parameters"][1],
            "Hinata",
        )

    def test_refresh_translated_snapshots_from_loaded_sessions_applies_actor_name_and_alias(
        self,
    ) -> None:
        harness = _ActorAliasSaveHarness()
        actor_path = Path("Actors.json")
        map_path = Path("Map001.json")
        actor_segment = _dialogue_segment("Actors.json:A:1", "ヒナタ")
        actor_segment.translation_lines = ["Hinata"]
        actor_segment.original_translation_lines = [""]

        alias_main_segment = _dialogue_segment("Actors.json:A:1:alt_1", "ヒナタ")
        alias_main_segment.lines = ["ヒナタ"]
        alias_main_segment.original_lines = ["ヒナタ"]
        alias_main_segment.translation_lines = [""]
        alias_main_segment.original_translation_lines = [""]
        alias_main_segment.segment_kind = "actor_name_alias"
        setattr(alias_main_segment, "is_actor_name_alias", True)
        setattr(alias_main_segment, "actor_alias_actor_id", 1)
        setattr(
            alias_main_segment,
            "actor_alias_target_refs",
            [(map_path, ("events", 0, "pages", 0, "list", 0, "parameters", 1))],
        )

        alias_nickname_segment = _dialogue_segment("Actors.json:A:1:alt_2", "ひな")
        alias_nickname_segment.lines = ["ひな"]
        alias_nickname_segment.original_lines = ["ひな"]
        alias_nickname_segment.translation_lines = ["Hina"]
        alias_nickname_segment.original_translation_lines = [""]
        alias_nickname_segment.segment_kind = "actor_name_alias"
        setattr(alias_nickname_segment, "is_actor_name_alias", True)
        setattr(alias_nickname_segment, "actor_alias_actor_id", 1)
        setattr(
            alias_nickname_segment,
            "actor_alias_target_refs",
            [(map_path, ("events", 0, "pages", 0, "list", 1, "parameters", 1))],
        )

        actor_session = FileSession(
            path=actor_path,
            data=[{"id": 1, "name": "ヒナタ"}],
            bundles=[],
            segments=[actor_segment, alias_main_segment, alias_nickname_segment],
        )
        setattr(actor_session, "is_name_index_session", True)
        setattr(actor_session, "name_index_uid_prefix", "A")

        map_session = FileSession(
            path=map_path,
            data={
                "events": [
                    {
                        "pages": [
                            {
                                "list": [
                                    {"code": 320, "indent": 0, "parameters": [1, "ヒナタ"]},
                                    {"code": 320, "indent": 0, "parameters": [1, "ひな"]},
                                ]
                            }
                        ]
                    }
                ]
            },
            bundles=[],
            segments=[],
        )

        harness.sessions = {actor_path: actor_session, map_path: map_session}

        saved_count = harness._refresh_translated_snapshots_from_loaded_sessions(
            profile_id="default"
        )

        self.assertEqual(saved_count, 2)
        translated_by_path = {
            rel_path: data
            for rel_path, data, _profile_id in harness.version_db.translated_calls
        }
        self.assertIn("Map001.json", translated_by_path)
        self.assertEqual(
            translated_by_path["Map001.json"]["events"][0]["pages"][0]["list"][0]["parameters"][1],
            "Hinata",
        )
        self.assertEqual(
            translated_by_path["Map001.json"]["events"][0]["pages"][0]["list"][1]["parameters"][1],
            "Hina",
        )

    def test_refresh_translated_snapshots_updates_map_commands_without_target_refs(
        self,
    ) -> None:
        harness = _ActorAliasSaveHarness()
        actor_path = Path("Actors.json")
        common_path = Path("CommonEvents.json")
        map_path = Path("Map002.json")

        actor_segment = _dialogue_segment("Actors.json:A:1", "ヒナタ")
        actor_segment.translation_lines = ["Hinata"]
        actor_segment.original_translation_lines = [""]

        alias_segment = _dialogue_segment("Actors.json:A:1:alt_1", "ひな")
        alias_segment.lines = ["ひな"]
        alias_segment.original_lines = ["ひな"]
        alias_segment.translation_lines = ["Hina"]
        alias_segment.original_translation_lines = [""]
        alias_segment.segment_kind = "actor_name_alias"
        setattr(alias_segment, "is_actor_name_alias", True)
        setattr(alias_segment, "actor_alias_actor_id", 1)
        # Intentionally omit actor_alias_target_refs to verify global code320 mapping path.
        setattr(alias_segment, "actor_alias_target_refs", [])

        actor_session = FileSession(
            path=actor_path,
            data=[{"id": 1, "name": "ヒナタ"}],
            bundles=[],
            segments=[actor_segment, alias_segment],
        )
        setattr(actor_session, "is_name_index_session", True)
        setattr(actor_session, "name_index_uid_prefix", "A")

        common_session = FileSession(
            path=common_path,
            data={
                "list": [
                    {"code": 320, "indent": 0, "parameters": [1, "ヒナタ"]},
                ]
            },
            bundles=[],
            segments=[],
        )
        map_session = FileSession(
            path=map_path,
            data={
                "events": [
                    {
                        "pages": [
                            {
                                "list": [
                                    {"code": 320, "indent": 0, "parameters": [1, "ヒナタ"]},
                                    {"code": 320, "indent": 0, "parameters": [1, "ひな"]},
                                ]
                            }
                        ]
                    }
                ]
            },
            bundles=[],
            segments=[],
        )

        harness.sessions = {
            actor_path: actor_session,
            common_path: common_session,
            map_path: map_session,
        }

        saved_count = harness._refresh_translated_snapshots_from_loaded_sessions(
            profile_id="default"
        )

        self.assertEqual(saved_count, 3)
        translated_by_path = {
            rel_path: data
            for rel_path, data, _profile_id in harness.version_db.translated_calls
        }
        self.assertEqual(
            translated_by_path["CommonEvents.json"]["list"][0]["parameters"][1],
            "Hinata",
        )
        self.assertEqual(
            translated_by_path["Map002.json"]["events"][0]["pages"][0]["list"][0]["parameters"][1],
            "Hinata",
        )
        self.assertEqual(
            translated_by_path["Map002.json"]["events"][0]["pages"][0]["list"][1]["parameters"][1],
            "Hina",
        )

    def test_reset_current_file_in_translator_mode_avoids_full_rerender(self) -> None:
        harness = _ResetCurrentFileHarness()
        segment = _dialogue_segment("A:1", "line")
        segment.translation_lines = ["changed"]
        segment.original_translation_lines = ["orig"]
        segment.translation_speaker = "new"
        segment.original_translation_speaker = "old"
        segment.disable_line1_speaker_inference = True
        segment.original_disable_line1_speaker_inference = False
        segment.force_line1_speaker_inference = False
        segment.original_force_line1_speaker_inference = True
        session = FileSession(path=Path("A.json"), data={}, bundles=[], segments=[segment])
        harness.current_path = session.path
        harness.sessions[session.path] = session

        with patch(
            "dialogue_visual_editor.helpers.mixins.persistence_export_mixin.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            harness._on_reset_current_file_requested()

        self.assertEqual(segment.translation_lines, ["orig"])
        self.assertEqual(segment.translation_speaker, "old")
        self.assertFalse(segment.disable_line1_speaker_inference)
        self.assertTrue(segment.force_line1_speaker_inference)
        self.assertEqual(harness.refresh_dirty_calls, 1)
        self.assertEqual(harness.rerender_nearby_calls, 1)
        self.assertEqual(harness.render_session_calls, 0)

    def test_update_file_item_text_scopes_problem_badges_for_mixed_session(self) -> None:
        harness = _ScopedWarningBadgeHarness()
        path = Path("Troops.json")
        dialogue = _dialogue_segment("Troops.json:L0:0", "Too long")
        misc = _dialogue_segment("Troops.json:P:1", "Troop A")
        misc.segment_kind = "name_index"
        session = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[dialogue, misc],
        )
        harness.sessions[path] = session
        dialogue_item = _ListItemHarness()
        misc_item = _ListItemHarness()
        harness.file_items[path] = dialogue_item
        harness.file_items_scoped[(path, "dialogue")] = dialogue_item
        harness.file_items_scoped[(path, "misc")] = misc_item

        harness._update_file_item_text(path)

        self.assertIn("Troops (", dialogue_item.text)
        self.assertIn("Troops (", misc_item.text)
        self.assertNotIn(".json", dialogue_item.text)
        self.assertNotIn(".json", misc_item.text)
        self.assertIn("[!1]", dialogue_item.text)
        self.assertNotIn("[!1]", misc_item.text)


if __name__ == "__main__":
    unittest.main()
