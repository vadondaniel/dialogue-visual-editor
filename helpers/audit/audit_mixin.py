from __future__ import annotations

from .audit_name_consistency_mixin import AuditNameConsistencyMixin
from .audit_consistency_mixin import AuditConsistencyMixin
from .audit_control_mismatch_mixin import AuditControlMismatchMixin
from .audit_core_mixin import AuditCoreMixin
from .audit_search_mixin import AuditSearchMixin
from .audit_sanitize_mixin import AuditSanitizeMixin
from .audit_term_usage_mixin import AuditTermUsageMixin
from .audit_window_mixin import AuditWindowMixin


class AuditMixin(
    AuditWindowMixin,
    AuditCoreMixin,
    AuditSanitizeMixin,
    AuditSearchMixin,
    AuditControlMismatchMixin,
    AuditConsistencyMixin,
    AuditTermUsageMixin,
    AuditNameConsistencyMixin,
):
    pass
