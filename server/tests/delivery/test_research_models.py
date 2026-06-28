"""RepoResearchTask / PartialPlan 模型守护测试（Phase 39-01，DOMAIN §6/§7/§14）。

model-only 守护（不触 39-02 ResearchService，用 ORM 直建——tests/ 不受 INV-6
grep 守护约束）：覆盖默认态 / CASCADE / SET_NULL / makemigrations 零漂移。
"""

from __future__ import annotations

import uuid

import pytest
from django.core.management import call_command

from agents.models import AgentSession
from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from subagent.models import SubAgentSession


def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


def _make_session() -> ConvergenceSession:
    return ConvergenceSession.objects.create(entrypoint=ConvergenceSessionEntrypoint.CHAT)


@pytest.mark.django_db
def test_repo_research_task_defaults() -> None:
    """RepoResearchTask 默认 status=pending、attempt=0、error={}、时间戳非空。"""
    session = _make_session()
    repo = _make_repo()
    task = RepoResearchTask.objects.create(session=session, repository=repo)

    assert task.status == RepoResearchTaskStatus.PENDING
    assert task.attempt == 0
    assert task.error == {}
    assert task.routed_confidence == ""
    assert task.subagent_session is None
    assert task.created_at is not None
    assert task.updated_at is not None


@pytest.mark.django_db
def test_partial_plan_defaults() -> None:
    """PartialPlan 默认 valid=True、content={}、invalidated_reason/content_hash 空。"""
    session = _make_session()
    repo = _make_repo()
    task = RepoResearchTask.objects.create(session=session, repository=repo)
    partial = PartialPlan.objects.create(research_task=task)

    assert partial.valid is True
    assert partial.content == {}
    assert partial.invalidated_reason == ""
    assert partial.content_hash == ""
    assert partial.created_at is not None


@pytest.mark.django_db
def test_cascade_session_delete() -> None:
    """删 ConvergenceSession → 关联 RepoResearchTask 级联删除（CASCADE）。"""
    session = _make_session()
    repo = _make_repo()
    task = RepoResearchTask.objects.create(session=session, repository=repo)
    task_id = task.id

    session.delete()
    assert not RepoResearchTask.objects.filter(id=task_id).exists()


@pytest.mark.django_db
def test_subagent_session_set_null() -> None:
    """删 SubAgentSession → task.subagent_session 置 None（SET_NULL，不删 task）。"""
    session = _make_session()
    repo = _make_repo()
    agent_session = AgentSession.objects.create(session_id=f"agent-{uuid.uuid4().hex[:8]}")
    sub = SubAgentSession.objects.create(
        session_id=f"sub-{uuid.uuid4().hex[:8]}",
        main_session=agent_session,
        repo_url="https://github.com/test/r.git",
        task_type=SubAgentSession.TaskType.PLAN,
        status=SubAgentSession.Status.PENDING,
    )
    task = RepoResearchTask.objects.create(
        session=session, repository=repo, subagent_session=sub
    )

    sub.delete()
    task.refresh_from_db()
    assert task.subagent_session is None
    assert RepoResearchTask.objects.filter(id=task.id).exists()


@pytest.mark.django_db
def test_makemigrations_clean() -> None:
    """migration 0013 与模型零漂移：makemigrations --check --dry-run 不抛 SystemExit。"""
    call_command("makemigrations", "delivery", "--check", "--dry-run")
