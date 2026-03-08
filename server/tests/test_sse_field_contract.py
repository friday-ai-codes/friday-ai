"""SSE 字段名契约测试。
验证后端 AgentLoop 事件字段名与前端 SSEEvent 接口完全一致。
防止未来字段名不匹配导致 Web 端流式功能不可用。
前端 SSEEvent 接口契约：
- text_delta: { text: string }
- tool_use_start: { tool_name: string, tool_call_id: string, input: dict }
- tool_use_result: { tool_name: string, tool_call_id: string, success: bool, result: string }
- message_complete: { usage: dict, status: string, iterations: int, model: string }
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.events import (
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 TOOL_USE_RESULT,
 TOOL_USE_START,
 AgentEvent,
)
from agents.tools.base import ToolResult, tool
from agents.tools.registry import ToolRegistry
# ============================================================================
# Mock 基础设施（自包含，不依赖其他测试文件）
# ============================================================================
@dataclass
class MockLLMResponse:
 """模拟 LLMResponse。"""
 content: str = "mock answer"
 raw_content: list[Any] = field(default_factory=lambda: [{"type": "text", "text": "mock answer"}])
 tool_calls: list[Any] = field(default_factory=list)
 usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 10, "output_tokens": 5})
 stop_reason: str = "end_turn"
 @property
 def has_tool_calls(self) -> bool:
 return len(self.tool_calls) > 0
@dataclass
class MockToolCall:
 """模拟 ToolCall。"""
 id: str = "tc_1"
 name: str = "test_tool"
 arguments: dict[str, Any] = field(default_factory=dict)
@pytest.fixture
def mock_state_manager:
 """Mock AgentStateManager 以避免 DB FK 约束。"""
 with patch("agents.core.loop.AgentStateManager") as MockMgr:
 mock_instance = MagicMock
 mock_instance.save_state = AsyncMock
 mock_instance.load_state = AsyncMock(return_value=None)
 mock_instance.log_tool_call = AsyncMock
 MockMgr.return_value = mock_instance
 yield mock_instance
def _make_event_collector -> tuple[list[AgentEvent], Any]:
 """创建事件收集器和 on_event 回调。"""
 events: list[AgentEvent] =
 async def on_event(event: AgentEvent) -> None:
 events.append(event)
 return events, on_event
# 模块级注册契约测试工具（只注册一次，避免重复注册错误）
_CONTRACT_TOOL_NAME = "sse_contract_test_tool"
if not ToolRegistry.get_tool(_CONTRACT_TOOL_NAME):
 @tool(name=_CONTRACT_TOOL_NAME, description="Tool for SSE contract testing")
 async def sse_contract_test_tool(query: str = "default") -> ToolResult:
 return ToolResult(success=True, output=f"result: {query}")
def _make_stream_provider(deltas: list[str] | None = None) -> MagicMock:
 """创建带 stream_chat 的 mock provider。"""
 if deltas is None:
 deltas = ["你", "好"]
 mock_provider = MagicMock
 mock_provider.model = "claude-sonnet-4-20250514"
 async def fake_stream_chat(messages: Any, tools: Any = None, max_tokens: int = 4096, on_text: Any = None) -> MockLLMResponse:
 if on_text:
 for d in deltas:
 await on_text(d)
 return MockLLMResponse(content="".join(deltas))
 mock_provider.stream_chat = AsyncMock(side_effect=fake_stream_chat)
 return mock_provider
def _make_tool_provider -> MagicMock:
 """创建返回 tool_use 的 mock provider（非流式）。"""
 response_with_tools = MockLLMResponse(
 content="",
 raw_content=[{
 "type": "tool_use",
 "id": "tc_contract_1",
 "name": _CONTRACT_TOOL_NAME,
 "input": {"query": "test"},
 }],
 tool_calls=[MockToolCall(
 id="tc_contract_1",
 name=_CONTRACT_TOOL_NAME,
 arguments={"query": "test"},
 )],
 stop_reason="tool_use",
 )
 response_final = MockLLMResponse(content="Done")
 mock_provider = MagicMock
 mock_provider.model = "claude-sonnet-4-20250514"
 mock_provider.chat = AsyncMock(side_effect=[response_with_tools, response_final])
 mock_provider.get_tool_schema = MagicMock(return_value=[{
 "name": _CONTRACT_TOOL_NAME,
 "description": "Tool for SSE contract testing",
 "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
 }])
 # 不提供 stream_chat，走非流式路径
 if hasattr(mock_provider, "stream_chat"):
 del mock_provider.stream_chat
 return mock_provider
# ============================================================================
# SSE 字段名契约测试
# ============================================================================
@pytest.mark.django_db
class TestSSEFieldContract:
 """SSE 字段名契约测试 — 确保后端事件字段与前端 SSEEvent 接口一致。"""
 async def test_text_delta_fields(self, mock_state_manager: MagicMock) -> None:
 """text_delta 事件必须包含 'text' 字段（而非 'delta'）。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 events, on_event = _make_event_collector
 mock_provider = _make_stream_provider(["Hello", " World"])
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=)
 context = AgentContext(session_id="contract-text-delta", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 await loop.run("hello")
 delta_events = [e for e in events if e.type == TEXT_DELTA]
 assert len(delta_events) == 2
 for event in delta_events:
 # 前端契约：必须用 "text" 字段
 assert "text" in event.data, f"text_delta 事件缺少 'text' 字段: {event.data}"
 assert isinstance(event.data["text"], str)
 # 旧字段名不应存在
 assert "delta" not in event.data, f"text_delta 事件仍包含旧字段 'delta': {event.data}"
 async def test_tool_use_start_fields(self, mock_state_manager: MagicMock) -> None:
 """tool_use_start 事件必须包含 tool_name, tool_call_id, input（而非 arguments）。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 events, on_event = _make_event_collector
 mock_provider = _make_tool_provider
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=[_CONTRACT_TOOL_NAME])
 context = AgentContext(session_id="contract-tool-start", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 await loop.run("use the tool")
 start_events = [e for e in events if e.type == TOOL_USE_START]
 assert len(start_events) >= 1
 event = start_events[0]
 # 前端契约字段
 assert "tool_name" in event.data, f"tool_use_start 缺少 'tool_name': {event.data}"
 assert isinstance(event.data["tool_name"], str)
 assert "tool_call_id" in event.data, f"tool_use_start 缺少 'tool_call_id': {event.data}"
 assert isinstance(event.data["tool_call_id"], str)
 assert "input" in event.data, f"tool_use_start 缺少 'input': {event.data}"
 assert isinstance(event.data["input"], dict)
 # 旧字段名不应存在
 assert "arguments" not in event.data, f"tool_use_start 仍包含旧字段 'arguments': {event.data}"
 async def test_tool_use_result_fields(self, mock_state_manager: MagicMock) -> None:
 """tool_use_result 事件必须包含 tool_name, tool_call_id, success, result（而非 summary）。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 events, on_event = _make_event_collector
 mock_provider = _make_tool_provider
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=[_CONTRACT_TOOL_NAME])
 context = AgentContext(session_id="contract-tool-result", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 await loop.run("use the tool")
 result_events = [e for e in events if e.type == TOOL_USE_RESULT]
 assert len(result_events) >= 1
 event = result_events[0]
 # 前端契约字段
 assert "tool_name" in event.data, f"tool_use_result 缺少 'tool_name': {event.data}"
 assert isinstance(event.data["tool_name"], str)
 assert "tool_call_id" in event.data, f"tool_use_result 缺少 'tool_call_id': {event.data}"
 assert isinstance(event.data["tool_call_id"], str)
 assert "success" in event.data, f"tool_use_result 缺少 'success': {event.data}"
 assert isinstance(event.data["success"], bool)
 assert "result" in event.data, f"tool_use_result 缺少 'result': {event.data}"
 assert isinstance(event.data["result"], str)
 # 旧字段名不应存在
 assert "summary" not in event.data, f"tool_use_result 仍包含旧字段 'summary': {event.data}"
 async def test_message_complete_fields(self, mock_state_manager: MagicMock) -> None:
 """message_complete 事件必须包含 usage, status, iterations, model。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 events, on_event = _make_event_collector
 mock_provider = MagicMock
 mock_provider.model = "claude-sonnet-4-20250514"
 mock_provider.chat = AsyncMock(return_value=MockLLMResponse)
 mock_provider.get_tool_schema = MagicMock(return_value=)
 if hasattr(mock_provider, "stream_chat"):
 del mock_provider.stream_chat
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=)
 context = AgentContext(session_id="contract-complete", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 await loop.run("hello")
 complete_events = [e for e in events if e.type == MESSAGE_COMPLETE]
 assert len(complete_events) == 1
 event = complete_events[0]
 # 前端契约字段
 assert "usage" in event.data, f"message_complete 缺少 'usage': {event.data}"
 assert isinstance(event.data["usage"], dict)
 assert "status" in event.data, f"message_complete 缺少 'status': {event.data}"
 assert isinstance(event.data["status"], str)
 assert "iterations" in event.data, f"message_complete 缺少 'iterations': {event.data}"
 assert isinstance(event.data["iterations"], int)
 assert "model" in event.data, f"message_complete 缺少 'model': {event.data}"
 assert isinstance(event.data["model"], str)
