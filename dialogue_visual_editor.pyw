from __future__ import annotations

try:
    from .app import DialogueVisualEditor, main
except ImportError:
    import sys
    from pathlib import Path

    script_dir = Path(__file__).resolve().parent
    script_dir_str = str(script_dir)
    if script_dir_str not in sys.path:
        sys.path.insert(0, script_dir_str)
    from app import DialogueVisualEditor, main

__all__ = ["DialogueVisualEditor", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
