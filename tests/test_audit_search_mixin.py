from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession
from dialogue_visual_editor.helpers.audit.audit_search_mixin import AuditSearchMixin
from dialogue_visual_editor.helpers.audit.audit_core_mixin import AuditCoreMixin


class _Harness(AuditSearchMixin):
    _normalize_audit_translation_lines_for_segment = (
        AuditCoreMixin._normalize_audit_translation_lines_for_segment
    )

    def __init__(self) -> None:
        self.sessions: dict[Path, FileSession] = {}

    @staticmethod
    def _is_name_index_session(_session: FileSession) -> bool:
        return False

    @staticmethod
    def _name_index_label(_session: FileSession) -> str:
        return "Actor"

    @staticmethod
    def _actor_id_from_uid(_uid: str) -> None:
        return None

    @staticmethod
    def _segment_source_lines_for_display(segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    @staticmethod
    def _normalize_translation_lines(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) if item is not None else "" for item in value] or [""]
        if isinstance(value, str):
            return value.split("\n")
        return [""]

    @staticmethod
    def _audit_highlight_style() -> str:
        return "background:#ff0;"

    @staticmethod
    def _relative_path(path: Path) -> str:
        return path.as_posix()

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

    @staticmethod
    def _refresh_dirty_state(_session: FileSession) -> None:
        return


class _TimerStub:
    def __init__(self) -> None:
        self.started = 0

    def start(self) -> None:
        self.started += 1


class _CheckedAction:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


class _RaisingAction:
    @staticmethod
    def isChecked() -> bool:
        raise RuntimeError("boom")


def _segment(uid: str, source: str, translation: str, *, kind: str = "dialogue") -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=[source],
        original_lines=[source],
        source_lines=[source],
        segment_kind=kind,
        translation_lines=[translation],
        original_translation_lines=[translation],
    )


class AuditSearchMixinTests(unittest.TestCase):
    def test_natural_mode_helpers_and_case_sensitive_guard_paths(self) -> None:
        harness = _Harness()

        self.assertFalse(harness._audit_search_uses_natural_mode(""))
        self.assertEqual(harness._natural_match_spans("", "a", False), [])
        self.assertEqual(harness._natural_match_spans(r"\C[2]   \N[1]", "a", False), [])

        harness.audit_search_timer = None
        harness._schedule_audit_search()
        timer = _TimerStub()
        harness.audit_search_timer = timer
        harness._schedule_audit_search()
        self.assertEqual(timer.started, 1)

        harness.audit_search_case_sensitive_check = None
        self.assertFalse(harness._audit_search_case_sensitive_enabled())
        harness.audit_search_case_sensitive_check = _RaisingAction()
        self.assertFalse(harness._audit_search_case_sensitive_enabled())
        harness.audit_search_case_sensitive_check = _CheckedAction(True)
        self.assertTrue(harness._audit_search_case_sensitive_enabled())

    def test_audit_search_needle_preserves_whitespace_literal_query(self) -> None:
        harness = _Harness()
        query = " úr "

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=True,
        )

        self.assertFalse(natural_mode)
        self.assertEqual(needle, query)

    def test_audit_search_needle_casefolds_literal_whitespace_query(self) -> None:
        harness = _Harness()
        query = " ÚR "

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=False,
        )

        self.assertFalse(natural_mode)
        self.assertEqual(needle, query.casefold())

    def test_audit_search_needle_uses_literal_mode_for_control_queries(self) -> None:
        harness = _Harness()
        query = r"\N[3] úr"

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=True,
        )

        self.assertFalse(natural_mode)
        self.assertEqual(needle, query)

    def test_audit_search_needle_uses_natural_mode_without_whitespace(self) -> None:
        harness = _Harness()
        query = "魔王"

        needle, natural_mode = harness._audit_search_needle(
            query,
            case_sensitive=False,
        )

        self.assertTrue(natural_mode)
        self.assertEqual(needle, query.casefold())

    def test_search_records_use_display_numbering_when_map_display_name_exists(self) -> None:
        harness = _Harness()
        path = Path("Map001.json")
        session = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[
                _segment("Map001.json:map_display_name", "Village", "Village EN", kind="map_display_name"),
                _segment("Map001.json:L0:0", "Village line", "Village line EN"),
            ],
        )

        records = harness._compute_audit_search_records_worker(
            [(path, session)],
            scope="original",
            needle="village",
            natural_mode=False,
            case_sensitive=False,
        )

        labels = [str(record["entry_text"]) for record in records]
        self.assertIn("Map displayName", labels)
        self.assertIn("Block 1", labels)
        self.assertNotIn("Block 2", labels)

    def test_replace_in_lines_treats_backslashes_in_replacement_as_literal(self) -> None:
        harness = _Harness()

        replaced, count = harness._replace_in_lines(
            [r"Szintosszeg \V", r"Szintosszeg \V \V"],
            r"Szintosszeg \V",
            r"Szintosszeg: \V",
            True,
        )

        self.assertEqual(count, 2)
        self.assertEqual(replaced, [r"Szintosszeg: \V", r"Szintosszeg: \V \V"])

    def test_replace_in_session_entry_normalizes_tyrano_markers(self) -> None:
        harness = _Harness()
        path = Path("scene.ks")
        session = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("scene.ks:K:1", "src", "Hello", kind="tyrano_dialogue")],
        )
        harness.sessions = {path: session}

        changed, replacements = harness._replace_in_session_entry(
            str(path),
            "scene.ks:K:1",
            "Hello",
            "Hi[r]There[p]",
            "translation",
            True,
        )

        self.assertTrue(changed)
        self.assertEqual(replacements, 1)
        self.assertEqual(session.segments[0].translation_lines, ["Hi", "There"])

    def test_highlight_and_add_result_guard_paths(self) -> None:
        harness = _Harness()
        highlighted_no_match = harness._highlight_audit_match_html(
            "A < B",
            "XYZ",
            "xyz",
            False,
            False,
        )
        highlighted_prefix = harness._highlight_audit_match_html(
            "xAlpha",
            "Alpha",
            "alpha",
            False,
            False,
        )
        self.assertEqual(highlighted_no_match, "A &lt; B")
        self.assertIn("x", highlighted_prefix)
        self.assertIn("background:", highlighted_prefix)

        harness.audit_search_results_list = None
        harness._add_audit_search_result(
            path=Path("Map001.json"),
            uid="u1",
            entry_text="Block 1",
            matched_field="Original",
            matched_text="Alpha",
            query="Alpha",
            needle="alpha",
            natural_mode=False,
            case_sensitive=False,
        )

    def test_compute_worker_fallbacks_and_name_index_actor_id_labels(self) -> None:
        class _NameHarness(_Harness):
            @staticmethod
            def _is_name_index_session(_session: FileSession) -> bool:
                return True

            @staticmethod
            def _actor_id_from_uid(_uid: str) -> int:
                return 7

        harness = _NameHarness()
        harness._audit_entry_text_for_segment = None

        def _raise_normalize(_segment: DialogueSegment, _lines: list[str]) -> list[str]:
            raise RuntimeError("normalize failed")

        harness._normalize_audit_translation_lines_for_segment = _raise_normalize
        path = Path("Actors.json")
        session = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("Actors.json:A:7:name", "Alpha", "Alpha", kind="name_index")],
        )

        records = harness._compute_audit_search_records_worker(
            [(path, session)],
            scope="both",
            needle="alpha",
            natural_mode=False,
            case_sensitive=False,
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["entry_text"], "Actor ID 7")

    def test_replace_in_session_entry_defensive_paths(self) -> None:
        harness = _Harness()
        changed, replacements = harness._replace_in_session_entry(
            "Missing.json",
            "u1",
            "a",
            "b",
            "both",
            True,
        )
        self.assertFalse(changed)
        self.assertEqual(replacements, 0)

        path = Path("Map001.json")
        session = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("u1", "aa", "aa")],
        )
        harness.sessions[path] = session
        changed, replacements = harness._replace_in_session_entry(
            str(path),
            "missing",
            "a",
            "b",
            "both",
            True,
        )
        self.assertFalse(changed)
        self.assertEqual(replacements, 0)

        changed, replacements = harness._replace_in_session_entry(
            str(path),
            "u1",
            "a",
            "b",
            "original",
            True,
        )
        self.assertTrue(changed)
        self.assertEqual(replacements, 2)
        self.assertEqual(session.segments[0].lines, ["bb"])

        session.segments[0].translation_lines = ["aa"]
        harness._normalize_audit_translation_lines_for_segment = None
        changed, replacements = harness._replace_in_session_entry(
            str(path),
            "u1",
            "a",
            "b",
            "translation",
            True,
        )
        self.assertTrue(changed)
        self.assertEqual(replacements, 2)
        self.assertEqual(session.segments[0].translation_lines, ["bb"])

    def test_replace_in_lines_empty_find_and_no_hit_paths(self) -> None:
        harness = _Harness()
        replaced, count = harness._replace_in_lines(
            ["alpha", "beta"],
            "",
            "x",
            True,
        )
        self.assertEqual(replaced, ["alpha", "beta"])
        self.assertEqual(count, 0)

        replaced, count = harness._replace_in_lines(
            ["alpha", "beta"],
            "zzz",
            "x",
            True,
        )
        self.assertEqual(replaced, ["alpha", "beta"])
        self.assertEqual(count, 0)

    def test_replace_in_session_entry_translation_normalizer_exception_paths(self) -> None:
        harness = _Harness()
        path = Path("scene.ks")
        session = FileSession(
            path=path,
            data={},
            bundles=[],
            segments=[_segment("scene.ks:K:1", "src", "aa", kind="tyrano_dialogue")],
        )
        harness.sessions[path] = session

        def _raise_on_read(_segment: DialogueSegment, _lines: list[str]) -> list[str]:
            raise RuntimeError("read normalize failed")

        harness._normalize_audit_translation_lines_for_segment = _raise_on_read
        changed, replacements = harness._replace_in_session_entry(
            str(path),
            "scene.ks:K:1",
            "a",
            "b",
            "translation",
            True,
        )
        self.assertTrue(changed)
        self.assertEqual(replacements, 2)
        self.assertEqual(session.segments[0].translation_lines, ["bb"])

        session.segments[0].translation_lines = ["aa"]

        def _raise_on_store(_segment: DialogueSegment, lines: list[str]) -> list[str]:
            if lines == ["aa"]:
                return ["aa"]
            raise RuntimeError("store normalize failed")

        harness._normalize_audit_translation_lines_for_segment = _raise_on_store
        changed, replacements = harness._replace_in_session_entry(
            str(path),
            "scene.ks:K:1",
            "a",
            "b",
            "translation",
            True,
        )
        self.assertTrue(changed)
        self.assertEqual(replacements, 2)
        self.assertEqual(session.segments[0].translation_lines, ["bb"])


if __name__ == "__main__":
    unittest.main()
