"""Provider 快照取 Space 不得触发同步 ORM。

`_snapshot_ai_node_providers` 里原先是 `getattr(workflow_execution, "space", None)`。
那是惰性 FK 访问：未预取时在 async 上下文抛 SynchronousOnlyOperation，被外层
`except Exception` 吞成一条 sampling 级 error 日志，结果 node_snapshots 为空——
Replay 稳定性（后续改 default_provider_credential_id 不影响历史 Execution）静默失效。

症状极隐蔽：流程照跑、测试照绿，只有日志里一行
`snapshot.ai_node_providers_helper_failed`。
"""

from __future__ import annotations

import uuid

import pytest

from workflows.engine.scheduler import WorkflowEngine


class _FieldsCache:
    def __init__(self, cached: dict) -> None:
        self._cached = cached

    def get(self, key):
        return self._cached.get(key)


class _State:
    def __init__(self, cached: dict) -> None:
        self.fields_cache = _FieldsCache(cached)


class _Execution:
    """WorkflowExecution 替身。

    `space` 属性刻意做成访问即炸，模拟未预取时的同步 ORM 行为——真实代码若退回
    直接 getattr，这里会立刻暴露。
    """

    def __init__(self, cached_space=None, space_id=None) -> None:
        self._state = _State({"space": cached_space} if cached_space else {})
        self.space_id = space_id

    @property
    def space(self):
        raise AssertionError(
            "不应直接访问 .space —— 未预取时会在 async 上下文触发同步 ORM 查询"
        )


@pytest.mark.asyncio
async def test_uses_cached_space_without_touching_lazy_attribute():
    sentinel = object()
    execution = _Execution(cached_space=sentinel, space_id=uuid.uuid4())

    result = await WorkflowEngine._aget_execution_space(execution)

    assert result is sentinel


@pytest.mark.asyncio
async def test_returns_none_when_no_space_id():
    """无关联 Space 时返回 None，不查库也不炸。"""
    execution = _Execution(cached_space=None, space_id=None)

    assert await WorkflowEngine._aget_execution_space(execution) is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_falls_back_to_async_query_when_not_prefetched():
    """未预取时走异步查询拿到真实对象，而不是抛 SynchronousOnlyOperation。"""
    from asgiref.sync import sync_to_async

    from projects.models import Space

    space = await sync_to_async(Space.objects.create)(name="snapshot-space")
    execution = _Execution(cached_space=None, space_id=space.id)

    result = await WorkflowEngine._aget_execution_space(execution)

    assert result is not None
    assert result.id == space.id
