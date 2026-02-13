from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import DialogueSegment
from .text_utils import now_utc_iso


class DialogueIndexDB:
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
                CREATE TABLE IF NOT EXISTS file_index (
                    file_path TEXT PRIMARY KEY,
                    modified_ts REAL NOT NULL,
                    scanned_at TEXT NOT NULL,
                    block_count INTEGER NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS block_index (
                    file_path TEXT NOT NULL,
                    block_uid TEXT NOT NULL,
                    block_order INTEGER NOT NULL,
                    context TEXT NOT NULL,
                    speaker TEXT,
                    face_name TEXT,
                    has_face INTEGER NOT NULL,
                    line_count INTEGER NOT NULL,
                    preview TEXT,
                    PRIMARY KEY (file_path, block_uid)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS change_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    block_uid TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    old_text TEXT NOT NULL,
                    new_text TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_change_file_time ON change_log(file_path, changed_at)"
            )

    def update_file_index(self, file_path: str, modified_ts: float, segments: list[DialogueSegment]) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO file_index(file_path, modified_ts, scanned_at, block_count)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    modified_ts=excluded.modified_ts,
                    scanned_at=excluded.scanned_at,
                    block_count=excluded.block_count
                """,
                (file_path, modified_ts, now_utc_iso(), len(segments)),
            )
            self.conn.execute("DELETE FROM block_index WHERE file_path = ?", (file_path,))
            rows = []
            for idx, seg in enumerate(segments):
                preview = seg.text_joined().replace("\n", " / ")
                if len(preview) > 180:
                    preview = preview[:177] + "..."
                rows.append(
                    (
                        file_path,
                        seg.uid,
                        idx,
                        seg.context,
                        seg.speaker_name,
                        seg.face_name,
                        1 if seg.has_face else 0,
                        len(seg.lines),
                        preview,
                    )
                )
            if rows:
                self.conn.executemany(
                    """
                    INSERT INTO block_index(
                        file_path, block_uid, block_order, context,
                        speaker, face_name, has_face, line_count, preview
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def log_changes(self, file_path: str, changes: list[tuple[str, str, str]]) -> None:
        if not changes:
            return
        ts = now_utc_iso()
        with self.conn:
            self.conn.executemany(
                """
                INSERT INTO change_log(file_path, block_uid, changed_at, old_text, new_text)
                VALUES(?, ?, ?, ?, ?)
                """,
                [(file_path, uid, ts, old_text, new_text) for uid, old_text, new_text in changes],
            )

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
