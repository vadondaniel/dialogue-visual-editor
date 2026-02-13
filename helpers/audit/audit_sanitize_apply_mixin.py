from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from ..core.models import DialogueSegment, FileSession


class _AuditSanitizeHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditSanitizeApplyMixin(_AuditSanitizeHostTypingFallback):
    def _apply_audit_sanitize_rule_to_entry(
        self,
        rule: dict[str, str],
        path_raw: str,
        uid: str,
    ) -> None:
        path = Path(path_raw)
        session = self.sessions.get(path)
        if session is None:
            self.statusBar().showMessage(f"Entry not loaded: {path.name}.")
            return
        target_segment: Optional[DialogueSegment] = None
        for segment in session.segments:
            if segment.uid == uid:
                target_segment = segment
                break
        if target_segment is None:
            self.statusBar().showMessage("Entry no longer exists.")
            return
        rule_id = rule.get("rule_id", "")
        if self._is_audit_sanitize_entry_ignored(rule_id, str(path), uid):
            self.statusBar().showMessage("Entry is ignored for this rule.")
            return

        scope = self._audit_sanitize_scope()
        replacements = 0
        changed = False
        if scope in ("original", "both"):
            original_lines = list(target_segment.lines) if target_segment.lines else [""]
            replaced_lines, replaced_count = self._apply_sanitize_rules_to_lines(
                original_lines,
                [rule],
            )
            if replaced_count > 0 and replaced_lines != original_lines:
                target_segment.lines = list(replaced_lines)
                target_segment.source_lines = list(replaced_lines)
                replacements += replaced_count
                changed = True
        if scope in ("translation", "both"):
            translation_lines = self._normalize_translation_lines(target_segment.translation_lines)
            replaced_lines, replaced_count = self._apply_sanitize_rules_to_lines(
                translation_lines,
                [rule],
            )
            if replaced_count > 0 and replaced_lines != translation_lines:
                target_segment.translation_lines = list(replaced_lines)
                replacements += replaced_count
                changed = True

        if not changed:
            self.statusBar().showMessage("No replacements applied for selected entry.")
            return

        self._refresh_dirty_state(session)
        if self.current_path == path:
            self._render_session(
                session,
                focus_uid=uid,
                preserve_scroll=True,
            )
        else:
            self._refresh_translator_detail_panel()
        self._invalidate_audit_caches()
        self._refresh_audit_sanitize_panel()
        self._refresh_audit_control_mismatch_panel()
        self.statusBar().showMessage(
            f"Applied sanitize rule to entry: {replacements} replacement(s)."
        )

    def _apply_sanitize_rules_to_lines(
        self,
        source_lines: list[str],
        rules: list[dict[str, str]],
    ) -> tuple[list[str], int]:
        updated_lines = list(source_lines) if source_lines else [""]
        replacements = 0
        for rule in rules:
            find_text = rule["find_text"]
            replace_text = rule["replace_text"]
            if not find_text:
                continue
            for idx, line in enumerate(updated_lines):
                hit_count = line.count(find_text)
                if hit_count <= 0:
                    continue
                updated_lines[idx] = line.replace(find_text, replace_text)
                replacements += hit_count
        return updated_lines, replacements

    def _apply_audit_sanitize_rules(self, rules: list[dict[str, str]]) -> None:
        if not rules:
            self.statusBar().showMessage("No sanitize rules selected.")
            return
        if not self.sessions:
            self.statusBar().showMessage("No data loaded.")
            return
        active_rules = list(rules)

        scope = self._audit_sanitize_scope()
        touched_sessions: list[FileSession] = []
        changed_segments = 0
        total_replacements = 0

        for path in self.file_paths:
            session = self.sessions.get(path)
            if session is None:
                continue
            session_changed = False
            for segment in session.segments:
                segment_changed = False
                segment_rules = [
                    rule for rule in active_rules
                    if not self._is_audit_sanitize_entry_ignored(
                        str(rule.get("rule_id", "")),
                        str(path),
                        segment.uid,
                    )
                ]
                if not segment_rules:
                    continue
                if scope in ("original", "both"):
                    original_lines = list(segment.lines) if segment.lines else [""]
                    replaced_lines, replaced_count = self._apply_sanitize_rules_to_lines(
                        original_lines,
                        segment_rules,
                    )
                    if replaced_count > 0 and replaced_lines != original_lines:
                        segment.lines = list(replaced_lines)
                        segment.source_lines = list(replaced_lines)
                        total_replacements += replaced_count
                        segment_changed = True
                if scope in ("translation", "both"):
                    translation_lines = self._normalize_translation_lines(segment.translation_lines)
                    replaced_lines, replaced_count = self._apply_sanitize_rules_to_lines(
                        translation_lines,
                        segment_rules,
                    )
                    if replaced_count > 0 and replaced_lines != translation_lines:
                        segment.translation_lines = list(replaced_lines)
                        total_replacements += replaced_count
                        segment_changed = True
                if segment_changed:
                    changed_segments += 1
                    session_changed = True
            if session_changed:
                touched_sessions.append(session)
                self._refresh_dirty_state(session)

        if not touched_sessions:
            self.statusBar().showMessage("No replacements applied.")
            self._refresh_audit_sanitize_panel()
            self._refresh_audit_control_mismatch_panel()
            return

        if self.current_path is not None:
            current_session = self.sessions.get(self.current_path)
            if current_session is not None and current_session in touched_sessions:
                self._render_session(
                    current_session,
                    focus_uid=self.selected_segment_uid,
                    preserve_scroll=True,
                )
            else:
                self._refresh_translator_detail_panel()
        else:
            self._refresh_translator_detail_panel()

        self._invalidate_audit_caches()
        self._refresh_audit_sanitize_panel()
        self._refresh_audit_control_mismatch_panel()
        self.statusBar().showMessage(
            f"Applied sanitize rules: {total_replacements} replacement(s) in {changed_segments} segment(s)."
        )

    def _apply_selected_audit_sanitize_rule(self) -> None:
        if self.audit_sanitize_rules_list is None:
            return
        payload = self._audit_sanitize_rule_payload(
            self.audit_sanitize_rules_list.currentItem()
        )
        if payload is None:
            self.statusBar().showMessage("Select a sanitize rule first.")
            return
        self._apply_audit_sanitize_rules([payload])

