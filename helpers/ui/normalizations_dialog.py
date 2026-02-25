from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NormalizationsDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        on_normalize_codes: Callable[[], None],
        on_trim_extra_ellipses: Callable[[], None],
        on_smart_collapse_all: Callable[[], None],
        on_variable_lengths: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Normalizations")
        self.setModal(False)
        self.resize(420, 260)

        layout = QVBoxLayout(self)
        intro = QLabel(
            (
                "Run text normalization and cleanup tools from one place.\n"
                "Each action opens its own confirmation/options workflow."
            )
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(intro)

        normalize_codes_btn = QPushButton("Normalize Codes...")
        normalize_codes_btn.clicked.connect(on_normalize_codes)
        layout.addWidget(normalize_codes_btn)

        trim_ellipses_btn = QPushButton("Trim Extra Ellipses...")
        trim_ellipses_btn.clicked.connect(on_trim_extra_ellipses)
        layout.addWidget(trim_ellipses_btn)

        smart_collapse_btn = QPushButton("Smart Collapse All...")
        smart_collapse_btn.clicked.connect(on_smart_collapse_all)
        layout.addWidget(smart_collapse_btn)

        variable_lengths_btn = QPushButton("Variable Lengths...")
        variable_lengths_btn.clicked.connect(on_variable_lengths)
        layout.addWidget(variable_lengths_btn)

        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
