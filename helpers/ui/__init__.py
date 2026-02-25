from __future__ import annotations

from .mass_translate_dialog import MassTranslateDialog
from .normalizations_dialog import NormalizationsDialog
from .ui_components import (
    ControlCodeHighlighter,
    DialogueBlockWidget,
    ExactMatchReviewDialog,
    ItemNameDescriptionWidget,
    SpeakerManagerDialog,
    VariableLengthManagerDialog,
    build_control_mismatch_selections,
)

__all__ = [
    "ControlCodeHighlighter",
    "DialogueBlockWidget",
    "ExactMatchReviewDialog",
    "ItemNameDescriptionWidget",
    "MassTranslateDialog",
    "NormalizationsDialog",
    "SpeakerManagerDialog",
    "VariableLengthManagerDialog",
    "build_control_mismatch_selections",
]
