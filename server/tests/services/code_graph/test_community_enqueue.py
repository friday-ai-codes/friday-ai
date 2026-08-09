"""``services/community_enqueue.py`` + 钩子旁路验收测（MOD-01 / D-03）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from durable.queues import QUEUE_GRAPH
from services.community_enqueue import enqueue_community_rebuild


@pytest.mark.asyncio
async def test_enqueue_uses_queue_graph_and_community_lock(monkeypatch) -> None:
    """``enqueue_community_rebuild`` 走 ``QUEUE_GRAPH`` 与 community 锁键。

    （Req: MOD-01, 决策: D-03, 威胁: T-125-05）
    """
    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["task"] = task
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return "job-community"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)

    job = await enqueue_community_rebuild("repo-x", branch_name="feat/a")
    assert job == "job-community"
    assert captured["task"] == "durable_community_rebuild"
    assert captured["kwargs"]["queue"] == QUEUE_GRAPH
    assert captured["kwargs"]["idempotency_key"] == "community:repo-x:feat/a"
    assert captured["payload"]["repository_id"] == "repo-x"
    assert captured["payload"]["branch_name"] == "feat/a"


@pytest.mark.asyncio
async def test_enqueue_passes_initiated_by_user_id(monkeypatch) -> None:
    """enqueue payload 携带 ``initiated_by_user_id``（观测绑定触发用户）。

    （Req: MOD-01, 决策: D-03）
    """
    captured: dict = {}

    async def _fake_defer(task, payload, **kwargs):
        captured["task"] = task
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return "job-2"

    monkeypatch.setattr("durable.service.DurableTaskService.defer", _fake_defer)

    await enqueue_community_rebuild(
        "repo-y",
        branch_name="",
        initiated_by_user_id="42",
    )
    assert captured["kwargs"]["initiated_by_user_id"] == "42"
    assert captured["kwargs"]["idempotency_key"] == "community:repo-y:"


def test_hooks_enqueue_not_inline_louvain() -> None:
    """graph_builder / code_relations 钩子旁只调用 enqueue，不内联 Louvain。

    （Req: MOD-01, 决策: D-03）
    """
    root = Path(__file__).resolve().parents[3]
    targets = [
        root / "services" / "graph_builder.py",
        root / "code_relations" / "tasks.py",
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        assert "enqueue_community_rebuild" in src, f"{path} missing enqueue"
        assert "louvain_communities" not in src, f"{path} must not inline louvain"
