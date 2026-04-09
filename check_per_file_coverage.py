from __future__ import annotations

import argparse
import json
from pathlib import Path


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _in_scope(path: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    normalized = _normalize_path(path)
    return any(normalized.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _is_excluded(path: str, suffixes: list[str]) -> bool:
    if not suffixes:
        return False
    normalized = _normalize_path(path)
    return any(normalized.endswith(suffix) for suffix in suffixes)


def _has_excluded_prefix(path: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return False
    normalized = _normalize_path(path)
    return any(normalized.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when any measured file falls below a coverage threshold."
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default="coverage.json",
        help="Coverage JSON report path.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Per-file minimum coverage percentage.",
    )
    parser.add_argument(
        "--include-prefix",
        action="append",
        default=[],
        help="Only evaluate files whose normalized path starts with this prefix.",
    )
    parser.add_argument(
        "--exclude-prefix",
        action="append",
        default=["tests/"],
        help="Skip files whose normalized path starts with this prefix.",
    )
    parser.add_argument(
        "--exclude-suffix",
        action="append",
        default=["/__init__.py"],
        help="Skip files whose normalized path ends with this suffix.",
    )
    args = parser.parse_args()

    report_path = Path(args.json_path)
    if not report_path.is_file():
        print(f"Coverage JSON report not found: {report_path}")
        return 2

    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    files_data = report_data.get("files", {})

    failing_files: list[tuple[str, float]] = []
    checked_files = 0
    for file_path, file_info in files_data.items():
        normalized = _normalize_path(file_path)
        if not _in_scope(normalized, args.include_prefix):
            continue
        if _has_excluded_prefix(normalized, args.exclude_prefix):
            continue
        if _is_excluded(normalized, args.exclude_suffix):
            continue

        summary = file_info.get("summary", {})
        statements = int(summary.get("num_statements", 0))
        if statements <= 0:
            continue

        checked_files += 1
        percent_covered = float(summary.get("percent_covered", 0.0))
        if percent_covered + 1e-9 < args.threshold:
            failing_files.append((normalized, percent_covered))

    if checked_files == 0:
        print("No files matched the configured scope.")
        return 2

    if failing_files:
        print(f"Per-file coverage check failed (< {args.threshold:.1f}%):")
        for path, percent in sorted(failing_files):
            print(f"  {path}: {percent:.1f}%")
        return 1

    print(
        f"Per-file coverage check passed: {checked_files} files are >= {args.threshold:.1f}%."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
