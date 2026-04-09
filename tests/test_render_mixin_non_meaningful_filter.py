from __future__ import annotations

import unittest
from pathlib import Path

from helpers.core.models import DialogueSegment, FileSession
from helpers.mixins.render_mixin import RenderMixin


class _CheckBoxStub:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _Harness(RenderMixin):
    def __init__(self, *, hide_non_meaningful: bool) -> None:
        self.hide_non_meaningful_entries_check = _CheckBoxStub(hide_non_meaningful)
        self.block_widgets: dict[str, object] = {}
        self._pagination_page_by_scope_key: dict[tuple[Path, str], int] = {}
        self.selected_segment_uid: str | None = None
        self._page_size = 50

    @staticmethod
    def _is_actor_index_session(session: FileSession) -> bool:
        return bool(getattr(session, "is_actor_index_session", False))

    @staticmethod
    def _normalized_view_scope_for_path(
        _path: Path,
        _session: FileSession,
        requested_scope: str | None = None,
    ) -> str:
        if isinstance(requested_scope, str) and requested_scope.strip().lower() == "misc":
            return "misc"
        return "dialogue"

    @staticmethod
    def _name_index_field_from_uid(uid: str) -> str:
        if ":" not in uid:
            return "name"
        tail = uid.rsplit(":", 1)[-1]
        if tail.isdigit():
            return "name"
        return tail

    def _pagination_page_size(self) -> int:
        return int(self._page_size)


def _segment(
    uid: str,
    text: str,
    *,
    segment_kind: str = "dialogue",
    translation_only: bool = False,
) -> DialogueSegment:
    lines = text.split("\n") if text else [""]
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(lines),
        original_lines=list(lines),
        source_lines=list(lines),
        segment_kind=segment_kind,
        translation_only=translation_only,
    )


def _session_with_segments(segments: list[DialogueSegment]) -> FileSession:
    return FileSession(
        path=Path("plugins.js"),
        data=[],
        bundles=[],
        segments=segments,
    )


class RenderMixinNonMeaningfulFilterTests(unittest.TestCase):
    def test_refresh_block_width_constraints_calls_widget_width_apply_hook(self) -> None:
        class _WidthAwareWidget:
            def __init__(self) -> None:
                self.calls = 0

            def _apply_editor_width(self) -> None:
                self.calls += 1

        harness = _Harness(hide_non_meaningful=False)
        target = _WidthAwareWidget()
        harness.block_widgets = {"a": target, "b": object()}

        harness._refresh_block_width_constraints()

        self.assertEqual(target.calls, 1)

    def test_toggle_off_keeps_map_and_plugin_parameter_entries(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        map_empty = _segment("map", "", segment_kind="map_display_name")
        plugin_bool = _segment("pbool", "true", segment_kind="plugin_text")
        setattr(plugin_bool, "plugin_text_path", ("plugins", 0, "parameters", "enabled"))
        plugin_int = _segment("pint", "0", segment_kind="plugin_text")
        setattr(plugin_int, "plugin_text_path", ("plugins", 0, "parameters", "count"))
        plugin_text = _segment("ptext", "Hello", segment_kind="plugin_text")
        setattr(plugin_text, "plugin_text_path", ("plugins", 0, "parameters", "label"))
        translation_only = _segment("tl", "TL only", translation_only=True)
        session = _session_with_segments(
            [map_empty, plugin_bool, plugin_int, plugin_text, translation_only]
        )

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=False,
        )

        self.assertEqual(
            [segment.uid for segment in display],
            ["map", "pbool", "pint", "ptext"],
        )

    def test_toggle_on_hides_empty_map_and_non_meaningful_plugin_parameters(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        map_empty = _segment("map_empty", "", segment_kind="map_display_name")
        map_non_empty = _segment("map_non_empty", "Village", segment_kind="map_display_name")
        map_codes_only = _segment("map_codes_only", "\\C[3]", segment_kind="map_display_name")
        plugin_bool = _segment("pbool", "false", segment_kind="plugin_text")
        setattr(plugin_bool, "plugin_text_path", ("plugins", 0, "parameters", "enabled"))
        plugin_int = _segment("pint", "-2", segment_kind="plugin_text")
        setattr(plugin_int, "plugin_text_path", ("plugins", 0, "parameters", "index"))
        plugin_on = _segment("pon", "ON", segment_kind="plugin_text")
        setattr(plugin_on, "plugin_text_path", ("plugins", 0, "parameters", "switch"))
        plugin_float = _segment("pfloat", "3.25", segment_kind="plugin_text")
        setattr(plugin_float, "plugin_text_path", ("plugins", 0, "parameters", "ratio"))
        plugin_number_list = _segment("plist", "[1, 2, 3.5]", segment_kind="plugin_text")
        setattr(plugin_number_list, "plugin_text_path", ("plugins", 0, "parameters", "weights"))
        plugin_none = _segment("pnone", "None", segment_kind="plugin_text")
        setattr(plugin_none, "plugin_text_path", ("plugins", 0, "parameters", "fallback"))
        plugin_label = _segment("plabel", "Hello", segment_kind="plugin_text")
        setattr(plugin_label, "plugin_text_path", ("plugins", 0, "parameters", "label"))
        plugin_description = _segment("pdesc", "Main plugin", segment_kind="plugin_text")
        setattr(plugin_description, "plugin_text_path", ("plugins", 0, "description"))
        session = _session_with_segments(
            [
                map_empty,
                map_non_empty,
                map_codes_only,
                plugin_bool,
                plugin_int,
                plugin_on,
                plugin_float,
                plugin_number_list,
                plugin_none,
                plugin_label,
                plugin_description,
            ]
        )

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=False,
        )

        self.assertEqual(
            [segment.uid for segment in display],
            ["map_non_empty", "plabel", "pdesc"],
        )

    def test_translator_mode_still_includes_translation_only_when_meaningful(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        translation_only = _segment("tl", "Translated text", translation_only=True)
        session = _session_with_segments([translation_only])

        display = harness._display_segments_for_session(
            session,
            translator_mode=True,
            actor_mode=False,
        )

        self.assertEqual([segment.uid for segment in display], ["tl"])

    def test_actor_session_hides_empty_and_duplicate_entries(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        s1 = _segment("Actors.json:A:1", "Harold", segment_kind="name_index")
        s2 = _segment("Actors.json:A:2", "Harold", segment_kind="name_index")
        s3 = _segment("Actors.json:A:3", "", segment_kind="name_index")
        s4 = _segment("Actors.json:A:4", "\\C[2]", segment_kind="name_index")
        s5 = _segment("Actors.json:A:5", "Therese", segment_kind="name_index")
        session = _session_with_segments([s1, s2, s3, s4, s5])
        setattr(session, "is_actor_index_session", True)

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=True,
        )

        self.assertEqual([segment.uid for segment in display], ["Actors.json:A:1", "Actors.json:A:5"])

    def test_actor_session_keeps_non_name_fields_even_when_text_repeats(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        name_a = _segment("Actors.json:A:1", "Harold", segment_kind="name_index")
        name_b = _segment("Actors.json:A:2", "Harold", segment_kind="name_index")
        profile_a = _segment("Actors.json:A:1:profile", "Harpy", segment_kind="name_index")
        profile_b = _segment("Actors.json:A:2:profile", "Harpy", segment_kind="name_index")
        session = _session_with_segments([name_a, name_b, profile_a, profile_b])
        setattr(session, "is_actor_index_session", True)

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=True,
        )

        self.assertEqual(
            [segment.uid for segment in display],
            ["Actors.json:A:1", "Actors.json:A:1:profile", "Actors.json:A:2:profile"],
        )

    def test_non_actor_name_index_session_keeps_duplicate_and_empty_entries(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        s1 = _segment("Items.json:I:1", "Potion", segment_kind="name_index")
        s2 = _segment("Items.json:I:2", "Potion", segment_kind="name_index")
        s3 = _segment("Items.json:I:3", "", segment_kind="name_index")
        session = _session_with_segments([s1, s2, s3])
        setattr(session, "is_actor_index_session", False)
        setattr(session, "name_index_kind", "item")

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=True,
        )

        self.assertEqual([segment.uid for segment in display], ["Items.json:I:1", "Items.json:I:2", "Items.json:I:3"])

    def test_mixed_dialogue_and_misc_session_filters_by_actor_mode(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        dialogue = _segment("Troops.json:L0:0", "Hello", segment_kind="dialogue")
        misc = _segment("Troops.json:P:1", "Troop A", segment_kind="name_index")
        session = _session_with_segments([dialogue, misc])
        setattr(session, "has_mixed_dialogue_misc_segments", True)

        dialogue_view = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=False,
        )
        misc_view = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=True,
        )

        self.assertEqual([segment.uid for segment in dialogue_view], ["Troops.json:L0:0"])
        self.assertEqual([segment.uid for segment in misc_view], ["Troops.json:P:1"])

    def test_mixed_dialogue_and_misc_session_filters_without_mixed_flag(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        dialogue = _segment("Troops.json:L0:0", "Hello", segment_kind="dialogue")
        misc = _segment("Troops.json:P:1", "Troop A", segment_kind="name_index")
        session = _session_with_segments([dialogue, misc])

        dialogue_view = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=False,
        )
        misc_view = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=True,
        )

        self.assertEqual([segment.uid for segment in dialogue_view], ["Troops.json:L0:0"])
        self.assertEqual([segment.uid for segment in misc_view], ["Troops.json:P:1"])

    def test_tyrano_mixed_dialogue_and_misc_filters_without_mixed_flag(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        dialogue = _segment("scene1.ks:K:1", "こんにちは", segment_kind="tyrano_dialogue")
        misc = _segment("scene1.ks:KT:1", "選択肢", segment_kind="tyrano_tag_text")
        session = _session_with_segments([dialogue, misc])

        dialogue_view = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=False,
        )
        misc_view = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=True,
        )

        self.assertEqual([segment.uid for segment in dialogue_view], ["scene1.ks:K:1"])
        self.assertEqual([segment.uid for segment in misc_view], ["scene1.ks:KT:1"])

    def test_toggle_on_hides_non_meaningful_plugin_command_parameters(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        numeric_arg = _segment("pc_num", "24", segment_kind="plugin_command_text")
        setattr(
            numeric_arg,
            "plugin_command_text_path",
            ("events", 0, "pages", 0, "list", 0, "parameters", 3, "fontSize"),
        )
        text_arg = _segment("pc_text", "メイドレベル", segment_kind="plugin_command_text")
        setattr(
            text_arg,
            "plugin_command_text_path",
            ("events", 0, "pages", 0, "list", 0, "parameters", 3, "text"),
        )
        session = _session_with_segments([numeric_arg, text_arg])

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=True,
        )

        self.assertEqual([segment.uid for segment in display], ["pc_text"])

    def test_toggle_on_hides_alphanumeric_tyrano_script_string_segments(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        script_id = _segment("scene.ks:KS:1", "SAVE1", segment_kind="tyrano_tag_text")
        setattr(script_id, "tyrano_tag_text_join_mode", "script_string")
        script_words = _segment("scene.ks:KS:2", "MAIN MENU 2", segment_kind="tyrano_tag_text")
        setattr(script_words, "tyrano_tag_text_join_mode", "script_string")
        script_path = _segment("scene.ks:KS:3", "opening.ks", segment_kind="tyrano_tag_text")
        setattr(script_path, "tyrano_tag_text_join_mode", "script_string")
        script_jp = _segment("scene.ks:KS:4", "回想モード", segment_kind="tyrano_tag_text")
        setattr(script_jp, "tyrano_tag_text_join_mode", "script_string")
        session = _session_with_segments([script_id, script_words, script_path, script_jp])

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=False,
        )

        self.assertEqual([segment.uid for segment in display], ["scene.ks:KS:3", "scene.ks:KS:4"])

    def test_toggle_off_keeps_alphanumeric_tyrano_script_string_segments(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        script_id = _segment("scene.ks:KS:1", "SAVE1", segment_kind="tyrano_tag_text")
        setattr(script_id, "tyrano_tag_text_join_mode", "script_string")
        script_words = _segment("scene.ks:KS:2", "MAIN MENU 2", segment_kind="tyrano_tag_text")
        setattr(script_words, "tyrano_tag_text_join_mode", "script_string")
        session = _session_with_segments([script_id, script_words])

        display = harness._display_segments_for_session(
            session,
            translator_mode=False,
            actor_mode=False,
        )

        self.assertEqual([segment.uid for segment in display], ["scene.ks:KS:1", "scene.ks:KS:2"])

    def test_translation_state_entry_filter_respects_toggle_for_plugin_parameters(self) -> None:
        entry = {
            "source_uid": "plugins.js:J:3:param_1_enabled",
            "source_preview": "true",
        }
        harness_off = _Harness(hide_non_meaningful=False)
        harness_on = _Harness(hide_non_meaningful=True)

        self.assertTrue(harness_off._translation_state_entry_is_meaningful_for_display(entry))
        self.assertFalse(harness_on._translation_state_entry_is_meaningful_for_display(entry))

    def test_translation_state_entry_filter_hides_on_float_and_number_lists(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        entries = [
            {"source_uid": "plugins.js:J:1:param_1_mode", "source_preview": "off"},
            {"source_uid": "plugins.js:J:1:param_2_ratio", "source_preview": "0.75"},
            {"source_uid": "plugins.js:J:1:param_3_steps", "source_preview": "1, 2, 3"},
            {"source_uid": "plugins.js:J:1:param_4_fallback", "source_preview": "none"},
        ]

        for entry in entries:
            self.assertFalse(
                harness._translation_state_entry_is_meaningful_for_display(entry)
            )

    def test_translation_state_entry_filter_keeps_plugin_text_and_drops_empty_source(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        plugin_text_entry = {
            "source_uid": "plugins.js:J:3:param_2_label",
            "source_preview": "Boss Name",
        }
        empty_entry = {
            "source_uid": "Map001.json:map_display_name",
            "source_preview": "",
        }

        self.assertTrue(
            harness._translation_state_entry_is_meaningful_for_display(plugin_text_entry)
        )
        self.assertFalse(
            harness._translation_state_entry_is_meaningful_for_display(empty_entry)
        )

    def test_translation_state_entry_filter_hides_alphanumeric_tyrano_script_string_entries(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        hidden_entry = {
            "source_uid": "scene.ks:KS:7",
            "source_preview": "MAIN MENU 2",
        }
        visible_entry = {
            "source_uid": "scene.ks:KS:8",
            "source_preview": "回想モード",
        }

        self.assertFalse(
            harness._translation_state_entry_is_meaningful_for_display(hidden_entry)
        )
        self.assertTrue(
            harness._translation_state_entry_is_meaningful_for_display(visible_entry)
        )

    def test_plugin_group_key_and_title_detected_for_plugin_text_segment(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        segment = _segment("pdesc", "Main plugin", segment_kind="plugin_text")
        segment.code101["parameters"] = ["", 0, 0, 2, "QuestCore"]
        setattr(
            segment,
            "plugin_text_path",
            ("__dve_plugins_js_array__", 2, "description"),
        )

        info = harness._plugin_group_key_and_title_for_segment(
            Path("js/plugins.js"),
            segment,
        )

        self.assertIsNotNone(info)
        assert info is not None
        group_key, title = info
        self.assertEqual(group_key, "js/plugins.js::plugin::2")
        self.assertEqual(title, "Plugin 3: QuestCore")

    def test_plugin_group_key_not_created_for_non_plugin_segment(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        segment = _segment("d1", "Hello", segment_kind="dialogue")

        info = harness._plugin_group_key_and_title_for_segment(
            Path("Map001.json"),
            segment,
        )

        self.assertIsNone(info)

    def test_plugin_group_collapsed_state_can_toggle_without_name_collision(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        key = "js/plugins.js::plugin::0"

        self.assertTrue(harness._is_plugin_group_collapsed(key))
        harness._set_plugin_group_collapsed(key, True)
        self.assertTrue(harness._is_plugin_group_collapsed(key))
        harness._set_plugin_group_collapsed(key, False)
        self.assertFalse(harness._is_plugin_group_collapsed(key))

    def test_plugin_group_description_hint_uses_description_segment(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        segment = _segment(
            "pdesc",
            "Main plugin for quest flow management.",
            segment_kind="plugin_text",
        )
        setattr(
            segment,
            "plugin_text_path",
            ("__dve_plugins_js_array__", 0, "description"),
        )

        hint = harness._plugin_group_description_hint_for_segment(
            segment,
            translator_mode=False,
        )

        self.assertEqual(hint, "Main plugin for quest flow management.")

    def test_plugin_group_description_hint_is_none_for_non_description_field(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        segment = _segment("p1", "true", segment_kind="plugin_text")
        setattr(
            segment,
            "plugin_text_path",
            ("__dve_plugins_js_array__", 0, "parameters", "enabled"),
        )

        hint = harness._plugin_group_description_hint_for_segment(
            segment,
            translator_mode=False,
        )

        self.assertIsNone(hint)

    def test_plugin_group_description_hint_prefers_translation_in_translator_mode(self) -> None:
        harness = _Harness(hide_non_meaningful=True)
        segment = _segment("pdesc", "JP source", segment_kind="plugin_text")
        setattr(
            segment,
            "plugin_text_path",
            ("__dve_plugins_js_array__", 0, "description"),
        )
        segment.translation_lines = ["EN translated description"]

        hint = harness._plugin_group_description_hint_for_segment(
            segment,
            translator_mode=True,
        )

        self.assertEqual(hint, "EN translated description")

    def test_paginate_segments_uses_default_first_page(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        segments = [_segment(f"Map001:{idx}", f"line {idx}") for idx in range(1, 121)]
        session = _session_with_segments(segments)

        paged, state = harness._paginate_segments_for_render(
            session,
            segments,
            actor_mode=False,
            focus_uid=None,
        )

        self.assertEqual(len(paged), 50)
        self.assertEqual(paged[0].uid, "Map001:1")
        self.assertEqual(paged[-1].uid, "Map001:50")
        self.assertEqual(state["current_page"], 1)
        self.assertEqual(state["total_pages"], 3)

    def test_display_block_numbers_keep_translation_only_followups_on_anchor_number(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        segments = [
            _segment("Map001:1", "A1"),
            _segment("Map001:1:f1", "A1-f1", translation_only=True),
            _segment("Map001:1:f2", "A1-f2", translation_only=True),
            _segment("map_name", "Town", segment_kind="map_display_name"),
            _segment("Map001:2", "A2"),
            _segment("Map001:2:f1", "A2-f1", translation_only=True),
        ]

        numbers = harness._display_block_numbers(segments, actor_mode=False)

        self.assertEqual(numbers["Map001:1"], 1)
        self.assertEqual(numbers["Map001:1:f1"], 1)
        self.assertEqual(numbers["Map001:1:f2"], 1)
        self.assertEqual(numbers["map_name"], 0)
        self.assertEqual(numbers["Map001:2"], 2)
        self.assertEqual(numbers["Map001:2:f1"], 2)

    def test_display_block_count_aligns_with_anchor_numbering(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        segments = [
            _segment("Map001:1", "A1"),
            _segment("Map001:1:f1", "A1-f1", translation_only=True),
            _segment("Map001:2", "A2"),
            _segment("Map001:2:f1", "A2-f1", translation_only=True),
            _segment("map_name", "Town", segment_kind="map_display_name"),
        ]

        count = harness._display_block_count(segments, actor_mode=False)

        self.assertEqual(count, 2)

    def test_display_entry_indices_count_each_followup(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        segments = [
            _segment("Map001:1", "A1"),
            _segment("Map001:1:f1", "A1-f1", translation_only=True),
            _segment("map_name", "Town", segment_kind="map_display_name"),
            _segment("Map001:2", "A2"),
            _segment("Map001:2:f1", "A2-f1", translation_only=True),
        ]

        indices = harness._display_entry_indices(segments, actor_mode=False)

        self.assertEqual(indices["Map001:1"], 1)
        self.assertEqual(indices["Map001:1:f1"], 2)
        self.assertEqual(indices["map_name"], 0)
        self.assertEqual(indices["Map001:2"], 3)
        self.assertEqual(indices["Map001:2:f1"], 4)

    def test_paginate_segments_selects_page_for_focus_uid(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        segments = [_segment(f"Map001:{idx}", f"line {idx}") for idx in range(1, 121)]
        session = _session_with_segments(segments)

        paged, state = harness._paginate_segments_for_render(
            session,
            segments,
            actor_mode=False,
            focus_uid="Map001:115",
        )

        self.assertEqual(state["current_page"], 3)
        self.assertEqual(len(paged), 20)
        self.assertEqual(paged[0].uid, "Map001:101")
        self.assertEqual(paged[-1].uid, "Map001:120")

    def test_paginate_segments_uses_selected_uid_when_focus_uid_missing(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        segments = [_segment(f"Map001:{idx}", f"line {idx}") for idx in range(1, 121)]
        session = _session_with_segments(segments)
        harness.selected_segment_uid = "Map001:79"

        paged, state = harness._paginate_segments_for_render(
            session,
            segments,
            actor_mode=False,
            focus_uid=None,
        )

        self.assertEqual(state["current_page"], 2)
        self.assertEqual(paged[0].uid, "Map001:51")
        self.assertEqual(paged[-1].uid, "Map001:100")

    def test_paginate_segments_keeps_translation_only_followups_with_anchor(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        harness._page_size = 2
        segments = [
            _segment("Map001:1", "A1"),
            _segment("Map001:1:f1", "A1-f1", translation_only=True),
            _segment("Map001:2", "A2"),
            _segment("Map001:2:f1", "A2-f1", translation_only=True),
            _segment("Map001:3", "A3"),
        ]
        session = _session_with_segments(segments)

        paged, state = harness._paginate_segments_for_render(
            session,
            segments,
            actor_mode=False,
            focus_uid=None,
        )

        self.assertEqual(state["current_page"], 1)
        self.assertEqual(state["total_pages"], 2)
        self.assertEqual(state["total_entries"], 3)
        self.assertEqual(state["page_start_index"], 1)
        self.assertEqual(state["page_end_index"], 2)
        self.assertEqual(
            [segment.uid for segment in paged],
            ["Map001:1", "Map001:1:f1", "Map001:2", "Map001:2:f1"],
        )

    def test_paginate_segments_focus_followup_uses_anchor_page(self) -> None:
        harness = _Harness(hide_non_meaningful=False)
        harness._page_size = 1
        segments = [
            _segment("Map001:1", "A1"),
            _segment("Map001:1:f1", "A1-f1", translation_only=True),
            _segment("Map001:2", "A2"),
            _segment("Map001:2:f1", "A2-f1", translation_only=True),
            _segment("Map001:3", "A3"),
        ]
        session = _session_with_segments(segments)

        paged, state = harness._paginate_segments_for_render(
            session,
            segments,
            actor_mode=False,
            focus_uid="Map001:2:f1",
        )

        self.assertEqual(state["current_page"], 2)
        self.assertEqual(
            [segment.uid for segment in paged],
            ["Map001:2", "Map001:2:f1"],
        )


if __name__ == "__main__":
    unittest.main()
