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
        on_smart_quotes: Callable[[], None],
        on_smart_collapse_all: Callable[[], None],
        on_variable_lengths: Callable[[], None],
        count_normalize_codes: Callable[[], int],
        count_trim_extra_ellipses: Callable[[], int],
        count_smart_quotes: Callable[[], int],
        count_smart_collapse_current_file: Callable[[], int],
        count_smart_collapse_all_files: Callable[[], int],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Normalizations")
        self.setModal(False)
        self.resize(420, 260)
        self._on_normalize_codes = on_normalize_codes
        self._on_trim_extra_ellipses = on_trim_extra_ellipses
        self._on_smart_quotes = on_smart_quotes
        self._on_smart_collapse_all = on_smart_collapse_all
        self._on_variable_lengths = on_variable_lengths
        self._count_normalize_codes = count_normalize_codes
        self._count_trim_extra_ellipses = count_trim_extra_ellipses
        self._count_smart_quotes = count_smart_quotes
        self._count_smart_collapse_current_file = count_smart_collapse_current_file
        self._count_smart_collapse_all_files = count_smart_collapse_all_files
        self._normalize_codes_base_text = "Normalize Codes..."
        self._trim_ellipses_base_text = "Trim Extra Ellipses..."
        self._smart_quotes_base_text = "Smart Quotes..."
        self._smart_collapse_base_text = "Smart Collapse All..."
        self._variable_lengths_base_text = "Variable Lengths..."

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

        self.normalize_codes_btn = QPushButton(self._normalize_codes_base_text)
        self.normalize_codes_btn.clicked.connect(
            self._run_normalize_codes_and_refresh
        )
        layout.addWidget(self.normalize_codes_btn)

        self.trim_ellipses_btn = QPushButton(self._trim_ellipses_base_text)
        self.trim_ellipses_btn.clicked.connect(
            self._run_trim_ellipses_and_refresh
        )
        layout.addWidget(self.trim_ellipses_btn)

        self.smart_quotes_btn = QPushButton(self._smart_quotes_base_text)
        self.smart_quotes_btn.clicked.connect(
            self._run_smart_quotes_and_refresh
        )
        layout.addWidget(self.smart_quotes_btn)

        self.smart_collapse_btn = QPushButton(self._smart_collapse_base_text)
        self.smart_collapse_btn.clicked.connect(
            self._run_smart_collapse_and_refresh
        )
        layout.addWidget(self.smart_collapse_btn)

        self.variable_lengths_btn = QPushButton(self._variable_lengths_base_text)
        self.variable_lengths_btn.clicked.connect(
            self._run_variable_lengths_and_refresh
        )
        layout.addWidget(self.variable_lengths_btn)

        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self._refresh_counts()

    def _button_text_with_fix_count(self, base_text: str, count: int) -> str:
        safe_count = max(0, int(count))
        return f"{base_text} ({safe_count})"

    def _smart_collapse_button_text(self, current_file_count: int, all_files_count: int) -> str:
        safe_current = max(0, int(current_file_count))
        safe_all = max(0, int(all_files_count))
        return f"{self._smart_collapse_base_text} ({safe_current} | {safe_all})"

    def _refresh_counts(self) -> None:
        try:
            normalize_count = int(self._count_normalize_codes())
        except Exception:
            normalize_count = 0
        try:
            trim_count = int(self._count_trim_extra_ellipses())
        except Exception:
            trim_count = 0
        try:
            smart_quotes_count = int(self._count_smart_quotes())
        except Exception:
            smart_quotes_count = 0
        try:
            smart_collapse_current_file_count = int(
                self._count_smart_collapse_current_file()
            )
        except Exception:
            smart_collapse_current_file_count = 0
        try:
            smart_collapse_all_files_count = int(
                self._count_smart_collapse_all_files()
            )
        except Exception:
            smart_collapse_all_files_count = 0

        self.normalize_codes_btn.setText(
            self._button_text_with_fix_count(
                self._normalize_codes_base_text,
                normalize_count,
            )
        )
        self.trim_ellipses_btn.setText(
            self._button_text_with_fix_count(
                self._trim_ellipses_base_text,
                trim_count,
            )
        )
        self.smart_quotes_btn.setText(
            self._button_text_with_fix_count(
                self._smart_quotes_base_text,
                smart_quotes_count,
            )
        )
        self.smart_collapse_btn.setText(
            self._smart_collapse_button_text(
                smart_collapse_current_file_count,
                smart_collapse_all_files_count,
            )
        )
        self.variable_lengths_btn.setText(self._variable_lengths_base_text)

    def _run_normalize_codes_and_refresh(self) -> None:
        self._on_normalize_codes()
        self._refresh_counts()

    def _run_trim_ellipses_and_refresh(self) -> None:
        self._on_trim_extra_ellipses()
        self._refresh_counts()

    def _run_smart_quotes_and_refresh(self) -> None:
        self._on_smart_quotes()
        self._refresh_counts()

    def _run_smart_collapse_and_refresh(self) -> None:
        self._on_smart_collapse_all()
        self._refresh_counts()

    def _run_variable_lengths_and_refresh(self) -> None:
        self._on_variable_lengths()
        self._refresh_counts()
