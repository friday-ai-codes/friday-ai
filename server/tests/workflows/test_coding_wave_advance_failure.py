"""wave 推进异常时不得以「完成」示人。

`_resume_wave` 由容器回调驱动。推进失败意味着 wave 状态机没走完——可能仍有仓
在 RUNNING、或下一 wave 根本没派发。此前的处理是 warning 一条然后直接
`_finalize_wave` 收尾，节点因此标 completed 并触发 MR / 通知 / 经验沉淀：用户看到
「流程成功」，实际编码没做完。

现在仍然收尾（已 done 的仓该出的 MR 不能丢），但把 NodeResult 显式降级为 failed。
刻意不 raise：抛异常会让容器回调 5xx 触发重试风暴。
"""

from __future__ import annotations

import uuid

import pytest

from workflows.nodes.ai.coding import AICodingNode
from workflows.nodes.base import NodeResult


@pytest.fixture
def node_with_stubbed_finalize(monkeypatch):
    """把收尾段替换成可观测桩，聚焦「推进异常 → 结果状态」这一条因果。"""
    node = AICodingNode()
    calls: dict[str, int] = {"finalize": 0}

    async def _fake_finalize(context, output_data, plan_version_id, log):
        calls["finalize"] += 1
        return NodeResult(
            status="completed",
            output={"succeeded": [{"repository_name": "done-repo"}], "failed": []},
        )

    monkeypatch.setattr(node, "_finalize_wave", _fake_finalize)
    return node, calls


@pytest.mark.asyncio
async def test_advance_exception_marks_node_failed_not_completed(
    node_with_stubbed_finalize, monkeypatch
):
    node, calls = node_with_stubbed_finalize

    async def _boom(_plan_version_id):
        raise RuntimeError("DB 抖动")

    monkeypatch.setattr("services.process_runtime.aadvance_coding_waves", _boom)

    async def _fake_count(_plan_version_id):
        return 3

    monkeypatch.setattr(
        "delivery.models.RepoCodingTask.objects",
        _StubManager(count=3),
    )

    result = await node._resume_wave(
        context=_StubContext(), output_data={}, plan_version_id=uuid.uuid4(), log=_StubLog()
    )

    assert result.status == "failed", "推进失败却报 completed —— 用户会以为流程成功"
    assert "wave 推进失败" in (result.error or "")
    # 已完成仓的产物不能因为这次降级而丢失
    assert calls["finalize"] == 1, "应仍然收尾，避免丢掉已 done 仓的 MR"
    assert result.output["succeeded"][0]["repository_name"] == "done-repo"


class _StubContext:
    execution_id = "exec-1"
    node_id = "node-1"


class _StubLog:
    def info(self, *a, **k): ...
    def warning(self, *a, **k): ...
    def error(self, *a, **k): ...


class _StubQuerySet:
    def __init__(self, count: int) -> None:
        self._count = count

    async def acount(self) -> int:
        return self._count


class _StubManager:
    def __init__(self, count: int) -> None:
        self._count = count

    def filter(self, **_kwargs) -> _StubQuerySet:
        return _StubQuerySet(self._count)
