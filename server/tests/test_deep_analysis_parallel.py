"""Phase P15 — deep_analysis 多仓库并行 dispatch 语义测试。

核心变更：``existing_session`` 复用键由 ``(conversation_id, source)`` 升级为
``(conversation_id, repository_id, source)``。

这让 LLM 在「深度分析」模式下能对同一 conversation 内的多个不同仓库**并行**
dispatch Claude Code 容器（用户跨仓库追踪场景的核心需求）。

3 个关键 case：
- 同 conv + 同 repo + 同 source → 复用现有 session（避免重复开容器）
- 同 conv + **不同 repo** + 同 source → **创建新 session**（核心修复）
- 不同 conv + 同 repo → 创建新 session
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tools.chat_tools import deep_analysis


def _make_mocks(
    *,
    existing_candidates: list[dict[str, Any]] | None = None,
    target_repo_id: str = "repo-A",
) -> dict[str, Any]:
    """构造 deep_analysis 调用所需的全套 mock。

    Args:
        existing_candidates: 模拟 SubAgentSession 里已存在的 RUNNING 候选会话，
            每项是 last_output 的 dict（控制 conversation_id / repository_id /
            source 三个字段以触发不同的复用语义）。
        target_repo_id: deep_analysis 当前调用要分析的 repo id。

    Returns:
        ``{
            "patches": [...],         # context managers
            "dispatched": list,       # 被 dispatcher 收到的 DispatchTask
            "created_sub_sessions": list,  # SubAgentSession.acreate 被调用的次数
            "agent_session_acreate": AsyncMock,
        }``
    """
    dispatched: list[Any] = []
    created_sub_sessions: list[Any] = []

    mock_project = MagicMock()
    mock_project.id = "proj-1"
    mock_project.name = "Test"

    mock_repo = MagicMock()
    mock_repo.id = target_repo_id
    mock_repo.name = f"repo-{target_repo_id}"
    mock_repo.git_url = "https://github.com/test/repo.git"
    mock_repo.default_branch = "main"

    mock_dispatcher = MagicMock()

    async def _fake_dispatch(task: Any) -> None:
        dispatched.append(task)

    mock_dispatcher.dispatch = _fake_dispatch

    candidates_list = existing_candidates or []
    candidate_objs = []
    for cand_output in candidates_list:
        c = MagicMock()
        c.last_output = cand_output
        c.session_id = f"existing-{cand_output.get('repository_id')}"
        # asave 是 async；候选复用路径会触发 asave 更新 task_description
        c.asave = AsyncMock(return_value=None)
        candidate_objs.append(c)

    async def _candidates_aiter() -> AsyncIterator[Any]:
        for c in candidate_objs:
            yield c

    async def _empty_aiter() -> AsyncIterator[Any]:
        if False:  # pragma: no cover — 占位让函数成为 async generator
            yield None
        return

    async def _repo_aiter() -> AsyncIterator[Any]:
        yield mock_repo

    mock_agent_session = MagicMock()
    mock_agent_session.session_id = "agent-deep-test"
    agent_session_acreate = AsyncMock(return_value=mock_agent_session)

    async def _track_sub_acreate(**kwargs: Any) -> Any:
        sub = MagicMock()
        sub.session_id = f"new-{kwargs.get('session_id', 'unknown')}"
        created_sub_sessions.append(sub)
        return sub

    patches = [
        patch("projects.models.Space.objects", new_callable=MagicMock),
        patch("repositories.models.Repository.objects", new_callable=MagicMock),
        patch("subagent.models.SubAgentSession.objects", new_callable=MagicMock),
        patch("runners.models.Runner.objects", new_callable=MagicMock),
        patch("agents.models.AgentSession.objects", new_callable=MagicMock),
        patch("runners.dispatcher.get_dispatcher", return_value=mock_dispatcher),
        patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value=""),
        patch("agents.tools.blocking_task_registry.register_blocking_task", new_callable=AsyncMock),
        patch("repositories.models.GitCredential.objects", new_callable=MagicMock),
    ]

    return {
        "patches": patches,
        "dispatched": dispatched,
        "created_sub_sessions": created_sub_sessions,
        "agent_session_acreate": agent_session_acreate,
        "mock_project": mock_project,
        "mock_repo": mock_repo,
        "candidate_objs": candidate_objs,
        "candidates_aiter": _candidates_aiter,
        "empty_aiter": _empty_aiter,
        "repo_aiter": _repo_aiter,
        "track_sub_acreate": _track_sub_acreate,
    }


def _wire_mocks(ctx: dict[str, Any], started_patches: list[Any]) -> None:
    """串接 mock —— 把构造好的对象挂到 patch 出的 MagicMock 上。"""
    (
        mock_proj_objs,
        mock_repo_objs,
        mock_sub_objs,
        mock_runner_objs,
        mock_agent_objs,
        _mock_dispatcher,
        _mock_settings,
        _mock_register,
        mock_git_objs,
    ) = started_patches

    mock_proj_objs.aget = AsyncMock(return_value=ctx["mock_project"])

    repo_qs = MagicMock()
    repo_qs.__getitem__ = MagicMock(return_value=repo_qs)
    repo_qs.__aiter__ = lambda self: ctx["repo_aiter"]()
    mock_repo_objs.filter.return_value = repo_qs

    sub_qs = MagicMock()
    sub_qs.select_related.return_value = sub_qs
    sub_qs.__aiter__ = lambda self: ctx["candidates_aiter"]()
    mock_sub_objs.filter.return_value = sub_qs
    mock_sub_objs.acreate = AsyncMock(side_effect=ctx["track_sub_acreate"])

    runner_qs = MagicMock()
    runner_qs.acount = AsyncMock(return_value=1)
    mock_runner_objs.filter.return_value = runner_qs

    mock_agent_objs.acreate = ctx["agent_session_acreate"]

    from repositories.models import GitCredential
    mock_git_objs.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_no_existing_session_creates_new() -> None:
    """clean slate：无已存在 candidate，必须创建新 session 并 dispatch。"""
    ctx = _make_mocks(existing_candidates=None, target_repo_id="repo-A")

    started = [p.start() for p in ctx["patches"]]
    try:
        _wire_mocks(ctx, started)
        result = await deep_analysis(
            space_id="proj-1",
            task_description="分析 A 仓库的入口跳转",
            repository_id="repo-A",
            conversation_id="cid",
        )
    finally:
        for p in ctx["patches"]:
            p.stop()

    assert result.success is True
    assert len(ctx["dispatched"]) == 1
    assert len(ctx["created_sub_sessions"]) == 1
    ctx["agent_session_acreate"].assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_same_conv_same_repo_reuses_existing() -> None:
    """同 conversation_id + 同 repository_id + 同 source → 复用 existing，不开新容器。"""
    existing = [{
        "source": "chat_deep_analysis",
        "conversation_id": "cid",
        "repository_id": "repo-A",
        "task_description": "之前的任务",
    }]
    ctx = _make_mocks(existing_candidates=existing, target_repo_id="repo-A")

    started = [p.start() for p in ctx["patches"]]
    try:
        _wire_mocks(ctx, started)
        result = await deep_analysis(
            space_id="proj-1",
            task_description="同一仓库的新角度问题",
            repository_id="repo-A",
            conversation_id="cid",
        )
    finally:
        for p in ctx["patches"]:
            p.stop()

    assert result.success is True
    # 复用路径：dispatch 不会被再次调用；SubAgentSession.acreate 也不调用
    assert len(ctx["dispatched"]) == 0
    assert len(ctx["created_sub_sessions"]) == 0
    ctx["agent_session_acreate"].assert_not_awaited()
    # 现有 candidate 的 last_output.task_description 应被更新（同仓库换问题视角）
    ctx["candidate_objs"][0].asave.assert_awaited()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_same_conv_different_repo_dispatches_new() -> None:
    """[核心修复] 同 conversation_id + **不同** repository_id → 创建新 session 并 dispatch。

    这是 P15 关键语义：让 LLM 在跨仓库追踪场景下能并行开多个 Claude Code 容器，
    而非复用 conv 下第一个容器。
    """
    existing = [{
        "source": "chat_deep_analysis",
        "conversation_id": "cid",
        "repository_id": "repo-A",  # 已有的是 A
        "task_description": "分析 A 仓库",
    }]
    ctx = _make_mocks(existing_candidates=existing, target_repo_id="repo-B")  # 现在调 B

    started = [p.start() for p in ctx["patches"]]
    try:
        _wire_mocks(ctx, started)
        result = await deep_analysis(
            space_id="proj-1",
            task_description="分析 B 仓库的对应入口",
            repository_id="repo-B",
            conversation_id="cid",
        )
    finally:
        for p in ctx["patches"]:
            p.stop()

    assert result.success is True
    # 关键断言：B 仓库的调用必须真实 dispatch，不能复用 A 的 session
    assert len(ctx["dispatched"]) == 1, "不同 repo 必须开新容器并 dispatch"
    assert len(ctx["created_sub_sessions"]) == 1
    ctx["agent_session_acreate"].assert_awaited_once()
    # 现有 A 仓库的 candidate 不应被触碰
    ctx["candidate_objs"][0].asave.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_different_conv_same_repo_dispatches_new() -> None:
    """不同 conversation_id + 同 repository_id → 创建新 session（不同 conv 不复用）。"""
    existing = [{
        "source": "chat_deep_analysis",
        "conversation_id": "conv-OTHER",
        "repository_id": "repo-A",
        "task_description": "别的会话的任务",
    }]
    ctx = _make_mocks(existing_candidates=existing, target_repo_id="repo-A")

    started = [p.start() for p in ctx["patches"]]
    try:
        _wire_mocks(ctx, started)
        result = await deep_analysis(
            space_id="proj-1",
            task_description="本会话第一次分析 A",
            repository_id="repo-A",
            conversation_id="cid",
        )
    finally:
        for p in ctx["patches"]:
            p.stop()

    assert result.success is True
    assert len(ctx["dispatched"]) == 1
    assert len(ctx["created_sub_sessions"]) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_wrong_source_does_not_reuse() -> None:
    """non-chat_deep_analysis 来源的 candidate 不应被复用（防止误抢其他子系统 session）。"""
    existing = [{
        "source": "coding_plan_executor",  # 不是 chat_deep_analysis
        "conversation_id": "cid",
        "repository_id": "repo-A",
    }]
    ctx = _make_mocks(existing_candidates=existing, target_repo_id="repo-A")

    started = [p.start() for p in ctx["patches"]]
    try:
        _wire_mocks(ctx, started)
        result = await deep_analysis(
            space_id="proj-1",
            task_description="分析 A 仓库",
            repository_id="repo-A",
            conversation_id="cid",
        )
    finally:
        for p in ctx["patches"]:
            p.stop()

    assert result.success is True
    # source 不匹配 → 必须开新容器
    assert len(ctx["dispatched"]) == 1
    assert len(ctx["created_sub_sessions"]) == 1
