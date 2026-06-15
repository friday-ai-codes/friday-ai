"""审计事件 emit 双入口（同步/异步） -- 统一的 AuditEvent 写入接口。

沿用 ``interactions/ledger.py`` 的模式：

- 同步核心实现 ``emit_audit_event`` —— 直接 ORM 写入
- 异步包装 ``aemit_audit_event`` —— ``sync_to_async`` bridge，供 adrf 异步视图调用
- best-effort：写库失败降级为 structlog warning，返回 None，不阻塞主请求
- actor 信息从 contextvars 读取（中间件已设置），显式参数可覆盖
"""

from __future__ import annotations

from typing import Any

import structlog
from asgiref.sync import sync_to_async

from .context import get_current_actor
from .models import AuditEvent

logger = structlog.get_logger("audit")

__all__ = ["emit_audit_event", "aemit_audit_event"]


def emit_audit_event(
    *,
    action: str,
    target_type: str,
    target_id: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    source: str = "",
    extra: dict[str, Any] | None = None,
    # 可选：显式覆盖 contextvars 中的 actor（management command 等系统操作）
    actor_type: str = "",
    actor_id: str = "",
    actor_display: str = "",
    ip_address: str | None = None,
    request_id: str = "",
    user_agent: str = "",
) -> AuditEvent | None:
    """写入一条 AuditEvent（同步入口）。

    actor 信息来源优先级：
    1. 显式传入的 actor_type / actor_id / actor_display
    2. contextvars 中的 ``get_current_actor()``
    3. 兜底为 system 默认值

    写库失败时降级为 structlog warning，返回 None（best-effort）。
    """
    # 从 contextvars 获取默认 actor
    ctx_actor = get_current_actor()

    # 合并：显式参数覆盖 contextvars
    final_actor_type = actor_type or ctx_actor.actor_type
    final_actor_id = actor_id or ctx_actor.actor_id
    final_actor_display = actor_display or ctx_actor.actor_display
    final_ip = ip_address if ip_address is not None else ctx_actor.ip_address
    final_request_id = request_id or ctx_actor.request_id

    # source 推断：有 request_id 意味着来自 API 请求
    if not source:
        source = AuditEvent.Source.API if final_request_id else AuditEvent.Source.SYSTEM

    try:
        event = AuditEvent.objects.create(
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before or {},
            after=after or {},
            source=source,
            actor_type=final_actor_type,
            actor_display=final_actor_display,
            ip_address=final_ip,
            user_agent=user_agent,
        )
        logger.debug("audit_event_emitted", action=action, event_id=str(event.pk))
        return event
    except Exception:
        logger.warning(
            "audit_emit_failed",
            action=action,
            target_type=target_type,
            target_id=target_id,
            exc_info=True,
        )
        return None


async def aemit_audit_event(
    *,
    action: str,
    target_type: str,
    target_id: str = "",
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    source: str = "",
    extra: dict[str, Any] | None = None,
    actor_type: str = "",
    actor_id: str = "",
    actor_display: str = "",
    ip_address: str | None = None,
    request_id: str = "",
    user_agent: str = "",
) -> AuditEvent | None:
    """emit_audit_event 的异步包装（adrf 异步视图调用）。

    内部 ``sync_to_async`` 包装同步实现，与 ``interactions/ledger.py`` 异步入口模式一致。
    """
    return await sync_to_async(emit_audit_event)(
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        source=source,
        extra=extra,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_display=actor_display,
        ip_address=ip_address,
        request_id=request_id,
        user_agent=user_agent,
    )
