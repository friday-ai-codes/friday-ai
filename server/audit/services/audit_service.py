"""AuditService：AuditEvent 单一写入入口（AUDIT-01 / AUDIT-02）。

所有 ``AuditEvent`` 落库只允许经本 service（INV-6 单一写入入口）：提供同步面
``emit`` 与异步面 ``aemit``（``sync_to_async`` 桥接 ORM），收口于唯一
``AuditEvent.objects.create``。三项地基不变量：

1. **单一写入入口（INV-6）**：除本模块外无旁路写表（源码层 grep 守护兜底）。
2. **入口强制脱敏（AUDIT-02）**：``before`` / ``after`` / ``metadata`` 经
   ``_redact_audit_payload`` 兜底，调用方传明文也绝不落明文（脱敏在入口内强制，
   调用方无法绕过）。
3. **fail-soft（AUDIT-02）**：``emit`` 整段 try/except 吞异常 + ``audit.emit_failed``
   warning，绝不冒泡阻断主操作；warning 仅记 action/target_type，不记敏感载荷。

async 安全：actor 字段访问（``actor.id`` / ``actor.username``）全在
``sync_to_async(emit)`` 同步块内发生（``aemit`` 委托 ``emit``），规避 async 裸访问
lazy-FK（per RESEARCH §6）。
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

from audit.models import AuditEvent
from audit.services.redaction import _redact_audit_payload

logger = structlog.get_logger(__name__)


def _actor_id(actor: Any) -> uuid.UUID | None:
    """从 actor 取标量 id（None → None）。仅在 sync 块内调用（async 安全）。"""
    if actor is None:
        return None
    return getattr(actor, "id", None)


def _actor_repr(actor: Any) -> str:
    """构造 actor 人类可读快照（如 "zhangsan (superuser)"）。仅在 sync 块内调用。

    缺 username 字段时容错降级为 ``str(actor)``；actor 为 None → 空串。
    """
    if actor is None:
        return ""
    username = getattr(actor, "username", None)
    if username is None:
        return str(actor)
    repr_text = str(username)
    if getattr(actor, "is_superuser", False):
        repr_text += " (superuser)"
    return repr_text


class AuditService:
    """AuditEvent 唯一写入入口（INV-6）+ 强制脱敏 + fail-soft。"""

    @staticmethod
    def emit(
        *,
        action: str,
        actor: Any = None,
        target_type: str = "",
        target_id: Any = "",
        target_repr: str = "",
        before: Any = None,
        after: Any = None,
        source: str = "",
        occurred_at: Any = None,
        metadata: Any = None,
    ) -> None:
        """同步单一写入入口：落一行 AuditEvent，强制脱敏 + fail-soft。

        脱敏在入口内强制（调用方无法绕过）：``before`` / ``after`` / ``metadata`` 经
        ``_redact_audit_payload`` 兜底。fail-soft：整段 try/except 吞异常 + warning，
        绝不冒泡阻断主操作。

        事务边界：建议调用方在**主操作成功后**调用（如 ``transaction.on_commit``），
        避免 emit 与主操作同事务回滚——具体由 Phase 54 各调用方按场景处理。
        """
        try:
            AuditEvent.objects.create(
                actor_id=_actor_id(actor),
                actor_repr=_actor_repr(actor),
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id != "" else "",
                target_repr=target_repr,
                before=_redact_audit_payload(before or {}),
                after=_redact_audit_payload(after or {}),
                source=source,
                occurred_at=occurred_at or timezone.now(),
                metadata=_redact_audit_payload(metadata or {}),
            )
        except Exception:  # noqa: BLE001 — fail-soft，绝不冒泡阻断主操作；不记敏感载荷
            logger.warning("audit.emit_failed", action=action, target_type=target_type)

    @staticmethod
    async def aemit(**kwargs: Any) -> None:
        """异步面：``sync_to_async`` 桥接 ORM（adrf/channels 调用方用）。

        actor 字段访问全在 ``sync_to_async(emit)`` 同步块内发生（async 安全）。
        """
        await sync_to_async(AuditService.emit)(**kwargs)
