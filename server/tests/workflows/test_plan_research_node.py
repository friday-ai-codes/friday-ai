"""AIPlanResearchNode 节点单测（ENTRY-01，41-03 Task 2）。

覆盖：建 PlanSession(entrypoint=workflow) + 驱动 engine 到 done（adapters mock 在 IO 边界）→
NodeResult completed（plan_version_id 非空）/ clarifying 挂起 waiting_event / failed 映射 /
schema 合法 + 自动注册。用真实 PlanSession/PlanSessionService + 真实 engine，IO 边界 mock。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from delivery.models import Clarification, PlanSession, PlanSessionStatus
from delivery.services import PlanSessionService
from services.plan_orchestration import ClarifyAdapter, PlanOrchestrationEngine
from workflows.nodes.ai.plan_research import AIPlanResearchNode
from workflows.nodes.base import ExecutionContext
from workflows.nodes.registry import NodeRegistry

# async ORM 测试用 transaction=True（真实 commit + 表间清理，对齐 test_research_completion_callback）
pytestmark = pytest.mark.django_db(transaction=True)


def _ctx(config: dict | None = None) -> ExecutionContext:
    return ExecutionContext(
        execution_id="exec-pr-001",
        node_id="node-pr-001",
        node_config=config or {"requirement_text": "为多仓需求做方案编排"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )


def _bind_engine(node: AIPlanResearchNode, engine: PlanOrchestrationEngine) -> None:
    node._build_engine = lambda context, session: engine  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_drive_to_done_emits_merged_plan_ref() -> None:
    """建 session + 驱动到 done → completed + output.plan_version_id 非空 + status done。"""
    pv_id = uuid.uuid4()

    router = AsyncMock()
    router.route = AsyncMock(
        return_value={
            "candidates": [
                {"repo_id": "r1", "confidence": "high"},
                {"repo_id": "r2", "confidence": "high"},
            ]
        }
    )
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "q", "kinds": []})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})  # 无 task → barrier 直通 merging
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})

    async def _merge_side(session):
        await PlanSessionService().set_current_plan_version(session, pv_id)
        return {"validation_status": "passed", "attempt": 0}

    merge = AsyncMock()
    merge.merge = AsyncMock(side_effect=_merge_side)

    engine = PlanOrchestrationEngine(
        router=router, recall=recall, research=research, merge=merge, clarify=clarify
    )
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "completed"
    assert result.output["plan_version_id"] == str(pv_id)
    assert result.output["status"] == "done"
    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.status == PlanSessionStatus.DONE
    assert session.entrypoint == "workflow"


@pytest.mark.asyncio
async def test_clarifying_suspends_waiting_event() -> None:
    """needs-clarification → waiting_event（不 completed）+ 卡片 payload + DB pending + clarifying。"""
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": []})
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "", "kinds": []})
    # 真实 ClarifyAdapter + policy 判需澄清
    clarify = ClarifyAdapter(policy=lambda s: (True, "请补充涉及的仓库", []))

    engine = PlanOrchestrationEngine(router=router, recall=recall, clarify=clarify)
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "waiting_event"
    assert result.output["kind"] == "clarification"
    assert result.output["suspension"]["question"] == "请补充涉及的仓库"
    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.status == PlanSessionStatus.CLARIFYING
    assert (
        await Clarification.objects.filter(
            session_id=session.id, answered_at__isnull=True
        ).acount()
        == 1
    )


@pytest.mark.asyncio
async def test_failed_terminal_maps_to_node_failed() -> None:
    """merge 限次耗尽 → failed → NodeResult failed + error_code=plan_session_failed。"""
    router = AsyncMock()
    router.route = AsyncMock(
        return_value={"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    )
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "q", "kinds": []})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "failed", "attempt": 1, "report": {}}
    )

    engine = PlanOrchestrationEngine(
        router=router, recall=recall, research=research, merge=merge, clarify=clarify
    )
    node = AIPlanResearchNode()
    _bind_engine(node, engine)

    result = await node.execute(_ctx())

    assert result.status == "failed"
    assert result.output["error_code"] == "plan_session_failed"
    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.status == PlanSessionStatus.FAILED


@pytest.mark.asyncio
async def test_missing_requirement_fails_fast() -> None:
    """无 requirement_text 且无上游输入 → 快速失败（missing_requirement），不建 session。"""
    node = AIPlanResearchNode()
    result = await node.execute(_ctx({"requirement_text": ""}))
    assert result.status == "failed"
    assert result.output["error_code"] == "missing_requirement"
    assert await PlanSession.objects.acount() == 0


def test_schema_and_registration() -> None:
    """节点自动注册 + config_schema 合法 + ports 完整。"""
    cls = NodeRegistry.get("ai_plan_research")
    assert cls is AIPlanResearchNode
    assert cls.validate_config({}) == []
    assert cls.validate_config(
        {"requirement_text": "x", "include_repos": ["a"], "work_item_id": ""}
    ) == []
    props = cls.config_schema["properties"]
    assert {"requirement_text", "include_repos", "work_item_id"} <= set(props)
    assert [p.name for p in cls.inputs] == ["default"]
    output_names = {p.name for p in cls.outputs}
    assert output_names == {"default", "error"}
    default_out = next(p for p in cls.outputs if p.name == "default")
    assert "plan_version_id" in (default_out.schema or {}).get("properties", {})
