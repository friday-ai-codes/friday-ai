"""SDK EventAdapter 单元测试。
验证 StreamEvent → AgentEvent 的映射逻辑，覆盖 需求。
所有测试标记 xfail，等待 event_adapter.py 实现。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import MagicMock
import pytest
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
 assert events[0].data["tool_use_id"] == "tool_abc123"
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
