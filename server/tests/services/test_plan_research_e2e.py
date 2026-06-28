"""端到端 technical_plan 编排测试（Chassis v2 · P2，IO 边界 mock）。

真实 ``ProcessEngine`` + 真实 service（``ConvergenceSessionService`` / ``ResearchService`` /
``ClarificationService`` / ``ArtifactService``）+ 真实 PlanValidator/merged_plan schema +
真实 ``ResearchDispatchAdapter`` / ``ArchitectMergeAdapter``，仅在 **IO 边界 mock**：
- router/recall（LLM/检索）→ 注入 AsyncMock。
- 容器调度（get_dispatcher().dispatch）+ runner 在线计数 → monkeypatch。
- 容器回调 → 直接调 ``subagent.api.callbacks._handle_research_completion``。
- merge synthesizer（LLM）→ 注入 fake 返回合法 §7 MergedPlan。

覆盖：需求 → 拆分→路由→召回→澄清→并行调研→融合 → 带跨仓依赖的 technical_plan
``ArtifactVersion`` + trace 事件持久化 + 澄清回路（仅 affected partial 重跑）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import (
    ArtifactVersion,
    Clarification,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ConvergenceSessionStatus,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ClarificationService, ConvergenceSessionService
from repositories.models import Repository
from services.process_runtime import (
    ArchitectMergeAdapter,
    ClarifyAdapter,
    ProcessEngine,
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
    def __init__(self, repo_a: str, repo_b: str, *, fail_first: bool = False) -> None:
        self.repo_a = repo_a
        self.repo_b = repo_b
        self.fail_first = fail_first
        self.calls = 0

    async def synthesize(self, session: Any, partials: list[dict]) -> dict:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            return {"title": "x", "summary": "y", "execution_plan": []}
        return _valid_merged(self.repo_a, self.repo_b)


def _repo_content(repository_id: str, exposer_id: str) -> dict:
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
    engine: ProcessEngine,
    session: ConvergenceSession,
    *,
    exposer_id: str,
    answer_text: str = "用 repoA 与 repoB",
    max_iter: int = 40,
) -> ConvergenceSession:
    """通用驱动：advance + 在 waiting_clarification(pending) 答复 / waiting_event(在途) 完成回调。"""
    for _ in range(max_iter):
        session = await ConvergenceSession.objects.aget(id=session.id)
        if session.status in (
            ConvergenceSessionStatus.DONE,
            ConvergenceSessionStatus.FAILED,
        ):
            return session
        if session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION:
            if await ClarificationService().ahas_pending(session.id):
                from delivery.models import ClarificationQuestion

                pending = await Clarification.objects.filter(
                    session_id=session.id, answered_at__isnull=True
                ).afirst()
                if pending is not None:
                    answers = [
                        {"question_id": str(qid), "selected": None, "freeform_text": answer_text}
                        async for qid in ClarificationQuestion.objects.filter(
                            clarification_id=pending.id, answered_at__isnull=True
                        ).values_list("id", flat=True)
                    ]
                    if answers:
                        await ClarificationService().answer_round(pending, answers)
                    continue
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


def _engine(*, router_candidates, synth, clarify, node_execution_id: str = "") -> ProcessEngine:
    router = AsyncMock()
    router.route = AsyncMock(return_value={"candidates": router_candidates})
    recall = AsyncMock()
    recall.recall = AsyncMock(return_value={"hits": [], "query": "需求", "kinds": []})
    deps = SimpleNamespace(
        router=router,
        recall=recall,
        research=ResearchDispatchAdapter(node_execution_id=node_execution_id),
        merge=ArchitectMergeAdapter(synthesizer=synth),
        clarify=clarify,
    )
    return ProcessEngine(session_service=ConvergenceSessionService(), deps=deps)


@pytest.mark.asyncio
async def test_research_suspend_resume_reaches_done_via_node_execution() -> None:
    """researching 段 waiting_event 的 resume 通路打通（工作流入口节点 + 容器回调续推）。"""
    from projects.models import Space
    from subagent.models import SubAgentSession
    from workflows.models import (
        NodeExecution,
        Workflow,
        WorkflowExecution,
        WorkflowNode,
    )
    from workflows.nodes.ai.plan_research import AIPlanResearchNode
    from workflows.nodes.base import ExecutionContext as _ExecCtx

    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")

    project = await Space.objects.acreate(name=f"proj-{uuid.uuid4().hex[:6]}")
    workflow = await Workflow.objects.acreate(name="编排工作流", space=project)
    wf_node = await WorkflowNode.objects.acreate(
        workflow=workflow, node_type="ai_plan_research", name="AI 方案编排"
    )
    wf_exec = await WorkflowExecution.objects.acreate(
        workflow=workflow, space=project, trigger_type="manual"
    )
    node_exec = await NodeExecution.objects.acreate(
        workflow_execution=wf_exec, node=wf_node, status="running"
    )

    candidates = [
        {"repo_id": str(repo_a.id), "confidence": "high"},
        {"repo_id": str(repo_b.id), "confidence": "high"},
    ]
    synth = _FakeSynth(str(repo_a.id), str(repo_b.id))
    clarify = AsyncMock()
    clarify.clarify = AsyncMock(return_value={"needs_clarification": False})
    engine = _engine(
        router_candidates=candidates,
        synth=synth,
        clarify=clarify,
        node_execution_id=str(node_exec.id),
    )

    node = AIPlanResearchNode()
    node._build_engine = lambda context, session: engine  # type: ignore[assignment]
    ctx = _ExecCtx(
        execution_id=str(wf_exec.id),
        node_id=str(wf_node.id),
        node_config={"requirement_text": "为 A/B 两仓做跨仓方案"},
        input_data={},
        workflow_context={},
        previous_outputs={},
        node_execution=node_exec,
    )

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(
            ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)
        ),
    ):
        result = await node.execute(ctx)
        assert result.status == "waiting_event"
        assert result.output["kind"] == "research"

        subs = [s async for s in SubAgentSession.objects.filter(node_execution=node_exec)]
        assert len(subs) == 2
        assert all(s.node_execution_id == node_exec.id for s in subs)
        assert dispatcher.dispatch.await_count == 2

        node_exec.output_data = result.output
        await node_exec.asave(update_fields=["output_data"])

        session = await ConvergenceSession.objects.aget(id=result.output["session_id"])
        await _complete_running_tasks(session, exposer_id=str(repo_a.id))

        result2 = await node.execute(ctx)

    assert result2.status == "completed"
    assert result2.output["artifact_version_id"]
    session = await ConvergenceSession.objects.aget(id=session.id)
    assert session.status == ConvergenceSessionStatus.DONE
    assert session.current_artifact_version_id is not None


@pytest.mark.asyncio
async def test_e2e_requirement_to_merged_plan_with_cross_repo_deps() -> None:
    """需求经六段编排 → 带跨仓依赖的 technical_plan ArtifactVersion + trace 事件覆盖。"""
    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")
    session = await ConvergenceSessionService().create_session(
        "technical_plan",
        ConvergenceSessionEntrypoint.WORKFLOW,
        stage_state={
            "decomposition": {
                "requirement_text": "为 A/B 两仓做跨仓方案",
                "include_repos": [str(repo_a.id), str(repo_b.id)],
            }
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

    assert session.status == ConvergenceSessionStatus.DONE
    assert session.current_artifact_version_id is not None

    av = await ArtifactVersion.objects.aget(id=session.current_artifact_version_id)
    content = av.content
    assert content["dependency_dag"] == {str(repo_b.id): [str(repo_a.id)]}
    t2 = next(t for t in content["execution_plan"] if t["id"] == "t2")
    assert t2["dependencies"] == ["t1"]
    assert t2["dependencies_on_other_repos"] == ["ContractX"]

    events = {
        e
        async for e in ConvergenceSessionEvent.objects.filter(session_id=session.id).values_list(
            "event", flat=True
        )
    }
    assert {
        "repo.routing",
        "knowledge.recalling",
        "repo.research.started",
        "repo.research.completed",
        "technical_plan.merge.started",
        "technical_plan.merge.completed",
    } <= events

    assert dispatcher.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_e2e_clarification_loop_reruns_only_affected() -> None:
    """merge 验证失败 → 澄清（affected=taskA）→ answer → 仅 taskA 重跑、taskB 复用 → done。"""
    repo_a = await _make_repo("repoA")
    repo_b = await _make_repo("repoB")
    session = await ConvergenceSessionService().create_session(
        "technical_plan",
        ConvergenceSessionEntrypoint.WORKFLOW,
        stage_state={
            "decomposition": {
                "requirement_text": "为 A/B 两仓做跨仓方案（含澄清回路）",
                "include_repos": [str(repo_a.id), str(repo_b.id)],
            }
        },
    )
    candidates = [
        {"repo_id": str(repo_a.id), "confidence": "high"},
        {"repo_id": str(repo_b.id), "confidence": "high"},
    ]
    synth = _FakeSynth(str(repo_a.id), str(repo_b.id), fail_first=True)

    class _StatefulClarify:
        def __init__(self) -> None:
            self.calls = 0

        async def clarify(self, sess: ConvergenceSession) -> dict:
            self.calls += 1
            if self.calls == 2:
                clar = await ClarificationService().create_round(
                    sess,
                    [
                        {
                            "question": "请澄清 repoA 的契约",
                            "type": "single",
                            "options": [],
                            "recommended": [],
                        }
                    ],
                )
                await ConvergenceSessionService()._emit_event(
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

    assert session.status == ConvergenceSessionStatus.DONE

    # P3 process-agnostic 澄清：merge 校验失败 → 经注入 clarify 建结构化澄清轮 → 答复后放行
    # 重融合至 done。注：旧 ``affected_partials`` 选择性重跑（按受影响 partial 失效）已随
    # 澄清 process-agnostic 化删除，故此处只断言「澄清回路真实驱动到 done + 两仓调研终态」。
    clar = await Clarification.objects.filter(session_id=session.id).afirst()
    assert clar is not None
    assert clar.answered_at is not None

    task_a = await RepoResearchTask.objects.filter(
        session_id=session.id, repository_id=repo_a.id
    ).afirst()
    task_b = await RepoResearchTask.objects.filter(
        session_id=session.id, repository_id=repo_b.id
    ).afirst()
    assert task_a.status == RepoResearchTaskStatus.DONE
    assert task_b.status == RepoResearchTaskStatus.DONE
