"""start_plan_research chat 工具守护测试（ENTRY-02，42-01 Task 3）。

覆盖（IO 边界 mock，真实 PlanSessionService/TechnicalPlanService/ArchitectMergeAdapter +
真实 engine）：
- chat 工具经共享 helper 驱动同一 engine 到 done → 产出 canonical MergedPlan 引用（SC-1）。
- 工具自动注册进 registry + 在 chat 工具白名单（_INDEXED_TOOL_NAMES）可用。
- SC-3 / INV-2：chat 自然语言需求（work_item=None）→ PlanSession.work_item 与 canonical
  TechnicalPlan.work_item 均为 None 且 entrypoint=chat 显式可追溯。

真实 LLM / 容器端到端沿用既有 deferred（mock 在 IO 边界）。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agents.tools.base import ToolCategory
from agents.tools.plan_research_tools import start_plan_research
from agents.tools.registry import ToolRegistry
from delivery.models import (
    PlanSession,
    PlanSessionStatus,
    PlanVersion,
    TechnicalPlan,
)
from delivery.services import PlanSessionService
from repositories.models import Repository
from services.plan_orchestration import ArchitectMergeAdapter, PlanOrchestrationEngine

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_repo(name: str) -> Repository:
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.test/{name}-{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _valid_merged(repo_a: str, repo_b: str) -> dict:
    """合法 §7 MergedPlan（含跨仓 dependency_dag + execution_plan[].dependencies）。"""
    return {
        "title": "跨仓主方案",
        "summary": "融合 repoA/repoB 的跨仓方案",
        "api_contracts": [{"name": "ContractX", "repo": repo_a}],
        "dependency_dag": {repo_b: [repo_a]},
        "data_migrations": [{"repository_id": repo_a}],
        "compat_risks": [],
        "release_order": [repo_a, repo_b],
        "rollback_plan": {repo_a: "回滚A", repo_b: "回滚B"},
        "execution_plan": [
            {
                "id": "t1",
                "name": "A 暴露契约",
                "description": "",
                "repository_id": repo_a,
                "repository_name": "repoA",
                "branch_strategy": "feature",
                "coding_instruction": "实现 ContractX",
                "dependencies": [],
                "api_contracts_exposed": ["ContractX"],
                "dependencies_on_other_repos": [],
            },
            {
                "id": "t2",
                "name": "B 接入契约",
                "description": "",
                "repository_id": repo_b,
                "repository_name": "repoB",
                "branch_strategy": "feature",
                "coding_instruction": "调用 ContractX",
                "dependencies": ["t1"],
                "api_contracts_exposed": [],
                "dependencies_on_other_repos": ["ContractX"],
            },
        ],
    }


class _FakeSynth:
    """架构师 LLM 合成器 fake（IO 边界）：直接返回合法 §7 MergedPlan。"""

    def __init__(self, repo_a: str, repo_b: str) -> None:
        self.repo_a = repo_a
        self.repo_b = repo_b

    async def synthesize(self, session: Any, partials: list[dict]) -> dict:
        return _valid_merged(self.repo_a, self.repo_b)


def _mock_merge_engine(pv_id: uuid.UUID) -> PlanOrchestrationEngine:
    """注入直通 mock adapters 的真实 engine：research 直通、merge 经 set_current_plan_version。

    对齐 test_plan_research_node.py::test_drive_to_done_emits_merged_plan_ref：router 返回候选、
    recall 空、research.dispatch 返回 {} → barrier 直通 merging、merge 置 current_plan_version
    后返回 validation_status=passed → done。
    """
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
    research.dispatch = AsyncMock(return_value={})
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})

    async def _merge_side(session: Any) -> dict:
        await PlanSessionService().set_current_plan_version(session, pv_id)
        return {"validation_status": "passed", "attempt": 0}

    merge = AsyncMock()
    merge.merge = AsyncMock(side_effect=_merge_side)
    return PlanOrchestrationEngine(
        router=router, recall=recall, research=research, merge=merge, clarify=clarify
    )


def _real_merge_engine(repo_a: str, repo_b: str) -> PlanOrchestrationEngine:
    """注入真实 ArchitectMergeAdapter(+_FakeSynth) 的 engine：研究段直通（dispatch {}）→
    无 partial → 架构师合成 _valid_merged → 落 canonical（work_item=None）→ done。"""
    router = AsyncMock()
    router.route = AsyncMock(
        return_value={
            "candidates": [
                {"repo_id": repo_a, "confidence": "high"},
                {"repo_id": repo_b, "confidence": "high"},
            ]
        }
    )
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "q", "kinds": []})
    research = AsyncMock()
    research.dispatch = AsyncMock(return_value={})
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})
    return PlanOrchestrationEngine(
        session_service=PlanSessionService(),
        router=router,
        recall=recall,
        research=research,
        merge=ArchitectMergeAdapter(synthesizer=_FakeSynth(repo_a, repo_b)),
        clarify=clarify,
    )


async def _make_project_and_conversation() -> tuple[Any, Any]:
    from chat.models import Conversation
    from projects.models import Space

    project = await Space.objects.acreate(name=f"proj-{uuid.uuid4().hex[:6]}")
    conv = await Conversation.objects.acreate(space=project)
    return project, conv


@pytest.mark.asyncio
async def test_start_plan_research_drives_to_done_merged_plan(monkeypatch) -> None:
    """chat 工具建 entrypoint=chat session + 驱动同一 engine 到 done → success + plan_version_id。"""
    pv_id = uuid.uuid4()
    engine = _mock_merge_engine(pv_id)
    monkeypatch.setattr(
        "services.plan_orchestration.build_orchestration_engine",
        lambda **kw: engine,
    )

    project, conv = await _make_project_and_conversation()

    result = await start_plan_research(
        requirement_text="为 A/B 两仓做跨仓方案",
        space_id=str(project.id),
        conversation_id=str(conv.id),
    )

    assert result.success is True
    assert result.output["status"] == "done"
    assert result.output["plan_version_id"] == str(pv_id)

    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.entrypoint == "chat"
    assert session.status == PlanSessionStatus.DONE


def test_start_plan_research_registered() -> None:
    """工具自动注册 registry（category=PROJECT，schema 含 requirement_text/include_repos）+
    在 chat 工具白名单 _INDEXED_TOOL_NAMES。"""
    t = ToolRegistry.get_tool("start_plan_research")
    assert t is not None
    assert t.category == ToolCategory.PROJECT
    props = t.parameters["properties"]
    assert "requirement_text" in props
    assert "include_repos" in props
    # space_id/conversation_id 仍在 schema 中（由 MCP 适配层注入时移除，LLM 不可见）
    assert "space_id" in props
    assert "conversation_id" in props

    from agents.chat_runner import _INDEXED_TOOL_NAMES

    assert "start_plan_research" in _INDEXED_TOOL_NAMES


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
async def test_start_plan_research_blank_requirement_fail_closed(monkeypatch, blank) -> None:
    """WR-02：空 / 纯空白 requirement_text → fail-closed（success=False），不建 session / 驱 engine
    （与工作流节点 missing_requirement 对称）。"""
    called = False

    def _should_not_build(**kw):
        nonlocal called
        called = True
        raise AssertionError("engine must not be built for blank requirement")

    monkeypatch.setattr(
        "services.plan_orchestration.build_orchestration_engine",
        _should_not_build,
    )

    project, conv = await _make_project_and_conversation()
    before = await PlanSession.objects.acount()

    result = await start_plan_research(
        requirement_text=blank,
        space_id=str(project.id),
        conversation_id=str(conv.id),
    )

    assert result.success is False
    assert result.error
    assert called is False
    # 未建任何 PlanSession（薄守护，零编排）
    assert await PlanSession.objects.acount() == before


@pytest.mark.asyncio
async def test_start_plan_research_inv2_null_work_item(monkeypatch) -> None:
    """SC-3 / INV-2：chat 自然语言需求（不传 work_item）→ session + canonical TechnicalPlan
    的 work_item 均为 None，且 entrypoint=chat 显式可追溯。"""
    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")
    engine = _real_merge_engine(str(repo_a.id), str(repo_b.id))
    monkeypatch.setattr(
        "services.plan_orchestration.build_orchestration_engine",
        lambda **kw: engine,
    )

    project, conv = await _make_project_and_conversation()

    result = await start_plan_research(
        requirement_text="为 A/B 两仓做跨仓方案（自然语言需求，无 work_item）",
        space_id=str(project.id),
        conversation_id=str(conv.id),
    )

    assert result.success is True
    assert result.output["status"] == "done"
    assert result.output["plan_version_id"]

    # PlanSession：work_item 为 None + entrypoint=chat（显式可追溯）
    session = await PlanSession.objects.aget(id=result.output["session_id"])
    assert session.work_item_id is None
    assert session.entrypoint == "chat"
    assert session.status == PlanSessionStatus.DONE

    # canonical：current_plan_version → PlanVersion → TechnicalPlan.work_item 为 None（INV-2）
    pv = await PlanVersion.objects.aget(id=session.current_plan_version)
    plan = await TechnicalPlan.objects.aget(id=pv.plan_id)
    assert plan.work_item_id is None
    assert plan.origin == "orchestration"
