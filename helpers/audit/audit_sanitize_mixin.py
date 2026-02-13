from __future__ import annotations

from .audit_sanitize_apply_mixin import AuditSanitizeApplyMixin
from .audit_sanitize_ui_mixin import AuditSanitizeUiMixin
from .audit_sanitize_worker_mixin import AuditSanitizeWorkerMixin


class AuditSanitizeMixin(
    AuditSanitizeUiMixin,
    AuditSanitizeWorkerMixin,
    AuditSanitizeApplyMixin,
):
    pass
