from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .audit_constants import SANITIZE_CHAR_RULES


class _AuditWindowHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditWindowMixin(_AuditWindowHostTypingFallback):
    def _default_audit_search_scope(self) -> str:
        return "translation" if self._is_translator_mode() else "original"

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
            self._refresh_audit_sanitize_panel()
        self._refresh_audit_control_mismatch_panel()
        if self.audit_window is None:
            return
        self.audit_window.show()
        self.audit_window.raise_()
        self.audit_window.activateWindow()
        if self.audit_search_query_edit is not None:
            self.audit_search_query_edit.setFocus()

    def _build_audit_window(self) -> None:
        dialog = QDialog(cast(QWidget, self))
        dialog.setWindowTitle("Audit")
        dialog.setModal(False)
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
        controls_row.addWidget(query_edit, 2)

        scope_combo = QComboBox()
        scope_combo.addItem("Original", "original")
        scope_combo.addItem("Translation", "translation")
        scope_combo.addItem("Both", "both")
        controls_row.addWidget(scope_combo)
        case_sensitive_check = QCheckBox("Case sensitive")
        case_sensitive_check.setChecked(False)
        controls_row.addWidget(case_sensitive_check)
        replace_edit = QLineEdit()
        replace_edit.setPlaceholderText("Replace with...")
        controls_row.addWidget(replace_edit, 2)
        replace_selected_btn = QPushButton("Replace Sel")
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

        search_progress_overlay = self._create_audit_progress_overlay(
            results_list)
        sanitize_progress_overlay = self._create_audit_progress_overlay(
            sanitize_occurrences_list
        )
        control_progress_overlay = self._create_audit_progress_overlay(
            control_results_list)

        self.audit_window = dialog
        self.audit_search_query_edit = query_edit
        self.audit_search_scope_combo = scope_combo
        self.audit_search_replace_edit = replace_edit
        self.audit_search_case_sensitive_check = case_sensitive_check
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
        case_sensitive_check.toggled.connect(
            lambda _checked: (
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
        tabs.currentChanged.connect(self._on_audit_tab_changed)

        self._refresh_audit_sanitize_panel()
        self._refresh_audit_control_mismatch_panel()
        self._refresh_audit_search_replace_preview()

    def _on_audit_tab_changed(self, _index: int) -> None:
        self._hide_audit_progress_overlay(self.audit_search_progress_overlay)
        self._hide_audit_progress_overlay(self.audit_sanitize_progress_overlay)
        self._hide_audit_progress_overlay(
            self.audit_control_mismatch_progress_overlay)
        self._refresh_audit_sanitize_panel()
