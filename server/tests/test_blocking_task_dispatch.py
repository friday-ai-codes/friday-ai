"""deep_analysis fire-and-forget 行为 + blocking_task_registry 单元测试。

验证 deep_analysis 工具 dispatch 后立即返回 __blocking_task__ 标记，
不再阻塞轮询。同时验证 blocking_task_registry 的 register/drain 接口。
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.tools.base import ToolResult

# ── blocking_task_registry 独立测试（无 Django 依赖） ──


@pytest.mark.asyncio
async def test_blocking_task_registry_register_and_drain() -> None:
    """register 后 drain 返回已注册任务，drain 后再次读取为空。"""
    from agents.tools.blocking_task_registry import (
        _store,
        drain_blocking_tasks,
        register_blocking_task,
    )

    _store.clear()

    await register_blocking_task("cid", {"task_id": "contract", "task_type": "deep_analysis"})
    tasks = await drain_blocking_tasks("cid")
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "contract"
    assert await drain_blocking_tasks("cid") == []


@pytest.mark.asyncio
async def test_blocking_task_registry_multiple_tasks() -> None:
    """同一 session 注册多个 blocking task 后一次性 drain。"""
    from agents.tools.blocking_task_registry import (
        _store,
        drain_blocking_tasks,
        register_blocking_task,
    )

    _store.clear()

    await register_blocking_task("conv-2", {"task_id": "a", "task_type": "deep_analysis"})
    await register_blocking_task("conv-2", {"task_id": "b", "task_type": "deep_analysis"})
    tasks = await drain_blocking_tasks("conv-2")
    assert len(tasks) == 2
    assert {t["task_id"] for t in tasks} == {"a", "b"}


@pytest.mark.asyncio
async def test_blocking_task_registry_drain_nonexistent() -> None:
    """drain 不存在的 conversation_id 返回空列表。"""
    from agents.tools.blocking_task_registry import _store, drain_blocking_tasks

    _store.clear()

    assert await drain_blocking_tasks("nonexistent") == []


# ── deep_analysis fire-and-forget 测试（Mock Django ORM） ──


def _make_mock_project(name: str = "test-project") -> MagicMock:
    p = MagicMock()
    p.name = name
    p.id = uuid.uuid4()
    return p


def _make_mock_repo(name: str = "test-repo") -> MagicMock:
    r = MagicMock()
    r.name = name
    r.id = uuid.uuid4()
    r.git_url = "https://github.com/test/repo.git"
    r.default_branch = "main"
    r.index_status = "indexed"
    r.is_deleted = False
    return r


def _make_mock_session(session_id: str = "deep-abc123") -> MagicMock:
    s = MagicMock()
    s.session_id = session_id
    s.status = "pending"
    s.last_output = {}
    s.asave = AsyncMock()
    return s


def _build_deep_analysis_mocks(
    project: MagicMock | None = None,
    repo: MagicMock | None = None,
    online_runners: int = 1,
    existing_session: MagicMock | None = None,
) -> dict[str, MagicMock | AsyncMock]:
    """构建 deep_analysis 所需的全套 mock 对象。"""
    project = project or _make_mock_project()
    repo = repo or _make_mock_repo()

    mock_project_aget = AsyncMock(return_value=project)
    mock_repo_filter = MagicMock()

    async def _repo_iter(*_a: object, **_kw: object) -> MagicMock:
        for r in [repo]:
            yield r

    mock_repo_filter.__aiter__ = _repo_iter
    mock_repo_filter.__getitem__ = MagicMock(return_value=mock_repo_filter)

    # SubAgentSession — existing session 查询
    mock_sub_filter = MagicMock()
    mock_sub_filter.select_related = MagicMock(return_value=mock_sub_filter)

    async def _sub_iter(*_a: object, **_kw: object) -> MagicMock:
        if existing_session:
            yield existing_session
        return

    mock_sub_filter.__aiter__ = _sub_iter

    # Runner 在线检查
    mock_runner_filter = MagicMock()
    mock_runner_filter.acount = AsyncMock(return_value=online_runners)

    # AgentSession + SubAgentSession 创建
    mock_agent_create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    mock_sub_create = AsyncMock(return_value=_make_mock_session())

    # Dispatcher
    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch = AsyncMock()
    mock_get_dispatcher = MagicMock(return_value=mock_dispatcher)

    # aget_setting_value
    mock_setting = AsyncMock(return_value="test-key")

    # GitCredential
    from repositories.models import GitCredential
    mock_git_cred_aget = AsyncMock(side_effect=GitCredential.DoesNotExist)

    return {
        "project_aget": mock_project_aget,
        "repo_filter": mock_repo_filter,
        "sub_filter": mock_sub_filter,
        "runner_filter": mock_runner_filter,
        "agent_create": mock_agent_create,
        "sub_create": mock_sub_create,
        "get_dispatcher": mock_get_dispatcher,
        "dispatcher": mock_dispatcher,
        "setting": mock_setting,
        "git_cred_aget": mock_git_cred_aget,
        "project": project,
        "repo": repo,
    }


@pytest.fixture
def da_mocks() -> dict[str, MagicMock | AsyncMock]:
    return _build_deep_analysis_mocks()


async def _call_deep_analysis(mocks: dict[str, MagicMock | AsyncMock]) -> ToolResult:
    """在 mock 环境下调用 deep_analysis。"""
    from agents.tools.blocking_task_registry import _store

    _store.clear()

    with (
        patch("agents.tools.chat_tools.Space.objects") as mock_proj_objects,
        patch("agents.tools.chat_tools.Repository.objects") as mock_repo_objects,
        patch("subagent.models.SubAgentSession.objects") as mock_sub_objects,
        patch("runners.models.Runner.objects") as mock_runner_objects,
        patch("agents.models.AgentSession.objects") as mock_agent_objects,
        patch("runners.dispatcher.get_dispatcher", mocks["get_dispatcher"]),
        patch("chat.services.aget_setting_value", mocks["setting"]),
        patch("repositories.models.GitCredential.objects") as mock_git_objects,
    ):
        mock_proj_objects.aget = mocks["project_aget"]
        mock_repo_objects.filter.return_value = mocks["repo_filter"]
        mock_sub_objects.filter.return_value = mocks["sub_filter"]
        mock_sub_objects.acreate = mocks["sub_create"]
        mock_runner_objects.filter.return_value = mocks["runner_filter"]
        mock_agent_objects.acreate = mocks["agent_create"]
        mock_git_objects.aget = mocks["git_cred_aget"]

        from agents.tools.chat_tools import deep_analysis

        return await deep_analysis(
            space_id="proj-1",
            task_description="analyze auth module",
            conversation_id="cid",
        )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_returns_blocking_marker(da_mocks: dict[str, MagicMock | AsyncMock]) -> None:
    """deep_analysis 返回 __blocking_task__ 标记。"""
    result = await _call_deep_analysis(da_mocks)

    assert result.success is True
    assert isinstance(result.output, dict)
    assert result.output["__blocking_task__"] is True
    assert result.output["task_type"] == "deep_analysis"
    assert "task_id" in result.output


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_output_contains_params(da_mocks: dict[str, MagicMock | AsyncMock]) -> None:
    """返回值包含 task_id、task_type、params。"""
    result = await _call_deep_analysis(da_mocks)

    assert result.output["task_type"] == "deep_analysis"
    assert "task_id" in result.output
    params = result.output["params"]
    assert params["task_description"] == "analyze auth module"
    assert params["space_id"] == "proj-1"
    assert "repository_id" in params


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_does_not_block(da_mocks: dict[str, MagicMock | AsyncMock]) -> None:
    """deep_analysis 在 dispatch 后立即返回，不轮询。"""
    start = time.monotonic()
    result = await _call_deep_analysis(da_mocks)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0
    assert result.success is True


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_no_online_runner() -> None:
    """无在线 Runner 时返回 ToolResult(success=False)。"""
    mocks = _build_deep_analysis_mocks(online_runners=0)
    result = await _call_deep_analysis(mocks)

    assert result.success is False
    assert "Runner" in (result.error or "")


# ── _extract_blocking_tasks + registry key 一致性测试 ──


@pytest.mark.asyncio
async def test_extract_blocking_tasks_uses_conversation_id() -> None:
    """_extract_blocking_tasks 使用 conversation_id 作为 drain key。"""
    mock_drain = AsyncMock(return_value=[])
    with patch("agents.tools.blocking_task_registry.drain_blocking_tasks", mock_drain):
        from orchestration.graph import _extract_blocking_tasks

        await _extract_blocking_tasks({}, "conv-uuid-123")

    mock_drain.assert_awaited_once_with("conv-uuid-123")


@pytest.mark.asyncio
async def test_registry_key_consistency() -> None:
    """register 和 drain 使用同一 UUID 格式 conversation_id 时数据能匹配。"""
    from agents.tools.blocking_task_registry import (
        _store,
        drain_blocking_tasks,
        register_blocking_task,
    )

    _store.clear()
    conv_id = str(uuid.uuid4())
    task_info = {"task_id": "t-abc", "task_type": "deep_analysis"}

    await register_blocking_task(conv_id, task_info)
    tasks = await drain_blocking_tasks(conv_id)

    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "t-abc"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_reuse_existing_session() -> None:
    """同 conversation_id + 同 repository_id 时复用已有 session、不重新 dispatch。

    Phase P15：复用键由 (conv_id, source) 升级为 (conv_id, repo_id, source)。
    本测试覆盖"同 conv + 同 repo"复用路径；并行场景（同 conv + 不同 repo）由
    tests/test_deep_analysis_parallel.py 覆盖。
    """
    mocks = _build_deep_analysis_mocks()
    existing = _make_mock_session("deep-existing")
    existing.last_output = {
        "source": "chat_deep_analysis",
        "conversation_id": "cid",
        # 必须匹配 mocks["repo"].id，否则 P15 新复用键判定为「不同仓库」
        # 会真实开新容器（这是正确行为，但不是本测试要验证的）。
        "repository_id": str(mocks["repo"].id),
    }
    # 重建 sub_filter 让它 yield 这个 existing
    async def _sub_iter_with_existing(*_a: object, **_kw: object) -> MagicMock:
        yield existing

    mocks["sub_filter"].__aiter__ = _sub_iter_with_existing

    result = await _call_deep_analysis(mocks)

    assert result.success is True
    mocks["dispatcher"].dispatch.assert_not_awaited()
    assert result.output["task_id"] == "deep-existing"
