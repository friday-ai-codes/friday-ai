"""Chassis v2 · P0 反应运行时测试。

覆盖：信号投影、反应幂等（重放不重复副作用）、失败隔离（不反噬主流程）、
宿主节点匹配（host_node vs 工作流级）。
"""

import pytest

from projects.models import Space
from workflows.models import (
    ReactionExecutionStatus,
    Workflow,
    WorkflowExecution,
    WorkflowNode,
    WorkflowReaction,
)
from workflows.reactions import runtime as reaction_runtime
from workflows.reactions.signal import (
    SIG_NODE_COMPLETED,
    SOURCE_WORKFLOW_HOOK,
    Signal,
    project_from_hook,
)


class _FakeNodeExecution:
    """投影纯函数测试用的轻量替身。"""

    def __init__(self, id, node_id, status, error_code=None):
        self.id = id
        self.node_id = node_id
        self.status = status
        self.error_code = error_code


class _FakeExecution:
    def __init__(self, id):
        self.id = id


def test_project_from_hook_node_completed():
    """node_completed hook → node.completed 信号，subject_id = 宿主节点 id。"""
    ne = _FakeNodeExecution(id="ne-1", node_id="node-42", status="completed")
    ex = _FakeExecution(id="exec-1")

    signals = project_from_hook("node_completed", execution=ex, node_execution=ne)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.name == SIG_NODE_COMPLETED
    assert sig.scope == "node_execution"
    assert sig.subject_id == "node-42"
    assert sig.source == SOURCE_WORKFLOW_HOOK
    assert sig.payload["execution_id"] == "exec-1"
    assert sig.payload["node_id"] == "node-42"


def test_project_from_hook_waiting_approval_multi():
    """node_waiting_approval → node.waiting + approval.requested 两个信号。"""
    ne = _FakeNodeExecution(id="ne-2", node_id="node-7", status="waiting_approval")
    ex = _FakeExecution(id="exec-2")

    signals = project_from_hook("node_waiting_approval", execution=ex, node_execution=ne)
    names = {s.name for s in signals}

    assert "node.waiting" in names
    assert "approval.requested" in names


def test_project_from_hook_skipped_no_signal():
    """node_skipped 不投影信号。"""
    ne = _FakeNodeExecution(id="ne-3", node_id="node-8", status="skipped")
    ex = _FakeExecution(id="exec-3")
    assert project_from_hook("node_skipped", execution=ex, node_execution=ne) == []


def test_project_from_hook_failed_includes_error_code():
    """失败信号 payload 带 error_code（受控字段），不带 error_message。"""
    ne = _FakeNodeExecution(
        id="ne-4", node_id="node-9", status="failed", error_code="runtime"
    )
    ex = _FakeExecution(id="exec-4")
    signals = project_from_hook("node_failed", execution=ex, node_execution=ne)
    assert signals[0].payload["error_code"] == "runtime"
    assert "error_message" not in signals[0].payload


async def _make_execution_with_node():
    space = await Space.objects.acreate(name="RX Space", description="reaction tests")
    workflow = await Workflow.objects.acreate(
        name="RX Workflow", trigger_type="manual", space=space
    )
    node = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="condition", name="Host", position_x=0, position_y=0
    )
    execution = await WorkflowExecution.objects.acreate(
        workflow=workflow, space=space, trigger_type="manual"
    )
    return space, workflow, node, execution


def _node_signal(node_id: str, execution_id: str) -> Signal:
    return Signal(
        name=SIG_NODE_COMPLETED,
        scope="node_execution",
        subject_id=str(node_id),
        source=SOURCE_WORKFLOW_HOOK,
        payload={"execution_id": str(execution_id), "node_id": str(node_id)},
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reaction_dispatch_idempotent():
    """同一信号重放：执行器仅调用一次，仅一条 delivered 记录。"""
    _, workflow, node, execution = await _make_execution_with_node()

    calls: list[str] = []

    @reaction_runtime.register_executor("test_count")
    async def _counter(reaction, exec_, signal):  # noqa: ANN001
        calls.append(signal.name)
        return {"ok": True}

    reaction = await WorkflowReaction.objects.acreate(
        workflow=workflow,
        host_node=node,
        signal_name=SIG_NODE_COMPLETED,
        target_type="test_count",
        config={},
    )

    sig = _node_signal(node.id, execution.id)

    first = await reaction_runtime.dispatch(sig, execution)
    second = await reaction_runtime.dispatch(sig, execution)  # 重放

    assert len(calls) == 1, "重放不应重复执行副作用"
    assert len(first) == 1
    assert first[0].status == ReactionExecutionStatus.DELIVERED
    # 第二次返回已存在记录（短路），状态仍为 delivered
    assert second[0].id == first[0].id
    assert second[0].status == ReactionExecutionStatus.DELIVERED

    delivered = [
        r
        async for r in reaction.executions.filter(
            status=ReactionExecutionStatus.DELIVERED
        )
    ]
    assert len(delivered) == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reaction_failure_isolated_and_recorded():
    """执行器抛错：记录 failed 且 dispatch 不向上抛（不反噬主流程）。"""
    _, workflow, node, execution = await _make_execution_with_node()

    @reaction_runtime.register_executor("test_boom")
    async def _boom(reaction, exec_, signal):  # noqa: ANN001
        raise RuntimeError("boom")

    await WorkflowReaction.objects.acreate(
        workflow=workflow,
        host_node=node,
        signal_name=SIG_NODE_COMPLETED,
        target_type="test_boom",
        config={},
    )

    sig = _node_signal(node.id, execution.id)
    results = await reaction_runtime.dispatch(sig, execution)  # 不应抛出

    assert len(results) == 1
    assert results[0].status == ReactionExecutionStatus.FAILED
    assert "boom" in results[0].last_error


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reaction_host_node_scoping():
    """host_node 反应仅匹配该节点信号；工作流级（host_node 为空）匹配任意节点。"""
    space, workflow, node, execution = await _make_execution_with_node()
    other_node = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="condition", name="Other", position_x=1, position_y=1
    )

    hits: list[str] = []

    @reaction_runtime.register_executor("test_scope")
    async def _hit(reaction, exec_, signal):  # noqa: ANN001
        hits.append(str(reaction.id))
        return {}

    # 绑定到 node 的反应
    await WorkflowReaction.objects.acreate(
        workflow=workflow,
        host_node=node,
        signal_name=SIG_NODE_COMPLETED,
        target_type="test_scope",
        config={},
    )
    # 工作流级反应（host_node 为空）
    await WorkflowReaction.objects.acreate(
        workflow=workflow,
        host_node=None,
        signal_name=SIG_NODE_COMPLETED,
        target_type="test_scope",
        config={},
    )

    # node 的信号：命中 host_node 反应 + 工作流级反应 = 2
    await reaction_runtime.dispatch(_node_signal(node.id, execution.id), execution)
    assert len(hits) == 2

    hits.clear()
    # other_node 的信号：只命中工作流级反应 = 1
    await reaction_runtime.dispatch(_node_signal(other_node.id, execution.id), execution)
    assert len(hits) == 1
