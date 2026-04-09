from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from helpers.core.version_state_db import (
    DEFAULT_TRANSLATION_PROFILE_ID,
    DialogueVersionDB,
)


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
                db.save_translated_snapshot(
                    "Map001.json",
                    {"v": 4},
                    profile_id="alt",
                )

                original = json.loads(
                    db.get_snapshot_payload("Map001.json", "original") or ""
                )
                working = json.loads(
                    db.get_snapshot_payload("Map001.json", "working") or ""
                )
                translated = json.loads(
                    db.get_snapshot_payload("Map001.json", "translated") or ""
                )
                translated_alt = json.loads(
                    db.get_snapshot_payload(
                        "Map001.json",
                        "translated",
                        profile_id="alt",
                    )
                    or ""
                )
                self.assertEqual(original["v"], 1)
                self.assertEqual(working["v"], 2)
                self.assertEqual(translated["v"], 3)
                self.assertEqual(translated_alt["v"], 4)
            finally:
                db.close()

    def test_import_from_disk_targets_requested_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.ensure_original_snapshot("Map002.json", {"v": "orig"})
                db.import_from_disk(
                    "Map002.json",
                    {"v": "tl"},
                    "translated",
                    profile_id="alt",
                )
                db.import_from_disk("Map002.json", {"v": "wk"}, "working")

                working = json.loads(
                    db.get_snapshot_payload("Map002.json", "working") or ""
                )
                translated = json.loads(
                    db.get_snapshot_payload("Map002.json", "translated") or ""
                )
                translated_alt = json.loads(
                    db.get_snapshot_payload(
                        "Map002.json",
                        "translated",
                        profile_id="alt",
                    )
                    or ""
                )
                self.assertEqual(working["v"], "wk")
                self.assertEqual(translated["v"], "tl")
                self.assertEqual(translated_alt["v"], "tl")
            finally:
                db.close()

    def test_applied_version_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.set_applied_version("translated")
                db.set_applied_translation_profile("alt")
                self.assertEqual(db.get_applied_version(), "translated")
                self.assertEqual(db.get_applied_translation_profile(), "alt")
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
                translated_default = json.loads(
                    db.get_snapshot_payload(
                        "Map003.json",
                        "translated",
                        profile_id=DEFAULT_TRANSLATION_PROFILE_ID,
                    )
                    or ""
                )
                self.assertEqual(working["v"], "tl")
                self.assertEqual(translated_default["v"], "tl")
            finally:
                db.close()

    def test_copy_and_delete_translation_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.save_translated_snapshot("Map010.json", {"v": "base"})
                db.save_translated_snapshot("Map011.json", {"v": "base-2"})
                db.copy_translation_profile("default", "draft")

                copied_1 = json.loads(
                    db.get_snapshot_payload(
                        "Map010.json",
                        "translated",
                        profile_id="draft",
                    )
                    or ""
                )
                copied_2 = json.loads(
                    db.get_snapshot_payload(
                        "Map011.json",
                        "translated",
                        profile_id="draft",
                    )
                    or ""
                )
                self.assertEqual(copied_1["v"], "base")
                self.assertEqual(copied_2["v"], "base-2")
                self.assertIn("draft", db.list_translation_profiles())

                db.delete_translation_profile("draft")
                deleted_payload = db.get_snapshot_payload(
                    "Map010.json",
                    "translated",
                    profile_id="draft",
                )
                self.assertEqual(deleted_payload, db.get_snapshot_payload("Map010.json", "translated"))
            finally:
                db.close()

    def test_get_payloads_return_none_for_unknown_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                self.assertIsNone(db.get_snapshot_payload("Missing.json", "original"))
                self.assertIsNone(db.get_snapshot_payload("Missing.json", "working"))
                self.assertIsNone(db.get_working_snapshot_payload("Missing.json"))
            finally:
                db.close()

    def test_default_translation_profile_and_empty_state_behaviors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                self.assertEqual(
                    db.get_applied_translation_profile(),
                    DEFAULT_TRANSLATION_PROFILE_ID,
                )
                self.assertIsNone(db.get_applied_version())
                self.assertEqual(
                    db.list_translation_profiles(),
                    [DEFAULT_TRANSLATION_PROFILE_ID],
                )

                db.conn.execute(
                    "INSERT INTO project_state(key, value) VALUES(?, ?)",
                    ("applied_translation_profile", ""),
                )
                db.conn.commit()
                self.assertEqual(
                    db.get_applied_translation_profile(),
                    DEFAULT_TRANSLATION_PROFILE_ID,
                )

                db.conn.execute(
                    "INSERT INTO project_state(key, value) VALUES(?, ?)",
                    ("applied_version", "working"),
                )
                db.conn.commit()
                self.assertEqual(db.get_applied_version(), "working")

                db.conn.execute(
                    "INSERT OR REPLACE INTO project_state(key, value) VALUES(?, ?)",
                    ("applied_version", "translated"),
                )
                db.conn.commit()
                self.assertEqual(db.get_applied_version(), "translated")

                db.conn.execute(
                    """
                    INSERT OR REPLACE INTO file_versions(
                        file_path,
                        original_json,
                        working_json,
                        translated_json,
                        original_saved_at,
                        working_saved_at,
                        translated_saved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "Map019.json",
                        json.dumps({}, ensure_ascii=False),
                        None,
                        json.dumps({}, ensure_ascii=False),
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                db.conn.commit()
                self.assertIsNone(db.get_working_snapshot_payload("Map019.json"))
                self.assertEqual(db.get_applied_version_timestamp(), "")
            finally:
                db.close()

    def test_applied_version_normalized_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.conn.execute(
                    "INSERT OR REPLACE INTO project_state(key, value) VALUES (?, ?)",
                    ("applied_version", "original"),
                )
                db.conn.execute(
                    "INSERT OR REPLACE INTO project_state(key, value) VALUES (?, ?)",
                    ("applied_version", "mystery"),
                )
                db.conn.execute(
                    "INSERT OR REPLACE INTO project_state(key, value) VALUES (?, ?)",
                    ("applied_version", "working"),
                )
                db.conn.commit()

                self.assertEqual(db.get_applied_version(), "working")
                db.conn.execute(
                    "INSERT OR REPLACE INTO project_state(key, value) VALUES (?, ?)",
                    ("applied_version", "original"),
                )
                db.conn.commit()
                self.assertEqual(db.get_applied_version(), "original")
                db.conn.execute(
                    "INSERT OR REPLACE INTO project_state(key, value) VALUES (?, ?)",
                    ("applied_version", "mystery"),
                )
                db.conn.commit()
                self.assertIsNone(db.get_applied_version())
            finally:
                db.close()

    def test_normalize_blank_profile_id_on_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            try:
                db.save_translated_snapshot(
                    "Map020.json",
                    {"v": 1},
                    profile_id="   ",
                )
                translated_payload = json.loads(
                    db.get_snapshot_payload("Map020.json", "translated") or ""
                )
                translated_payload_default_profile = json.loads(
                    db.get_snapshot_payload(
                        "Map020.json",
                        "translated",
                        profile_id="",
                    )
                    or ""
                )
                self.assertEqual(translated_payload["v"], 1)
                self.assertEqual(translated_payload_default_profile["v"], 1)
            finally:
                db.close()

    def test_close_swallows_connection_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "versions.sqlite3"
            db = DialogueVersionDB(db_path)
            original_conn = db.conn

            class _FailingConnection:
                def close(self) -> None:
                    raise RuntimeError("boom")

            db.conn = _FailingConnection()
            try:
                db.close()
            finally:
                original_conn.close()
