"""指标表保留清理（RATE-03 保留治理）——镜像 Phase 71 ``log_retention`` 的按天数 +
行数上限清理，扩到三张指标表。

由 apscheduler ``purge_metrics_job``（daily）周期调用，清理三张 append-only 指标表：

- ``GaugeSample``：按 ``ts`` 删旧 + 行数上限；
- ``RequestMetric``：按 ``ts`` 删旧 + 行数上限；
- ``ModelUsageRecord``：**按 ``created_at``**（非 ``ts``——本表时间列是 ``created_at``，
  按 ``ts`` 会 ``FieldError``）删旧 + 行数上限。

全部 **best-effort**（异常 warning，不抛），绝不反噬业务。async ORM 直接用异步
manager 方法（``acount`` / ``adelete`` / ``async for``）。

MetricDailyRollup 占位说明：本 Phase **不建 rollup 模型 / 迁移**——指标量级低，原始行 +
73-02 ``percentile_cont`` 精确分位已足够覆盖长区间趋势（per 73-CONTEXT「倾向只落保留
清理 + 留 rollup 占位」/ MILESTONE-PROPOSAL §C「可选/按需」）。rollup 为后续 v2 可选项，
此处刻意不引入未消费的空表。
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.utils import timezone

logger = structlog.get_logger(__name__)

# 默认保留策略（与 SettingKeys.METRIC_* 注释一致）。
_DEFAULT_RETENTION_DAYS = 30
# 指标比日志高频，单表行数上限略放宽。
_DEFAULT_RETENTION_SIZE = 2_000_000

# 按行数清理时单次取待删 id 的安全上限，避免一次性 IN 列表过大（镜像 log_retention）。
_SIZE_DELETE_BATCH = 50_000


async def _metric_retention_config() -> tuple[int, int]:
    """读指标保留天数 + 行数上限（settings_service，失败回默认）。

    逐字镜像 ``log_retention._retention_config``，仅换 key + 默认值。
    """
    from system.models import SettingKeys
    from system.settings_service import aget_int_setting

    days = await aget_int_setting(SettingKeys.METRIC_RETENTION_DAYS, _DEFAULT_RETENTION_DAYS)
    size = await aget_int_setting(SettingKeys.METRIC_RETENTION_SIZE, _DEFAULT_RETENTION_SIZE)
    return max(0, days), max(0, size)


async def _purge_table(model, time_field: str, label: str) -> dict[str, int]:
    """按天数 + 行数上限清理单张指标表（抽公共逻辑，避免三份复制）。

    ``time_field`` 为各 wrapper 传入的**白名单字面量**（``ts`` / ``created_at``），
    **非用户输入**——绝不删错列。先按天数删 ``{time_field}__lt cutoff``；再按行数上限
    取最旧的超出部分（单批不超 ``_SIZE_DELETE_BATCH``）删除。整段 ``try/except``
    best-effort（异常 warning ``<label>_purge_failed``，返回已统计部分）。

    返回 ``{"by_age": n1, "by_size": n2}``。
    """
    by_age = 0
    by_size = 0
    try:
        days, size = await _metric_retention_config()

        if days > 0:
            cutoff = timezone.now() - timedelta(days=days)
            deleted, _ = await model.objects.filter(**{f"{time_field}__lt": cutoff}).adelete()
            by_age = deleted

        if size > 0:
            total = await model.objects.acount()
            if total > size:
                excess = min(total - size, _SIZE_DELETE_BATCH)
                ids = [
                    pk
                    async for pk in model.objects.order_by(time_field).values_list(
                        "id", flat=True
                    )[:excess]
                ]
                if ids:
                    deleted, _ = await model.objects.filter(id__in=ids).adelete()
                    by_size = deleted
    except Exception as exc:  # noqa: BLE001 — 保留清理 best-effort，绝不反噬业务
        logger.warning(
            f"{label}_purge_failed",
            category="caller",
            component="metric_retention",
            error=str(exc),
        )
    return {"by_age": by_age, "by_size": by_size}


async def purge_gauge_samples() -> dict[str, int]:
    """清理 ``GaugeSample``：按 ``ts`` 删旧 + 行数上限。best-effort。"""
    from system.models import GaugeSample

    result = await _purge_table(GaugeSample, "ts", "gauge_samples")
    logger.info(
        "gauge_samples_purged",
        category="caller",
        component="metric_retention",
        source="scheduler",
        by_age=result["by_age"],
        by_size=result["by_size"],
    )
    return result


async def purge_request_metrics() -> dict[str, int]:
    """清理 ``RequestMetric``：按 ``ts`` 删旧 + 行数上限。best-effort。"""
    from system.models import RequestMetric

    result = await _purge_table(RequestMetric, "ts", "request_metrics")
    logger.info(
        "request_metrics_purged",
        category="caller",
        component="metric_retention",
        source="scheduler",
        by_age=result["by_age"],
        by_size=result["by_size"],
    )
    return result


async def purge_model_usage_records() -> dict[str, int]:
    """清理 ``ModelUsageRecord``：**按 ``created_at``**（非 ``ts``）删旧 + 行数上限。

    口径差异（关键，绝不删错列）：``ModelUsageRecord`` 时间列是 ``created_at``
    （``auto_now_add``），本表无 ``ts`` 字段——按 ``ts`` 清理会 ``FieldError``。
    best-effort。
    """
    from interactions.models import ModelUsageRecord

    result = await _purge_table(ModelUsageRecord, "created_at", "model_usage_records")
    logger.info(
        "model_usage_records_purged",
        category="caller",
        component="metric_retention",
        source="scheduler",
        by_age=result["by_age"],
        by_size=result["by_size"],
    )
    return result
