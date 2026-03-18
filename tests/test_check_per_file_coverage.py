from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dialogue_visual_editor import check_per_file_coverage as checker


class CheckPerFileCoverageTests(unittest.TestCase):
    def test_normalize_and_scope_helpers(self) -> None:
        self.assertEqual(checker._normalize_path(r"a\b\c"), "a/b/c")
        self.assertTrue(checker._in_scope("dialogue_visual_editor/app.py", []))
        self.assertTrue(
            checker._in_scope(
                "dialogue_visual_editor/helpers/core/parser.py",
                ["dialogue_visual_editor/"],
            )
        )
        self.assertFalse(
            checker._in_scope(
                "third_party/lib.py",
                ["dialogue_visual_editor/"],
            )
        )

    def test_excluded_prefix_and_suffix_helpers(self) -> None:
        self.assertFalse(checker._is_excluded("a/b.py", []))
        self.assertFalse(checker._is_excluded("dialogue_visual_editor/app.py", ["__init__.py"]))
        self.assertTrue(
            checker._is_excluded(
                "dialogue_visual_editor/__init__.py",
                ["/__init__.py"],
            )
        )
        self.assertFalse(checker._has_excluded_prefix("dialogue_visual_editor/app.py", []))
        self.assertTrue(
            checker._has_excluded_prefix(
                "dialogue_visual_editor/tests/test.py",
                ["dialogue_visual_editor/tests/"],
            )
        )

    def test_main_skips_files_with_no_matching_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "external/lib.py": {
                                "summary": {
                                    "num_statements": 10,
                                    "percent_covered": 50.0,
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "sys.argv",
                [
                    "check",
                    "--json",
                    str(report_path),
                    "--include-prefix",
                    "other/",
                ],
            ):
                self.assertEqual(checker.main(), 2)

    def test_main_skips_excluded_prefix_and_suffix_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "dialogue_visual_editor/tests/test_check.py": {
                                "summary": {
                                    "num_statements": 10,
                                    "percent_covered": 50.0,
                                }
                            },
                            "dialogue_visual_editor/helpers/__init__.py": {
                                "summary": {
                                    "num_statements": 10,
                                    "percent_covered": 50.0,
                                }
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "sys.argv",
                [
                    "check",
                    "--json",
                    str(report_path),
                    "--exclude-prefix",
                    "dialogue_visual_editor/tests/",
                    "--exclude-suffix",
                    "/__init__.py",
                ],
            ):
                self.assertEqual(checker.main(), 2)

    def test_main_ignores_zero_statement_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "dialogue_visual_editor/helpers/core/zero.py": {
                                "summary": {"num_statements": 0, "percent_covered": 0.0}
                            },
                            "dialogue_visual_editor/helpers/core/ok.py": {
                                "summary": {
                                    "num_statements": 10,
                                    "percent_covered": 90.0,
                                }
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch("sys.argv", ["check", "--json", str(report_path)]):
                self.assertEqual(checker.main(), 0)

    def test_module_entrypoint_uses_system_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "missing_coverage.json"
            module_path = Path(__file__).resolve().parents[1] / "check_per_file_coverage.py"

            with patch("sys.argv", ["check-per-file", "--json", str(report_path)]):
                with self.assertRaises(SystemExit) as raised:
                    runpy.run_path(str(module_path), run_name="__main__")

        self.assertEqual(raised.exception.code, 2)

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
