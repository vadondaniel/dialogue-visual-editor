from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import copy
import json
import logging
import re
import sys
import ctypes
from pathlib import Path
from time import monotonic
from typing import Any, Optional, cast

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCloseEvent,
    QCursor,
    QFont,
    QKeySequence,
    QKeyEvent,
    QMouseEvent,
    QShortcut,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QSpinBox,
    QSplitter,
    QTextEdit,
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
        configure_message_text_metrics,
        configure_name_text_metrics,
        configure_variable_text_metrics,
        align_source_translated_segments,
        looks_like_name_line,
        natural_sort_key,
        normalize_control_code_word_case,
        parse_dialogue_data,
        parse_dialogue_file,
        strip_control_tokens,
        trim_extra_ellipsis_runs,
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
        ExactMatchReviewDialog,
        ItemNameDescriptionWidget,
        MassTranslateDialog,
        SpeakerManagerDialog,
        VariableLengthManagerDialog,
        build_control_mismatch_selections,
    )
except ImportError:
    from helpers import (
        DialogueIndexDB,
        DialogueVersionDB,
        DialogueSegment,
        FileSession,
        NO_SPEAKER_KEY,
        StructuralAction,
        configure_message_text_metrics,
        configure_name_text_metrics,
        configure_variable_text_metrics,
        align_source_translated_segments,
        looks_like_name_line,
        natural_sort_key,
        normalize_control_code_word_case,
        parse_dialogue_data,
        parse_dialogue_file,
        strip_control_tokens,
        trim_extra_ellipsis_runs,
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
        ExactMatchReviewDialog,
        ItemNameDescriptionWidget,
        MassTranslateDialog,
        SpeakerManagerDialog,
        VariableLengthManagerDialog,
        build_control_mismatch_selections,
    )

try:
    from .helpers.core.logging_utils import (
        configure_file_logging,
        install_global_exception_hooks,
    )
except ImportError:
    from helpers.core.logging_utils import (
        configure_file_logging,
        install_global_exception_hooks,
    )

BlockWidgetType = DialogueBlockWidget | ItemNameDescriptionWidget
FILE_LIST_SECTION_ROLE = int(Qt.ItemDataRole.UserRole) + 1
logger = logging.getLogger(__name__)


class FileListItemDelegate(QStyledItemDelegate):
    def paint(
        self,
        painter: Any,
        option: QStyleOptionViewItem,
        index: Any,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        if index.data(FILE_LIST_SECTION_ROLE):
            opt_any = cast(Any, opt)
            state = getattr(opt_any, "state", None)
            if state is not None:
                state = state & ~QStyle.StateFlag.State_MouseOver
                state = state & ~QStyle.StateFlag.State_Selected
                setattr(opt_any, "state", state)
        super().paint(painter, opt, index)


DEFAULT_THIN_WIDTH = 47
DEFAULT_WIDE_WIDTH = 60
DEFAULT_MAX_LINES = 4
DB_FILENAME = ".dialogue_editor_index.sqlite3"
VERSION_DB_FILENAME = ".dialogue_version_state.sqlite3"
TRANSLATION_STATE_FILENAME = ".dialogue_translation_state.json"
UI_STATE_FILENAME = ".dialogue_visual_editor_ui_state.json"
APP_ID = "com.ceavan.dialoguevisualeditor"
APP_TITLE = "Dialogue Visual Editor"
DEFAULT_TRANSLATION_PROFILE_ID = "default"
DEFAULT_TRANSLATION_PROFILE_NAME = "Default"
_MV_DEFAULT_MESSAGE_FONT_SIZE = 28
_MZ_DEFAULT_MESSAGE_FONT_SIZE = 26
_JS_RETURN_INT_RE = re.compile(r"return\s+(-?\d+)\s*;")
_JS_SYSTEM_ADVANCED_FONT_RE = re.compile(
    r"\$dataSystem\s*\.\s*advanced\s*\.\s*fontSize"
)
_VARIABLE_TOKEN_RE = re.compile(r"\\[Vv]\[(\d+)\]")
_INLINE_COLOR_CODE_RE = re.compile(r"\\[Cc]\[(\d+)\]")
_DEFAULT_VARIABLE_LENGTH_ESTIMATE = 4
_MAX_VARIABLE_LENGTH_ESTIMATE = 64
_DEFAULT_SMART_COLLAPSE_SOFT_RATIO_PERCENT = 50
_DEFAULT_NAME_LENGTH_ESTIMATE = 8
_MAX_NAME_LENGTH_ESTIMATE = 64


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
        self.setWindowTitle(APP_TITLE)
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
        default_prompt_template = self._default_translation_prompt_template()
        self.active_translation_profile_id = DEFAULT_TRANSLATION_PROFILE_ID
        self.translation_profiles_meta: dict[str, dict[str, Any]] = {
            DEFAULT_TRANSLATION_PROFILE_ID: {
                "name": DEFAULT_TRANSLATION_PROFILE_NAME,
                "target_language_code": "en",
                "prompt_template": default_prompt_template,
            }
        }
        self.speaker_custom_colors: dict[str, str] = {}
        self.speaker_translation_map: dict[str, str] = {}
        self._speaker_auto_color_map: dict[str, str] = {}
        self._speaker_auto_color_theme_dark: Optional[bool] = None
        self._windowskin_text_colors: dict[int, str] = {}
        self._windowskin_text_colors_loaded = False
        self.translation_state_path: Optional[Path] = None
        self.last_folder_path = ""
        self.detected_rpg_engine = "unknown"
        self.detected_message_font_size = _MV_DEFAULT_MESSAGE_FONT_SIZE
        self.detected_message_font_source = "default"
        self.default_variable_length_estimate = _DEFAULT_VARIABLE_LENGTH_ESTIMATE
        self.variable_length_overrides: dict[int, int] = {}
        self.smart_collapse_soft_ratio_rule_enabled = True
        self.smart_collapse_allow_comma_endings = False
        self.smart_collapse_allow_colon_triplet_endings = False
        self.smart_collapse_ellipsis_lowercase_rule = False
        self.smart_collapse_collapse_if_no_punctuation = True
        self.smart_collapse_soft_ratio_percent = _DEFAULT_SMART_COLLAPSE_SOFT_RATIO_PERCENT
        self.ui_state_path = Path(
            __file__).resolve().with_name(UI_STATE_FILENAME)
        self.project_ui_settings_by_folder: dict[str, dict[str, Any]] = {}
        self._applying_project_ui_state = False
        self.translation_state: dict[str, Any] = {
            "version": 2,
            "active_profile_id": DEFAULT_TRANSLATION_PROFILE_ID,
            "source_language_code": "ja",
            "profiles": {
                DEFAULT_TRANSLATION_PROFILE_ID: {
                    "name": DEFAULT_TRANSLATION_PROFILE_NAME,
                    "uid_counter": 0,
                    "target_language_code": "en",
                    "prompt_template": default_prompt_template,
                    "speaker_map": {},
                    "files": {},
                }
            },
        }
        self._settings_translation_profiles_menu: Optional[QMenu] = None
        self._settings_translation_profiles_switch_menu: Optional[QMenu] = None
        self._settings_translation_profile_switch_group: Optional[QActionGroup] = None
        self._settings_translation_new_profile_action: Optional[QAction] = None
        self._settings_translation_profile_settings_action: Optional[QAction] = None
        self._settings_translation_project_source_action: Optional[QAction] = None
        self._settings_translation_rename_profile_action: Optional[QAction] = None
        self._settings_translation_delete_profile_action: Optional[QAction] = None
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
        self.audit_consistency_dialogue_only_check: Optional[QCheckBox] = None
        self.audit_consistency_sort_combo: Optional[QComboBox] = None
        self.audit_consistency_groups_list: Optional[QListWidget] = None
        self.audit_consistency_entries_list: Optional[QListWidget] = None
        self.audit_consistency_source_edit: Optional[QPlainTextEdit] = None
        self.audit_consistency_target_edit: Optional[QPlainTextEdit] = None
        self.audit_consistency_source_highlighter: Optional[ControlCodeHighlighter] = None
        self.audit_consistency_target_highlighter: Optional[ControlCodeHighlighter] = None
        self.audit_consistency_status_label: Optional[QLabel] = None
        self.audit_consistency_goto_btn: Optional[QPushButton] = None
        self.audit_consistency_apply_btn: Optional[QPushButton] = None
        self.audit_consistency_use_common_btn: Optional[QPushButton] = None
        self.audit_term_query_edit: Optional[QLineEdit] = None
        self.audit_term_candidates_edit: Optional[QLineEdit] = None
        self.audit_term_dialogue_only_check: Optional[QCheckBox] = None
        self.audit_term_variants_list: Optional[QListWidget] = None
        self.audit_term_hits_list: Optional[QListWidget] = None
        self.audit_term_status_label: Optional[QLabel] = None
        self.audit_term_goto_btn: Optional[QPushButton] = None
        self.audit_term_apply_canonical_btn: Optional[QPushButton] = None
        self.audit_term_suggest_jp_list: Optional[QListWidget] = None
        self.audit_term_suggest_en_list: Optional[QListWidget] = None
        self.audit_term_suggest_refresh_btn: Optional[QPushButton] = None
        self.audit_term_variants_progress_overlay: Optional[QLabel] = None
        self.audit_term_hits_progress_overlay: Optional[QLabel] = None
        self.mass_translate_dialog: Optional[MassTranslateDialog] = None
        self.audit_cache_generation = 0
        self.audit_result_batch_size = 16
        self.audit_render_batch_interval_ms = 8
        self.audit_search_cache_key: Optional[tuple[int, str, str, bool, bool]] = None
        self.audit_search_cache_records: list[dict[str, Any]] = []
        self.audit_search_render_records: list[dict[str, Any]] = []
        self.audit_search_render_index = 0
        self.audit_search_render_query = ""
        self.audit_search_render_scope = "original"
        self.audit_search_render_generation = 0
        self.audit_search_displayed_key: Optional[tuple[int, str, str, bool, bool]] = None
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
        self.audit_term_cache_key: Optional[tuple[int, str, str, bool]] = None
        self.audit_term_cache_groups: list[dict[str, Any]] = []
        self.audit_term_render_groups: list[dict[str, Any]] = []
        self.audit_term_render_index = 0
        self.audit_term_render_generation = 0
        self.audit_term_render_term = ""
        self.audit_term_render_candidates = ""
        self.audit_term_render_dialogue_only = True
        self.audit_term_displayed_key: Optional[tuple[int, str, str, bool]] = None
        self.audit_term_display_complete = False
        self.audit_term_render_timer = QTimer(self)
        self.audit_term_render_timer.setSingleShot(True)
        self.audit_term_render_timer.timeout.connect(
            self._render_next_audit_term_group_batch
        )
        self.audit_term_hits_render_entries: list[dict[str, Any]] = []
        self.audit_term_hits_render_index = 0
        self.audit_term_hits_render_group_key = ""
        self._audit_term_hits_render_candidates: list[str] = []
        self.audit_term_hits_render_timer = QTimer(self)
        self.audit_term_hits_render_timer.setSingleShot(True)
        self.audit_term_hits_render_timer.timeout.connect(
            self._render_next_audit_term_hits_batch
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
        self.audit_term_worker_future: Optional[Future] = None
        self.audit_term_worker_running_request: Optional[dict[str, Any]] = None
        self.audit_term_worker_pending_request: Optional[dict[str, Any]] = None
        self.audit_term_worker_timer = QTimer(self)
        self.audit_term_worker_timer.setSingleShot(True)
        self.audit_term_worker_timer.timeout.connect(
            self._poll_audit_term_worker)
        self.structural_undo_stack: list[StructuralAction] = []
        self.structural_redo_stack: list[StructuralAction] = []
        self._pending_render_state: Optional[dict[str, Any]] = None
        self._render_batch_size = 2
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
        self._theme_refresh_timer = QTimer(self)
        self._theme_refresh_timer.setSingleShot(True)
        self._theme_refresh_timer.setInterval(60)
        self._theme_refresh_timer.timeout.connect(self._apply_runtime_theme_refresh)
        self._current_palette_dark = is_dark_palette()

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
        self._next_problem_shortcut = QShortcut(QKeySequence("F5"), self)
        self._next_problem_shortcut.activated.connect(self._jump_to_next_problem)

        self._sync_variable_length_measurement_settings()
        self._build_ui()
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.installEventFilter(self)
        self._default_v_scroll_policy = self.scroll_area.verticalScrollBarPolicy()
        self._default_h_scroll_policy = self.scroll_area.horizontalScrollBarPolicy()
        self._update_mode_controls()
        self._load_ui_state()
        self._update_window_title()
        if self.data_dir is None:
            self.statusBar().showMessage("Open a data folder to start.")

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._init_hidden_settings_controls()
        self._build_menu_bar()

        self.thin_width_spin.valueChanged.connect(
            self._on_layout_constraints_changed)
        self.wide_width_spin.valueChanged.connect(
            self._on_layout_constraints_changed)
        self.max_lines_spin.valueChanged.connect(
            self._on_layout_constraints_changed)
        self.thin_width_spin.valueChanged.connect(
            self._sync_settings_limits_menu_labels)
        self.wide_width_spin.valueChanged.connect(
            self._sync_settings_limits_menu_labels)
        self.max_lines_spin.valueChanged.connect(
            self._sync_settings_limits_menu_labels)
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
        self.problem_char_limit_check.toggled.connect(
            self._on_problem_checks_changed
        )
        self.problem_line_limit_check.toggled.connect(
            self._on_problem_checks_changed
        )
        self.problem_control_mismatch_check.toggled.connect(
            self._on_problem_checks_changed
        )
        self.problem_trailing_color_code_check.toggled.connect(
            self._on_problem_checks_changed
        )
        self.problem_missing_translation_check.toggled.connect(
            self._on_problem_checks_changed
        )
        self.problem_contains_japanese_check.toggled.connect(
            self._on_problem_checks_changed
        )
        self.problem_char_limit_check.toggled.connect(self._on_project_setting_changed)
        self.problem_line_limit_check.toggled.connect(self._on_project_setting_changed)
        self.problem_control_mismatch_check.toggled.connect(
            self._on_project_setting_changed
        )
        self.problem_trailing_color_code_check.toggled.connect(
            self._on_project_setting_changed
        )
        self.problem_missing_translation_check.toggled.connect(
            self._on_project_setting_changed
        )
        self.problem_contains_japanese_check.toggled.connect(
            self._on_project_setting_changed
        )
        self.hide_non_meaningful_entries_check.toggled.connect(
            self._on_hide_non_meaningful_toggled
        )
        self.hide_non_meaningful_entries_check.toggled.connect(
            self._on_project_setting_changed
        )

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
        self.file_list.setItemDelegate(FileListItemDelegate(self.file_list))
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
        self.next_problem_btn = QPushButton("Next Problem")
        self.next_problem_btn.setToolTip(
            "Jump to the next block that exceeds width or max-lines in the current mode."
        )
        self.next_problem_btn.clicked.connect(self._jump_to_next_problem)
        self.next_problem_btn.setEnabled(False)
        file_header_row.addWidget(self.next_problem_btn)
        self._update_problem_checks_ui()
        header_row_height = max(
            self.file_header_label.sizeHint().height(),
            self.next_problem_btn.sizeHint().height(),
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
        self.translator_speaker_jp_edit = QLabel("")
        self.translator_speaker_jp_edit.setTextFormat(Qt.TextFormat.RichText)
        self.translator_speaker_jp_edit.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.translator_speaker_jp_edit.setWordWrap(False)
        speaker_jp_row.addWidget(self.translator_speaker_jp_edit, 1)
        detail_content_layout.addWidget(self.translator_speaker_jp_row)

        self.translator_speaker_en_row = QWidget()
        speaker_en_row = QHBoxLayout(self.translator_speaker_en_row)
        speaker_en_row.setContentsMargins(0, 0, 0, 0)
        self.translator_speaker_en_label = QLabel("Speaker EN")
        speaker_en_row.addWidget(self.translator_speaker_en_label)
        self.translator_speaker_en_edit = QLabel("")
        self.translator_speaker_en_edit.setTextFormat(Qt.TextFormat.RichText)
        self.translator_speaker_en_edit.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.translator_speaker_en_edit.setWordWrap(False)
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
            resolve_color_flow=True,
        )
        detail_content_layout.addWidget(self.translator_source_view, 1)

        self.translator_reference_exact_label = QLabel("")
        self.translator_reference_exact_label.setWordWrap(True)
        self.translator_reference_exact_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        detail_content_layout.addWidget(self.translator_reference_exact_label)
        self.translator_review_exact_matches_btn = QPushButton(
            "Review Exact Matches..."
        )
        self.translator_review_exact_matches_btn.clicked.connect(
            self._open_exact_match_review_dialog
        )
        detail_content_layout.addWidget(self.translator_review_exact_matches_btn)

        self.translator_reference_similar_label = QLabel("")
        self.translator_reference_similar_label.setWordWrap(True)
        self.translator_reference_similar_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
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

    def _init_hidden_settings_controls(self) -> None:
        self.remember_folder_check = QCheckBox(self)
        self.remember_folder_check.setChecked(False)
        self.remember_folder_check.setToolTip(
            "Remember last project folder and reopen it on startup."
        )
        self.remember_folder_check.toggled.connect(self._on_remember_folder_toggled)

        self.editor_mode_combo = QComboBox(self)
        self.editor_mode_combo.addItem("Plain Edit", "plain")
        self.editor_mode_combo.addItem("Translator Edit", "translator")
        self.editor_mode_combo.setToolTip(
            "Plain Edit modifies JSON directly. Translator Edit keeps source read-only and edits translation data."
        )

        self.thin_width_spin = QSpinBox(self)
        self.thin_width_spin.setRange(10, 200)
        self.thin_width_spin.setValue(DEFAULT_THIN_WIDTH)

        self.wide_width_spin = QSpinBox(self)
        self.wide_width_spin.setRange(10, 240)
        self.wide_width_spin.setValue(DEFAULT_WIDE_WIDTH)

        self.max_lines_spin = QSpinBox(self)
        self.max_lines_spin.setRange(1, 20)
        self.max_lines_spin.setValue(DEFAULT_MAX_LINES)

        self.auto_split_check = QCheckBox(self)
        self.auto_split_check.setChecked(True)

        self.infer_speaker_check = QCheckBox(self)
        self.infer_speaker_check.setChecked(False)
        self.infer_speaker_check.setToolTip(
            "Only used when code 101 speaker is empty; tries to detect a speaker from the first text line."
        )

        self.hide_control_codes_check = QCheckBox(self)
        self.hide_control_codes_check.setChecked(True)
        self.hide_control_codes_check.setToolTip(
            "When enabled, control codes are hidden in unfocused dialogue editors and shown when focused."
        )

        self.backup_check = QCheckBox(self)
        self.backup_check.setChecked(True)

        self.problem_char_limit_check = QCheckBox(self)
        self.problem_char_limit_check.setChecked(True)
        self.problem_char_limit_check.setToolTip(
            "Treat character-width overflow as a problem."
        )

        self.problem_line_limit_check = QCheckBox(self)
        self.problem_line_limit_check.setChecked(True)
        self.problem_line_limit_check.setToolTip(
            "Treat line-count overflow as a problem."
        )

        self.problem_control_mismatch_check = QCheckBox(self)
        self.problem_control_mismatch_check.setChecked(False)
        self.problem_control_mismatch_check.setToolTip(
            "Treat control-code token mismatches between source and translation as a problem."
        )

        self.problem_trailing_color_code_check = QCheckBox(self)
        self.problem_trailing_color_code_check.setChecked(False)
        self.problem_trailing_color_code_check.setToolTip(
            "Treat missing/mismatched trailing \\C[n] token (when JP ends with one) as a problem."
        )

        self.problem_missing_translation_check = QCheckBox(self)
        self.problem_missing_translation_check.setChecked(False)
        self.problem_missing_translation_check.setToolTip(
            "Treat untranslated dialogue blocks (source has visible text, translation is empty) as a problem."
        )

        self.problem_contains_japanese_check = QCheckBox(self)
        self.problem_contains_japanese_check.setChecked(False)
        self.problem_contains_japanese_check.setToolTip(
            "Treat translated text that still contains Japanese characters as a problem."
        )

        self.hide_non_meaningful_entries_check = QCheckBox(self)
        self.hide_non_meaningful_entries_check.setChecked(False)
        self.hide_non_meaningful_entries_check.setToolTip(
            "Hide empty map displayName entries and plugins.js parameters that are bool/on-off/none/number-list values."
        )

        self.apply_version_combo = QComboBox(self)
        self.apply_version_combo.addItem("Original", "original")
        self.apply_version_combo.addItem("Working", "working")
        self.apply_version_combo.addItem("Translated", "translated")
        self.apply_version_combo.setCurrentIndex(1)
        self.apply_version_combo.setToolTip(
            "Choose which snapshot version to apply to game files."
        )

        self._settings_plain_mode_action: Optional[QAction] = None
        self._settings_translator_mode_action: Optional[QAction] = None
        self._settings_thin_width_action: Optional[QAction] = None
        self._settings_wide_width_action: Optional[QAction] = None
        self._settings_max_lines_action: Optional[QAction] = None
        self._settings_smart_collapse_soft_rule_action: Optional[QAction] = None
        self._settings_smart_collapse_allow_comma_action: Optional[QAction] = None
        self._settings_smart_collapse_allow_colon_triplet_action: Optional[QAction] = None
        self._settings_smart_collapse_ellipsis_lowercase_action: Optional[QAction] = None
        self._settings_smart_collapse_no_punctuation_action: Optional[QAction] = None
        self._settings_smart_collapse_soft_ratio_action: Optional[QAction] = None
        self._settings_toggle_bindings: list[tuple[QAction, QCheckBox]] = []
        self._apply_to_game_files_actions: list[QAction] = []

        hidden_controls: tuple[QWidget, ...] = (
            self.remember_folder_check,
            self.editor_mode_combo,
            self.thin_width_spin,
            self.wide_width_spin,
            self.max_lines_spin,
            self.auto_split_check,
            self.infer_speaker_check,
            self.hide_control_codes_check,
            self.backup_check,
            self.problem_char_limit_check,
            self.problem_line_limit_check,
            self.problem_control_mismatch_check,
            self.problem_trailing_color_code_check,
            self.problem_missing_translation_check,
            self.problem_contains_japanese_check,
            self.hide_non_meaningful_entries_check,
            self.apply_version_combo,
        )
        for control in hidden_controls:
            control.setVisible(False)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.clear()

        file_menu = menu_bar.addMenu("File")
        open_folder_action = QAction("Open Data Folder...", self)
        open_folder_action.triggered.connect(self._choose_folder)
        file_menu.addAction(open_folder_action)

        reload_folder_action = QAction("Reload Folder", self)
        reload_folder_action.triggered.connect(self._reload_folder_from_text)
        file_menu.addAction(reload_folder_action)

        file_menu.addSeparator()
        self.save_btn = QAction("Save", self)
        self.save_btn.setShortcut(QKeySequence.StandardKey.Save)
        self.save_btn.setEnabled(False)
        self.save_btn.triggered.connect(self._save_current_file)
        file_menu.addAction(self.save_btn)

        self.save_all_btn = QAction("Save All", self)
        self.save_all_btn.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_all_btn.setEnabled(False)
        self.save_all_btn.triggered.connect(self._save_all_files)
        file_menu.addAction(self.save_all_btn)

        file_menu.addSeparator()
        apply_menu = file_menu.addMenu("Apply To Game Files")
        self._apply_to_game_files_actions = []
        apply_versions: tuple[tuple[str, str], ...] = (
            ("Original", "original"),
            ("Working", "working"),
            ("Translated", "translated"),
        )
        for version_label, version_data in apply_versions:
            apply_action = QAction(f"Apply {version_label}", self)
            apply_action.setEnabled(False)
            apply_action.triggered.connect(
                lambda _checked=False, v=version_data: self._apply_snapshot_version_from_menu(v)
            )
            apply_menu.addAction(apply_action)
            self._apply_to_game_files_actions.append(apply_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menu_bar.addMenu("Tools")
        speakers_action = QAction("Speakers...", self)
        speakers_action.setShortcut(QKeySequence("F1"))
        speakers_action.triggered.connect(self._open_speaker_manager)
        tools_menu.addAction(speakers_action)

        variable_lengths_action = QAction("Variable Lengths...", self)
        variable_lengths_action.setShortcut(QKeySequence("F6"))
        variable_lengths_action.triggered.connect(
            self._open_variable_length_manager
        )
        tools_menu.addAction(variable_lengths_action)

        mass_translate_action = QAction("Mass Translate...", self)
        mass_translate_action.setShortcut(QKeySequence("F2"))
        mass_translate_action.triggered.connect(self._open_mass_translate_dialog)
        tools_menu.addAction(mass_translate_action)

        translations_action = QAction("Translations...", self)
        translations_action.setShortcut(QKeySequence("F7"))
        translations_action.triggered.connect(
            self._open_translation_settings_dialog
        )
        tools_menu.addAction(translations_action)

        normalize_codes_action = QAction("Normalize Codes...", self)
        normalize_codes_action.setShortcut(QKeySequence("F3"))
        normalize_codes_action.triggered.connect(self._open_normalize_codes_dialog)
        tools_menu.addAction(normalize_codes_action)

        audit_action = QAction("Audit...", self)
        audit_action.setShortcut(QKeySequence("F4"))
        audit_action.triggered.connect(self._open_audit_window)
        tools_menu.addAction(audit_action)

        tools_menu.addSeparator()
        smart_collapse_all_action = QAction("Smart Collapse All...", self)
        smart_collapse_all_action.triggered.connect(
            self._smart_collapse_all_dialogue_blocks
        )
        tools_menu.addAction(smart_collapse_all_action)

        trim_ellipses_action = QAction("Trim Extra Ellipses...", self)
        trim_ellipses_action.triggered.connect(self._open_trim_extra_ellipses_dialog)
        tools_menu.addAction(trim_ellipses_action)

        self._settings_translation_profiles_menu = None
        self._settings_translation_profiles_switch_menu = None
        self._settings_translation_new_profile_action = None
        self._settings_translation_profile_settings_action = None
        self._settings_translation_project_source_action = None
        self._settings_translation_rename_profile_action = None
        self._settings_translation_delete_profile_action = None
        self._rebuild_translation_profile_menu()

        settings_menu = menu_bar.addMenu("Settings")
        mode_menu = settings_menu.addMenu("Edit Mode")
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        plain_mode_action = QAction("Plain Edit", self)
        plain_mode_action.setCheckable(True)
        plain_mode_action.triggered.connect(self._set_plain_edit_mode_from_menu)
        mode_menu.addAction(plain_mode_action)
        mode_group.addAction(plain_mode_action)

        translator_mode_action = QAction("Translator Edit", self)
        translator_mode_action.setCheckable(True)
        translator_mode_action.triggered.connect(
            self._set_translator_edit_mode_from_menu
        )
        mode_menu.addAction(translator_mode_action)
        mode_group.addAction(translator_mode_action)

        self._settings_plain_mode_action = plain_mode_action
        self._settings_translator_mode_action = translator_mode_action
        self.editor_mode_combo.currentIndexChanged.connect(
            self._sync_settings_menu_from_controls
        )
        self._sync_settings_menu_from_controls()

        limits_menu = settings_menu.addMenu("Layout Constraints")
        self._settings_thin_width_action = QAction("", self)
        self._settings_thin_width_action.triggered.connect(
            self._set_thin_width_from_menu
        )
        limits_menu.addAction(self._settings_thin_width_action)

        self._settings_wide_width_action = QAction("", self)
        self._settings_wide_width_action.triggered.connect(
            self._set_wide_width_from_menu
        )
        limits_menu.addAction(self._settings_wide_width_action)

        self._settings_max_lines_action = QAction("", self)
        self._settings_max_lines_action.triggered.connect(
            self._set_max_lines_from_menu
        )
        limits_menu.addAction(self._settings_max_lines_action)
        self._sync_settings_limits_menu_labels()

        smart_collapse_menu = settings_menu.addMenu("Smart Collapse")
        self._settings_smart_collapse_soft_rule_action = QAction(
            "Collapse if previous line is shorter than threshold",
            self,
        )
        self._settings_smart_collapse_soft_rule_action.setCheckable(True)
        self._settings_smart_collapse_soft_rule_action.toggled.connect(
            self._set_smart_collapse_soft_rule_enabled
        )
        smart_collapse_menu.addAction(self._settings_smart_collapse_soft_rule_action)

        self._settings_smart_collapse_allow_comma_action = QAction(
            "Collapse if previous line ends with comma (, 、 ，)",
            self,
        )
        self._settings_smart_collapse_allow_comma_action.setCheckable(True)
        self._settings_smart_collapse_allow_comma_action.toggled.connect(
            self._set_smart_collapse_allow_comma_enabled
        )
        smart_collapse_menu.addAction(self._settings_smart_collapse_allow_comma_action)

        self._settings_smart_collapse_allow_colon_triplet_action = QAction(
            "Collapse if previous line ends with ...",
            self,
        )
        self._settings_smart_collapse_allow_colon_triplet_action.setCheckable(True)
        self._settings_smart_collapse_allow_colon_triplet_action.toggled.connect(
            self._set_smart_collapse_allow_colon_triplet_enabled
        )
        smart_collapse_menu.addAction(
            self._settings_smart_collapse_allow_colon_triplet_action
        )

        self._settings_smart_collapse_ellipsis_lowercase_action = QAction(
            "Collapse if previous line ends with ... and next starts lowercase",
            self,
        )
        self._settings_smart_collapse_ellipsis_lowercase_action.setCheckable(True)
        self._settings_smart_collapse_ellipsis_lowercase_action.toggled.connect(
            self._set_smart_collapse_ellipsis_lowercase_rule_enabled
        )
        smart_collapse_menu.addAction(
            self._settings_smart_collapse_ellipsis_lowercase_action
        )

        self._settings_smart_collapse_no_punctuation_action = QAction(
            "Collapse if previous line ends without punctuation",
            self,
        )
        self._settings_smart_collapse_no_punctuation_action.setCheckable(True)
        self._settings_smart_collapse_no_punctuation_action.toggled.connect(
            self._set_smart_collapse_collapse_if_no_punctuation_enabled
        )
        smart_collapse_menu.addAction(
            self._settings_smart_collapse_no_punctuation_action
        )

        self._settings_smart_collapse_soft_ratio_action = QAction("", self)
        self._settings_smart_collapse_soft_ratio_action.triggered.connect(
            self._set_smart_collapse_soft_ratio_from_menu
        )
        smart_collapse_menu.addAction(
            self._settings_smart_collapse_soft_ratio_action
        )
        self._sync_smart_collapse_menu_state()

        problem_checks_menu = settings_menu.addMenu("Problem Checks")
        problem_char_limit_action = QAction("Flag char-width overflow", self)
        self._bind_toggle_menu_action(
            problem_char_limit_action, self.problem_char_limit_check
        )
        problem_checks_menu.addAction(problem_char_limit_action)

        problem_line_limit_action = QAction("Flag line-count overflow", self)
        self._bind_toggle_menu_action(
            problem_line_limit_action, self.problem_line_limit_check
        )
        problem_checks_menu.addAction(problem_line_limit_action)

        problem_control_mismatch_action = QAction(
            "Flag control-code mismatches",
            self,
        )
        self._bind_toggle_menu_action(
            problem_control_mismatch_action, self.problem_control_mismatch_check
        )
        problem_checks_menu.addAction(problem_control_mismatch_action)

        problem_trailing_color_code_action = QAction(
            "Flag trailing \\C[n] mismatch",
            self,
        )
        self._bind_toggle_menu_action(
            problem_trailing_color_code_action,
            self.problem_trailing_color_code_check,
        )
        problem_checks_menu.addAction(problem_trailing_color_code_action)

        problem_missing_translation_action = QAction(
            "Flag missing translation",
            self,
        )
        self._bind_toggle_menu_action(
            problem_missing_translation_action,
            self.problem_missing_translation_check,
        )
        problem_checks_menu.addAction(problem_missing_translation_action)

        problem_contains_japanese_action = QAction(
            "Flag Japanese in translation",
            self,
        )
        self._bind_toggle_menu_action(
            problem_contains_japanese_action,
            self.problem_contains_japanese_check,
        )
        problem_checks_menu.addAction(problem_contains_japanese_action)

        settings_menu.addSeparator()
        hide_non_meaningful_action = QAction(
            "Hide non-meaningful entries",
            self,
        )
        self._bind_toggle_menu_action(
            hide_non_meaningful_action,
            self.hide_non_meaningful_entries_check,
        )
        settings_menu.addAction(hide_non_meaningful_action)

        settings_menu.addSeparator()
        auto_split_action = QAction("Auto-split overflow on save", self)
        self._bind_toggle_menu_action(auto_split_action, self.auto_split_check)
        settings_menu.addAction(auto_split_action)

        infer_speaker_action = QAction("Infer speaker from line 1", self)
        self._bind_toggle_menu_action(infer_speaker_action, self.infer_speaker_check)
        settings_menu.addAction(infer_speaker_action)

        hide_control_codes_action = QAction("Hide control codes unless focused", self)
        self._bind_toggle_menu_action(
            hide_control_codes_action, self.hide_control_codes_check
        )
        settings_menu.addAction(hide_control_codes_action)

        backup_action = QAction("Create .bak backup", self)
        self._bind_toggle_menu_action(backup_action, self.backup_check)
        settings_menu.addAction(backup_action)

        settings_menu.addSeparator()
        remember_folder_action = QAction("Remember last folder", self)
        self._bind_toggle_menu_action(
            remember_folder_action, self.remember_folder_check
        )
        settings_menu.addAction(remember_folder_action)
        self._sync_settings_toggle_actions_from_controls()
        self._update_problem_checks_ui()

    def _bind_toggle_menu_action(self, action: QAction, checkbox: QCheckBox) -> None:
        action.setCheckable(True)
        action.setChecked(bool(checkbox.isChecked()))
        action.toggled.connect(checkbox.setChecked)
        checkbox.toggled.connect(action.setChecked)
        self._settings_toggle_bindings.append((action, checkbox))

    def _sync_settings_toggle_actions_from_controls(self) -> None:
        for action, checkbox in self._settings_toggle_bindings:
            target_checked = bool(checkbox.isChecked())
            if action.isChecked() == target_checked:
                continue
            action.blockSignals(True)
            try:
                action.setChecked(target_checked)
            finally:
                action.blockSignals(False)

    def _translation_profile_ids_sorted(self) -> list[str]:
        profiles_raw = self.translation_state.get("profiles")
        profile_ids = [
            key.strip()
            for key in profiles_raw.keys()
            if isinstance(key, str) and key.strip()
        ] if isinstance(profiles_raw, dict) else []
        if not profile_ids:
            return [DEFAULT_TRANSLATION_PROFILE_ID]
        unique_ids = list(dict.fromkeys(profile_ids))
        unique_ids.sort(key=natural_sort_key)
        return unique_ids

    def _translation_profile_name(self, profile_id: str) -> str:
        meta = self.translation_profiles_meta.get(profile_id)
        if isinstance(meta, dict):
            raw_name = meta.get("name")
            if isinstance(raw_name, str) and raw_name.strip():
                return raw_name.strip()
        profiles_raw = self.translation_state.get("profiles")
        if isinstance(profiles_raw, dict):
            profile_state = profiles_raw.get(profile_id)
            if isinstance(profile_state, dict):
                raw_name = profile_state.get("name")
                if isinstance(raw_name, str) and raw_name.strip():
                    return raw_name.strip()
        if profile_id == DEFAULT_TRANSLATION_PROFILE_ID:
            return DEFAULT_TRANSLATION_PROFILE_NAME
        return profile_id

    def _translation_profile_choice_label(self, profile_id: str) -> str:
        profile_name = self._translation_profile_name(profile_id)
        target_language_code = self._translation_profile_target_language_code(profile_id)
        if profile_name == profile_id:
            return f"{profile_name} [{target_language_code}]"
        return f"{profile_name} ({profile_id}) [{target_language_code}]"

    def _generate_translation_profile_id(self, display_name: str) -> str:
        normalized_base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
        if not normalized_base:
            normalized_base = "profile"
        existing_ids = set(self._translation_profile_ids_sorted())
        if normalized_base not in existing_ids:
            return normalized_base
        suffix = 2
        while True:
            candidate = f"{normalized_base}-{suffix}"
            if candidate not in existing_ids:
                return candidate
            suffix += 1

    def _rebuild_translation_profile_menu(self) -> None:
        switch_menu = self._settings_translation_profiles_switch_menu
        profile_ids = self._translation_profile_ids_sorted()
        if switch_menu is not None:
            switch_menu.clear()
            action_group = QActionGroup(self)
            action_group.setExclusive(True)
            self._settings_translation_profile_switch_group = action_group
            for profile_id in profile_ids:
                action = QAction(self._translation_profile_choice_label(profile_id), self)
                action.setCheckable(True)
                action.setChecked(profile_id == self.active_translation_profile_id)
                action.triggered.connect(
                    lambda checked=False, pid=profile_id: (
                        self._switch_translation_profile(pid)
                        if checked
                        else None
                    )
                )
                switch_menu.addAction(action)
                action_group.addAction(action)

        has_folder = self.data_dir is not None
        if self._settings_translation_new_profile_action is not None:
            self._settings_translation_new_profile_action.setEnabled(has_folder)
        if self._settings_translation_profile_settings_action is not None:
            self._settings_translation_profile_settings_action.setEnabled(
                has_folder and bool(profile_ids)
            )
        if self._settings_translation_project_source_action is not None:
            self._settings_translation_project_source_action.setEnabled(has_folder)
        if self._settings_translation_rename_profile_action is not None:
            self._settings_translation_rename_profile_action.setEnabled(
                has_folder and bool(profile_ids)
            )
        if self._settings_translation_delete_profile_action is not None:
            self._settings_translation_delete_profile_action.setEnabled(
                has_folder and len(profile_ids) > 1
            )

    def _open_translation_settings_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Translations")
        dialog.resize(760, 460)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        main_row = QHBoxLayout()
        main_row.setSpacing(10)
        layout.addLayout(main_row, 1)

        profiles_group = QGroupBox("Profiles", dialog)
        profiles_layout = QVBoxLayout(profiles_group)
        profiles_layout.setContentsMargins(8, 8, 8, 8)
        profiles_layout.setSpacing(6)
        profiles_list = QListWidget(profiles_group)
        profiles_list.setAlternatingRowColors(True)
        profiles_layout.addWidget(profiles_list, 1)
        main_row.addWidget(profiles_group, 1)

        details_group = QGroupBox("Selected Profile", dialog)
        details_form = QFormLayout(details_group)

        selected_name_label = QLabel(details_group)
        selected_name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_form.addRow("Name", selected_name_label)

        selected_id_label = QLabel(details_group)
        selected_id_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_form.addRow("Profile ID", selected_id_label)

        selected_target_label = QLabel(details_group)
        selected_target_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_form.addRow("Target language", selected_target_label)

        selected_warning_label = QLabel(details_group)
        selected_warning_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_form.addRow("Warnings", selected_warning_label)

        selected_progress_label = QLabel(details_group)
        selected_progress_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_form.addRow("Translated strings", selected_progress_label)

        source_language_label = QLabel(details_group)
        source_language_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        details_form.addRow("Project source", source_language_label)

        main_row.addWidget(details_group, 1)

        def selected_profile_id() -> str:
            current_item = profiles_list.currentItem()
            if current_item is None:
                return ""
            profile_id_raw = current_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(profile_id_raw, str):
                return ""
            return profile_id_raw.strip()

        def profile_stats(profile_id: str) -> tuple[int, int, int]:
            profile_state = self._ensure_translation_profile(profile_id)
            files_raw = profile_state.get("files")
            translated_count = 0
            total_count = 0
            warning_count = 0
            if not isinstance(files_raw, dict):
                return translated_count, total_count, warning_count

            for file_state_raw in files_raw.values():
                if not isinstance(file_state_raw, dict):
                    continue
                entries_raw = file_state_raw.get("entries")
                if not isinstance(entries_raw, dict):
                    continue
                for entry_raw in entries_raw.values():
                    if not isinstance(entry_raw, dict):
                        continue
                    if bool(entry_raw.get("translation_only", False)):
                        continue
                    if not self._translation_state_entry_is_meaningful_for_display(
                        entry_raw
                    ):
                        continue

                    total_count += 1
                    translation_lines_raw = entry_raw.get("translation_lines", [])
                    if isinstance(translation_lines_raw, list):
                        translation_lines = [
                            line if isinstance(line, str) else str(line)
                            for line in translation_lines_raw
                        ]
                    elif isinstance(translation_lines_raw, str):
                        translation_lines = [translation_lines_raw]
                    else:
                        translation_lines = []
                    has_translation = any(line.strip() for line in translation_lines)
                    if has_translation:
                        translated_count += 1
                    else:
                        warning_count += 1
            return translated_count, total_count, warning_count

        def refresh_selected_profile_details() -> None:
            profile_id = selected_profile_id()
            source_language_label.setText(self._translation_project_source_language_code())
            if not profile_id:
                selected_name_label.setText("-")
                selected_id_label.setText("-")
                selected_target_label.setText("-")
                selected_warning_label.setText("0")
                selected_progress_label.setText("0 / 0")
                return
            translated_count, total_count, warning_count = profile_stats(profile_id)
            profile_name = self._translation_profile_name(profile_id)
            if profile_id == self.active_translation_profile_id:
                profile_name = f"{profile_name}"
            selected_name_label.setText(profile_name)
            selected_id_label.setText(profile_id)
            selected_target_label.setText(
                self._translation_profile_target_language_code(profile_id)
            )
            selected_warning_label.setText(str(warning_count))
            selected_progress_label.setText(f"{translated_count} / {total_count}")

        def refresh_profiles_list(preferred_profile_id: Optional[str] = None) -> None:
            profile_ids = self._translation_profile_ids_sorted()
            preferred = preferred_profile_id or selected_profile_id() or self.active_translation_profile_id
            profiles_list.blockSignals(True)
            try:
                profiles_list.clear()
                for profile_id in profile_ids:
                    translated_count, total_count, warning_count = profile_stats(profile_id)
                    _ = warning_count
                    profile_name = self._translation_profile_name(profile_id)
                    if total_count > 0:
                        percent_value = int(round((translated_count / total_count) * 100))
                        percent_text = f"{percent_value}%"
                    else:
                        percent_text = "--"
                    if profile_id == self.active_translation_profile_id:
                        row_text = f"{profile_name} {percent_text} [ACTIVE]"
                    else:
                        row_text = f"{profile_name} {percent_text}"
                    item = QListWidgetItem(row_text)
                    item.setData(Qt.ItemDataRole.UserRole, profile_id)
                    profiles_list.addItem(item)
                target_id = preferred if preferred else self.active_translation_profile_id
                selected_row = -1
                for row in range(profiles_list.count()):
                    item = profiles_list.item(row)
                    profile_id_raw = item.data(Qt.ItemDataRole.UserRole)
                    if isinstance(profile_id_raw, str) and profile_id_raw == target_id:
                        selected_row = row
                        break
                if selected_row < 0 and profiles_list.count() > 0:
                    selected_row = 0
                if selected_row >= 0:
                    profiles_list.setCurrentRow(selected_row)
            finally:
                profiles_list.blockSignals(False)
            refresh_selected_profile_details()

        def switch_selected_profile() -> None:
            profile_id = selected_profile_id()
            if not profile_id:
                return
            self._switch_translation_profile(profile_id)
            refresh_profiles_list(preferred_profile_id=profile_id)

        def create_profile() -> None:
            self._create_translation_profile()
            refresh_profiles_list(preferred_profile_id=self.active_translation_profile_id)

        def rename_profile() -> None:
            profile_id = selected_profile_id()
            if not profile_id:
                return
            if self._rename_translation_profile(profile_id):
                refresh_profiles_list(preferred_profile_id=profile_id)

        def delete_profile() -> None:
            profile_id = selected_profile_id()
            if not profile_id:
                return
            if self._delete_translation_profile(profile_id):
                refresh_profiles_list(preferred_profile_id=self.active_translation_profile_id)

        def edit_profile_settings() -> None:
            profile_id = selected_profile_id()
            if not profile_id:
                return
            if self._edit_translation_profile_settings(profile_id):
                refresh_profiles_list(preferred_profile_id=profile_id)

        def set_source_language() -> None:
            self._set_project_source_language_code()
            refresh_selected_profile_details()
            refresh_profiles_list(preferred_profile_id=selected_profile_id())

        def open_profiles_context_menu(pos: QPoint) -> None:
            viewport_pos = profiles_list.viewport().mapFrom(profiles_list, pos)
            clicked_item = profiles_list.itemAt(viewport_pos)
            if clicked_item is not None and profiles_list.currentItem() is not clicked_item:
                profiles_list.setCurrentItem(clicked_item)

            menu = QMenu(profiles_list)
            has_folder = self.data_dir is not None
            profile_ids = self._translation_profile_ids_sorted()
            selected_id = selected_profile_id()
            has_selected = clicked_item is not None and bool(selected_id)

            if has_selected:
                switch_action = menu.addAction("Switch To This Profile")
                switch_action.setEnabled(
                    has_folder and selected_id != self.active_translation_profile_id
                )
                switch_action.triggered.connect(switch_selected_profile)

                edit_action = menu.addAction("Edit This Profile Settings...")
                edit_action.setEnabled(has_folder)
                edit_action.triggered.connect(edit_profile_settings)

                rename_action = menu.addAction("Rename This Profile...")
                rename_action.setEnabled(has_folder)
                rename_action.triggered.connect(rename_profile)

                delete_action = menu.addAction("Delete This Profile...")
                delete_action.setEnabled(has_folder and len(profile_ids) > 1)
                delete_action.triggered.connect(delete_profile)

                menu.addSeparator()

            new_action = menu.addAction("Create New Profile...")
            new_action.setEnabled(has_folder)
            new_action.triggered.connect(create_profile)

            source_action = menu.addAction("Set Project Source Language...")
            source_action.setEnabled(has_folder)
            source_action.triggered.connect(set_source_language)

            menu.exec(profiles_list.viewport().mapToGlobal(viewport_pos))

        profiles_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        profiles_list.customContextMenuRequested.connect(open_profiles_context_menu)
        profiles_list.itemSelectionChanged.connect(refresh_selected_profile_details)
        profiles_list.itemDoubleClicked.connect(
            lambda _item: switch_selected_profile()
        )

        close_row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
        close_row.rejected.connect(dialog.reject)
        close_row.accepted.connect(dialog.accept)
        layout.addWidget(close_row)

        refresh_profiles_list(preferred_profile_id=self.active_translation_profile_id)
        dialog.exec()

    def _reset_session_for_profile_switch(self, session: FileSession) -> None:
        reset_segments: list[DialogueSegment] = []
        for segment in session.segments:
            if segment.translation_only:
                continue
            segment.translation_lines = [""]
            segment.original_translation_lines = [""]
            segment.translation_speaker = ""
            segment.original_translation_speaker = ""
            segment.disable_line1_speaker_inference = False
            segment.original_disable_line1_speaker_inference = False
            segment.force_line1_speaker_inference = False
            segment.original_force_line1_speaker_inference = False
            reset_segments.append(segment)
        session.segments = reset_segments

    def _switch_translation_profile(
        self,
        profile_id: str,
        *,
        prompt_unsaved: bool = True,
    ) -> bool:
        normalized_profile_id = self._normalize_translation_profile_id(profile_id)
        if normalized_profile_id == self.active_translation_profile_id:
            self._rebuild_translation_profile_menu()
            return True
        if prompt_unsaved and (not self._prompt_unsaved_if_any()):
            self._rebuild_translation_profile_menu()
            return False

        self.active_translation_profile_id = normalized_profile_id
        self.translation_state["active_profile_id"] = normalized_profile_id
        profile_state = self._active_profile_state()
        counter_raw = profile_state.get("uid_counter", 0)
        self.translation_uid_counter = counter_raw if isinstance(counter_raw, int) else 0
        if self.translation_uid_counter < 0:
            self.translation_uid_counter = 0
        speaker_map_raw = profile_state.get("speaker_map")
        self.speaker_translation_map = (
            dict(speaker_map_raw) if isinstance(speaker_map_raw, dict) else {}
        )

        for path, session in self.sessions.items():
            self._reset_session_for_profile_switch(session)
            self._apply_translation_state_to_session(session)
            self._clear_structural_history_for_path(path)
            self._invalidate_cached_block_view_for_path(path)
            self._refresh_dirty_state(session)
            if self.index_db is not None:
                try:
                    self.index_db.update_file_index(
                        self._relative_path(path),
                        path.stat().st_mtime,
                        session.segments,
                    )
                except Exception:
                    logger.exception(
                        "Failed to update index DB while switching profile for '%s'.",
                        path,
                    )

        self.reference_summary_cache_by_path.clear()
        self._invalidate_audit_caches()
        self._refresh_all_file_item_text()
        if self.current_path is not None:
            self._rerender_current_file()
        else:
            self._refresh_translator_detail_panel()

        self._save_translation_state()
        self._rebuild_translation_profile_menu()
        self.statusBar().showMessage(
            f"Switched translation profile to '{self._translation_profile_name(normalized_profile_id)}'."
        )
        return True

    def _prompt_new_translation_profile_seed_mode(self) -> Optional[str]:
        prompt = QMessageBox(self)
        prompt.setWindowTitle("New translation profile")
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setText("How should the new profile be initialized?")
        duplicate_btn = prompt.addButton(
            "Duplicate Active",
            QMessageBox.ButtonRole.AcceptRole,
        )
        empty_btn = prompt.addButton(
            "Empty",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel_btn = prompt.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        prompt.exec()
        clicked = prompt.clickedButton()
        if clicked is duplicate_btn:
            return "duplicate"
        if clicked is empty_btn:
            return "empty"
        if clicked is cancel_btn:
            return None
        return None

    def _create_translation_profile(self) -> None:
        if self.data_dir is None:
            QMessageBox.warning(
                self,
                "No folder selected",
                "Load a data folder before creating translation profiles.",
            )
            return
        if not self._prompt_unsaved_if_any():
            return

        name_raw, accepted = QInputDialog.getText(
            self,
            "New Translation Profile",
            "Profile name:",
        )
        if not accepted:
            return
        profile_name = name_raw.strip()
        if not profile_name:
            QMessageBox.warning(
                self,
                "Invalid profile name",
                "Profile name cannot be empty.",
            )
            return

        seed_mode = self._prompt_new_translation_profile_seed_mode()
        if seed_mode is None:
            return

        profile_id = self._generate_translation_profile_id(profile_name)
        profiles_raw = self.translation_state.get("profiles")
        profiles = profiles_raw if isinstance(profiles_raw, dict) else {}
        self.translation_state["profiles"] = profiles

        if seed_mode == "duplicate":
            source_profile_id = self.active_translation_profile_id
            source_profile_state = self._ensure_translation_profile(source_profile_id)
            copied_state = copy.deepcopy(source_profile_state)
            copied_state["name"] = profile_name
            profiles[profile_id] = copied_state
            if self.version_db is not None:
                try:
                    self.version_db.copy_translation_profile(
                        source_profile_id,
                        profile_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to duplicate translated snapshots from profile '%s' to '%s'.",
                        source_profile_id,
                        profile_id,
                    )
        else:
            source_profile_target_language_code = self._translation_profile_target_language_code(
                self.active_translation_profile_id
            )
            source_profile_prompt_template = self._translation_profile_prompt_template(
                self.active_translation_profile_id
            )
            profiles[profile_id] = {
                "name": profile_name,
                "uid_counter": 0,
                "target_language_code": source_profile_target_language_code,
                "prompt_template": source_profile_prompt_template,
                "speaker_map": {},
                "files": {},
            }
            if self.version_db is not None:
                for path, session in self.sessions.items():
                    rel_path = self._relative_path(path)
                    baseline_data = self._build_source_data_for_session(session)
                    working_payload = self.version_db.get_snapshot_payload(
                        rel_path,
                        "working",
                    )
                    if working_payload:
                        try:
                            baseline_data = json.loads(working_payload)
                        except Exception:
                            logger.exception(
                                "Failed to parse working snapshot payload while seeding empty profile for '%s'.",
                                rel_path,
                            )
                    try:
                        self.version_db.save_translated_snapshot(
                            rel_path,
                            baseline_data,
                            profile_id=profile_id,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to seed translated snapshot for '%s' in profile '%s'.",
                            rel_path,
                            profile_id,
                        )

        self._refresh_translation_profiles_meta()
        self._switch_translation_profile(profile_id, prompt_unsaved=False)

    def _edit_translation_profile_settings(self, profile_id: str) -> bool:
        if self.data_dir is None:
            QMessageBox.warning(
                self,
                "No folder selected",
                "Load a data folder before editing translation profile settings.",
            )
            return False
        normalized_profile_id = self._normalize_translation_profile_id(profile_id)
        profile_ids = self._translation_profile_ids_sorted()
        if normalized_profile_id not in profile_ids:
            QMessageBox.warning(
                self,
                "Profile not found",
                f"Profile '{normalized_profile_id}' was not found.",
            )
            return False
        profile_name = self._translation_profile_name(normalized_profile_id)
        current_target_language_code = self._translation_profile_target_language_code(
            normalized_profile_id
        )
        current_prompt_template = self._translation_profile_prompt_template(
            normalized_profile_id
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Profile Settings: {profile_name} ({normalized_profile_id})"
        )
        dialog.resize(760, 560)
        root = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        target_language_code_edit = QLineEdit(current_target_language_code)
        target_language_code_edit.setPlaceholderText("en, fr, es-419, ...")
        form.addRow("Target language code", target_language_code_edit)

        prompt_template_edit = QTextEdit()
        prompt_template_edit.setAcceptRichText(False)
        prompt_template_edit.setPlainText(current_prompt_template)
        form.addRow("Prompt template", prompt_template_edit)
        root.addLayout(form, 1)

        hint_label = QLabel(
            (
                "Available placeholders: {source_language_code}, {target_language_code}, "
                "{source_field}, {target_field}, {payload_json}."
            )
        )
        hint_label.setWordWrap(True)
        root.addWidget(hint_label)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        reset_prompt_btn = button_box.addButton(
            "Reset Default Prompt",
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        reset_prompt_btn.clicked.connect(
            lambda: prompt_template_edit.setPlainText(
                self._default_translation_prompt_template()
            )
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        root.addWidget(button_box)

        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return False

        target_language_code = target_language_code_edit.text().strip()
        if not target_language_code:
            QMessageBox.warning(
                self,
                "Invalid language code",
                "Target language code cannot be empty.",
            )
            return False
        prompt_template = prompt_template_edit.toPlainText().strip()
        self._set_translation_profile_prompt_settings(
            target_language_code=target_language_code,
            prompt_template=prompt_template,
            profile_id=normalized_profile_id,
        )
        self._save_translation_state()
        self._rebuild_translation_profile_menu()
        self.statusBar().showMessage(
            (
                f"Updated profile settings for '{profile_name}' "
                f"({normalized_profile_id}) -> target {self._translation_profile_target_language_code(normalized_profile_id)}."
            )
        )
        return True

    def _edit_active_translation_profile_settings(self) -> None:
        self._edit_translation_profile_settings(self.active_translation_profile_id)

    def _set_project_source_language_code(self) -> None:
        if self.data_dir is None:
            QMessageBox.warning(
                self,
                "No folder selected",
                "Load a data folder before editing project source language.",
            )
            return
        current_source_language_code = self._translation_project_source_language_code()
        source_language_code_raw, accepted = QInputDialog.getText(
            self,
            "Project Source Language",
            "Project source language code:",
            QLineEdit.EchoMode.Normal,
            current_source_language_code,
        )
        if not accepted:
            return
        source_language_code = source_language_code_raw.strip()
        if not source_language_code:
            QMessageBox.warning(
                self,
                "Invalid language code",
                "Source language code cannot be empty.",
            )
            return
        self._set_translation_project_source_language_code(source_language_code)
        self._save_translation_state()
        self.statusBar().showMessage(
            (
                "Set project source language to "
                f"'{self._translation_project_source_language_code()}'."
            )
        )

    def _rename_translation_profile(self, profile_id: str) -> bool:
        if self.data_dir is None:
            QMessageBox.warning(
                self,
                "No folder selected",
                "Load a data folder before renaming translation profiles.",
            )
            return False
        normalized_profile_id = self._normalize_translation_profile_id(profile_id)
        profile_ids = self._translation_profile_ids_sorted()
        if normalized_profile_id not in profile_ids:
            QMessageBox.warning(
                self,
                "Profile not found",
                f"Profile '{normalized_profile_id}' was not found.",
            )
            return False
        profile_state = self._ensure_translation_profile(normalized_profile_id)
        current_name_raw = profile_state.get("name")
        current_name = (
            current_name_raw.strip()
            if isinstance(current_name_raw, str) and current_name_raw.strip()
            else self._translation_profile_name(normalized_profile_id)
        )
        new_name_raw, accepted = QInputDialog.getText(
            self,
            "Rename Translation Profile",
            "Profile name:",
            QLineEdit.EchoMode.Normal,
            current_name,
        )
        if not accepted:
            return False
        new_name = new_name_raw.strip()
        if not new_name:
            QMessageBox.warning(
                self,
                "Invalid profile name",
                "Profile name cannot be empty.",
            )
            return False
        if new_name == current_name:
            return False
        profile_state["name"] = new_name
        self._refresh_translation_profiles_meta()
        self._save_translation_state()
        self._rebuild_translation_profile_menu()
        self.statusBar().showMessage(
            f"Renamed translation profile to '{new_name}'."
        )
        return True

    def _rename_active_translation_profile(self) -> None:
        self._rename_translation_profile(self.active_translation_profile_id)

    def _delete_translation_profile(
        self,
        profile_id: str,
        *,
        prompt_unsaved: bool = True,
    ) -> bool:
        if self.data_dir is None:
            QMessageBox.warning(
                self,
                "No folder selected",
                "Load a data folder before deleting translation profiles.",
            )
            return False
        normalized_profile_id = self._normalize_translation_profile_id(profile_id)
        profile_ids = self._translation_profile_ids_sorted()
        if len(profile_ids) <= 1:
            QMessageBox.warning(
                self,
                "Cannot delete profile",
                "At least one translation profile must remain.",
            )
            return False
        if normalized_profile_id not in profile_ids:
            QMessageBox.warning(
                self,
                "Delete failed",
                f"Profile '{normalized_profile_id}' was not found.",
            )
            return False
        if prompt_unsaved and (not self._prompt_unsaved_if_any()):
            return False

        is_active_profile = normalized_profile_id == self.active_translation_profile_id
        profile_name = self._translation_profile_name(normalized_profile_id)
        profile_scope = "active profile" if is_active_profile else "profile"
        confirm = QMessageBox.question(
            self,
            "Delete Translation Profile",
            (
                f"Delete {profile_scope} '{profile_name}' ({normalized_profile_id})?\n\n"
                "This removes its translation state and translated snapshots."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return False

        profiles_raw = self.translation_state.get("profiles")
        profiles = profiles_raw if isinstance(profiles_raw, dict) else {}
        profiles.pop(normalized_profile_id, None)
        remaining_ids = sorted(
            [pid for pid in profiles.keys() if isinstance(pid, str) and pid.strip()],
            key=natural_sort_key,
        )
        if not remaining_ids:
            QMessageBox.warning(
                self,
                "Delete failed",
                "No fallback profile is available.",
            )
            return False
        next_active_profile_id = self.active_translation_profile_id
        if next_active_profile_id not in remaining_ids:
            next_active_profile_id = remaining_ids[0]

        if self.version_db is not None:
            try:
                self.version_db.delete_translation_profile(normalized_profile_id)
            except Exception:
                logger.exception(
                    "Failed to delete translated snapshots for profile '%s'.",
                    normalized_profile_id,
                )

        self.translation_state["profiles"] = profiles
        self.translation_state["active_profile_id"] = next_active_profile_id
        self._refresh_translation_profiles_meta()
        if is_active_profile:
            self._switch_translation_profile(next_active_profile_id, prompt_unsaved=False)
        else:
            self._save_translation_state()
            self._rebuild_translation_profile_menu()
            self.statusBar().showMessage(
                f"Deleted translation profile '{profile_name}'."
            )
        return True

    def _delete_active_translation_profile(self) -> None:
        self._delete_translation_profile(self.active_translation_profile_id)

    def _prompt_translation_profile_for_apply(
        self,
        *,
        default_profile_id: Optional[str] = None,
    ) -> Optional[str]:
        profile_ids = self._translation_profile_ids_sorted()
        if not profile_ids:
            return DEFAULT_TRANSLATION_PROFILE_ID
        if len(profile_ids) == 1:
            return profile_ids[0]
        effective_default = (
            default_profile_id
            if isinstance(default_profile_id, str) and default_profile_id in profile_ids
            else self.active_translation_profile_id
        )
        if effective_default not in profile_ids:
            effective_default = profile_ids[0]

        labels = [self._translation_profile_choice_label(pid) for pid in profile_ids]
        selected_index = profile_ids.index(effective_default)
        label_to_id = dict(zip(labels, profile_ids))
        selected_label, accepted = QInputDialog.getItem(
            self,
            "Select Translation Profile",
            "Apply translated snapshots from profile:",
            labels,
            selected_index,
            False,
        )
        if not accepted:
            return None
        return label_to_id.get(selected_label, effective_default)

    def _set_editor_mode_by_data(self, mode_data: str) -> None:
        idx = self.editor_mode_combo.findData(mode_data)
        if idx < 0:
            return
        if idx != self.editor_mode_combo.currentIndex():
            self.editor_mode_combo.setCurrentIndex(idx)

    def _set_plain_edit_mode_from_menu(self, checked: bool) -> None:
        if checked:
            self._set_editor_mode_by_data("plain")

    def _set_translator_edit_mode_from_menu(self, checked: bool) -> None:
        if checked:
            self._set_editor_mode_by_data("translator")

    def _sync_settings_menu_from_controls(self, *_args: Any) -> None:
        plain_mode_action = self._settings_plain_mode_action
        translator_mode_action = self._settings_translator_mode_action
        if plain_mode_action is None or translator_mode_action is None:
            return

        mode_value = str(self.editor_mode_combo.currentData())
        plain_mode_action.blockSignals(True)
        translator_mode_action.blockSignals(True)
        try:
            plain_mode_action.setChecked(mode_value == "plain")
            translator_mode_action.setChecked(mode_value == "translator")
        finally:
            plain_mode_action.blockSignals(False)
            translator_mode_action.blockSignals(False)

    def _sync_settings_limits_menu_labels(self, *_args: Any) -> None:
        thin_action = self._settings_thin_width_action
        if thin_action is not None:
            thin_action.setText(
                f"Thin Width: {int(self.thin_width_spin.value())}..."
            )
        wide_action = self._settings_wide_width_action
        if wide_action is not None:
            wide_action.setText(
                f"Wide Width: {int(self.wide_width_spin.value())}..."
            )
        max_lines_action = self._settings_max_lines_action
        if max_lines_action is not None:
            max_lines_action.setText(
                f"Max Lines: {int(self.max_lines_spin.value())}..."
            )

    def _smart_collapse_min_soft_ratio(self) -> float:
        percent = int(self.smart_collapse_soft_ratio_percent)
        clamped = max(0, min(100, percent))
        return float(clamped) / 100.0

    def _smart_collapse_use_soft_ratio_rule(self) -> bool:
        return bool(self.smart_collapse_soft_ratio_rule_enabled)

    def _sync_smart_collapse_menu_state(self) -> None:
        checkbox_actions: tuple[tuple[Optional[QAction], bool], ...] = (
            (self._settings_smart_collapse_soft_rule_action, bool(self.smart_collapse_soft_ratio_rule_enabled)),
            (self._settings_smart_collapse_allow_comma_action, bool(self.smart_collapse_allow_comma_endings)),
            (self._settings_smart_collapse_allow_colon_triplet_action, bool(self.smart_collapse_allow_colon_triplet_endings)),
            (self._settings_smart_collapse_ellipsis_lowercase_action, bool(self.smart_collapse_ellipsis_lowercase_rule)),
            (self._settings_smart_collapse_no_punctuation_action, bool(self.smart_collapse_collapse_if_no_punctuation)),
        )
        for action, checked in checkbox_actions:
            if action is None or action.isChecked() == checked:
                continue
            action.blockSignals(True)
            try:
                action.setChecked(checked)
            finally:
                action.blockSignals(False)
        ratio_action = self._settings_smart_collapse_soft_ratio_action
        if ratio_action is not None:
            ratio_action.setText(
                f"Length threshold for collapse-if-short: {int(self.smart_collapse_soft_ratio_percent)}%..."
            )

    def _set_smart_collapse_soft_rule_enabled(self, checked: bool) -> None:
        next_value = bool(checked)
        if next_value == self.smart_collapse_soft_ratio_rule_enabled:
            return
        self.smart_collapse_soft_ratio_rule_enabled = next_value
        self._sync_smart_collapse_menu_state()
        self._on_project_setting_changed()
        if self.current_path is not None:
            self._rerender_current_file()

    def _set_smart_collapse_allow_comma_enabled(self, checked: bool) -> None:
        next_value = bool(checked)
        if next_value == self.smart_collapse_allow_comma_endings:
            return
        self.smart_collapse_allow_comma_endings = next_value
        self._sync_smart_collapse_menu_state()
        self._on_project_setting_changed()
        if self.current_path is not None:
            self._rerender_current_file()

    def _set_smart_collapse_allow_colon_triplet_enabled(self, checked: bool) -> None:
        next_value = bool(checked)
        if next_value == self.smart_collapse_allow_colon_triplet_endings:
            return
        self.smart_collapse_allow_colon_triplet_endings = next_value
        self._sync_smart_collapse_menu_state()
        self._on_project_setting_changed()
        if self.current_path is not None:
            self._rerender_current_file()

    def _set_smart_collapse_ellipsis_lowercase_rule_enabled(self, checked: bool) -> None:
        next_value = bool(checked)
        if next_value == self.smart_collapse_ellipsis_lowercase_rule:
            return
        self.smart_collapse_ellipsis_lowercase_rule = next_value
        self._sync_smart_collapse_menu_state()
        self._on_project_setting_changed()
        if self.current_path is not None:
            self._rerender_current_file()

    def _set_smart_collapse_collapse_if_no_punctuation_enabled(self, checked: bool) -> None:
        next_value = bool(checked)
        if next_value == self.smart_collapse_collapse_if_no_punctuation:
            return
        self.smart_collapse_collapse_if_no_punctuation = next_value
        self._sync_smart_collapse_menu_state()
        self._on_project_setting_changed()
        if self.current_path is not None:
            self._rerender_current_file()

    def _set_smart_collapse_soft_ratio_from_menu(self) -> None:
        value, accepted = QInputDialog.getInt(
            self,
            "Smart Collapse Threshold",
            "Collapse if previous line is shorter than this (% of max width):",
            int(self.smart_collapse_soft_ratio_percent),
            0,
            100,
            1,
        )
        if not accepted:
            return
        clamped = max(0, min(100, int(value)))
        if clamped == self.smart_collapse_soft_ratio_percent:
            self._sync_smart_collapse_menu_state()
            return
        self.smart_collapse_soft_ratio_percent = clamped
        self._sync_smart_collapse_menu_state()
        self._on_project_setting_changed()
        if self.current_path is not None:
            self._rerender_current_file()

    def _set_apply_version_by_data(self, version_data: str) -> None:
        self._set_combo_data_if_present(self.apply_version_combo, version_data)

    def _apply_snapshot_version_from_menu(self, version_data: str) -> None:
        self._set_apply_version_by_data(version_data)
        self._apply_selected_snapshot_to_game_files()

    def _set_apply_snapshot_actions_enabled(self, enabled: bool) -> None:
        for action in self._apply_to_game_files_actions:
            action.setEnabled(enabled)

    def _prompt_int_for_spin(
        self,
        spin: QSpinBox,
        title: str,
        label: str,
    ) -> None:
        value, accepted = QInputDialog.getInt(
            self,
            title,
            label,
            int(spin.value()),
            int(spin.minimum()),
            int(spin.maximum()),
            max(1, int(spin.singleStep())),
        )
        if accepted and value != spin.value():
            spin.setValue(value)

    def _set_thin_width_from_menu(self) -> None:
        self._prompt_int_for_spin(
            self.thin_width_spin,
            "Thin Width",
            "Max characters per line (with face):",
        )

    def _set_wide_width_from_menu(self) -> None:
        self._prompt_int_for_spin(
            self.wide_width_spin,
            "Wide Width",
            "Max characters per line (no face):",
        )

    def _set_max_lines_from_menu(self) -> None:
        self._prompt_int_for_spin(
            self.max_lines_spin,
            "Max Lines",
            "Maximum dialogue lines per block:",
        )

    def _normalize_control_codes_in_lines(self, lines: list[str]) -> tuple[list[str], int]:
        if not lines:
            return [], 0
        normalized_lines: list[str] = []
        replacements = 0
        for line in lines:
            normalized_line, count = normalize_control_code_word_case(line)
            normalized_lines.append(normalized_line)
            replacements += count
        return normalized_lines, replacements

    def _count_possible_control_code_normalizations(
        self,
        *,
        include_source_text: bool,
        include_source_speaker: bool,
        include_translation_text: bool,
        include_translation_speaker: bool,
    ) -> tuple[int, int, int, int]:
        source_text = 0
        source_speaker = 0
        translation_text = 0
        translation_speaker = 0
        for session in self.sessions.values():
            for segment in session.segments:
                if include_source_text:
                    _, source_count = self._normalize_control_codes_in_lines(
                        segment.lines
                    )
                    source_text += source_count
                if include_source_speaker:
                    _, source_speaker_count = normalize_control_code_word_case(
                        segment.speaker_name
                    )
                    source_speaker += source_speaker_count
                if include_translation_text:
                    _, tl_count = self._normalize_control_codes_in_lines(
                        segment.translation_lines
                    )
                    translation_text += tl_count
                if include_translation_speaker:
                    _, speaker_count = normalize_control_code_word_case(
                        segment.translation_speaker
                    )
                    translation_speaker += speaker_count
        return source_text, source_speaker, translation_text, translation_speaker

    def _apply_control_code_normalization(
        self,
        *,
        include_source_text: bool,
        include_source_speaker: bool,
        include_translation_text: bool,
        include_translation_speaker: bool,
    ) -> tuple[int, int, int, int, int, int, set[Path]]:
        source_text = 0
        source_speaker = 0
        translation_text = 0
        translation_speaker = 0
        changed_paths: set[Path] = set()
        changed_blocks = 0

        for path, session in self.sessions.items():
            session_changed = False
            for segment in session.segments:
                segment_changed = False

                if include_source_text:
                    normalized_source_lines, source_count = self._normalize_control_codes_in_lines(
                        segment.lines
                    )
                    if source_count > 0 and normalized_source_lines != segment.lines:
                        segment.lines = list(normalized_source_lines)
                        segment.source_lines = list(normalized_source_lines)
                        source_text += source_count
                        segment_changed = True

                if include_source_speaker:
                    old_speaker_key = self._speaker_key_for_segment(segment)
                    normalized_source_speaker, source_speaker_count = (
                        normalize_control_code_word_case(segment.speaker_name)
                    )
                    if (
                        source_speaker_count > 0
                        and normalized_source_speaker != segment.speaker_name
                    ):
                        params = segment.params
                        while len(params) <= 4:
                            params.append("")
                        params[4] = normalized_source_speaker
                        segment.code101["parameters"] = params
                        source_speaker += source_speaker_count
                        segment_changed = True

                        new_speaker_key = self._speaker_key_for_segment(segment)
                        if (
                            old_speaker_key != new_speaker_key
                            and old_speaker_key in self.speaker_translation_map
                        ):
                            mapped = self.speaker_translation_map.pop(old_speaker_key, "")
                            if (
                                mapped
                                and new_speaker_key != NO_SPEAKER_KEY
                                and (
                                new_speaker_key not in self.speaker_translation_map
                                or not self.speaker_translation_map[new_speaker_key].strip()
                                )
                            ):
                                self.speaker_translation_map[new_speaker_key] = mapped

                if include_translation_text:
                    normalized_tl_lines, tl_count = self._normalize_control_codes_in_lines(
                        segment.translation_lines
                    )
                    if tl_count > 0 and normalized_tl_lines != segment.translation_lines:
                        segment.translation_lines = list(normalized_tl_lines)
                        translation_text += tl_count
                        segment_changed = True

                if include_translation_speaker:
                    normalized_tl_speaker, speaker_count = normalize_control_code_word_case(
                        segment.translation_speaker
                    )
                    if (
                        speaker_count > 0
                        and normalized_tl_speaker != segment.translation_speaker
                    ):
                        segment.translation_speaker = normalized_tl_speaker
                        cleaned_speaker = normalized_tl_speaker.strip()
                        if cleaned_speaker:
                            speaker_key = self._speaker_key_for_segment(segment)
                            if speaker_key != NO_SPEAKER_KEY:
                                self.speaker_translation_map[speaker_key] = cleaned_speaker
                        translation_speaker += speaker_count
                        segment_changed = True

                if segment_changed:
                    changed_blocks += 1
                    session_changed = True

            if session_changed:
                changed_paths.add(path)
                self._refresh_dirty_state(session)

        if self.current_path is not None and self.current_path in changed_paths:
            current_session = self.sessions.get(self.current_path)
            if current_session is not None:
                self._render_session(current_session, preserve_scroll=True)

        total = source_text + source_speaker + translation_text + translation_speaker
        return (
            total,
            source_text,
            source_speaker,
            translation_text,
            translation_speaker,
            changed_blocks,
            changed_paths,
        )

    def _persist_sessions_for_paths(self, paths: set[Path]) -> tuple[int, int]:
        if not paths:
            return 0, 0
        saved = 0
        failed = 0
        ordered_paths = sorted(
            paths,
            key=lambda path: natural_sort_key(self._relative_path(path)),
        )
        for path in ordered_paths:
            session = self.sessions.get(path)
            if session is None:
                failed += 1
                continue
            if self._save_session(
                session,
                refresh_current_view=(path == self.current_path),
            ):
                saved += 1
            else:
                failed += 1
        return saved, failed

    def _open_normalize_codes_dialog(self) -> None:
        if not self.sessions:
            QMessageBox.information(
                self,
                "Normalize Codes",
                "Load files first.",
            )
            return

        include_source_text = True
        include_source_speaker = True
        include_translation_text = True
        include_translation_speaker = True
        source_count, source_speaker_count, tl_count, tl_speaker_count = (
            self._count_possible_control_code_normalizations(
                include_source_text=include_source_text,
                include_source_speaker=include_source_speaker,
                include_translation_text=include_translation_text,
                include_translation_speaker=include_translation_speaker,
            )
        )
        total_count = source_count + source_speaker_count + tl_count + tl_speaker_count
        if total_count <= 0:
            QMessageBox.information(
                self,
                "Normalize Codes",
                (
                    "No control-code casing normalizations found.\n\n"
                    "Example normalization: \\c[0] -> \\C[0]"
                ),
            )
            return

        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setWindowTitle("Normalize Codes")
        prompt.setText(
            (
                "Normalize control-code casing across loaded files?\n\n"
                "This makes control-code words uppercase for consistency.\n"
                "Example: \\c[0] -> \\C[0]\n\n"
                "Scope: Source text + source speaker + translation text + translation speaker.\n\n"
                f"Possible normalizations: {total_count}\n"
                f"Source text: {source_count}\n"
                f"Source speaker: {source_speaker_count}\n"
                f"Translation text: {tl_count}\n"
                f"Translation speaker: {tl_speaker_count}\n"
            )
        )
        persist_checkbox = QCheckBox(
            "Persist immediately (save changed files)",
            prompt,
        )
        persist_checkbox.setChecked(True)
        prompt.setCheckBox(persist_checkbox)
        prompt.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        prompt.setDefaultButton(QMessageBox.StandardButton.Yes)
        if prompt.exec() != int(QMessageBox.StandardButton.Yes):
            return
        persist_immediately = bool(persist_checkbox.isChecked())

        (
            applied_total,
            applied_source,
            applied_source_speaker,
            applied_tl,
            applied_tl_speaker,
            changed_blocks,
            changed_paths,
        ) = self._apply_control_code_normalization(
            include_source_text=include_source_text,
            include_source_speaker=include_source_speaker,
            include_translation_text=include_translation_text,
            include_translation_speaker=include_translation_speaker,
        )
        if applied_total <= 0:
            self.statusBar().showMessage("Normalize Codes: no changes applied.")
            return

        block_label = "block" if changed_blocks == 1 else "blocks"
        persist_suffix = ""
        if persist_immediately:
            saved_files, failed_files = self._persist_sessions_for_paths(changed_paths)
            saved_label = "file" if saved_files == 1 else "files"
            if failed_files > 0:
                failed_label = "file" if failed_files == 1 else "files"
                persist_suffix = (
                    f" Persisted {saved_files} {saved_label}; "
                    f"{failed_files} {failed_label} failed."
                )
            else:
                persist_suffix = f" Persisted {saved_files} {saved_label}."
        self.statusBar().showMessage(
            (
                f"Normalized {applied_total} control-code occurrences "
                f"(source text {applied_source}, source speaker {applied_source_speaker}, "
                f"TL text {applied_tl}, TL speaker {applied_tl_speaker}) "
                f"across {changed_blocks} {block_label}.{persist_suffix}"
            )
        )

    def _trim_extra_ellipses_in_lines(self, lines: list[str]) -> tuple[list[str], int]:
        if not lines:
            return [], 0
        trimmed_lines: list[str] = []
        replacements = 0
        for line in lines:
            trimmed_line, count = trim_extra_ellipsis_runs(line)
            trimmed_lines.append(trimmed_line)
            replacements += count
        return trimmed_lines, replacements

    def _count_possible_extra_ellipsis_trims(self) -> int:
        total = 0
        for session in self.sessions.values():
            for segment in session.segments:
                tl_lines = self._normalize_translation_lines(segment.translation_lines)
                _, count = self._trim_extra_ellipses_in_lines(tl_lines)
                total += count
        return total

    def _apply_extra_ellipsis_trim(self) -> tuple[int, int, set[Path]]:
        total_replacements = 0
        changed_blocks = 0
        changed_paths: set[Path] = set()

        for path, session in self.sessions.items():
            session_changed = False
            for segment in session.segments:
                tl_lines = self._normalize_translation_lines(segment.translation_lines)
                trimmed_lines, replacements = self._trim_extra_ellipses_in_lines(
                    tl_lines
                )
                if replacements <= 0 or trimmed_lines == tl_lines:
                    continue
                segment.translation_lines = list(trimmed_lines)
                total_replacements += replacements
                changed_blocks += 1
                session_changed = True

            if session_changed:
                changed_paths.add(path)
                self._refresh_dirty_state(session)

        if self.current_path is not None and self.current_path in changed_paths:
            current_session = self.sessions.get(self.current_path)
            if current_session is not None:
                self._render_session(current_session, preserve_scroll=True)

        return total_replacements, changed_blocks, changed_paths

    def _open_trim_extra_ellipses_dialog(self) -> None:
        if not self.sessions:
            QMessageBox.information(
                self,
                "Trim Extra Ellipses",
                "Load files first.",
            )
            return

        possible_replacements = self._count_possible_extra_ellipsis_trims()
        if possible_replacements <= 0:
            QMessageBox.information(
                self,
                "Trim Extra Ellipses",
                (
                    "No extra ellipsis runs found in translation text.\n\n"
                    "This tool only trims runs of 4+ periods to '...'.\n"
                    "Pause-only dot lines like '.........' are preserved."
                ),
            )
            return

        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setWindowTitle("Trim Extra Ellipses")
        prompt.setText(
            (
                "Trim extra ellipsis runs in translation text across loaded files?\n\n"
                "Rule: any run of 4+ periods becomes '...'.\n"
                "Pause-only dot lines (e.g. '.........') are left unchanged.\n\n"
                f"Possible trims: {possible_replacements}"
            )
        )
        persist_checkbox = QCheckBox(
            "Persist immediately (save changed files)",
            prompt,
        )
        persist_checkbox.setChecked(True)
        prompt.setCheckBox(persist_checkbox)
        prompt.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        prompt.setDefaultButton(QMessageBox.StandardButton.Yes)
        if prompt.exec() != int(QMessageBox.StandardButton.Yes):
            return
        persist_immediately = bool(persist_checkbox.isChecked())

        applied_total, changed_blocks, changed_paths = self._apply_extra_ellipsis_trim()
        if applied_total <= 0:
            self.statusBar().showMessage("Trim Extra Ellipses: no changes applied.")
            return

        persist_suffix = ""
        if persist_immediately:
            saved_files, failed_files = self._persist_sessions_for_paths(changed_paths)
            saved_label = "file" if saved_files == 1 else "files"
            if failed_files > 0:
                failed_label = "file" if failed_files == 1 else "files"
                persist_suffix = (
                    f" Persisted {saved_files} {saved_label}; "
                    f"{failed_files} {failed_label} failed."
                )
            else:
                persist_suffix = f" Persisted {saved_files} {saved_label}."

        block_label = "block" if changed_blocks == 1 else "blocks"
        self.statusBar().showMessage(
            (
                f"Trimmed {applied_total} extra ellipsis runs across "
                f"{changed_blocks} {block_label}.{persist_suffix}"
            )
        )

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
        self._apply_middle_autoscroll_indicator_style(indicator)
        indicator.hide()
        self._middle_autoscroll_indicator = indicator
        return indicator

    def _apply_middle_autoscroll_indicator_style(self, indicator: QLabel) -> None:
        if is_dark_palette():
            indicator.setStyleSheet(
                "QLabel {"
                "background: rgba(15, 23, 42, 210);"
                "color: #f8fafc;"
                "border: 2px solid #93c5fd;"
                "border-radius: 17px;"
                "}"
            )
            return
        indicator.setStyleSheet(
            "QLabel {"
            "background: rgba(255, 255, 255, 235);"
            "color: #0f172a;"
            "border: 2px solid #2563eb;"
            "border-radius: 17px;"
            "}"
        )

    def _schedule_runtime_theme_refresh(self) -> None:
        self._theme_refresh_timer.start()

    def _apply_runtime_theme_refresh(self) -> None:
        dark_theme = is_dark_palette()
        if dark_theme == self._current_palette_dark:
            return
        self._current_palette_dark = dark_theme

        self._invalidate_speaker_auto_color_cache()

        if self.translator_source_highlighter is not None:
            self.translator_source_highlighter.set_dark_theme(dark_theme)
            self.translator_source_highlighter.rehighlight()
        if self.audit_consistency_source_highlighter is not None:
            self.audit_consistency_source_highlighter.set_dark_theme(dark_theme)
            self.audit_consistency_source_highlighter.rehighlight()
        if self.audit_consistency_target_highlighter is not None:
            self.audit_consistency_target_highlighter.set_dark_theme(dark_theme)
            self.audit_consistency_target_highlighter.rehighlight()
        if self._middle_autoscroll_indicator is not None:
            self._apply_middle_autoscroll_indicator_style(
                self._middle_autoscroll_indicator
            )

        for widget in self.block_widgets.values():
            refresh_theme = getattr(widget, "refresh_theme_palette", None)
            if callable(refresh_theme):
                refresh_theme()

        self._refresh_translator_detail_panel()
        self._refresh_block_control_mismatch_highlighting()

        if self.audit_window is not None and self.audit_window.isVisible():
            refresh_search = getattr(self, "_run_audit_search", None)
            if callable(refresh_search):
                refresh_search()
            self._refresh_audit_search_replace_preview()
            self._refresh_audit_sanitize_panel()
            self._refresh_audit_control_mismatch_panel()
            self._refresh_audit_consistency_panel()
            self._refresh_audit_term_panel()
            self._refresh_audit_term_suggestions_panel()

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
        event_type = event.type()
        theme_change_type = getattr(QEvent.Type, "ThemeChange", None)
        if (
            event_type in (
                QEvent.Type.ApplicationPaletteChange,
                QEvent.Type.PaletteChange,
                QEvent.Type.StyleChange,
            )
            or (theme_change_type is not None and event_type == theme_change_type)
        ):
            app_instance = QApplication.instance()
            if watched is app_instance or watched is self:
                self._schedule_runtime_theme_refresh()

        if event_type == QEvent.Type.MouseButtonPress:
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
        elif event_type == QEvent.Type.MouseButtonRelease:
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
        elif self._middle_autoscroll_active and event_type == QEvent.Type.Wheel:
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
        actor_mode = self._is_name_index_session(session)
        translator_mode = self._is_translator_mode()
        display_segments = self._display_segments_for_session(
            session,
            translator_mode=translator_mode,
            actor_mode=actor_mode,
        )
        block_numbers = self._display_block_numbers(
            display_segments,
            actor_mode=actor_mode,
        )
        for segment in display_segments:
            if segment.uid != uid:
                continue
            number = block_numbers.get(uid)
            if number is None or number <= 0:
                return None
            return number
        return None

    def _refresh_block_control_mismatch_highlighting(self) -> None:
        enabled = bool(self.problem_control_mismatch_check.isChecked())
        for widget in self.block_widgets.values():
            setter = getattr(widget, "set_control_mismatch_highlighting_enabled", None)
            if callable(setter):
                setter(enabled)

    def _apply_translator_source_mismatch_highlighting(
        self,
        segment: Optional[DialogueSegment],
        *,
        actor_mode: bool,
    ) -> None:
        if segment is None or actor_mode:
            self.translator_source_view.setExtraSelections([])
            return
        if not self.problem_control_mismatch_check.isChecked():
            self.translator_source_view.setExtraSelections([])
            return
        source_lines = self._segment_source_lines_for_translation(segment)
        tl_lines = self._segment_translation_lines_for_translation(segment)
        source_text = "\n".join(source_lines)
        tl_text = "\n".join(tl_lines)
        if not tl_text.strip():
            self.translator_source_view.setExtraSelections([])
            return
        selections = build_control_mismatch_selections(
            self.translator_source_view,
            source_text=source_text,
            translation_text=tl_text,
            highlight_side="source",
            dark_theme=is_dark_palette(),
        )
        self.translator_source_view.setExtraSelections(selections)

    def _refresh_translator_detail_panel(self) -> None:
        translator_mode = self._is_translator_mode()
        self.translator_detail_panel.setVisible(translator_mode)
        if not translator_mode:
            self.translator_source_view.setExtraSelections([])
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
        structural_dialogue_selected = bool(
            segment is not None and segment.is_structural_dialogue
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
        self.translator_speaker_jp_row.setVisible(
            (not actor_mode) and structural_dialogue_selected
        )
        self.translator_speaker_en_row.setVisible(
            (not actor_mode) and structural_dialogue_selected
        )
        self.translator_reference_exact_label.setVisible(not actor_mode)
        self.translator_review_exact_matches_btn.setVisible(not actor_mode)
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
            self._set_translator_speaker_display_text(
                self.translator_speaker_jp_edit,
                "",
            )
            self._set_translator_speaker_display_text(
                self.translator_speaker_en_edit,
                "",
            )
            self.translator_source_view.setPlainText("")
            self.translator_source_highlighter.set_initial_active_color_code(0)
            self.translator_source_highlighter.rehighlight()
            self.translator_reference_exact_label.setText("")
            self.translator_reference_similar_label.setText("")
            self.translator_review_exact_matches_btn.setEnabled(False)
            self.translator_source_view.setExtraSelections([])
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
            if segment.segment_kind == "map_display_name":
                self.translator_detail_title.setText("Selected Map Display Name")
                self.translator_block_label.setText("Map displayName")
            elif block_number is None:
                self.translator_detail_title.setText("Selected Dialogue")
                self.translator_block_label.setText("Block: -")
            else:
                self.translator_detail_title.setText(
                    f"Selected Dialogue: Block {block_number}")
                self.translator_block_label.setText(f"Block: {block_number}")
            self.translator_context_label.setText(
                f"Context: {segment.context}")

            if segment.is_structural_dialogue:
                speaker_jp, speaker_en = self._translator_panel_speaker_values(
                    segment
                )
                self._set_translator_speaker_display_text(
                    self.translator_speaker_jp_edit,
                    speaker_jp,
                )
                self._set_translator_speaker_display_text(
                    self.translator_speaker_en_edit,
                    speaker_en,
                )
            else:
                self._set_translator_speaker_display_text(
                    self.translator_speaker_jp_edit,
                    "",
                )
                self._set_translator_speaker_display_text(
                    self.translator_speaker_en_edit,
                    "",
                )

        self.translator_source_highlighter.set_initial_active_color_code(
            self._translator_source_initial_active_color_code(segment)
        )
        self.translator_source_view.setPlainText(
            "\n".join(self._segment_source_lines_for_translation(segment))
        )
        self.translator_source_highlighter.rehighlight()
        if actor_mode:
            self.translator_reference_exact_label.setText("")
            self.translator_reference_similar_label.setText("")
            self.translator_review_exact_matches_btn.setEnabled(False)
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
            self.translator_review_exact_matches_btn.setEnabled(
                not exact.startswith("Exact JP matches: none.")
            )
        self._apply_translator_source_mismatch_highlighting(
            segment,
            actor_mode=actor_mode,
        )

    def _translator_panel_speaker_values(
        self,
        segment: DialogueSegment,
    ) -> tuple[str, str]:
        if not segment.is_structural_dialogue:
            return "", ""

        speaker_key = self._speaker_key_for_segment(segment)
        explicit_speaker_raw = self._resolve_name_tokens_in_text(
            segment.speaker_name,
            prefer_translated=False,
        )
        explicit_speaker_key = self._normalize_speaker_key(explicit_speaker_raw)
        if explicit_speaker_key != NO_SPEAKER_KEY:
            speaker_jp = explicit_speaker_key
        elif speaker_key != NO_SPEAKER_KEY:
            speaker_jp = speaker_key
        else:
            speaker_jp = NO_SPEAKER_KEY

        if speaker_key == NO_SPEAKER_KEY:
            return speaker_jp, NO_SPEAKER_KEY

        speaker_en = self._speaker_translation_for_key(speaker_key)
        if not speaker_en:
            speaker_en = segment.translation_speaker.strip()
        return speaker_jp, speaker_en

    def _set_translator_speaker_display_text(
        self,
        target: QLabel,
        text: str,
    ) -> None:
        cleaned = text.strip()
        if not cleaned:
            target.setText("")
            target.setToolTip("")
            return
        target.setText(self._render_text_with_visible_color_codes_html(cleaned))
        target.setToolTip(cleaned)

    def _active_color_code_at_end_of_lines(self, lines: list[str]) -> int:
        active = 0
        text = "\n".join(lines)
        for match in _INLINE_COLOR_CODE_RE.finditer(text):
            try:
                active = int(match.group(1))
            except Exception:
                active = 0
        return max(0, active)

    def _translator_source_initial_active_color_code(
        self,
        segment: DialogueSegment,
    ) -> int:
        if not self._segment_has_inferred_line1_speaker(segment):
            return 0
        source_lines = self._segment_source_lines_for_display(segment)
        if len(source_lines) <= 1:
            return 0
        first_line = source_lines[0] if isinstance(source_lines[0], str) else ""
        if not first_line:
            return 0
        return self._active_color_code_at_end_of_lines([first_line])

    def _segment_for_exact_match_row(self, row: dict[str, Any]) -> Optional[DialogueSegment]:
        path = row.get("path")
        index_raw = row.get("segment_index")
        if not isinstance(path, Path):
            return None
        if not isinstance(index_raw, int):
            return None
        session = self.sessions.get(path)
        if session is None:
            return None
        if index_raw < 0 or index_raw >= len(session.segments):
            return None
        return session.segments[index_raw]

    def _snapshot_for_segment_index(
        self,
        session: FileSession,
        segment_index: int,
    ) -> dict[str, str]:
        def text_for_index(index: int) -> tuple[str, str]:
            if index < 0 or index >= len(session.segments):
                return "", ""
            segment = session.segments[index]
            source_text = "\n".join(self._segment_source_lines_for_translation(segment)).strip()
            tl_text = "\n".join(self._segment_translation_lines_for_translation(segment)).strip()
            return source_text, tl_text

        prev_source, prev_tl = text_for_index(segment_index - 1)
        curr_source, curr_tl = text_for_index(segment_index)
        next_source, next_tl = text_for_index(segment_index + 1)
        return {
            "prev_source": prev_source,
            "current_source": curr_source,
            "next_source": next_source,
            "prev_tl": prev_tl,
            "current_tl": curr_tl,
            "next_tl": next_tl,
        }

    def _exact_match_review_rows_for_segment(
        self,
        session: FileSession,
        segment: DialogueSegment,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        exact_groups: dict[str, list[dict[str, Any]]] = {}
        for row_path, row_session in self.sessions.items():
            for segment_index, row_segment in enumerate(row_session.segments):
                source_text = self._segment_reference_source_text(row_segment).strip()
                if not source_text:
                    continue
                row = {
                    "path": row_path,
                    "uid": row_segment.uid,
                    "file": row_path.name,
                    "block_number": segment_index + 1,
                    "segment_index": segment_index,
                    "source_text": source_text,
                }
                rows.append(row)
                exact_groups.setdefault(source_text, []).append(row)

        own_source = self._segment_reference_source_text(segment).strip()
        if not own_source:
            return []
        exact_pool, _is_cross_file = self._exact_reference_candidates(
            own_source=own_source,
            own_path=session.path,
            own_uid=segment.uid,
            exact_groups=exact_groups,
        )
        current_index = next(
            (idx for idx, item in enumerate(session.segments) if item.uid == segment.uid),
            -1,
        )
        current_snapshot = (
            self._snapshot_for_segment_index(session, current_index)
            if current_index >= 0
            else {}
        )

        review_rows: list[dict[str, Any]] = []
        for row in exact_pool:
            path = row["path"]
            segment_index = row["segment_index"]
            if not isinstance(path, Path) or not isinstance(segment_index, int):
                continue
            row_session = self.sessions.get(path)
            if row_session is None:
                continue
            snapshot = self._snapshot_for_segment_index(row_session, segment_index)
            review_rows.append(
                {
                    **row,
                    **snapshot,
                    "same_neighbors": (
                        current_snapshot.get("prev_source", "").strip()
                        == snapshot.get("prev_source", "").strip()
                        and current_snapshot.get("next_source", "").strip()
                        == snapshot.get("next_source", "").strip()
                    ),
                }
            )

        review_rows.sort(
            key=lambda row: (
                natural_sort_key(str(row.get("file", ""))),
                int(row.get("block_number", 0)),
            )
        )
        return review_rows

    def _apply_translation_lines_between_segments(
        self,
        source_segment: DialogueSegment,
        target_rows: list[dict[str, Any]],
    ) -> int:
        source_visible_lines = self._segment_translation_lines_for_translation(source_segment)
        touched_paths: set[Path] = set()
        changed_count = 0

        for row in target_rows:
            target_segment = self._segment_for_exact_match_row(row)
            if target_segment is None:
                continue
            target_path = row.get("path")
            if not isinstance(target_path, Path):
                continue
            new_lines = self._compose_translation_lines_for_segment(
                target_segment,
                source_visible_lines,
            )
            normalized_existing = self._normalize_translation_lines(target_segment.translation_lines)
            normalized_new = self._normalize_translation_lines(new_lines)
            if normalized_existing == normalized_new:
                continue
            target_segment.translation_lines = list(normalized_new)
            touched_paths.add(target_path)
            changed_count += 1

        for path in touched_paths:
            touched_session = self.sessions.get(path)
            if touched_session is not None:
                self._refresh_dirty_state(touched_session)

        if self.current_path is not None:
            current_session = self.sessions.get(self.current_path)
            if current_session is not None:
                self._render_session(current_session, preserve_scroll=True)
        else:
            self._refresh_translator_detail_panel()
        return changed_count

    def _open_exact_match_review_dialog(self) -> None:
        if not self._is_translator_mode():
            return
        if self.current_path is None:
            return
        current_session = self.sessions.get(self.current_path)
        if current_session is None or self._is_name_index_session(current_session):
            return
        if not self.selected_segment_uid:
            QMessageBox.information(
                self,
                "No block selected",
                "Select a dialogue block first.",
            )
            return
        current_segment = self.current_segment_lookup.get(self.selected_segment_uid)
        if current_segment is None:
            return

        review_rows = self._exact_match_review_rows_for_segment(
            current_session,
            current_segment,
        )
        if not review_rows:
            QMessageBox.information(
                self,
                "No exact matches",
                "No exact JP matches were found for the selected block.",
            )
            return

        current_index = next(
            (idx for idx, item in enumerate(current_session.segments) if item.uid == current_segment.uid),
            -1,
        )
        if current_index < 0:
            return
        current_snapshot = self._snapshot_for_segment_index(current_session, current_index)
        block_number = self._block_number_for_uid(current_segment.uid)
        current_label = (
            f"Current: {current_session.path.name}#{block_number}"
            if block_number is not None
            else f"Current: {current_session.path.name}"
        )
        dialog = ExactMatchReviewDialog(
            self,
            current_block_label=current_label,
            current_snapshot=current_snapshot,
            match_rows=review_rows,
            color_code_resolver=self._color_for_rpgm_code,
        )
        if dialog.exec() != int(QDialog.DialogCode.Accepted):
            return
        action = dialog.selected_action
        selected_row = dialog.selected_match_row

        changed = 0
        if action == "selected_to_current":
            if selected_row is None:
                return
            source_segment = self._segment_for_exact_match_row(selected_row)
            if source_segment is None:
                return
            target_rows = [
                {
                    "path": current_session.path,
                    "segment_index": current_index,
                }
            ]
            changed = self._apply_translation_lines_between_segments(
                source_segment=source_segment,
                target_rows=target_rows,
            )
            self.statusBar().showMessage(
                "Applied selected exact-match translation to current block."
                if changed > 0
                else "Current block already matched selected translation."
            )
            return

        if action == "selected_to_all":
            if selected_row is None:
                return
            source_segment = self._segment_for_exact_match_row(selected_row)
            if source_segment is None:
                return
            changed = self._apply_translation_lines_between_segments(
                source_segment=source_segment,
                target_rows=review_rows,
            )
            target_label = "block" if changed == 1 else "blocks"
            self.statusBar().showMessage(
                f"Applied selected exact-match translation to {changed} listed {target_label}."
            )
            return

        if action == "current_to_selected":
            if selected_row is None:
                return
            changed = self._apply_translation_lines_between_segments(
                source_segment=current_segment,
                target_rows=[selected_row],
            )
            self.statusBar().showMessage(
                "Applied current block translation to selected exact match."
                if changed > 0
                else "Selected exact match already had current translation."
            )
            return

        if action == "current_to_all":
            changed = self._apply_translation_lines_between_segments(
                source_segment=current_segment,
                target_rows=review_rows,
            )
            target_label = "block" if changed == 1 else "blocks"
            self.statusBar().showMessage(
                f"Applied current block translation to {changed} exact-match {target_label}."
            )
            return

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
        if key == NO_SPEAKER_KEY:
            return ""
        value = self.speaker_translation_map.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip()

        resolved_key = self._normalize_speaker_key(
            self._resolve_name_tokens_in_text(
                key,
                prefer_translated=False,
            )
        )
        if resolved_key != key:
            legacy_value = self.speaker_translation_map.get(resolved_key, "")
            if isinstance(legacy_value, str) and legacy_value.strip():
                return legacy_value.strip()

        jp_by_id, en_by_id = self._actor_name_maps()
        for actor_id, jp_name in jp_by_id.items():
            normalized_jp_name = self._normalize_speaker_key(jp_name)
            if normalized_jp_name != key and normalized_jp_name != resolved_key:
                continue
            candidate = en_by_id.get(actor_id, "").strip()
            if candidate:
                return candidate
        return ""

    def _set_speaker_translation_everywhere(self, speaker_key: str, translated_name: str) -> int:
        key = self._normalize_speaker_key(speaker_key)
        if key == NO_SPEAKER_KEY:
            self.statusBar().showMessage("No JP speaker key selected.")
            return 0
        cleaned = translated_name.strip()
        previous = self._speaker_translation_for_key(key)
        changed_blocks = 0
        touched_sessions: list[FileSession] = []

        for session in self.sessions.values():
            if self._is_name_index_session(session):
                continue
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
        normalized_raw = value.strip()
        normalized, _count = normalize_control_code_word_case(normalized_raw)
        normalized = normalized.strip()
        return normalized if normalized else NO_SPEAKER_KEY

    def _inferred_speaker_from_segment_line1(self, segment: DialogueSegment) -> str:
        if not self.infer_speaker_check.isChecked():
            return ""
        if not segment.is_structural_dialogue:
            return ""
        if segment.speaker_name != NO_SPEAKER_KEY:
            return ""
        if bool(getattr(segment, "disable_line1_speaker_inference", False)):
            return ""
        lines = self._segment_source_lines_for_display(segment)
        if not lines:
            return ""
        if len(lines) <= 1:
            return ""
        first_line = lines[0].strip()
        if not first_line:
            return ""
        resolved_first = self._resolve_name_tokens_in_text(
            first_line,
            prefer_translated=False,
        ).strip()
        if bool(getattr(segment, "force_line1_speaker_inference", False)):
            return resolved_first or first_line
        second_line_visible = strip_control_tokens(lines[1]).replace("\u3000", " ").lstrip()
        if second_line_visible.startswith("「"):
            return resolved_first or first_line
        if first_line and looks_like_name_line(first_line):
            return resolved_first or first_line
        if resolved_first and looks_like_name_line(resolved_first):
            return resolved_first
        if self._matches_name_token(first_line):
            return resolved_first or first_line
        return ""

    def _segment_has_inferred_line1_speaker(self, segment: DialogueSegment) -> bool:
        return bool(self._inferred_speaker_from_segment_line1(segment))

    def _segment_source_lines_for_translation(self, segment: DialogueSegment) -> list[str]:
        lines = self._segment_source_lines_for_display(segment)
        if self._segment_has_inferred_line1_speaker(segment):
            if len(lines) > 1:
                return list(lines[1:])
            return [""]
        return list(lines) if lines else [""]

    def _segment_translation_lines_for_translation(self, segment: DialogueSegment) -> list[str]:
        lines = self._normalize_translation_lines(segment.translation_lines)
        if self._segment_has_inferred_line1_speaker(segment):
            if len(lines) > 1:
                return list(lines[1:])
            return [""]
        return list(lines) if lines else [""]

    def _compose_translation_lines_for_segment(
        self,
        segment: DialogueSegment,
        visible_lines: list[str],
    ) -> list[str]:
        normalized_visible = list(visible_lines) if visible_lines else [""]
        if not self._segment_has_inferred_line1_speaker(segment):
            return normalized_visible
        source_lines = self._segment_source_lines_for_display(segment)
        speaker_line = source_lines[0] if source_lines else ""
        return [speaker_line] + normalized_visible

    def _speaker_key_for_segment(self, segment: DialogueSegment) -> str:
        if not segment.is_structural_dialogue:
            return NO_SPEAKER_KEY
        explicit_raw = segment.speaker_name
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
        dialogue_keys: set[str] = set()
        for session in self.sessions.values():
            if self._is_name_index_session(session):
                continue
            for segment in session.segments:
                dialogue_keys.add(self._speaker_key_for_segment(segment))
        keys: set[str] = {NO_SPEAKER_KEY}
        keys.update(dialogue_keys)
        keys.update(
            key for key in self.speaker_custom_colors.keys() if key in dialogue_keys
        )
        keys.update(
            key for key in self.speaker_translation_map.keys() if key in dialogue_keys
        )
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
            if self._is_name_index_session(session):
                continue
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
            if (
                new_name != NO_SPEAKER_KEY
                and new_name not in self.speaker_translation_map
            ):
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

    def _clamp_variable_length_estimate(self, value: int) -> int:
        return max(1, min(_MAX_VARIABLE_LENGTH_ESTIMATE, int(value)))

    def _variable_length_estimate_for_id(self, variable_id: int) -> int:
        safe_id = max(0, int(variable_id))
        override = self.variable_length_overrides.get(safe_id)
        if isinstance(override, int) and override > 0:
            return self._clamp_variable_length_estimate(override)
        return self._clamp_variable_length_estimate(self.default_variable_length_estimate)

    def _variable_length_override_exists(self, variable_id: int) -> bool:
        return max(0, int(variable_id)) in self.variable_length_overrides

    def _default_variable_length_for_manager(self) -> int:
        return self._clamp_variable_length_estimate(self.default_variable_length_estimate)

    def _clamp_name_length_estimate(self, value: int) -> int:
        return max(1, min(_MAX_NAME_LENGTH_ESTIMATE, int(value)))

    def _name_length_estimate_for_actor_id(self, actor_id: int) -> int:
        safe_id = max(0, int(actor_id))
        jp_by_id, en_by_id = self._actor_name_maps()
        use_translated = self._is_translator_mode()
        primary = en_by_id if use_translated else jp_by_id
        fallback = jp_by_id if use_translated else en_by_id
        candidate = primary.get(safe_id, "").strip() or fallback.get(safe_id, "").strip()
        if not candidate:
            return _DEFAULT_NAME_LENGTH_ESTIMATE
        visible_name = strip_control_tokens(candidate).replace("\n", " ").strip()
        if not visible_name:
            return _DEFAULT_NAME_LENGTH_ESTIMATE
        return self._clamp_name_length_estimate(len(visible_name))

    def _sync_variable_length_measurement_settings(self) -> None:
        configure_variable_text_metrics(
            self._clamp_variable_length_estimate(
                self.default_variable_length_estimate
            ),
            self._variable_length_estimate_for_id,
        )
        configure_name_text_metrics(
            _DEFAULT_NAME_LENGTH_ESTIMATE,
            self._name_length_estimate_for_actor_id,
        )

    def _extract_variable_ids_from_text(self, text: str) -> set[int]:
        ids: set[int] = set()
        for match in _VARIABLE_TOKEN_RE.finditer(text or ""):
            try:
                value = int(match.group(1))
            except Exception:
                continue
            if value >= 0:
                ids.add(value)
        return ids

    def _collect_variable_ids_for_manager(self) -> list[int]:
        ids: set[int] = {
            key for key in self.variable_length_overrides.keys() if key >= 0
        }
        system_values = self._system_variables_from_session(translated=False)
        ids.update(variable_id for variable_id in system_values.keys() if variable_id >= 0)
        original_values = self._system_variables_from_original_snapshot()
        ids.update(variable_id for variable_id in original_values.keys() if variable_id >= 0)

        for session in self.sessions.values():
            for segment in session.segments:
                candidate_line_groups = (
                    segment.lines,
                    segment.source_lines,
                    segment.original_lines,
                    segment.translation_lines,
                    segment.original_translation_lines,
                )
                for lines in candidate_line_groups:
                    if not isinstance(lines, list):
                        continue
                    for line in lines:
                        if not isinstance(line, str):
                            continue
                        ids.update(self._extract_variable_ids_from_text(line))
        return sorted(ids)

    def _apply_variable_length_setting_changes(self, status_message: str) -> None:
        self._sync_variable_length_measurement_settings()
        if self.data_dir is not None:
            self._store_current_project_ui_settings()
            self._save_ui_state()
        self._refresh_all_file_item_text()
        if self.current_path is not None:
            self._rerender_current_file()
        self.statusBar().showMessage(status_message)

    def _set_default_variable_length_estimate(self, value: int) -> int:
        clamped = self._clamp_variable_length_estimate(value)
        if clamped == self.default_variable_length_estimate:
            return clamped
        self.default_variable_length_estimate = clamped
        self._apply_variable_length_setting_changes(
            f"Default \\V[n] visible length set to {clamped}."
        )
        return clamped

    def _set_variable_length_override(self, variable_id: int, length: int) -> int:
        safe_id = max(0, int(variable_id))
        clamped = self._clamp_variable_length_estimate(length)
        self.variable_length_overrides[safe_id] = clamped
        self._apply_variable_length_setting_changes(
            f"Set \\V[{safe_id}] visible length to {clamped}."
        )
        return clamped

    def _clear_variable_length_override(self, variable_id: int) -> bool:
        safe_id = max(0, int(variable_id))
        if safe_id not in self.variable_length_overrides:
            return False
        del self.variable_length_overrides[safe_id]
        self._apply_variable_length_setting_changes(
            f"Cleared \\V[{safe_id}] override."
        )
        return True

    def _open_variable_length_manager(self) -> None:
        if not self.sessions:
            QMessageBox.information(
                self,
                "No data loaded",
                "Load a data folder before opening Variable Lengths.",
            )
            return
        dialog = VariableLengthManagerDialog(self)
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
        existing_dialog = self.mass_translate_dialog
        if existing_dialog is not None:
            if existing_dialog.isVisible():
                refresh_scope = getattr(existing_dialog, "_on_scope_or_filters_changed", None)
                if callable(refresh_scope):
                    refresh_scope()
                existing_dialog.raise_()
                existing_dialog.activateWindow()
                return
            self.mass_translate_dialog = None

        dialog = MassTranslateDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(self._on_mass_translate_dialog_destroyed)
        self.mass_translate_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_mass_translate_dialog_destroyed(self, _obj: QObject) -> None:
        self.mass_translate_dialog = None
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

    def _update_window_title(self) -> None:
        if self.data_dir is None:
            self.setWindowTitle(APP_TITLE)
            return
        dirty_suffix = " *" if any(session.dirty for session in self.sessions.values()) else ""
        self.setWindowTitle(f"{APP_TITLE} | {self.data_dir}{dirty_suffix}")

    def _project_state_key(self, folder: Path) -> str:
        try:
            return str(folder.resolve())
        except Exception:
            return str(folder)

    def _candidate_js_dirs(self, folder: Path) -> list[Path]:
        candidate_js_dirs: list[Path] = []
        seen: set[Path] = set()
        for base in (folder, folder.parent, folder.parent.parent):
            js_dir = base / "js"
            try:
                resolved = js_dir.resolve()
            except Exception:
                resolved = js_dir
            if resolved in seen:
                continue
            seen.add(resolved)
            if js_dir.exists() and js_dir.is_dir():
                candidate_js_dirs.append(js_dir)
        return candidate_js_dirs

    def _detect_rpg_maker_engine(self, folder: Path) -> str:
        candidate_js_dirs = self._candidate_js_dirs(folder)
        if not candidate_js_dirs:
            return "unknown"

        has_mz_runtime = any(
            (js_dir / name).is_file()
            for js_dir in candidate_js_dirs
            for name in ("rmmz_objects.js", "rmmz_core.js")
        )
        has_mv_runtime = any(
            (js_dir / name).is_file()
            for js_dir in candidate_js_dirs
            for name in ("rpg_objects.js", "rpg_core.js")
        )
        if has_mz_runtime and not has_mv_runtime:
            return "mz"
        if has_mv_runtime and not has_mz_runtime:
            return "mv"
        if has_mz_runtime and has_mv_runtime:
            return "mz"
        return "unknown"

    def _coerce_positive_int(self, value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        parsed: Optional[int] = None
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, float):
            parsed = int(value)
        elif isinstance(value, str):
            stripped = value.strip()
            if stripped and re.fullmatch(r"-?\d+", stripped):
                try:
                    parsed = int(stripped)
                except Exception:
                    parsed = None
        if parsed is None or parsed <= 0:
            return None
        return parsed

    def _read_text_file_best_effort(self, path: Path) -> Optional[str]:
        for encoding in ("utf-8-sig", "utf-8", "cp932"):
            try:
                return path.read_text(encoding=encoding)
            except Exception:
                continue
        return None

    def _system_json_candidates(self, folder: Path) -> list[Path]:
        candidates = [
            folder / "System.json",
            folder / "system.json",
            folder.parent / "data" / "System.json",
            folder.parent / "data" / "system.json",
        ]
        deduped: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            deduped.append(candidate)
        return deduped

    def _font_size_from_system_json(self, folder: Path) -> tuple[Optional[int], str]:
        for path in self._system_json_candidates(folder):
            if not path.is_file():
                continue
            raw_text = self._read_text_file_best_effort(path)
            if raw_text is None:
                continue
            try:
                decoded = json.loads(raw_text)
            except Exception:
                continue
            if not isinstance(decoded, dict):
                continue

            advanced = decoded.get("advanced")
            if isinstance(advanced, dict):
                for key in ("fontSize", "mainFontSize"):
                    parsed = self._coerce_positive_int(advanced.get(key))
                    if parsed is not None:
                        return parsed, f"{path.name} advanced.{key}"

            for key in ("fontSize", "mainFontSize"):
                parsed = self._coerce_positive_int(decoded.get(key))
                if parsed is not None:
                    return parsed, f"{path.name} {key}"
        return None, ""

    def _font_size_from_js_function_body(
        self,
        body: str,
        system_font_size: Optional[int],
    ) -> Optional[int]:
        direct_match = _JS_RETURN_INT_RE.search(body)
        if direct_match is not None:
            parsed = self._coerce_positive_int(direct_match.group(1))
            if parsed is not None:
                return parsed
        if (
            system_font_size is not None
            and _JS_SYSTEM_ADVANCED_FONT_RE.search(body) is not None
        ):
            return system_font_size
        return None

    def _font_size_from_js_source_function(
        self,
        source_text: str,
        function_name: str,
        system_font_size: Optional[int],
    ) -> Optional[int]:
        escaped_name = re.escape(function_name)
        patterns = (
            re.compile(
                rf"{escaped_name}\s*=\s*function\s*\([^)]*\)\s*\{{(?P<body>.*?)\}}",
                re.DOTALL,
            ),
            re.compile(
                rf"\b{escaped_name}\s*\([^)]*\)\s*\{{(?P<body>.*?)\}}",
                re.DOTALL,
            ),
        )
        for pattern in patterns:
            for match in pattern.finditer(source_text):
                body = match.group("body")
                parsed = self._font_size_from_js_function_body(
                    body,
                    system_font_size,
                )
                if parsed is not None:
                    return parsed
        return None

    def _font_size_from_runtime_scripts(
        self,
        folder: Path,
        system_font_size: Optional[int],
    ) -> tuple[Optional[int], str]:
        if self.detected_rpg_engine == "mv":
            checks = [("rpg_windows.js", "standardFontSize")]
        elif self.detected_rpg_engine == "mz":
            checks = [
                ("rmmz_objects.js", "mainFontSize"),
                ("rmmz_windows.js", "mainFontSize"),
            ]
        else:
            checks = [
                ("rpg_windows.js", "standardFontSize"),
                ("rmmz_objects.js", "mainFontSize"),
                ("rmmz_windows.js", "mainFontSize"),
            ]

        for js_dir in self._candidate_js_dirs(folder):
            for filename, function_name in checks:
                script_path = js_dir / filename
                if not script_path.is_file():
                    continue
                source = self._read_text_file_best_effort(script_path)
                if source is None:
                    continue
                parsed = self._font_size_from_js_source_function(
                    source,
                    function_name,
                    system_font_size,
                )
                if parsed is not None:
                    return parsed, f"{filename} {function_name}()"
        return None, ""

    def _infer_project_message_font_size(self, folder: Path) -> tuple[int, str]:
        system_font_size, system_source = self._font_size_from_system_json(folder)
        runtime_font_size, runtime_source = self._font_size_from_runtime_scripts(
            folder,
            system_font_size,
        )
        if runtime_font_size is not None:
            return runtime_font_size, runtime_source
        if system_font_size is not None:
            return system_font_size, system_source
        if self.detected_rpg_engine == "mz":
            return _MZ_DEFAULT_MESSAGE_FONT_SIZE, "MZ default"
        return _MV_DEFAULT_MESSAGE_FONT_SIZE, "MV default"

    def _configure_project_message_text_metrics(self, folder: Path) -> tuple[int, str]:
        inferred_size, source = self._infer_project_message_font_size(folder)
        configured_size = configure_message_text_metrics(inferred_size)
        self.detected_message_font_size = configured_size
        self.detected_message_font_source = source
        return configured_size, source

    def _rpg_engine_label(self, engine: str) -> str:
        if engine == "mv":
            return "MV"
        if engine == "mz":
            return "MZ"
        return "Unknown"

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
            "smart_collapse_soft_rule_enabled": bool(
                self.smart_collapse_soft_ratio_rule_enabled
            ),
            "smart_collapse_allow_comma_endings": bool(
                self.smart_collapse_allow_comma_endings
            ),
            "smart_collapse_allow_colon_triplet_endings": bool(
                self.smart_collapse_allow_colon_triplet_endings
            ),
            "smart_collapse_ellipsis_lowercase_rule": bool(
                self.smart_collapse_ellipsis_lowercase_rule
            ),
            "smart_collapse_collapse_if_no_punctuation": bool(
                self.smart_collapse_collapse_if_no_punctuation
            ),
            "smart_collapse_soft_ratio_percent": int(
                self.smart_collapse_soft_ratio_percent
            ),
            "hide_control_codes": bool(self.hide_control_codes_check.isChecked()),
            "create_backup": bool(self.backup_check.isChecked()),
            "problem_char_limit": bool(self.problem_char_limit_check.isChecked()),
            "problem_line_limit": bool(self.problem_line_limit_check.isChecked()),
            "problem_control_mismatch": bool(
                self.problem_control_mismatch_check.isChecked()
            ),
            "problem_trailing_color_code": bool(
                self.problem_trailing_color_code_check.isChecked()
            ),
            "problem_missing_translation": bool(
                self.problem_missing_translation_check.isChecked()
            ),
            "problem_contains_japanese": bool(
                self.problem_contains_japanese_check.isChecked()
            ),
            "hide_non_meaningful_entries": bool(
                self.hide_non_meaningful_entries_check.isChecked()
            ),
            "show_empty_files": bool(self.show_empty_files_check.isChecked()),
            "default_variable_length": int(self.default_variable_length_estimate),
            "variable_length_overrides": {
                str(key): int(value)
                for key, value in sorted(self.variable_length_overrides.items())
            },
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
        self.problem_char_limit_check.blockSignals(True)
        self.problem_line_limit_check.blockSignals(True)
        self.problem_control_mismatch_check.blockSignals(True)
        self.problem_trailing_color_code_check.blockSignals(True)
        self.problem_missing_translation_check.blockSignals(True)
        self.problem_contains_japanese_check.blockSignals(True)
        self.hide_non_meaningful_entries_check.blockSignals(True)
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
            smart_collapse_soft_rule_enabled = settings.get(
                "smart_collapse_soft_rule_enabled"
            )
            if isinstance(smart_collapse_soft_rule_enabled, bool):
                self.smart_collapse_soft_ratio_rule_enabled = (
                    smart_collapse_soft_rule_enabled
                )
            smart_collapse_allow_comma_endings = settings.get(
                "smart_collapse_allow_comma_endings"
            )
            if isinstance(smart_collapse_allow_comma_endings, bool):
                self.smart_collapse_allow_comma_endings = (
                    smart_collapse_allow_comma_endings
                )
            smart_collapse_allow_colon_triplet_endings = settings.get(
                "smart_collapse_allow_colon_triplet_endings"
            )
            if isinstance(smart_collapse_allow_colon_triplet_endings, bool):
                self.smart_collapse_allow_colon_triplet_endings = (
                    smart_collapse_allow_colon_triplet_endings
                )
            smart_collapse_ellipsis_lowercase_rule = settings.get(
                "smart_collapse_ellipsis_lowercase_rule"
            )
            if isinstance(smart_collapse_ellipsis_lowercase_rule, bool):
                self.smart_collapse_ellipsis_lowercase_rule = (
                    smart_collapse_ellipsis_lowercase_rule
                )
            collapse_if_no_punctuation = settings.get(
                "smart_collapse_collapse_if_no_punctuation"
            )
            if not isinstance(collapse_if_no_punctuation, bool):
                collapse_if_no_punctuation = settings.get(
                    "smart_collapse_keep_break_on_any_punctuation"
                )
            if not isinstance(collapse_if_no_punctuation, bool):
                collapse_if_no_punctuation = settings.get(
                    "smart_collapse_only_no_punctuation"
                )
            if isinstance(collapse_if_no_punctuation, bool):
                self.smart_collapse_collapse_if_no_punctuation = (
                    collapse_if_no_punctuation
                )
            smart_collapse_soft_ratio_percent = settings.get(
                "smart_collapse_soft_ratio_percent"
            )
            if isinstance(smart_collapse_soft_ratio_percent, int):
                self.smart_collapse_soft_ratio_percent = max(
                    0, min(100, int(smart_collapse_soft_ratio_percent))
                )
            hide_control_codes = settings.get("hide_control_codes")
            if isinstance(hide_control_codes, bool):
                self.hide_control_codes_check.setChecked(hide_control_codes)
            create_backup = settings.get("create_backup")
            if isinstance(create_backup, bool):
                self.backup_check.setChecked(create_backup)
            problem_char_limit = settings.get("problem_char_limit")
            if isinstance(problem_char_limit, bool):
                self.problem_char_limit_check.setChecked(problem_char_limit)
            problem_line_limit = settings.get("problem_line_limit")
            if isinstance(problem_line_limit, bool):
                self.problem_line_limit_check.setChecked(problem_line_limit)
            problem_control_mismatch = settings.get("problem_control_mismatch")
            if isinstance(problem_control_mismatch, bool):
                self.problem_control_mismatch_check.setChecked(
                    problem_control_mismatch
                )
            problem_trailing_color_code = settings.get(
                "problem_trailing_color_code"
            )
            if isinstance(problem_trailing_color_code, bool):
                self.problem_trailing_color_code_check.setChecked(
                    problem_trailing_color_code
                )
            problem_missing_translation = settings.get(
                "problem_missing_translation"
            )
            if isinstance(problem_missing_translation, bool):
                self.problem_missing_translation_check.setChecked(
                    problem_missing_translation
                )
            problem_contains_japanese = settings.get(
                "problem_contains_japanese"
            )
            if isinstance(problem_contains_japanese, bool):
                self.problem_contains_japanese_check.setChecked(
                    problem_contains_japanese
                )
            hide_non_meaningful_entries = settings.get(
                "hide_non_meaningful_entries"
            )
            if isinstance(hide_non_meaningful_entries, bool):
                self.hide_non_meaningful_entries_check.setChecked(
                    hide_non_meaningful_entries
                )
            show_empty_files = settings.get("show_empty_files")
            if isinstance(show_empty_files, bool):
                self.show_empty_files_check.setChecked(show_empty_files)

            default_variable_length = settings.get("default_variable_length")
            if isinstance(default_variable_length, int):
                self.default_variable_length_estimate = (
                    self._clamp_variable_length_estimate(default_variable_length)
                )
            raw_variable_overrides = settings.get("variable_length_overrides")
            parsed_overrides: dict[int, int] = {}
            if isinstance(raw_variable_overrides, dict):
                for raw_key, raw_value in raw_variable_overrides.items():
                    if not isinstance(raw_value, int):
                        continue
                    parsed_key: Optional[int] = None
                    if isinstance(raw_key, int):
                        parsed_key = raw_key
                    elif isinstance(raw_key, str):
                        stripped_key = raw_key.strip()
                        if stripped_key and re.fullmatch(r"\d+", stripped_key):
                            parsed_key = int(stripped_key)
                    if parsed_key is None:
                        continue
                    parsed_overrides[parsed_key] = self._clamp_variable_length_estimate(
                        raw_value
                    )
            self.variable_length_overrides = parsed_overrides
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
            self.problem_char_limit_check.blockSignals(False)
            self.problem_line_limit_check.blockSignals(False)
            self.problem_control_mismatch_check.blockSignals(False)
            self.problem_trailing_color_code_check.blockSignals(False)
            self.problem_missing_translation_check.blockSignals(False)
            self.problem_contains_japanese_check.blockSignals(False)
            self.hide_non_meaningful_entries_check.blockSignals(False)
            self.show_empty_files_check.blockSignals(False)
            self._applying_project_ui_state = False

        self._sync_variable_length_measurement_settings()
        self._update_mode_controls()
        self._sync_settings_menu_from_controls()
        self._sync_settings_toggle_actions_from_controls()
        self._update_problem_checks_ui()
        self._sync_settings_limits_menu_labels()
        self._sync_smart_collapse_menu_state()
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
            logger.exception("Failed to load UI state from '%s'.", self.ui_state_path)
            return

        self.project_ui_settings_by_folder = loaded_project_settings
        self.remember_folder_check.blockSignals(True)
        self.remember_folder_check.setChecked(remember_last_folder)
        self.remember_folder_check.blockSignals(False)
        self._sync_settings_toggle_actions_from_controls()
        self.last_folder_path = last_folder

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
                last_folder = self.last_folder_path.strip()

        payload = {
            "remember_last_folder": remember_last_folder,
            "last_folder": last_folder,
            "project_settings": self.project_ui_settings_by_folder,
        }
        try:
            with self.ui_state_path.open("w", encoding="utf-8") as dst:
                json.dump(payload, dst, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to save UI state to '%s'.", self.ui_state_path)

    def _choose_folder(self) -> None:
        start_dir = str(self.data_dir) if self.data_dir else str(Path.cwd())
        chosen = QFileDialog.getExistingDirectory(
            self, "Select data folder", start_dir)
        if not chosen:
            return
        self.last_folder_path = chosen
        self._load_data_folder(Path(chosen))

    def _reload_folder_from_text(self) -> None:
        text = str(self.data_dir) if self.data_dir is not None else self.last_folder_path.strip()
        if not text:
            QMessageBox.warning(
                self,
                "Missing folder",
                "Open a data folder first.",
            )
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
                "This will re-read JSON files from disk and overwrite snapshot data.\n"
                "Use with caution.\n\n"
                f"Selected apply version: {selected_label}\n"
                f"Default import target: {import_target_label}\n"
                f"Will overwrite: {import_target_label} snapshot\n"
                "Original snapshot is locked and will not be overwritten."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        applied_version = self.version_db.get_applied_version(
        ) if self.version_db is not None else None
        selected_profile_id = self.active_translation_profile_id
        selected_profile_label = self._translation_profile_choice_label(
            selected_profile_id
        )
        applied_profile_id = self.version_db.get_applied_translation_profile(
        ) if self.version_db is not None else DEFAULT_TRANSLATION_PROFILE_ID
        applied_profile_label = self._translation_profile_choice_label(
            applied_profile_id
        )
        profile_mismatch = (
            selected_version == "translated"
            and applied_version == "translated"
            and applied_profile_id != selected_profile_id
        )
        version_mismatch = (
            applied_version is not None and applied_version != selected_version
        )
        if version_mismatch or profile_mismatch:
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
            message_lines = [
                "Selected apply version and last applied game-file version do not match.",
                "",
                f"Selected: {selected_label}",
                f"Last applied to files: {applied_label}",
                f"Last applied timestamp: {applied_at or '(unknown)'}",
            ]
            if selected_version == "translated":
                message_lines.extend(
                    [
                        f"Selected profile: {selected_profile_label}",
                        f"Last applied translated profile: {applied_profile_label}",
                    ]
                )
            message_lines.extend(
                [
                    "",
                    "Choose which snapshot this disk read should overwrite.",
                ]
            )
            serious.setText("\n".join(message_lines))
            to_selected_btn = serious.addButton(
                f"Import Into {import_target_label}",
                QMessageBox.ButtonRole.AcceptRole,
            )
            to_applied_btn = None
            if (
                applied_import_target
                and applied_import_target != import_target_version
            ):
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

    def _on_hide_non_meaningful_toggled(self, _checked: bool) -> None:
        self._rebuild_file_list(preferred_path=self.current_path)
        if self.current_path is not None:
            self._rerender_current_file()

    def _visible_file_paths(self) -> list[Path]:
        visible_paths: list[Path] = []
        show_empty = self.show_empty_files_check.isChecked()
        translator_mode = self._is_translator_mode()
        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            actor_mode = self._is_name_index_session(session)
            display_segments = self._display_segments_for_session(
                session,
                translator_mode=translator_mode,
                actor_mode=actor_mode,
            )
            if not show_empty and not display_segments:
                continue
            visible_paths.append(path)
        return visible_paths

    def _is_misc_file_session(self, path: Path) -> bool:
        session = self.sessions.get(path)
        if session is None:
            return False
        return self._is_name_index_session(session)

    def _add_file_list_section(self, title: str) -> None:
        header_item = QListWidgetItem(f"[ {title.upper()} ]")
        header_item.setFlags(Qt.ItemFlag.NoItemFlags)
        header_item.setData(FILE_LIST_SECTION_ROLE, True)
        header_font = QFont(header_item.font())
        header_font.setBold(True)
        header_font.setItalic(True)
        header_item.setFont(header_font)
        header_item.setForeground(QColor("#64748b"))
        header_item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
        self.file_list.addItem(header_item)

    def _rebuild_file_list(self, preferred_path: Optional[Path] = None) -> None:
        visible_paths = self._visible_file_paths()
        target = preferred_path if preferred_path in visible_paths else None
        if target is None and self.current_path in visible_paths:
            target = self.current_path
        if target is None and visible_paths:
            target = visible_paths[0]
        dialogue_paths = [
            path for path in visible_paths if not self._is_misc_file_session(path)
        ]
        misc_paths = [path for path in visible_paths if self._is_misc_file_session(path)]

        self.file_list.blockSignals(True)
        self.file_list.clear()
        self.file_items.clear()
        if visible_paths:
            self._add_file_list_section("Dialogues")
            for path in dialogue_paths:
                item = QListWidgetItem("")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.file_list.addItem(item)
                self.file_items[path] = item
                self._update_file_item_text(path)

            self._add_file_list_section("Misc")
            for path in misc_paths:
                item = QListWidgetItem("")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.file_list.addItem(item)
                self.file_items[path] = item
                self._update_file_item_text(path)
        self.file_list.blockSignals(False)

        if not visible_paths:
            self.current_path = None
            self._update_window_title()
            self._clear_blocks()
            self.current_segment_lookup.clear()
            self.block_widgets.clear()
            self.selected_segment_uid = None
            self.current_reference_map = {}
            no_visible_message = (
                "No visible files. Enable 'Show empty' to include files without dialogue blocks."
            )
            if self.hide_non_meaningful_entries_check.isChecked():
                no_visible_message += (
                    " You can also disable 'Hide non-meaningful entries'."
                )
            self.file_header_label.setText(no_visible_message)
            self._update_reset_json_button(None)
            self._refresh_translator_detail_panel()
            return

        assert target is not None
        target_item = self.file_items.get(target)
        if target_item is not None:
            self.file_list.setCurrentItem(target_item)

    def _plugins_js_candidates(self, data_dir: Path) -> list[Path]:
        parent_dir = data_dir.parent
        return [
            parent_dir / "js" / "plugins.js",
            data_dir / "js" / "plugins.js",
        ]

    def _collect_supported_file_paths(self, data_dir: Path) -> list[Path]:
        excluded_names = {
            TRANSLATION_STATE_FILENAME,
        }
        supported_files: list[Path] = [
            path
            for path in data_dir.glob("*.json")
            if (
                path.is_file()
                and not path.name.endswith(".bak")
                and path.name not in excluded_names
            )
        ]
        seen: set[Path] = {path.resolve() for path in supported_files}
        for candidate in self._plugins_js_candidates(data_dir):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            supported_files.append(resolved)
            seen.add(resolved)
        supported_files.sort(
            key=lambda path: natural_sort_key(self._relative_path(path)))
        return supported_files

    def _prepare_session_for_translated_disk_import(
        self,
        path: Path,
        rel_path: str,
        translated_disk_session: FileSession,
    ) -> FileSession:
        if self.version_db is None:
            return translated_disk_session

        payload = self.version_db.get_working_snapshot_payload(rel_path)
        if not payload:
            return translated_disk_session
        try:
            decoded = json.loads(payload)
            working_session = parse_dialogue_data(path, decoded)
        except Exception:
            logger.exception(
                "Failed to parse working snapshot for translated import fallback '%s'; using disk session.",
                rel_path,
            )
            return translated_disk_session
        return working_session

    def _json_backup_counterpart_for_path(self, path: Path) -> Optional[Path]:
        if path.suffix.lower() != ".json":
            return None
        backup_path = path.with_suffix(path.suffix + ".bak")
        if backup_path.is_file():
            return backup_path
        return None

    def _parse_json_dialogue_source_as_path(
        self,
        source_path: Path,
        virtual_path: Path,
    ) -> FileSession:
        with source_path.open("r", encoding="utf-8") as src:
            decoded = json.load(src)
        return parse_dialogue_data(virtual_path, decoded)

    def _build_translation_only_segment_for_import(
        self,
        session: FileSession,
        template_segment: DialogueSegment,
        translated_segment: DialogueSegment,
    ) -> DialogueSegment:
        speaker_text = translated_segment.speaker_name.strip()
        if speaker_text == NO_SPEAKER_KEY:
            speaker_text = ""
        translation_lines = self._normalize_translation_lines(translated_segment.lines)
        return DialogueSegment(
            uid=self._new_segment_uid(session.path),
            context=template_segment.context,
            code101=copy.deepcopy(template_segment.code101),
            lines=[""],
            original_lines=[""],
            source_lines=[""],
            code401_template=copy.deepcopy(template_segment.code401_template),
            segment_kind=template_segment.segment_kind,
            line_entry_code=template_segment.line_entry_code,
            choice_branch_entries=copy.deepcopy(template_segment.choice_branch_entries),
            script_entries_template=copy.deepcopy(template_segment.script_entries_template),
            script_entry_roles=list(template_segment.script_entry_roles),
            script_entry_quotes=list(template_segment.script_entry_quotes),
            tl_uid=self._new_translation_uid(),
            translation_lines=list(translation_lines),
            original_translation_lines=list(translation_lines),
            translation_speaker=speaker_text,
            original_translation_speaker=speaker_text,
            disable_line1_speaker_inference=template_segment.disable_line1_speaker_inference,
            original_disable_line1_speaker_inference=template_segment.disable_line1_speaker_inference,
            force_line1_speaker_inference=template_segment.force_line1_speaker_inference,
            original_force_line1_speaker_inference=template_segment.force_line1_speaker_inference,
            inserted=False,
            translation_only=True,
        )

    def _hydrate_translation_from_translated_session(
        self,
        session: FileSession,
        translated_session: FileSession,
    ) -> bool:
        source_segments = [seg for seg in session.segments if not seg.translation_only]
        translated_segments = [
            seg for seg in translated_session.segments if not seg.translation_only
        ]
        if not source_segments or not translated_segments:
            return False

        mapped_pairs: list[tuple[int, int]] = []
        translated_inserts_by_anchor: dict[int, list[int]] = {}
        is_name_index_session = bool(getattr(session, "is_name_index_session", False))
        if is_name_index_session:
            translated_by_uid: dict[str, int] = {}
            duplicate_uid = False
            for idx, segment in enumerate(translated_segments):
                if segment.uid in translated_by_uid:
                    duplicate_uid = True
                    break
                translated_by_uid[segment.uid] = idx
            if not duplicate_uid:
                for source_idx, segment in enumerate(source_segments):
                    translated_idx = translated_by_uid.get(segment.uid)
                    if translated_idx is not None:
                        mapped_pairs.append((source_idx, translated_idx))
        if not mapped_pairs:
            mapped_pairs, translated_inserts_by_anchor = align_source_translated_segments(
                source_segments,
                translated_segments,
            )

        mapped_count = 0
        for source_idx, translated_idx in mapped_pairs:
            if source_idx < 0 or source_idx >= len(source_segments):
                continue
            if translated_idx < 0 or translated_idx >= len(translated_segments):
                continue
            source_segment = source_segments[source_idx]
            translated_segment = translated_segments[translated_idx]
            translation_lines = self._normalize_translation_lines(translated_segment.lines)
            source_segment.translation_lines = list(translation_lines)
            source_segment.original_translation_lines = list(translation_lines)

            speaker_text = translated_segment.speaker_name.strip()
            if speaker_text == NO_SPEAKER_KEY:
                speaker_text = ""
            if source_segment.speaker_name != NO_SPEAKER_KEY:
                source_segment.translation_speaker = speaker_text
                source_segment.original_translation_speaker = speaker_text
                if speaker_text:
                    speaker_key = self._speaker_key_for_segment(source_segment)
                    if speaker_key != NO_SPEAKER_KEY:
                        self.speaker_translation_map[speaker_key] = speaker_text
            else:
                source_segment.translation_speaker = ""
                source_segment.original_translation_speaker = ""
            mapped_count += 1

        def template_for_anchor(anchor_idx: int) -> Optional[DialogueSegment]:
            if 0 <= anchor_idx < len(source_segments):
                candidate = source_segments[anchor_idx]
                if candidate.is_structural_dialogue:
                    return candidate
            for reverse_idx in range(min(anchor_idx, len(source_segments) - 1), -1, -1):
                candidate = source_segments[reverse_idx]
                if candidate.is_structural_dialogue:
                    return candidate
            for candidate in source_segments:
                if candidate.is_structural_dialogue:
                    return candidate
            return None

        ordered_segments: list[DialogueSegment] = []
        inserted_count = 0
        leading_insert_indexes = translated_inserts_by_anchor.get(-1, [])
        if leading_insert_indexes:
            template_segment = template_for_anchor(-1)
            for translated_idx in leading_insert_indexes:
                if translated_idx < 0 or translated_idx >= len(translated_segments):
                    continue
                translated_segment = translated_segments[translated_idx]
                if template_segment is None or not translated_segment.is_structural_dialogue:
                    continue
                inserted_segment = self._build_translation_only_segment_for_import(
                    session,
                    template_segment,
                    translated_segment,
                )
                if inserted_segment.translation_speaker:
                    speaker_key = self._speaker_key_for_segment(inserted_segment)
                    if speaker_key != NO_SPEAKER_KEY:
                        self.speaker_translation_map[speaker_key] = (
                            inserted_segment.translation_speaker
                        )
                ordered_segments.append(inserted_segment)
                inserted_count += 1

        for source_idx, source_segment in enumerate(source_segments):
            ordered_segments.append(source_segment)
            translated_insert_indexes = translated_inserts_by_anchor.get(source_idx, [])
            if not translated_insert_indexes:
                continue
            template_segment = template_for_anchor(source_idx)
            for translated_idx in translated_insert_indexes:
                if translated_idx < 0 or translated_idx >= len(translated_segments):
                    continue
                translated_segment = translated_segments[translated_idx]
                if template_segment is None or not translated_segment.is_structural_dialogue:
                    continue
                inserted_segment = self._build_translation_only_segment_for_import(
                    session,
                    template_segment,
                    translated_segment,
                )
                if inserted_segment.translation_speaker:
                    speaker_key = self._speaker_key_for_segment(inserted_segment)
                    if speaker_key != NO_SPEAKER_KEY:
                        self.speaker_translation_map[speaker_key] = (
                            inserted_segment.translation_speaker
                        )
                ordered_segments.append(inserted_segment)
                inserted_count += 1

        session.segments = ordered_segments
        if mapped_count != len(source_segments):
            logger.warning(
                "Translated import mapping mismatch for '%s': mapped=%s source=%s translated=%s inserted=%s",
                session.path.name,
                mapped_count,
                len(source_segments),
                len(translated_segments),
                inserted_count,
            )
        return mapped_count > 0 or inserted_count > 0

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
        self.last_folder_path = str(self.data_dir)
        logger.info(
            "Loading data folder '%s' (force_disk_import=%s, import_target_version=%s).",
            self.data_dir,
            force_disk_import,
            import_target_version,
        )
        self.detected_rpg_engine = self._detect_rpg_maker_engine(self.data_dir)
        self.default_variable_length_estimate = _DEFAULT_VARIABLE_LENGTH_ESTIMATE
        self.variable_length_overrides = {}
        self.smart_collapse_soft_ratio_rule_enabled = True
        self.smart_collapse_allow_comma_endings = False
        self.smart_collapse_allow_colon_triplet_endings = False
        self.smart_collapse_ellipsis_lowercase_rule = False
        self.smart_collapse_collapse_if_no_punctuation = True
        self.smart_collapse_soft_ratio_percent = _DEFAULT_SMART_COLLAPSE_SOFT_RATIO_PERCENT
        self._sync_variable_length_measurement_settings()
        self._configure_project_message_text_metrics(self.data_dir)
        self._update_window_title()
        project_key = self._project_state_key(self.data_dir)
        project_settings = self.project_ui_settings_by_folder.get(project_key)
        project_has_infer_setting = (
            isinstance(project_settings, dict)
            and isinstance(project_settings.get("infer_speaker"), bool)
        )
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
        version_db_path = self.data_dir / VERSION_DB_FILENAME
        version_db_preexisting = version_db_path.exists()
        self.index_db = DialogueIndexDB(self.data_dir / DB_FILENAME)
        self.version_db = DialogueVersionDB(version_db_path)
        self.translation_state_path = self.data_dir / TRANSLATION_STATE_FILENAME
        self._load_translation_state()
        self._rebuild_translation_profile_menu()

        self.sessions.clear()
        self._update_window_title()
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

        self.file_paths = self._collect_supported_file_paths(self.data_dir)

        if not self.file_paths:
            self.file_header_label.setText(
                "No supported files found in selected folder")
            self._update_reset_json_button(None)
            self.save_btn.setEnabled(False)
            self.save_all_btn.setEnabled(False)
            self.apply_version_combo.setEnabled(False)
            self._set_apply_snapshot_actions_enabled(False)
            self.next_problem_btn.setEnabled(False)
            self.selected_segment_uid = None
            self.current_reference_map = {}
            self._refresh_translator_detail_panel()
            self.statusBar().showMessage("No supported files found.")
            return

        load_errors: list[str] = []
        loaded_from_db_count = 0
        loaded_from_disk_count = 0
        total_blocks = 0
        translated_import_hydrated = False
        bootstrap_from_json_backups = (
            (not force_disk_import) and (not version_db_preexisting)
        )
        bak_bootstrap_count = 0
        # Never force positional TL-state matching. Source-hash matching is safer
        # for parser/order changes and avoids large desync cascades.
        self._translation_state_force_positional_match = False
        for path in self.file_paths:
            try:
                rel_path = self._relative_path(path)
                session: Optional[FileSession] = None
                loaded_from_db = False
                had_working_payload = False
                failed_working_snapshot_parse = False
                import_data: Any = None
                translated_disk_session: Optional[FileSession] = None
                used_bak_bootstrap = False
                bak_source_data: Any = None
                bak_translated_data: Any = None

                if not force_disk_import and self.version_db is not None:
                    payload = self.version_db.get_working_snapshot_payload(
                        rel_path)
                    if payload:
                        had_working_payload = True
                        try:
                            decoded = json.loads(payload)
                            session = parse_dialogue_data(path, decoded)
                            loaded_from_db = True
                        except Exception:
                            logger.exception(
                                "Failed to parse working snapshot JSON for '%s'; falling back to disk file.",
                                rel_path,
                            )
                            failed_working_snapshot_parse = True
                            session = None

                if force_disk_import and import_target_version == "translated":
                    translated_disk_session = parse_dialogue_file(path)
                    import_data = translated_disk_session.data
                    session = self._prepare_session_for_translated_disk_import(
                        path,
                        rel_path,
                        translated_disk_session,
                    )
                elif session is None:
                    if bootstrap_from_json_backups:
                        backup_path = self._json_backup_counterpart_for_path(path)
                        if backup_path is not None:
                            try:
                                session = self._parse_json_dialogue_source_as_path(
                                    backup_path,
                                    path,
                                )
                                translated_disk_session = parse_dialogue_file(path)
                                import_data = session.data
                                used_bak_bootstrap = True
                                bak_source_data = session.data
                                bak_translated_data = translated_disk_session.data
                                bak_bootstrap_count += 1
                            except Exception:
                                logger.exception(
                                    "Failed to bootstrap '%s' from backup '%s'; falling back to disk file.",
                                    rel_path,
                                    backup_path,
                                )
                                session = None
                    if session is None:
                        session = parse_dialogue_file(path)
                        import_data = session.data
                elif import_data is None:
                    import_data = session.data

                self._apply_translation_state_to_session(session)
                if translated_disk_session is not None:
                    if self._hydrate_translation_from_translated_session(
                        session,
                        translated_disk_session,
                    ):
                        translated_import_hydrated = True
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
                                import_data,
                                target_version,
                                profile_id=self.active_translation_profile_id,
                            )
                        elif not loaded_from_db and (not had_working_payload):
                            if (
                                used_bak_bootstrap
                                and bak_source_data is not None
                                and bak_translated_data is not None
                            ):
                                self.version_db.ensure_original_snapshot(
                                    rel_path,
                                    bak_source_data,
                                )
                                self.version_db.save_working_snapshot(
                                    rel_path,
                                    bak_source_data,
                                )
                                self.version_db.save_translated_snapshot(
                                    rel_path,
                                    bak_translated_data,
                                    profile_id=self.active_translation_profile_id,
                                )
                            else:
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
                                    profile_id=self.active_translation_profile_id,
                                )
                        elif failed_working_snapshot_parse:
                            logger.warning(
                                "Preserving existing DB snapshots for '%s' because working snapshot payload exists but could not be parsed.",
                                rel_path,
                            )
                    except Exception:
                        logger.exception(
                            "Failed to update version snapshots for '%s'.", rel_path
                        )
                if self.index_db is not None:
                    try:
                        self.index_db.update_file_index(
                            rel_path,
                            path.stat().st_mtime,
                            session.segments,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to update index DB for '%s' during folder load.",
                            rel_path,
                        )
            except Exception:
                logger.exception("Failed to load supported file '%s'.", path)
                load_errors.append(path.name)
        self._translation_state_force_positional_match = False

        if translated_import_hydrated:
            self._save_translation_state()

        if not self.sessions:
            self.save_btn.setEnabled(False)
            self.save_all_btn.setEnabled(False)
            self.apply_version_combo.setEnabled(False)
            self._set_apply_snapshot_actions_enabled(False)
            self.next_problem_btn.setEnabled(False)
            self.file_header_label.setText(
                "No readable supported files found in selected folder.")
            self._update_reset_json_button(None)
            self.selected_segment_uid = None
            self.current_reference_map = {}
            self._refresh_translator_detail_panel()
            self.statusBar().showMessage("No readable supported files found.")
            logger.warning("No readable supported files were loaded from '%s'.", self.data_dir)
            return

        has_explicit_speakers = any(
            segment.speaker_name != NO_SPEAKER_KEY
            for session in self.sessions.values()
            if not self._is_name_index_session(session)
            for segment in session.segments
        )
        infer_auto_changed = False
        infer_auto_suffix = ""
        if not project_has_infer_setting:
            infer_default = self.infer_speaker_check.isChecked()
            infer_reason = ""
            if self.detected_rpg_engine == "mv":
                infer_default = True
                infer_reason = "MV project detected"
            elif self.detected_rpg_engine == "mz":
                infer_default = False
                infer_reason = "MZ project detected"
            else:
                infer_default = not has_explicit_speakers
                if infer_default:
                    infer_reason = "no explicit speakers found"
                else:
                    infer_reason = "explicit speakers found"
            if self.infer_speaker_check.isChecked() != infer_default:
                self.infer_speaker_check.setChecked(infer_default)
                infer_auto_changed = True
            infer_state = "enabled" if infer_default else "disabled"
            infer_auto_suffix = f" Auto infer speaker-from-line1 {infer_state} ({infer_reason})."

        self.save_btn.setEnabled(True)
        self.save_all_btn.setEnabled(True)
        self.apply_version_combo.setEnabled(True)
        self._set_apply_snapshot_actions_enabled(True)
        self.next_problem_btn.setEnabled(True)
        self._rebuild_file_list()

        visible_count = len(self._visible_file_paths())
        engine_suffix = f" Engine: {self._rpg_engine_label(self.detected_rpg_engine)}."
        font_source = self.detected_message_font_source or "default"
        font_suffix = f" Message font: {self.detected_message_font_size}px ({font_source})."
        infer_suffix = infer_auto_suffix if infer_auto_changed else ""
        bak_suffix = (
            f" Imported source from .bak for {bak_bootstrap_count} files."
            if bak_bootstrap_count > 0
            else ""
        )
        if load_errors:
            skipped_label = "file" if len(load_errors) == 1 else "files"
            self.statusBar().showMessage(
                f"Loaded {len(self.sessions)} files ({visible_count} shown), "
                f"{total_blocks} blocks from DB:{loaded_from_db_count}/disk:{loaded_from_disk_count}. "
                f"Skipped {len(load_errors)} unreadable {skipped_label}.{engine_suffix}{font_suffix}{infer_suffix}{bak_suffix}"
            )
            logger.warning(
                "Folder load completed with unreadable files: %s",
                ", ".join(load_errors),
            )
        else:
            self.statusBar().showMessage(
                f"Loaded {len(self.sessions)} files ({visible_count} shown), "
                f"{total_blocks} blocks from DB:{loaded_from_db_count}/disk:{loaded_from_disk_count}.{engine_suffix}{font_suffix}{infer_suffix}{bak_suffix}"
            )
        logger.info(
            "Folder load complete: total_files=%d loaded=%d visible=%d blocks=%d db=%d disk=%d errors=%d bak_bootstrapped=%d.",
            len(self.file_paths),
            len(self.sessions),
            visible_count,
            total_blocks,
            loaded_from_db_count,
            loaded_from_disk_count,
            len(load_errors),
            bak_bootstrap_count,
        )

    def _file_path_from_item(self, item: Optional[QListWidgetItem]) -> Optional[Path]:
        if item is None:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        if not raw:
            return None
        return Path(str(raw))

    def _sync_file_list_selection(self, path: Path) -> None:
        target_item = self.file_items.get(path)
        if target_item is None:
            return
        if self.file_list.currentItem() is target_item:
            return
        self.file_list.blockSignals(True)
        try:
            self.file_list.setCurrentItem(target_item)
        finally:
            self.file_list.blockSignals(False)

    def _on_file_selected(self, current: Optional[QListWidgetItem], _previous: Optional[QListWidgetItem]) -> None:
        path = self._file_path_from_item(current)
        if path is None:
            if self.current_path is not None:
                selected_item = self.file_items.get(self.current_path)
                if selected_item is not None and self.file_list.currentItem() is not selected_item:
                    self.file_list.blockSignals(True)
                    self.file_list.setCurrentItem(selected_item)
                    self.file_list.blockSignals(False)
            return
        self._open_file(path)

    def _relative_path(self, path: Path) -> str:
        if self.data_dir is None:
            return path.name
        resolved = path.resolve()
        try:
            return str(resolved.relative_to(self.data_dir))
        except ValueError:
            try:
                return str(resolved.relative_to(self.data_dir.parent))
            except ValueError:
                return str(resolved)

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
                            logger.exception(
                                "Failed to parse working snapshot JSON for '%s'; falling back to disk file.",
                                rel_path,
                            )
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
            logger.exception("JSON parse error while opening '%s'.", path)
            QMessageBox.critical(self, "JSON parse error",
                                 f"Failed to parse file:\n{path}\n\n{exc}")
            return
        except Exception as exc:
            logger.exception("Failed to open file '%s'.", path)
            QMessageBox.critical(
                self, "Error", f"Failed to open file:\n{path}\n\n{exc}")
            return

        self.current_path = path
        self._sync_file_list_selection(path)
        self._update_window_title()
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
                logger.exception("Failed to update index DB for '%s'.", path)

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

    def _problem_checks_summary_text(self) -> str:
        enabled_checks: list[str] = []
        if self.problem_char_limit_check.isChecked():
            enabled_checks.append("char width")
        if self.problem_line_limit_check.isChecked():
            enabled_checks.append("line count")
        if self.problem_control_mismatch_check.isChecked():
            enabled_checks.append("control-code mismatch")
        if self.problem_trailing_color_code_check.isChecked():
            enabled_checks.append("trailing \\C[n]")
        if self.problem_missing_translation_check.isChecked():
            enabled_checks.append("missing translation")
        if self.problem_contains_japanese_check.isChecked():
            enabled_checks.append("contains Japanese")
        if not enabled_checks:
            return "none"
        return ", ".join(enabled_checks)

    def _update_problem_checks_ui(self) -> None:
        if not hasattr(self, "next_problem_btn"):
            return
        checks_text = self._problem_checks_summary_text()
        if checks_text == "none":
            tooltip = (
                "No problem checks enabled. Enable checks in Settings > Problem Checks."
            )
        else:
            tooltip = (
                "Jump to the next block matching enabled checks "
                f"({checks_text}) in the current mode."
            )
        self.next_problem_btn.setToolTip(tooltip)

    def _on_problem_checks_changed(self, _checked: bool) -> None:
        self._refresh_all_file_item_text()
        self._update_problem_checks_ui()
        self._refresh_block_control_mismatch_highlighting()
        self._refresh_translator_detail_panel()

    def _jump_to_next_problem(self) -> None:
        if not self.sessions:
            self.statusBar().showMessage("Load files before jumping to problems.")
            return

        checks_text = self._problem_checks_summary_text()
        if checks_text == "none":
            self.statusBar().showMessage(
                "No problem checks enabled. Enable checks in Settings > Problem Checks."
            )
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
                f"No problems found ({checks_text}) in {mode_label} mode."
            )
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
        self.audit_term_worker_timer.stop()
        try:
            self.audit_worker_executor.shutdown(
                wait=False, cancel_futures=True)
        except TypeError:
            self.audit_worker_executor.shutdown(wait=False)
        self._save_ui_state()
        super().closeEvent(event)


def _set_windows_app_id(app_id: str) -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass  # don’t crash if it fails


def main() -> int:
    _set_windows_app_id(APP_ID)
    
    log_path: Optional[Path] = None
    try:
        log_path = configure_file_logging()
    except Exception:
        # Last-resort fallback: keep the app functional even if logging setup fails.
        log_path = None
    install_global_exception_hooks()
    if log_path is not None:
        logger.info("Starting %s. Log file: %s", APP_TITLE, log_path)
    else:
        logger.warning("Starting %s without file logging.", APP_TITLE)

    app = QApplication(sys.argv)
    
    icon_path = Path(__file__).resolve().parent / "icon.ico"
    icon = QIcon(str(icon_path))
    if icon.isNull():
        raise FileNotFoundError(f"Icon not found/invalid: {icon_path}")
    
    app.setWindowIcon(icon)
    window = DialogueVisualEditor()
    window.setWindowIcon(icon)
    window.show()
    exit_code = app.exec()
    logger.info("Exited %s with code %s.", APP_TITLE, exit_code)
    return exit_code
