"""metric_sampling（RATE-03 采样侧）守护测试。

覆盖：
- 并发/积压快照拍平成受控 name 的 GaugeSample 行（value 正确、labels 仅受控键无密钥）；
- 源 available=False 不落噪声行；
- 采集器抛错 → sample_gauges 降级 written=0 不冒泡（best-effort）；
- sample_gauges_job / purge_metrics_job wrapper 接线 + 失败不打断 scheduler。

async 写测试用 ``transaction=True``（async ORM 写不跨连接泄漏，per 73-CONTEXT）。
"""

from __future__ import annotations

from typing import Any

import pytest

from system import metric_sampling
from system.models import GaugeSample


def _concurrency_payload() -> dict[str, Any]:
    return {
        "available": True,
        "error": "",
        "provider_slots": [
            {"credential_id": "cred-uuid-1", "provider": "anthropic", "max": 50, "in_use": 2},
            {"credential_id": "cred-uuid-2", "provider": "openai", "max": 10, "in_use": None},
        ],
        "durable_queues": {
            "by_queue_status": [
                {"queue": "default", "status": "todo", "count": 3},
                {"queue": "default", "status": "doing", "count": 1},
                {"queue": "default", "status": "succeeded", "count": 99},
            ],
            "totals": {"todo": 3, "doing": 1, "succeeded": 99},
        },
        "runner": {
            "assignments_by_status": {"assigned": 4, "running": 2},
            "current_tasks": 2,
            "capacity": 8,
            "active_runners": 1,
        },
        "rag": {"available": False, "error": "n/a"},
    }


def _host_payload() -> dict[str, Any]:
    return {
        "available": True,
        "error": "",
        "cpu_percent": 1.0,
        "background_tasks": {
            "durable_active": 4,
            "durable_total": 103,
            "subagent_active": 5,
            "orchestration_active": 1,
            "total_active": 10,
        },
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sample_gauges_flattens_controlled_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider 槽位 / durable / runner / 积压拍平成受控 name 行，labels 仅受控键无密钥。"""
    # sample_gauges 内 ``from system.snapshot_service import ...`` 为函数级，patch 源模块。
    monkeypatch.setattr(
        "system.snapshot_service.collect_concurrency_snapshot", _async(_concurrency_payload())
    )
    monkeypatch.setattr(
        "system.snapshot_service.collect_host_snapshot", _async(_host_payload())
    )

    result = await metric_sampling.sample_gauges()
    assert result["written"] > 0

    names = {name async for name in GaugeSample.objects.values_list("name", flat=True)}
    assert "concurrency.provider_slots" in names
    assert "queue.durable_todo" in names
    assert "queue.durable_doing" in names
    assert "queue.runner_pending" in names
    assert "queue.runner_local" in names
    assert "backlog.subagent_active" in names
    assert "backlog.background_tasks" in names

    # provider 槽位：in_use=2 落库，in_use=None 凭证跳过（不臆造）。
    provider_rows = [
        r async for r in GaugeSample.objects.filter(name="concurrency.provider_slots")
    ]
    assert len(provider_rows) == 1
    row = provider_rows[0]
    assert row.value == 2.0
    assert set(row.labels.keys()) == {"credential", "provider"}
    assert row.labels["credential"] == "cred-uuid-1"
    assert row.labels["provider"] == "anthropic"

    # durable todo=3 / doing=1，succeeded 不落趋势行。
    todo = await GaugeSample.objects.aget(name="queue.durable_todo")
    assert todo.value == 3.0
    assert todo.labels == {"queue": "default"}
    doing = await GaugeSample.objects.aget(name="queue.durable_doing")
    assert doing.value == 1.0

    # runner_pending = assigned(4)，runner_local = current_tasks(2)。
    pending = await GaugeSample.objects.aget(name="queue.runner_pending")
    assert pending.value == 4.0
    local = await GaugeSample.objects.aget(name="queue.runner_local")
    assert local.value == 2.0

    # 积压：subagent_active=5，background_tasks=total_active=10。
    sub = await GaugeSample.objects.aget(name="backlog.subagent_active")
    assert sub.value == 5.0
    bg = await GaugeSample.objects.aget(name="backlog.background_tasks")
    assert bg.value == 10.0

    # RAG n/a 不落行。
    assert await GaugeSample.objects.filter(name="concurrency.rag").acount() == 0

    # 全部 name 在受控枚举内。
    assert names <= metric_sampling._GAUGE_NAMES


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sample_gauges_skips_unavailable_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """源 available=False → 不落该源行（不产 0 噪声）。"""
    concurrency = {"available": False, "error": "boom"}
    host = {"available": False, "error": "boom"}
    monkeypatch.setattr(
        "system.snapshot_service.collect_concurrency_snapshot", _async(concurrency)
    )
    monkeypatch.setattr("system.snapshot_service.collect_host_snapshot", _async(host))

    result = await metric_sampling.sample_gauges()
    assert result["written"] == 0
    assert await GaugeSample.objects.acount() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sample_gauges_swallows_collector_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """采集器抛错 → sample_gauges 返回 written=0 不冒泡（best-effort）。"""

    async def _boom() -> dict[str, Any]:
        raise RuntimeError("collector down")

    monkeypatch.setattr("system.snapshot_service.collect_concurrency_snapshot", _boom)
    monkeypatch.setattr("system.snapshot_service.collect_host_snapshot", _async(_host_payload()))

    result = await metric_sampling.sample_gauges()
    assert result == {"written": 0}


def test_sample_gauges_job_wires_run_async_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """sample_gauges_job 经 run_async_task 调 sample_gauges 一次，不抛。"""
    from agents.management.commands import runapscheduler

    called = {"n": 0}

    async def _stub() -> dict[str, int]:
        called["n"] += 1
        return {"written": 0}

    monkeypatch.setattr("system.metric_sampling.sample_gauges", _stub)

    runapscheduler.sample_gauges_job()
    assert called["n"] == 1


def test_sample_gauges_job_swallows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """sample_gauges 抛错 → sample_gauges_job 吞异常不冒泡（scheduler 主循环不被打断）。"""
    from agents.management.commands import runapscheduler

    async def _boom() -> dict[str, int]:
        raise RuntimeError("sampling failed")

    monkeypatch.setattr("system.metric_sampling.sample_gauges", _boom)

    # 不应抛出。
    runapscheduler.sample_gauges_job()


def test_purge_metrics_job_wires_three_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    """purge_metrics_job 顺序调三表清理各一次，不抛。"""
    from agents.management.commands import runapscheduler

    calls: list[str] = []

    async def _gauge() -> dict[str, int]:
        calls.append("gauge")
        return {"by_age": 0, "by_size": 0}

    async def _request() -> dict[str, int]:
        calls.append("request")
        return {"by_age": 0, "by_size": 0}

    async def _model() -> dict[str, int]:
        calls.append("model")
        return {"by_age": 0, "by_size": 0}

    monkeypatch.setattr("system.metric_retention.purge_gauge_samples", _gauge)
    monkeypatch.setattr("system.metric_retention.purge_request_metrics", _request)
    monkeypatch.setattr("system.metric_retention.purge_model_usage_records", _model)

    runapscheduler.purge_metrics_job()
    assert calls == ["gauge", "request", "model"]


def test_purge_metrics_job_swallows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """清理抛错 → purge_metrics_job 吞异常不冒泡。"""
    from agents.management.commands import runapscheduler

    async def _boom() -> dict[str, int]:
        raise RuntimeError("purge failed")

    monkeypatch.setattr("system.metric_retention.purge_gauge_samples", _boom)
    monkeypatch.setattr("system.metric_retention.purge_request_metrics", _boom)
    monkeypatch.setattr("system.metric_retention.purge_model_usage_records", _boom)

    # 不应抛出。
    runapscheduler.purge_metrics_job()


def _async(value: Any):
    """构造返回固定值的 async 无参 stub。"""

    async def _inner() -> Any:
        return value

    return _inner
