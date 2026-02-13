from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import sys
from pathlib import Path
from time import monotonic
from typing import Any, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QCursor,
    QFont,
    QKeySequence,
    QKeyEvent,
    QMouseEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from .helpers import (
        DialogueIndexDB,
        DialogueVersionDB,
        DialogueSegment,
        FileSession,
        NO_SPEAKER_KEY,
        StructuralAction,
        looks_like_name_line,
        natural_sort_key,
        parse_dialogue_data,
        parse_dialogue_file,
    )
    from .helpers.audit import AuditMixin
    from .helpers.mixins import (
        PersistenceExportMixin,
        PresentationHelpersMixin,
        RenderMixin,
        StructuralEditingMixin,
        TranslationStateMixin,
        is_dark_palette,
    )
    from .helpers.ui import (
        ControlCodeHighlighter,
        DialogueBlockWidget,
        ItemNameDescriptionWidget,
        MassTranslateDialog,
        SpeakerManagerDialog,
    )
except ImportError:
    from helpers import (
        DialogueIndexDB,
        DialogueVersionDB,
        DialogueSegment,
        FileSession,
        NO_SPEAKER_KEY,
        StructuralAction,
        looks_like_name_line,
        natural_sort_key,
        parse_dialogue_data,
        parse_dialogue_file,
    )
    from helpers.audit import AuditMixin
    from helpers.mixins import (
        PersistenceExportMixin,
        PresentationHelpersMixin,
        RenderMixin,
        StructuralEditingMixin,
        TranslationStateMixin,
        is_dark_palette,
    )
    from helpers.ui import (
        ControlCodeHighlighter,
        DialogueBlockWidget,
        ItemNameDescriptionWidget,
        MassTranslateDialog,
        SpeakerManagerDialog,
    )

BlockWidgetType = DialogueBlockWidget | ItemNameDescriptionWidget


DEFAULT_THIN_WIDTH = 47
DEFAULT_WIDE_WIDTH = 60
DEFAULT_MAX_LINES = 4
DB_FILENAME = ".dialogue_editor_index.sqlite3"
VERSION_DB_FILENAME = ".dialogue_version_state.sqlite3"
TRANSLATION_STATE_FILENAME = ".dialogue_translation_state.json"
UI_STATE_FILENAME = ".dialogue_visual_editor_ui_state.json"


class DialogueVisualEditor(
    AuditMixin,
    RenderMixin,
    TranslationStateMixin,
    StructuralEditingMixin,
    PersistenceExportMixin,
    PresentationHelpersMixin,
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dialogue Visual Editor (Code 101/401)")
        self.resize(1320, 820)

        self.data_dir: Optional[Path] = None
        self.index_db: Optional[DialogueIndexDB] = None
        self.version_db: Optional[DialogueVersionDB] = None
        self.file_paths: list[Path] = []
        self.file_items: dict[Path, QListWidgetItem] = {}
        self.sessions: dict[Path, FileSession] = {}
        self.current_path: Optional[Path] = None
        self.current_segment_lookup: dict[str, DialogueSegment] = {}
        self.block_widgets: dict[str, BlockWidgetType] = {}
        self.cached_block_widgets_by_path: dict[Path,
                                                dict[str, BlockWidgetType]] = {}
        self.cached_block_uid_order_by_path: dict[Path, list[str]] = {}
        self.cached_block_view_meta_by_path: dict[Path, tuple[Any, ...]] = {}
        self.cached_block_containers_by_path: dict[Path, dict[str, Any]] = {}
        self.rendered_block_view_meta: Optional[tuple[Any, ...]] = None
        self.reference_summary_cache_by_path: dict[Path, dict[str, tuple[str, str]]] = {
        }
        self.main_render_progress_overlay: Optional[QLabel] = None
        self.rendered_blocks_path: Optional[Path] = None
        self.rendered_block_uid_order: list[str] = []
        self.selected_segment_uid: Optional[str] = None
        self.current_reference_map: dict[str, tuple[str, str]] = {}
        self.segment_uid_counter = 0
        self.translation_uid_counter = 0
        self.speaker_custom_colors: dict[str, str] = {}
        self.speaker_translation_map: dict[str, str] = {}
        self._speaker_auto_color_map: dict[str, str] = {}
        self._speaker_auto_color_theme_dark: Optional[bool] = None
        self._windowskin_text_colors: dict[int, str] = {}
        self._windowskin_text_colors_loaded = False
        self.translation_state_path: Optional[Path] = None
        self.ui_state_path = Path(
            __file__).resolve().with_name(UI_STATE_FILENAME)
        self.project_ui_settings_by_folder: dict[str, dict[str, Any]] = {}
        self._applying_project_ui_state = False
        self.translation_state: dict[str, Any] = {
            "version": 1,
            "uid_counter": 0,
            "speaker_map": {},
            "files": {},
        }
        self.audit_window: Optional[QDialog] = None
        self.audit_search_query_edit: Optional[QLineEdit] = None
        self.audit_search_replace_edit: Optional[QLineEdit] = None
        self.audit_search_case_sensitive_check: Optional[QAction] = None
        self.audit_search_scope_combo: Optional[QComboBox] = None
        self.audit_search_results_list: Optional[QListWidget] = None
        self.audit_search_status_label: Optional[QLabel] = None
        self.audit_search_goto_btn: Optional[QPushButton] = None
        self.audit_search_replace_selected_btn: Optional[QPushButton] = None
        self.audit_search_replace_all_btn: Optional[QPushButton] = None
        self.pending_audit_flash_uid: Optional[str] = None
        self.audit_pinned_uid: Optional[str] = None
        self.audit_search_progress_overlay: Optional[QLabel] = None
        self.audit_search_timer: Optional[QTimer] = None
        self.audit_sanitize_scope_combo: Optional[QComboBox] = None
        self.audit_sanitize_rules_list: Optional[QListWidget] = None
        self.audit_sanitize_occurrences_list: Optional[QListWidget] = None
        self.audit_sanitize_summary_label: Optional[QLabel] = None
        self.audit_sanitize_goto_btn: Optional[QPushButton] = None
        self.audit_sanitize_apply_selected_btn: Optional[QPushButton] = None
        self.audit_sanitize_progress_overlay: Optional[QLabel] = None
        self.audit_sanitize_ignored_entries_by_rule: dict[str, set[tuple[str, str]]] = {
        }
        self.audit_sanitize_total_hits = 0
        self.audit_sanitize_rules_with_hits = 0
        self.audit_control_mismatch_results_list: Optional[QListWidget] = None
        self.audit_control_mismatch_status_label: Optional[QLabel] = None
        self.audit_control_mismatch_goto_btn: Optional[QPushButton] = None
        self.audit_control_mismatch_progress_overlay: Optional[QLabel] = None
        self.audit_control_mismatch_only_translated_check: Optional[QCheckBox] = None
        self.audit_consistency_only_inconsistent_check: Optional[QCheckBox] = None
        self.audit_consistency_sort_combo: Optional[QComboBox] = None
        self.audit_consistency_groups_list: Optional[QListWidget] = None
        self.audit_consistency_entries_list: Optional[QListWidget] = None
        self.audit_consistency_source_edit: Optional[QPlainTextEdit] = None
        self.audit_consistency_target_edit: Optional[QPlainTextEdit] = None
        self.audit_consistency_status_label: Optional[QLabel] = None
        self.audit_consistency_goto_btn: Optional[QPushButton] = None
        self.audit_consistency_apply_btn: Optional[QPushButton] = None
        self.audit_consistency_use_common_btn: Optional[QPushButton] = None
        self.audit_cache_generation = 0
        self.audit_result_batch_size = 16
        self.audit_render_batch_interval_ms = 8
        self.audit_search_cache_key: Optional[tuple[int, str, str, bool]] = None
        self.audit_search_cache_records: list[dict[str, Any]] = []
        self.audit_search_render_records: list[dict[str, Any]] = []
        self.audit_search_render_index = 0
        self.audit_search_render_query = ""
        self.audit_search_render_scope = "original"
        self.audit_search_render_generation = 0
        self.audit_search_displayed_key: Optional[tuple[int, str, str, bool]] = None
        self.audit_search_display_complete = False
        self.audit_search_render_timer = QTimer(self)
        self.audit_search_render_timer.setSingleShot(True)
        self.audit_search_render_timer.timeout.connect(
            self._render_next_audit_search_batch
        )
        self.audit_sanitize_occurrence_cache_key: Optional[tuple[int, str, str]] = None
        self.audit_sanitize_occurrence_cache_payload: Optional[dict[str, Any]] = None
        self.audit_sanitize_occurrence_cache_by_key: dict[tuple[int, str, str], dict[str, Any]] = {
        }
        self.audit_sanitize_render_records: list[dict[str, Any]] = []
        self.audit_sanitize_render_index = 0
        self.audit_sanitize_render_rule_id = ""
        self.audit_sanitize_render_find_text = ""
        self.audit_sanitize_render_show_field_label = False
        self.audit_sanitize_render_generation = 0
        self.audit_sanitize_render_scope = "original"
        self.audit_sanitize_render_total_hits = 0
        self.audit_sanitize_render_entries = 0
        self.audit_sanitize_render_block_count = 0
        self.audit_sanitize_displayed_key: Optional[tuple[int, str, str]] = None
        self.audit_sanitize_display_complete = False
        self.audit_sanitize_built_view_keys: set[tuple[int, str, str]] = set()
        self.audit_sanitize_active_view_key: Optional[tuple[int, str, str]] = None
        self.audit_sanitize_render_timer = QTimer(self)
        self.audit_sanitize_render_timer.setSingleShot(True)
        self.audit_sanitize_render_timer.timeout.connect(
            self._render_next_audit_sanitize_occurrence_batch
        )
        self.audit_control_mismatch_cache_key: Optional[tuple[int, bool]] = None
        self.audit_control_mismatch_cache_records: list[dict[str, Any]] = []
        self.audit_control_mismatch_cache_scanned_blocks = 0
        self.audit_control_mismatch_render_records: list[dict[str, Any]] = []
        self.audit_control_mismatch_render_index = 0
        self.audit_control_mismatch_render_scanned_blocks = 0
        self.audit_control_mismatch_render_only_translated = True
        self.audit_control_mismatch_render_generation = 0
        self.audit_control_mismatch_displayed_key: Optional[tuple[int, bool]] = None
        self.audit_control_mismatch_display_complete = False
        self.audit_control_mismatch_render_timer = QTimer(self)
        self.audit_control_mismatch_render_timer.setSingleShot(True)
        self.audit_control_mismatch_render_timer.timeout.connect(
            self._render_next_audit_control_mismatch_batch
        )
        self.audit_worker_executor = ThreadPoolExecutor(max_workers=1)
        self.audit_search_worker_future: Optional[Future] = None
        self.audit_search_worker_running_request: Optional[dict[str, Any]] = None
        self.audit_search_worker_pending_request: Optional[dict[str, Any]] = None
        self.audit_search_worker_timer = QTimer(self)
        self.audit_search_worker_timer.setSingleShot(True)
        self.audit_search_worker_timer.timeout.connect(
            self._poll_audit_search_worker)
        self.audit_sanitize_counts_cache_key: Optional[tuple[int, str]] = None
        self.audit_sanitize_counts_cache: dict[str, int] = {}
        self.audit_sanitize_worker_future: Optional[Future] = None
        self.audit_sanitize_worker_running_request: Optional[dict[str, Any]] = None
        self.audit_sanitize_worker_pending_request: Optional[dict[str, Any]] = None
        self.audit_sanitize_worker_timer = QTimer(self)
        self.audit_sanitize_worker_timer.setSingleShot(True)
        self.audit_sanitize_worker_timer.timeout.connect(
            self._poll_audit_sanitize_worker)
        self.audit_control_worker_future: Optional[Future] = None
        self.audit_control_worker_running_request: Optional[dict[str, Any]] = None
        self.audit_control_worker_pending_request: Optional[dict[str, Any]] = None
        self.audit_control_worker_timer = QTimer(self)
        self.audit_control_worker_timer.setSingleShot(True)
        self.audit_control_worker_timer.timeout.connect(
            self._poll_audit_control_worker)
        self.structural_undo_stack: list[StructuralAction] = []
        self.structural_redo_stack: list[StructuralAction] = []
        self._pending_render_state: Optional[dict[str, Any]] = None
        self._render_batch_size = 1
        self._render_blocks_timer = QTimer(self)
        self._render_blocks_timer.setSingleShot(True)
        self._render_blocks_timer.timeout.connect(
            self._render_next_block_batch)
        self._middle_autoscroll_active = False
        self._middle_autoscroll_anchor = QPoint()
        self._middle_autoscroll_press_started_at: Optional[float] = None
        self._middle_autoscroll_started_from_press = False
        self._middle_autoscroll_hold_release_threshold_sec = 0.22
        self._middle_autoscroll_indicator: Optional[QLabel] = None
        self._middle_autoscroll_timer = QTimer(self)
        self._middle_autoscroll_timer.setInterval(16)
        self._middle_autoscroll_timer.timeout.connect(
            self._tick_middle_autoscroll)

        self._global_undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._global_redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._global_redo_alt_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+Z"), self)
        self._global_undo_shortcut.activated.connect(
            self._on_global_undo_shortcut)
        self._global_redo_shortcut.activated.connect(
            self._on_global_redo_shortcut)
        self._global_redo_alt_shortcut.activated.connect(
            self._on_global_redo_shortcut)

        self._build_ui()
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.installEventFilter(self)
        self._default_v_scroll_policy = self.scroll_area.verticalScrollBarPolicy()
        self._default_h_scroll_policy = self.scroll_area.horizontalScrollBarPolicy()
        self._update_mode_controls()
        self._load_ui_state()
        if self.data_dir is None:
            self.statusBar().showMessage("Open a data folder to start.")

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._build_top_controls(layout)

        self.thin_width_spin.valueChanged.connect(
            self._on_layout_constraints_changed)
        self.wide_width_spin.valueChanged.connect(
            self._on_layout_constraints_changed)
        self.max_lines_spin.valueChanged.connect(
            self._on_layout_constraints_changed)
        self.infer_speaker_check.toggled.connect(self._rerender_current_file)
        self.hide_control_codes_check.toggled.connect(
            self._on_hide_control_codes_toggled)
        self.editor_mode_combo.currentIndexChanged.connect(
            self._on_editor_mode_changed)
        self.editor_mode_combo.currentIndexChanged.connect(
            self._on_project_setting_changed)
        self.apply_version_combo.currentIndexChanged.connect(
            self._on_project_setting_changed)
        self.thin_width_spin.valueChanged.connect(
            self._on_project_setting_changed)
        self.wide_width_spin.valueChanged.connect(
            self._on_project_setting_changed)
        self.max_lines_spin.valueChanged.connect(
            self._on_project_setting_changed)
        self.auto_split_check.toggled.connect(self._on_project_setting_changed)
        self.infer_speaker_check.toggled.connect(
            self._on_project_setting_changed)
        self.hide_control_codes_check.toggled.connect(
            self._on_project_setting_changed)
        self.backup_check.toggled.connect(self._on_project_setting_changed)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        files_header_row = QHBoxLayout()
        files_header_row.addWidget(QLabel("Files"))
        self.show_empty_files_check = QCheckBox("Show empty")
        self.show_empty_files_check.setChecked(False)
        self.show_empty_files_check.toggled.connect(
            self._on_show_empty_toggled)
        self.show_empty_files_check.toggled.connect(
            self._on_project_setting_changed)
        files_header_row.addStretch(1)
        files_header_row.addWidget(self.show_empty_files_check)
        left_layout.addLayout(files_header_row)
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        left_layout.addWidget(self.file_list, 1)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        file_header_row = QHBoxLayout()
        file_header_row.setContentsMargins(0, 0, 0, 0)
        file_header_row.setSpacing(8)

        self.file_header_label = QLabel("No file selected")
        header_font = self.file_header_label.font()
        header_font.setBold(True)
        self.file_header_label.setFont(header_font)
        self.file_header_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        file_header_row.addWidget(self.file_header_label)

        self.reset_json_btn = QPushButton("Reset JSON")
        self.reset_json_btn.setToolTip(
            "Discard unsaved edits in this JSON and reload it from saved snapshot data.")
        self.reset_json_btn.clicked.connect(
            self._on_reset_current_file_requested)
        self.reset_json_btn.setVisible(False)
        self.reset_json_btn.setEnabled(False)
        file_header_row.addWidget(self.reset_json_btn)
        file_header_row.addStretch(1)
        header_row_height = max(
            self.file_header_label.sizeHint().height(),
            self.reset_json_btn.sizeHint().height(),
        )
        self.file_header_label.setMinimumHeight(header_row_height)

        right_layout.addLayout(file_header_row)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_container, self.blocks_layout = self._create_blocks_container()
        self.scroll_area.setWidget(self.scroll_container)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_container.installEventFilter(self)
        self.main_render_progress_overlay = self._create_audit_progress_overlay(
            self.scroll_area)
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.addWidget(self.scroll_area)

        self.translator_detail_panel = QWidget()
        translator_layout = QVBoxLayout(self.translator_detail_panel)
        translator_layout.setContentsMargins(8, 8, 8, 8)
        translator_layout.setSpacing(8)

        self.translator_detail_title = QLabel("Selected Dialogue")
        detail_title_font = self.translator_detail_title.font()
        detail_title_font.setBold(True)
        self.translator_detail_title.setFont(detail_title_font)
        translator_layout.addWidget(self.translator_detail_title)

        self.translator_detail_empty_label = QLabel(
            "Select a dialogue block to view source details."
        )
        self.translator_detail_empty_label.setWordWrap(True)
        translator_layout.addWidget(self.translator_detail_empty_label)

        self.translator_detail_content = QWidget()
        detail_content_layout = QVBoxLayout(self.translator_detail_content)
        detail_content_layout.setContentsMargins(0, 0, 0, 0)
        detail_content_layout.setSpacing(6)

        self.translator_block_label = QLabel("Block: -")
        self.translator_context_label = QLabel("Context: -")
        self.translator_context_label.setWordWrap(True)
        detail_content_layout.addWidget(self.translator_block_label)
        detail_content_layout.addWidget(self.translator_context_label)

        self.translator_speaker_jp_row = QWidget()
        speaker_jp_row = QHBoxLayout(self.translator_speaker_jp_row)
        speaker_jp_row.setContentsMargins(0, 0, 0, 0)
        self.translator_speaker_jp_label = QLabel("Speaker JP")
        speaker_jp_row.addWidget(self.translator_speaker_jp_label)
        self.translator_speaker_jp_edit = QLineEdit()
        self.translator_speaker_jp_edit.setReadOnly(True)
        speaker_jp_row.addWidget(self.translator_speaker_jp_edit, 1)
        detail_content_layout.addWidget(self.translator_speaker_jp_row)

        self.translator_speaker_en_row = QWidget()
        speaker_en_row = QHBoxLayout(self.translator_speaker_en_row)
        speaker_en_row.setContentsMargins(0, 0, 0, 0)
        self.translator_speaker_en_label = QLabel("Speaker EN")
        speaker_en_row.addWidget(self.translator_speaker_en_label)
        self.translator_speaker_en_edit = QLineEdit()
        self.translator_speaker_en_edit.setPlaceholderText(
            "Set in Speakers dialog"
        )
        self.translator_speaker_en_edit.setReadOnly(True)
        speaker_en_row.addWidget(self.translator_speaker_en_edit, 1)
        self.translator_open_speakers_btn = QPushButton("Speakers...")
        self.translator_open_speakers_btn.clicked.connect(
            self._open_speaker_manager
        )
        speaker_en_row.addWidget(self.translator_open_speakers_btn)
        detail_content_layout.addWidget(self.translator_speaker_en_row)

        self.translator_source_label = QLabel("Source (JP)")
        translator_layout_font = self.translator_source_label.font()
        translator_layout_font.setBold(True)
        self.translator_source_label.setFont(translator_layout_font)
        detail_content_layout.addWidget(self.translator_source_label)

        self.translator_source_view = QPlainTextEdit()
        self.translator_source_view.setReadOnly(True)
        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.translator_source_view.setFont(mono)
        self.translator_source_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self.translator_source_highlighter = ControlCodeHighlighter(
            self.translator_source_view.document(),
            is_dark_palette(),
            color_code_resolver=self._color_for_rpgm_code,
        )
        detail_content_layout.addWidget(self.translator_source_view, 1)

        self.translator_reference_exact_label = QLabel("")
        self.translator_reference_exact_label.setWordWrap(True)
        detail_content_layout.addWidget(self.translator_reference_exact_label)

        self.translator_reference_similar_label = QLabel("")
        self.translator_reference_similar_label.setWordWrap(True)
        detail_content_layout.addWidget(
            self.translator_reference_similar_label)

        translator_layout.addWidget(self.translator_detail_content, 1)

        self.editor_splitter.addWidget(self.translator_detail_panel)
        self.editor_splitter.setStretchFactor(0, 7)
        self.editor_splitter.setStretchFactor(1, 3)
        self.editor_splitter.setSizes([70, 30])
        right_layout.addWidget(self.editor_splitter, 1)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)

        self._sync_translator_mode_ui()

    def _build_top_controls(self, root_layout: QVBoxLayout) -> None:
        controls_panel = QWidget()
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        self._build_project_controls_row(controls_layout)
        self._build_editor_settings_row(controls_layout)
        self._build_action_controls_row(controls_layout)

        root_layout.addWidget(controls_panel)

    def _build_project_controls_row(self, controls_layout: QVBoxLayout) -> None:
        project_row = QHBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(6)
        project_row.addWidget(QLabel("Data Folder"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select your RPG Maker data folder")
        project_row.addWidget(self.folder_edit, 1)

        browse_btn = QPushButton("Browse")
        refresh_btn = QPushButton("Reload")
        browse_btn.clicked.connect(self._choose_folder)
        refresh_btn.clicked.connect(self._reload_folder_from_text)
        project_row.addWidget(browse_btn)
        project_row.addWidget(refresh_btn)

        self.remember_folder_check = QCheckBox("Remember")
        self.remember_folder_check.setChecked(False)
        self.remember_folder_check.setToolTip(
            "Remember last project folder and reopen it on startup."
        )
        self.remember_folder_check.toggled.connect(self._on_remember_folder_toggled)
        project_row.addWidget(self.remember_folder_check)
        controls_layout.addLayout(project_row)

    def _build_editor_settings_row(self, controls_layout: QVBoxLayout) -> None:
        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.setSpacing(8)

        settings_row.addWidget(QLabel("Mode"))
        self.editor_mode_combo = QComboBox()
        self.editor_mode_combo.addItem("Plain Edit", "plain")
        self.editor_mode_combo.addItem("Translator Edit", "translator")
        self.editor_mode_combo.setToolTip(
            "Plain Edit modifies JSON directly. Translator Edit keeps source read-only and edits translation data."
        )
        settings_row.addWidget(self.editor_mode_combo)

        settings_row.addWidget(QLabel("Thin"))
        self.thin_width_spin = QSpinBox()
        self.thin_width_spin.setRange(10, 200)
        self.thin_width_spin.setValue(DEFAULT_THIN_WIDTH)
        settings_row.addWidget(self.thin_width_spin)

        settings_row.addWidget(QLabel("Wide"))
        self.wide_width_spin = QSpinBox()
        self.wide_width_spin.setRange(10, 240)
        self.wide_width_spin.setValue(DEFAULT_WIDE_WIDTH)
        settings_row.addWidget(self.wide_width_spin)

        settings_row.addWidget(QLabel("Max Lines"))
        self.max_lines_spin = QSpinBox()
        self.max_lines_spin.setRange(1, 20)
        self.max_lines_spin.setValue(DEFAULT_MAX_LINES)
        settings_row.addWidget(self.max_lines_spin)

        self.auto_split_check = QCheckBox("Auto-split overflow on save")
        self.auto_split_check.setChecked(True)
        settings_row.addWidget(self.auto_split_check)

        self.infer_speaker_check = QCheckBox("Infer speaker from line 1")
        self.infer_speaker_check.setChecked(False)
        self.infer_speaker_check.setToolTip(
            "Only used when code 101 speaker is empty; tries to detect a speaker from the first text line."
        )
        settings_row.addWidget(self.infer_speaker_check)

        self.hide_control_codes_check = QCheckBox("Hide control codes unless focused")
        self.hide_control_codes_check.setChecked(True)
        self.hide_control_codes_check.setToolTip(
            "When enabled, control codes are hidden in unfocused dialogue editors and shown when focused."
        )
        settings_row.addWidget(self.hide_control_codes_check)

        self.backup_check = QCheckBox("Create .bak backup")
        self.backup_check.setChecked(True)
        settings_row.addWidget(self.backup_check)

        settings_row.addStretch(1)
        self.next_problem_btn = QPushButton("Next Problem")
        self.next_problem_btn.setToolTip(
            "Jump to the next block that exceeds width or max-lines in the current mode."
        )
        self.next_problem_btn.clicked.connect(self._jump_to_next_problem)
        self.next_problem_btn.setEnabled(False)
        settings_row.addWidget(self.next_problem_btn)
        controls_layout.addLayout(settings_row)

    def _build_action_controls_row(self, controls_layout: QVBoxLayout) -> None:
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(6)

        self.speaker_manager_btn = QPushButton("Speakers")
        self.speaker_manager_btn.setToolTip(
            "Rename speakers globally and customize speaker colors."
        )
        self.speaker_manager_btn.clicked.connect(self._open_speaker_manager)
        actions_row.addWidget(self.speaker_manager_btn)

        self.mass_translate_btn = QPushButton("Mass Translate")
        self.mass_translate_btn.setToolTip(
            "Build context-aware LLM chunks for dialogues/speakers and paste results back."
        )
        self.mass_translate_btn.clicked.connect(self._open_mass_translate_dialog)
        actions_row.addWidget(self.mass_translate_btn)

        self.audit_btn = QPushButton("Audit")
        self.audit_btn.setToolTip("Open non-blocking audit tools.")
        self.audit_btn.clicked.connect(self._open_audit_window)
        actions_row.addWidget(self.audit_btn)

        actions_row.addStretch(1)

        self.save_btn = QPushButton("Save File")
        self.save_all_btn = QPushButton("Save All")
        self.save_btn.setToolTip("Save current edits to the project snapshot database.")
        self.save_all_btn.setToolTip("Save all edits to the project snapshot database.")
        self.save_btn.clicked.connect(self._save_current_file)
        self.save_all_btn.clicked.connect(self._save_all_files)
        self.save_btn.setEnabled(False)
        self.save_all_btn.setEnabled(False)
        actions_row.addWidget(self.save_btn)
        actions_row.addWidget(self.save_all_btn)

        actions_row.addSpacing(8)
        actions_row.addWidget(QLabel("Apply Snapshot"))
        self.apply_version_combo = QComboBox()
        self.apply_version_combo.addItem("Original", "original")
        self.apply_version_combo.addItem("Working", "working")
        self.apply_version_combo.addItem("Translated", "translated")
        self.apply_version_combo.setCurrentIndex(1)
        self.apply_version_combo.setToolTip(
            "Choose which snapshot version to apply to game files."
        )
        self.apply_version_combo.setEnabled(False)
        actions_row.addWidget(self.apply_version_combo)

        self.apply_version_btn = QPushButton("Apply To Game Files")
        self.apply_version_btn.setToolTip(
            "Write selected snapshot version directly to JSON files in the data folder."
        )
        self.apply_version_btn.clicked.connect(
            self._apply_selected_snapshot_to_game_files
        )
        self.apply_version_btn.setEnabled(False)
        actions_row.addWidget(self.apply_version_btn)
        controls_layout.addLayout(actions_row)

    def _focused_text_editor(self) -> Optional[QPlainTextEdit]:
        focus = QApplication.focusWidget()
        widget = focus
        while widget is not None:
            if isinstance(widget, QPlainTextEdit):
                return widget
            widget = widget.parentWidget()
        return None

    def _middle_autoscroll_step(self, delta: int) -> int:
        dead_zone = 10
        abs_delta = abs(delta)
        if abs_delta <= dead_zone:
            return 0
        direction = 1 if delta > 0 else -1
        scaled = abs_delta - dead_zone
        step = min(80, (scaled * scaled) // 140 + 1)
        return direction * step

    def _start_middle_autoscroll(self, anchor_global: QPoint) -> None:
        self._middle_autoscroll_anchor = QPoint(anchor_global)
        self._middle_autoscroll_active = True
        self._show_middle_autoscroll_indicator(anchor_global)
        self._middle_autoscroll_timer.start()

    def _stop_middle_autoscroll(self) -> None:
        if not self._middle_autoscroll_active:
            return
        self._middle_autoscroll_active = False
        self._middle_autoscroll_press_started_at = None
        self._middle_autoscroll_started_from_press = False
        self._middle_autoscroll_timer.stop()
        self._hide_middle_autoscroll_indicator()

    def _tick_middle_autoscroll(self) -> None:
        if not self._middle_autoscroll_active:
            return
        current_pos = QCursor.pos()
        dx = current_pos.x() - self._middle_autoscroll_anchor.x()
        dy = current_pos.y() - self._middle_autoscroll_anchor.y()
        step_x = self._middle_autoscroll_step(dx)
        step_y = self._middle_autoscroll_step(dy)
        if step_y != 0:
            vbar = self.scroll_area.verticalScrollBar()
            vbar.setValue(vbar.value() + step_y)
        if step_x != 0:
            hbar = self.scroll_area.horizontalScrollBar()
            hbar.setValue(hbar.value() + step_x)

    def _point_in_editor_viewport(self, global_pos: QPoint) -> bool:
        viewport = self.scroll_area.viewport()
        local_pos = viewport.mapFromGlobal(global_pos)
        return viewport.rect().contains(local_pos)

    def _ensure_middle_autoscroll_indicator(self) -> QLabel:
        if self._middle_autoscroll_indicator is not None:
            return self._middle_autoscroll_indicator
        indicator = QLabel(self.scroll_area.viewport())
        indicator.setFixedSize(34, 34)
        indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        indicator.setText("↑\n↓")
        font = QFont("Segoe UI")
        font.setPointSize(8)
        font.setBold(True)
        indicator.setFont(font)
        if is_dark_palette():
            indicator.setStyleSheet(
                "QLabel {"
                "background: rgba(15, 23, 42, 210);"
                "color: #f8fafc;"
                "border: 2px solid #93c5fd;"
                "border-radius: 17px;"
                "}"
            )
        else:
            indicator.setStyleSheet(
                "QLabel {"
                "background: rgba(255, 255, 255, 235);"
                "color: #0f172a;"
                "border: 2px solid #2563eb;"
                "border-radius: 17px;"
                "}"
            )
        indicator.hide()
        self._middle_autoscroll_indicator = indicator
        return indicator

    def _show_middle_autoscroll_indicator(self, anchor_global: QPoint) -> None:
        indicator = self._ensure_middle_autoscroll_indicator()
        viewport = self.scroll_area.viewport()
        local = viewport.mapFromGlobal(anchor_global)
        half_w = indicator.width() // 2
        half_h = indicator.height() // 2
        x = max(0, min(local.x() - half_w, viewport.width() - indicator.width()))
        y = max(0, min(local.y() - half_h, viewport.height() - indicator.height()))
        indicator.move(x, y)
        indicator.show()
        indicator.raise_()

    def _hide_middle_autoscroll_indicator(self) -> None:
        if self._middle_autoscroll_indicator is not None:
            self._middle_autoscroll_indicator.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            if not isinstance(event, QMouseEvent):
                return super().eventFilter(watched, event)
            mouse_event = event
            button = mouse_event.button()
            anchor = mouse_event.globalPosition().toPoint()
            if button == Qt.MouseButton.MiddleButton and self._point_in_editor_viewport(anchor):
                if self._middle_autoscroll_active:
                    self._stop_middle_autoscroll()
                else:
                    self._start_middle_autoscroll(anchor)
                    self._middle_autoscroll_started_from_press = True
                    self._middle_autoscroll_press_started_at = monotonic()
                return True
            if self._middle_autoscroll_active and button in (
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.RightButton,
                Qt.MouseButton.MiddleButton,
            ):
                self._stop_middle_autoscroll()
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if not isinstance(event, QMouseEvent):
                return super().eventFilter(watched, event)
            mouse_event = event
            button = mouse_event.button()
            if (
                button == Qt.MouseButton.MiddleButton
                and self._middle_autoscroll_active
                and self._middle_autoscroll_started_from_press
            ):
                started_at = self._middle_autoscroll_press_started_at
                held_for = (monotonic() - started_at) if started_at is not None else 0.0
                self._middle_autoscroll_press_started_at = None
                self._middle_autoscroll_started_from_press = False
                if held_for >= self._middle_autoscroll_hold_release_threshold_sec:
                    self._stop_middle_autoscroll()
                return True
        elif self._middle_autoscroll_active and event.type() == QEvent.Type.Wheel:
            self._stop_middle_autoscroll()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._middle_autoscroll_active and event.key() == Qt.Key.Key_Escape:
            self._stop_middle_autoscroll()
            event.accept()
            return
        super().keyPressEvent(event)

    def _update_reset_json_button(self, session: Optional[FileSession]) -> None:
        dirty = bool(session is not None and session.dirty)
        self.reset_json_btn.setVisible(dirty)
        self.reset_json_btn.setEnabled(dirty)

    def _sync_translator_mode_ui(self) -> None:
        translator_mode = self._is_translator_mode()
        was_visible = self.translator_detail_panel.isVisible()
        self.translator_detail_panel.setVisible(translator_mode)
        if translator_mode and not was_visible:
            def apply_translator_split() -> None:
                total = max(2, self.editor_splitter.width())
                left = max(1, int(total * 0.7))
                right = max(1, total - left)
                self.editor_splitter.setSizes([left, right])

            QTimer.singleShot(0, apply_translator_split)
        if not translator_mode:
            self.selected_segment_uid = None
        self._refresh_translator_detail_panel()

    def _block_number_for_uid(self, uid: str) -> Optional[int]:
        if self.current_path is None:
            return None
        session = self.sessions.get(self.current_path)
        if session is None:
            return None
        for idx, segment in enumerate(session.segments, start=1):
            if segment.uid == uid:
                return idx
        return None

    def _refresh_translator_detail_panel(self) -> None:
        translator_mode = self._is_translator_mode()
        self.translator_detail_panel.setVisible(translator_mode)
        if not translator_mode:
            return

        current_session = (
            self.sessions.get(self.current_path)
            if self.current_path is not None
            else None
        )
        actor_mode = bool(
            current_session and self._is_name_index_session(current_session))
        name_index_label = self._name_index_label(
            current_session) if actor_mode else "Entry"
        segment = self.current_segment_lookup.get(
            self.selected_segment_uid) if self.selected_segment_uid else None
        selected_field = (
            self._name_index_field_from_uid(segment.uid)
            if actor_mode and segment is not None
            else "name"
        )
        is_name_desc_combined = (
            actor_mode
            and segment is not None
            and isinstance(getattr(segment, "name_index_combined_fields", ()), tuple)
            and "name" in getattr(segment, "name_index_combined_fields", ())
            and "description" in getattr(segment, "name_index_combined_fields", ())
        )
        if is_name_desc_combined:
            field_label = "Name + Description"
        else:
            field_label = (
                "Name"
                if selected_field == "name"
                else selected_field.replace("_", " ").strip().title()
            )
        self.translator_speaker_jp_row.setVisible(not actor_mode)
        self.translator_speaker_en_row.setVisible(not actor_mode)
        self.translator_reference_exact_label.setVisible(not actor_mode)
        self.translator_reference_similar_label.setVisible(not actor_mode)
        self.translator_source_label.setText(
            f"{field_label} (JP)" if actor_mode else "Source (JP)")

        has_segment = segment is not None
        self.translator_detail_empty_label.setVisible(not has_segment)
        self.translator_detail_content.setVisible(has_segment)
        if segment is None:
            self.translator_detail_title.setText(
                f"Selected {name_index_label}" if actor_mode else "Selected Dialogue"
            )
            self.translator_block_label.setText(
                f"{name_index_label} ID: -" if actor_mode else "Block: -"
            )
            self.translator_context_label.setText(
                "Entry: -" if actor_mode else "Context: -")
            self.translator_speaker_jp_edit.setText("")
            self.translator_speaker_en_edit.setText("")
            self.translator_source_view.setPlainText("")
            self.translator_reference_exact_label.setText("")
            self.translator_reference_similar_label.setText("")
            return

        block_number = self._block_number_for_uid(segment.uid)
        if actor_mode:
            actor_id = self._actor_id_from_uid(segment.uid)
            self.translator_detail_title.setText(
                f"Selected {name_index_label}")
            if actor_id is None:
                self.translator_block_label.setText(
                    f"{name_index_label} ID: -")
            else:
                self.translator_block_label.setText(
                    f"{name_index_label} ID: {actor_id}")
            self.translator_context_label.setText(f"Entry: {segment.context}")
        else:
            if block_number is None:
                self.translator_detail_title.setText("Selected Dialogue")
                self.translator_block_label.setText("Block: -")
            else:
                self.translator_detail_title.setText(
                    f"Selected Dialogue: Block {block_number}")
                self.translator_block_label.setText(f"Block: {block_number}")
            self.translator_context_label.setText(
                f"Context: {segment.context}")

            speaker_key = self._speaker_key_for_segment(segment)
            self.translator_speaker_jp_edit.setText(speaker_key)
            speaker_en = self._speaker_translation_for_key(speaker_key)
            if not speaker_en:
                speaker_en = segment.translation_speaker.strip()
            self.translator_speaker_en_edit.setText(speaker_en)

        self.translator_source_view.setPlainText(
            "\n".join(self._segment_source_lines_for_display(segment)))
        if actor_mode:
            self.translator_reference_exact_label.setText("")
            self.translator_reference_similar_label.setText("")
        else:
            exact, similar = self.current_reference_map.get(
                segment.uid,
                (
                    "Exact JP matches: none.",
                    "Similar JP phrases: none.",
                ),
            )
            self.translator_reference_exact_label.setText(exact)
            self.translator_reference_similar_label.setText(similar)

    def _on_block_activated(self, uid: str) -> None:
        if uid not in self.current_segment_lookup:
            return
        if self.audit_pinned_uid is not None:
            self.audit_pinned_uid = None
        if self.selected_segment_uid == uid:
            self._refresh_block_visual_states()
            return
        self.selected_segment_uid = uid
        self._refresh_block_visual_states()
        self._refresh_translator_detail_panel()

    def _refresh_block_visual_states(self) -> None:
        selected_uid = self.selected_segment_uid
        pinned_uid = self.audit_pinned_uid
        for uid, widget in self.block_widgets.items():
            set_selected = getattr(widget, "set_selected_state", None)
            if callable(set_selected):
                set_selected(selected_uid == uid)
            set_pinned = getattr(widget, "set_audit_pinned_state", None)
            if callable(set_pinned):
                set_pinned(pinned_uid == uid)

    def _speaker_translation_for_key(self, speaker_key: str) -> str:
        key = self._normalize_speaker_key(speaker_key)
        value = self.speaker_translation_map.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip()

        jp_by_id, en_by_id = self._actor_name_maps()
        for actor_id, jp_name in jp_by_id.items():
            if self._normalize_speaker_key(jp_name) != key:
                continue
            candidate = en_by_id.get(actor_id, "").strip()
            if candidate:
                return candidate
        return ""

    def _set_speaker_translation_everywhere(self, speaker_key: str, translated_name: str) -> int:
        key = self._normalize_speaker_key(speaker_key)
        cleaned = translated_name.strip()
        previous = self._speaker_translation_for_key(key)
        changed_blocks = 0
        touched_sessions: list[FileSession] = []

        for session in self.sessions.values():
            touched = False
            for segment in session.segments:
                if self._speaker_key_for_segment(segment) != key:
                    continue
                if segment.translation_speaker.strip() == cleaned:
                    continue
                segment.translation_speaker = cleaned
                changed_blocks += 1
                touched = True
            if touched:
                touched_sessions.append(session)

        if cleaned:
            self.speaker_translation_map[key] = cleaned
        else:
            self.speaker_translation_map.pop(key, None)

        for session in touched_sessions:
            self._refresh_dirty_state(session)

        if self.current_path is not None:
            session = self.sessions.get(self.current_path)
            if session is not None:
                self._render_session(session, preserve_scroll=True)
        else:
            self._refresh_translator_detail_panel()

        map_changed = previous != cleaned

        if changed_blocks > 0:
            value_display = cleaned if cleaned else "(blank)"
            block_label = "block" if changed_blocks == 1 else "blocks"
            self.statusBar().showMessage(
                f"Set Speaker EN for '{key}' to '{value_display}' in {changed_blocks} {block_label}."
            )
        elif map_changed:
            value_display = cleaned if cleaned else "(blank)"
            self.statusBar().showMessage(
                f"Set Speaker EN for '{key}' to '{value_display}'."
            )
        else:
            self.statusBar().showMessage(
                f"No speaker EN changes needed for '{key}'."
            )
        return changed_blocks

    def _normalize_speaker_key(self, value: str) -> str:
        normalized = value.strip()
        return normalized if normalized else NO_SPEAKER_KEY

    def _inferred_speaker_from_segment_line1(self, segment: DialogueSegment) -> str:
        if not self.infer_speaker_check.isChecked():
            return ""
        if segment.speaker_name != NO_SPEAKER_KEY:
            return ""
        lines = self._segment_source_lines_for_display(segment)
        if not lines:
            return ""
        first_line = lines[0].strip()
        if not first_line:
            return ""
        resolved_first = self._resolve_name_tokens_in_text(
            first_line,
            prefer_translated=False,
        ).strip()
        if first_line and looks_like_name_line(first_line):
            return resolved_first or first_line
        if resolved_first and looks_like_name_line(resolved_first):
            return resolved_first
        if self._matches_name_token(first_line):
            return resolved_first or first_line
        return ""

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        explicit_raw = self._resolve_name_tokens_in_text(
            segment.speaker_name,
            prefer_translated=False,
        )
        explicit = self._normalize_speaker_key(explicit_raw)
        if explicit != NO_SPEAKER_KEY:
            return explicit
        inferred = self._inferred_speaker_from_segment_line1(segment)
        if inferred:
            return self._normalize_speaker_key(inferred)
        return NO_SPEAKER_KEY

    def _speaker_param_value_from_key(self, speaker_key: str) -> str:
        return "" if speaker_key == NO_SPEAKER_KEY else speaker_key

    def _collect_speaker_keys(self) -> list[str]:
        keys: set[str] = {NO_SPEAKER_KEY}
        keys.update(self.speaker_custom_colors.keys())
        keys.update(self.speaker_translation_map.keys())
        for session in self.sessions.values():
            for segment in session.segments:
                keys.add(self._speaker_key_for_segment(segment))
        return sorted(keys, key=natural_sort_key)

    def _invalidate_speaker_auto_color_cache(self) -> None:
        self._speaker_auto_color_map.clear()
        self._speaker_auto_color_theme_dark = None

    def _auto_speaker_color_for_key(self, speaker_key: str) -> str:
        if speaker_key == NO_SPEAKER_KEY:
            return "#64748b"

        dark = is_dark_palette()
        if (
            self._speaker_auto_color_theme_dark is None
            or self._speaker_auto_color_theme_dark != dark
            or speaker_key not in self._speaker_auto_color_map
        ):
            self._rebuild_speaker_auto_color_map(dark)

        cached = self._speaker_auto_color_map.get(speaker_key)
        if isinstance(cached, str):
            return cached

        # Fallback should be rare; keep deterministic per key.
        fallback_hash = self._speaker_color_hash(speaker_key)
        hue = fallback_hash % 360
        saturation = 172
        lightness = 158 if dark else 106
        color = QColor.fromHsl(hue, saturation, lightness)
        return color.name(QColor.NameFormat.HexRgb)

    def _speaker_color_hash(self, speaker_key: str) -> int:
        seed = 0
        for idx, ch in enumerate(speaker_key):
            seed = (seed * 131 + ord(ch) + idx) % 2147483647
        return seed

    def _rebuild_speaker_auto_color_map(self, dark: bool) -> None:
        speaker_keys = [
            key
            for key in self._collect_speaker_keys()
            if key != NO_SPEAKER_KEY
        ]
        ordered_keys = sorted(speaker_keys, key=self._speaker_color_hash)
        total = len(ordered_keys)
        saturation = 172
        lightness = 158 if dark else 106
        color_map: dict[str, str] = {}
        for index, key in enumerate(ordered_keys):
            hue = int((index * 360) / max(total, 1)) % 360
            color = QColor.fromHsl(hue, saturation, lightness)
            color_map[key] = color.name(QColor.NameFormat.HexRgb)
        self._speaker_auto_color_map = color_map
        self._speaker_auto_color_theme_dark = dark

    def _speaker_color_for_key(self, speaker_key: str) -> str:
        key = self._normalize_speaker_key(speaker_key)
        custom = self.speaker_custom_colors.get(key)
        if isinstance(custom, str) and QColor(custom).isValid():
            return custom
        return self._auto_speaker_color_for_key(key)

    def _speaker_color_for_segment(self, segment: DialogueSegment) -> str:
        return self._speaker_color_for_key(self._speaker_key_for_segment(segment))

    def _set_custom_speaker_color(self, speaker_key: str, color_hex: str) -> None:
        key = self._normalize_speaker_key(speaker_key)
        color = QColor(color_hex)
        if not color.isValid():
            return
        self.speaker_custom_colors[key] = color.name(QColor.NameFormat.HexRgb)
        if self.current_path is not None:
            session = self.sessions.get(self.current_path)
            if session is not None:
                self._render_session(session, preserve_scroll=True)

    def _clear_custom_speaker_color(self, speaker_key: str) -> None:
        key = self._normalize_speaker_key(speaker_key)
        if key in self.speaker_custom_colors:
            del self.speaker_custom_colors[key]
            if self.current_path is not None:
                session = self.sessions.get(self.current_path)
                if session is not None:
                    self._render_session(session, preserve_scroll=True)

    def _rename_speaker_everywhere(self, old_key: str, new_key: str) -> int:
        old_name = self._normalize_speaker_key(old_key)
        new_name = self._normalize_speaker_key(new_key)
        if old_name == new_name:
            return 0

        changed_blocks = 0
        for session in self.sessions.values():
            touched = False
            for segment in session.segments:
                if self._speaker_key_for_segment(segment) != old_name:
                    continue
                params = segment.params
                while len(params) <= 4:
                    params.append("")
                params[4] = self._speaker_param_value_from_key(new_name)
                segment.code101["parameters"] = params
                changed_blocks += 1
                touched = True
            if touched:
                self._refresh_dirty_state(session)

        if old_name in self.speaker_custom_colors:
            if new_name not in self.speaker_custom_colors:
                self.speaker_custom_colors[new_name] = self.speaker_custom_colors[old_name]
            del self.speaker_custom_colors[old_name]

        if old_name in self.speaker_translation_map:
            if new_name not in self.speaker_translation_map:
                self.speaker_translation_map[new_name] = self.speaker_translation_map[old_name]
            del self.speaker_translation_map[old_name]
        self._invalidate_speaker_auto_color_cache()

        if self.current_path is not None:
            session = self.sessions.get(self.current_path)
            if session is not None:
                self._render_session(session, preserve_scroll=True)

        if changed_blocks > 0:
            block_label = "block" if changed_blocks == 1 else "blocks"
            self.statusBar().showMessage(
                f"Renamed speaker '{old_name}' -> '{new_name}' in {changed_blocks} {block_label}."
            )
        else:
            self.statusBar().showMessage(
                f"Renamed speaker key '{old_name}' -> '{new_name}'.")
        return changed_blocks

    def _open_speaker_manager(self) -> None:
        if not self.sessions:
            QMessageBox.information(
                self, "No data loaded", "Load a data folder before opening Speaker Manager.")
            return
        dialog = SpeakerManagerDialog(self)
        dialog.exec()
        self._refresh_translator_detail_panel()

    def _open_mass_translate_dialog(self) -> None:
        if not self.sessions:
            QMessageBox.information(
                self,
                "No data loaded",
                "Load a data folder before opening Mass Translate.",
            )
            return
        dialog = MassTranslateDialog(self)
        dialog.exec()
        self._refresh_translator_detail_panel()

    def _on_global_undo_shortcut(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None and editor.document().isUndoAvailable():
            editor.undo()
            return
        if self._is_translator_mode():
            self.statusBar().showMessage("Nothing to undo.")
            return
        if not self._undo_last_structural_action():
            self.statusBar().showMessage("Nothing to undo.")

    def _on_global_redo_shortcut(self) -> None:
        editor = self._focused_text_editor()
        if editor is not None and editor.document().isRedoAvailable():
            editor.redo()
            return
        if self._is_translator_mode():
            self.statusBar().showMessage("Nothing to redo.")
            return
        if not self._redo_last_structural_action():
            self.statusBar().showMessage("Nothing to redo.")

    def _on_remember_folder_toggled(self, _checked: bool) -> None:
        self._save_ui_state()

    def _project_state_key(self, folder: Path) -> str:
        try:
            return str(folder.resolve())
        except Exception:
            return str(folder)

    def _collect_project_ui_settings(self) -> dict[str, Any]:
        mode_raw = self.editor_mode_combo.currentData()
        mode_value = mode_raw if isinstance(mode_raw, str) else "plain"
        apply_raw = self.apply_version_combo.currentData()
        apply_value = apply_raw if isinstance(apply_raw, str) else "working"
        return {
            "editor_mode": mode_value,
            "apply_version": apply_value,
            "thin_width": int(self.thin_width_spin.value()),
            "wide_width": int(self.wide_width_spin.value()),
            "max_lines": int(self.max_lines_spin.value()),
            "auto_split": bool(self.auto_split_check.isChecked()),
            "infer_speaker": bool(self.infer_speaker_check.isChecked()),
            "hide_control_codes": bool(self.hide_control_codes_check.isChecked()),
            "create_backup": bool(self.backup_check.isChecked()),
            "show_empty_files": bool(self.show_empty_files_check.isChecked()),
        }

    def _store_project_ui_settings(self, folder: Path) -> None:
        key = self._project_state_key(folder)
        self.project_ui_settings_by_folder[key] = self._collect_project_ui_settings()

    def _store_current_project_ui_settings(self) -> None:
        if self.data_dir is None:
            return
        self._store_project_ui_settings(self.data_dir)

    def _set_combo_data_if_present(self, combo: QComboBox, data_value: str) -> None:
        index = combo.findData(data_value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _apply_project_ui_settings(self, settings: dict[str, Any]) -> None:
        self._applying_project_ui_state = True
        self.editor_mode_combo.blockSignals(True)
        self.apply_version_combo.blockSignals(True)
        self.thin_width_spin.blockSignals(True)
        self.wide_width_spin.blockSignals(True)
        self.max_lines_spin.blockSignals(True)
        self.auto_split_check.blockSignals(True)
        self.infer_speaker_check.blockSignals(True)
        self.hide_control_codes_check.blockSignals(True)
        self.backup_check.blockSignals(True)
        self.show_empty_files_check.blockSignals(True)
        try:
            editor_mode = settings.get("editor_mode")
            if isinstance(editor_mode, str):
                self._set_combo_data_if_present(self.editor_mode_combo, editor_mode)
            apply_version = settings.get("apply_version")
            if isinstance(apply_version, str):
                self._set_combo_data_if_present(
                    self.apply_version_combo, apply_version
                )
            thin_width = settings.get("thin_width")
            if isinstance(thin_width, int):
                self.thin_width_spin.setValue(thin_width)
            wide_width = settings.get("wide_width")
            if isinstance(wide_width, int):
                self.wide_width_spin.setValue(wide_width)
            max_lines = settings.get("max_lines")
            if isinstance(max_lines, int):
                self.max_lines_spin.setValue(max_lines)
            auto_split = settings.get("auto_split")
            if isinstance(auto_split, bool):
                self.auto_split_check.setChecked(auto_split)
            infer_speaker = settings.get("infer_speaker")
            if isinstance(infer_speaker, bool):
                self.infer_speaker_check.setChecked(infer_speaker)
            hide_control_codes = settings.get("hide_control_codes")
            if isinstance(hide_control_codes, bool):
                self.hide_control_codes_check.setChecked(hide_control_codes)
            create_backup = settings.get("create_backup")
            if isinstance(create_backup, bool):
                self.backup_check.setChecked(create_backup)
            show_empty_files = settings.get("show_empty_files")
            if isinstance(show_empty_files, bool):
                self.show_empty_files_check.setChecked(show_empty_files)
        finally:
            self.editor_mode_combo.blockSignals(False)
            self.apply_version_combo.blockSignals(False)
            self.thin_width_spin.blockSignals(False)
            self.wide_width_spin.blockSignals(False)
            self.max_lines_spin.blockSignals(False)
            self.auto_split_check.blockSignals(False)
            self.infer_speaker_check.blockSignals(False)
            self.hide_control_codes_check.blockSignals(False)
            self.backup_check.blockSignals(False)
            self.show_empty_files_check.blockSignals(False)
            self._applying_project_ui_state = False

        self._update_mode_controls()
        refresh_file_items = getattr(self, "_refresh_all_file_item_text", None)
        if callable(refresh_file_items):
            refresh_file_items()
        sync_mode_ui = getattr(self, "_sync_translator_mode_ui", None)
        if callable(sync_mode_ui):
            sync_mode_ui()
        if self.current_path is not None:
            self._rerender_current_file()

    def _on_project_setting_changed(self, *_args: Any) -> None:
        if self._applying_project_ui_state:
            return
        if self.data_dir is None:
            return
        self._store_current_project_ui_settings()
        self._save_ui_state()

    def _load_ui_state(self) -> None:
        remember_last_folder = False
        last_folder = ""
        loaded_project_settings: dict[str, dict[str, Any]] = {}

        try:
            if self.ui_state_path.exists():
                with self.ui_state_path.open("r", encoding="utf-8") as src:
                    loaded = json.load(src)
                if isinstance(loaded, dict):
                    remember_last_folder = bool(
                        loaded.get("remember_last_folder", False))
                    raw_last_folder = loaded.get("last_folder", "")
                    if isinstance(raw_last_folder, str):
                        last_folder = raw_last_folder.strip()
                    raw_project_settings = loaded.get("project_settings")
                    if isinstance(raw_project_settings, dict):
                        for key, value in raw_project_settings.items():
                            if isinstance(key, str) and isinstance(value, dict):
                                loaded_project_settings[key] = value
        except Exception:
            return

        self.project_ui_settings_by_folder = loaded_project_settings
        self.remember_folder_check.blockSignals(True)
        self.remember_folder_check.setChecked(remember_last_folder)
        self.remember_folder_check.blockSignals(False)

        if last_folder:
            self.folder_edit.setText(last_folder)

        if remember_last_folder and last_folder:
            candidate = Path(last_folder)
            if candidate.exists() and candidate.is_dir():
                self._load_data_folder(candidate)

    def _save_ui_state(self) -> None:
        self._store_current_project_ui_settings()
        remember_last_folder = bool(self.remember_folder_check.isChecked())
        last_folder = ""
        if remember_last_folder:
            if self.data_dir is not None:
                last_folder = str(self.data_dir)
            else:
                last_folder = self.folder_edit.text().strip()

        payload = {
            "remember_last_folder": remember_last_folder,
            "last_folder": last_folder,
            "project_settings": self.project_ui_settings_by_folder,
        }
        try:
            with self.ui_state_path.open("w", encoding="utf-8") as dst:
                json.dump(payload, dst, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _choose_folder(self) -> None:
        start_dir = str(self.data_dir) if self.data_dir else str(Path.cwd())
        chosen = QFileDialog.getExistingDirectory(
            self, "Select data folder", start_dir)
        if not chosen:
            return
        self.folder_edit.setText(chosen)
        self._load_data_folder(Path(chosen))

    def _reload_folder_from_text(self) -> None:
        text = self.folder_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "Missing folder",
                                "Please select a folder first.")
            return
        if not self._prompt_unsaved_if_any():
            return

        selected_version_raw = self.apply_version_combo.currentData()
        if selected_version_raw == "original":
            selected_version = "original"
        elif selected_version_raw == "working":
            selected_version = "working"
        else:
            selected_version = "translated"

        if selected_version == "original":
            selected_label = "Original"
            import_target_version = "working"
        elif selected_version == "working":
            selected_label = "Working"
            import_target_version = "working"
        else:
            selected_label = "Translated"
            import_target_version = "translated"

        import_target_label = (
            "Working" if import_target_version == "working" else "Translated"
        )

        confirm = QMessageBox.question(
            self,
            "Reload from game files",
            (
                "This will re-read JSON files from disk and overwrite your working snapshot data.\n"
                "Use with caution.\n\n"
                f"Selected apply version: {selected_label}\n"
                f"Default import target: {import_target_label}\n"
                "Original snapshot is locked and will not be overwritten."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        applied_version = self.version_db.get_applied_version(
        ) if self.version_db is not None else None
        if applied_version is not None and applied_version != selected_version:
            if applied_version == "original":
                applied_label = "Original"
                applied_import_target = ""
            elif applied_version == "working":
                applied_label = "Working"
                applied_import_target = "working"
            else:
                applied_label = "Translated"
                applied_import_target = "translated"
            applied_at = self.version_db.get_applied_version_timestamp(
            ) if self.version_db is not None else ""
            serious = QMessageBox(self)
            serious.setWindowTitle("Version mismatch warning")
            serious.setIcon(QMessageBox.Icon.Critical)
            serious.setText(
                (
                    "Selected apply version and last applied game-file version do not match.\n\n"
                    f"Selected: {selected_label}\n"
                    f"Last applied to files: {applied_label}\n"
                    f"Last applied timestamp: {applied_at or '(unknown)'}\n\n"
                    "Choose which snapshot this disk read should overwrite."
                )
            )
            to_selected_btn = serious.addButton(
                f"Import Into {import_target_label}",
                QMessageBox.ButtonRole.AcceptRole,
            )
            to_applied_btn = None
            if applied_import_target:
                applied_target_label = (
                    "Working" if applied_import_target == "working" else "Translated"
                )
                to_applied_btn = serious.addButton(
                    f"Import Into {applied_target_label}",
                    QMessageBox.ButtonRole.DestructiveRole,
                )
            cancel_btn = serious.addButton(
                "Cancel", QMessageBox.ButtonRole.RejectRole)
            serious.exec()
            clicked = serious.clickedButton()
            if clicked is cancel_btn:
                return
            if to_applied_btn is not None and clicked is to_applied_btn:
                import_target_version = applied_import_target
            elif clicked is not to_selected_btn:
                return

        self._load_data_folder(
            Path(text),
            force_disk_import=True,
            import_target_version=import_target_version,
        )

    def _prompt_unsaved_if_any(self) -> bool:
        dirty = [session for session in self.sessions.values()
                 if session.dirty]
        if not dirty:
            return True

        msg = QMessageBox(self)
        msg.setWindowTitle("Unsaved changes")
        msg.setText("You have unsaved changes. Save before switching folders?")
        msg.setIcon(QMessageBox.Icon.Warning)
        save_btn = msg.addButton("Save All", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is cancel_btn:
            return False
        if clicked is save_btn:
            if not self._save_all_files():
                return False
        return True

    def _on_show_empty_toggled(self, _checked: bool) -> None:
        self._rebuild_file_list(preferred_path=self.current_path)

    def _visible_file_paths(self) -> list[Path]:
        visible_paths: list[Path] = []
        show_empty = self.show_empty_files_check.isChecked()
        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            if not show_empty and not session.segments:
                continue
            visible_paths.append(path)
        return visible_paths

    def _rebuild_file_list(self, preferred_path: Optional[Path] = None) -> None:
        visible_paths = self._visible_file_paths()
        target = preferred_path if preferred_path in visible_paths else None
        if target is None and self.current_path in visible_paths:
            target = self.current_path
        if target is None and visible_paths:
            target = visible_paths[0]

        self.file_list.blockSignals(True)
        self.file_list.clear()
        self.file_items.clear()
        for path in visible_paths:
            item = QListWidgetItem("")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(item)
            self.file_items[path] = item
            self._update_file_item_text(path)
        self.file_list.blockSignals(False)

        if not visible_paths:
            self.current_path = None
            self._clear_blocks()
            self.current_segment_lookup.clear()
            self.block_widgets.clear()
            self.selected_segment_uid = None
            self.current_reference_map = {}
            self.file_header_label.setText(
                "No visible files. Enable 'Show empty' to include files without dialogue blocks."
            )
            self._update_reset_json_button(None)
            self._refresh_translator_detail_panel()
            return

        assert target is not None
        row = visible_paths.index(target)
        self.file_list.setCurrentRow(row)

    def _load_data_folder(
        self,
        folder: Path,
        force_disk_import: bool = False,
        import_target_version: str = "working",
    ) -> None:
        if not folder.exists() or not folder.is_dir():
            QMessageBox.critical(self, "Invalid folder",
                                 f"Not a directory:\n{folder}")
            return

        if self.data_dir is not None and folder.resolve() != self.data_dir.resolve():
            if not self._prompt_unsaved_if_any():
                return
        elif self.data_dir is None and not self._prompt_unsaved_if_any():
            return

        if self.data_dir is not None:
            self._store_current_project_ui_settings()

        self.data_dir = folder.resolve()
        self.folder_edit.setText(str(self.data_dir))
        project_key = self._project_state_key(self.data_dir)
        project_settings = self.project_ui_settings_by_folder.get(project_key)
        if isinstance(project_settings, dict):
            self._apply_project_ui_settings(project_settings)
        self._save_ui_state()
        self._windowskin_text_colors.clear()
        self._windowskin_text_colors_loaded = False
        self._invalidate_audit_caches()

        if self.index_db is not None:
            self.index_db.close()
        if self.version_db is not None:
            self.version_db.close()
        self.index_db = DialogueIndexDB(self.data_dir / DB_FILENAME)
        self.version_db = DialogueVersionDB(self.data_dir / VERSION_DB_FILENAME)
        self.translation_state_path = self.data_dir / TRANSLATION_STATE_FILENAME
        self._load_translation_state()

        self.sessions.clear()
        self.current_path = None
        self.current_segment_lookup.clear()
        self.block_widgets.clear()
        self._clear_cached_block_views()
        self.reference_summary_cache_by_path.clear()
        self.selected_segment_uid = None
        self.current_reference_map = {}
        self.segment_uid_counter = 0
        self.speaker_custom_colors.clear()
        self._invalidate_speaker_auto_color_cache()
        self.audit_sanitize_ignored_entries_by_rule.clear()
        self.structural_undo_stack.clear()
        self.structural_redo_stack.clear()

        self.file_list.clear()
        self.file_items.clear()
        self._clear_blocks()
        self._update_reset_json_button(None)
        self._refresh_translator_detail_panel()

        all_json = [
            path for path in self.data_dir.glob("*.json")
            if path.is_file() and not path.name.endswith(".bak")
        ]
        all_json.sort(key=lambda p: natural_sort_key(p.name))
        self.file_paths = all_json

        if not self.file_paths:
            self.file_header_label.setText(
                "No JSON files found in selected folder")
            self._update_reset_json_button(None)
            self.save_btn.setEnabled(False)
            self.save_all_btn.setEnabled(False)
            self.apply_version_combo.setEnabled(False)
            self.apply_version_btn.setEnabled(False)
            self.next_problem_btn.setEnabled(False)
            self.selected_segment_uid = None
            self.current_reference_map = {}
            self._refresh_translator_detail_panel()
            self.statusBar().showMessage("No JSON files found.")
            return

        load_errors: list[str] = []
        loaded_from_db_count = 0
        loaded_from_disk_count = 0
        total_blocks = 0
        for path in self.file_paths:
            try:
                rel_path = self._relative_path(path)
                session: Optional[FileSession] = None
                loaded_from_db = False

                if not force_disk_import and self.version_db is not None:
                    payload = self.version_db.get_working_snapshot_payload(
                        rel_path)
                    if payload:
                        try:
                            decoded = json.loads(payload)
                            session = parse_dialogue_data(path, decoded)
                            loaded_from_db = True
                        except Exception:
                            session = None

                if session is None:
                    session = parse_dialogue_file(path)

                self._apply_translation_state_to_session(session)
                self.sessions[path] = session
                self.segment_uid_counter = max(
                    self.segment_uid_counter, len(session.segments))
                total_blocks += len(session.segments)

                if loaded_from_db:
                    loaded_from_db_count += 1
                else:
                    loaded_from_disk_count += 1

                if self.version_db is not None:
                    try:
                        if force_disk_import:
                            target_version = "translated" if import_target_version == "translated" else "working"
                            self.version_db.import_from_disk(
                                rel_path,
                                session.data,
                                target_version,
                            )
                        elif not loaded_from_db:
                            self.version_db.ensure_original_snapshot(
                                rel_path,
                                session.data,
                            )
                            self.version_db.save_working_snapshot(
                                rel_path,
                                session.data,
                            )
                            self.version_db.save_translated_snapshot(
                                rel_path,
                                self._export_translated_data_for_session(
                                    session),
                            )
                    except Exception:
                        pass
                if self.index_db is not None:
                    try:
                        self.index_db.update_file_index(
                            rel_path,
                            path.stat().st_mtime,
                            session.segments,
                        )
                    except Exception:
                        pass
            except Exception:
                load_errors.append(path.name)

        if not self.sessions:
            self.save_btn.setEnabled(False)
            self.save_all_btn.setEnabled(False)
            self.apply_version_combo.setEnabled(False)
            self.apply_version_btn.setEnabled(False)
            self.next_problem_btn.setEnabled(False)
            self.file_header_label.setText(
                "No readable JSON files found in selected folder.")
            self._update_reset_json_button(None)
            self.selected_segment_uid = None
            self.current_reference_map = {}
            self._refresh_translator_detail_panel()
            self.statusBar().showMessage("No readable JSON files found.")
            return

        has_explicit_speakers = any(
            segment.speaker_name != NO_SPEAKER_KEY
            for session in self.sessions.values()
            if not self._is_name_index_session(session)
            for segment in session.segments
        )
        auto_enabled_infer = False
        if not has_explicit_speakers and not self.infer_speaker_check.isChecked():
            self.infer_speaker_check.setChecked(True)
            auto_enabled_infer = True

        self.save_btn.setEnabled(True)
        self.save_all_btn.setEnabled(True)
        self.apply_version_combo.setEnabled(True)
        self.apply_version_btn.setEnabled(True)
        self.next_problem_btn.setEnabled(True)
        self._rebuild_file_list()

        visible_count = len(self._visible_file_paths())
        infer_suffix = " Infer speaker-from-line1 enabled (no explicit speakers found)." if auto_enabled_infer else ""
        if load_errors:
            skipped_label = "file" if len(load_errors) == 1 else "files"
            self.statusBar().showMessage(
                f"Loaded {len(self.sessions)} files ({visible_count} shown), "
                f"{total_blocks} blocks from DB:{loaded_from_db_count}/disk:{loaded_from_disk_count}. "
                f"Skipped {len(load_errors)} unreadable {skipped_label}.{infer_suffix}"
            )
        else:
            self.statusBar().showMessage(
                f"Loaded {len(self.sessions)} files ({visible_count} shown), "
                f"{total_blocks} blocks from DB:{loaded_from_db_count}/disk:{loaded_from_disk_count}.{infer_suffix}"
            )

    def _file_path_from_item(self, item: Optional[QListWidgetItem]) -> Optional[Path]:
        if item is None:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        if not raw:
            return None
        return Path(str(raw))

    def _on_file_selected(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        path = self._file_path_from_item(current)
        if path is None:
            return
        self._open_file(path)

    def _relative_path(self, path: Path) -> str:
        if self.data_dir is None:
            return path.name
        try:
            return str(path.relative_to(self.data_dir))
        except ValueError:
            return str(path)

    def _focus_existing_block_widget(self, uid: str) -> bool:
        widget = self.block_widgets.get(uid)
        if widget is None:
            return False
        if uid in self.current_segment_lookup:
            self.selected_segment_uid = uid
        self._refresh_block_visual_states()
        self._refresh_translator_detail_panel()

        def focus_and_reveal() -> None:
            widget.focus_editor()
            self.scroll_area.ensureWidgetVisible(widget, 20, 20)

        QTimer.singleShot(0, focus_and_reveal)
        return True

    def _open_file(self, path: Path, force_reload: bool = False, focus_uid: Optional[str] = None) -> None:
        previous_path = self.current_path
        if (
            not force_reload
            and previous_path is not None
            and previous_path == path
            and self._pending_render_state is None
        ):
            if focus_uid is None:
                return
            if self._focus_existing_block_widget(focus_uid):
                return

        if (
            not force_reload
            and focus_uid is None
            and previous_path is not None
            and previous_path == path
            and self._pending_render_state is None
        ):
            return
        try:
            if force_reload or path not in self.sessions:
                rel_path = self._relative_path(path)
                session: Optional[FileSession] = None
                if self.version_db is not None:
                    payload = self.version_db.get_working_snapshot_payload(
                        rel_path)
                    if payload:
                        try:
                            decoded = json.loads(payload)
                            session = parse_dialogue_data(path, decoded)
                        except Exception:
                            session = None
                if session is None:
                    session = parse_dialogue_file(path)
                self._apply_translation_state_to_session(session)
                self.sessions[path] = session
                self.segment_uid_counter = max(
                    self.segment_uid_counter, len(session.segments))
                self._clear_structural_history_for_path(path)
                self._invalidate_cached_block_view_for_path(path)
                self.reference_summary_cache_by_path.clear()
            else:
                session = self.sessions[path]
        except json.JSONDecodeError as exc:
            QMessageBox.critical(self, "JSON parse error",
                                 f"Failed to parse file:\n{path}\n\n{exc}")
            return
        except Exception as exc:
            QMessageBox.critical(
                self, "Error", f"Failed to open file:\n{path}\n\n{exc}")
            return

        self.current_path = path
        self._update_file_item_text(path)
        self._render_session(
            session,
            focus_uid=focus_uid,
            start_at_top=(previous_path != path and focus_uid is None),
        )

        if self.index_db is not None:
            try:
                self.index_db.update_file_index(
                    self._relative_path(path),
                    path.stat().st_mtime,
                    session.segments,
                )
            except Exception:
                pass

    def _rerender_current_file(self) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return
        self._clear_cached_block_views()
        self._render_session(session)

    def _on_layout_constraints_changed(self, _value: int) -> None:
        self._refresh_all_file_item_text()
        self._rerender_current_file()

    def _jump_to_next_problem(self) -> None:
        if not self.sessions:
            self.statusBar().showMessage("Load files before jumping to problems.")
            return

        translator_mode = self._is_translator_mode()
        ordered_files = [path for path in self.file_paths if path in self.sessions]
        problem_targets: list[tuple[Path, str]] = []
        for path in ordered_files:
            session = self.sessions.get(path)
            if session is None:
                continue
            for segment in session.segments:
                if self._segment_has_layout_problem(session, segment, translator_mode):
                    problem_targets.append((path, segment.uid))

        if not problem_targets:
            mode_label = "translator" if translator_mode else "plain"
            self.statusBar().showMessage(
                f"No layout problems found in {mode_label} mode.")
            return

        start_index = -1
        if self.current_path is not None:
            current_uid = self.selected_segment_uid or ""
            for idx, target in enumerate(problem_targets):
                if target[0] == self.current_path and target[1] == current_uid:
                    start_index = idx
                    break
            if start_index < 0:
                for idx, target in enumerate(problem_targets):
                    if target[0] == self.current_path:
                        start_index = idx - 1
                        break

        target_index = (start_index + 1) % len(problem_targets)
        target_path, target_uid = problem_targets[target_index]
        self._open_file(target_path, focus_uid=target_uid)
        self.statusBar().showMessage(
            f"Jumped to next problem ({target_index + 1}/{len(problem_targets)})."
        )

    def _on_hide_control_codes_toggled(self, checked: bool) -> None:
        scroll_bar = self.scroll_area.verticalScrollBar()
        previous_scroll = scroll_bar.value()
        for widget in self.block_widgets.values():
            widget.set_hide_control_codes_when_unfocused(bool(checked))
        self._clear_cached_block_views()
        if self.current_path is not None:
            session = self.sessions.get(self.current_path)
            if session is not None:
                self._update_reset_json_button(session)
        QTimer.singleShot(0, lambda: scroll_bar.setValue(previous_scroll))

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_middle_autoscroll()
        dirty = [session for session in self.sessions.values()
                 if session.dirty]
        if dirty:
            msg = QMessageBox(self)
            msg.setWindowTitle("Unsaved changes")
            msg.setText("Save unsaved changes before closing?")
            msg.setIcon(QMessageBox.Icon.Warning)
            save_btn = msg.addButton(
                "Save All", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = msg.addButton(
                "Cancel", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked is cancel_btn:
                event.ignore()
                return
            if clicked is save_btn and not self._save_all_files():
                event.ignore()
                return

        if self.index_db is not None:
            self.index_db.close()
        if self.version_db is not None:
            self.version_db.close()
        self.audit_search_worker_timer.stop()
        self.audit_sanitize_worker_timer.stop()
        self.audit_control_worker_timer.stop()
        try:
            self.audit_worker_executor.shutdown(
                wait=False, cancel_futures=True)
        except TypeError:
            self.audit_worker_executor.shutdown(wait=False)
        self._save_ui_state()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = DialogueVisualEditor()
    window.show()
    return app.exec()
