"""Quick Task：part_started / part_delta / part_completed
SSE 事件契约 + 双轨期硬约束（旧事件不能消失）。
测试矩阵（PLAN § 测试要求：5 条契约级 + 2 条 unit）：
1. test_all_event_types_includes_new_part_constants
2. test_text_delta_followed_by_part_started_and_part_delta
3. test_tool_use_start_emits_part_completed_for_prev_text_then_part_started_for_tool
4. test_part_event_index_monotonic_per_message
5. test_message_complete_includes_parts_array_payload
6. test_legacy_event_names_still_emitted_when_new_enabled（双轨期硬约束）
7. test_thinking_does_not_emit_part_completed_for_text_part
"""
from __future__ import annotations
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langchain_core.messages import AIMessageChunk
from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig
from agents.core.events import (
 ALL_EVENT_TYPES,
 MESSAGE_COMPLETE,
 PART_COMPLETED,
 PART_DELTA,
 PART_STARTED,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_RESULT,
 TOOL_USE_START,
)
from agents.tools.base import ToolResult
def _make_config(max_turns: int = 30) -> ChatRunnerConfig:
 return ChatRunnerConfig(
 system_prompt="t",
 model="claude-sonnet-4-5",
 space_id="proj-1",
 session_id="sess-1",
 conversation_id="conv-sse",
 api_key="sk-test",
 max_turns=max_turns,
 )
@pytest.fixture(autouse=True)
def _disable_history -> AsyncGenerator[None, None]:
 with patch(
 "agents.chat_runner._load_history_messages",
 new=AsyncMock(return_value=),
 ):
 yield
def _scripted_bound(scripts: list[list[AIMessageChunk]]) -> SimpleNamespace:
 state = {"i": 0}
 async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
 i = state["i"]
 state["i"] += 1
 if i >= len(scripts):
 yield AIMessageChunk(content="done")
 return
 for chunk in scripts[i]:
 yield chunk
 return SimpleNamespace(
 astream=_astream,
 bind_tools=lambda _t: SimpleNamespace(astream=_astream),
 )
# ============================================================================
# 1. ALL_EVENT_TYPES 含 3 个新常量
# ============================================================================
def test_all_event_types_includes_new_part_constants -> None:
 assert PART_STARTED == "part_started"
 assert PART_DELTA == "part_delta"
 assert PART_COMPLETED == "part_completed"
 assert PART_STARTED in ALL_EVENT_TYPES
 assert PART_DELTA in ALL_EVENT_TYPES
 assert PART_COMPLETED in ALL_EVENT_TYPES
# ============================================================================
# 2. text_delta 后必跟 part_started + part_delta
# ============================================================================
@pytest.mark.asyncio
async def test_text_delta_followed_by_part_started_and_part_delta -> None:
 runner = ChatAnthropicRunner(_make_config)
 bound = SimpleNamespace
 async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
 yield AIMessageChunk(content="hi")
 yield AIMessageChunk(
 content=" there",
 response_metadata={"usage": {"input_tokens": 5, "output_tokens": 2}},
 )
 bound.astream = _astream # type: ignore[attr-defined]
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value={}),
 ):
 events = [e async for e in runner.stream("hi")]
 types = [e.type for e in events]
 # 第一个 text_delta 触发 part_started + part_delta
 assert TEXT_DELTA in types
 first_text_idx = types.index(TEXT_DELTA)
 assert types[first_text_idx + 1] == PART_STARTED
 assert types[first_text_idx + 2] == PART_DELTA
 # 第二个 text_delta 只跟 part_delta（同 part append）
 second_text_idx = types.index(TEXT_DELTA, first_text_idx + 1)
 assert types[second_text_idx + 1] == PART_DELTA
 # 紧跟的不是 part_started（不开新 part）
 assert types[second_text_idx + 1] != PART_STARTED
 # part_started.data.part.type == "text"
 started = next(e for e in events if e.type == PART_STARTED)
 assert started.data["part"]["type"] == "text"
 assert started.data["part"]["state"] == "streaming"
 # part_delta.data.delta_type == "text_append"
 delta = next(e for e in events if e.type == PART_DELTA)
 assert delta.data["delta_type"] == "text_append"
 assert delta.data["text"] == "hi"
# ============================================================================
# 3. tool_use_start 触发 part_completed(prev text) + part_started(tool)
# ============================================================================
@pytest.mark.asyncio
async def test_tool_use_start_emits_part_completed_for_prev_text_then_part_started_for_tool -> None:
 runner = ChatAnthropicRunner(_make_config)
 turn1 = [
 AIMessageChunk(content="先思考"),
 AIMessageChunk(
 content="",
 tool_calls=[{
 "name": "search_repository_code",
 "args": {"q": "x"},
 "id": "call_1",
 "type": "tool_call",
 }],
 response_metadata={"usage": {"input_tokens": 5, "output_tokens": 3}},
 ),
 ]
 turn2 = [
 AIMessageChunk(
 content="完成",
 response_metadata={"usage": {"input_tokens": 3, "output_tokens": 2}},
 ),
 ]
 bound = _scripted_bound([turn1, turn2])
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound
 async def _exec(_args: dict[str, object]) -> ToolResult:
 return ToolResult(success=True, output={"ok": True})
 tool_specs = {
 "search_repository_code": SimpleNamespace(
 tool=object, execute=_exec, definition=MagicMock,
 ),
 }
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
 ):
 events = [e async for e in runner.stream("找 x")]
 types = [e.type for e in events]
 # tool_use_start 之后顺序：TOOL_USE_START → PART_COMPLETED(text) → PART_STARTED(tool)
 tus_idx = types.index(TOOL_USE_START)
 assert types[tus_idx + 1] == PART_COMPLETED
 assert types[tus_idx + 2] == PART_STARTED
 # part_completed 是 text part 收尾
 pc = events[tus_idx + 1]
 assert pc.data["part"]["state"] == "done"
 # part_started 是 tool_use part
 ps = events[tus_idx + 2]
 assert ps.data["part"]["type"] == "tool_use"
 assert ps.data["part"]["status"] == "running"
 assert ps.data["part"]["tool_call_id"] == "call_1"
# ============================================================================
# 4. part_*.index 单调递增（同一 message 内）
# ============================================================================
@pytest.mark.asyncio
async def test_part_event_index_monotonic_per_message -> None:
 runner = ChatAnthropicRunner(_make_config)
 turn1 = [
 AIMessageChunk(content="A"),
 AIMessageChunk(
 content="",
 tool_calls=[{
 "name": "search_repository_code",
 "args": {"q": "x"},
 "id": "call_1",
 "type": "tool_call",
 }],
 response_metadata={"usage": {"input_tokens": 5, "output_tokens": 3}},
 ),
 ]
 turn2 = [
 AIMessageChunk(content="B",
 response_metadata={"usage": {"input_tokens": 3, "output_tokens": 2}}),
 ]
 bound = _scripted_bound([turn1, turn2])
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound
 async def _exec(_args: dict[str, object]) -> ToolResult:
 return ToolResult(success=True, output={"ok": True})
 tool_specs = {
 "search_repository_code": SimpleNamespace(
 tool=object, execute=_exec, definition=MagicMock,
 ),
 }
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
 ):
 events = [e async for e in runner.stream("hi")]
 part_starts = [e for e in events if e.type == PART_STARTED]
 indices = [e.data["index"] for e in part_starts]
 # part_started 在不同 part 上严格单调递增
 assert indices == sorted(indices)
 assert len(set(indices)) == len(indices)
# ============================================================================
# 5. message_complete payload 含 parts: list
# ============================================================================
@pytest.mark.asyncio
async def test_message_complete_includes_parts_array_payload -> None:
 runner = ChatAnthropicRunner(_make_config)
 async def _astream(_m: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
 yield AIMessageChunk(content="hi",
 response_metadata={"usage": {"input_tokens": 5, "output_tokens": 2}})
 bound = SimpleNamespace(astream=_astream)
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value={}),
 ):
 events = [e async for e in runner.stream("hi")]
 completes = [e for e in events if e.type == MESSAGE_COMPLETE]
 assert completes
 parts = completes[-1].data.get("parts")
 assert isinstance(parts, list)
 assert parts[0]["type"] == "text"
 assert parts[0]["text"] == "hi"
 assert parts[0]["state"] == "done"
# ============================================================================
# 6. 双轨期硬约束：legacy 事件不被新事件取代
# ============================================================================
@pytest.mark.asyncio
async def test_legacy_event_names_still_emitted_when_new_enabled -> None:
 runner = ChatAnthropicRunner(_make_config)
 turn1 = [
 AIMessageChunk(content="hi"),
 AIMessageChunk(
 content="",
 tool_calls=[{
 "name": "search_repository_code",
 "args": {"q": "x"},
 "id": "call_1",
 "type": "tool_call",
 }],
 response_metadata={"usage": {"input_tokens": 5, "output_tokens": 3}},
 ),
 ]
 turn2 = [
 AIMessageChunk(content="done",
 response_metadata={"usage": {"input_tokens": 3, "output_tokens": 2}}),
 ]
 bound = _scripted_bound([turn1, turn2])
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound
 async def _exec(_args: dict[str, object]) -> ToolResult:
 return ToolResult(success=True, output={"ok": True})
 tool_specs = {
 "search_repository_code": SimpleNamespace(
 tool=object, execute=_exec, definition=MagicMock,
 ),
 }
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
 ):
 events = [e async for e in runner.stream("hi")]
 types = {e.type for e in events}
 # 所有 legacy 事件都不能消失
 assert TEXT_DELTA in types
 assert TOOL_USE_START in types
 assert TOOL_USE_RESULT in types
 assert MESSAGE_COMPLETE in types
 # 新事件并存
 assert PART_STARTED in types
 assert PART_DELTA in types
 assert PART_COMPLETED in types
class _FakeChunk:
 """绕过 AIMessageChunk content_blocks 归一化，直接喂 raw blocks 让
 ``_extract_content_blocks`` 看到 thinking 块（与 test_chat_runner_parts.py 一致）。"""
 def __init__(self, blocks: list[dict[str, Any]], *, usage: dict[str, int] | None = None) -> None:
 self.content_blocks = blocks
 self.content = blocks
 self.tool_calls: list[dict[str, Any]] =
 self.text = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
 self.usage_metadata = usage or {}
 self.response_metadata = {"usage": usage} if usage else {}
 def __add__(self, other: Any) -> "_FakeChunk":
 merged = _FakeChunk(self.content_blocks + getattr(other, "content_blocks", ))
 merged.tool_calls = self.tool_calls + getattr(other, "tool_calls", )
 usage = self.usage_metadata or getattr(other, "usage_metadata", {})
 merged.usage_metadata = usage
 merged.response_metadata = {"usage": usage} if usage else {}
 return merged
# ============================================================================
# 7. thinking 不发 part_completed for text part
# ============================================================================
@pytest.mark.asyncio
async def test_thinking_does_not_emit_part_completed_for_text_part -> None:
 """thinking 与 text 互不封口；中间 thinking 不能让前面的 text part 收 part_completed。"""
 runner = ChatAnthropicRunner(_make_config)
 async def _astream(_m: list[object]) -> AsyncGenerator[Any, None]:
 yield _FakeChunk([{"type": "text", "text": "正文"}])
 yield _FakeChunk([{"type": "thinking", "thinking": "推理"}])
 yield _FakeChunk(
 [{"type": "text", "text": "后半"}],
 usage={"input_tokens": 5, "output_tokens": 3},
 )
 bound = SimpleNamespace(astream=_astream)
 fake_model = MagicMock
 fake_model.bind_tools.return_value = bound
 with (
 patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
 patch("agents.chat_runner._build_tool_specs", return_value={}),
 patch("agents.chat_runner.AIMessageChunk", _FakeChunk),
 ):
 events = [e async for e in runner.stream("hi")]
 types = [e.type for e in events]
 # part_completed 数 == 0：无 tool_use_start 场景下不应有 part 被封口
 # （MESSAGE_COMPLETE 自己只在 payload 里附 parts，不发 PART_COMPLETED 事件）
 part_completed_events = [e for e in events if e.type == PART_COMPLETED]
 assert len(part_completed_events) == 0
 # 同时确保 thinking 事件被发出
 assert THINKING in types
