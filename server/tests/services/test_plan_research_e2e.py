"""SC-2 端到端编排测试（ENTRY-01，41-03 Task 3，IO 边界 mock）。

真实 ``PlanOrchestrationEngine`` + 全部真实 service（PlanSessionService/ResearchService/
ClarificationService/TechnicalPlanService）+ 真实 PlanValidator/merged_plan schema +
真实 ResearchDispatchAdapter/ArchitectMergeAdapter，仅在 **IO 边界 mock**：
- router/recall（LLM/检索）→ 注入 AsyncMock。
- 容器调度（get_dispatcher().dispatch）+ runner 在线计数 → monkeypatch。
- 容器回调 → 直接调 ``subagent.api.callbacks._handle_research_completion`` 写入各仓
  结构化 PartialPlan（含跨仓契约 exposed/depends）。
- merge synthesizer（LLM）→ 注入 fake 返回合法 §7 MergedPlan。

覆盖：需求 → 拆分→路由→召回→澄清→并行调研→融合 → 带跨仓依赖的 canonical MergedPlan +
§15 事件持久化 + 澄清回路（仅 affected partial 重跑）。真实 LLM/容器 E2E 仍 deferred。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import (
    Clarification,
    PartialPlan,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionEvent,
    PlanSessionStatus,
    PlanVersion,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ClarificationService, PlanSessionService
from repositories.models import Repository
from services.plan_orchestration import (
    ArchitectMergeAdapter,
    ClarifyAdapter,
    PlanOrchestrationEngine,
    ResearchDispatchAdapter,
    aall_research_tasks_terminal,
)

pytestmark = pytest.mark.django_db(transaction=True)


def _log() -> Any:
    log = MagicMock()
    log.info = lambda *a, **kw: None
    log.debug = lambda *a, **kw: None
    log.warning = lambda *a, **kw: None
    return log


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
    """架构师 LLM 合成器 fake（IO 边界）：可选首次失败（空 execution_plan）后成功。"""

    def __init__(self, repo_a: str, repo_b: str, *, fail_first: bool = False) -> None:
        self.repo_a = repo_a
        self.repo_b = repo_b
        self.fail_first = fail_first
        self.calls = 0

    async def synthesize(self, session: Any, partials: list[dict]) -> dict:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            # 空 execution_plan → PlanValidator non_empty 失败（merge 回退 clarifying）
            return {"title": "x", "summary": "y", "execution_plan": []}
        return _valid_merged(self.repo_a, self.repo_b)


def _repo_content(repository_id: str, exposer_id: str) -> dict:
    """构造单仓容器回调 §7 输出（exposer 暴露 ContractX，其余依赖之，形成跨仓依赖）。"""
    if repository_id == exposer_id:
        return {
            "result_type": "text",
            "output": {
                "research_summary": f"{repository_id} 暴露 ContractX",
                "candidate_files": ["api.py"],
                "api_contracts_exposed": [{"name": "ContractX"}],
                "dependencies_on_other_repos": [],
                "proposed_changes": [{"file": "api.py"}],
            },
        }
    return {
        "result_type": "text",
        "output": {
            "research_summary": f"{repository_id} 依赖 ContractX",
            "candidate_files": ["client.py"],
            "api_contracts_exposed": [],
            "dependencies_on_other_repos": [{"name": "ContractX"}],
            "proposed_changes": [{"file": "client.py"}],
        },
    }


async def _complete_running_tasks(session: PlanSession, exposer_id: str) -> None:
    """模拟容器回调：对所有 running RepoResearchTask 调真实 _handle_research_completion。"""
    from subagent.api.callbacks import _handle_research_completion
    from subagent.models import SubAgentSession

    tasks = [
        t
        async for t in RepoResearchTask.objects.filter(
            session_id=session.id, status=RepoResearchTaskStatus.RUNNING
        )
    ]
    for task in tasks:
        sub = await SubAgentSession.objects.aget(id=task.subagent_session_id)
        content = _repo_content(str(task.repository_id), exposer_id)
        await _handle_research_completion(sub, content, _log())


async def _drive(
    engine: PlanOrchestrationEngine,
    session: PlanSession,
    *,
    exposer_id: str,
    answer_text: str = "用 repoA 与 repoB",
    max_iter: int = 40,
) -> PlanSession:
    """通用驱动：advance + 在 clarifying(pending) 答复 / researching(在途) 完成容器回调。"""
    for _ in range(max_iter):
        session = await PlanSession.objects.aget(id=session.id)
        if session.status in (PlanSessionStatus.DONE, PlanSessionStatus.FAILED):
            return session
        if session.status == PlanSessionStatus.CLARIFYING:
            pending = await Clarification.objects.filter(
                session_id=session.id, answered_at__isnull=True
            ).afirst()
            if pending is not None:
                await ClarificationService().answer_clarification(pending, answer_text)
                continue
        if session.status == PlanSessionStatus.RESEARCHING:
            if not await aall_research_tasks_terminal(session.id):
                running = await RepoResearchTask.objects.filter(
                    session_id=session.id, status=RepoResearchTaskStatus.RUNNING
                ).aexists()
                if running:
                    # 模拟容器回调完成在途调研（barrier 推进到 merging）
                    await _complete_running_tasks(session, exposer_id)
                    continue
                # 有 stale/pending 未派发 → advance 触发 dispatch（含澄清后 stale 重派）
        await engine.advance(session)
    return await PlanSession.objects.aget(id=session.id)


def _engine(*, router_candidates, synth, clarify) -> PlanOrchestrationEngine:
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": router_candidates})
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "需求", "kinds": []})
    return PlanOrchestrationEngine(
        session_service=PlanSessionService(),
        router=router,
        recall=recall,
        research=ResearchDispatchAdapter(),
        merge=ArchitectMergeAdapter(synthesizer=synth),
        clarify=clarify,
    )


@pytest.mark.asyncio
async def test_e2e_requirement_to_merged_plan_with_cross_repo_deps() -> None:
    """需求经六段编排 → 带跨仓依赖的 canonical MergedPlan + §15 事件覆盖（无澄清直通）。"""
    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")
    session = await PlanSessionService().create_session(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        decomposition={
            "requirement_text": "为 A/B 两仓做跨仓方案",
            "include_repos": [str(repo_a.id), str(repo_b.id)],
        },
    )
    candidates = [
        {"repo_id": str(repo_a.id), "confidence": "high"},
        {"repo_id": str(repo_b.id), "confidence": "high"},
    ]
    synth = _FakeSynth(str(repo_a.id), str(repo_b.id))
    engine = _engine(router_candidates=candidates, synth=synth, clarify=ClarifyAdapter())

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)
        ),
    ):
        session = await _drive(engine, session, exposer_id=str(repo_a.id))

    assert session.status == PlanSessionStatus.DONE
    assert session.current_plan_version is not None

    pv = await PlanVersion.objects.aget(id=session.current_plan_version)
    content = pv.content
    # 跨仓依赖显式存在
    assert content["dependency_dag"] == {str(repo_b.id): [str(repo_a.id)]}
    t2 = next(t for t in content["execution_plan"] if t["id"] == "t2")
    assert t2["dependencies"] == ["t1"]
    assert t2["dependencies_on_other_repos"] == ["ContractX"]

    # §15 事件持久化覆盖（routing/recalling/research.*/merge.*）
    events = {
        e async for e in PlanSessionEvent.objects.filter(session_id=session.id).values_list(
            "event", flat=True
        )
    }
    assert {
        "repo.routing",
        "knowledge.recalling",
        "repo.research.started",
        "repo.research.completed",
        "plan.merge.started",
        "plan.merge.completed",
    } <= events

    # 无真实容器：dispatch 被 mock（无网络/容器调用）
    assert dispatcher.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_e2e_clarification_loop_reruns_only_affected() -> None:
    """merge 验证失败 → 澄清（affected=taskA）→ answer → 仅 taskA 重跑、taskB 复用 → done。"""
    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")
    session = await PlanSessionService().create_session(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        decomposition={
            "requirement_text": "为 A/B 两仓做跨仓方案（含澄清回路）",
            "include_repos": [str(repo_a.id), str(repo_b.id)],
        },
    )
    candidates = [
        {"repo_id": str(repo_a.id), "confidence": "high"},
        {"repo_id": str(repo_b.id), "confidence": "high"},
    ]
    # 首次融合失败（空方案）→ 回退 clarifying；二次融合成功
    synth = _FakeSynth(str(repo_a.id), str(repo_b.id), fail_first=True)

    class _StatefulClarify:
        """注入 ClarifyProtocol（IO 边界）：仅第 2 次进入 clarifying 时澄清，affected=taskA。"""

        def __init__(self) -> None:
            self.calls = 0

        async def clarify(self, sess: PlanSession) -> dict:
            self.calls += 1
            # call#1 = 研究前直通；call#2 = merge 失败回退后澄清（此时 task 已存在）
            if self.calls == 2:
                task_a = await RepoResearchTask.objects.filter(
                    session_id=sess.id, repository_id=repo_a.id
                ).afirst()
                affected = [task_a.id] if task_a is not None else []
                clar = await ClarificationService().create_clarification(
                    sess, "请澄清 repoA 的契约", affected
                )
                await PlanSessionService()._emit_event(
                    "clarification.asked",
                    sess,
                    {"clarification_id": str(clar.id), "question": "请澄清 repoA 的契约"},
                )
                return {"needs_clarification": True, "clarification_id": str(clar.id)}
            return {"needs_clarification": False}

    engine = _engine(router_candidates=candidates, synth=synth, clarify=_StatefulClarify())

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)
        ),
    ):
        session = await _drive(engine, session, exposer_id=str(repo_a.id))

    assert session.status == PlanSessionStatus.DONE

    # 澄清确实发生（DB 有已答 Clarification，affected=taskA）
    clar = await Clarification.objects.filter(session_id=session.id).afirst()
    assert clar is not None
    assert clar.answered_at is not None

    # taskB partial 全程复用（未失效）；taskA 经 stale 重跑后有新的 valid partial
    task_a = await RepoResearchTask.objects.filter(
        session_id=session.id, repository_id=repo_a.id
    ).afirst()
    task_b = await RepoResearchTask.objects.filter(
        session_id=session.id, repository_id=repo_b.id
    ).afirst()
    # taskA 重跑：曾有 invalidated（clarification）partial + 新 valid partial
    a_invalidated = await PartialPlan.objects.filter(
        research_task_id=task_a.id, valid=False, invalidated_reason="clarification"
    ).acount()
    a_valid = await PartialPlan.objects.filter(
        research_task_id=task_a.id, valid=True
    ).acount()
    assert a_invalidated == 1
    assert a_valid == 1
    # taskB 复用：始终单一 valid partial，从未失效
    b_valid = await PartialPlan.objects.filter(
        research_task_id=task_b.id, valid=True
    ).acount()
    b_invalidated = await PartialPlan.objects.filter(
        research_task_id=task_b.id, valid=False
    ).acount()
    assert b_valid == 1
    assert b_invalidated == 0

    # taskA 经 stale 重派后回到 done（重跑成功）；taskB 始终 done（复用未重派）
    assert task_a.status == RepoResearchTaskStatus.DONE
    assert task_b.status == RepoResearchTaskStatus.DONE
