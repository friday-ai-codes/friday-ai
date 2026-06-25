"""metric_retention（RATE-03 保留治理）守护测试。

覆盖：
- GaugeSample 按 ts 删旧留新（by_age）；
- RequestMetric 按行数上限删最旧超出部分（by_size）；
- ModelUsageRecord 按 created_at 删旧（断言不抛 FieldError、删对行）；
- adelete 抛错 → wrapper 返回部分结果不冒泡（best-effort）。

async 写测试用 ``transaction=True``（async ORM 写不跨连接泄漏，per 73-CONTEXT）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from interactions.models import ModelUsageRecord
from system import metric_retention
from system.models import GaugeSample, RequestMetric


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_purge_gauge_samples_by_age(monkeypatch: pytest.MonkeyPatch) -> None:
    """造跨保留期的 GaugeSample（旧行 ts < cutoff + 新行）→ 删旧留新、by_age 正确。"""

    async def _cfg() -> tuple[int, int]:
        return 30, 1_000_000

    monkeypatch.setattr(metric_retention, "_metric_retention_config", _cfg)

    now = timezone.now()
    old_ts = now - timedelta(days=45)
    # 2 旧行 + 1 新行。
    await GaugeSample.objects.acreate(ts=old_ts, name="queue.durable_todo", value=1.0)
    await GaugeSample.objects.acreate(ts=old_ts, name="queue.durable_doing", value=2.0)
    fresh = await GaugeSample.objects.acreate(ts=now, name="queue.durable_todo", value=3.0)

    result = await metric_retention.purge_gauge_samples()
    assert result["by_age"] == 2

    remaining = [pk async for pk in GaugeSample.objects.values_list("id", flat=True)]
    assert remaining == [fresh.id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_purge_request_metrics_by_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """造超过 size 上限的 RequestMetric → by_size 删最旧超出部分。"""

    async def _cfg() -> tuple[int, int]:
        # days=0 关闭按龄清理，只测按量；size=2 上限。
        return 0, 2

    monkeypatch.setattr(metric_retention, "_metric_retention_config", _cfg)

    now = timezone.now()
    # 4 行，ts 递增；上限 2 → 删最旧 2 行。
    rows = []
    for i in range(4):
        r = await RequestMetric.objects.acreate(
            ts=now - timedelta(minutes=10 - i), source="rest", route="/x"
        )
        rows.append(r)

    result = await metric_retention.purge_request_metrics()
    assert result["by_age"] == 0
    assert result["by_size"] == 2

    remaining = {pk async for pk in RequestMetric.objects.values_list("id", flat=True)}
    # 保留最新的 2 行（rows[2], rows[3]）。
    assert remaining == {rows[2].id, rows[3].id}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_purge_model_usage_records_by_created_at(monkeypatch: pytest.MonkeyPatch) -> None:
    """ModelUsageRecord 按 created_at 删旧（不抛 FieldError、删对行）。

    ``created_at`` 为 ``auto_now_add`` 不可直接赋值，故创建后用 update 回填旧时间。
    """

    async def _cfg() -> tuple[int, int]:
        return 30, 1_000_000

    monkeypatch.setattr(metric_retention, "_metric_retention_config", _cfg)

    now = timezone.now()
    old = await ModelUsageRecord.objects.acreate(provider="anthropic", model="claude")
    fresh = await ModelUsageRecord.objects.acreate(provider="openai", model="gpt")
    # 回填旧行 created_at 到保留期外。
    await ModelUsageRecord.objects.filter(id=old.id).aupdate(
        created_at=now - timedelta(days=45)
    )

    result = await metric_retention.purge_model_usage_records()
    assert result["by_age"] == 1

    remaining = [pk async for pk in ModelUsageRecord.objects.values_list("id", flat=True)]
    assert remaining == [fresh.id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_purge_swallows_adelete_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """adelete 抛错 → wrapper 返回部分结果不冒泡（best-effort）。"""
    from django.db.models.query import QuerySet

    async def _cfg() -> tuple[int, int]:
        return 30, 1_000_000

    monkeypatch.setattr(metric_retention, "_metric_retention_config", _cfg)

    async def _boom(self):
        raise RuntimeError("adelete down")

    monkeypatch.setattr(QuerySet, "adelete", _boom)

    # 不应抛出，返回部分结果。
    result = await metric_retention.purge_gauge_samples()
    assert result == {"by_age": 0, "by_size": 0}
