from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .audit_constants import SANITIZE_CHAR_RULES
from ..core.models import FileSession


class _AuditSanitizeHostTypingFallback:
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...


class AuditSanitizeWorkerMixin(_AuditSanitizeHostTypingFallback):
    def _sanitize_cache_generation(self) -> int:
        generation_resolver = getattr(self, "_audit_generation", None)
        if callable(generation_resolver):
            try:
                resolved = generation_resolver("sanitize")
            except Exception:
                resolved = None
            if isinstance(resolved, (int, float, str)):
                try:
                    return int(resolved)
                except Exception:
                    pass
        return int(getattr(self, "audit_cache_generation", 0))

    def _compute_audit_sanitize_payload_worker(
        self,
        path_sessions: list[tuple[Path, FileSession]],
        scope: str,
        selected_rule_id: str,
        selected_find_text: str,
        ignored_entries_by_rule: dict[str, set[tuple[str, str]]],
    ) -> dict[str, Any]:
        counts = {rule_id: 0 for rule_id, _label,
                  _find, _replace in SANITIZE_CHAR_RULES}
        records: list[dict[str, Any]] = []
        total_hits = 0
        entries = 0
        selected_ignored = ignored_entries_by_rule.get(selected_rule_id, set())

        for path, session in path_sessions:
            for idx, segment in enumerate(session.segments, start=1):
                entry_text = self._audit_entry_text_for_segment(
                    session, segment, idx)
                occurrences: list[dict[str, Any]] = []
                ignored_for_rule = (str(path), segment.uid) in selected_ignored
                if scope in ("original", "both"):
                    for line_index, line in enumerate((segment.lines or [""]), start=1):
                        for rule_id, _label, find_text, _replace in SANITIZE_CHAR_RULES:
                            hit_count = line.count(find_text)
                            if hit_count > 0:
                                counts[rule_id] += hit_count
                        if selected_find_text:
                            selected_hit_count = line.count(selected_find_text)
                            if selected_hit_count > 0:
                                occurrences.append(
                                    {
                                        "field_label": "OG",
                                        "line_index": line_index,
                                        "hit_count": selected_hit_count,
                                        "line_text": (line if line else "(empty)"),
                                        "ignored": ignored_for_rule,
                                    }
                                )
                                total_hits += selected_hit_count
                                entries += 1
                if scope in ("translation", "both"):
                    tl_lines = self._normalize_translation_lines(
                        segment.translation_lines)
                    for line_index, line in enumerate(tl_lines, start=1):
                        for rule_id, _label, find_text, _replace in SANITIZE_CHAR_RULES:
                            hit_count = line.count(find_text)
                            if hit_count > 0:
                                counts[rule_id] += hit_count
                        if selected_find_text:
                            selected_hit_count = line.count(selected_find_text)
                            if selected_hit_count > 0:
                                occurrences.append(
                                    {
                                        "field_label": "TL",
                                        "line_index": line_index,
                                        "hit_count": selected_hit_count,
                                        "line_text": (line if line else "(empty)"),
                                        "ignored": ignored_for_rule,
                                    }
                                )
                                total_hits += selected_hit_count
                                entries += 1
                if occurrences:
                    records.append(
                        {
                            "path": path,
                            "uid": segment.uid,
                            "entry_text": entry_text,
                            "occurrences": occurrences,
                        }
                    )

        return {
            "counts": counts,
            "records": records,
            "total_hits": total_hits,
            "entries": entries,
            "block_count": len(records),
        }

    def _compute_audit_sanitize_occurrences_worker(
        self,
        path_sessions: list[tuple[Path, FileSession]],
        scope: str,
        selected_find_text: str,
        selected_ignored: set[tuple[str, str]],
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        total_hits = 0
        entries = 0

        for path, session in path_sessions:
            for idx, segment in enumerate(session.segments, start=1):
                entry_text = self._audit_entry_text_for_segment(
                    session, segment, idx)
                occurrences: list[dict[str, Any]] = []
                ignored_for_rule = (str(path), segment.uid) in selected_ignored
                if scope in ("original", "both"):
                    for line_index, line in enumerate((segment.lines or [""]), start=1):
                        selected_hit_count = line.count(selected_find_text)
                        if selected_hit_count <= 0:
                            continue
                        occurrences.append(
                            {
                                "field_label": "OG",
                                "line_index": line_index,
                                "hit_count": selected_hit_count,
                                "line_text": (line if line else "(empty)"),
                                "ignored": ignored_for_rule,
                            }
                        )
                        total_hits += selected_hit_count
                        entries += 1
                if scope in ("translation", "both"):
                    tl_lines = self._normalize_translation_lines(
                        segment.translation_lines)
                    for line_index, line in enumerate(tl_lines, start=1):
                        selected_hit_count = line.count(selected_find_text)
                        if selected_hit_count <= 0:
                            continue
                        occurrences.append(
                            {
                                "field_label": "TL",
                                "line_index": line_index,
                                "hit_count": selected_hit_count,
                                "line_text": (line if line else "(empty)"),
                                "ignored": ignored_for_rule,
                            }
                        )
                        total_hits += selected_hit_count
                        entries += 1
                if occurrences:
                    records.append(
                        {
                            "path": path,
                            "uid": segment.uid,
                            "entry_text": entry_text,
                            "occurrences": occurrences,
                        }
                    )
        return {
            "records": records,
            "total_hits": total_hits,
            "entries": entries,
            "block_count": len(records),
        }

    def _queue_audit_sanitize_worker(self, request: dict[str, Any]) -> None:
        request_key = self._sanitize_request_key(request)
        if request_key == self._sanitize_request_key(self.audit_sanitize_worker_running_request):
            return
        if request_key == self._sanitize_request_key(self.audit_sanitize_worker_pending_request):
            return
        self.audit_sanitize_worker_pending_request = request
        if self.audit_sanitize_worker_future is None:
            self._start_next_audit_sanitize_worker()

    def _start_next_audit_sanitize_worker(self) -> None:
        request = self.audit_sanitize_worker_pending_request
        if request is None:
            return
        self.audit_sanitize_worker_pending_request = None
        self.audit_sanitize_worker_running_request = request
        try:
            mode = str(request.get("mode", "full"))
            if mode == "occurrences":
                self.audit_sanitize_worker_future = self.audit_worker_executor.submit(
                    self._compute_audit_sanitize_occurrences_worker,
                    cast(list[tuple[Path, FileSession]],
                         request["path_sessions"]),
                    str(request["scope"]),
                    str(request["selected_find_text"]),
                    cast(set[tuple[str, str]], request["selected_ignored"]),
                )
            else:
                self.audit_sanitize_worker_future = self.audit_worker_executor.submit(
                    self._compute_audit_sanitize_payload_worker,
                    cast(list[tuple[Path, FileSession]],
                         request["path_sessions"]),
                    str(request["scope"]),
                    str(request["selected_rule_id"]),
                    str(request["selected_find_text"]),
                    cast(dict[str, set[tuple[str, str]]],
                         request["ignored_entries_by_rule"]),
                )
        except Exception as exc:
            self.audit_sanitize_worker_future = None
            self.audit_sanitize_worker_running_request = None
            if self.audit_sanitize_summary_label is not None:
                self.audit_sanitize_summary_label.setText(
                    f"Sanitize scan failed: {exc}")
            return
        self.audit_sanitize_worker_timer.start(18)

    def _poll_audit_sanitize_worker(self) -> None:
        future = self.audit_sanitize_worker_future
        if future is None:
            if self.audit_sanitize_worker_pending_request is not None:
                self._start_next_audit_sanitize_worker()
            return
        if not future.done():
            self.audit_sanitize_worker_timer.start(18)
            return

        running_request = self.audit_sanitize_worker_running_request
        self.audit_sanitize_worker_future = None
        self.audit_sanitize_worker_running_request = None
        try:
            payload = cast(dict[str, Any], future.result())
        except Exception as exc:
            if self.audit_sanitize_worker_pending_request is not None:
                self._start_next_audit_sanitize_worker()
                return
            if self.audit_sanitize_summary_label is not None:
                self.audit_sanitize_summary_label.setText(
                    f"Sanitize scan failed: {exc}")
            return

        if self.audit_sanitize_worker_pending_request is not None:
            self._start_next_audit_sanitize_worker()
            return
        if not isinstance(running_request, dict):
            return
        if (
            self.audit_sanitize_rules_list is None
            or self.audit_sanitize_summary_label is None
            or self.audit_sanitize_occurrences_list is None
            or self.audit_sanitize_goto_btn is None
        ):
            return

        mode = str(running_request.get("mode", "full"))
        generation = int(running_request.get("generation", -1))
        scope = str(running_request.get("scope", "original"))
        selected_rule_id = str(running_request.get("selected_rule_id", ""))
        selected_find_text = str(running_request.get("selected_find_text", ""))
        if generation != self._sanitize_cache_generation():
            return
        if self._audit_sanitize_scope() != scope:
            return
        current_payload = self._audit_sanitize_rule_payload(
            self.audit_sanitize_rules_list.currentItem()
        )
        current_rule_id = current_payload["rule_id"] if current_payload is not None else ""
        current_find_text = current_payload["find_text"] if current_payload is not None else ""
        if current_rule_id != selected_rule_id or current_find_text != selected_find_text:
            return
        if mode == "occurrences":
            counts_payload = dict(self.audit_sanitize_counts_cache)
            if self.audit_sanitize_counts_cache_key != (generation, scope):
                counts_payload = {rule_id: 0 for rule_id,
                                  _label, _find, _replace in SANITIZE_CHAR_RULES}
            merged_payload: dict[str, Any] = {"counts": counts_payload}
            merged_payload.update(payload)
            payload = merged_payload
        self._apply_audit_sanitize_payload(
            generation=generation,
            scope=scope,
            selected_rule_id=selected_rule_id,
            selected_find_text=selected_find_text,
            payload=payload,
        )
