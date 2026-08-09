"""process enqueue + QUEUE_GRAPH 验收（EXEC-01 / D-03）。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from durable.queues import QUEUE_GRAPH
from services.process_enqueue import enqueue_process_rebuild


@pytest.mark.asyncio
async def test_enqueue_uses_queue_graph_and_process_lock(monkeypatch) -> None:
    """idempotency_key / queueing_lock = process:{repo_id}:{branch}；QUEUE_GRAPH。

    （Req: EXEC-01, 决策: D-03）
    """
    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["task"] = task
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return "job-process"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)

    job = await enqueue_process_rebuild("repo-x", branch_name="feat/a")
    assert job == "job-process"
    assert captured["task"] == "durable_process_rebuild"
    assert captured["kwargs"]["queue"] == QUEUE_GRAPH
    assert captured["kwargs"]["idempotency_key"] == "process:repo-x:feat/a"
    assert captured["payload"]["repository_id"] == "repo-x"
    assert captured["payload"]["branch_name"] == "feat/a"


@pytest.mark.asyncio
async def test_enqueue_passes_initiated_by_user_id(monkeypatch) -> None:
    """enqueue 透传 initiated_by_user_id（无则 system）。

    （Req: EXEC-01, 决策: D-03）
    """
    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["task"] = task
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return "job-2"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)

    await enqueue_process_rebuild(
        "repo-y",
        branch_name="",
        initiated_by_user_id="42",
    )
    assert captured["kwargs"]["initiated_by_user_id"] == "42"
    assert captured["kwargs"]["idempotency_key"] == "process:repo-y:"

    # 缺省不抛；失败 swallow 返回 None
    async def _boom(*a, **k):
        raise RuntimeError("defer down")

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _boom)
    assert await enqueue_process_rebuild("repo-z") is None


@pytest.mark.asyncio
async def test_community_success_chains_process_enqueue(monkeypatch) -> None:
    """run_community_rebuild 成功路径 best-effort enqueue；raise 不链式。

    （Req: EXEC-01, 决策: D-03）
    """
    from durable.tasks_impl import run_community_rebuild

    chained: list[dict] = []

    async def _fake_enqueue(repository_id, *, branch_name="", initiated_by_user_id=None):
        chained.append(
            {
                "repository_id": repository_id,
                "branch_name": branch_name,
                "initiated_by_user_id": initiated_by_user_id,
            }
        )
        return "proc-job"

    monkeypatch.setattr(
        "services.process_enqueue.enqueue_process_rebuild",
        _fake_enqueue,
    )
    monkeypatch.setattr(
        "services.code_graph.community.rebuild_communities",
        AsyncMock(return_value={"status": "ok", "communities_total": 0}),
    )

    result = await run_community_rebuild(
        repository_id="repo-c",
        branch_name="main",
        initiated_by_user_id="7",
    )
    assert result["status"] == "ok"
    assert chained == [
        {
            "repository_id": "repo-c",
            "branch_name": "main",
            "initiated_by_user_id": "7",
        }
    ]

    chained.clear()
    monkeypatch.setattr(
        "services.code_graph.community.rebuild_communities",
        AsyncMock(side_effect=RuntimeError("louvain boom")),
    )
    with pytest.raises(RuntimeError, match="louvain boom"):
        await run_community_rebuild(
            repository_id="repo-c",
            branch_name="main",
            initiated_by_user_id="7",
        )
    assert chained == []
