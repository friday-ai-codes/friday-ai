"""CodingSession graph 测试 -- interrupt/resume 驱动的三阶段 dispatch 编排。
使用 MemorySaver 作为 checkpointer（不依赖 SQLite 文件），mock dispatch_coding_task
以避免真实 DB 和 Runner 依赖。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END
from langgraph.types import Command
from orchestration.coding_graph import build_coding_graph, route_after_coding
from orchestration.coding_state import CodingSessionState
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def graph_config -> dict[str, Any]:
 """带 thread_id 的 graph config。"""
 return {"configurable": {"thread_id": "coding-test-1"}}
@pytest.fixture
def mock_coding_session -> MagicMock:
 """构建一个 mock CodingSession 实例。"""
 session = MagicMock
 session.id = "cs-test-123"
 session.tech_plan = "## 技术方案\n- 步骤 1"
 session.conversation.project.name = "Test Project"
 session.repository.name = "Test Repo"
 session.repository.default_branch = "main"
 session.repository.git_url = "https://github.com/test/repo.git"
 session.repository.git_platform = "github"
 session.branch_name = "feat20260409.test-feature"
 session.affected_files = [{"path": "src/main.py", "change_type": "modify"}]
 session.confirmed_commit_message = ""
 session.suggested_pr_title = ""
 session.suggested_pr_description = ""
 session.pr_url = ""
 session.amark_awaiting_confirmation = AsyncMock
 session.amark_failed = AsyncMock
 session.aresume_running = AsyncMock
 session.amark_completed = AsyncMock
 session.asave = AsyncMock
 return session
def _patch_dispatch -> Any:
 """Patch dispatch_coding_task 返回 mock session_id。"""
 return patch(
 "orchestration.coding_graph.dispatch_coding_task",
 new_callable=AsyncMock,
 return_value="sub-session-abc",
 )
def _patch_get_coding_session(mock_session: MagicMock) -> Any:
 """Patch _get_coding_session 返回 mock session。
 直接 mock 内部的 _get_coding_session 函数，避免复杂的 ORM 链式调用 mock。
 """
 return patch(
 "orchestration.coding_graph._get_coding_session",
 new_callable=AsyncMock,
 return_value=mock_session,
 )
# ---------------------------------------------------------------------------
# 拓扑测试
# ---------------------------------------------------------------------------
class TestGraphTopology:
 """验证 build_coding_graph 节点和边连接。"""
 def test_graph_topology(self) -> None:
 """build_coding_graph 包含 9 个节点和正确的边连接。"""
 graph = build_coding_graph
 # StateGraph builder 的 nodes 属性记录节点
 node_names = set(graph.nodes.keys)
 assert "dispatch_coding" in node_names
 assert "wait_coding_complete" in node_names
 assert "await_commit_confirm" in node_names
 assert "conflict_check" in node_names
 assert "dispatch_commit" in node_names
 assert "wait_commit_complete" in node_names
 assert "generate_pr_draft" in node_names
 assert "await_pr_confirm" in node_names
 assert "create_pr_or_skip" in node_names
 assert len(node_names) == 9
 def test_graph_compiles_with_memory_saver(self) -> None:
 """graph 可使用 MemorySaver 编译。"""
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 assert graph is not None
# ---------------------------------------------------------------------------
# Interrupt 测试
# ---------------------------------------------------------------------------
class TestGraphInterrupt:
 """验证 graph 在各 interrupt 点正确暂停。"""
 @pytest.mark.asyncio
 async def test_interrupt_at_wait_coding(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """启动 graph 后第一次 interrupt 在 wait_coding_complete。"""
 with _patch_dispatch as mock_dispatch, _patch_get_coding_session(mock_coding_session):
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 result = await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # dispatch_coding_task 应被调用
 mock_dispatch.assert_awaited_once
 # graph 应暂停在 wait_coding_complete
 state = await graph.aget_state(graph_config)
 assert "wait_coding_complete" in state.next
 assert any(t.interrupts for t in state.tasks)
 @pytest.mark.asyncio
 async def test_resume_coding_complete_success(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 成功后 graph 进入 await_commit_confirm interrupt。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session):
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Resume: Phase 编码完成
 result = await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: add feature"}),
 config=graph_config,
 )
 # CodingSession DB 应更新为 awaiting_confirmation
 mock_coding_session.amark_awaiting_confirmation.assert_awaited_once_with(
 "commit_message", "feat: add feature"
 )
 # graph 应暂停在 await_commit_confirm
 state = await graph.aget_state(graph_config)
 assert "await_commit_confirm" in state.next
 assert result.get("suggested_commit_message") == "feat: add feature"
 assert result.get("phase") == "awaiting_commit_confirm"
 @pytest.mark.asyncio
 async def test_resume_coding_complete_failure(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 失败后 graph 进入 failed + END。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session):
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Resume: Phase 编码失败
 result = await graph.ainvoke(
 Command(resume={"success": False, "error": "build failed"}),
 config=graph_config,
 )
 # CodingSession DB 应更新为 failed
 mock_coding_session.amark_failed.assert_awaited_once_with("build failed")
 assert result["phase"] == "failed"
 assert result["error"] == "build failed"
 # graph 应结束（没有 next）
 state = await graph.aget_state(graph_config)
 assert not state.next
 @pytest.mark.asyncio
 async def test_resume_commit_confirm(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """从 await_commit_confirm resume 后进入 dispatch_commit -> wait_commit_complete interrupt。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session):
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 # Phase: dispatch -> wait_coding_complete
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Phase 完成 -> await_commit_confirm
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 # 用户确认 commit message
 result = await graph.ainvoke(
 Command(resume="feat: user edited message"),
 config=graph_config,
 )
 # aresume_running 应被调用
 mock_coding_session.aresume_running.assert_awaited_once
 # graph 应暂停在 wait_commit_complete
 state = await graph.aget_state(graph_config)
 assert "wait_commit_complete" in state.next
 assert result.get("confirmed_commit_message") == "feat: user edited message"
 @pytest.mark.asyncio
 async def test_resume_commit_complete_success(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 成功后 graph 进入 generate_pr_draft（而非直接结束）。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"), \
 patch("orchestration.coding_graph.anthropic") as mock_anthropic:
 # mock LLM 返回 PR 草稿
 mock_response = MagicMock
 mock_content = MagicMock
 mock_content.text = '{"title": "feat: test PR", "description": "PR description"}'
 mock_response.content = [mock_content]
 mock_client = AsyncMock
 mock_client.messages.create = AsyncMock(return_value=mock_response)
 mock_anthropic.AsyncAnthropic.return_value = mock_client
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 # Phase: dispatch -> wait_coding_complete
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Phase 完成 -> await_commit_confirm
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 # 用户确认 commit message -> dispatch_commit -> wait_commit_complete
 await graph.ainvoke(
 Command(resume="feat: user message"),
 config=graph_config,
 )
 # Phase 完成 -> generate_pr_draft -> await_pr_confirm (interrupt)
 result = await graph.ainvoke(
 Command(resume={"success": True}),
 config=graph_config,
 )
 # Phase 成功后不再直接 amark_completed，而是进入 PR 流程
 # graph 应暂停在 await_pr_confirm
 state = await graph.aget_state(graph_config)
 assert "await_pr_confirm" in state.next
 assert result.get("phase") == "awaiting_pr_confirm"
 @pytest.mark.asyncio
 async def test_resume_commit_complete_failure(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 失败后 graph 仍然直接 -> END。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session):
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 await graph.ainvoke(
 Command(resume="feat: user message"),
 config=graph_config,
 )
 # Phase 失败
 result = await graph.ainvoke(
 Command(resume={"success": False, "error": "push rejected"}),
 config=graph_config,
 )
 mock_coding_session.amark_failed.assert_awaited
 assert result["phase"] == "failed"
 assert result["error"] == "push rejected"
 state = await graph.aget_state(graph_config)
 assert not state.next
# ---------------------------------------------------------------------------
# DB 状态同步测试
# ---------------------------------------------------------------------------
class TestDBStateSync:
 """验证 graph 节点正确调用 CodingSession DB 状态方法。"""
 @pytest.mark.asyncio
 async def test_db_state_sync_full_flow(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """完整流程中各节点调用正确的 DB 方法（到 Phase 完成进入 PR 流程）。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"), \
 patch("orchestration.coding_graph.anthropic") as mock_anthropic:
 # mock LLM
 mock_response = MagicMock
 mock_content = MagicMock
 mock_content.text = '{"title": "feat: PR title", "description": "PR desc"}'
 mock_response.content = [mock_content]
 mock_client = AsyncMock
 mock_client.messages.create = AsyncMock(return_value=mock_response)
 mock_anthropic.AsyncAnthropic.return_value = mock_client
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 # dispatch_coding -> wait_coding_complete (interrupt)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # resume coding complete (success)
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 mock_coding_session.amark_awaiting_confirmation.assert_awaited_once_with(
 "commit_message", "feat: test"
 )
 # resume commit confirm
 await graph.ainvoke(
 Command(resume="feat: final message"),
 config=graph_config,
 )
 mock_coding_session.aresume_running.assert_awaited_once
 # resume commit complete (success) -> generate_pr_draft -> await_pr_confirm (interrupt)
 await graph.ainvoke(
 Command(resume={"success": True}),
 config=graph_config,
 )
 # Phase 成功后进入 PR 流程，amark_awaiting_confirmation 被二次调用（pr_review）
 assert mock_coding_session.amark_awaiting_confirmation.await_count == 2
# ---------------------------------------------------------------------------
# CodingSessionState 字段测试
# ---------------------------------------------------------------------------
class TestCodingSessionStateFields:
 """验证 CodingSessionState TypedDict 包含 PR 相关字段。"""
 def test_state_has_pr_fields(self) -> None:
 """CodingSessionState 包含 PR Phase 相关字段。"""
 import typing
 hints = typing.get_type_hints(CodingSessionState)
 assert "suggested_pr_title" in hints
 assert "suggested_pr_description" in hints
 assert "confirmed_pr_title" in hints
 assert "confirmed_pr_description" in hints
 assert "target_branch" in hints
 assert "skip_pr" in hints
 # 类型正确性（使用 get_type_hints 解析 ForwardRef）
 assert hints["suggested_pr_title"] is str
 assert hints["skip_pr"] is bool
# ---------------------------------------------------------------------------
# PR Phase 测试
# ---------------------------------------------------------------------------
def _setup_llm_mock(mock_anthropic: MagicMock, title: str = "feat: test PR", description: str = "PR description") -> None:
 """配置 mock anthropic LLM 返回 PR 草稿。"""
 mock_response = MagicMock
 mock_content = MagicMock
 mock_content.text = f'{{"title": "{title}", "description": "{description}"}}'
 mock_response.content = [mock_content]
 mock_client = AsyncMock
 mock_client.messages.create = AsyncMock(return_value=mock_response)
 mock_anthropic.AsyncAnthropic.return_value = mock_client
def _patch_llm_and_settings -> tuple:
 """返回 LLM 和 settings 的 patch context managers。"""
 return (
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("orchestration.coding_graph.anthropic"),
 )
async def _drive_to_phase2_complete(
 graph: Any,
 graph_config: dict[str, Any],
) -> Any:
 """驱动 graph 从 START 到 Phase 完成（wait_commit_complete resume success）。
 返回 Phase 完成后的 result。
 """
 # Phase: dispatch -> wait_coding_complete (interrupt)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Phase 完成
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 # 用户确认 commit message
 await graph.ainvoke(
 Command(resume="feat: user message"),
 config=graph_config,
 )
 # Phase 完成 -> generate_pr_draft -> await_pr_confirm (interrupt)
 result = await graph.ainvoke(
 Command(resume={"success": True}),
 config=graph_config,
 )
 return result
class TestPRPhase:
 """Phase: PR 草稿生成、确认、创建/跳过测试。"""
 @pytest.mark.asyncio
 async def test_phase2_success_enters_pr_draft(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 成功后 graph 暂停在 await_pr_confirm（而非结束）。"""
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic:
 _setup_llm_mock(mock_anthropic)
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 result = await _drive_to_phase2_complete(graph, graph_config)
 state = await graph.aget_state(graph_config)
 assert "await_pr_confirm" in state.next
 assert result.get("phase") == "awaiting_pr_confirm"
 @pytest.mark.asyncio
 async def test_phase2_failure_still_ends(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 失败后 graph 仍然 -> END。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session):
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 await graph.ainvoke(
 Command(resume="feat: user message"),
 config=graph_config,
 )
 result = await graph.ainvoke(
 Command(resume={"success": False, "error": "push rejected"}),
 config=graph_config,
 )
 assert result["phase"] == "failed"
 state = await graph.aget_state(graph_config)
 assert not state.next
 @pytest.mark.asyncio
 async def test_generate_pr_draft_calls_llm(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """generate_pr_draft 调用 LLM 并持久化 suggested_pr_title/description 到 DB。"""
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic:
 _setup_llm_mock(mock_anthropic, title="feat: awesome PR", description="Awesome changes")
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 result = await _drive_to_phase2_complete(graph, graph_config)
 # LLM 应被调用
 mock_client = mock_anthropic.AsyncAnthropic.return_value
 mock_client.messages.create.assert_awaited_once
 # 应持久化到 DB
 mock_coding_session.asave.assert_awaited
 assert mock_coding_session.suggested_pr_title == "feat: awesome PR"
 assert mock_coding_session.suggested_pr_description == "Awesome changes"
 @pytest.mark.asyncio
 async def test_generate_pr_draft_idempotent(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """suggested_pr_title 已有值时跳过 LLM 调用。"""
 mock_coding_session.suggested_pr_title = "已有标题"
 mock_coding_session.suggested_pr_description = "已有描述"
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic:
 _setup_llm_mock(mock_anthropic)
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 result = await _drive_to_phase2_complete(graph, graph_config)
 # LLM 不应被调用（幂等跳过）
 mock_client = mock_anthropic.AsyncAnthropic.return_value
 mock_client.messages.create.assert_not_awaited
 @pytest.mark.asyncio
 async def test_generate_pr_draft_llm_failure_fallback(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """LLM 调用抛异常时使用 fallback 模板。"""
 # confirmed_commit_message 来自 graph state（由 await_commit_confirm 设置），
 # _drive_to_phase2_complete 中 commit confirm resume 传入 "feat: user message"
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic:
 # LLM 调用抛异常
 mock_client = AsyncMock
 mock_client.messages.create = AsyncMock(side_effect=Exception("LLM API error"))
 mock_anthropic.AsyncAnthropic.return_value = mock_client
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 result = await _drive_to_phase2_complete(graph, graph_config)
 # 使用 fallback: state 中 confirmed_commit_message 第一行作为 title
 # _drive_to_phase2_complete 中 commit confirm resume 传入 "feat: user message"
 assert mock_coding_session.suggested_pr_title == "feat: user message"
 # tech_plan 前 500 字作为 description
 assert mock_coding_session.suggested_pr_description == mock_coding_session.tech_plan[:500]
 # 流程不阻塞，仍然进入 await_pr_confirm
 state = await graph.aget_state(graph_config)
 assert "await_pr_confirm" in state.next
 @pytest.mark.asyncio
 async def test_pr_confirm_skip(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """resume skip_pr=True 后 create_pr_or_skip 标记 completed 返回 branch_url。"""
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic, \
 patch("chat.coding_events.store_coding_complete_to_message", new_callable=AsyncMock) as mock_store:
 _setup_llm_mock(mock_anthropic)
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await _drive_to_phase2_complete(graph, graph_config)
 # 用户选择跳过 PR
 result = await graph.ainvoke(
 Command(resume={"skip_pr": True}),
 config=graph_config,
 )
 assert result["phase"] == "completed"
 assert "branch_url" in result
 assert "github.com" in result["branch_url"]
 mock_coding_session.amark_completed.assert_awaited_once
 # store_coding_complete_to_message 被调用且 branch_url 参数非空
 mock_store.assert_awaited_once
 call_kwargs = mock_store.call_args
 assert call_kwargs[1].get("branch_url") or (len(call_kwargs[0]) > 1 and call_kwargs[0][1])
 @pytest.mark.asyncio
 async def test_pr_confirm_create_success(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """resume skip_pr=False + title/desc/target_branch 后成功创建 PR。"""
 from services.git_platform.models import MRCreateResult
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic, \
 patch("chat.coding_events.store_coding_complete_to_message", new_callable=AsyncMock) as mock_store, \
 patch("repositories.models.GitCredential") as mock_git_cred_cls, \
 patch("common.encryption.decrypt_value", return_value="test-token"), \
 patch("services.git_platform.get_git_platform_client") as mock_get_client:
 _setup_llm_mock(mock_anthropic)
 # mock GitCredential
 mock_cred = MagicMock
 mock_cred.encrypted_token = "encrypted-token"
 mock_git_cred_cls.objects.aget = AsyncMock(return_value=mock_cred)
 # mock git platform client
 mock_platform_client = AsyncMock
 mock_platform_client.create_merge_request = AsyncMock(
 return_value=MRCreateResult(success=True, mr_url="https://github.com/test/repo/pull/1", mr_id="1")
 )
 mock_get_client.return_value = mock_platform_client
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await _drive_to_phase2_complete(graph, graph_config)
 # 用户确认创建 PR
 result = await graph.ainvoke(
 Command(resume={
 "skip_pr": False,
 "title": "feat: my PR",
 "description": "PR body",
 "target_branch": "main",
 }),
 config=graph_config,
 )
 assert result["phase"] == "completed"
 assert result.get("pr_url") == "https://github.com/test/repo/pull/1"
 mock_coding_session.amark_completed.assert_awaited_once
 mock_store.assert_awaited_once
 @pytest.mark.asyncio
 async def test_pr_confirm_create_failure(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """GitPlatformClient 返回 success=False 时标记 failed。"""
 from services.git_platform.models import MRCreateResult
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic, \
 patch("repositories.models.GitCredential") as mock_git_cred_cls, \
 patch("common.encryption.decrypt_value", return_value="test-token"), \
 patch("services.git_platform.get_git_platform_client") as mock_get_client:
 _setup_llm_mock(mock_anthropic)
 mock_cred = MagicMock
 mock_cred.encrypted_token = "encrypted-token"
 mock_git_cred_cls.objects.aget = AsyncMock(return_value=mock_cred)
 mock_platform_client = AsyncMock
 mock_platform_client.create_merge_request = AsyncMock(
 return_value=MRCreateResult(success=False, error="merge conflict")
 )
 mock_get_client.return_value = mock_platform_client
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await _drive_to_phase2_complete(graph, graph_config)
 result = await graph.ainvoke(
 Command(resume={
 "skip_pr": False,
 "title": "feat: my PR",
 "description": "PR body",
 "target_branch": "main",
 }),
 config=graph_config,
 )
 assert result["phase"] == "failed"
 mock_coding_session.amark_failed.assert_awaited
 @pytest.mark.asyncio
 async def test_full_three_phase_flow(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """完整三阶段流程到 completed（含 PR 创建）。"""
 from services.git_platform.models import MRCreateResult
 settings_patch, anthropic_patch = _patch_llm_and_settings
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 settings_patch, anthropic_patch as mock_anthropic, \
 patch("chat.coding_events.store_coding_complete_to_message", new_callable=AsyncMock) as mock_store, \
 patch("repositories.models.GitCredential") as mock_git_cred_cls, \
 patch("common.encryption.decrypt_value", return_value="test-token"), \
 patch("services.git_platform.get_git_platform_client") as mock_get_client:
 _setup_llm_mock(mock_anthropic)
 mock_cred = MagicMock
 mock_cred.encrypted_token = "encrypted-token"
 mock_git_cred_cls.objects.aget = AsyncMock(return_value=mock_cred)
 mock_platform_client = AsyncMock
 mock_platform_client.create_merge_request = AsyncMock(
 return_value=MRCreateResult(success=True, mr_url="https://github.com/test/repo/pull/42", mr_id="42")
 )
 mock_get_client.return_value = mock_platform_client
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 # Phase: dispatch -> wait_coding_complete
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Phase 完成
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 # 用户确认 commit message
 await graph.ainvoke(
 Command(resume="feat: user message"),
 config=graph_config,
 )
 # Phase 完成 -> generate_pr_draft -> await_pr_confirm
 await graph.ainvoke(
 Command(resume={"success": True}),
 config=graph_config,
 )
 # 用户确认创建 PR
 result = await graph.ainvoke(
 Command(resume={
 "skip_pr": False,
 "title": "feat: final PR",
 "description": "Final PR desc",
 "target_branch": "main",
 }),
 config=graph_config,
 )
 assert result["phase"] == "completed"
 assert result.get("pr_url") == "https://github.com/test/repo/pull/42"
 state = await graph.aget_state(graph_config)
 assert not state.next
 mock_store.assert_awaited_once
# ---------------------------------------------------------------------------
# ConflictCheck 节点测试
# ---------------------------------------------------------------------------
class TestConflictCheckNode:
 """验证 conflict_check_node 非阻断性冲突预检行为。"""
 @pytest.mark.asyncio
 async def test_conflict_check_no_credential(
 self, mock_coding_session: MagicMock
 ) -> None:
 """无 Git 凭据时直接返回 {"phase": "committing"}，不抛异常。"""
 from orchestration.coding_graph import conflict_check_node
 state: CodingSessionState = {
 "coding_session_id": "cs-test-123",
 "phase": "committing",
 }
 with _patch_get_coding_session(mock_coding_session), \
 patch("repositories.models.GitCredential.objects") as mock_cred_objects:
 mock_cred_objects.filter.return_value.afirst = AsyncMock(return_value=None)
 result = await conflict_check_node(state)
 assert result == {"phase": "committing"}
 @pytest.mark.asyncio
 async def test_conflict_check_success_no_conflicts(
 self, mock_coding_session: MagicMock
 ) -> None:
 """compare_branches 返回 success=True, behind_by=0 时持久化结果且 has_conflicts=False。"""
 from services.git_platform.models import BranchCompareResult, CompareFileEntry
 from orchestration.coding_graph import conflict_check_node
 state: CodingSessionState = {
 "coding_session_id": "cs-test-123",
 "phase": "committing",
 }
 compare_result = BranchCompareResult(
 success=True,
 ahead_by=1,
 behind_by=0,
 files=[CompareFileEntry(path="src/main.py", change_type="modified", additions=10, deletions=2)],
 total_additions=10,
 total_deletions=2,
 truncated=False,
 has_potential_conflicts=False,
 conflicting_files=,
 )
 mock_cred = MagicMock
 mock_cred.encrypted_token = "encrypted-token"
 mock_client = AsyncMock
 mock_client.compare_branches = AsyncMock(return_value=compare_result)
 with _patch_get_coding_session(mock_coding_session), \
 patch("repositories.models.GitCredential.objects") as mock_cred_objects, \
 patch("common.encryption.decrypt_value", return_value="test-token"), \
 patch("services.git_platform.get_git_platform_client", return_value=mock_client):
 mock_cred_objects.filter.return_value.afirst = AsyncMock(return_value=mock_cred)
 result = await conflict_check_node(state)
 assert result == {"phase": "committing"}
 mock_coding_session.asave.assert_awaited_once
 assert mock_coding_session.conflict_check_result["has_conflicts"] is False
 assert mock_coding_session.diff_summary["total_additions"] == 10
 @pytest.mark.asyncio
 async def test_conflict_check_exception_non_blocking(
 self, mock_coding_session: MagicMock
 ) -> None:
 """compare_branches 抛出异常时返回 {"phase": "committing"}，不阻断流程。"""
 from orchestration.coding_graph import conflict_check_node
 state: CodingSessionState = {
 "coding_session_id": "cs-test-123",
 "phase": "committing",
 }
 mock_cred = MagicMock
 mock_cred.encrypted_token = "encrypted-token"
 mock_client = AsyncMock
 mock_client.compare_branches = AsyncMock(side_effect=Exception("Network error"))
 with _patch_get_coding_session(mock_coding_session), \
 patch("repositories.models.GitCredential.objects") as mock_cred_objects, \
 patch("common.encryption.decrypt_value", return_value="test-token"), \
 patch("services.git_platform.get_git_platform_client", return_value=mock_client):
 mock_cred_objects.filter.return_value.afirst = AsyncMock(return_value=mock_cred)
 result = await conflict_check_node(state)
 assert result == {"phase": "committing"}
# ---------------------------------------------------------------------------
# Phase: LangGraph 拓扑静态断言测试
# ---------------------------------------------------------------------------
class TestCodingGraphTopology:
 """G2 (Phase Wave): LangGraph 静态拓扑断言 -- conflict_check 必须在 await_commit_confirm 之前。"""
 def test_conflict_check_precedes_await_commit_confirm(self) -> None:
 """build_coding_graph 编译后 edges 包含 (conflict_check, await_commit_confirm) 且不包含反向边。"""
 builder = build_coding_graph
 # 优先尝试直接属性访问 builder.edges
 raw_edges: set[tuple[str, str]] = set
 if hasattr(builder, "edges"):
 for edge in builder.edges:
 if isinstance(edge, tuple) and len(edge) == 2:
 raw_edges.add(edge)
 else:
 src = getattr(edge, "source", None)
 dst = getattr(edge, "target", None) or getattr(edge, "destination", None)
 if src and dst:
 raw_edges.add((src, dst))
 # fallback: compile + introspect graph.get_graph.edges
 if not raw_edges:
 compiled = builder.compile(checkpointer=MemorySaver)
 g = compiled.get_graph
 raw_edges = {(e.source, e.target) for e in g.edges}
 assert ("conflict_check", "await_commit_confirm") in raw_edges, (
 f"expected ('conflict_check', 'await_commit_confirm') in edges, got {raw_edges}"
 )
 assert ("await_commit_confirm", "conflict_check") not in raw_edges, (
 f"legacy edge ('await_commit_confirm', 'conflict_check') must be removed, got {raw_edges}"
 )
 assert ("await_commit_confirm", "dispatch_commit") in raw_edges, (
 f"expected ('await_commit_confirm', 'dispatch_commit') in edges, got {raw_edges}"
 )
# ---------------------------------------------------------------------------
# Phase: route_after_coding 条件路由分支覆盖测试
# ---------------------------------------------------------------------------
class TestRouteAfterCoding:
 """G2 (Phase Wave): route_after_coding 条件路由分支覆盖。"""
 def test_route_after_coding_success_returns_conflict_check(self) -> None:
 """Phase 成功后 route_after_coding 返回 'conflict_check'（而非旧值 'await_commit_confirm'）。"""
 state: dict[str, Any] = {
 "coding_session_id": "cs-test-123",
 "phase": "awaiting_commit_confirm",
 }
 assert route_after_coding(state) == "conflict_check" # type: ignore[arg-type]
 def test_route_after_coding_failed_returns_end(self) -> None:
 """Phase 失败时 route_after_coding 返回 END（不经过 conflict_check）。"""
 state: dict[str, Any] = {
 "coding_session_id": "cs-test-123",
 "phase": "failed",
 }
 result = route_after_coding(state) # type: ignore[arg-type]
 assert result == END
 assert result != "conflict_check"
# ---------------------------------------------------------------------------
# Phase: resume 集成测试 -- conflict_check 前置 + interrupt payload + 失败 bypass
# ---------------------------------------------------------------------------
def _patch_conflict_check_compare(
 has_conflicts: bool = True,
 conflicting_files: list[str] | None = None,
) -> tuple[Any, Any, Any, MagicMock]:
 """构造 conflict_check_node 依赖链的完整 mock：
 - GitCredential.objects.filter.afirst 返回带 encrypted_token 的 mock cred
 - common.encryption.decrypt_value 返回明文 token
 - services.git_platform.get_git_platform_client 返回 compare_branches 已设置的 client
 返回 (cred_patch, decrypt_patch, client_patch, mock_cred)。
 """
 from services.git_platform.models import BranchCompareResult, CompareFileEntry
 files = conflicting_files if conflicting_files is not None else ["src/main.py"]
 compare_result = BranchCompareResult(
 success=True,
 ahead_by=3,
 behind_by=2,
 files=[
 CompareFileEntry(
 path="src/main.py",
 change_type="modified",
 additions=10,
 deletions=5,
 )
 ],
 total_additions=10,
 total_deletions=5,
 truncated=False,
 has_potential_conflicts=has_conflicts,
 conflicting_files=files,
 )
 mock_cred = MagicMock
 mock_cred.encrypted_token = "encrypted-token"
 mock_platform_client = AsyncMock
 mock_platform_client.compare_branches = AsyncMock(return_value=compare_result)
 cred_patch = patch("repositories.models.GitCredential.objects")
 decrypt_patch = patch("common.encryption.decrypt_value", return_value="test-token")
 client_patch = patch(
 "services.git_platform.get_git_platform_client",
 return_value=mock_platform_client,
 )
 return cred_patch, decrypt_patch, client_patch, mock_cred
class TestCodingSessionGraphResume:
 """G2 (Phase Wave): conflict_check 前置后的 resume 集成测试。"""
 @pytest.mark.asyncio
 async def test_conflict_check_runs_before_await_commit_confirm(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase resume 成功后，graph 先跑 conflict_check 再暂停在 await_commit_confirm。
 断言:
 1. conflict_check_node 成功执行 -- mock_coding_session.conflict_check_result 被写入非 None
 2. graph 暂停在 await_commit_confirm（即 conflict_check 已在 interrupt 之前完成）
 """
 # 初始化 mock session 的 conflict / diff 字段（避免 MagicMock 自动属性导致 assertion 误判）
 mock_coding_session.conflict_check_result = None
 mock_coding_session.diff_summary = None
 cred_patch, decrypt_patch, client_patch, mock_cred = _patch_conflict_check_compare(
 has_conflicts=True, conflicting_files=["src/main.py"]
 )
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 cred_patch as mock_cred_objects, decrypt_patch, client_patch:
 mock_cred_objects.filter.return_value.afirst = AsyncMock(return_value=mock_cred)
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 # Phase: dispatch -> wait_coding_complete
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Phase 完成 -> 应先执行 conflict_check，再停在 await_commit_confirm
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 # 断言 conflict_check_node 已运行并写入 DB
 assert mock_coding_session.conflict_check_result is not None, (
 "conflict_check_result 未被写入 -- conflict_check_node 未在 await 之前运行"
 )
 assert mock_coding_session.conflict_check_result["has_conflicts"] is True
 assert mock_coding_session.conflict_check_result["conflicting_files"] == ["src/main.py"]
 # 断言 diff_summary 也被写入
 assert mock_coding_session.diff_summary is not None
 assert mock_coding_session.diff_summary["total_additions"] == 10
 assert mock_coding_session.diff_summary["total_deletions"] == 5
 # 断言 graph 停在 await_commit_confirm（next 节点名含 await_commit_confirm）
 state = await graph.aget_state(graph_config)
 assert "await_commit_confirm" in state.next, (
 f"graph 应停在 await_commit_confirm，当前 next={state.next}"
 )
 @pytest.mark.asyncio
 async def test_await_commit_confirm_interrupt_includes_conflict_data(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """await_commit_confirm 的 interrupt payload 必须包含 conflict_check_result + diff_summary。"""
 mock_coding_session.conflict_check_result = None
 mock_coding_session.diff_summary = None
 cred_patch, decrypt_patch, client_patch, mock_cred = _patch_conflict_check_compare(
 has_conflicts=True, conflicting_files=["src/main.py"]
 )
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session), \
 cred_patch as mock_cred_objects, decrypt_patch, client_patch:
 mock_cred_objects.filter.return_value.afirst = AsyncMock(return_value=mock_cred)
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 await graph.ainvoke(
 Command(resume={"success": True, "suggested_commit_message": "feat: test"}),
 config=graph_config,
 )
 # 通过 snapshot.tasks[*].interrupts[*].value 读取 interrupt payload
 snapshot = await graph.aget_state(graph_config)
 interrupt_payloads: list[dict[str, Any]] =
 for task in snapshot.tasks:
 for itrp in task.interrupts:
 if isinstance(itrp.value, dict):
 interrupt_payloads.append(itrp.value)
 assert interrupt_payloads, (
 f"应至少有一个 await_commit_confirm interrupt payload，snapshot.tasks={snapshot.tasks}"
 )
 # 找到 waiting_for == "commit_confirm" 的 payload
 commit_confirm_payloads = [
 p for p in interrupt_payloads if p.get("waiting_for") == "commit_confirm"
 ]
 assert commit_confirm_payloads, (
 f"应有 waiting_for=commit_confirm 的 payload，实际 payloads={interrupt_payloads}"
 )
 payload = commit_confirm_payloads[0]
 # 断言新增字段存在
 assert "conflict_check_result" in payload, (
 f"interrupt payload 必须包含 'conflict_check_result' key，实际 keys={list(payload.keys)}"
 )
 assert "diff_summary" in payload, (
 f"interrupt payload 必须包含 'diff_summary' key，实际 keys={list(payload.keys)}"
 )
 assert payload["conflict_check_result"] is not None
 assert payload["conflict_check_result"]["has_conflicts"] is True
 assert payload["conflict_check_result"]["conflicting_files"] == ["src/main.py"]
 # 既有字段未回归
 assert "suggested_commit_message" in payload
 assert payload["suggested_commit_message"] == "feat: test"
 @pytest.mark.asyncio
 async def test_phase1_failure_bypasses_conflict_check(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 失败时 route_after_coding 直接到 END，conflict_check_node 不被执行。"""
 mock_coding_session.conflict_check_result = None
 mock_coding_session.diff_summary = None
 # 不 patch GitCredential / compare_branches -- 如果失败路径错误触及 conflict_check_node，
 # GitCredential ORM 查询会 raise（未 patch DB 访问），测试会额外失败
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session):
 graph = build_coding_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"coding_session_id": "cs-test-123", "phase": "coding"},
 config=graph_config,
 )
 # Phase 失败 resume
 result = await graph.ainvoke(
 Command(resume={"success": False, "error": "compile failed"}),
 config=graph_config,
 )
 # 断言 graph 已结束
 state = await graph.aget_state(graph_config)
 assert not state.next, f"失败路径下 graph 应到达 END，当前 next={state.next}"
 # 断言 conflict_check_node 未执行 -- mock session 的 conflict 字段仍为 None
 assert mock_coding_session.conflict_check_result is None, (
 "失败路径不应执行 conflict_check_node"
 )
 assert mock_coding_session.diff_summary is None
 # 断言 Phase 失败状态同步
 mock_coding_session.amark_failed.assert_awaited_once_with("compile failed")
 assert result["phase"] == "failed"
 assert result["error"] == "compile failed"
