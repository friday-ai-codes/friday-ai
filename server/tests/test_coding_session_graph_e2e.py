"""contract: CodingSession multi-confirm 端到端回归测试。

覆盖 coding-plan workflow implementation 修复后的全链路：

    view confirm → coding_graph.ainvoke → wait_coding_complete interrupt
                → callback (_handle_completed) → graph resume → awaiting_confirmation

使用 ``MemorySaver`` 作为 checkpointer（不依赖 sqlite ``orchestration_checkpoints.db``，
测试可重入），mock ``dispatch_coding_task`` 不真起容器，让 graph 节点跑到
``wait_coding_complete_node`` 的 ``interrupt()`` 暂停。

5 个 case：
  1. confirm 启动 graph 后暂停在 wait_coding_complete + CodingSession=running
  2. HTTP callback (_update_coding_session_on_complete) resume graph 到
     awaiting_commit_confirm + suggested_commit_message 落库
  3. WS callback (RunnerConsumer._handle_completed 共享同一 _update_…_on_complete) 行为对称
  4. Runner offline 返回 503 + CodingSession 保持 draft + graph thread 不存在
  5. _update_coding_session_on_fail → CodingSession=failed + error_message 落库
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import structlog
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from langgraph.checkpoint.memory import MemorySaver
from rest_framework_simplejwt.tokens import RefreshToken

from agents.models import AgentSession
from chat.models import CodingSession, Conversation
from orchestration.coding_graph import build_coding_graph
from projects.models import Project
from repositories.models import Repository
from subagent.models import SubAgentSession

if TYPE_CHECKING:
    from django.contrib.auth.models import User as DjangoUser

User = get_user_model()

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def memory_checkpointer() -> MemorySaver:
    """每个 test 独立的 MemorySaver，避免跨 case 状态污染。"""
    return MemorySaver()


@pytest_asyncio.fixture
async def e2e_user() -> "DjangoUser":
    user = await sync_to_async(User.objects.create_user)(
        username=f"e2e_user_{uuid.uuid4().hex[:8]}",
        email="e2e@test.local",
        password="testpass",
    )
    return cast("DjangoUser", user)


@pytest_asyncio.fixture
async def e2e_repository() -> Repository:
    return await Repository.objects.acreate(
        name=f"e2e-repo-{uuid.uuid4().hex[:6]}",
        git_url="https://github.com/test/e2e-repo.git",
        git_platform="github",
        default_branch="main",
    )


@pytest_asyncio.fixture
async def e2e_project(e2e_repository: Repository) -> Project:
    project = await Project.objects.acreate(
        name=f"e2e-proj-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"e2e-{uuid.uuid4().hex[:6]}",
    )
    await sync_to_async(project.repositories.add)(e2e_repository)
    return project


@pytest_asyncio.fixture
async def e2e_coding_session(
    e2e_project: Project, e2e_repository: Repository, e2e_user: Any,
) -> CodingSession:
    conversation = await Conversation.objects.acreate(
        project=e2e_project, title="e2e 281 测试对话", created_by=e2e_user,
    )
    return await CodingSession.objects.acreate(
        conversation=conversation,
        repository=e2e_repository,
        tech_plan="## e2e 测试方案\n- step 1",
        branch_name=f"feat20260520.e2e-{uuid.uuid4().hex[:6]}",
        status=CodingSession.Status.DRAFT,
    )


async def _make_sub_session(
    repo: Repository,
    task_type: str = "coding",
    status: str = SubAgentSession.Status.RUNNING,
) -> SubAgentSession:
    agent_session = await AgentSession.objects.acreate(
        session_id=f"agent-{uuid.uuid4().hex[:12]}",
        project=None,
        status=AgentSession.Status.RUNNING,
    )
    return await SubAgentSession.objects.acreate(
        session_id=f"sub-{uuid.uuid4().hex[:12]}",
        main_session=agent_session,
        task_type=SubAgentSession.TaskType.CODING,
        status=status,
        repo_url=repo.git_url,
        last_output={"task_type": task_type},
    )


async def _auth_cookies(user: Any) -> dict[str, str]:
    """生成 JWT cookie（与全局 CookieJWTAuthentication 一致）。"""
    refresh = await sync_to_async(RefreshToken.for_user)(user)
    return {"access_token": str(refresh.access_token)}


# ---------------------------------------------------------------------------
# Case 1：confirm 启动 graph + 暂停在 wait_coding_complete
# ---------------------------------------------------------------------------


async def test_confirm_starts_graph_and_pauses_at_wait_coding(
    e2e_user: Any,
    e2e_coding_session: CodingSession,
    e2e_repository: Repository,
    memory_checkpointer: MemorySaver,
) -> None:
    """直接驱动 coding_graph 验证 dispatch_coding_node 推进 running + 暂停在 wait_coding_complete。

    view 的 asyncio.create_task 在 sync 测试客户端下会被事件循环吞掉（参见
    test_coding_session.py 已覆盖 view 的同步契约），本 case 跳过 view 层直接
    跑 graph 验证 contract graph 节点的状态推进契约。
    """
    sub_session = await _make_sub_session(e2e_repository)

    with patch(
        "orchestration.coding_graph.dispatch_coding_task",
        new=AsyncMock(return_value=sub_session.session_id),
    ) as mock_dispatch:
        graph = build_coding_graph().compile(checkpointer=memory_checkpointer)
        thread_id = f"coding-{e2e_coding_session.id}"
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

        # dispatch_coding_task 内部会设置 coding_session.subagent_session_id；
        # mock 拦截后需要手动模拟该副作用，让 amark_running 拿到正确的 FK。
        async def _side_effect_set_fk(cs, **_kw):
            cs.subagent_session_id = sub_session.id
            await cs.asave(update_fields=["subagent_session", "updated_at"])
            return sub_session.session_id

        mock_dispatch.side_effect = _side_effect_set_fk

        await graph.ainvoke(  # type: ignore[call-overload]
            {"coding_session_id": str(e2e_coding_session.id)},
            config=config,
        )

    await e2e_coding_session.arefresh_from_db()
    assert e2e_coding_session.status == CodingSession.Status.RUNNING, \
        f"dispatch_coding_node 应推进到 running，实际 {e2e_coding_session.status}"
    assert e2e_coding_session.subagent_session_id == sub_session.id

    # CheckpointTuple 验证 thread 已落库；graph.aget_state 取 next nodes
    snapshot = await memory_checkpointer.aget_tuple(config)
    assert snapshot is not None, "graph thread coding-{id} 应在 checkpointer 中创建"

    state = await graph.aget_state(config)
    assert "wait_coding_complete" in state.next, \
        f"graph 应暂停在 wait_coding_complete，实际 next={state.next}"


# ---------------------------------------------------------------------------
# Case 2：HTTP callback resume graph 到 awaiting_commit_confirm
# ---------------------------------------------------------------------------


async def test_http_callback_resumes_graph_to_awaiting_commit_confirm(
    e2e_coding_session: CodingSession,
    e2e_repository: Repository,
    memory_checkpointer: MemorySaver,
) -> None:
    """HTTP completed callback 应 resume graph 到 await_commit_confirm interrupt。"""
    sub_session = await _make_sub_session(e2e_repository)

    # Phase：用 memory_checkpointer 驱动 graph 到 wait_coding_complete interrupt
    async def _side_effect_set_fk(cs, **_kw):
        cs.subagent_session_id = sub_session.id
        await cs.asave(update_fields=["subagent_session", "updated_at"])
        return sub_session.session_id

    with patch(
        "orchestration.coding_graph.dispatch_coding_task",
        new=AsyncMock(side_effect=_side_effect_set_fk),
    ):
        graph = build_coding_graph().compile(checkpointer=memory_checkpointer)
        thread_id = f"coding-{e2e_coding_session.id}"
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        await graph.ainvoke(  # type: ignore[call-overload]
            {"coding_session_id": str(e2e_coding_session.id)},
            config=config,
        )

    # 模拟 Runner 完成回调：last_output 含 suggested_commit_message
    # _update_coding_session_on_complete 直接读 session.last_output.get("suggested_commit_message")
    sub_session.last_output = {
        "task_type": "coding",
        "suggested_commit_message": "feat: e2e 281 commit message",
    }
    await sub_session.amark_completed()
    await sub_session.asave(update_fields=["last_output", "updated_at"])

    # 关联 CodingSession.subagent_session 已经在 Phase 通过 _side_effect_set_fk 设置
    # 但 _update_coding_session_on_complete 用 reverse FK 查询 — 需要确保 FK 已落库
    await e2e_coding_session.arefresh_from_db()
    assert e2e_coding_session.subagent_session_id == sub_session.id

    # 调 HTTP callback handler，并 mock get_checkpointer 返回同一 MemorySaver
    from services.git_platform.models import MRCreateResult
    from subagent.api.callbacks import _update_coding_session_on_complete

    mock_platform_client = AsyncMock()
    mock_platform_client.create_merge_request = AsyncMock(
        return_value=MRCreateResult(
            success=True,
            mr_url="https://github.com/test/repo/pull/e2e-http",
            mr_id="e2e-http",
        )
    )
    with patch(
        "orchestration.checkpointer.get_checkpointer",
        new=AsyncMock(return_value=memory_checkpointer),
    ), patch(
        "services.git_credentials.aresolve_git_token",
        new=AsyncMock(return_value="test-token"),
    ), patch(
        "services.git_platform.get_git_platform_client",
        return_value=mock_platform_client,
    ):
        await _update_coding_session_on_complete(sub_session)

    await e2e_coding_session.arefresh_from_db()
    assert e2e_coding_session.status == CodingSession.Status.COMPLETED, \
        f"HTTP callback 应直接完成 PR 创建，实际 {e2e_coding_session.status}"
    assert e2e_coding_session.pr_url == "https://github.com/test/repo/pull/e2e-http"
    assert e2e_coding_session.suggested_commit_message == "feat: e2e 281 commit message", \
        f"suggested_commit_message 应落库，实际 {e2e_coding_session.suggested_commit_message!r}"

    # 重建 graph + checkpointer 句柄取 next nodes（与 case 1 相同 thread）
    verify_graph = build_coding_graph().compile(checkpointer=memory_checkpointer)
    state = await verify_graph.aget_state(config)
    assert not state.next, f"graph 应完成，实际 next={state.next}"


# ---------------------------------------------------------------------------
# Case 3：WS callback 与 HTTP 路径对称（workflow update Task 3 commit 9cf0a2d3）
# ---------------------------------------------------------------------------


async def test_ws_callback_resumes_graph_same_as_http(
    e2e_coding_session: CodingSession,
    e2e_repository: Repository,
    memory_checkpointer: MemorySaver,
) -> None:
    """WS task_completed handler 应与 HTTP callback 行为完全对称。

    workflow update Task 3（commit 9cf0a2d3）已修复 RunnerConsumer._handle_completed 调
    _update_coding_session_on_complete，本 case 实测该闭环。
    """
    from runners.consumers import RunnerConsumer

    sub_session = await _make_sub_session(e2e_repository)

    # Phase：先驱动 graph 到 wait_coding_complete
    async def _side_effect_set_fk(cs, **_kw):
        cs.subagent_session_id = sub_session.id
        await cs.asave(update_fields=["subagent_session", "updated_at"])
        return sub_session.session_id

    with patch(
        "orchestration.coding_graph.dispatch_coding_task",
        new=AsyncMock(side_effect=_side_effect_set_fk),
    ):
        graph = build_coding_graph().compile(checkpointer=memory_checkpointer)
        config: dict[str, Any] = {
            "configurable": {"thread_id": f"coding-{e2e_coding_session.id}"},
        }
        await graph.ainvoke(  # type: ignore[call-overload]
            {"coding_session_id": str(e2e_coding_session.id)},
            config=config,
        )

    # 准备 WS payload（_handle_completed 内部走与 HTTP 共享的
    # _update_coding_session_on_complete，并且自身先把 last_output 设到 session
    # （实际生产侧由 progress 帧累积 + completed 帧写 raw_output）；这里直接为
    # sub_session 写 last_output 模拟，与 case 2 相同字段语义）。
    sub_session.last_output = {
        "task_type": "coding",
        "suggested_commit_message": "feat: e2e 281 ws path",
    }
    await sub_session.asave(update_fields=["last_output", "updated_at"])

    payload = {
        "task_id": sub_session.session_id,
        "result_type": "text",
        "text_output": "diff",
        "branch_name": e2e_coding_session.branch_name,
        "commit_sha": "abc1234",
        "modified_files": ["a.py"],
        "output": {
            "text": "diff",
            "branch_name": e2e_coding_session.branch_name,
            "commit_sha": "abc1234",
            "suggested_commit_message": "feat: e2e 281 ws path",
            "modified_files": ["a.py"],
            "task_type": "coding",
        },
    }

    consumer = RunnerConsumer()
    log = structlog.get_logger("e2e").bind(case="ws")

    from services.git_platform.models import MRCreateResult

    mock_platform_client = AsyncMock()
    mock_platform_client.create_merge_request = AsyncMock(
        return_value=MRCreateResult(
            success=True,
            mr_url="https://github.com/test/repo/pull/e2e-ws",
            mr_id="e2e-ws",
        )
    )
    with patch(
        "orchestration.checkpointer.get_checkpointer",
        new=AsyncMock(return_value=memory_checkpointer),
    ), patch(
        "services.git_credentials.aresolve_git_token",
        new=AsyncMock(return_value="test-token"),
    ), patch(
        "services.git_platform.get_git_platform_client",
        return_value=mock_platform_client,
    ):
        await consumer._handle_completed(payload, log)

    await e2e_coding_session.arefresh_from_db()
    assert e2e_coding_session.status == CodingSession.Status.COMPLETED, \
        f"WS callback 路径应与 HTTP 等价直接完成 PR 创建，实际 {e2e_coding_session.status}"
    assert e2e_coding_session.pr_url == "https://github.com/test/repo/pull/e2e-ws"
    assert e2e_coding_session.suggested_commit_message == "feat: e2e 281 ws path"

    verify_graph = build_coding_graph().compile(checkpointer=memory_checkpointer)
    state = await verify_graph.aget_state(config)
    assert not state.next, f"WS 路径下 graph 应完成，实际 next={state.next}"


# ---------------------------------------------------------------------------
# Case 4：Runner 不在线 → 503 + CodingSession 保持 draft + 无 graph thread
# ---------------------------------------------------------------------------


async def test_runner_offline_returns_503_and_no_graph_started(
    e2e_user: Any,
    e2e_coding_session: CodingSession,
    memory_checkpointer: MemorySaver,
) -> None:
    """Runner 不在线时 view 应返回 503，CodingSession 回滚到 draft，graph thread 不存在。"""
    cookies = await _auth_cookies(e2e_user)

    client = AsyncClient()
    for k, v in cookies.items():
        client.cookies[k] = v

    with (
        patch(
            "chat.views.check_runner_online",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "chat.views.get_checkpointer",
            new=AsyncMock(return_value=memory_checkpointer),
        ),
    ):
        response = await client.post(
            f"/api/chat/coding-sessions/{e2e_coding_session.id}/confirm/",
            data={},
            content_type="application/json",
        )

    assert response.status_code == 503, \
        f"Runner offline 应返回 503，实际 {response.status_code}: {response.content!r}"

    await e2e_coding_session.arefresh_from_db()
    assert e2e_coding_session.status == CodingSession.Status.DRAFT, \
        f"Runner offline 时 CodingSession 应回滚到 draft，实际 {e2e_coding_session.status}"

    config = {"configurable": {"thread_id": f"coding-{e2e_coding_session.id}"}}
    snapshot = await memory_checkpointer.aget_tuple(config)
    assert snapshot is None, "Runner offline 时不应启动 graph thread"


# ---------------------------------------------------------------------------
# Case 5：failed callback → CodingSession=failed + error_message 落库
# ---------------------------------------------------------------------------


async def test_failed_callback_marks_coding_session_failed(
    e2e_coding_session: CodingSession,
    e2e_repository: Repository,
    memory_checkpointer: MemorySaver,
) -> None:
    """callback 上报 failed 时 CodingSession 应推进到 failed + error_message 落库。"""
    sub_session = await _make_sub_session(e2e_repository)

    # Phase：先驱动 graph 到 wait_coding_complete interrupt
    async def _side_effect_set_fk(cs, **_kw):
        cs.subagent_session_id = sub_session.id
        await cs.asave(update_fields=["subagent_session", "updated_at"])
        return sub_session.session_id

    with patch(
        "orchestration.coding_graph.dispatch_coding_task",
        new=AsyncMock(side_effect=_side_effect_set_fk),
    ):
        graph = build_coding_graph().compile(checkpointer=memory_checkpointer)
        config: dict[str, Any] = {
            "configurable": {"thread_id": f"coding-{e2e_coding_session.id}"},
        }
        await graph.ainvoke(  # type: ignore[call-overload]
            {"coding_session_id": str(e2e_coding_session.id)},
            config=config,
        )

    await e2e_coding_session.arefresh_from_db()
    assert e2e_coding_session.status == CodingSession.Status.RUNNING

    # 调 HTTP _update_coding_session_on_fail 入口（与 WS 路径共享，行为对称）
    from subagent.api.callbacks import _update_coding_session_on_fail

    with patch(
        "orchestration.checkpointer.get_checkpointer",
        new=AsyncMock(return_value=memory_checkpointer),
    ):
        await _update_coding_session_on_fail(sub_session, "e2e mock error: 容器执行超时")

    await e2e_coding_session.arefresh_from_db()
    assert e2e_coding_session.status == CodingSession.Status.FAILED, \
        f"failed callback 应推进到 failed，实际 {e2e_coding_session.status}"
    assert "mock error" in e2e_coding_session.error_message
