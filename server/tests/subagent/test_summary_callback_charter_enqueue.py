"""summary 成功回调串联 charter 入队：归因、失败路径、enqueue 异常不冒泡。"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from accounts.models import User
from agents.models import AgentSession
from repositories.models import Repository
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


async def test_summary_complete_enqueues_charter_with_session_user(repo_and_session) -> None:
    repo, session, user = repo_and_session
    enqueue = AsyncMock(return_value="job-c")

    with patch("repositories.charter_enqueue.enqueue_charter_draft", enqueue):
        await _update_repository_on_summary_complete(
            session,
            {
                "result_type": "text",
                "output": {
                    "text": '{"overview":"ok","tech_stack":[],"entry_points":[]}',
                },
            },
        )

    enqueue.assert_awaited_once()
    args, kwargs = enqueue.await_args
    assert args[0] == str(repo.id)
    assert kwargs.get("initiated_by_user_id") == str(user.id)

    await repo.arefresh_from_db()
    assert repo.ai_summary_status == "completed"


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
            {
                "result_type": "text",
                "output": {"text": '{"overview":"ok"}'},
            },
        )

    await repo.arefresh_from_db()
    assert repo.ai_summary_status == "completed"


def test_no_direct_adraft_in_complete_callback() -> None:
    """回调串联只 defer，不直接 await adraft_charter。"""
    src = inspect.getsource(cb._update_repository_on_summary_complete)
    assert "adraft_charter" not in src
    assert "enqueue_charter_draft" in src
