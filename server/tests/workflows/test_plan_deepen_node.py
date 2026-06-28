"""PlanDeepenNode 守护测试（Phase 89，PLAN-01，89-01）。

覆盖：
- 节点自动注册（registry 含 plan_deepen）+ is_blocking + 输出 handle。
- 无需求文本 → failed + error。
- clarifying 未答 → status=="waiting_event" + 订阅创建（acreate 被调）。
- 终态 DONE → completed，output 含 plan_version 锚 + initiated_by 透传。
- FAILED → error 分支。

纯 mock（patch _resolve_space/_aresolve_project/PlanDeepenService + 发卡 + 订阅 acreate），
不落库。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.nodes.base import ExecutionContext
from workflows.nodes.integrations.plan_deepen import PlanDeepenNode
from workflows.nodes.registry import NodeRegistry

_NODE_MOD = "workflows.nodes.integrations.plan_deepen"


class _FakeExecution:
    """最小工作流执行替身（满足 render_template 的 global 取值路径）。"""

    def __init__(self, triggered_by_id: int | None) -> None:
        self.triggered_by_id = triggered_by_id
        self.global_params: dict = {}

    def get_all_global_variables(self) -> dict:
        return {}


def _ctx(
    config: dict,
    *,
    with_execution: bool = True,
    triggered_by_id: int | None = 42,
) -> ExecutionContext:
    execution = _FakeExecution(triggered_by_id) if with_execution else None
    node_execution = SimpleNamespace(id="ne-1") if with_execution else None
    return ExecutionContext(
        execution_id="exec-1",
        node_id="node-1",
        node_config=config,
        input_data={},
        workflow_context={},
        previous_outputs={},
        workflow_execution=execution,
        node_execution=node_execution,
    )


def test_node_auto_registered() -> None:
    node_cls = NodeRegistry.get("plan_deepen")
    assert node_cls is PlanDeepenNode
    assert node_cls.is_blocking is True
    assert node_cls.execution_mode == "server_local"
    out_handles = {p.name for p in node_cls.outputs}
    assert out_handles == {"default", "clarifying", "error"}


@pytest.mark.asyncio
async def test_no_requirement_fails() -> None:
    node = PlanDeepenNode()
    result = await node.execute(_ctx({}))
    assert result.status == "failed"
    assert result.next_handle == "error"


def _deepen_patches(session: SimpleNamespace, capture: dict):
    svc = MagicMock()

    async def _deepen(**kwargs):
        capture.update(kwargs)
        return session

    svc.deepen = AsyncMock(side_effect=_deepen)
    return (
        patch(f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))),
        patch(f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))),
        patch(f"{_NODE_MOD}.PlanDeepenService", return_value=svc),
    )


@pytest.mark.asyncio
async def test_clarifying_waiting_event_and_subscription() -> None:
    node = PlanDeepenNode()
    session = SimpleNamespace(
        id="sess-1", status="waiting_clarification", current_artifact_version_id=None
    )
    capture: dict = {}
    p_space, p_proj, p_svc = _deepen_patches(session, capture)
    acreate = AsyncMock()

    with p_space, p_proj, p_svc, patch.object(
        PlanDeepenNode, "_send_clarify_card", new=AsyncMock()
    ), patch.object(
        PlanDeepenNode, "_apending_clarification_question", new=AsyncMock(return_value="刷新策略未定？")
    ), patch(
        f"{_NODE_MOD}.WorkflowEventSubscription.objects.acreate", new=acreate
    ):
        result = await node.execute(_ctx({"requirement_text": "把登录改成 JWT"}))

    assert result.status == "waiting_event"
    assert result.output["session_id"] == "sess-1"
    acreate.assert_awaited_once()
    # initiated_by 透传（triggered_by_id=42）
    assert capture["initiated_by_user_id"] == "42"
    assert capture["node_execution_id"] == "ne-1"


@pytest.mark.asyncio
async def test_done_completed_with_plan_anchor() -> None:
    node = PlanDeepenNode()
    session = SimpleNamespace(id="sess-1", status="done", current_artifact_version_id="ver-9")
    capture: dict = {}
    p_space, p_proj, p_svc = _deepen_patches(session, capture)

    with p_space, p_proj, p_svc, patch.object(
        PlanDeepenNode, "_send_done_card", new=AsyncMock()
    ):
        result = await node.execute(_ctx({"requirement_text": "需求 X"}))

    assert result.status == "completed"
    assert result.next_handle == "default"
    assert result.output["artifact_version_id"] == "ver-9"
    assert result.output["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_failed_session_routes_error() -> None:
    node = PlanDeepenNode()
    session = SimpleNamespace(id="sess-1", status="failed", current_artifact_version_id=None)
    capture: dict = {}
    p_space, p_proj, p_svc = _deepen_patches(session, capture)

    with p_space, p_proj, p_svc:
        result = await node.execute(_ctx({"requirement_text": "需求 X"}))

    assert result.status == "failed"
    assert result.next_handle == "error"


@pytest.mark.asyncio
async def test_deepen_exception_routes_error() -> None:
    node = PlanDeepenNode()
    svc = MagicMock()
    svc.deepen = AsyncMock(side_effect=RuntimeError("boom"))

    with patch(
        f"{_NODE_MOD}._resolve_space", AsyncMock(return_value=SimpleNamespace(id="s1"))
    ), patch(
        f"{_NODE_MOD}._aresolve_project", AsyncMock(return_value=SimpleNamespace(id="p1"))
    ), patch(f"{_NODE_MOD}.PlanDeepenService", return_value=svc):
        result = await node.execute(_ctx({"requirement_text": "需求 X"}))

    assert result.status == "failed"
    assert result.next_handle == "error"
