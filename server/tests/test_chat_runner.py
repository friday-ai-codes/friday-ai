from __future__ import annotations
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import AIMessageChunk
from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig, _thinking_budget_tokens
from agents.core.events import MESSAGE_COMPLETE, TEXT_DELTA, TOOL_USE_RESULT, TOOL_USE_START
from agents.tools.base import ToolResult
def _make_config -> ChatRunnerConfig:
 return ChatRunnerConfig(
 system_prompt="你是测试助手",
 model="claude-sonnet-4-5",
 project_id="proj-1",
 session_id="sess-1",
 # conversation fixture omitted
 api_key="sk-test",
 )
def _make_bound_model(chunks: list[AIMessageChunk]):
 async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
 for chunk in chunks:
 yield chunk
 return SimpleNamespace(astream=_astream)
def test_thinking_budget_enabled_for_supported_claude_models -> None:
 assert _thinking_budget_tokens('claude-sonnet-4-5') == 4096
 assert _thinking_budget_tokens('claude-opus-4-5-thinking') == 4096
 assert _thinking_budget_tokens('gpt-5') is None
def test_build_model_enables_thinking_with_temperature_one -> None:
 runner = ChatAnthropicRunner(_make_config)
 with patch('agents.chat_runner.ChatAnthropic') as mock_chat_anthropic:
 runner._build_model
 kwargs = mock_chat_anthropic.call_args.kwargs
 assert kwargs['thinking'] == {'type': 'enabled', 'budget_tokens': 4096}
 assert kwargs['temperature'] == 1
@pytest.mark.asyncio
async def test_chat_runner_streams_text_and_message_complete -> None:
 runner = ChatAnthropicRunner(_make_config)
 bound_model = _make_bound_model([
 AIMessageChunk(content="你"),
 AIMessageChunk(
 content="好",
 response_metadata={"usage": {"input_tokens": 10, "output_tokens": 2}},
 ),
 ])
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound_model
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value={}),
 ):
 events = [event async for event in runner.stream("你好")]
 assert [event.type for event in events] == [TEXT_DELTA, TEXT_DELTA, MESSAGE_COMPLETE]
 assert events[-1].data["result"] == "你好"
 assert runner.result is not None
 assert runner.result.final_answer == "你好"
 assert runner.result.usage == {"input_tokens": 10, "output_tokens": 2}
@pytest.mark.asyncio
async def test_chat_runner_emits_tool_events_for_blocking_tool -> None:
 runner = ChatAnthropicRunner(_make_config)
 bound_model = _make_bound_model([
 AIMessageChunk(
 content="",
 tool_calls=[{
 "name": "deep_analysis",
 "args": {"task_description": "分析项目"},
 "id": "call_1",
 "type": "tool_call",
 }],
 response_metadata={"usage": {"input_tokens": 20, "output_tokens": 5}},
 ),
 ])
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound_model
 async def _execute(_arguments: dict[str, object]) -> ToolResult:
 return ToolResult(
 success=True,
 output={
 "__blocking_task__": True,
 "task_id": "deep-1",
 "task_type": "deep_analysis",
 },
 )
 tool_specs = {
 "deep_analysis": SimpleNamespace(
 tool=object,
 execute=_execute,
 definition=MagicMock,
 ),
 }
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
 ):
 events = [event async for event in runner.stream("分析一下")]
 assert [event.type for event in events] == [TOOL_USE_START, TOOL_USE_RESULT]
 assert events[-1].data["result"]["__blocking_task__"] is True
 assert runner.result is not None
 assert runner.result.status == "completed"
 assert runner.result.final_answer == ""
