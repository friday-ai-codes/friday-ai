"""deep_analysis fire-and-forget 行为 + blocking_task_registry 单元测试。
验证 deep_analysis 工具 dispatch 后立即返回 __blocking_task__ 标记，
不再阻塞轮询。同时验证 blocking_task_registry 的 register/drain 接口。
"""
from __future__ import annotations
import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.tools.base import ToolResult
# ── blocking_task_registry 独立测试（无 Django 依赖） ──
@pytest.mark.asyncio
async def test_blocking_task_registry_register_and_drain -> None:
 """register 后 drain 返回已注册任务，drain 后再次读取为空。"""
 from agents.tools.blocking_task_registry import (
 _store,
 drain_blocking_tasks,
 register_blocking_task,
 )
 _store.clear
 await register_blocking_task("session-1", {"task_id": "", "task_type": "deep_analysis"})
 tasks = await drain_blocking_tasks("session-1")
 assert len(tasks) == 1
 assert tasks[0]["task_id"] == ""
 assert await drain_blocking_tasks("session-1") ==
@pytest.mark.asyncio
async def test_blocking_task_registry_multiple_tasks -> None:
 """同一 session 注册多个 blocking task 后一次性 drain。"""
 from agents.tools.blocking_task_registry import (
 _store,
 drain_blocking_tasks,
 register_blocking_task,
 )
 _store.clear
 await register_blocking_task("s-2", {"task_id": "a", "task_type": "deep_analysis"})
 await register_blocking_task("s-2", {"task_id": "b", "task_type": "deep_analysis"})
 tasks = await drain_blocking_tasks("s-2")
 assert len(tasks) == 2
 assert {t["task_id"] for t in tasks} == {"a", "b"}
@pytest.mark.asyncio
async def test_blocking_task_registry_drain_nonexistent -> None:
 """drain 不存在的 session_id 返回空列表。"""
 from agents.tools.blocking_task_registry import _store, drain_blocking_tasks
 _store.clear
 assert await drain_blocking_tasks("nonexistent") ==
# ── deep_analysis fire-and-forget 测试（Mock Django ORM） ──
def _make_mock_project(name: str = "test-project") -> MagicMock:
 p = MagicMock
 p.name = name
 p.id = uuid.uuid4
 return p
def _make_mock_repo(name: str = "test-repo") -> MagicMock:
 r = MagicMock
 r.name = name
 r.id = uuid.uuid4
 r.git_url = "https://github.com/test/repo.git"
 r.default_branch = "main"
 r.index_status = "indexed"
 r.is_deleted = False
 return r
def _make_mock_session(session_id: str = "deep-abc123") -> MagicMock:
 s = MagicMock
 s.session_id = session_id
 s.status = "pending"
 s.last_output = {}
 s.asave = AsyncMock
 return s
def _build_deep_analysis_mocks(
 project: MagicMock | None = None,
 repo: MagicMock | None = None,
 online_runners: int = 1,
 existing_session: MagicMock | None = None,
) -> dict[str, MagicMock | AsyncMock]:
 """构建 deep_analysis 所需的全套 mock 对象。"""
 project = project or _make_mock_project
 repo = repo or _make_mock_repo
 mock_project_aget = AsyncMock(return_value=project)
 mock_repo_filter = MagicMock
 async def _repo_iter(*_a: object, **_kw: object) -> MagicMock:
 for r in [repo]:
 yield r
 mock_repo_filter.__aiter__ = _repo_iter
 mock_repo_filter.__getitem__ = MagicMock(return_value=mock_repo_filter)
 # SubAgentSession — existing session 查询
 mock_sub_filter = MagicMock
 mock_sub_filter.select_related = MagicMock(return_value=mock_sub_filter)
 async def _sub_iter(*_a: object, **_kw: object) -> MagicMock:
 if existing_session:
 yield existing_session
 return
 mock_sub_filter.__aiter__ = _sub_iter
 # Runner 在线检查
 mock_runner_filter = MagicMock
 mock_runner_filter.acount = AsyncMock(return_value=online_runners)
 # AgentSession + SubAgentSession 创建
 mock_agent_create = AsyncMock(return_value=MagicMock(id=uuid.uuid4))
 mock_sub_create = AsyncMock(return_value=_make_mock_session)
 # Dispatcher
 mock_dispatcher = MagicMock
 mock_dispatcher.dispatch = AsyncMock
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
def da_mocks -> dict[str, MagicMock | AsyncMock]:
 return _build_deep_analysis_mocks
async def _call_deep_analysis(mocks: dict[str, MagicMock | AsyncMock]) -> ToolResult:
 """在 mock 环境下调用 deep_analysis。"""
 from agents.tools.blocking_task_registry import _store
 _store.clear
 with (
 patch("agents.tools.chat_tools.Project.objects") as mock_proj_objects,
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
 project_id="proj-1",
 task_description="analyze auth module",
 # conversation fixture omitted
 )
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_returns_blocking_marker(da_mocks: dict[str, MagicMock | AsyncMock]) -> None:
 """: deep_analysis 返回 __blocking_task__ 标记。"""
 result = await _call_deep_analysis(da_mocks)
 assert result.success is True
 assert isinstance(result.output, dict)
 assert result.output["__blocking_task__"] is True
 assert result.output["task_type"] == "deep_analysis"
 assert "task_id" in result.output
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_output_contains_params(da_mocks: dict[str, MagicMock | AsyncMock]) -> None:
 """: 返回值包含 task_id、task_type、params。"""
 result = await _call_deep_analysis(da_mocks)
 assert result.output["task_type"] == "deep_analysis"
 assert "task_id" in result.output
 params = result.output["params"]
 assert params["task_description"] == "analyze auth module"
 assert params["project_id"] == "proj-1"
 assert "repository_id" in params
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_does_not_block(da_mocks: dict[str, MagicMock | AsyncMock]) -> None:
 """: deep_analysis 在 dispatch 后立即返回，不轮询。"""
 start = time.monotonic
 result = await _call_deep_analysis(da_mocks)
 elapsed = time.monotonic - start
 assert elapsed < 1.0
 assert result.success is True
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_no_online_runner -> None:
 """: 无在线 Runner 时返回 ToolResult(success=False)。"""
 mocks = _build_deep_analysis_mocks(online_runners=0)
 result = await _call_deep_analysis(mocks)
 assert result.success is False
 assert "Runner" in (result.error or "")
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_deep_analysis_reuse_existing_session -> None:
 """: 复用已有 session 时不重新 dispatch。"""
 existing = _make_mock_session("deep-existing")
 existing.last_output = {
 "source": "chat_deep_analysis",
 "conversation_id": "cid",
 }
 mocks = _build_deep_analysis_mocks(existing_session=existing)
 result = await _call_deep_analysis(mocks)
 assert result.success is True
 mocks["dispatcher"].dispatch.assert_not_awaited
 assert result.output["task_id"] == "deep-existing"
