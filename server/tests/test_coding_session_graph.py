"""CodingSession graph 测试 -- interrupt/resume 驱动的两阶段 dispatch 编排。
使用 MemorySaver 作为 checkpointer（不依赖 SQLite 文件），mock dispatch_coding_task
以避免真实 DB 和 Runner 依赖。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from orchestration.coding_graph import build_coding_graph
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
 session.amark_awaiting_confirmation = AsyncMock
 session.amark_failed = AsyncMock
 session.aresume_running = AsyncMock
 session.amark_completed = AsyncMock
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
 """build_coding_graph 包含 5 个节点和正确的边连接。"""
 graph = build_coding_graph
 # StateGraph builder 的 nodes 属性记录节点
 node_names = set(graph.nodes.keys)
 assert "dispatch_coding" in node_names
 assert "wait_coding_complete" in node_names
 assert "await_commit_confirm" in node_names
 assert "dispatch_commit" in node_names
 assert "wait_commit_complete" in node_names
 assert len(node_names) == 5
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
 """完整流程到 completed。"""
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
 # 用户确认 commit message -> dispatch_commit -> wait_commit_complete
 await graph.ainvoke(
 Command(resume="feat: user message"),
 config=graph_config,
 )
 # Phase 完成
 result = await graph.ainvoke(
 Command(resume={"success": True}),
 config=graph_config,
 )
 # CodingSession DB 应更新为 completed
 mock_coding_session.amark_completed.assert_awaited_once
 assert result["phase"] == "completed"
 state = await graph.aget_state(graph_config)
 assert not state.next
 @pytest.mark.asyncio
 async def test_resume_commit_complete_failure(
 self, graph_config: dict[str, Any], mock_coding_session: MagicMock
 ) -> None:
 """Phase 失败到 failed。"""
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
 """完整流程中各节点调用正确的 DB 方法。"""
 with _patch_dispatch, _patch_get_coding_session(mock_coding_session):
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
 # resume commit complete (success)
 await graph.ainvoke(
 Command(resume={"success": True}),
 config=graph_config,
 )
 mock_coding_session.amark_completed.assert_awaited_once
