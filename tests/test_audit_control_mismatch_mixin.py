from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from dialogue_visual_editor.helpers.audit.audit_control_mismatch_mixin import (
    AuditControlMismatchMixin,
)
from dialogue_visual_editor.helpers.core.models import DialogueSegment, FileSession


def _segment(
    uid: str,
    source_text: str,
    translation_text: str,
    *,
    translation_only: bool = False,
) -> DialogueSegment:
    source_lines = source_text.split("\n") if source_text else [""]
    translation_lines = translation_text.split("\n") if translation_text else [""]
    return DialogueSegment(
        uid=uid,
        context="ctx",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, ""]},
        lines=list(source_lines),
        original_lines=list(source_lines),
        source_lines=list(source_lines),
        translation_lines=list(translation_lines),
        original_translation_lines=list(translation_lines),
        translation_only=translation_only,
    )


class _Harness(AuditControlMismatchMixin):
    def _normalize_translation_lines(self, value: Any) -> list[str]:
        if isinstance(value, list):
            normalized: list[str] = []
            for item in value:
                if isinstance(item, str):
                    normalized.append(item)
                elif item is None:
                    normalized.append("")
                else:
                    normalized.append(str(item))
            return normalized or [""]
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        return [""]

    def _segment_source_lines_for_display(self, segment: DialogueSegment) -> list[str]:
        return list(segment.source_lines or segment.original_lines or segment.lines or [""])

    def _audit_entry_text_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
        index: int,
    ) -> str:
        _ = session
        _ = segment
        return f"Block {index}"


class AuditControlMismatchMixinTests(unittest.TestCase):
    def test_translation_only_followup_is_unified_with_source_block(self) -> None:
        harness = _Harness()
        source = _segment("Map001.json:L0:0", r"JP \!", "TL first part")
        followup = _segment(
            "Map001.json:I:1",
            "",
            r"TL second part \!",
            translation_only=True,
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[source, followup],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(payload["records"], [])

    def test_unified_followup_still_reports_real_mismatch_once(self) -> None:
        harness = _Harness()
        source = _segment("Map001.json:L0:0", r"JP \!", "TL first part")
        followup = _segment(
            "Map001.json:I:1",
            "",
            r"TL second part \.",
            translation_only=True,
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[source, followup],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        records = payload["records"]
        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["uid"], "Map001.json:L0:0")
        self.assertIn("TL split", records[0]["entry_text"])

    def test_worker_prefers_problem_check_translation_resolver_for_split_followups(self) -> None:
        harness = _Harness()
        anchor = _segment("Map001.json:L0:0", r"\C[2]JP\C[0]", r"\C[2]TL\C[0]")
        followup = _segment(
            "Map001.json:I:1",
            "",
            r"\C[2]TL\C[0]",
            translation_only=True,
        )
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor, followup],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            lambda _segment, session=None: [r"\C[2]TL\C[0]"],
        )
        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            lambda _segment, session=None: [r"\C[2]JP\C[0]"],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(payload["records"], [])

    def test_worker_prefers_logical_source_resolver(self) -> None:
        harness = _Harness()
        anchor = _segment("Map001.json:L0:0", r"\C[2]JP\C[0]", "TL")
        session = FileSession(
            path=Path("Map001.json"),
            data={},
            bundles=[],
            segments=[anchor],
        )
        setattr(
            harness,
            "_logical_translation_source_lines_for_segment",
            lambda _segment, session=None: ["JP"],
        )
        setattr(
            harness,
            "_logical_translation_lines_for_problem_checks",
            lambda _segment, session=None: ["TL"],
        )

        payload = harness._compute_audit_control_mismatch_worker(
            [(Path("Map001.json"), session)],
            only_translated=True,
        )

        self.assertEqual(payload["scanned_blocks"], 1)
        self.assertEqual(payload["records"], [])


if __name__ == "__main__":
    unittest.main()
