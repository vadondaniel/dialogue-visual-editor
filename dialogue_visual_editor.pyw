from __future__ import annotations

try:
    from .app import DialogueVisualEditor, main
except ImportError:
    from app import DialogueVisualEditor, main

__all__ = ["DialogueVisualEditor", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
