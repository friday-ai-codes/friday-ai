"""日志保留策略清理（LOG-08）：按天数 + 行数上限定时清理可观测落库表。

由 apscheduler ``purge_observability_logs_job`` 周期调用（daily），清理两张
append-only 表：

- ``SystemLogEntry``：按 ``LOG_RETENTION_DAYS`` 删旧（``ts``），再按
  ``LOG_RETENTION_SIZE`` 行数上限删最旧的超出部分；
- ``InboundWebhookEvent``：同款按 ``received_at`` 保留清理。

全部 **best-effort**（异常 warning，不抛），绝不反噬业务（沿用观测代码惯例）。
async ORM 直接用异步 manager 方法（``acount`` / ``adelete`` / ``async for``）。
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.utils import timezone

logger = structlog.get_logger(__name__)

# 默认保留策略（与 SettingKeys 注释一致）。
_DEFAULT_RETENTION_DAYS = 30
_DEFAULT_RETENTION_SIZE = 1_000_000

# 按行数清理时单次取待删 id 的安全上限，避免一次性 IN 列表过大。
_SIZE_DELETE_BATCH = 50_000


async def _retention_config() -> tuple[int, int]:
    """读保留天数 + 行数上限（settings_service，失败回默认）。"""
    from system.models import SettingKeys
    from system.settings_service import aget_int_setting

    days = await aget_int_setting(SettingKeys.LOG_RETENTION_DAYS, _DEFAULT_RETENTION_DAYS)
    size = await aget_int_setting(SettingKeys.LOG_RETENTION_SIZE, _DEFAULT_RETENTION_SIZE)
    return max(0, days), max(0, size)


async def purge_system_logs() -> dict[str, int]:
    """清理 ``SystemLogEntry``：先按天数删旧，再按行数上限删最旧的超出部分。

    返回 ``{"by_age": n1, "by_size": n2}``。best-effort：任何异常吞掉记 warning，
    返回已统计的部分结果，绝不反噬业务。
    """
    from system.models import SystemLogEntry

    by_age = 0
    by_size = 0
    try:
        days, size = await _retention_config()

        if days > 0:
            cutoff = timezone.now() - timedelta(days=days)
            deleted, _ = await SystemLogEntry.objects.filter(ts__lt=cutoff).adelete()
            by_age = deleted

        if size > 0:
            total = await SystemLogEntry.objects.acount()
            if total > size:
                excess = min(total - size, _SIZE_DELETE_BATCH)
                ids = [
                    pk
                    async for pk in SystemLogEntry.objects.order_by("ts").values_list(
                        "id", flat=True
                    )[:excess]
                ]
                if ids:
                    deleted, _ = await SystemLogEntry.objects.filter(id__in=ids).adelete()
                    by_size = deleted

        logger.info(
            "system_logs_purged",
            category="caller",
            component="log_retention",
            source="scheduler",
            by_age=by_age,
            by_size=by_size,
        )
    except Exception as exc:  # noqa: BLE001 — 保留清理 best-effort，绝不反噬业务
        logger.warning(
            "system_logs_purge_failed",
            category="caller",
            component="log_retention",
            error=str(exc),
        )
    return {"by_age": by_age, "by_size": by_size}


async def purge_webhook_events() -> dict[str, int]:
    """清理 ``InboundWebhookEvent``：同款按天数 + 行数上限保留清理（按 ``received_at``）。

    返回 ``{"by_age": n1, "by_size": n2}``。best-effort，绝不反噬业务。
    """
    from system.models import InboundWebhookEvent

    by_age = 0
    by_size = 0
    try:
        days, size = await _retention_config()

        if days > 0:
            cutoff = timezone.now() - timedelta(days=days)
            deleted, _ = await InboundWebhookEvent.objects.filter(
                received_at__lt=cutoff
            ).adelete()
            by_age = deleted

        if size > 0:
            total = await InboundWebhookEvent.objects.acount()
            if total > size:
                excess = min(total - size, _SIZE_DELETE_BATCH)
                ids = [
                    pk
                    async for pk in InboundWebhookEvent.objects.order_by(
                        "received_at"
                    ).values_list("id", flat=True)[:excess]
                ]
                if ids:
                    deleted, _ = await InboundWebhookEvent.objects.filter(
                        id__in=ids
                    ).adelete()
                    by_size = deleted

        logger.info(
            "webhook_events_purged",
            category="caller",
            component="log_retention",
            source="scheduler",
            by_age=by_age,
            by_size=by_size,
        )
    except Exception as exc:  # noqa: BLE001 — 保留清理 best-effort，绝不反噬业务
        logger.warning(
            "webhook_events_purge_failed",
            category="caller",
            component="log_retention",
            error=str(exc),
        )
    return {"by_age": by_age, "by_size": by_size}
