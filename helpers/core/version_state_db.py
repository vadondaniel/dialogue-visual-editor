from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Literal, Optional

from .text_utils import now_utc_iso

VersionKind = Literal["original", "translated"]


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
                    translated_json TEXT NOT NULL,
                    original_saved_at TEXT NOT NULL,
                    translated_saved_at TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_versions_saved_at ON file_versions(translated_saved_at)"
            )

    def _encode_payload(self, data: Any) -> str:
        return json.dumps(data, ensure_ascii=False, indent=0)

    def ensure_original_snapshot(self, file_path: str, original_data: Any) -> None:
        payload = self._encode_payload(original_data)
        now = now_utc_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO file_versions(
                    file_path,
                    original_json,
                    translated_json,
                    original_saved_at,
                    translated_saved_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (file_path, payload, payload, now, now),
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
                    translated_json,
                    original_saved_at,
                    translated_saved_at
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    translated_json=excluded.translated_json,
                    translated_saved_at=excluded.translated_saved_at
                """,
                (file_path, payload, payload, now, now),
            )

    def get_snapshot_payload(self, file_path: str, version: VersionKind) -> Optional[str]:
        column = "original_json" if version == "original" else "translated_json"
        cursor = self.conn.execute(
            f"SELECT {column} FROM file_versions WHERE file_path = ?",
            (file_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        value = row[0]
        return value if isinstance(value, str) else None

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
