from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audit_constants import SANITIZE_CHAR_RULES
from ..mixins.presentation_mixins import is_dark_palette
from ..ui.ui_components import ControlCodeHighlighter


class _AuditWindowHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditWindowMixin(_AuditWindowHostTypingFallback):
    _AUDIT_TAB_SEARCH = 0
    _AUDIT_TAB_SANITIZE = 1
    _AUDIT_TAB_CONTROL_MISMATCH = 2
    _AUDIT_TAB_CONSISTENCY = 3
    _AUDIT_TAB_TERM_USAGE = 4
    _AUDIT_TAB_NAME_CONSISTENCY = 5

    def _audit_case_toggle_icon(self, checked: bool) -> QIcon:
        pixmap = QPixmap(26, 26)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            dark = is_dark_palette()
            if dark:
                text = QColor("#f3f4f6") if checked else QColor("#d1d5db")
                fill = QColor("#4b5563") if checked else QColor(0, 0, 0, 0)
            else:
                text = QColor("#111111") if checked else QColor("#222222")
                fill = QColor("#d1d5db") if checked else QColor(0, 0, 0, 0)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRect(0, 0, 25, 25)
            font = QFont()
            font.setPointSize(10)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(text, 1))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Aa")
        finally:
            painter.end()
        return QIcon(pixmap)

    def _default_audit_search_scope(self) -> str:
        return "translation" if self._is_translator_mode() else "original"

    def _current_audit_tab_index(self) -> int:
        tabs = getattr(self, "audit_tabs", None)
        if isinstance(tabs, QTabWidget):
            return tabs.currentIndex()
        return self._AUDIT_TAB_SEARCH

    def _refresh_audit_tab(self, tab_index: int) -> None:
        if tab_index == self._AUDIT_TAB_SEARCH:
            self._run_audit_search()
            self._refresh_audit_search_replace_preview()
            return
        if tab_index == self._AUDIT_TAB_SANITIZE:
            self._refresh_audit_sanitize_panel()
            return
        if tab_index == self._AUDIT_TAB_CONTROL_MISMATCH:
            self._refresh_audit_control_mismatch_panel()
            return
        if tab_index == self._AUDIT_TAB_CONSISTENCY:
            self._refresh_audit_consistency_panel()
            return
        if tab_index == self._AUDIT_TAB_TERM_USAGE:
            self._refresh_audit_term_panel()
            self._refresh_audit_term_suggestions_panel()
            return
        if tab_index == self._AUDIT_TAB_NAME_CONSISTENCY:
            self._refresh_audit_name_consistency_panel()

    def _open_audit_window(self) -> None:
        if self.audit_window is None:
            self._build_audit_window()
        if self.audit_search_scope_combo is not None:
            default_scope = self._default_audit_search_scope()
            scope_index = self.audit_search_scope_combo.findData(default_scope)
            if scope_index >= 0:
                self.audit_search_scope_combo.setCurrentIndex(scope_index)
        if self.audit_sanitize_scope_combo is not None:
            default_scope = self._default_audit_search_scope()
            scope_index = self.audit_sanitize_scope_combo.findData(
                default_scope)
            if scope_index >= 0:
                self.audit_sanitize_scope_combo.setCurrentIndex(scope_index)
        if self.audit_window is None:
            return
        self._refresh_audit_tab(self._current_audit_tab_index())
        self.audit_window.show()
        self.audit_window.raise_()
        self.audit_window.activateWindow()
        if self.audit_search_query_edit is not None:
            self.audit_search_query_edit.setFocus()

    def _build_audit_window(self) -> None:
        dialog = QDialog(cast(QWidget, self))
        dialog.setWindowTitle("Audit")
        dialog.setModal(False)
        dialog.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        dialog.resize(980, 650)

        root_layout = QVBoxLayout(dialog)
        tabs = QTabWidget()
        root_layout.addWidget(tabs, 1)

        search_tab = QWidget()
        search_layout = QVBoxLayout(search_tab)
        search_layout.setContentsMargins(8, 8, 8, 8)
        search_layout.setSpacing(8)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(6)
        query_edit = QLineEdit()
        query_edit.setPlaceholderText("Find...")
        query_edit.setClearButtonEnabled(True)
        query_edit.setStyleSheet(
            "QLineEdit { padding-right: 34px; } "
            "QLineEdit QToolButton { width: 26px; height: 26px; }"
        )
        controls_row.addWidget(query_edit, 2)

        scope_combo = QComboBox()
        scope_combo.addItem("Original", "original")
        scope_combo.addItem("Translation", "translation")
        scope_combo.addItem("Both", "both")
        controls_row.addWidget(scope_combo)
        replace_edit = QLineEdit()
        replace_edit.setPlaceholderText("Replace with...")
        replace_edit.setClearButtonEnabled(True)
        controls_row.addWidget(replace_edit, 2)
        case_sensitive_action = QAction("Aa", query_edit)
        case_sensitive_action.setCheckable(True)
        case_sensitive_action.setChecked(False)
        case_sensitive_action.setToolTip("Case sensitive search/replace")
        case_sensitive_action.setIcon(self._audit_case_toggle_icon(False))
        query_edit.addAction(case_sensitive_action, QLineEdit.ActionPosition.TrailingPosition)
        replace_selected_btn = QPushButton("Replace Selected")
        replace_all_btn = QPushButton("Replace All")
        replace_selected_btn.setEnabled(False)
        replace_all_btn.setEnabled(False)
        controls_row.addWidget(replace_selected_btn)
        controls_row.addWidget(replace_all_btn)
        search_layout.addLayout(controls_row)

        results_list = QListWidget()
        search_layout.addWidget(results_list, 1)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(6)
        status_label = QLabel("Type to search.")
        footer_row.addWidget(status_label, 1)
        goto_btn = QPushButton("Go To")
        goto_btn.setEnabled(False)
        footer_row.addWidget(goto_btn)
        search_layout.addLayout(footer_row)

        tabs.addTab(search_tab, "Search")

        sanitize_tab = QWidget()
        sanitize_layout = QVBoxLayout(sanitize_tab)
        sanitize_layout.setContentsMargins(8, 8, 8, 8)
        sanitize_layout.setSpacing(8)

        sanitize_controls_row = QHBoxLayout()
        sanitize_controls_row.setContentsMargins(0, 0, 0, 0)
        sanitize_controls_row.setSpacing(6)
        sanitize_controls_row.addWidget(QLabel("Scope"))
        sanitize_scope_combo = QComboBox()
        sanitize_scope_combo.addItem("Original", "original")
        sanitize_scope_combo.addItem("Translation", "translation")
        sanitize_scope_combo.addItem("Both", "both")
        sanitize_controls_row.addWidget(sanitize_scope_combo)
        sanitize_controls_row.addStretch(1)
        apply_selected_btn = QPushButton("Apply Selected Rule")
        sanitize_controls_row.addWidget(apply_selected_btn)
        sanitize_layout.addLayout(sanitize_controls_row)

        sanitize_splitter = QSplitter(Qt.Orientation.Horizontal)
        sanitize_layout.addWidget(sanitize_splitter, 1)

        sanitize_rules_panel = QWidget()
        sanitize_rules_layout = QVBoxLayout(sanitize_rules_panel)
        sanitize_rules_layout.setContentsMargins(0, 0, 0, 0)
        sanitize_rules_layout.setSpacing(6)
        sanitize_rules_layout.addWidget(QLabel("Character Rules"))
        sanitize_rules_list = QListWidget()
        sanitize_rules_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        sanitize_rules_layout.addWidget(sanitize_rules_list, 1)
        sanitize_splitter.addWidget(sanitize_rules_panel)

        sanitize_occ_panel = QWidget()
        sanitize_occ_layout = QVBoxLayout(sanitize_occ_panel)
        sanitize_occ_layout.setContentsMargins(0, 0, 0, 0)
        sanitize_occ_layout.setSpacing(6)
        sanitize_occ_layout.addWidget(
            QLabel("Potential Replacements (selected rule)"))
        sanitize_occurrences_list = QListWidget()
        sanitize_occurrences_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        sanitize_occ_layout.addWidget(sanitize_occurrences_list, 1)
        sanitize_occ_footer = QHBoxLayout()
        sanitize_occ_footer.setContentsMargins(0, 0, 0, 0)
        sanitize_occ_footer.setSpacing(6)
        sanitize_summary_label = QLabel("Potential replacements: 0")
        sanitize_occ_footer.addWidget(sanitize_summary_label, 1)
        sanitize_goto_btn = QPushButton("Go To")
        sanitize_goto_btn.setEnabled(False)
        sanitize_occ_footer.addWidget(sanitize_goto_btn)
        sanitize_occ_layout.addLayout(sanitize_occ_footer)
        sanitize_splitter.addWidget(sanitize_occ_panel)
        sanitize_splitter.setStretchFactor(0, 4)
        sanitize_splitter.setStretchFactor(1, 6)

        tabs.addTab(sanitize_tab, "Sanitize")

        control_tab = QWidget()
        control_layout = QVBoxLayout(control_tab)
        control_layout.setContentsMargins(8, 8, 8, 8)
        control_layout.setSpacing(8)

        control_controls_row = QHBoxLayout()
        control_controls_row.setContentsMargins(0, 0, 0, 0)
        control_controls_row.setSpacing(6)
        control_only_translated_check = QCheckBox("Only translated blocks")
        control_only_translated_check.setChecked(True)
        control_controls_row.addWidget(control_only_translated_check)
        control_controls_row.addStretch(1)
        control_refresh_btn = QPushButton("Refresh")
        control_controls_row.addWidget(control_refresh_btn)
        control_layout.addLayout(control_controls_row)

        control_results_list = QListWidget()
        control_layout.addWidget(control_results_list, 1)

        control_footer = QHBoxLayout()
        control_footer.setContentsMargins(0, 0, 0, 0)
        control_footer.setSpacing(6)
        control_status_label = QLabel(
            "Press Refresh to scan control-code mismatches.")
        control_footer.addWidget(control_status_label, 1)
        control_goto_btn = QPushButton("Go To")
        control_goto_btn.setEnabled(False)
        control_footer.addWidget(control_goto_btn)
        control_layout.addLayout(control_footer)

        tabs.addTab(control_tab, "Control Mismatch")

        consistency_tab = QWidget()
        consistency_layout = QVBoxLayout(consistency_tab)
        consistency_layout.setContentsMargins(8, 8, 8, 8)
        consistency_layout.setSpacing(8)

        consistency_controls_row = QHBoxLayout()
        consistency_controls_row.setContentsMargins(0, 0, 0, 0)
        consistency_controls_row.setSpacing(6)
        consistency_only_inconsistent_check = QCheckBox("Only inconsistent")
        consistency_only_inconsistent_check.setChecked(True)
        consistency_controls_row.addWidget(consistency_only_inconsistent_check)
        consistency_dialogue_only_check = QCheckBox("Dialogue only")
        consistency_dialogue_only_check.setChecked(True)
        consistency_controls_row.addWidget(consistency_dialogue_only_check)
        consistency_controls_row.addWidget(QLabel("Sort"))
        consistency_sort_combo = QComboBox()
        consistency_sort_combo.addItem("Source order", "source_order")
        consistency_sort_combo.addItem("Most duplicates", "occurrence")
        consistency_sort_combo.addItem("Most variants", "variants")
        consistency_sort_combo.addItem("A-Z", "alphabetical")
        consistency_controls_row.addWidget(consistency_sort_combo)
        consistency_controls_row.addStretch(1)
        consistency_refresh_btn = QPushButton("Refresh")
        consistency_controls_row.addWidget(consistency_refresh_btn)
        consistency_layout.addLayout(consistency_controls_row)

        consistency_splitter = QSplitter(Qt.Orientation.Horizontal)
        consistency_layout.addWidget(consistency_splitter, 1)

        consistency_groups_panel = QWidget()
        consistency_groups_layout = QVBoxLayout(consistency_groups_panel)
        consistency_groups_layout.setContentsMargins(0, 0, 0, 0)
        consistency_groups_layout.setSpacing(6)
        consistency_groups_layout.addWidget(QLabel("Duplicate Source Groups"))
        consistency_groups_list = QListWidget()
        consistency_groups_layout.addWidget(consistency_groups_list, 1)
        consistency_splitter.addWidget(consistency_groups_panel)

        consistency_entries_panel = QWidget()
        consistency_entries_layout = QVBoxLayout(consistency_entries_panel)
        consistency_entries_layout.setContentsMargins(0, 0, 0, 0)
        consistency_entries_layout.setSpacing(6)
        consistency_entries_layout.addWidget(
            QLabel("Entries In Selected Group"))
        consistency_entries_list = QListWidget()
        consistency_entries_layout.addWidget(consistency_entries_list, 1)
        consistency_entries_layout.addWidget(QLabel("Original Source"))
        consistency_source_edit = QPlainTextEdit()
        consistency_source_edit.setReadOnly(True)
        consistency_source_edit.setPlaceholderText(
            "Selected duplicate group's source text."
        )
        consistency_source_edit.setFixedHeight(84)
        consistency_source_highlighter = ControlCodeHighlighter(
            consistency_source_edit.document(),
            is_dark_palette(),
            color_code_resolver=self._color_for_rpgm_code,
            resolve_color_flow=True,
        )
        consistency_entries_layout.addWidget(consistency_source_edit)
        consistency_entries_layout.addWidget(QLabel("Sync Translation Target"))
        consistency_target_edit = QPlainTextEdit()
        consistency_target_edit.setPlaceholderText(
            "Type translation to apply to all entries in selected group."
        )
        consistency_target_edit.setFixedHeight(84)
        consistency_target_highlighter = ControlCodeHighlighter(
            consistency_target_edit.document(),
            is_dark_palette(),
            color_code_resolver=self._color_for_rpgm_code,
            resolve_color_flow=True,
        )
        consistency_entries_layout.addWidget(consistency_target_edit)
        consistency_actions_row = QHBoxLayout()
        consistency_actions_row.setContentsMargins(0, 0, 0, 0)
        consistency_actions_row.setSpacing(6)
        consistency_use_common_btn = QPushButton("Use Most Common")
        consistency_apply_btn = QPushButton("Apply To Group")
        consistency_goto_btn = QPushButton("Go To Entry")
        consistency_use_common_btn.setEnabled(False)
        consistency_apply_btn.setEnabled(False)
        consistency_goto_btn.setEnabled(False)
        consistency_actions_row.addWidget(consistency_use_common_btn)
        consistency_actions_row.addStretch(1)
        consistency_actions_row.addWidget(consistency_apply_btn)
        consistency_actions_row.addWidget(consistency_goto_btn)
        consistency_entries_layout.addLayout(consistency_actions_row)
        consistency_status_label = QLabel("Duplicate groups: 0 | Duplicate entries: 0")
        consistency_entries_layout.addWidget(consistency_status_label)
        consistency_splitter.addWidget(consistency_entries_panel)
        consistency_splitter.setStretchFactor(0, 4)
        consistency_splitter.setStretchFactor(1, 6)

        tabs.addTab(consistency_tab, "Consistency")

        term_tab = QWidget()
        term_layout = QVBoxLayout(term_tab)
        term_layout.setContentsMargins(8, 8, 8, 8)
        term_layout.setSpacing(8)

        term_controls_row = QHBoxLayout()
        term_controls_row.setContentsMargins(0, 0, 0, 0)
        term_controls_row.setSpacing(6)
        term_controls_row.addWidget(QLabel("Source term"))
        term_query_edit = QLineEdit()
        term_query_edit.setPlaceholderText("e.g. 魔王")
        term_query_edit.setClearButtonEnabled(True)
        term_controls_row.addWidget(term_query_edit, 1)
        term_controls_row.addWidget(QLabel("Candidates"))
        term_candidates_edit = QLineEdit()
        term_candidates_edit.setPlaceholderText(
            "comma / | / ; separated, e.g. Demon Lord, Demon King"
        )
        term_candidates_edit.setClearButtonEnabled(True)
        term_controls_row.addWidget(term_candidates_edit, 2)
        term_dialogue_only_check = QCheckBox("Dialogue only")
        term_dialogue_only_check.setChecked(True)
        term_controls_row.addWidget(term_dialogue_only_check)
        term_refresh_btn = QPushButton("Refresh")
        term_controls_row.addWidget(term_refresh_btn)
        term_layout.addLayout(term_controls_row)

        term_vertical_splitter = QSplitter(Qt.Orientation.Vertical)
        term_layout.addWidget(term_vertical_splitter, 1)

        term_splitter = QSplitter(Qt.Orientation.Horizontal)
        term_vertical_splitter.addWidget(term_splitter)

        term_variants_panel = QWidget()
        term_variants_layout = QVBoxLayout(term_variants_panel)
        term_variants_layout.setContentsMargins(0, 0, 0, 0)
        term_variants_layout.setSpacing(6)
        term_variants_layout.addWidget(QLabel("Translation Variants"))
        term_variants_list = QListWidget()
        term_variants_layout.addWidget(term_variants_list, 1)
        term_splitter.addWidget(term_variants_panel)

        term_hits_panel = QWidget()
        term_hits_layout = QVBoxLayout(term_hits_panel)
        term_hits_layout.setContentsMargins(0, 0, 0, 0)
        term_hits_layout.setSpacing(6)
        term_hits_layout.addWidget(QLabel("Matching Source Lines"))
        term_hits_list = QListWidget()
        term_hits_layout.addWidget(term_hits_list, 1)
        term_footer = QHBoxLayout()
        term_footer.setContentsMargins(0, 0, 0, 0)
        term_footer.setSpacing(6)
        term_status_label = QLabel("Type a JP source term to inspect variants.")
        term_footer.addWidget(term_status_label, 1)
        term_apply_canonical_btn = QPushButton("Apply To Canonical")
        term_apply_canonical_btn.setEnabled(False)
        term_footer.addWidget(term_apply_canonical_btn)
        term_goto_btn = QPushButton("Go To")
        term_goto_btn.setEnabled(False)
        term_footer.addWidget(term_goto_btn)
        term_hits_layout.addLayout(term_footer)
        term_splitter.addWidget(term_hits_panel)
        term_splitter.setStretchFactor(0, 4)
        term_splitter.setStretchFactor(1, 6)

        term_suggest_row = QHBoxLayout()
        term_suggest_row.setContentsMargins(0, 0, 0, 0)
        term_suggest_row.setSpacing(6)
        term_suggest_row.addWidget(QLabel("Frequent Terms"))
        term_suggest_row.addStretch(1)
        term_suggest_toggle_btn = QPushButton("Collapse")
        term_suggest_toggle_btn.setCheckable(True)
        term_suggest_toggle_btn.setChecked(True)
        term_suggest_toggle_btn.setToolTip(
            "Collapse/expand the frequent terms section."
        )
        term_suggest_row.addWidget(term_suggest_toggle_btn)
        term_suggest_refresh_btn = QPushButton("Refresh Suggestions")
        term_suggest_row.addWidget(term_suggest_refresh_btn)

        term_suggest_section = QWidget()
        term_suggest_section_layout = QVBoxLayout(term_suggest_section)
        term_suggest_section_layout.setContentsMargins(0, 0, 0, 0)
        term_suggest_section_layout.setSpacing(6)
        term_suggest_section_layout.addLayout(term_suggest_row)

        term_suggest_splitter = QSplitter(Qt.Orientation.Horizontal)
        term_suggest_section_layout.addWidget(term_suggest_splitter, 1)

        term_suggest_jp_panel = QWidget()
        term_suggest_jp_layout = QVBoxLayout(term_suggest_jp_panel)
        term_suggest_jp_layout.setContentsMargins(0, 0, 0, 0)
        term_suggest_jp_layout.setSpacing(6)
        term_suggest_jp_layout.addWidget(QLabel("JP frequent words/phrases"))
        term_suggest_jp_list = QListWidget()
        term_suggest_jp_layout.addWidget(term_suggest_jp_list, 1)
        term_suggest_splitter.addWidget(term_suggest_jp_panel)

        term_suggest_en_panel = QWidget()
        term_suggest_en_layout = QVBoxLayout(term_suggest_en_panel)
        term_suggest_en_layout.setContentsMargins(0, 0, 0, 0)
        term_suggest_en_layout.setSpacing(6)
        term_suggest_en_layout.addWidget(QLabel("TL frequent words/phrases"))
        term_suggest_en_list = QListWidget()
        term_suggest_en_layout.addWidget(term_suggest_en_list, 1)
        term_suggest_splitter.addWidget(term_suggest_en_panel)
        term_suggest_splitter.setStretchFactor(0, 1)
        term_suggest_splitter.setStretchFactor(1, 1)
        term_vertical_splitter.addWidget(term_suggest_section)
        term_vertical_splitter.setStretchFactor(0, 5)
        term_vertical_splitter.setStretchFactor(1, 2)

        term_suggest_size_state: dict[str, int] = {"height": 220}

        def _remember_term_suggest_height() -> None:
            sizes = term_vertical_splitter.sizes()
            if len(sizes) < 2:
                return
            lower_height = sizes[1]
            if lower_height > 0:
                term_suggest_size_state["height"] = lower_height

        def _set_term_suggest_section_visible(visible: bool) -> None:
            sizes = term_vertical_splitter.sizes()
            total_height = sum(sizes) if sizes else 0
            if total_height <= 0:
                total_height = term_vertical_splitter.height()
            if total_height <= 0:
                total_height = 1
            if visible:
                requested_height = max(80, term_suggest_size_state["height"])
                if requested_height >= total_height:
                    requested_height = max(1, total_height // 3)
                term_vertical_splitter.setSizes(
                    [max(1, total_height - requested_height), requested_height]
                )
                term_suggest_toggle_btn.setText("Collapse")
            else:
                _remember_term_suggest_height()
                term_vertical_splitter.setSizes([max(1, total_height), 0])
                term_suggest_toggle_btn.setText("Expand")

        term_vertical_splitter.splitterMoved.connect(
            lambda _pos, _index: _remember_term_suggest_height()
        )
        term_suggest_toggle_btn.toggled.connect(
            lambda checked: _set_term_suggest_section_visible(bool(checked))
        )
        QTimer.singleShot(0, lambda: _set_term_suggest_section_visible(True))

        tabs.addTab(term_tab, "Term Usage")

        name_consistency_tab = QWidget()
        name_consistency_layout = QVBoxLayout(name_consistency_tab)
        name_consistency_layout.setContentsMargins(8, 8, 8, 8)
        name_consistency_layout.setSpacing(8)

        name_consistency_controls_row = QHBoxLayout()
        name_consistency_controls_row.setContentsMargins(0, 0, 0, 0)
        name_consistency_controls_row.setSpacing(6)
        name_consistency_dialogue_only_check = QCheckBox("Dialogue only")
        name_consistency_dialogue_only_check.setChecked(True)
        name_consistency_controls_row.addWidget(name_consistency_dialogue_only_check)
        name_consistency_only_discrepancy_check = QCheckBox("Only discrepancies")
        name_consistency_only_discrepancy_check.setChecked(True)
        name_consistency_controls_row.addWidget(name_consistency_only_discrepancy_check)
        name_consistency_controls_row.addWidget(QLabel("Search"))
        name_consistency_filter_edit = QLineEdit()
        name_consistency_filter_edit.setPlaceholderText(
            "Source / expected TL / misc context"
        )
        name_consistency_filter_edit.setClearButtonEnabled(True)
        name_consistency_controls_row.addWidget(name_consistency_filter_edit, 1)
        name_consistency_controls_row.addWidget(QLabel("Sort"))
        name_consistency_sort_combo = QComboBox()
        name_consistency_sort_combo.addItem("Most misses", "hits_desc")
        name_consistency_sort_combo.addItem("Most checked", "checked_desc")
        name_consistency_sort_combo.addItem("Source A-Z", "source_az")
        name_consistency_sort_combo.addItem("Source Z-A", "source_za")
        name_consistency_sort_combo.addItem("Misc file A-Z", "path_az")
        name_consistency_controls_row.addWidget(name_consistency_sort_combo)
        name_consistency_controls_row.addStretch(1)
        name_consistency_refresh_btn = QPushButton("Refresh")
        name_consistency_controls_row.addWidget(name_consistency_refresh_btn)
        name_consistency_layout.addLayout(name_consistency_controls_row)

        name_consistency_splitter = QSplitter(Qt.Orientation.Horizontal)
        name_consistency_layout.addWidget(name_consistency_splitter, 1)

        name_consistency_groups_panel = QWidget()
        name_consistency_groups_layout = QVBoxLayout(name_consistency_groups_panel)
        name_consistency_groups_layout.setContentsMargins(0, 0, 0, 0)
        name_consistency_groups_layout.setSpacing(6)
        name_consistency_groups_layout.addWidget(QLabel("Inconsistent Source Terms"))
        name_consistency_groups_list = QListWidget()
        name_consistency_groups_layout.addWidget(name_consistency_groups_list, 1)
        name_consistency_splitter.addWidget(name_consistency_groups_panel)

        name_consistency_entries_panel = QWidget()
        name_consistency_entries_layout = QVBoxLayout(name_consistency_entries_panel)
        name_consistency_entries_layout.setContentsMargins(0, 0, 0, 0)
        name_consistency_entries_layout.setSpacing(6)
        name_consistency_entries_layout.addWidget(QLabel("Dialogue Hits"))
        name_consistency_entries_list = QListWidget()
        name_consistency_entries_layout.addWidget(name_consistency_entries_list, 1)
        name_consistency_replace_row = QHBoxLayout()
        name_consistency_replace_row.setContentsMargins(0, 0, 0, 0)
        name_consistency_replace_row.setSpacing(6)
        name_consistency_replace_row.addWidget(QLabel("Seen as"))
        name_consistency_replace_find_edit = QLineEdit()
        name_consistency_replace_find_edit.setPlaceholderText(
            "TL term currently used in dialogue hits"
        )
        name_consistency_replace_find_edit.setClearButtonEnabled(True)
        name_consistency_replace_row.addWidget(name_consistency_replace_find_edit, 1)
        name_consistency_replace_btn = QPushButton("Replace In Hits")
        name_consistency_replace_btn.setEnabled(False)
        name_consistency_replace_row.addWidget(name_consistency_replace_btn)
        name_consistency_entries_layout.addLayout(name_consistency_replace_row)
        name_consistency_footer = QHBoxLayout()
        name_consistency_footer.setContentsMargins(0, 0, 0, 0)
        name_consistency_footer.setSpacing(6)
        name_consistency_status_label = QLabel(
            "Checks repeated source terms for inconsistent TL naming."
        )
        name_consistency_footer.addWidget(name_consistency_status_label, 1)
        name_consistency_goto_btn = QPushButton("Go To")
        name_consistency_goto_btn.setEnabled(False)
        name_consistency_footer.addWidget(name_consistency_goto_btn)
        name_consistency_entries_layout.addLayout(name_consistency_footer)
        name_consistency_splitter.addWidget(name_consistency_entries_panel)
        name_consistency_splitter.setStretchFactor(0, 4)
        name_consistency_splitter.setStretchFactor(1, 6)

        tabs.addTab(name_consistency_tab, "Name Consistency")

        search_progress_overlay = self._create_audit_progress_overlay(
            results_list)
        sanitize_progress_overlay = self._create_audit_progress_overlay(
            sanitize_occurrences_list
        )
        control_progress_overlay = self._create_audit_progress_overlay(
            control_results_list)
        term_variants_progress_overlay = self._create_audit_progress_overlay(
            term_variants_list
        )
        term_hits_progress_overlay = self._create_audit_progress_overlay(
            term_hits_list
        )

        self.audit_tabs = tabs
        self.audit_window = dialog
        self.audit_search_query_edit = query_edit
        self.audit_search_scope_combo = scope_combo
        self.audit_search_replace_edit = replace_edit
        self.audit_search_case_sensitive_check = case_sensitive_action
        self.audit_search_results_list = results_list
        self.audit_search_status_label = status_label
        self.audit_search_goto_btn = goto_btn
        self.audit_search_replace_selected_btn = replace_selected_btn
        self.audit_search_replace_all_btn = replace_all_btn
        self.audit_search_progress_overlay = search_progress_overlay
        self.audit_search_timer = QTimer(dialog)
        self.audit_search_timer.setSingleShot(True)
        self.audit_search_timer.setInterval(180)
        self.audit_search_timer.timeout.connect(self._run_audit_search)
        self.audit_sanitize_scope_combo = sanitize_scope_combo
        self.audit_sanitize_rules_list = sanitize_rules_list
        self.audit_sanitize_occurrences_list = sanitize_occurrences_list
        self.audit_sanitize_summary_label = sanitize_summary_label
        self.audit_sanitize_goto_btn = sanitize_goto_btn
        self.audit_sanitize_apply_selected_btn = apply_selected_btn
        self.audit_sanitize_progress_overlay = sanitize_progress_overlay
        self.audit_control_mismatch_results_list = control_results_list
        self.audit_control_mismatch_status_label = control_status_label
        self.audit_control_mismatch_goto_btn = control_goto_btn
        self.audit_control_mismatch_progress_overlay = control_progress_overlay
        self.audit_control_mismatch_only_translated_check = control_only_translated_check
        self.audit_consistency_only_inconsistent_check = consistency_only_inconsistent_check
        self.audit_consistency_dialogue_only_check = consistency_dialogue_only_check
        self.audit_consistency_sort_combo = consistency_sort_combo
        self.audit_consistency_groups_list = consistency_groups_list
        self.audit_consistency_entries_list = consistency_entries_list
        self.audit_consistency_source_edit = consistency_source_edit
        self.audit_consistency_target_edit = consistency_target_edit
        self.audit_consistency_source_highlighter = consistency_source_highlighter
        self.audit_consistency_target_highlighter = consistency_target_highlighter
        self.audit_consistency_status_label = consistency_status_label
        self.audit_consistency_goto_btn = consistency_goto_btn
        self.audit_consistency_apply_btn = consistency_apply_btn
        self.audit_consistency_use_common_btn = consistency_use_common_btn
        self.audit_term_query_edit = term_query_edit
        self.audit_term_candidates_edit = term_candidates_edit
        self.audit_term_dialogue_only_check = term_dialogue_only_check
        self.audit_term_variants_list = term_variants_list
        self.audit_term_hits_list = term_hits_list
        self.audit_term_status_label = term_status_label
        self.audit_term_goto_btn = term_goto_btn
        self.audit_term_apply_canonical_btn = term_apply_canonical_btn
        self.audit_term_suggest_jp_list = term_suggest_jp_list
        self.audit_term_suggest_en_list = term_suggest_en_list
        self.audit_term_suggest_refresh_btn = term_suggest_refresh_btn
        self.audit_term_variants_progress_overlay = term_variants_progress_overlay
        self.audit_term_hits_progress_overlay = term_hits_progress_overlay
        self.audit_name_consistency_dialogue_only_check = name_consistency_dialogue_only_check
        self.audit_name_consistency_only_discrepancy_check = (
            name_consistency_only_discrepancy_check
        )
        self.audit_name_consistency_filter_edit = name_consistency_filter_edit
        self.audit_name_consistency_sort_combo = name_consistency_sort_combo
        self.audit_name_consistency_groups_list = name_consistency_groups_list
        self.audit_name_consistency_entries_list = name_consistency_entries_list
        self.audit_name_consistency_replace_find_edit = name_consistency_replace_find_edit
        self.audit_name_consistency_replace_btn = name_consistency_replace_btn
        self.audit_name_consistency_status_label = name_consistency_status_label
        self.audit_name_consistency_goto_btn = name_consistency_goto_btn

        for rule_id, label, find_text, replace_text in SANITIZE_CHAR_RULES:
            item = QListWidgetItem()
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                {
                    "rule_id": rule_id,
                    "label": label,
                    "find_text": find_text,
                    "replace_text": replace_text,
                },
            )
            sanitize_rules_list.addItem(item)

        scope_index = scope_combo.findData(self._default_audit_search_scope())
        if scope_index >= 0:
            scope_combo.setCurrentIndex(scope_index)
        sanitize_scope_index = sanitize_scope_combo.findData(
            self._default_audit_search_scope())
        if sanitize_scope_index >= 0:
            sanitize_scope_combo.setCurrentIndex(sanitize_scope_index)
        if sanitize_rules_list.count() > 0:
            sanitize_rules_list.setCurrentRow(0)

        query_edit.returnPressed.connect(self._run_audit_search)
        query_edit.textChanged.connect(
            lambda _text: (
                self._schedule_audit_search(),
                self._refresh_audit_search_replace_preview(),
            ))
        replace_edit.textChanged.connect(
            lambda _text: self._refresh_audit_search_replace_preview()
        )
        scope_combo.currentIndexChanged.connect(
            lambda _index: (
                self._schedule_audit_search(),
                self._refresh_audit_search_replace_preview(),
            )
        )
        case_sensitive_action.toggled.connect(
            lambda _checked: (
                case_sensitive_action.setIcon(
                    self._audit_case_toggle_icon(
                        bool(case_sensitive_action.isChecked())
                    )
                ),
                self._schedule_audit_search(),
                self._refresh_audit_search_replace_preview(),
            )
        )
        goto_btn.clicked.connect(self._go_to_selected_audit_result)
        replace_selected_btn.clicked.connect(
            self._replace_selected_audit_search_result
        )
        replace_all_btn.clicked.connect(self._replace_all_audit_search_results)
        results_list.itemDoubleClicked.connect(
            lambda _item: self._go_to_selected_audit_result()
        )
        results_list.itemActivated.connect(
            lambda _item: self._go_to_selected_audit_result()
        )
        results_list.currentItemChanged.connect(
            lambda current, _previous: (
                goto_btn.setEnabled(current is not None),
                replace_selected_btn.setEnabled(current is not None),
                self._refresh_audit_search_replace_preview(),
            )
        )
        replace_edit.returnPressed.connect(self._replace_selected_audit_search_result)
        sanitize_scope_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_audit_sanitize_panel()
        )
        sanitize_rules_list.currentItemChanged.connect(
            lambda _current, _previous: self._refresh_audit_sanitize_occurrences()
        )
        sanitize_rules_list.customContextMenuRequested.connect(
            self._on_audit_sanitize_rules_context_menu
        )
        sanitize_occurrences_list.currentItemChanged.connect(
            lambda current, _previous: sanitize_goto_btn.setEnabled(
                current is not None)
        )
        sanitize_occurrences_list.customContextMenuRequested.connect(
            self._on_audit_sanitize_occurrences_context_menu
        )
        sanitize_occurrences_list.itemDoubleClicked.connect(
            lambda _item: self._go_to_selected_audit_sanitize_occurrence()
        )
        sanitize_occurrences_list.itemActivated.connect(
            lambda _item: self._go_to_selected_audit_sanitize_occurrence()
        )
        sanitize_goto_btn.clicked.connect(
            self._go_to_selected_audit_sanitize_occurrence)
        apply_selected_btn.clicked.connect(
            self._apply_selected_audit_sanitize_rule)
        control_only_translated_check.toggled.connect(
            lambda _checked: self._refresh_audit_control_mismatch_panel()
        )
        control_refresh_btn.clicked.connect(
            self._refresh_audit_control_mismatch_panel)
        control_results_list.currentItemChanged.connect(
            lambda current, _previous: control_goto_btn.setEnabled(
                current is not None)
        )
        control_results_list.itemDoubleClicked.connect(
            lambda _item: self._go_to_selected_audit_control_mismatch()
        )
        control_results_list.itemActivated.connect(
            lambda _item: self._go_to_selected_audit_control_mismatch()
        )
        control_goto_btn.clicked.connect(
            self._go_to_selected_audit_control_mismatch)
        consistency_only_inconsistent_check.toggled.connect(
            lambda _checked: self._refresh_audit_consistency_panel()
        )
        consistency_dialogue_only_check.toggled.connect(
            lambda _checked: self._refresh_audit_consistency_panel()
        )
        consistency_refresh_btn.clicked.connect(
            lambda: self._refresh_audit_consistency_panel()
        )
        consistency_sort_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_audit_consistency_panel()
        )
        consistency_groups_list.currentItemChanged.connect(
            lambda _current, _previous: self._refresh_audit_consistency_entries()
        )
        consistency_entries_list.currentItemChanged.connect(
            lambda current, _previous: (
                consistency_goto_btn.setEnabled(current is not None),
                self._on_audit_consistency_entry_selected(),
            )
        )
        consistency_entries_list.itemDoubleClicked.connect(
            lambda _item: self._go_to_selected_audit_consistency_entry()
        )
        consistency_entries_list.itemActivated.connect(
            lambda _item: self._go_to_selected_audit_consistency_entry()
        )
        consistency_goto_btn.clicked.connect(
            self._go_to_selected_audit_consistency_entry
        )
        consistency_use_common_btn.clicked.connect(
            self._use_most_common_audit_consistency_translation
        )
        consistency_apply_btn.clicked.connect(
            self._apply_audit_consistency_target_to_group
        )
        term_query_edit.textChanged.connect(
            lambda _text: self._refresh_audit_term_panel()
        )
        term_query_edit.returnPressed.connect(self._refresh_audit_term_panel)
        term_candidates_edit.textChanged.connect(
            lambda _text: self._refresh_audit_term_panel()
        )
        term_candidates_edit.returnPressed.connect(self._refresh_audit_term_panel)
        term_dialogue_only_check.toggled.connect(
            lambda _checked: (
                self._refresh_audit_term_panel(),
                self._refresh_audit_term_suggestions_panel(),
            )
        )
        term_refresh_btn.clicked.connect(
            lambda: (
                self._refresh_audit_term_panel(),
                self._refresh_audit_term_suggestions_panel(),
            )
        )
        term_suggest_refresh_btn.clicked.connect(self._refresh_audit_term_suggestions_panel)
        term_variants_list.currentItemChanged.connect(
            lambda _current, _previous: (
                self._refresh_audit_term_hits(),
                self._refresh_audit_term_apply_state(),
            )
        )
        term_suggest_jp_list.itemActivated.connect(
            lambda _item: self._use_selected_audit_term_jp_suggestion()
        )
        term_suggest_jp_list.itemDoubleClicked.connect(
            lambda _item: self._use_selected_audit_term_jp_suggestion()
        )
        term_suggest_en_list.itemActivated.connect(
            lambda _item: self._append_selected_audit_term_en_suggestion()
        )
        term_suggest_en_list.itemDoubleClicked.connect(
            lambda _item: self._append_selected_audit_term_en_suggestion()
        )
        term_hits_list.currentItemChanged.connect(
            lambda current, _previous: term_goto_btn.setEnabled(current is not None)
        )
        term_hits_list.itemDoubleClicked.connect(
            lambda _item: self._go_to_selected_audit_term_hit()
        )
        term_hits_list.itemActivated.connect(
            lambda _item: self._go_to_selected_audit_term_hit()
        )
        term_apply_canonical_btn.clicked.connect(
            self._apply_selected_audit_term_variant_to_canonical
        )
        term_goto_btn.clicked.connect(self._go_to_selected_audit_term_hit)
        name_consistency_dialogue_only_check.toggled.connect(
            lambda _checked: self._refresh_audit_name_consistency_panel()
        )
        name_consistency_only_discrepancy_check.toggled.connect(
            lambda _checked: self._refresh_audit_name_consistency_panel()
        )
        name_consistency_filter_edit.textChanged.connect(
            lambda _text: self._refresh_audit_name_consistency_panel()
        )
        name_consistency_sort_combo.currentIndexChanged.connect(
            lambda _index: self._refresh_audit_name_consistency_panel()
        )
        name_consistency_refresh_btn.clicked.connect(
            self._refresh_audit_name_consistency_panel
        )
        name_consistency_groups_list.currentItemChanged.connect(
            lambda _current, _previous: (
                self._refresh_audit_name_consistency_entries(),
                self._refresh_audit_name_consistency_replace_state(),
            )
        )
        name_consistency_entries_list.currentItemChanged.connect(
            lambda current, _previous: name_consistency_goto_btn.setEnabled(
                current is not None
            )
        )
        name_consistency_replace_find_edit.textChanged.connect(
            lambda _text: self._refresh_audit_name_consistency_replace_state()
        )
        name_consistency_replace_find_edit.returnPressed.connect(
            self._apply_audit_name_consistency_replace_in_hits
        )
        name_consistency_replace_btn.clicked.connect(
            self._apply_audit_name_consistency_replace_in_hits
        )
        name_consistency_entries_list.itemDoubleClicked.connect(
            lambda _item: self._go_to_selected_audit_name_consistency_entry()
        )
        name_consistency_entries_list.itemActivated.connect(
            lambda _item: self._go_to_selected_audit_name_consistency_entry()
        )
        name_consistency_goto_btn.clicked.connect(
            self._go_to_selected_audit_name_consistency_entry
        )
        tabs.currentChanged.connect(self._on_audit_tab_changed)

        self._refresh_audit_tab(tabs.currentIndex())

    def _on_audit_tab_changed(self, index: int) -> None:
        self._hide_audit_progress_overlay(self.audit_search_progress_overlay)
        self._hide_audit_progress_overlay(self.audit_sanitize_progress_overlay)
        self._hide_audit_progress_overlay(
            self.audit_control_mismatch_progress_overlay)
        self._hide_audit_progress_overlay(self.audit_term_variants_progress_overlay)
        self._hide_audit_progress_overlay(self.audit_term_hits_progress_overlay)
        self._refresh_audit_tab(index)
