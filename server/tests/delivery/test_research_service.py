"""ResearchService 行为测试（Phase 39-02，DOMAIN §6/§14）。

覆盖 <behavior>：建任务幂等 / 状态转移表 / record_partial 落 §7 + hash + done /
retry 单仓隔离（RESEARCH-02）/ 非 failed retry raise / invalidate stale（RESEARCH-03）。
"""

from __future__ import annotations

import uuid

import pytest

from agents.models import AgentSession
from delivery.models import (
    PartialPlan,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
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


def _make_session() -> PlanSession:
    return PlanSession.objects.create(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
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
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
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
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )
    repo_a = await Repository.objects.acreate(
        name=f"a-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github", default_branch="main", index_status="indexed",
    )
    repo_b = await Repository.objects.acreate(
        name=f"b-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github", default_branch="main", index_status="indexed",
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
    task_a = await RepoResearchTask.objects.acreate(session=session, repository=repo_a)
    task_b = await RepoResearchTask.objects.acreate(session=session, repository=repo_b)

    await svc.mark_running(task_a, sub)
    await task_a.arefresh_from_db()
    assert task_a.status == RepoResearchTaskStatus.RUNNING
    assert task_a.subagent_session_id == sub.id

    await svc.mark_done(task_a)
    await task_a.arefresh_from_db()
    assert task_a.status == RepoResearchTaskStatus.DONE

    await svc.mark_failed(task_b, {"reason": "boom"})
    await task_b.arefresh_from_db()
    assert task_b.status == RepoResearchTaskStatus.FAILED
    assert task_b.error == {"reason": "boom"}


@pytest.mark.asyncio
async def test_mark_failed_wraps_non_dict() -> None:
    """mark_failed 非 dict error 包成 {"message": str}。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github", default_branch="main", index_status="indexed",
    )
    task = await RepoResearchTask.objects.acreate(session=session, repository=repo)
    await ResearchService().mark_failed(task, "string error")
    await task.arefresh_from_db()
    assert task.error == {"message": "string error"}


@pytest.mark.asyncio
async def test_record_partial_done_and_hash() -> None:
    """record_partial → PartialPlan.valid True + content_hash 非空 + 两次同内容 hash 一致；task done。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github", default_branch="main", index_status="indexed",
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
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )
    repos = [
        await Repository.objects.acreate(
            name=f"r-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
            git_platform="github", default_branch="main", index_status="indexed",
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
    assert session.status == PlanSessionStatus.RESEARCHING


@pytest.mark.asyncio
async def test_retry_non_failed_raises() -> None:
    """对 running task retry → ValueError。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )
    repo = await Repository.objects.acreate(
        name=f"r-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github", default_branch="main", index_status="indexed",
    )
    task = await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=RepoResearchTaskStatus.RUNNING
    )
    with pytest.raises(ValueError):
        await ResearchService().retry_task(task)


@pytest.mark.asyncio
async def test_invalidate_for_repo_stale() -> None:
    """RESEARCH-03 核心：invalidate_for_repo(X) → partial 失效 + task stale + 计数=1；其他 repo 不受影响；幂等。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.RESEARCHING
    )
    repo_x = await Repository.objects.acreate(
        name=f"x-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github", default_branch="main", index_status="indexed",
    )
    repo_y = await Repository.objects.acreate(
        name=f"y-{uuid.uuid4().hex[:6]}", git_url=f"https://x/{uuid.uuid4().hex[:6]}.git",
        git_platform="github", default_branch="main", index_status="indexed",
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
