from __future__ import annotations

import copy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QPushButton, QWidget

from .models import (
    CommandBundle,
    CommandToken,
    DeletedBlockAction,
    DialogueSegment,
    FileSession,
    InsertedBlockAction,
    MergeBlocksAction,
    ResetBlockAction,
    SplitOverflowAction,
    StructuralAction,
)
from .text_utils import smart_collapse_lines_space_efficient

if TYPE_CHECKING:
    from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton



class _EditorHostTypingFallback:
    # DialogueVisualEditor provides many attributes/methods consumed by mixins.
    # For static analysis, allow unresolved host members to type as Any.
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class StructuralEditingMixin(_EditorHostTypingFallback):
    def _segment_line_width(self, segment: DialogueSegment) -> int:
        return self.thin_width_spin.value() if segment.has_face else self.wide_width_spin.value()

    def _same_merge_signature(self, left: DialogueSegment, right: DialogueSegment) -> bool:
        return (
            left.context == right.context
            and left.code101.get("parameters") == right.code101.get("parameters")
        )

    def _can_merge_segments(self, session: FileSession, left: DialogueSegment, right: DialogueSegment) -> bool:
        if not self._same_merge_signature(left, right):
            return False
        left_index = self._find_segment_index_by_uid(session, left.uid)
        right_index = self._find_segment_index_by_uid(session, right.uid)
        if left_index < 0 or right_index != left_index + 1:
            return False
        left_bundle, left_token_index = self._find_segment_token(session, left.uid)
        right_bundle, right_token_index = self._find_segment_token(session, right.uid)
        if left_bundle is None or right_bundle is None:
            return False
        if left_bundle is not right_bundle:
            return False
        return right_token_index == left_token_index + 1

    def _merged_pair_line_savings(self, left: DialogueSegment, right: DialogueSegment) -> int:
        width = self._segment_line_width(left)
        before = len(left.lines) + len(right.lines)
        merged = smart_collapse_lines_space_efficient(list(left.lines) + list(right.lines), width)
        return before - len(merged)

    def _build_merge_connector_widget(
        self,
        session: FileSession,
        left: DialogueSegment,
        right: DialogueSegment,
    ) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 2, 6, 2)
        row_layout.setSpacing(8)

        left_line = QFrame()
        left_line.setFrameShape(QFrame.Shape.HLine)
        left_line.setFrameShadow(QFrame.Shadow.Sunken)
        row_layout.addWidget(left_line, 1)

        button = QPushButton("Merge")
        button.setMinimumHeight(24)
        button.setToolTip("Merge these neighboring blocks.")
        savings = self._merged_pair_line_savings(left, right)
        if savings > 0:
            button.setText(f"Merge (-{savings}L)")
        button.clicked.connect(
            lambda _checked=False, left_uid=left.uid, right_uid=right.uid: self._on_merge_pair_requested(
                left_uid,
                right_uid,
            )
        )
        row_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)

        right_line = QFrame()
        right_line.setFrameShape(QFrame.Shape.HLine)
        right_line.setFrameShadow(QFrame.Shadow.Sunken)
        row_layout.addWidget(right_line, 1)
        return row

    def _on_block_text_changed(self, uid: str, lines: list[str]) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return
        segment = self.current_segment_lookup.get(uid)
        if segment is None:
            return
        if self._is_translator_mode():
            segment.translation_lines = self._normalize_translation_lines(lines)
        else:
            segment.lines = list(lines)
            segment.source_lines = list(segment.lines)
        self._refresh_dirty_state(session)

    def _new_segment_uid(self, path: Path) -> str:
        self.segment_uid_counter += 1
        return f"{path.name}:I:{self.segment_uid_counter}"

    def _find_segment_token(self, session: FileSession, uid: str) -> tuple[Optional[CommandBundle], int]:
        for bundle in session.bundles:
            for idx, token in enumerate(bundle.tokens):
                if token.kind == "dialogue" and token.segment and token.segment.uid == uid:
                    return bundle, idx
        return None, -1

    def _find_segment_index_by_uid(self, session: FileSession, uid: str) -> int:
        for idx, segment in enumerate(session.segments):
            if segment.uid == uid:
                return idx
        return -1

    def _find_bundle_token_index_by_uid(self, bundle: CommandBundle, uid: str) -> int:
        for idx, token in enumerate(bundle.tokens):
            if token.kind == "dialogue" and token.segment and token.segment.uid == uid:
                return idx
        return -1

    def _remove_segment_by_uid(self, session: FileSession, uid: str) -> bool:
        bundle, token_index = self._find_segment_token(session, uid)
        if bundle is None or token_index < 0:
            return False
        segment_index = self._find_segment_index_by_uid(session, uid)
        if segment_index < 0:
            return False
        del bundle.tokens[token_index]
        del session.segments[segment_index]
        return True

    def _restore_merged_segments_after(
        self,
        session: FileSession,
        anchor_uid: str,
        merged_segments: list[DialogueSegment],
    ) -> int:
        if not merged_segments:
            return 0
        bundle, token_index = self._find_segment_token(session, anchor_uid)
        if bundle is None or token_index < 0:
            return 0
        segment_index = self._find_segment_index_by_uid(session, anchor_uid)
        if segment_index < 0:
            return 0

        restored = 0
        insert_token_index = token_index + 1
        insert_segment_index = segment_index + 1
        for restored_segment in merged_segments:
            if self._find_segment_index_by_uid(session, restored_segment.uid) >= 0:
                continue
            bundle.tokens.insert(insert_token_index, CommandToken(kind="dialogue", segment=restored_segment))
            session.segments.insert(insert_segment_index, restored_segment)
            insert_token_index += 1
            insert_segment_index += 1
            restored += 1
        return restored

    def _structural_action_references_uids(self, action: StructuralAction, path: Path, uids: set[str]) -> bool:
        if action.path != path:
            return False
        if action.kind == "insert":
            payload = cast(InsertedBlockAction, action.data)
            return payload.uid in uids
        if action.kind == "delete":
            payload = cast(DeletedBlockAction, action.data)
            return payload.uid in uids
        if action.kind == "merge":
            payload = cast(MergeBlocksAction, action.data)
            return payload.left_uid in uids or payload.right_uid in uids
        if action.kind == "reset":
            payload = cast(ResetBlockAction, action.data)
            if payload.uid in uids:
                return True
            return any(segment.uid in uids for segment in payload.restored_segments)
        if action.kind == "split_overflow":
            payload = cast(SplitOverflowAction, action.data)
            return payload.source_uid in uids or payload.moved_uid in uids
        return False

    def _prune_structural_history_entries(self, path: Path, uids: set[str]) -> None:
        if not uids:
            return
        self.structural_undo_stack = [
            entry for entry in self.structural_undo_stack
            if not self._structural_action_references_uids(entry, path, uids)
        ]
        self.structural_redo_stack = [
            entry for entry in self.structural_redo_stack
            if not self._structural_action_references_uids(entry, path, uids)
        ]

    def _clear_structural_history_for_path(self, path: Path) -> None:
        self.structural_undo_stack = [entry for entry in self.structural_undo_stack if entry.path != path]
        self.structural_redo_stack = [entry for entry in self.structural_redo_stack if entry.path != path]

    def _on_insert_after_requested(self, uid: str) -> None:
        if self._is_translator_mode():
            self.statusBar().showMessage("Insert is disabled in Translator Edit mode.")
            return
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        bundle, token_index = self._find_segment_token(session, uid)
        if bundle is None or token_index < 0:
            return

        source_token = bundle.tokens[token_index]
        if source_token.segment is None:
            return
        source_segment = source_token.segment

        try:
            bundle_index = session.bundles.index(bundle)
        except ValueError:
            return
        source_idx = session.segments.index(source_segment)

        new_segment = DialogueSegment(
            uid=self._new_segment_uid(session.path),
            context=source_segment.context,
            code101=copy.deepcopy(source_segment.code101),
            lines=[""],
            original_lines=[""],
            source_lines=[""],
            tl_uid=self._new_translation_uid(),
            translation_lines=[""],
            original_translation_lines=[""],
            translation_speaker=self.speaker_translation_map.get(source_segment.speaker_name, ""),
            original_translation_speaker=self.speaker_translation_map.get(source_segment.speaker_name, ""),
            inserted=True,
        )

        bundle.tokens.insert(token_index + 1, CommandToken(kind="dialogue", segment=new_segment))
        session.segments.insert(source_idx + 1, new_segment)
        insert_action = InsertedBlockAction(
            path=session.path,
            uid=new_segment.uid,
            bundle_index=bundle_index,
            token_index=token_index + 1,
            segment_index=source_idx + 1,
            segment=new_segment,
        )
        self.structural_undo_stack.append(
            StructuralAction(kind="insert", path=session.path, data=insert_action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        self._render_session(session, focus_uid=new_segment.uid, preserve_scroll=True)
        self.statusBar().showMessage("Inserted a new code 101 block.")

    def _on_split_overflow_requested(self, uid: str) -> None:
        if self._is_translator_mode():
            self.statusBar().showMessage("Overflow split is disabled in Translator Edit mode.")
            return
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        source_segment = self.current_segment_lookup.get(uid)
        if source_segment is None:
            return

        max_lines = self.max_lines_spin.value()
        source_lines_before = list(source_segment.lines)
        if len(source_lines_before) <= max_lines:
            self.statusBar().showMessage("No overflow lines to move.")
            return

        bundle, token_index = self._find_segment_token(session, uid)
        if bundle is None or token_index < 0:
            return
        source_index = self._find_segment_index_by_uid(session, uid)
        if source_index < 0:
            return

        kept_lines = source_lines_before[:max_lines]
        moved_lines = source_lines_before[max_lines:]
        new_segment = DialogueSegment(
            uid=self._new_segment_uid(session.path),
            context=source_segment.context,
            code101=copy.deepcopy(source_segment.code101),
            lines=list(moved_lines),
            original_lines=list(moved_lines),
            source_lines=list(moved_lines),
            tl_uid=self._new_translation_uid(),
            translation_lines=self._normalize_translation_lines(source_segment.translation_lines[max_lines:]),
            original_translation_lines=self._normalize_translation_lines(source_segment.translation_lines[max_lines:]),
            translation_speaker=source_segment.translation_speaker,
            original_translation_speaker=source_segment.translation_speaker,
            inserted=True,
        )

        source_segment.lines = list(kept_lines)
        source_segment.source_lines = list(source_segment.lines)
        source_tl_before = self._normalize_translation_lines(source_segment.translation_lines)
        source_segment.translation_lines = self._normalize_translation_lines(source_segment.translation_lines[:max_lines])
        bundle.tokens.insert(token_index + 1, CommandToken(kind="dialogue", segment=new_segment))
        session.segments.insert(source_index + 1, new_segment)

        split_action = SplitOverflowAction(
            path=session.path,
            source_uid=uid,
            moved_uid=new_segment.uid,
            source_lines_before=source_lines_before,
            source_lines_after=list(kept_lines),
            moved_segment=new_segment,
            source_translation_before=source_tl_before,
            source_translation_after=list(source_segment.translation_lines),
        )
        self.structural_undo_stack.append(
            StructuralAction(kind="split_overflow", path=session.path, data=split_action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        self._render_session(session, focus_uid=new_segment.uid, preserve_scroll=True)
        self.statusBar().showMessage(
            f"Moved {len(moved_lines)} overflow line(s) to a new block below."
        )

    def _on_merge_pair_requested(self, left_uid: str, right_uid: str) -> None:
        if self._is_translator_mode():
            self.statusBar().showMessage("Merge is disabled in Translator Edit mode.")
            return
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        left_index = self._find_segment_index_by_uid(session, left_uid)
        right_index = self._find_segment_index_by_uid(session, right_uid)
        if left_index < 0 or right_index != left_index + 1:
            return

        left_segment = session.segments[left_index]
        right_segment = session.segments[right_index]
        if not self._can_merge_segments(session, left_segment, right_segment):
            QMessageBox.information(
                cast(QWidget, self),
                "Cannot merge",
                "These blocks cannot be merged because their command context/settings differ.",
            )
            return

        left_bundle, left_token_index = self._find_segment_token(session, left_uid)
        right_bundle, right_token_index = self._find_segment_token(session, right_uid)
        if left_bundle is None or right_bundle is None:
            return
        if left_bundle is not right_bundle:
            return
        if right_token_index != left_token_index + 1:
            return

        left_lines_before = list(left_segment.lines)
        left_merged_before = list(left_segment.merged_segments)
        left_translation_before = self._normalize_translation_lines(left_segment.translation_lines)
        left_speaker_translation_before = left_segment.translation_speaker
        merged_lines = smart_collapse_lines_space_efficient(
            list(left_segment.lines) + list(right_segment.lines),
            self._segment_line_width(left_segment),
        )
        merged_tl_lines = smart_collapse_lines_space_efficient(
            self._normalize_translation_lines(left_segment.translation_lines)
            + self._normalize_translation_lines(right_segment.translation_lines),
            self._segment_line_width(left_segment),
        )
        merged_speaker_translation = (
            left_segment.translation_speaker.strip() or right_segment.translation_speaker.strip()
        )
        left_segment.lines = merged_lines
        left_segment.source_lines = list(left_segment.lines)
        left_segment.translation_lines = list(merged_tl_lines)
        left_segment.translation_speaker = merged_speaker_translation
        if merged_speaker_translation:
            self.speaker_translation_map[left_segment.speaker_name] = merged_speaker_translation
        left_segment.merged_segments.append(right_segment)
        del left_bundle.tokens[right_token_index]
        del session.segments[right_index]

        merge_action = MergeBlocksAction(
            path=session.path,
            left_uid=left_uid,
            right_uid=right_uid,
            left_lines_before=left_lines_before,
            left_lines_after=list(merged_lines),
            left_merged_before=left_merged_before,
            right_segment=right_segment,
            left_translation_before=left_translation_before,
            left_translation_after=list(merged_tl_lines),
            left_speaker_translation_before=left_speaker_translation_before,
            left_speaker_translation_after=merged_speaker_translation,
        )
        self.structural_undo_stack.append(
            StructuralAction(kind="merge", path=session.path, data=merge_action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        self._render_session(session, focus_uid=left_uid, preserve_scroll=True)
        self.statusBar().showMessage("Merged neighboring dialogue blocks.")

    def _on_reset_requested(self, uid: str) -> None:
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return
        segment = self.current_segment_lookup.get(uid)
        if segment is None:
            return

        if self._is_translator_mode():
            tl_before = self._normalize_translation_lines(segment.translation_lines)
            speaker_before = segment.translation_speaker.strip()
            tl_after = self._normalize_translation_lines(segment.original_translation_lines)
            speaker_after = segment.original_translation_speaker.strip()
            if tl_before == tl_after and speaker_before == speaker_after:
                self.statusBar().showMessage("Block translation is already reset.")
                return
            segment.translation_lines = list(tl_after)
            segment.translation_speaker = speaker_after
            if speaker_after:
                self.speaker_translation_map[segment.speaker_name] = speaker_after
            self._refresh_dirty_state(session)
            self._render_session(session, focus_uid=uid, preserve_scroll=True)
            self.statusBar().showMessage("Reset translation block.")
            return

        lines_before = list(segment.lines)
        merged_before = list(segment.merged_segments)
        restored_segments = [
            merged for merged in merged_before
            if self._find_segment_index_by_uid(session, merged.uid) < 0
        ]
        restored_count = 0
        if restored_segments:
            restored_count = self._restore_merged_segments_after(session, uid, restored_segments)
            segment.merged_segments.clear()
        lines_after = list(segment.original_lines)
        segment.lines = list(lines_after)
        segment.source_lines = list(segment.lines)
        changed = bool(merged_before) or lines_before != lines_after
        if changed:
            reset_action = ResetBlockAction(
                path=session.path,
                uid=uid,
                lines_before=lines_before,
                lines_after=lines_after,
                merged_before=merged_before,
                restored_segments=restored_segments,
            )
            self.structural_undo_stack.append(
                StructuralAction(kind="reset", path=session.path, data=reset_action)
            )
            self.structural_redo_stack.clear()
        self._refresh_dirty_state(session)
        self._render_session(session, focus_uid=uid, preserve_scroll=True)
        if restored_count > 0:
            self.statusBar().showMessage(f"Reset block and restored {restored_count} merged block(s).")
        else:
            self.statusBar().showMessage("Reset block.")

    def _on_delete_requested(self, uid: str) -> None:
        if self._is_translator_mode():
            self.statusBar().showMessage("Delete is disabled in Translator Edit mode.")
            return
        if self.current_path is None:
            return
        session = self.sessions.get(self.current_path)
        if session is None:
            return

        if len(session.segments) <= 1:
            QMessageBox.warning(
                cast(QWidget, self),
                "Cannot delete",
                "At least one dialogue block must remain in this file view.",
            )
            return

        button = QMessageBox.question(
            cast(QWidget, self),
            "Delete block",
            "Delete this dialogue block?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if button != QMessageBox.StandardButton.Yes:
            return

        bundle, token_index = self._find_segment_token(session, uid)
        if bundle is None or token_index < 0:
            return

        segment = bundle.tokens[token_index].segment
        if segment is None:
            return

        try:
            bundle_index = session.bundles.index(bundle)
        except ValueError:
            return
        segment_index = self._find_segment_index_by_uid(session, uid)
        if segment_index < 0:
            return
        action = DeletedBlockAction(
            path=session.path,
            uid=uid,
            bundle_index=bundle_index,
            token_index=token_index,
            segment_index=segment_index,
            segment=segment,
        )

        del bundle.tokens[token_index]
        del session.segments[segment_index]

        self.structural_undo_stack.append(
            StructuralAction(kind="delete", path=session.path, data=action)
        )
        self.structural_redo_stack.clear()

        self._refresh_dirty_state(session)
        self._render_session(session)
        self.statusBar().showMessage("Deleted dialogue block.")

    def _apply_undo_delete(self, action: DeletedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if action.bundle_index < 0 or action.bundle_index >= len(session.bundles):
            return False
        if self._find_segment_index_by_uid(session, action.uid) >= 0:
            return False

        bundle = session.bundles[action.bundle_index]
        token_index = max(0, min(action.token_index, len(bundle.tokens)))
        segment_index = max(0, min(action.segment_index, len(session.segments)))
        bundle.tokens.insert(token_index, CommandToken(kind="dialogue", segment=action.segment))
        session.segments.insert(segment_index, action.segment)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Undo delete: restored block in {action.path.name}")
        return True

    def _apply_undo_insert(self, action: InsertedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if self._find_segment_index_by_uid(session, action.uid) < 0:
            return False
        if not self._remove_segment_by_uid(session, action.uid):
            return False

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Undo insert: removed block in {action.path.name}")
        return True

    def _apply_redo_insert(self, action: InsertedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if action.bundle_index < 0 or action.bundle_index >= len(session.bundles):
            return False
        if self._find_segment_index_by_uid(session, action.uid) >= 0:
            return False

        bundle = session.bundles[action.bundle_index]
        token_index = max(0, min(action.token_index, len(bundle.tokens)))
        segment_index = max(0, min(action.segment_index, len(session.segments)))
        bundle.tokens.insert(token_index, CommandToken(kind="dialogue", segment=action.segment))
        session.segments.insert(segment_index, action.segment)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Redo insert: restored block in {action.path.name}")
        return True

    def _apply_redo_delete(self, action: DeletedBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if action.bundle_index < 0 or action.bundle_index >= len(session.bundles):
            return False

        bundle = session.bundles[action.bundle_index]
        token_index = self._find_bundle_token_index_by_uid(bundle, action.uid)
        segment_index = self._find_segment_index_by_uid(session, action.uid)
        if token_index < 0 or segment_index < 0:
            return False

        del bundle.tokens[token_index]
        del session.segments[segment_index]

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Redo delete: removed block in {action.path.name}")
        return True

    def _apply_undo_reset(self, action: ResetBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        segment_index = self._find_segment_index_by_uid(session, action.uid)
        if segment_index < 0:
            return False

        for restored in action.restored_segments:
            if self._find_segment_index_by_uid(session, restored.uid) < 0:
                return False
        for restored in action.restored_segments:
            if not self._remove_segment_by_uid(session, restored.uid):
                return False

        segment = session.segments[segment_index]
        segment.lines = list(action.lines_before)
        segment.source_lines = list(segment.lines)
        segment.merged_segments = list(action.merged_before)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Undo reset: restored pre-reset state in {action.path.name}")
        return True

    def _apply_redo_reset(self, action: ResetBlockAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        segment_index = self._find_segment_index_by_uid(session, action.uid)
        if segment_index < 0:
            return False
        for restored in action.restored_segments:
            if self._find_segment_index_by_uid(session, restored.uid) >= 0:
                return False

        restored_count = self._restore_merged_segments_after(session, action.uid, action.merged_before)
        if restored_count < len(action.merged_before):
            return False

        segment = session.segments[segment_index]
        segment.lines = list(action.lines_after)
        segment.source_lines = list(segment.lines)
        segment.merged_segments.clear()

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Redo reset: reapplied reset in {action.path.name}")
        return True

    def _apply_undo_split_overflow(self, action: SplitOverflowAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        source_index = self._find_segment_index_by_uid(session, action.source_uid)
        if source_index < 0:
            return False
        if self._find_segment_index_by_uid(session, action.moved_uid) < 0:
            return False
        if not self._remove_segment_by_uid(session, action.moved_uid):
            return False

        source_index = self._find_segment_index_by_uid(session, action.source_uid)
        if source_index < 0:
            return False
        source_segment = session.segments[source_index]
        source_segment.lines = list(action.source_lines_before)
        source_segment.source_lines = list(source_segment.lines)
        if action.source_translation_before:
            source_segment.translation_lines = self._normalize_translation_lines(action.source_translation_before)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.source_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Undo overflow split: restored block in {action.path.name}")
        return True

    def _apply_redo_split_overflow(self, action: SplitOverflowAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        if self._find_segment_index_by_uid(session, action.moved_uid) >= 0:
            return False

        source_index = self._find_segment_index_by_uid(session, action.source_uid)
        if source_index < 0:
            return False
        source_segment = session.segments[source_index]
        bundle, token_index = self._find_segment_token(session, action.source_uid)
        if bundle is None or token_index < 0:
            return False

        source_segment.lines = list(action.source_lines_after)
        source_segment.source_lines = list(source_segment.lines)
        if action.source_translation_after:
            source_segment.translation_lines = self._normalize_translation_lines(action.source_translation_after)
        bundle.tokens.insert(token_index + 1, CommandToken(kind="dialogue", segment=action.moved_segment))
        session.segments.insert(source_index + 1, action.moved_segment)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.moved_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Redo overflow split: moved lines in {action.path.name}")
        return True

    def _apply_undo_merge(self, action: MergeBlocksAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        left_index = self._find_segment_index_by_uid(session, action.left_uid)
        if left_index < 0:
            return False
        if self._find_segment_index_by_uid(session, action.right_uid) >= 0:
            return False

        left_segment = session.segments[left_index]
        restored = self._restore_merged_segments_after(session, action.left_uid, [action.right_segment])
        if restored <= 0:
            return False
        left_segment.lines = list(action.left_lines_before)
        left_segment.source_lines = list(left_segment.lines)
        if action.left_translation_before:
            left_segment.translation_lines = self._normalize_translation_lines(action.left_translation_before)
        left_segment.translation_speaker = action.left_speaker_translation_before
        if left_segment.translation_speaker:
            self.speaker_translation_map[left_segment.speaker_name] = left_segment.translation_speaker
        left_segment.merged_segments = list(action.left_merged_before)

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.left_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Undo merge: restored block in {action.path.name}")
        return True

    def _apply_redo_merge(self, action: MergeBlocksAction) -> bool:
        session = self.sessions.get(action.path)
        if session is None:
            return False
        left_index = self._find_segment_index_by_uid(session, action.left_uid)
        right_index = self._find_segment_index_by_uid(session, action.right_uid)
        if left_index < 0 or right_index < 0:
            return False
        if right_index != left_index + 1:
            return False

        left_segment = session.segments[left_index]
        right_segment = session.segments[right_index]
        left_bundle, left_token_index = self._find_segment_token(session, action.left_uid)
        right_bundle, right_token_index = self._find_segment_token(session, action.right_uid)
        if left_bundle is None or right_bundle is None:
            return False
        if left_bundle is not right_bundle:
            return False
        if right_token_index != left_token_index + 1:
            return False

        left_segment.lines = list(action.left_lines_after)
        left_segment.source_lines = list(left_segment.lines)
        if action.left_translation_after:
            left_segment.translation_lines = self._normalize_translation_lines(action.left_translation_after)
        left_segment.translation_speaker = action.left_speaker_translation_after
        if left_segment.translation_speaker:
            self.speaker_translation_map[left_segment.speaker_name] = left_segment.translation_speaker
        left_segment.merged_segments = list(action.left_merged_before) + [right_segment]
        del left_bundle.tokens[right_token_index]
        del session.segments[right_index]

        self._refresh_dirty_state(session)
        if self.current_path == action.path:
            self._render_session(session, focus_uid=action.left_uid, preserve_scroll=True)
        else:
            self._update_file_item_text(action.path)
        self.statusBar().showMessage(f"Redo merge: merged blocks in {action.path.name}")
        return True

    def _undo_last_structural_action(self) -> bool:
        while self.structural_undo_stack:
            action = self.structural_undo_stack.pop()
            ok = False
            if action.kind == "insert":
                ok = self._apply_undo_insert(cast(InsertedBlockAction, action.data))
            elif action.kind == "delete":
                ok = self._apply_undo_delete(cast(DeletedBlockAction, action.data))
            elif action.kind == "reset":
                ok = self._apply_undo_reset(cast(ResetBlockAction, action.data))
            elif action.kind == "split_overflow":
                ok = self._apply_undo_split_overflow(cast(SplitOverflowAction, action.data))
            elif action.kind == "merge":
                ok = self._apply_undo_merge(cast(MergeBlocksAction, action.data))
            if ok:
                self.structural_redo_stack.append(action)
                return True
        return False

    def _redo_last_structural_action(self) -> bool:
        while self.structural_redo_stack:
            action = self.structural_redo_stack.pop()
            ok = False
            if action.kind == "insert":
                ok = self._apply_redo_insert(cast(InsertedBlockAction, action.data))
            elif action.kind == "delete":
                ok = self._apply_redo_delete(cast(DeletedBlockAction, action.data))
            elif action.kind == "reset":
                ok = self._apply_redo_reset(cast(ResetBlockAction, action.data))
            elif action.kind == "split_overflow":
                ok = self._apply_redo_split_overflow(cast(SplitOverflowAction, action.data))
            elif action.kind == "merge":
                ok = self._apply_redo_merge(cast(MergeBlocksAction, action.data))
            if ok:
                self.structural_undo_stack.append(action)
                return True
        return False
