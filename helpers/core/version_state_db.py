from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Literal, Optional

from .text_utils import now_utc_iso

VersionKind = Literal["original", "working", "translated"]
ImportTargetKind = Literal["working", "translated"]
logger = logging.getLogger(__name__)


class DialogueVersionDB:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_versions (
                    file_path TEXT PRIMARY KEY,
                    original_json TEXT NOT NULL,
                    working_json TEXT,
                    translated_json TEXT NOT NULL,
                    original_saved_at TEXT NOT NULL,
                    working_saved_at TEXT,
                    translated_saved_at TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_versions_saved_at ON file_versions(translated_saved_at)"
            )

        self._migrate_file_versions_schema()

    def _migrate_file_versions_schema(self) -> None:
        info_rows = self.conn.execute(
            "PRAGMA table_info(file_versions)").fetchall()
        columns = {str(row[1]) for row in info_rows}
        with self.conn:
            if "working_json" not in columns:
                self.conn.execute(
                    "ALTER TABLE file_versions ADD COLUMN working_json TEXT")
            if "working_saved_at" not in columns:
                self.conn.execute(
                    "ALTER TABLE file_versions ADD COLUMN working_saved_at TEXT")
            self.conn.execute(
                """
                UPDATE file_versions
                SET working_json = translated_json
                WHERE working_json IS NULL OR working_json = ''
                """
            )
            self.conn.execute(
                """
                UPDATE file_versions
                SET working_saved_at = translated_saved_at
                WHERE working_saved_at IS NULL OR working_saved_at = ''
                """
            )

    def _encode_payload(self, data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=0)

    def has_snapshot(self, file_path: str) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM file_versions WHERE file_path = ?",
            (file_path,),
        )
        return cursor.fetchone() is not None

    def ensure_original_snapshot(self, file_path: str, original_data: Any) -> None:
        payload = self._encode_payload(original_data)
        now = now_utc_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO file_versions(
                    file_path,
                    original_json,
                    working_json,
                    translated_json,
                    original_saved_at,
                    working_saved_at,
                    translated_saved_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (file_path, payload, payload, payload, now, now, now),
            )
            self.conn.execute(
                """
                UPDATE file_versions
                SET
                    working_json = COALESCE(NULLIF(working_json, ''), translated_json),
                    working_saved_at = COALESCE(NULLIF(working_saved_at, ''), translated_saved_at)
                WHERE file_path = ?
                """,
                (file_path,),
            )

    def save_working_snapshot(self, file_path: str, working_data: Any) -> None:
        payload = self._encode_payload(working_data)
        now = now_utc_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO file_versions(
                    file_path,
                    original_json,
                    working_json,
                    translated_json,
                    original_saved_at,
                    working_saved_at,
                    translated_saved_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    working_json=excluded.working_json,
                    working_saved_at=excluded.working_saved_at
                """,
                (file_path, payload, payload, payload, now, now, now),
            )

    def save_translated_snapshot(self, file_path: str, translated_data: Any) -> None:
        payload = self._encode_payload(translated_data)
        now = now_utc_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO file_versions(
                    file_path,
                    original_json,
                    working_json,
                    translated_json,
                    original_saved_at,
                    working_saved_at,
                    translated_saved_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    translated_json=excluded.translated_json,
                    translated_saved_at=excluded.translated_saved_at
                """,
                (file_path, payload, payload, payload, now, now, now),
            )

    def import_from_disk(self, file_path: str, disk_data: Any, target_version: ImportTargetKind) -> None:
        payload = self._encode_payload(disk_data)
        now = now_utc_iso()
        self.ensure_original_snapshot(file_path, disk_data)
        with self.conn:
            if target_version == "working":
                self.conn.execute(
                    """
                    UPDATE file_versions
                    SET
                        working_json = ?,
                        working_saved_at = ?
                    WHERE file_path = ?
                    """,
                    (payload, now, file_path),
                )
            else:
                self.conn.execute(
                    """
                    UPDATE file_versions
                    SET
                        translated_json = ?,
                        translated_saved_at = ?,
                        working_json = ?,
                        working_saved_at = ?
                    WHERE file_path = ?
                    """,
                    (payload, now, payload, now, file_path),
                )

    def get_working_snapshot_payload(self, file_path: str) -> Optional[str]:
        cursor = self.conn.execute(
            "SELECT working_json FROM file_versions WHERE file_path = ?",
            (file_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        value = row[0]
        return value if isinstance(value, str) else None

    def get_snapshot_payload(self, file_path: str, version: VersionKind) -> Optional[str]:
        if version == "original":
            column = "original_json"
        elif version == "working":
            column = "working_json"
        else:
            column = "translated_json"
        cursor = self.conn.execute(
            f"SELECT {column} FROM file_versions WHERE file_path = ?",
            (file_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        value = row[0]
        return value if isinstance(value, str) else None

    def set_applied_version(self, version: VersionKind) -> None:
        now = now_utc_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO project_state(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                ("applied_version", version),
            )
            self.conn.execute(
                """
                INSERT INTO project_state(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                ("applied_version_at", now),
            )

    def get_applied_version(self) -> Optional[VersionKind]:
        cursor = self.conn.execute(
            "SELECT value FROM project_state WHERE key = ?",
            ("applied_version",),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        value = row[0]
        if value == "original":
            return "original"
        if value == "working":
            return "working"
        if value == "translated":
            return "translated"
        return None

    def get_applied_version_timestamp(self) -> str:
        cursor = self.conn.execute(
            "SELECT value FROM project_state WHERE key = ?",
            ("applied_version_at",),
        )
        row = cursor.fetchone()
        if row is None:
            return ""
        value = row[0]
        return value if isinstance(value, str) else ""

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            logger.exception("Failed to close version DB '%s'.", self.path)
