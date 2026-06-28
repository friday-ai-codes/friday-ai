"""SC-2 入口无关一致性守护测试（ENTRY-02，IO 边界 mock）。

证明「同一 engine、同一 stage graph → 入口无关一致产物」：相同需求 + 相同 include_repos，
分别经 ``start_orchestration(entrypoint="workflow")`` 与 ``start_orchestration(entrypoint="chat",
work_item=None)`` 建两 ConvergenceSession，用**结构相同的**注入 engine（同 _FakeSynth 产同一
§7 MergedPlan、同 mock router/recall、真实 ResearchDispatchAdapter + ArchitectMergeAdapter）
分别驱动到 done。断言：

- 两 session 各自 current_artifact_version 对应 ArtifactVersion.content **结构等价**。
- 两 session 的 §15 事件 taxonomy **序列相同**（按 created 顺序取 ConvergenceSessionEvent.event）。

真实 LLM / 容器端到端沿用既有 deferred（mock 在 IO 边界），范式取材 test_plan_research_e2e.py。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import (
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEvent,
    ConvergenceSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ConvergenceSessionService
from repositories.models import Repository
from services.process_runtime import (
    ArchitectMergeAdapter,
    ClarifyAdapter,
    ProcessEngine,
    ResearchDispatchAdapter,
    aall_research_tasks_terminal,
    start_orchestration,
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
    """架构师 LLM 合成器 fake（IO 边界）：直接返回同一合法 §7 MergedPlan。"""

    def __init__(self, repo_a: str, repo_b: str) -> None:
        self.repo_a = repo_a
        self.repo_b = repo_b

    async def synthesize(self, session: Any, partials: list[dict]) -> dict:
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


async def _complete_running_tasks(session: ConvergenceSession, exposer_id: str) -> None:
    """模拟容器回调：对所有 running RepoResearchTask 调真实 _handle_research_completion。"""
    from subagent.api.callbacks import _handle_research_completion
    from subagent.models import SubAgentSession

    tasks = [
        t
        async for t in RepoResearchTask.objects.filter(
            session_id=session.id, status=RepoResearchTaskStatus.RUNNING
        ).order_by("created_at")
    ]
    for task in tasks:
        sub = await SubAgentSession.objects.aget(id=task.subagent_session_id)
        content = _repo_content(str(task.repository_id), exposer_id)
        await _handle_research_completion(sub, content, _log())


async def _drive(
    engine: ProcessEngine,
    session: ConvergenceSession,
    *,
    exposer_id: str,
    max_iter: int = 40,
) -> ConvergenceSession:
    """通用驱动：advance + waiting_event(在途) 完成容器回调（无澄清直通）。"""
    for _ in range(max_iter):
        session = await ConvergenceSession.objects.aget(id=session.id)
        if session.status in (
            ConvergenceSessionStatus.DONE,
            ConvergenceSessionStatus.FAILED,
        ):
            return session
        if session.status == ConvergenceSessionStatus.WAITING_EVENT:
            if not await aall_research_tasks_terminal(session.id):
                running = await RepoResearchTask.objects.filter(
                    session_id=session.id, status=RepoResearchTaskStatus.RUNNING
                ).aexists()
                if running:
                    await _complete_running_tasks(session, exposer_id)
                    continue
        await engine.advance(session)
    return await ConvergenceSession.objects.aget(id=session.id)


def _make_engine(candidates: list[dict], repo_a: str, repo_b: str) -> ProcessEngine:
    """结构相同的注入 engine：同 mock router/recall + 真实 research/merge（同 _FakeSynth）。"""
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": candidates})
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "需求", "kinds": []})
    deps = SimpleNamespace(
        router=router,
        recall=recall,
        research=ResearchDispatchAdapter(),
        merge=ArchitectMergeAdapter(synthesizer=_FakeSynth(repo_a, repo_b)),
        clarify=ClarifyAdapter(),
    )
    return ProcessEngine(session_service=ConvergenceSessionService(), deps=deps)


async def _event_sequence(session_id: Any) -> list[str]:
    """按 created 顺序取 §15 事件 taxonomy 序列。"""
    return [
        e
        async for e in ConvergenceSessionEvent.objects.filter(session_id=session_id)
        .order_by("created_at")
        .values_list("event", flat=True)
    ]


@pytest.mark.asyncio
async def test_chat_and_workflow_entries_yield_equivalent_merged_plan() -> None:
    """SC-2：chat 与 workflow 两入口经同一 engine → 结构等价 MergedPlan + 同序 §15 事件。"""
    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")
    requirement = "为 A/B 两仓做跨仓方案"
    include_repos = [str(repo_a.id), str(repo_b.id)]
    candidates = [
        {"repo_id": str(repo_a.id), "confidence": "high"},
        {"repo_id": str(repo_b.id), "confidence": "high"},
    ]

    session_wf = await start_orchestration(
        entrypoint="workflow",
        requirement_text=requirement,
        include_repos=include_repos,
    )
    session_chat = await start_orchestration(
        entrypoint="chat",
        requirement_text=requirement,
        work_item=None,
        include_repos=include_repos,
    )

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)
        ),
    ):
        engine_wf = _make_engine(candidates, str(repo_a.id), str(repo_b.id))
        session_wf = await _drive(engine_wf, session_wf, exposer_id=str(repo_a.id))
        engine_chat = _make_engine(candidates, str(repo_a.id), str(repo_b.id))
        session_chat = await _drive(engine_chat, session_chat, exposer_id=str(repo_a.id))

    assert session_wf.status == ConvergenceSessionStatus.DONE
    assert session_chat.status == ConvergenceSessionStatus.DONE

    # 1) MergedPlan content 结构等价（同一融合产物）
    av_wf = await ArtifactVersion.objects.aget(id=session_wf.current_artifact_version_id)
    av_chat = await ArtifactVersion.objects.aget(id=session_chat.current_artifact_version_id)
    assert av_wf.content == av_chat.content
    assert av_wf.content["dependency_dag"] == {str(repo_b.id): [str(repo_a.id)]}
    t2_wf = next(t for t in av_wf.content["execution_plan"] if t["id"] == "t2")
    t2_chat = next(t for t in av_chat.content["execution_plan"] if t["id"] == "t2")
    assert t2_wf["dependencies"] == t2_chat["dependencies"] == ["t1"]

    # 2) §15 事件 taxonomy 序列相同（入口无关一致 trace）
    seq_wf = await _event_sequence(session_wf.id)
    seq_chat = await _event_sequence(session_chat.id)
    assert seq_wf == seq_chat
    assert "repo.routing" in seq_wf
    assert "knowledge.recalling" in seq_wf
    assert "technical_plan.merge.completed" in seq_wf

    # 3) INV-2：两入口 work_item 均为 None
    assert session_wf.work_item_id is None
    assert session_chat.work_item_id is None
