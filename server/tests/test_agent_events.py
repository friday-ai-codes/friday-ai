"""AgentEvent + on_event 回调 + stream_chat 测试。
测试 Phase 新增的事件基础设施：
- AgentEvent 数据结构
- AgentLoop on_event 回调机制（向后兼容验证）
- ClaudeProvider.stream_chat 流式调用
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.events import (
 ERROR,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TITLE_GENERATED,
 TOOL_USE_RESULT,
 TOOL_USE_START,
 AgentEvent,
)
# ============================================================================
# AgentEvent 基础测试
# ============================================================================
class TestAgentEvent:
 """AgentEvent dataclass 基础测试。"""
 def test_agent_event_creation(self):
 """创建 AgentEvent 实例。"""
 event = AgentEvent(type="text_delta", data={"delta": "hello"})
 assert event.type == "text_delta"
 assert event.data == {"delta": "hello"}
 def test_agent_event_default_data(self):
 """data 默认为空 dict。"""
 event = AgentEvent(type="thinking")
 assert event.data == {}
 def test_event_type_constants(self):
 """7 个事件类型常量正确。"""
 assert TEXT_DELTA == "text_delta"
 assert TOOL_USE_START == "tool_use_start"
 assert TOOL_USE_RESULT == "tool_use_result"
 assert MESSAGE_COMPLETE == "message_complete"
 assert THINKING == "thinking"
 assert ERROR == "error"
 assert TITLE_GENERATED == "title_generated"
# ============================================================================
# AgentLoop on_event 回调测试
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
@pytest.mark.django_db
class TestAgentLoopOnEvent:
 """AgentLoop on_event 回调测试。"""
 async def test_loop_without_on_event(self, mock_state_manager):
 """不传 on_event 时 AgentLoop 行为与之前完全一致。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(return_value=MockLLMResponse)
 mock_provider.get_tool_schema = MagicMock(return_value=)
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=)
 context = AgentContext(session_id="test-session", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider)
 # on_event 应为 None
 assert loop.on_event is None
 result = await loop.run("hello")
 assert result.status == "completed"
 assert result.final_answer == "mock answer"
 async def test_loop_emits_thinking_event(self, mock_state_manager):
 """验证每次迭代发射 thinking 事件。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 events: list[AgentEvent] =
 async def on_event(event: AgentEvent) -> None:
 events.append(event)
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(return_value=MockLLMResponse)
 mock_provider.get_tool_schema = MagicMock(return_value=)
 # 不提供 stream_chat，使得 loop 走非流式路径
 if hasattr(mock_provider, "stream_chat"):
 del mock_provider.stream_chat
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=)
 context = AgentContext(session_id="test-thinking", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 await loop.run("hello")
 thinking_events = [e for e in events if e.type == THINKING]
 assert len(thinking_events) >= 1
 assert thinking_events[0].data["iteration"] == 1
 async def test_loop_emits_text_delta_events(self, mock_state_manager):
 """传入有 stream_chat 的 mock provider + on_event，验证收到 text_delta 事件。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 events: list[AgentEvent] =
 async def on_event(event: AgentEvent) -> None:
 events.append(event)
 mock_provider = MagicMock
 mock_provider.get_tool_schema = MagicMock(return_value=)
 # stream_chat 模拟：调用 on_text 回调
 async def fake_stream_chat(messages, tools=None, max_tokens=4096, on_text=None):
 if on_text:
 await on_text("你")
 await on_text("好")
 return MockLLMResponse(content="你好")
 mock_provider.stream_chat = AsyncMock(side_effect=fake_stream_chat)
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=)
 context = AgentContext(session_id="test-stream", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 await loop.run("hello")
 delta_events = [e for e in events if e.type == TEXT_DELTA]
 assert len(delta_events) == 2
 assert delta_events[0].data["delta"] == "你"
 assert delta_events[1].data["delta"] == "好"
 async def test_loop_emits_message_complete(self, mock_state_manager):
 """验证循环结束时发射 message_complete 事件（含 usage）。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 events: list[AgentEvent] =
 async def on_event(event: AgentEvent) -> None:
 events.append(event)
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(return_value=MockLLMResponse)
 mock_provider.get_tool_schema = MagicMock(return_value=)
 if hasattr(mock_provider, "stream_chat"):
 del mock_provider.stream_chat
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=)
 context = AgentContext(session_id="test-complete", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 await loop.run("hello")
 complete_events = [e for e in events if e.type == MESSAGE_COMPLETE]
 assert len(complete_events) == 1
 assert complete_events[0].data["status"] == "completed"
 assert "usage" in complete_events[0].data
 async def test_loop_emits_tool_events(self, mock_state_manager):
 """mock provider 返回 tool_use，验证 tool_use_start + tool_use_result 事件。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 from agents.tools.base import ToolResult, tool
 events: list[AgentEvent] =
 async def on_event(event: AgentEvent) -> None:
 events.append(event)
 # 注册一个测试工具
 @tool(name="test_echo_tool", description="Echo tool for testing")
 async def test_echo_tool(message: str = "default") -> ToolResult:
 return ToolResult(success=True, output=f"echo: {message}")
 # 第一次返回 tool_use，第二次返回 final answer
 response_with_tools = MockLLMResponse(
 content="",
 raw_content=[{
 "type": "tool_use",
 "id": "tc_1",
 "name": "test_echo_tool",
 "input": {"message": "test"},
 }],
 tool_calls=[MockToolCall(id="tc_1", name="test_echo_tool", arguments={"message": "test"})],
 stop_reason="tool_use",
 )
 response_final = MockLLMResponse(content="Done")
 mock_provider = MagicMock
 mock_provider.chat = AsyncMock(side_effect=[response_with_tools, response_final])
 mock_provider.get_tool_schema = MagicMock(return_value=[{
 "name": "test_echo_tool",
 "description": "Echo tool for testing",
 "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}},
 }])
 if hasattr(mock_provider, "stream_chat"):
 del mock_provider.stream_chat
 config = AgentConfig(system_prompt="test", max_iterations=5, tool_names=["test_echo_tool"])
 context = AgentContext(session_id="test-tools", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 result = await loop.run("use the tool")
 start_events = [e for e in events if e.type == TOOL_USE_START]
 result_events = [e for e in events if e.type == TOOL_USE_RESULT]
 assert len(start_events) >= 1
 assert start_events[0].data["tool_name"] == "test_echo_tool"
 assert len(result_events) >= 1
 assert result_events[0].data["success"] is True
 async def test_loop_emits_message_complete_on_max_iterations(self, mock_state_manager):
 """设置 max_iterations=1 且 provider 总是返回 tool_use，验证 max_iterations 完成事件。"""
 from agents.core.context import AgentContext
 from agents.core.loop import AgentConfig, AgentLoop
 from agents.tools.base import ToolResult, tool
 events: list[AgentEvent] =
 async def on_event(event: AgentEvent) -> None:
 events.append(event)
 @tool(name="test_infinite_tool", description="Tool that always gets called")
 async def test_infinite_tool -> ToolResult:
 return ToolResult(success=True, output="done")
 response_with_tools = MockLLMResponse(
 content="",
 raw_content=[{
 "type": "tool_use",
 "id": "tc_1",
 "name": "test_infinite_tool",
 "input": {},
 }],
 tool_calls=[MockToolCall(id="tc_1", name="test_infinite_tool", arguments={})],
 stop_reason="tool_use",
 )
 mock_provider = MagicMock
 # 总是返回 tool_use，不会自然结束
 mock_provider.chat = AsyncMock(return_value=response_with_tools)
 mock_provider.get_tool_schema = MagicMock(return_value=[{
 "name": "test_infinite_tool",
 "description": "Tool that always gets called",
 "input_schema": {"type": "object", "properties": {}},
 }])
 if hasattr(mock_provider, "stream_chat"):
 del mock_provider.stream_chat
 config = AgentConfig(
 system_prompt="test",
 max_iterations=1,
 tool_names=["test_infinite_tool"],
 )
 context = AgentContext(session_id="test-max-iter", project_id=1, user_id=1)
 loop = AgentLoop(config=config, context=context, provider=mock_provider, on_event=on_event)
 result = await loop.run("loop forever")
 assert result.status == "max_iterations"
 complete_events = [e for e in events if e.type == MESSAGE_COMPLETE]
 assert len(complete_events) == 1
 assert complete_events[0].data["status"] == "max_iterations"
# ============================================================================
# ClaudeProvider.stream_chat 测试
# ============================================================================
class TestClaudeProviderStreamChat:
 """ClaudeProvider.stream_chat 测试。"""
 async def test_stream_chat_calls_on_text(self):
 """验证 on_text 被调用。"""
 from agents.llm.claude import ClaudeProvider
 deltas: list[str] =
 async def on_text(text: str) -> None:
 deltas.append(text)
 # Mock the stream context manager
 mock_final_message = MagicMock
 mock_final_message.content = [MagicMock(type="text", text="你好世界")]
 mock_final_message.usage = MagicMock(input_tokens=10, output_tokens=5)
 mock_final_message.stop_reason = "end_turn"
 mock_stream = AsyncMock
 # text_stream 需要是 async iterable
 mock_stream.text_stream = _async_iter(["你好", "世界"])
 mock_stream.get_final_message = AsyncMock(return_value=mock_final_message)
 # 设置 async context manager
 mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
 mock_stream.__aexit__ = AsyncMock(return_value=False)
 provider = ClaudeProvider(api_key="test-key", model="test-model")
 provider.client = MagicMock
 provider.client.messages.stream = MagicMock(return_value=mock_stream)
 result = await provider.stream_chat(
 messages=[{"role": "user", "content": "hi"}],
 on_text=on_text,
 )
 assert deltas == ["你好", "世界"]
 assert result.content == "你好世界"
 assert result.usage["input_tokens"] == 10
 async def test_stream_chat_without_on_text(self):
 """on_text=None 时正常工作。"""
 from agents.llm.claude import ClaudeProvider
 mock_final_message = MagicMock
 mock_final_message.content = [MagicMock(type="text", text="response")]
 mock_final_message.usage = MagicMock(input_tokens=5, output_tokens=3)
 mock_final_message.stop_reason = "end_turn"
 mock_stream = AsyncMock
 mock_stream.text_stream = _async_iter(["response"])
 mock_stream.get_final_message = AsyncMock(return_value=mock_final_message)
 mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
 mock_stream.__aexit__ = AsyncMock(return_value=False)
 provider = ClaudeProvider(api_key="test-key", model="test-model")
 provider.client = MagicMock
 provider.client.messages.stream = MagicMock(return_value=mock_stream)
 result = await provider.stream_chat(
 messages=[{"role": "user", "content": "hi"}],
 )
 assert result.content == "response"
 async def test_stream_chat_returns_llm_response(self):
 """验证返回值是 LLMResponse 且包含 content、usage。"""
 from agents.llm.claude import ClaudeProvider
 from agents.llm.types import LLMResponse
 mock_final_message = MagicMock
 mock_final_message.content = [MagicMock(type="text", text="test content")]
 mock_final_message.usage = MagicMock(input_tokens=15, output_tokens=8)
 mock_final_message.stop_reason = "end_turn"
 mock_stream = AsyncMock
 mock_stream.text_stream = _async_iter(["test", " content"])
 mock_stream.get_final_message = AsyncMock(return_value=mock_final_message)
 mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
 mock_stream.__aexit__ = AsyncMock(return_value=False)
 provider = ClaudeProvider(api_key="test-key", model="test-model")
 provider.client = MagicMock
 provider.client.messages.stream = MagicMock(return_value=mock_stream)
 result = await provider.stream_chat(
 messages=[{"role": "user", "content": "hi"}],
 )
 assert isinstance(result, LLMResponse)
 assert result.content == "test content"
 assert result.usage == {"input_tokens": 15, "output_tokens": 8}
 assert result.stop_reason == "end_turn"
# ============================================================================
# Helpers
# ============================================================================
async def _async_iter(items: list[str]):
 """将 list 转换为 async iterator。"""
 for item in items:
 yield item
