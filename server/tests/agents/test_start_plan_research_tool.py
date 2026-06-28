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
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agents.tools.base import ToolCategory
from agents.tools.plan_research_tools import (
    PLAN_CLARIFICATION_RENDER_MARKER,
    _maybe_suspend,
    start_plan_research,
)
from agents.tools.registry import ToolRegistry
from delivery.models import (
    Artifact,
    ArtifactVersion,
    Clarification,
    ConvergenceSession,
    ConvergenceSessionStatus,
)
from delivery.services import ConvergenceSessionService
from repositories.models import Repository
from services.process_runtime import ArchitectMergeAdapter, ProcessEngine

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


async def _make_artifact_version() -> ArtifactVersion:
    artifact = await Artifact.objects.acreate(artifact_type="technical_plan")
    av = await ArtifactVersion.objects.acreate(
        artifact=artifact, version_no=1, content={"title": "T"}, content_hash="h"
    )
    artifact.current_version = av
    await artifact.asave(update_fields=["current_version", "updated_at"])
    return av


def _mock_merge_engine(av_id: uuid.UUID) -> ProcessEngine:
    """注入直通 mock adapters 的真实 ProcessEngine：research 直通、merge 返回 artifact_version_id。

    router 返回候选、recall 空、research.dispatch {} → barrier 直通 merge、merge 返回
    validation_status=passed + artifact_version_id → engine 经 transition 落 current_artifact_version → done。
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
    merge = AsyncMock()
    merge.merge = AsyncMock(
        return_value={"validation_status": "passed", "artifact_version_id": str(av_id), "attempt": 0}
    )
    deps = SimpleNamespace(
        router=router, recall=recall, research=research, merge=merge, clarify=clarify
    )
    return ProcessEngine(session_service=ConvergenceSessionService(), deps=deps)


def _real_merge_engine(repo_a: str, repo_b: str) -> ProcessEngine:
    """注入真实 ArchitectMergeAdapter(+_FakeSynth) 的 engine：研究段直通（dispatch {}）→
    无 partial → 架构师合成 _valid_merged → 落 ArtifactVersion（work_item=None）→ done。"""
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
    deps = SimpleNamespace(
        router=router,
        recall=recall,
        research=research,
        merge=ArchitectMergeAdapter(synthesizer=_FakeSynth(repo_a, repo_b)),
        clarify=clarify,
    )
    return ProcessEngine(session_service=ConvergenceSessionService(), deps=deps)


async def _make_project_and_conversation() -> tuple[Any, Any]:
    from chat.models import Conversation
    from projects.models import Space

    project = await Space.objects.acreate(name=f"proj-{uuid.uuid4().hex[:6]}")
    conv = await Conversation.objects.acreate(space=project)
    return project, conv


@pytest.mark.asyncio
async def test_start_plan_research_drives_to_done_merged_plan(monkeypatch) -> None:
    """chat 工具建 entrypoint=chat session + 驱动同一 engine 到 done → success + artifact_version_id。"""
    av = await _make_artifact_version()
    engine = _mock_merge_engine(av.id)
    monkeypatch.setattr(
        "services.process_runtime.build_orchestration_engine",
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
    assert result.output["artifact_version_id"] == str(av.id)

    session = await ConvergenceSession.objects.aget(id=result.output["session_id"])
    assert session.entrypoint == "chat"
    assert session.status == ConvergenceSessionStatus.DONE


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
        "services.process_runtime.build_orchestration_engine",
        _should_not_build,
    )

    project, conv = await _make_project_and_conversation()
    before = await ConvergenceSession.objects.acount()

    result = await start_plan_research(
        requirement_text=blank,
        space_id=str(project.id),
        conversation_id=str(conv.id),
    )

    assert result.success is False
    assert result.error
    assert called is False
    # 未建任何 ConvergenceSession（薄守护，零编排）
    assert await ConvergenceSession.objects.acount() == before


@pytest.mark.asyncio
async def test_start_plan_research_inv2_null_work_item(monkeypatch) -> None:
    """SC-3 / INV-2：chat 自然语言需求（不传 work_item）→ session + canonical Artifact
    的 work_item 均为 None，且 entrypoint=chat 显式可追溯。"""
    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")
    engine = _real_merge_engine(str(repo_a.id), str(repo_b.id))
    monkeypatch.setattr(
        "services.process_runtime.build_orchestration_engine",
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
    assert result.output["artifact_version_id"]

    # ConvergenceSession：work_item 为 None + entrypoint=chat（显式可追溯）
    session = await ConvergenceSession.objects.aget(id=result.output["session_id"])
    assert session.work_item_id is None
    assert session.entrypoint == "chat"
    assert session.status == ConvergenceSessionStatus.DONE

    # canonical：current_artifact_version → ArtifactVersion → Artifact.work_item 为 None（INV-2）
    av = await ArtifactVersion.objects.select_related("artifact").aget(
        id=session.current_artifact_version_id
    )
    assert av.artifact.work_item_id is None
    assert av.artifact.artifact_type == "technical_plan"


# ===========================================================================
# UNIFY-05 二义消除守护（94-05）：plan 澄清挂起单一来源 + marker 物理隔离
# ---------------------------------------------------------------------------
# RESEARCH Wave 0 第 4 项续推/二义守护：plan 澄清用独立渲染 marker
# （"plan_clarification"），不被 chat 单题 _extract_pending_clarification（双条件
# name + marker = "ask_clarification"）捕获——彻底切断「marker 偷渡进 chat 单题
# interrupt → 写 ConversationIntentTrace → 不续推 PlanSession」误路由（T-94-05-MARKER）。
# ===========================================================================


@pytest.mark.asyncio
async def test_plan_clarification_uses_independent_render_marker(monkeypatch) -> None:
    """① plan marker 独立性：CLARIFYING 挂起 → ToolResult.output marker=="plan_clarification"
    且携 session_id + clarification_id（前端走 plan 多题卡的必要字段）。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="chat",
        current_stage="clarify",
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
    )
    # 旧单题行（无子题）→ ahas_pending 判 pending（legacy_pending 路径）
    clar = await Clarification.objects.acreate(
        session=session,
        question="要限定到哪个仓库？",
    )

    suspend = await _maybe_suspend(session, conversation_id=str(uuid.uuid4()))

    assert suspend is not None
    assert suspend.success is True
    assert suspend.output["marker"] == PLAN_CLARIFICATION_RENDER_MARKER
    assert suspend.output["marker"] == "plan_clarification"
    # 独立常量必不等于 chat 单题 marker（物理隔离前置条件）
    from agents.tools.clarification import CLARIFICATION_PENDING_MARKER

    assert suspend.output["marker"] != CLARIFICATION_PENDING_MARKER
    # 前端据 session_id + clarification_id 走 plan 卡（pending_plan_clarification runtime 驱动）
    assert suspend.output["session_id"] == str(session.id)
    assert suspend.output["clarification_id"] == str(clar.id)
    assert suspend.output["pending"] is True


@pytest.mark.asyncio
async def test_plan_clarification_not_captured_by_chat_single_extractor(monkeypatch) -> None:
    """② 不被 chat 单题路径捕获：把 plan CLARIFYING 挂起 output 包成
    _extract_pending_clarification 入参形态，断言返回 None（绝不进 chat 单题
    wait_clarification interrupt → 不写 ConversationIntentTrace，T-94-05-MARKER 守护）。"""
    from orchestration.graph import _extract_pending_clarification

    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint="chat",
        current_stage="clarify",
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
    )
    await Clarification.objects.acreate(session=session, question="要限定到哪个仓库？")

    suspend = await _maybe_suspend(session, conversation_id=str(uuid.uuid4()))
    assert suspend is not None

    # plan 工具 tool_call：name=start_plan_research（非 ask_clarification）+ marker=plan_clarification
    tool_calls_by_id = {
        "tc1": {"name": "start_plan_research", "result": suspend.output},
    }
    assert _extract_pending_clarification(tool_calls_by_id) is None

    # 纵深：即便名字被错填成 ask_clarification，marker 不命中也必返回 None（marker 单独隔离）
    spoofed = {
        "tc-spoof": {"name": "ask_clarification", "result": dict(suspend.output)},
    }
    assert _extract_pending_clarification(spoofed) is None


@pytest.mark.asyncio
async def test_chat_single_clarification_still_captured_zero_regression() -> None:
    """③ chat 单题零回归对照：ask_clarification 工具 output marker 仍 == "ask_clarification"
    且被 _extract_pending_clarification 捕获（name + marker 双 "ask_clarification"），
    证明两路径物理隔离、chat 单题链零回归。"""
    from agents.tools.clarification import (
        CLARIFICATION_PENDING_MARKER,
        ask_clarification,
    )
    from orchestration.graph import _extract_pending_clarification

    result = await ask_clarification(
        question="你想动哪个仓库？",
        options=[
            {"id": "opt-A", "label": "study-app"},
            {"id": "opt-B", "label": "problem-app"},
        ],
    )
    assert result.success is True
    assert result.output["marker"] == CLARIFICATION_PENDING_MARKER
    assert result.output["marker"] == "ask_clarification"

    tool_calls_by_id = {
        "tc1": {"name": "ask_clarification", "result": result.output},
    }
    extracted = _extract_pending_clarification(tool_calls_by_id)
    assert extracted is not None
    assert extracted["clarification_id"] == result.output["clarification_id"]
    assert extracted["question"] == "你想动哪个仓库？"
