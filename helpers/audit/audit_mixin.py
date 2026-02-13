from __future__ import annotations

from .audit_consistency_mixin import AuditConsistencyMixin
from .audit_control_mismatch_mixin import AuditControlMismatchMixin
from .audit_core_mixin import AuditCoreMixin
from .audit_search_mixin import AuditSearchMixin
from .audit_sanitize_mixin import AuditSanitizeMixin
from .audit_window_mixin import AuditWindowMixin


class AuditMixin(
    AuditWindowMixin,
    AuditCoreMixin,
    AuditSanitizeMixin,
    AuditSearchMixin,
    AuditControlMismatchMixin,
    AuditConsistencyMixin,
):
    pass
