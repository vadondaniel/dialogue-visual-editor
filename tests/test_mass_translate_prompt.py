from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from helpers.core.models import DialogueSegment, FileSession
from helpers.ui.mass_translate_dialog import (
    MassTranslateDialog,
)


class _EditorPromptMeta:
    def __init__(
        self,
        *,
        source_language_code: str = "ja",
        target_language_code: str = "en",
        prompt_template: str = "",
    ) -> None:
        self._source_language_code = source_language_code
        self._target_language_code = target_language_code
        self._prompt_template = prompt_template

    def _translation_project_source_language_code(self) -> str:
        return self._source_language_code

    def _translation_profile_target_language_code(
        self,
        profile_id: str | None = None,
    ) -> str:
        _ = profile_id
        return self._target_language_code

    def _translation_profile_prompt_template(
        self,
        profile_id: str | None = None,
    ) -> str:
        _ = profile_id
        return self._prompt_template


class _PromptDialogHarness:
    _NAME_TOKEN_RE = MassTranslateDialog._NAME_TOKEN_RE
    _default_prompt_template = classmethod(MassTranslateDialog._default_prompt_template.__func__)
    _normalize_prompt_language_code = staticmethod(
        MassTranslateDialog._normalize_prompt_language_code
    )
    _language_field_prefix = staticmethod(MassTranslateDialog._language_field_prefix)
    _source_text_field_name = MassTranslateDialog._source_text_field_name
    _target_translation_field_name = MassTranslateDialog._target_translation_field_name
    _translation_prompt_metadata = MassTranslateDialog._translation_prompt_metadata
    _build_prompt_for_payload = MassTranslateDialog._build_prompt_for_payload
    _speaker_display_for_prompt = MassTranslateDialog._speaker_display_for_prompt
    _resolve_name_tokens_for_prompt = MassTranslateDialog._resolve_name_tokens_for_prompt
    _actor_source_name_map_for_prompt = MassTranslateDialog._actor_source_name_map_for_prompt
    _persistent_speaker_key_for_segment = (
        MassTranslateDialog._persistent_speaker_key_for_segment
    )
    _segment_content_type = MassTranslateDialog._segment_content_type
    _segments_for_session_mass_translate = (
        MassTranslateDialog._segments_for_session_mass_translate
    )

    def __init__(self, editor: Any) -> None:
        self.editor = editor


class _SpeakerDisplayEditorMeta:
    def __init__(self) -> None:
        self._translated_by_key: dict[str, str] = {}
        self._resolved_by_key: dict[str, str] = {}
        self.sessions: dict[Path, Any] = {}

    @staticmethod
    def _normalize_speaker_key(value: str) -> str:
        cleaned = value.strip()
        return cleaned if cleaned else ""

    def _speaker_translation_for_key(self, speaker_key: str) -> str:
        return self._translated_by_key.get(speaker_key, "")

    def _resolve_name_tokens_in_text(
        self,
        text: str,
        prefer_translated: bool,
        unresolved_placeholder: bool = False,
    ) -> str:
        _ = prefer_translated
        _ = unresolved_placeholder
        return self._resolved_by_key.get(text, text)

    def _resolve_speaker_display_name(self, raw_speaker: str) -> str:
        return self._resolved_by_key.get(raw_speaker, raw_speaker)


class _SpeakerKeyEditorMeta:
    def __init__(self) -> None:
        self._speaker_keys_by_uid: dict[str, str] = {}
        self._display_segments: list[DialogueSegment] | None = None

    @staticmethod
    def _normalize_speaker_key(value: str) -> str:
        cleaned = value.strip()
        return cleaned if cleaned else ""

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        return self._speaker_keys_by_uid.get(segment.uid, "")

    @staticmethod
    def _is_translator_mode() -> bool:
        return True

    def _display_segments_for_session(
        self,
        session: FileSession,
        *,
        translator_mode: bool,
        actor_mode: bool,
    ) -> list[DialogueSegment]:
        _ = (session, translator_mode, actor_mode)
        return list(self._display_segments or [])

    @staticmethod
    def _name_index_field_from_uid(uid: str) -> str:
        if ":" not in uid:
            return "name"
        tail = uid.rsplit(":", 1)[-1]
        if tail.isdigit():
            return "name"
        return tail


def _segment(uid: str, text: str, speaker: str = "") -> DialogueSegment:
    lines = text.split("\n") if text else [""]
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=list(lines),
        original_lines=list(lines),
        source_lines=list(lines),
    )


class MassTranslatePromptTests(unittest.TestCase):
    def test_build_prompt_uses_project_source_and_profile_target_languages(self) -> None:
        harness = _PromptDialogHarness(
            _EditorPromptMeta(
                source_language_code="JA_JP",
                target_language_code="FR",
                prompt_template=(
                    "Translate `{source_field}` -> `{target_field}`.\n"
                    "lang {source_language_code} to {target_language_code}\n"
                    "{payload_json}"
                ),
            )
        )
        payload = {"entries": [{"id": "D:1", "ja_jp_text": "こんにちは", "fr_translation": ""}]}
        prompt = harness._build_prompt_for_payload(payload)

        self.assertIn("`ja_jp_text` -> `fr_translation`", prompt)
        self.assertIn("lang ja-jp to fr", prompt)
        self.assertIn('"fr_translation": ""', prompt)

    def test_build_prompt_defaults_without_profile_metadata_methods(self) -> None:
        harness = _PromptDialogHarness(object())
        payload = {"entries": [{"id": "D:2", "ja_text": "Hola", "en_translation": ""}]}
        prompt = harness._build_prompt_for_payload(payload)
        self.assertIn("from ja into en", prompt)
        self.assertIn("`ja_text`", prompt)
        self.assertIn("`en_translation`", prompt)

    def test_speaker_display_resolves_name_tokens_for_prompt_context(self) -> None:
        editor = _SpeakerDisplayEditorMeta()
        editor._resolved_by_key[r"\C[2]\N[1]\C[0]"] = r"\C[2]Masatoki\C[0]"
        harness = _PromptDialogHarness(editor)

        display = harness._speaker_display_for_prompt(r"\C[2]\N[1]\C[0]")

        self.assertEqual(display, r"\C[2]Masatoki\C[0]")

    def test_speaker_display_falls_back_to_actors_data_when_needed(self) -> None:
        editor = _SpeakerDisplayEditorMeta()
        actors_path = Path("Actors.json")
        editor.sessions[actors_path] = SimpleNamespace(
            path=actors_path,
            data=[
                None,
                {"name": "Ari"},
                {"name": "Boro"},
                {"name": "Cira"},
                {"name": "Dane"},
            ],
        )
        harness = _PromptDialogHarness(editor)

        display = harness._speaker_display_for_prompt(r"\C[2]\N[4]\C[0]")

        self.assertEqual(display, r"\C[2]Dane\C[0]")

    def test_persistent_speaker_key_uses_resolved_key_for_inferred_speakers(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        segment = _segment("Map001.json:1", "Alice\nHello", "")
        editor._speaker_keys_by_uid[segment.uid] = "Alice"
        harness = _PromptDialogHarness(editor)

        resolved = harness._persistent_speaker_key_for_segment(segment)

        self.assertEqual(resolved, "Alice")

    def test_segments_for_mass_translate_uses_display_filter_for_actor_sessions(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        s1 = _segment("Actors.json:A:1", "Harold")
        s2 = _segment("Actors.json:A:2", "")
        session = FileSession(
            path=Path("Actors.json"),
            data=[],
            bundles=[],
            segments=[s1, s2],
        )
        setattr(session, "name_index_kind", "actor")
        editor._display_segments = [s1]
        harness = _PromptDialogHarness(editor)

        resolved = harness._segments_for_session_mass_translate(session.path, session)

        self.assertEqual([segment.uid for segment in resolved], ["Actors.json:A:1"])

    def test_segments_for_mass_translate_can_include_actor_alias_rows(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        actor = _segment("Actors.json:A:1", "Harold")
        alias = _segment("Actors.json:A:1:alt_1", "ヒナタ")
        setattr(alias, "is_actor_name_alias", True)
        session = FileSession(
            path=Path("Actors.json"),
            data=[],
            bundles=[],
            segments=[actor, alias],
        )
        setattr(session, "name_index_kind", "actor")
        editor._display_segments = [actor, alias]
        harness = _PromptDialogHarness(editor)

        resolved = harness._segments_for_session_mass_translate(session.path, session)

        self.assertEqual(
            [segment.uid for segment in resolved],
            ["Actors.json:A:1", "Actors.json:A:1:alt_1"],
        )

    def test_segment_content_type_treats_plugin_command_text_as_misc(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        segment = _segment("Map001.json:L0:G:0:text", "テキスト")
        segment.segment_kind = "plugin_command_text"
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[segment],
        )
        harness = _PromptDialogHarness(editor)

        content_type = harness._segment_content_type(session.path, session, segment)

        self.assertEqual(content_type, "misc")

    def test_segment_content_type_treats_note_text_as_misc(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        segment = _segment("Map001.json:N:abc", "<LB:\\i[150]あずみさん>")
        segment.segment_kind = "note_text"
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[segment],
        )
        harness = _PromptDialogHarness(editor)

        content_type = harness._segment_content_type(session.path, session, segment)

        self.assertEqual(content_type, "misc")

    def test_segment_content_type_treats_actor_profile_as_misc(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        segment = _segment("Actors.json:A:34:profile", "両手が変化した。")
        segment.segment_kind = "name_index"
        session = FileSession(
            path=Path("Actors.json"),
            data=[],
            bundles=[],
            segments=[segment],
        )
        setattr(session, "is_name_index_session", True)
        setattr(session, "name_index_kind", "actor")
        harness = _PromptDialogHarness(editor)

        content_type = harness._segment_content_type(session.path, session, segment)

        self.assertEqual(content_type, "misc")

    def test_segment_content_type_treats_tyrano_dialogue_as_dialogue(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        segment = _segment("scene.ks:K:1", "こんにちは", "NPC")
        segment.segment_kind = "tyrano_dialogue"
        session = FileSession(
            path=Path("scene.ks"),
            data={},
            bundles=[],
            segments=[segment],
        )
        harness = _PromptDialogHarness(editor)

        content_type = harness._segment_content_type(session.path, session, segment)

        self.assertEqual(content_type, "dialogue")

    def test_segment_content_type_treats_choice_as_dialogue(self) -> None:
        editor = _SpeakerKeyEditorMeta()
        segment = _segment("scene.ks:KQ:1", "選択肢")
        segment.segment_kind = "choice"
        session = FileSession(
            path=Path("scene.ks"),
            data={},
            bundles=[],
            segments=[segment],
        )
        harness = _PromptDialogHarness(editor)

        content_type = harness._segment_content_type(session.path, session, segment)

        self.assertEqual(content_type, "dialogue")


if __name__ == "__main__":
    unittest.main()
