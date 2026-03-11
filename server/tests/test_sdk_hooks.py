"""SDK Hook 持久化单元测试。
验证 PostToolUse 和 Stop hook 的 DB 持久化逻辑，覆盖 需求。
所有测试标记 xfail，等待 hooks.py 实现。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.events import TOOL_USE_RESULT
def _make_post_tool_use_input(
 tool_name: str = "mcp__chat-tools__search_code",
 tool_input: dict[str, Any] | None = None,
 tool_response: Any = None,
 tool_use_id: str = "tool_123",
) -> dict[str, Any]:
 """创建 PostToolUse hook input_data mock。"""
 return {
 "hook_event_name": "PostToolUse",
 "tool_name": tool_name,
 "tool_input": tool_input or {"query": "test"},
 "tool_response": tool_response or {"content": [{"type": "text", "text": "result"}]},
 "tool_use_id": tool_use_id,
 "session_id": "test-session",
 "transcript_path": "/tmp/test",
 "cwd": "/tmp",
 "permission_mode": "plan",
 }
def _make_stop_input -> dict[str, Any]:
 """创建 Stop hook input_data mock。"""
 return {
 "hook_event_name": "Stop",
 "stop_hook_active": True,
 "session_id": "test-session",
 "transcript_path": "/tmp/test",
 "cwd": "/tmp",
 "permission_mode": "plan",
 }
@pytest.mark.django_db
async def test_post_tool_use_creates_log -> None:
 """PostToolUse hook 创建 ToolCallLog 记录。"""
 from agents.sdk.hooks import create_post_tool_use_hook
 session = MagicMock
 session.increment_tool_calls = MagicMock(return_value=1)
 hook = create_post_tool_use_hook(session)
 input_data = _make_post_tool_use_input
 with patch("agents.sdk.hooks.ToolCallLog") as mock_model:
 mock_model.objects.acreate = AsyncMock
 result = await hook(input_data, "tool_123", MagicMock)
 assert result == {}
 mock_model.objects.acreate.assert_awaited_once
 call_kwargs = mock_model.objects.acreate.call_args.kwargs
 assert call_kwargs["tool_name"] == "mcp__chat-tools__search_code"
 assert call_kwargs["tool_call_id"] == "tool_123"
@pytest.mark.django_db
async def test_post_tool_use_db_failure_silent -> None:
 """PostToolUse hook DB 写入失败时不抛出异常。"""
 from agents.sdk.hooks import create_post_tool_use_hook
 session = MagicMock
 session.increment_tool_calls = MagicMock(return_value=1)
 hook = create_post_tool_use_hook(session)
 input_data = _make_post_tool_use_input
 with patch("agents.sdk.hooks.ToolCallLog") as mock_model:
 mock_model.objects.acreate = AsyncMock(side_effect=Exception("DB error"))
 # 不应该抛出异常
 result = await hook(input_data, "tool_123", MagicMock)
 assert result == {}
@pytest.mark.django_db
async def test_post_tool_use_sends_event -> None:
 """PostToolUse hook 通过 event_callback 发送 TOOL_USE_RESULT 事件。"""
 from agents.sdk.hooks import create_post_tool_use_hook
 session = MagicMock
 session.increment_tool_calls = MagicMock(return_value=1)
 event_callback = AsyncMock
 hook = create_post_tool_use_hook(session, event_callback=event_callback)
 input_data = _make_post_tool_use_input
 with patch("agents.sdk.hooks.ToolCallLog") as mock_model:
 mock_model.objects.acreate = AsyncMock
 await hook(input_data, "tool_123", MagicMock)
 event_callback.assert_awaited_once
 event = event_callback.call_args[0][0]
 assert event.type == TOOL_USE_RESULT
@pytest.mark.django_db
async def test_stop_hook_updates_session -> None:
 """Stop hook 更新 AgentSession 为 completed 状态。"""
 from agents.sdk.hooks import create_stop_hook
 session = MagicMock
 session.asave = AsyncMock
 hook = create_stop_hook(session)
 input_data = _make_stop_input
 await hook(input_data, "", MagicMock)
 session.asave.assert_awaited_once
 assert session.status == "completed"
@pytest.mark.django_db
async def test_stop_hook_db_failure_silent -> None:
 """Stop hook DB 更新失败时不抛出异常。"""
 from agents.sdk.hooks import create_stop_hook
 session = MagicMock
 session.asave = AsyncMock(side_effect=Exception("DB error"))
 hook = create_stop_hook(session)
 input_data = _make_stop_input
 # 不应该抛出异常
 result = await hook(input_data, "", MagicMock)
 assert result == {}
