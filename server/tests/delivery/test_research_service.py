"""ResearchService 行为测试（Phase 39-02，DOMAIN §6/§14）。

覆盖 <behavior>：建任务幂等 / 状态转移表 / record_partial 落 §7 + hash + done /
retry 单仓隔离（RESEARCH-02）/ 非 failed retry raise / invalidate stale（RESEARCH-03）。
"""

from __future__ import annotations

import uuid
from io import StringIO

import pytest
from django.core.management import call_command

from agents.models import AgentSession
from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from delivery.services import ResearchService
from repositories.models import Repository
from subagent.models import SubAgentSession

pytestmark = pytest.mark.django_db(transaction=True)


def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_session() -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )


def _sample_content(repo_id: str) -> dict:
    return {
        "repository_id": repo_id,
        "research_summary": "本仓需新增鉴权中间件",
        "proposed_changes": [{"file": "auth.py", "desc": "加 JWT"}],
        "candidate_files": ["auth.py"],
        "api_contracts_exposed": [{"name": "verify_token"}],
        "dependencies_on_other_repos": [],
    }


@pytest.mark.asyncio
async def test_create_tasks_idempotent() -> None:
    """同 deep_repos 两次 create → RepoResearchTask 数不翻倍（get_or_create 幂等）。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    deep = [{"repository_id": str(repo.id), "routed_confidence": "high"}]
    svc = ResearchService()
    first = await svc.create_tasks_for_session(session, deep)
    second = await svc.create_tasks_for_session(session, deep)

    assert len(first) == 1
    assert len(second) == 1
    assert first[0].id == second[0].id
    count = await RepoResearchTask.objects.filter(session=session).acount()
    assert count == 1
    assert first[0].routed_confidence == "high"


@pytest.mark.asyncio
async def test_state_transitions_table() -> None:
    """pending→running→done；另一 task →failed + error 落库。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo_a = await Repository.objects.acreate(
        name=f"a-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    repo_b = await Repository.objects.acreate(
        name=f"b-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    agent = await AgentSession.objects.acreate(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    sub = await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=agent,
        repo_url="https://x/r.git",
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.PENDING,
    )
    svc = ResearchService()
    task_a = await RepoResearchTask.objects.acreate(
        session=session,
        repository=repo_a,
        error={"reason": "previous_attempt_failed"},
    )
    task_b = await RepoResearchTask.objects.acreate(session=session, repository=repo_b)

    await svc.mark_running(task_a, sub)
    await task_a.arefresh_from_db()
    assert task_a.status == RepoResearchTaskStatus.RUNNING
    assert task_a.subagent_session_id == sub.id
    assert task_a.error == {}

    await svc.mark_done(task_a)
    await task_a.arefresh_from_db()
    assert task_a.status == RepoResearchTaskStatus.DONE
    assert task_a.error == {}

    await svc.mark_failed(task_b, {"reason": "boom"})
    await task_b.arefresh_from_db()
    assert task_b.status == RepoResearchTaskStatus.FAILED
    assert task_b.error == {"reason": "boom"}


@pytest.mark.asyncio
async def test_mark_failed_wraps_non_dict() -> None:
    """mark_failed 非 dict error 包成 {"message": str}。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    task = await RepoResearchTask.objects.acreate(session=session, repository=repo)
    await ResearchService().mark_failed(task, "string error")
    await task.arefresh_from_db()
    assert task.error == {"message": "string error"}


@pytest.mark.asyncio
async def test_record_partial_done_and_hash() -> None:
    """record_partial → PartialPlan.valid True + content_hash 非空 + 两次同内容 hash 一致；task done。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    svc = ResearchService()
    task = await RepoResearchTask.objects.acreate(session=session, repository=repo)
    content = _sample_content(str(repo.id))
    partial = await svc.record_partial(task, content)

    assert partial.valid is True
    assert partial.content_hash
    assert partial.content == content
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.DONE

    # 同内容再 record → hash 一致
    task2 = await RepoResearchTask.objects.acreate(session=session, repository=repo)
    partial2 = await svc.record_partial(task2, content)
    assert partial2.content_hash == partial.content_hash


@pytest.mark.asyncio
async def test_retry_task_isolation() -> None:
    """RESEARCH-02 核心：retry_task(A failed) → A pending + attempt=1；B/C 与 session 不变。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repos = [
        await Repository.objects.acreate(
            name=f"r-{uuid.uuid4().hex[:6]}",
            git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
            git_platform="github",
            default_branch="main",
            index_status="indexed",
        )
        for _ in range(3)
    ]
    task_a = await RepoResearchTask.objects.acreate(
        session=session, repository=repos[0], status=RepoResearchTaskStatus.FAILED
    )
    task_b = await RepoResearchTask.objects.acreate(
        session=session, repository=repos[1], status=RepoResearchTaskStatus.RUNNING
    )
    task_c = await RepoResearchTask.objects.acreate(
        session=session, repository=repos[2], status=RepoResearchTaskStatus.DONE
    )
    svc = ResearchService()
    retried = await svc.retry_task(task_a)

    assert retried.status == RepoResearchTaskStatus.PENDING
    assert retried.attempt == 1
    await task_b.arefresh_from_db()
    await task_c.arefresh_from_db()
    assert task_b.status == RepoResearchTaskStatus.RUNNING
    assert task_b.attempt == 0
    assert task_c.status == RepoResearchTaskStatus.DONE
    await session.arefresh_from_db()
    assert session.current_stage == "research"


@pytest.mark.asyncio
async def test_retry_non_failed_raises() -> None:
    """对 running task retry → ValueError。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.RUNNING
    )
    with pytest.raises(ValueError):
        await ResearchService().retry_task(task)


@pytest.mark.asyncio
async def test_retry_stale_task_resets_pending() -> None:
    """IN-01：stale 任务（重索引失效）可经 retry_task 复位 pending（与 failed 对等的恢复路径）。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.STALE
    )
    retried = await ResearchService().retry_task(task)
    assert retried.status == RepoResearchTaskStatus.PENDING
    assert retried.attempt == 1


@pytest.mark.asyncio
async def test_retry_rejected_when_session_not_researching() -> None:
    """IN-01：session 已 merging（barrier 已 fire）时 retry failed 任务被拒，避免状态不一致。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="merge",
        status=ConvergenceSessionStatus.RUNNING,
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.FAILED
    )
    with pytest.raises(ValueError):
        await ResearchService().retry_task(task)
    # 任务未被复位
    await task.arefresh_from_db()
    assert task.status == RepoResearchTaskStatus.FAILED


@pytest.mark.asyncio
async def test_invalidate_for_repo_stale() -> None:
    """RESEARCH-03 核心：invalidate_for_repo(X) → partial 失效 + task stale + 计数=1；其他 repo 不受影响；幂等。"""
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo_x = await Repository.objects.acreate(
        name=f"x-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    repo_y = await Repository.objects.acreate(
        name=f"y-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
    svc = ResearchService()
    task_x = await RepoResearchTask.objects.acreate(session=session, repository=repo_x)
    await svc.record_partial(task_x, _sample_content(str(repo_x.id)))
    task_y = await RepoResearchTask.objects.acreate(session=session, repository=repo_y)
    partial_y = await svc.record_partial(task_y, _sample_content(str(repo_y.id)))

    count = await svc.invalidate_for_repo(str(repo_x.id))
    assert count == 1

    px = await PartialPlan.objects.aget(research_task=task_x)
    assert px.valid is False
    assert px.invalidated_reason == "repo_reindexed"
    await task_x.arefresh_from_db()
    assert task_x.status == RepoResearchTaskStatus.STALE

    # 其他 repo 不受影响
    py = await PartialPlan.objects.aget(id=partial_y.id)
    assert py.valid is True
    await task_y.arefresh_from_db()
    assert task_y.status == RepoResearchTaskStatus.DONE

    # 幂等：二次调用无新增失效
    count2 = await svc.invalidate_for_repo(str(repo_x.id))
    assert count2 == 0


@pytest.mark.asyncio
async def test_mark_stale_skips_running_affected_task() -> None:
    """WR-01：mark_stale 仅对已终态（done）affected 任务置 stale 重跑；正 running 的在途
    任务不被置 stale（让其自然完成）——避免对在途容器同仓双派 + 晚到回调结果被静默丢弃。"""
    session = await _make_session_async()
    repo_done = await _make_repo_async()
    repo_running = await _make_repo_async()
    svc = ResearchService()

    # 已 done 任务（有 valid partial）+ 正 running 任务（在途，无 partial）
    task_done = await RepoResearchTask.objects.acreate(
        session=session, repository=repo_done, status=RepoResearchTaskStatus.DONE
    )
    await PartialPlan.objects.acreate(
        research_task=task_done, content={"repository_id": str(repo_done.id)}, valid=True
    )
    task_running = await RepoResearchTask.objects.acreate(
        session=session, repository=repo_running, status=RepoResearchTaskStatus.RUNNING
    )

    invalidated = await svc.mark_stale([task_done.id, task_running.id])

    # done 任务 → stale + 其 partial 失效（reason=clarification），计数=1
    assert invalidated == 1
    await task_done.arefresh_from_db()
    assert task_done.status == RepoResearchTaskStatus.STALE
    pd = await PartialPlan.objects.aget(research_task=task_done)
    assert pd.valid is False
    assert pd.invalidated_reason == "clarification"

    # running 任务 → 保持 running（不置 stale，让在途容器自然完成）
    await task_running.arefresh_from_db()
    assert task_running.status == RepoResearchTaskStatus.RUNNING


@pytest.mark.asyncio
async def test_mark_stale_running_only_is_noop() -> None:
    """WR-01：affected 全为在途 running 任务 → mark_stale 完全 no-op（不置 stale、计数=0）。"""
    session = await _make_session_async()
    repo = await _make_repo_async()
    task_running = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.RUNNING
    )

    invalidated = await ResearchService().mark_stale([task_running.id])

    assert invalidated == 0
    await task_running.arefresh_from_db()
    assert task_running.status == RepoResearchTaskStatus.RUNNING


@pytest.mark.asyncio
async def test_mark_stale_invalidates_partials_of_already_stale_task() -> None:
    """⭐ 已 stale 的 task 名下 valid PartialPlan 必须照常失效（quick-260907 回归门）。

    ``blueprint_repo_plan.arecord_repo_plan`` 落 degraded 空壳时正是「task=stale +
    PartialPlan 仍 valid」这个组合。老实现把已 stale 的 task 整条跳过 ⇒ 空壳的 ``valid``
    位没有任何写路径能清 ⇒ 派发面查到该仓「已有方案」判完成、节点重跑与按仓驳回全成空
    操作，degraded 仓在当前会话里再也救不回来。**可证伪**：把 STALE 从 ``_mark_stale_sync``
    的终态集合里去掉立刻转红。
    """
    session = await _make_session_async()
    repo = await _make_repo_async()
    task_stale = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.STALE
    )
    await PartialPlan.objects.acreate(
        research_task=task_stale,
        content={"repository_id": str(repo.id), "repo_plan": {"delivery_status": "degraded"}},
        valid=True,
    )

    invalidated = await ResearchService().mark_stale([task_stale.id])

    assert invalidated == 1
    row = await PartialPlan.objects.aget(research_task=task_stale)
    assert row.valid is False
    assert row.invalidated_reason == "clarification"
    await task_stale.arefresh_from_db()
    assert task_stale.status == RepoResearchTaskStatus.STALE


@pytest.mark.asyncio
async def test_refund_attempt_gives_the_budget_back_and_floors_at_zero() -> None:
    """⭐ 基础设施故障退回一格派发计数；已经是 0 时幂等，绝不退成负数。"""
    session = await _make_session_async()
    repo = await _make_repo_async()
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.FAILED, attempt=2
    )
    service = ResearchService()

    assert await service.refund_attempt(task) == 1
    assert await service.refund_attempt(task) == 0
    assert await service.refund_attempt(task) == 0
    await task.arefresh_from_db()
    assert task.attempt == 0
    # ⛔ 只动计数：状态是失败就还是失败，终态与 barrier 不受影响。
    assert task.status == RepoResearchTaskStatus.FAILED


@pytest.mark.asyncio
async def test_reset_attempts_clears_budget_and_revives_failed_tasks() -> None:
    """运维口：清零计数 + 把 failed 放回 pending（只清零不复位则永远不会被重派）。"""
    session = await _make_session_async()
    other = await _make_session_async()
    repo_failed = await _make_repo_async()
    repo_done = await _make_repo_async()
    repo_other = await _make_repo_async()
    await RepoResearchTask.objects.acreate(
        session=session, repository=repo_failed, status=RepoResearchTaskStatus.FAILED, attempt=2
    )
    await RepoResearchTask.objects.acreate(
        session=session, repository=repo_done, status=RepoResearchTaskStatus.DONE, attempt=1
    )
    await RepoResearchTask.objects.acreate(
        session=other, repository=repo_other, status=RepoResearchTaskStatus.FAILED, attempt=2
    )

    counts = await ResearchService().reset_attempts(session.id)

    assert counts == {"reset": 2, "revived": 1}
    statuses = {
        str(row["repository_id"]): (row["status"], row["attempt"])
        async for row in RepoResearchTask.objects.filter(session=session).values(
            "repository_id", "status", "attempt"
        )
    }
    assert statuses[str(repo_failed.id)] == (RepoResearchTaskStatus.PENDING, 0)
    assert statuses[str(repo_done.id)] == (RepoResearchTaskStatus.DONE, 0)
    # ⛔ 会话隔离：绝不顺手重置别的会话的预算。
    untouched = await RepoResearchTask.objects.aget(session=other)
    assert (untouched.status, untouched.attempt) == (RepoResearchTaskStatus.FAILED, 2)


@pytest.mark.asyncio
async def test_reset_attempts_can_keep_failed_terminal() -> None:
    """``revive_failed=False``：只清零，不改状态（运维只想还预算、不想立刻重派时用）。"""
    session = await _make_session_async()
    repo = await _make_repo_async()
    await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.FAILED, attempt=2
    )

    counts = await ResearchService().reset_attempts(session.id, revive_failed=False)

    assert counts == {"reset": 1, "revived": 0}
    task = await RepoResearchTask.objects.aget(session=session)
    assert (task.status, task.attempt) == (RepoResearchTaskStatus.FAILED, 0)


def test_reset_research_attempts_command_revives_failed_tasks() -> None:
    """运维命令必须真正委托 service 清零预算并复活 failed 任务。"""
    session = ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )
    repo = _make_repo()
    task = RepoResearchTask.objects.create(
        session=session,
        repository=repo,
        status=RepoResearchTaskStatus.FAILED,
        attempt=2,
    )
    stdout = StringIO()

    call_command("reset_research_attempts", session_id=str(session.id), stdout=stdout)

    task.refresh_from_db()
    assert (task.status, task.attempt) == (RepoResearchTaskStatus.PENDING, 0)
    assert "reset=1 revived=1" in stdout.getvalue()


async def _make_session_async() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="research",
        status=ConvergenceSessionStatus.WAITING_EVENT,
    )


async def _make_repo_async() -> Repository:
    return await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}",
        git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )
