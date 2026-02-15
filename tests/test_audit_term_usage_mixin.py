from __future__ import annotations

import unittest
from pathlib import Path

from dialogue_visual_editor.helpers.audit.audit_term_usage_mixin import (
    AuditTermUsageMixin,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(uid: str, source_text: str, tl_text: str) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[source_text],
        original_lines=[source_text],
        source_lines=[source_text],
        translation_lines=[tl_text],
        original_translation_lines=[tl_text],
    )


class _Harness(AuditTermUsageMixin):
    def __init__(self) -> None:
        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}

    @staticmethod
    def _segment_source_lines_for_display(segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    @staticmethod
    def _normalize_translation_lines(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value]
        if isinstance(value, str):
            return value.split("\n")
        return [""]


class AuditTermUsageMixinTests(unittest.TestCase):
    def test_jp_suggestions_include_katakana_terms_inside_sentence(self) -> None:
        harness = _Harness()
        path = Path("MapJP001.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("jp1", "このポーションは高い。", "tl1"),
                _segment("jp2", "古いポーションを捨てる。", "tl2"),
                _segment("jp3", "ポーションがあれば安心だ。", "tl3"),
            ],
        )

        jp_suggestions, _tl_suggestions = harness._collect_audit_term_suggestions(
            dialogue_only=False
        )
        jp_suggestions_dict = dict(jp_suggestions)

        self.assertIn("ポーション", jp_suggestions_dict)
        self.assertGreaterEqual(jp_suggestions_dict["ポーション"], 3)

    def test_translation_suggestions_include_hungarian_accented_words(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("s1", "jp1", "A tűz fénye itt ég."),
                _segment("s2", "jp2", "Ez a tűz túl erős."),
                _segment("s3", "jp3", "Látom a tűz nyomát."),
            ],
        )

        _jp_suggestions, tl_suggestions = harness._collect_audit_term_suggestions(
            dialogue_only=False
        )
        tl_suggestions_dict = dict(tl_suggestions)

        self.assertIn("tűz", tl_suggestions_dict)
        self.assertGreaterEqual(tl_suggestions_dict["tűz"], 3)

    def test_translation_suggestions_keep_hungarian_hyphenated_words(self) -> None:
        harness = _Harness()
        path = Path("Map002.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("s1", "jp1", "árvíztűrő-tükörfúrógép működik"),
                _segment("s2", "jp2", "az árvíztűrő-tükörfúrógép itt van"),
                _segment("s3", "jp3", "hozd az árvíztűrő-tükörfúrógép szerszámot"),
            ],
        )

        _jp_suggestions, tl_suggestions = harness._collect_audit_term_suggestions(
            dialogue_only=False
        )
        tl_suggestions_dict = dict(tl_suggestions)

        self.assertIn("árvíztűrő-tükörfúrógép", tl_suggestions_dict)
        self.assertGreaterEqual(tl_suggestions_dict["árvíztűrő-tükörfúrógép"], 3)


if __name__ == "__main__":
    unittest.main()
