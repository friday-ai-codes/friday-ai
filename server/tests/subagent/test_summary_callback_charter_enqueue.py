"""summary 成功回调串联 charter：四分支决策树 + 归因 + 失败不冒泡。"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from accounts.models import User
from agents.models import AgentSession
from repositories.models import RepoCharter, Repository
from repositories.services.charter_service import compute_charter_fingerprint
from subagent.api import callbacks as cb
from subagent.api.callbacks import (
    _update_repository_on_summary_complete,
    _update_repository_on_summary_fail,
)
from subagent.models import SubAgentSession

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@pytest.fixture
async def repo_and_session():
    user = await sync_to_async(User.objects.create_user)(
        username="sum-user", email="s@e.com", password="x"
    )
    repo = await Repository.objects.acreate(
        name="sum-repo",
        git_url="https://github.com/t/sum.git",
        git_platform="github",
    )
    agent = await AgentSession.objects.acreate(
        session_id="agent-sum-1",
        user_id=user.id,
        status=AgentSession.Status.RUNNING,
        metadata={"source": "repo_summary", "repository_id": str(repo.id)},
    )
    session = await SubAgentSession.objects.acreate(
        session_id="reposummary-test1",
        main_session=agent,
        task_type=SubAgentSession.TaskType.REPO_SUMMARY,
        status=SubAgentSession.Status.PENDING,
        repo_url=repo.git_url,
        last_output={"source": "repo_summary", "repository_id": str(repo.id)},
    )
    return repo, session, user


def _summary_result(**extra) -> dict:
    """结构化 MCP 结果 dict（260818-pt8 D-01：唯一权威渠道 output.mcp_result）。"""
    return {
        "overview": "ok",
        "tech_stack": [],
        "entry_points": [],
        **extra,
    }


def _summary_output(**extra) -> dict:
    """completed payload：output 携带结构化 mcp_result。"""
    return {"result_type": "text", "output": {"mcp_result": _summary_result(**extra)}}


async def test_summary_complete_bootstrap_enqueues_when_no_row_no_charter(
    repo_and_session,
) -> None:
    repo, session, user = repo_and_session
    enqueue = AsyncMock(return_value="job-c")
    apply = AsyncMock(return_value=None)

    with (
        patch("repositories.charter_enqueue.enqueue_charter_draft", enqueue),
        patch(
            "repositories.services.charter_service.aapply_charter_from_runner",
            apply,
        ),
    ):
        await _update_repository_on_summary_complete(
            session,
            _summary_output(),
        )

    enqueue.assert_awaited_once()
    args, kwargs = enqueue.await_args
    assert args[0] == str(repo.id)
    assert kwargs.get("initiated_by_user_id") == str(user.id)
    assert kwargs.get("mode") == "bootstrap"
    assert kwargs.get("fingerprint")
    apply.assert_not_awaited()

    await repo.arefresh_from_db()
    assert repo.ai_summary_status == "completed"


async def test_summary_complete_applies_when_charter_present(repo_and_session) -> None:
    repo, session, user = repo_and_session
    enqueue = AsyncMock(return_value="job-c")
    apply = AsyncMock(return_value=object())

    with (
        patch("repositories.charter_enqueue.enqueue_charter_draft", enqueue),
        patch(
            "repositories.services.charter_service.aapply_charter_from_runner",
            apply,
        ),
    ):
        await _update_repository_on_summary_complete(
            session,
            _summary_output(
                charter={"positioning": "Runner 基线", "evolution": "active"}
            ),
        )

    apply.assert_awaited_once()
    enqueue.assert_not_awaited()
    _args, kwargs = apply.await_args
    assert kwargs.get("initiated_by_user_id") == str(user.id)
    assert kwargs.get("fingerprint")


async def test_summary_complete_skips_when_fingerprint_equal(repo_and_session) -> None:
    repo, session, _user = repo_and_session
    fp = compute_charter_fingerprint("ok", None, {})
    await RepoCharter.objects.acreate(
        repository=repo,
        source=RepoCharter.Source.AI_DRAFT,
        version=1,
        positioning="已有",
        baseline_fingerprint=fp,
    )
    enqueue = AsyncMock(return_value="job-c")
    apply = AsyncMock(return_value=object())

    with (
        patch("repositories.charter_enqueue.enqueue_charter_draft", enqueue),
        patch(
            "repositories.services.charter_service.aapply_charter_from_runner",
            apply,
        ),
    ):
        await _update_repository_on_summary_complete(
            session,
            _summary_output(),
        )

    enqueue.assert_not_awaited()
    apply.assert_awaited_once()  # skip 路径经 service 持久化指纹


async def test_summary_complete_supplement_when_row_no_charter(repo_and_session) -> None:
    repo, session, user = repo_and_session
    await RepoCharter.objects.acreate(
        repository=repo,
        source=RepoCharter.Source.AI_DRAFT,
        version=1,
        positioning="已有",
        baseline_fingerprint="old-fp",
    )
    enqueue = AsyncMock(return_value="job-s")
    apply = AsyncMock(return_value=None)

    with (
        patch("repositories.charter_enqueue.enqueue_charter_draft", enqueue),
        patch(
            "repositories.services.charter_service.aapply_charter_from_runner",
            apply,
        ),
    ):
        await _update_repository_on_summary_complete(
            session,
            _summary_output(),
        )

    enqueue.assert_awaited_once()
    _a, kwargs = enqueue.await_args
    assert kwargs.get("mode") == "supplement"
    assert kwargs.get("initiated_by_user_id") == str(user.id)
    apply.assert_not_awaited()


async def test_summary_fail_does_not_enqueue_charter(repo_and_session) -> None:
    repo, session, _user = repo_and_session
    enqueue = AsyncMock(return_value="job-c")

    with patch("repositories.charter_enqueue.enqueue_charter_draft", enqueue):
        await _update_repository_on_summary_fail(session, "runner exploded")

    enqueue.assert_not_awaited()
    await repo.arefresh_from_db()
    assert repo.ai_summary_status == "failed"


async def test_summary_complete_enqueue_error_swallowed(repo_and_session) -> None:
    repo, session, _user = repo_and_session
    enqueue = AsyncMock(side_effect=RuntimeError("queue down"))

    with patch("repositories.charter_enqueue.enqueue_charter_draft", enqueue):
        await _update_repository_on_summary_complete(
            session,
            _summary_output(),
        )

    await repo.arefresh_from_db()
    assert repo.ai_summary_status == "completed"


def test_callback_uses_apply_and_enqueue() -> None:
    src = inspect.getsource(cb._update_repository_on_summary_complete)
    assert "aapply_charter_from_runner" in src
    assert "enqueue_charter_draft" in src
    assert "mode=\"bootstrap\"" in src or "mode='bootstrap'" in src
    assert "mode=\"supplement\"" in src or "mode='supplement'" in src
