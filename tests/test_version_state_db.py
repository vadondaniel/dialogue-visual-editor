from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dialogue_visual_editor.helpers.core.version_state_db import DialogueVersionDB


class VersionStateDBTests(unittest.TestCase):
    def test_snapshot_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.ensure_original_snapshot("Map001.json", {"v": 1})
                self.assertTrue(db.has_snapshot("Map001.json"))

                db.save_working_snapshot("Map001.json", {"v": 2})
                db.save_translated_snapshot("Map001.json", {"v": 3})

                original = json.loads(
                    db.get_snapshot_payload("Map001.json", "original") or ""
                )
                working = json.loads(
                    db.get_snapshot_payload("Map001.json", "working") or ""
                )
                translated = json.loads(
                    db.get_snapshot_payload("Map001.json", "translated") or ""
                )
                self.assertEqual(original["v"], 1)
                self.assertEqual(working["v"], 2)
                self.assertEqual(translated["v"], 3)
            finally:
                db.close()

    def test_import_from_disk_targets_requested_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.ensure_original_snapshot("Map002.json", {"v": "orig"})
                db.import_from_disk("Map002.json", {"v": "tl"}, "translated")
                db.import_from_disk("Map002.json", {"v": "wk"}, "working")

                working = json.loads(
                    db.get_snapshot_payload("Map002.json", "working") or ""
                )
                translated = json.loads(
                    db.get_snapshot_payload("Map002.json", "translated") or ""
                )
                self.assertEqual(working["v"], "wk")
                self.assertEqual(translated["v"], "tl")
            finally:
                db.close()

    def test_applied_version_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.set_applied_version("translated")
                self.assertEqual(db.get_applied_version(), "translated")
                self.assertNotEqual(db.get_applied_version_timestamp(), "")
            finally:
                db.close()

    def test_migrates_legacy_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.sqlite3"
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE file_versions (
                        file_path TEXT PRIMARY KEY,
                        original_json TEXT NOT NULL,
                        translated_json TEXT NOT NULL,
                        original_saved_at TEXT NOT NULL,
                        translated_saved_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE project_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO file_versions(
                        file_path,
                        original_json,
                        translated_json,
                        original_saved_at,
                        translated_saved_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "Map003.json",
                        json.dumps({"v": "orig"}, ensure_ascii=False),
                        json.dumps({"v": "tl"}, ensure_ascii=False),
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            db = DialogueVersionDB(db_path)
            try:
                working = json.loads(
                    db.get_snapshot_payload("Map003.json", "working") or ""
                )
                self.assertEqual(working["v"], "tl")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
