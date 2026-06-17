"""audit models package — curated re-export（对齐 delivery 范式）。"""

from audit.models.audit_event import AuditEvent, AuditEventImmutableError

__all__ = [
    "AuditEvent",
    "AuditEventImmutableError",
]
