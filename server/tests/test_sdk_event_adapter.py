"""SDK EventAdapter 单元测试。
验证 StreamEvent → AgentEvent 的映射逻辑，覆盖 需求。
所有测试标记 xfail，等待 event_adapter.py 实现。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import MagicMock
from agents.core.events import (
 ERROR,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_START,
)
def _make_stream_event(event: dict[str, Any]) -> MagicMock:
 """创建模拟 SDK StreamEvent 的 mock 对象。"""
 mock = MagicMock
 mock.event = event
 # StreamEvent 有 event 属性但没有 result 属性
 del mock.result
 return mock
def _make_result_message(result: str = "完成") -> MagicMock:
 """创建模拟 SDK ResultMessage 的 mock 对象。"""
 mock = MagicMock
 mock.result = result
 # ResultMessage 有 result 属性但没有 event 属性
 del mock.event
 return mock
MODEL = "claude-sonnet-4-5"
SESSION_ID = "test-session-001"
def test_text_delta_event -> None:
 """content_block_delta + text_delta → TEXT_DELTA AgentEvent。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 msg = _make_stream_event({
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": "Hello"},
 })
 events = adapter.adapt(msg)
 assert len(events) == 1
 assert events[0].type == TEXT_DELTA
 assert events[0].data["text"] == "Hello"
 assert events[0].data["model"] == MODEL
 assert events[0].data["session_id"] == SESSION_ID
def test_tool_use_start_event -> None:
 """content_block_start(type=tool_use) → TOOL_USE_START AgentEvent。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 msg = _make_stream_event({
 "type": "content_block_start",
 "index": 1,
 "content_block": {
 "type": "tool_use",
 "id": "tool_abc123",
 "name": "mcp__chat-tools__search_code",
 "input": {},
 },
 })
 events = adapter.adapt(msg)
 assert len(events) == 1
 assert events[0].type == TOOL_USE_START
 assert events[0].data["tool_name"] == "mcp__chat-tools__search_code"
 assert events[0].data["tool_call_id"] == "tool_abc123"
def test_thinking_event -> None:
 """content_block_start(type=thinking) → THINKING AgentEvent。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 msg = _make_stream_event({
 "type": "content_block_start",
 "index": 0,
 "content_block": {"type": "thinking", "thinking": ""},
 })
 events = adapter.adapt(msg)
 assert len(events) == 1
 assert events[0].type == THINKING
def test_result_message_to_complete -> None:
 """ResultMessage → MESSAGE_COMPLETE AgentEvent。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 msg = _make_result_message("这是最终回复")
 events = adapter.adapt(msg)
 assert len(events) == 1
 assert events[0].type == MESSAGE_COMPLETE
 assert "result" in events[0].data
def test_error_event -> None:
 """adapt_error → ERROR AgentEvent。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 events = adapter.adapt_error(Exception("测试错误"))
 assert len(events) == 1
 assert events[0].type == ERROR
 assert "测试错误" in events[0].data["message"]
def test_unknown_event_passthrough -> None:
 """未识别 event type → 通用 AgentEvent 透传。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 msg = _make_stream_event({
 "type": "some_future_event",
 "data": {"key": "value"},
 })
 events = adapter.adapt(msg)
 assert len(events) == 1
 assert events[0].type == "some_future_event"
class _FakeAssistantMessage:
 def __init__(self, content_blocks: list[Any]) -> None:
 self.content = content_blocks
class _FakeToolUseBlock:
 def __init__(self, tool_id: str, name: str, tool_input: dict[str, Any] | None = None) -> None:
 self.id = tool_id
 self.name = name
 self.input = tool_input or {}
_FakeToolUseBlock.__name__ = "ToolUseBlock"
_FakeAssistantMessage.__name__ = "AssistantMessage"
def _make_assistant_message(content_blocks: list[Any]) -> _FakeAssistantMessage:
 """创建模拟 SDK AssistantMessage 的假对象。"""
 return _FakeAssistantMessage(content_blocks)
def _make_tool_use_block(tool_id: str, name: str, tool_input: dict[str, Any] | None = None) -> _FakeToolUseBlock:
 return _FakeToolUseBlock(tool_id, name, tool_input)
def test_tool_use_block_no_duplicate_on_input_update -> None:
 """同一 tool_id 输入更新时不应再次发 TOOL_USE_START。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 block_v1 = _make_tool_use_block("tool_1", "mcp__chat-tools__deep_analysis", {})
 msg1 = _make_assistant_message([block_v1])
 events1 = adapter.adapt(msg1)
 assert len(events1) == 1
 assert events1[0].type == TOOL_USE_START
 block_v2 = _make_tool_use_block("tool_1", "mcp__chat-tools__deep_analysis", {"task_description": "分析代码"})
 msg2 = _make_assistant_message([block_v2])
 events2 = adapter.adapt(msg2)
 assert len(events2) == 0, "Same tool_id with updated input should NOT emit another TOOL_USE_START"
def test_multiple_different_tool_ids_each_emit_once -> None:
 """不同 tool_id 应各自发出一次 TOOL_USE_START。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 block_a = _make_tool_use_block("tool_a", "mcp__chat-tools__search_code", {"query": "test"})
 block_b = _make_tool_use_block("tool_b", "mcp__chat-tools__deep_analysis", {"task_description": "分析"})
 msg = _make_assistant_message([block_a, block_b])
 events = adapter.adapt(msg)
 assert len(events) == 2
 assert events[0].data["tool_call_id"] == "tool_a"
 assert events[1].data["tool_call_id"] == "tool_b"
 msg2 = _make_assistant_message([block_a, block_b])
 events2 = adapter.adapt(msg2)
 assert len(events2) == 0, "Already-seen tool_ids should not emit again"
def test_metadata_injection -> None:
 """所有事件 data 中注入 model 和 session_id 元数据。"""
 from agents.sdk.event_adapter import EventAdapter
 adapter = EventAdapter(model=MODEL, session_id=SESSION_ID)
 msg = _make_stream_event({
 "type": "content_block_delta",
 "index": 0,
 "delta": {"type": "text_delta", "text": "test"},
 })
 events = adapter.adapt(msg)
 for event in events:
 assert event.data["model"] == MODEL
 assert event.data["session_id"] == SESSION_ID
