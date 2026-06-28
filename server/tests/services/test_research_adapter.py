"""ResearchDispatchAdapter 单测（Phase 39-03，RESEARCH-01）。

**真实容器 E2E DEFERRED**：本测试全程 mock dispatcher / runner 在线查询（mirror
``test_callbacks_cross_repo_relevance`` 范式），覆盖 filter 分流 / 容器派发回填 running /
prompt 注入 / no-candidates no-op / runner offline 降级 / repo.research.started 事件；
真实 runner + docker + 编码 agent 端到端验收延后（沿用既有里程碑惯例）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from services.process_runtime import ResearchDispatchAdapter
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


def _make_repo(name: str) -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://github.com/test/{name}-{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


@pytest.fixture
def session_with_candidates(db):
    """建 PlanSession，routing.candidates 含 high/medium/low 各一仓。"""
    repo_high = _make_repo("high")
    repo_medium = _make_repo("medium")
    repo_low = _make_repo("low")
    session = ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        stage_state={
            "decomposition": {"requirement_text": "统一鉴权改造"},
            "recall_context": [{"kind": "work_item", "title": "历史鉴权需求", "score": 0.9}],
            "routing": {
                "candidates": [
                    {"repo_id": str(repo_high.id), "confidence": "high", "repository_name": "high"},
                    {"repo_id": str(repo_medium.id), "confidence": "medium", "repository_name": "medium"},
                    {"repo_id": str(repo_low.id), "confidence": "low", "repository_name": "low"},
                ]
            },
        },
    )
    return session, repo_high, repo_medium, repo_low


def _mock_dispatcher():
    """返回 (get_dispatcher patch target, captured dispatch tasks list)。"""
    captured: list = []
    dispatcher = MagicMock()

    async def _dispatch(task):
        captured.append(task)

    dispatcher.dispatch = AsyncMock(side_effect=_dispatch)
    return dispatcher, captured


@pytest.mark.asyncio
async def test_filter_deep_vs_light(session_with_candidates) -> None:
    """high/medium 仓建 task + 派容器；low 仓不派容器、直接有 valid PartialPlan（轻量合成）。"""
    session, repo_high, repo_medium, repo_low = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)),
    ):
        result = await adapter.dispatch(session)

    assert len(result["dispatched"]) == 2
    assert len(result["light"]) == 1
    assert result["runner_offline"] is False
    # 容器派发 2 次（high/medium）
    assert dispatcher.dispatch.await_count == 2

    # low 仓有 valid PartialPlan，无容器
    low_task = await RepoResearchTask.objects.aget(session=session, repository=repo_low)
    assert low_task.status == RepoResearchTaskStatus.DONE
    low_partial = await PartialPlan.objects.aget(research_task=low_task)
    assert low_partial.valid is True
    assert low_task.subagent_session_id is None


@pytest.mark.asyncio
async def test_deep_dispatch_backfills_running(session_with_candidates) -> None:
    """high 仓 dispatch 后 status=running + subagent_session 非空 + task_type=PLAN + source=plan_research。"""
    session, repo_high, repo_medium, repo_low = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=2)),
    ):
        await adapter.dispatch(session)

    high_task = await RepoResearchTask.objects.aget(session=session, repository=repo_high)
    assert high_task.status == RepoResearchTaskStatus.RUNNING
    assert high_task.subagent_session_id is not None
    sub = await SubAgentSession.objects.aget(id=high_task.subagent_session_id)
    assert sub.task_type == SubAgentSession.TaskType.PLAN
    assert sub.last_output.get("source") == "plan_research"
    assert sub.last_output.get("research_task_id") == str(high_task.id)


@pytest.mark.asyncio
async def test_prompt_injects_context(session_with_candidates) -> None:
    """捕获 DispatchTask.prompt：含 recall 摘要 + requirement_text + §7 字段名。"""
    session, *_ = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)),
    ):
        await adapter.dispatch(session)

    assert captured, "应至少捕获一个 DispatchTask"
    prompt = captured[0].prompt
    assert "统一鉴权改造" in prompt  # requirement_text
    assert "历史鉴权需求" in prompt  # recall_context 摘要
    for field in (
        "research_summary",
        "proposed_changes",
        "candidate_files",
        "api_contracts_exposed",
        "dependencies_on_other_repos",
    ):
        assert field in prompt
    # task_type=plan
    assert captured[0].task_type == "plan"


@pytest.mark.asyncio
async def test_no_candidates_noop() -> None:
    """routing 空 candidates → 不建 task、不派容器、返回 skipped=no_candidates。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        stage_state={"routing": {}},
    )
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    with patch("runners.dispatcher.get_dispatcher", return_value=dispatcher):
        result = await adapter.dispatch(session)

    assert result.get("skipped") == "no_candidates"
    assert dispatcher.dispatch.await_count == 0
    assert await RepoResearchTask.objects.filter(session=session).acount() == 0


@pytest.mark.asyncio
async def test_runner_offline_degrades(session_with_candidates) -> None:
    """runner count==0 + 存在 deep_repos → deep 仓降级为轻量 PartialPlan（不抛），runner_offline=True。"""
    session, repo_high, repo_medium, repo_low = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=0)),
    ):
        result = await adapter.dispatch(session)

    assert result["runner_offline"] is True
    assert result["dispatched"] == []
    assert len(result["light"]) == 3  # high+medium+low 全降级为轻量
    assert dispatcher.dispatch.await_count == 0
    # 三仓都有 valid PartialPlan
    count = await PartialPlan.objects.filter(research_task__session=session, valid=True).acount()
    assert count == 3


@pytest.mark.asyncio
async def test_emits_research_started(session_with_candidates) -> None:
    """每个 deep 仓 emit 一次 repo.research.started，payload 含 repo_id/task_id。"""
    session, repo_high, repo_medium, repo_low = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)),
    ):
        await adapter.dispatch(session)

    started = [
        call for call in spy.call_args_list
        if call.args and call.args[0] == "repo.research.started"
    ]
    assert len(started) == 2
    for call in started:
        payload = call.args[2]
        assert "repo_id" in payload
        assert "task_id" in payload


@pytest.mark.asyncio
async def test_dispatch_idempotent_on_re_advance(session_with_candidates) -> None:
    """WR-01：同一 session 二次 dispatch 不重派已 running 的 deep 容器、不为已 done 的
    light 仓重复落 PartialPlan（resume-幂等）。"""
    session, repo_high, repo_medium, repo_low = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=2)),
    ):
        result1 = await adapter.dispatch(session)
        result2 = await adapter.dispatch(session)

    # 第一次派发 2 个 deep 容器 + 1 个 light partial
    assert len(result1["dispatched"]) == 2
    assert len(result1["light"]) == 1
    # 第二次 re-advance：deep 已 running、light 已 done → 全部跳过
    assert result2["dispatched"] == []
    assert result2["light"] == []
    # 容器只派发一次（不重派）
    assert dispatcher.dispatch.await_count == 2
    # task 不重建（仍 3 个）
    assert await RepoResearchTask.objects.filter(session=session).acount() == 3
    # light partial 不重复累积（仍 1 条）
    low_task = await RepoResearchTask.objects.aget(session=session, repository=repo_low)
    assert await PartialPlan.objects.filter(research_task=low_task).acount() == 1


@pytest.mark.asyncio
async def test_per_repo_dispatch_isolation(session_with_candidates) -> None:
    """WR-02：一个 deep 仓 dispatch 抛异常仅标该 task failed，其它 deep 仓仍正常派发，
    整个 dispatch 不中断（RESEARCH-02 单仓隔离）。"""
    session, repo_high, repo_medium, repo_low = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    # 第一个被派发的 deep 仓抛异常，后续仓正常
    original = adapter._dispatch_deep_task
    call_state = {"n": 0}

    async def _flaky(sess, task):
        call_state["n"] += 1
        if call_state["n"] == 1:
            raise RuntimeError("dispatch boom")
        return await original(sess, task)

    adapter._dispatch_deep_task = _flaky

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=2)),
    ):
        result = await adapter.dispatch(session)

    # 整个 dispatch 不抛（result 正常返回）
    assert "dispatched" in result
    # 两个 deep 仓：一个 failed、一个正常 running
    deep_tasks = [
        t
        async for t in RepoResearchTask.objects.filter(
            session=session, repository__in=[repo_high, repo_medium]
        )
    ]
    statuses = sorted(t.status for t in deep_tasks)
    assert RepoResearchTaskStatus.FAILED in statuses
    assert RepoResearchTaskStatus.RUNNING in statuses
    # failed 仓 error 记录 dispatch_failed
    failed_task = next(t for t in deep_tasks if t.status == RepoResearchTaskStatus.FAILED)
    assert failed_task.error.get("reason") == "dispatch_failed"
    # 只成功派发一个仓
    assert len(result["dispatched"]) == 1


@pytest.mark.asyncio
async def test_duplicate_candidates_deduped(db) -> None:
    """IN-02：candidates 含重复 repo_id → 去重，同一 light 仓只落一条 PartialPlan、一个 task。"""
    repo_low = await Repository.objects.acreate(
        name=f"dup-low-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/dup-{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        stage_state={
            "routing": {
                "candidates": [
                    {"repo_id": str(repo_low.id), "confidence": "low"},
                    {"repo_id": str(repo_low.id), "confidence": "low"},  # 重复
                ]
            }
        },
    )
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    with patch("runners.dispatcher.get_dispatcher", return_value=dispatcher):
        result = await adapter.dispatch(session)

    assert len(result["light"]) == 1
    assert await RepoResearchTask.objects.filter(session=session).acount() == 1
    low_task = await RepoResearchTask.objects.aget(session=session, repository=repo_low)
    assert await PartialPlan.objects.filter(research_task=low_task).acount() == 1


@pytest.mark.asyncio
async def test_missing_git_url_fails_task_without_container(db) -> None:
    """IN-03：deep 仓缺 git_url → mark_failed + repo.research.failed，不派占位 URL 容器。"""
    repo = await Repository.objects.acreate(
        name=f"nogit-{uuid.uuid4().hex[:6]}",
        git_url="",  # 缺 git_url
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        stage_state={"routing": {"candidates": [{"repo_id": str(repo.id), "confidence": "high"}]}},
    )
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()
    spy = AsyncMock()
    adapter.session_service._emit_event = spy

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)),
    ):
        result = await adapter.dispatch(session)

    # 不派容器、不计入 dispatched
    assert dispatcher.dispatch.await_count == 0
    assert result["dispatched"] == []
    task = await RepoResearchTask.objects.aget(session=session, repository=repo)
    assert task.status == RepoResearchTaskStatus.FAILED
    assert task.error.get("reason") == "missing_git_url"
    failed = [
        c for c in spy.call_args_list if c.args and c.args[0] == "repo.research.failed"
    ]
    assert len(failed) == 1


@pytest.mark.asyncio
async def test_writes_only_via_service(session_with_candidates) -> None:
    """deep 仓 task 经 ResearchService 建（行为层确认；旁路由 39-02 INV-6 grep 守护兜底）。"""
    session, repo_high, repo_medium, repo_low = session_with_candidates
    dispatcher, captured = _mock_dispatcher()
    adapter = ResearchDispatchAdapter()

    create_spy = AsyncMock(wraps=adapter.research_service.create_tasks_for_session)
    adapter.research_service.create_tasks_for_session = create_spy

    with (
        patch("runners.dispatcher.get_dispatcher", return_value=dispatcher),
        patch.object(ResearchDispatchAdapter, "_count_online_runners", new=AsyncMock(return_value=1)),
    ):
        await adapter.dispatch(session)

    assert create_spy.await_count >= 1
    # 所有 task 经 service 落库
    total = await RepoResearchTask.objects.filter(session=session).acount()
    assert total == 3
