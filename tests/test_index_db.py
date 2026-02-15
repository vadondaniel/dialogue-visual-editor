from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dialogue_visual_editor.helpers.core.index_db import DialogueIndexDB
from dialogue_visual_editor.helpers.core.models import DialogueSegment


def _segment(uid: str, speaker: str, line: str) -> DialogueSegment:
    return DialogueSegment(
        uid=uid,
        context="Map001.json > events > [0] > pages > [0] > list",
        code101={"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, speaker]},
        lines=[line],
        original_lines=[line],
        source_lines=[line],
    )


class IndexDBTests(unittest.TestCase):
    def test_update_file_index_writes_rows_and_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "index.sqlite3"
            db = DialogueIndexDB(db_path)
            try:
                long_line = "x" * 220
                segments = [
                    _segment("uid-a", "Hero", long_line),
                    _segment("uid-b", "", "Short line"),
                ]
                db.update_file_index("Map001.json", 123.0, segments)

                file_row = db.conn.execute(
                    "SELECT block_count FROM file_index WHERE file_path = ?",
                    ("Map001.json",),
                ).fetchone()
                self.assertIsNotNone(file_row)
                self.assertEqual(file_row[0], 2)

                block_rows = db.conn.execute(
                    """
                    SELECT block_uid, speaker, line_count, preview
                    FROM block_index
                    WHERE file_path = ?
                    ORDER BY block_order
                    """,
                    ("Map001.json",),
                ).fetchall()
                self.assertEqual(len(block_rows), 2)
                self.assertEqual(block_rows[0][0], "uid-a")
                self.assertEqual(block_rows[0][1], "Hero")
                self.assertEqual(block_rows[0][2], 1)
                self.assertTrue(str(block_rows[0][3]).endswith("..."))
                self.assertLessEqual(len(str(block_rows[0][3])), 180)
            finally:
                db.close()

    def test_log_changes_writes_change_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "index.sqlite3"
            db = DialogueIndexDB(db_path)
            try:
                db.log_changes(
                    "Map002.json",
                    [
                        ("uid-1", "old 1", "new 1"),
                        ("uid-2", "old 2", "new 2"),
                    ],
                )
                rows = db.conn.execute(
                    """
                    SELECT block_uid, old_text, new_text
                    FROM change_log
                    WHERE file_path = ?
                    ORDER BY id
                    """,
                    ("Map002.json",),
                ).fetchall()
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0][0], "uid-1")
                self.assertEqual(rows[0][1], "old 1")
                self.assertEqual(rows[0][2], "new 1")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
