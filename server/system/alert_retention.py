"""告警事件保留策略清理（ALERT-02）：按天数 + 行数上限定时清理 ``AlertEvent``。

镜像 Phase 71 ``log_retention``（按天数删旧 + 按行数上限删最旧超出部分），但时间列
换为 ``started_at``（AlertEvent 的事件时间列），**绝不**用 ts/created_at 删错列。

apscheduler 注册**不在本 plan**（在 74-02 与 ``evaluate_system_alerts`` 同处注册，
避免本 plan 与 74-02 抢 runapscheduler.py）；本 plan 仅提供清理函数。

全部 **best-effort**（异常 warning，不抛），绝不反噬业务（沿用观测代码惯例）。
async ORM 直接用异步 manager 方法（``acount`` / ``adelete`` / ``async for``）。

> 注：恢复已久的 resolved 事件与极老 firing 一并按 started_at 清理（量级低；如需保留
> 活跃 firing 可在 v2 加 status 过滤，本 phase 不做，避免过度设计）。
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.utils import timezone

logger = structlog.get_logger(__name__)

# 默认保留策略（与 SettingKeys.ALERT_RETENTION_* 注释一致；告警低频，保留略长）。
_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_RETENTION_SIZE = 500_000

# 按行数清理时单次取待删 id 的安全上限，避免一次性 IN 列表过大（T-74-01-05）。
_SIZE_DELETE_BATCH = 50_000


async def _alert_retention_config() -> tuple[int, int]:
    """读告警事件保留天数 + 行数上限（settings_service，失败回默认）。"""
    from system.models import SettingKeys
    from system.settings_service import aget_int_setting

    days = await aget_int_setting(SettingKeys.ALERT_RETENTION_DAYS, _DEFAULT_RETENTION_DAYS)
    size = await aget_int_setting(SettingKeys.ALERT_RETENTION_SIZE, _DEFAULT_RETENTION_SIZE)
    return max(0, days), max(0, size)


async def purge_alert_events() -> dict[str, int]:
    """清理 ``AlertEvent``：先按 ``started_at`` 天数删旧，再按行数上限删最旧超出部分。

    返回 ``{"by_age": n1, "by_size": n2}``。best-effort：任何异常吞掉记 warning，
    返回已统计的部分结果，绝不反噬业务。
    """
    from system.models import AlertEvent

    by_age = 0
    by_size = 0
    try:
        days, size = await _alert_retention_config()

        if days > 0:
            # 按 started_at（AlertEvent 事件时间列）删旧——绝不用 ts/created_at。
            cutoff = timezone.now() - timedelta(days=days)
            deleted, _ = await AlertEvent.objects.filter(started_at__lt=cutoff).adelete()
            by_age = deleted

        if size > 0:
            total = await AlertEvent.objects.acount()
            if total > size:
                excess = min(total - size, _SIZE_DELETE_BATCH)
                ids = [
                    pk
                    async for pk in AlertEvent.objects.order_by("started_at").values_list(
                        "id", flat=True
                    )[:excess]
                ]
                if ids:
                    deleted, _ = await AlertEvent.objects.filter(id__in=ids).adelete()
                    by_size = deleted

        logger.info(
            "alert_events_purged",
            category="caller",
            component="alert_retention",
            source="scheduler",
            by_age=by_age,
            by_size=by_size,
        )
    except Exception as exc:  # noqa: BLE001 — 保留清理 best-effort，绝不反噬业务
        logger.warning(
            "alert_events_purge_failed",
            category="caller",
            component="alert_retention",
            error=str(exc),
        )
    return {"by_age": by_age, "by_size": by_size}
