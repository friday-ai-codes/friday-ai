"""workflow 蓝图首驱入队测试（31u Task 2）。

覆盖 ``AIPlanResearchNode`` 的首驱入队分支：

- 新建蓝图会话 → 不内联 ``adrive``：defer ``durable_blueprint_resume``
  （lock=blueprint-resume-{id}）+ 返回 ``waiting_event``（output 带 session_id /
  kind=enqueued / schema_version）；
- defer 抛异常 → 降级走内联驱动（不比现状差）；
- resume 路径（output_data 已有 session_id）→ 不入队、仍内联驱动；
- 旧链（非蓝图）会话 → 不入队、仍内联驱动（分支只对蓝图会话生效）。

session 建立经 stub（``_create_session`` 替身返回预建 ConvergenceSession），不触碰
entry switch；驱动/挂起/终态映射用替身隔离，聚焦「入队 or 内联」的分流断言。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import ConvergenceSession, ConvergenceSessionStatus
from durable.service import DurableTaskService
from workflows.nodes.ai.plan_research import AIPlanResearchNode
from workflows.nodes.base import ExecutionContext, NodeResult

pytestmark = pytest.mark.django_db(transaction=True)


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-fd-001",
        node_id="node-fd-001",
        node_config={"requirement_text": "为多仓需求出技术蓝图"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )


async def _make_session(process_type: str = "technical_blueprint") -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type=process_type,
        entrypoint="workflow",
        current_stage="spec_gate",
        status=ConvergenceSessionStatus.RUNNING,
    )


def _capture_defer(monkeypatch) -> list[dict]:
    deferred: list[dict] = []

    async def _capture(task_name, payload, **kwargs):
        deferred.append({"task": task_name, "payload": payload, **kwargs})
        return "job-bp"

    monkeypatch.setattr(DurableTaskService, "defer", AsyncMock(side_effect=_capture))
    return deferred


def _wire_node(node: AIPlanResearchNode, session: Any, driven: list) -> None:
    """替身接线：首建通道返回预建 session；驱动/挂起/终态映射隔离。"""

    async def _no_resume(context):
        return None

    async def _create(context, log):
        return session

    async def _drive(engine, sess, max_steps=20):
        driven.append(sess)
        return sess

    node._resolve_session = _no_resume  # type: ignore[method-assign]
    node._create_session = _create  # type: ignore[method-assign]
    node._build_engine = lambda context, sess: (object(), _drive)  # type: ignore[method-assign]
    node._maybe_suspend = AsyncMock(return_value=None)  # type: ignore[method-assign]
    node._amap_terminal_blueprint = AsyncMock(  # type: ignore[method-assign]
        return_value=NodeResult(status="failed", error="sentinel", output={}, next_handle="error")
    )
    node._map_terminal = AsyncMock(  # type: ignore[method-assign]
        return_value=NodeResult(
            status="failed", error="sentinel-v0", output={}, next_handle="error"
        )
    )


@pytest.mark.asyncio
async def test_new_blueprint_session_enqueues_first_drive(monkeypatch) -> None:
    """首建蓝图会话 → defer durable_blueprint_resume + waiting_event，跳过内联驱动。"""
    session = await _make_session()
    deferred = _capture_defer(monkeypatch)
    driven: list = []
    node = AIPlanResearchNode()
    _wire_node(node, session, driven)

    result = await node.execute(_ctx())

    assert result.status == "waiting_event"
    assert result.output["session_id"] == str(session.id)
    assert result.output["kind"] == "enqueued"
    assert result.output["schema_version"] == "blueprint/v1"

    assert len(deferred) == 1
    call = deferred[0]
    assert call["task"] == "durable_blueprint_resume"
    assert call["payload"] == {"session_id": str(session.id)}
    assert call["lock"] == f"blueprint-resume-{session.id}"
    assert call.get("idempotency_key") is None

    assert driven == [], "首驱已入队时绝不内联驱动"


@pytest.mark.asyncio
async def test_enqueue_failure_degrades_to_inline_drive(monkeypatch) -> None:
    """defer 抛异常 → 降级为内联 adrive（不比现状差），且不再返回 enqueued。"""
    session = await _make_session()
    monkeypatch.setattr(
        DurableTaskService, "defer", AsyncMock(side_effect=RuntimeError("queue down"))
    )
    driven: list = []
    node = AIPlanResearchNode()
    _wire_node(node, session, driven)

    result = await node.execute(_ctx())

    assert driven == [session], "入队失败必须降级为内联驱动"
    assert result.error == "sentinel"


@pytest.mark.asyncio
async def test_resume_path_does_not_enqueue(monkeypatch) -> None:
    """resume 路径（output_data 已有 session_id）→ 不入队、仍内联驱动。"""
    session = await _make_session()
    deferred = _capture_defer(monkeypatch)
    driven: list = []
    node = AIPlanResearchNode()
    _wire_node(node, session, driven)

    async def _resume(context):
        return session

    node._resolve_session = _resume  # type: ignore[method-assign]

    result = await node.execute(_ctx())

    assert deferred == [], "resume 路径逐字不动：不入队"
    assert driven == [session]
    assert result.error == "sentinel"


@pytest.mark.asyncio
async def test_legacy_session_does_not_enqueue(monkeypatch) -> None:
    """旧链（非蓝图 process）新建会话 → 不入队、仍内联驱动（分支只对蓝图生效）。"""
    session = await _make_session(process_type="technical_plan")
    deferred = _capture_defer(monkeypatch)
    driven: list = []
    node = AIPlanResearchNode()
    _wire_node(node, session, driven)

    result = await node.execute(_ctx())

    assert deferred == [], "旧链逐字不动：不入队"
    assert driven == [session]
    assert result.error == "sentinel-v0"
