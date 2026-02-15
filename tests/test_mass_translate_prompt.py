from __future__ import annotations

import unittest
from typing import Any

from dialogue_visual_editor.helpers.ui.mass_translate_dialog import (
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
    _default_prompt_template = classmethod(MassTranslateDialog._default_prompt_template.__func__)
    _normalize_prompt_language_code = staticmethod(
        MassTranslateDialog._normalize_prompt_language_code
    )
    _language_field_prefix = staticmethod(MassTranslateDialog._language_field_prefix)
    _source_text_field_name = MassTranslateDialog._source_text_field_name
    _target_translation_field_name = MassTranslateDialog._target_translation_field_name
    _translation_prompt_metadata = MassTranslateDialog._translation_prompt_metadata
    _build_prompt_for_payload = MassTranslateDialog._build_prompt_for_payload

    def __init__(self, editor: Any) -> None:
        self.editor = editor


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


if __name__ == "__main__":
    unittest.main()
