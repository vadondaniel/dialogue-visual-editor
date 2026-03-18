from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dialogue_visual_editor import check_per_file_coverage as checker


class CheckPerFileCoverageTests(unittest.TestCase):
    def test_main_returns_2_when_report_file_is_missing(self) -> None:
        with patch("sys.argv", ["check", "--json", "does_not_exist.json"]):
            self.assertEqual(checker.main(), 2)

    def test_main_returns_0_when_all_files_meet_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "dialogue_visual_editor/helpers/core/parser.py": {
                                "summary": {"num_statements": 10, "percent_covered": 95.0}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "sys.argv",
                ["check", "--json", str(report_path), "--threshold", "80"],
            ):
                self.assertEqual(checker.main(), 0)

    def test_main_returns_1_when_file_is_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "dialogue_visual_editor/helpers/core/parser.py": {
                                "summary": {"num_statements": 10, "percent_covered": 70.0}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "sys.argv",
                ["check", "--json", str(report_path), "--threshold", "80"],
            ):
                self.assertEqual(checker.main(), 1)


if __name__ == "__main__":
    unittest.main()

