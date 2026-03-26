"""SSE 字段名契约测试。
验证 SDK 路径的事件字段名与前端 SSEEvent 接口完全一致。
防止未来字段名不匹配导致 Web 端流式功能不可用。
前端 SSEEvent 接口契约：
- text_delta: { text: string }
- tool_use_start: { tool_name: string, tool_call_id: string }
- tool_use_result: { tool_name: string, tool_call_id: string, success: bool }
- message_complete: { usage: dict, status: string, iterations: int, model: string }
- thinking: { thinking: string }
"""
from __future__ import annotations
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
import pytest
from agents.core.events import (
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_RESULT,
 TOOL_USE_START,
 AgentEvent,
)
from agents.sdk.event_adapter import EventAdapter
# ============================================================================
# SDK StreamEvent / ResultMessage 工厂
# ============================================================================
def _make_stream_event(event_dict: dict[str, Any]) -> SimpleNamespace:
 """构造模拟的 SDK StreamEvent 对象。"""
 return SimpleNamespace(event=event_dict)
def _make_result_message(result_text: str) -> SimpleNamespace:
 """构造模拟的 SDK ResultMessage 对象。"""
 return SimpleNamespace(result=result_text)
# ============================================================================
# SSE 字段名契约测试（基于 EventAdapter + Hook）
# ============================================================================
class TestSSEFieldContract:
 """SSE 字段名契约测试 — 确保 SDK 事件字段与前端 SSEEvent 接口一致。"""
 def test_text_delta_fields(self) -> None:
 """text_delta 事件必须包含 'text' 字段（而非 'delta'）。"""
 adapter = EventAdapter(model="claude-sonnet-4-20250514", session_id="contract-text")
 stream_event = _make_stream_event(
 {
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": "Hello"},
 }
 )
 events = adapter.adapt(stream_event)
 assert len(events) == 1
 event = events[0]
 assert event.type == TEXT_DELTA
 # 前端契约：必须用 "text" 字段
 assert "text" in event.data, f"text_delta 事件缺少 'text' 字段: {event.data}"
 assert isinstance(event.data["text"], str)
 assert event.data["text"] == "Hello"
 # 旧字段名不应存在
 assert "delta" not in event.data, f"text_delta 事件仍包含旧字段 'delta': {event.data}"
 def test_tool_use_start_fields(self) -> None:
 """tool_use_start 事件必须包含 tool_name, tool_call_id。"""
 adapter = EventAdapter(model="claude-sonnet-4-20250514", session_id="contract-tool-start")
 stream_event = _make_stream_event(
 {
 "type": "content_block_start",
 "index": 1,
 "content_block": {
 "type": "tool_use",
 "id": "toolu_01abc",
 "name": "search_code",
 },
 }
 )
 events = adapter.adapt(stream_event)
 assert len(events) == 1
 event = events[0]
 assert event.type == TOOL_USE_START
 # 前端契约字段
 assert "tool_name" in event.data, f"tool_use_start 缺少 'tool_name': {event.data}"
 assert isinstance(event.data["tool_name"], str)
 assert event.data["tool_name"] == "search_code"
 assert "tool_call_id" in event.data, f"tool_use_start 缺少 'tool_call_id': {event.data}"
 assert isinstance(event.data["tool_call_id"], str)
 assert event.data["tool_call_id"] == "toolu_01abc"
 # 旧字段名不应存在
 assert "tool_use_id" not in event.data, (
 f"tool_use_start 仍包含旧字段 'tool_use_id': {event.data}"
 )
 @pytest.mark.django_db
 async def test_tool_use_result_fields(self) -> None:
 """tool_use_result 事件必须包含 tool_name, tool_call_id, success。"""
 from agents.sdk.hooks import create_post_tool_use_hook
 # 创建 mock AgentSession
 mock_session = MagicMock
 mock_session.session_id = "contract-tool-result"
 mock_session.increment_tool_calls = MagicMock(return_value=1)
 # 捕获事件
 captured_events: list[AgentEvent] =
 async def capture_event(event: AgentEvent) -> None:
 captured_events.append(event)
 hook = create_post_tool_use_hook(mock_session, event_callback=capture_event)
 # 模拟 PostToolUseHookInput
 input_data = {
 "tool_name": "search_code",
 "tool_input": {"query": "test"},
 "tool_response": {"results": },
 "tool_use_id": "toolu_02xyz",
 }
 mock_context = MagicMock
 await hook(input_data, "toolu_02xyz", mock_context)
 # 验证 TOOL_USE_RESULT 事件
 result_events = [e for e in captured_events if e.type == TOOL_USE_RESULT]
 assert len(result_events) == 1
 event = result_events[0]
 # 前端契约字段
 assert "tool_name" in event.data, f"tool_use_result 缺少 'tool_name': {event.data}"
 assert isinstance(event.data["tool_name"], str)
 assert "tool_call_id" in event.data, f"tool_use_result 缺少 'tool_call_id': {event.data}"
 assert isinstance(event.data["tool_call_id"], str)
 assert "success" in event.data, f"tool_use_result 缺少 'success': {event.data}"
 assert isinstance(event.data["success"], bool)
 # 旧字段名不应存在
 assert "tool_use_id" not in event.data, (
 f"tool_use_result 仍包含旧字段 'tool_use_id': {event.data}"
 )
 def test_message_complete_fields(self) -> None:
 """message_complete 事件必须包含 result（来自 adapter），
 ConversationService 会补充 usage, status, iterations, model。"""
 adapter = EventAdapter(model="claude-sonnet-4-20250514", session_id="contract-complete")
 result_message = _make_result_message("这是回复")
 events = adapter.adapt(result_message)
 assert len(events) == 1
 event = events[0]
 assert event.type == MESSAGE_COMPLETE
 # adapter 级别的字段
 assert "result" in event.data, f"message_complete 缺少 'result': {event.data}"
 assert "model" in event.data, f"message_complete 缺少 'model': {event.data}"
 assert "session_id" in event.data, f"message_complete 缺少 'session_id': {event.data}"
 def test_thinking_fields(self) -> None:
 """thinking 事件必须包含 'thinking' 字段。"""
 adapter = EventAdapter(model="claude-sonnet-4-20250514", session_id="contract-thinking")
 # thinking_delta 事件
 stream_event = _make_stream_event(
 {
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "thinking_delta", "thinking": "让我思考一下..."},
 }
 )
 events = adapter.adapt(stream_event)
 assert len(events) == 1
 event = events[0]
 assert event.type == THINKING
 assert "thinking" in event.data, f"thinking 事件缺少 'thinking' 字段: {event.data}"
 assert isinstance(event.data["thinking"], str)
 assert event.data["thinking"] == "让我思考一下..."
