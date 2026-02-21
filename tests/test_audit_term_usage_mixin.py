from __future__ import annotations

import unittest
from pathlib import Path

from dialogue_visual_editor.helpers.audit.audit_term_usage_mixin import (
    AuditTermUsageMixin,
)
from dialogue_visual_editor.helpers.audit.audit_core_mixin import AuditCoreMixin
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(
    uid: str,
    source_text: str,
    tl_text: str,
    segment_kind: str = "dialogue",
) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[source_text],
        original_lines=[source_text],
        source_lines=[source_text],
        segment_kind=segment_kind,
        translation_lines=[tl_text],
        original_translation_lines=[tl_text],
    )


class _Harness(AuditTermUsageMixin):
    _normalize_audit_translation_lines_for_segment = (
        AuditCoreMixin._normalize_audit_translation_lines_for_segment
    )

    def __init__(self) -> None:
        self.file_paths: list[Path] = []
        self.sessions: dict[Path, FileSession] = {}

    def _audit_path_sessions_snapshot(self) -> list[tuple[Path, FileSession]]:
        return [(path, session) for path, session in self.sessions.items()]

    @staticmethod
    def _is_name_index_session(_session: FileSession) -> bool:
        return False

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

    @staticmethod
    def _audit_entry_text_for_segment(
        session: FileSession,
        segment: DialogueSegment,
        index: int,
    ) -> str:
        if segment.segment_kind == "map_display_name":
            return "Map displayName"
        block_index = 0
        for candidate in session.segments:
            if candidate.segment_kind == "map_display_name":
                continue
            block_index += 1
            if candidate.uid == segment.uid:
                return f"Block {block_index}"
        return f"Block {index}"


class _FakeEdit:
    def __init__(self, value: str) -> None:
        self._value = value

    def text(self) -> str:
        return self._value


class _FakeCheckBox:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _FakeList:
    def __init__(self, items: list[str] | None = None) -> None:
        self.items = list(items or [])
        self.clear_calls = 0

    def clear(self) -> None:
        self.clear_calls += 1
        self.items.clear()


class _FakeLabel:
    def __init__(self) -> None:
        self.value = ""

    def setText(self, value: str) -> None:
        self.value = value


class _FakeButton:
    def __init__(self) -> None:
        self.enabled = False

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class _FakeTimer:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1

    def start(self, _interval_ms: int) -> None:
        return


class _RefreshHarness(AuditTermUsageMixin):
    def __init__(self) -> None:
        self.audit_cache_generation = 1
        self.audit_render_batch_interval_ms = 8
        self.audit_term_query_edit = _FakeEdit("魔王")
        self.audit_term_candidates_edit = _FakeEdit("Demon Lord")
        self.audit_term_dialogue_only_check = _FakeCheckBox(True)
        self.audit_term_variants_list = _FakeList(["existing_variant"])
        self.audit_term_hits_list = _FakeList(["existing_hit"])
        self.audit_term_status_label = _FakeLabel()
        self.audit_term_goto_btn = _FakeButton()
        self.audit_term_render_timer = _FakeTimer()
        self.audit_term_hits_render_timer = _FakeTimer()
        self.audit_term_variants_progress_overlay = None
        self.audit_term_hits_progress_overlay = None
        self.audit_term_display_complete = True
        self.audit_term_displayed_key = (
            self.audit_cache_generation,
            "魔王",
            "Demon Lord",
            True,
        )
        self.audit_term_cache_key = None
        self.audit_term_cache_groups: list[dict[str, object]] = []
        self.audit_term_worker_pending_request = None
        self.refresh_hits_calls = 0
        self.refresh_apply_calls = 0

    def _refresh_audit_term_hits(self) -> None:
        self.refresh_hits_calls += 1

    def _refresh_audit_term_apply_state(self) -> None:
        self.refresh_apply_calls += 1


class AuditTermUsageMixinTests(unittest.TestCase):
    def test_term_groups_match_tyrano_inline_r_candidate_text(self) -> None:
        harness = _Harness()
        path = Path("scene.ks")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("scene.ks:K:1", "魔王", "Demon[r]Lord", segment_kind="tyrano_dialogue"),
            ],
        )

        groups = harness._compute_audit_term_groups_worker(
            [(path, harness.sessions[path])],
            term="魔王",
            candidates_text="Demon Lord",
            dialogue_only=True,
        )

        keys = [str(group["group_key"]) for group in groups]
        self.assertIn("Demon Lord", keys)
        self.assertNotIn("__unmatched__", keys)

    def test_collect_hits_dialogue_only_excludes_non_dialogue_segments(self) -> None:
        harness = _Harness()
        path = Path("Mixed.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "ポーションを使う", "Use potion", segment_kind="dialogue"),
                _segment("n1", "ポーションの説明", "Potion description", segment_kind="name_index"),
            ],
        )

        dialogue_only_hits = harness._collect_audit_term_hits("ポーション", dialogue_only=True)
        all_hits = harness._collect_audit_term_hits("ポーション", dialogue_only=False)

        self.assertEqual(len(dialogue_only_hits), 1)
        self.assertEqual(dialogue_only_hits[0]["uid"], "d1")
        self.assertEqual(len(all_hits), 2)

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

    def test_term_hits_use_display_numbering_when_map_display_name_exists(self) -> None:
        harness = _Harness()
        path = Path("Map003.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("map", "ポーション", "Potion", segment_kind="map_display_name"),
                _segment("d1", "ポーションを拾う", "Pick potion", segment_kind="dialogue"),
            ],
        )

        hits = harness._collect_audit_term_hits("ポーション", dialogue_only=False)
        entries = {str(hit["entry"]) for hit in hits}

        self.assertIn("Map displayName", entries)
        self.assertIn("Block 1", entries)
        self.assertNotIn("Block 2", entries)

    def test_term_hits_match_name_code_query_without_backslash(self) -> None:
        harness = _Harness()
        path = Path("Map004.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "\\N[3]が来た", "Name arrived", segment_kind="dialogue"),
            ],
        )

        hits = harness._collect_audit_term_hits("N[3]", dialogue_only=False)

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["uid"], "d1")

    def test_candidate_name_codes_match_translation_with_backslash(self) -> None:
        harness = _Harness()
        path = Path("Map005.json")
        harness.file_paths = [path]
        harness.sessions[path] = FileSession(
            path=path,
            data=[],
            bundles=[],
            segments=[
                _segment("d1", "勇者", "\\N[7] is ready", segment_kind="dialogue"),
            ],
        )

        groups = harness._compute_audit_term_groups_worker(
            [(path, harness.sessions[path])],
            term="勇者",
            candidates_text="N[7], N[8]",
            dialogue_only=False,
        )
        keys = [str(group["group_key"]) for group in groups]

        self.assertIn("N[7]", keys)
        self.assertNotIn("__unmatched__", keys)

    def test_parse_candidates_normalizes_name_code_with_optional_backslash(self) -> None:
        harness = _Harness()

        parsed = harness._parse_audit_term_candidates("\\N[7] | n[7] | N[8]")

        self.assertEqual(parsed, ["N[7]", "N[8]"])

    def test_replace_case_insensitive_handles_name_code_input_without_backslash(self) -> None:
        harness = _Harness()

        replaced, count = harness._replace_case_insensitive(
            r"A \N[2] B",
            "N[2]",
            "N[1]",
        )

        self.assertEqual(count, 1)
        self.assertEqual(replaced, r"A \N[1] B")

    def test_refresh_panel_fast_path_keeps_existing_variants_list(self) -> None:
        harness = _RefreshHarness()

        harness._refresh_audit_term_panel()

        self.assertEqual(harness.audit_term_variants_list.clear_calls, 0)
        self.assertEqual(harness.audit_term_hits_list.clear_calls, 0)
        self.assertEqual(harness.refresh_hits_calls, 1)
        self.assertEqual(harness.refresh_apply_calls, 1)


if __name__ == "__main__":
    unittest.main()
