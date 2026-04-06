from __future__ import annotations
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from agents.core.events import (
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_RESULT,
 TOOL_USE_START,
 AgentEvent,
)
from agents.core.result import AgentResult
from orchestration.graph import build_graph
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def graph_config -> dict[str, Any]:
 """带 SDK 运行时配置的 graph config。"""
 return {
 "configurable": {
 "thread_id": "test-sdk-1",
 "conversation_id": "conv-123",
 "api_key": "test-key",
 "model": "claude-sonnet-4-5",
 "session_id": "test-session-1",
 "system_prompt": "You are a test assistant.",
 "project_id": "proj-123",
 "project_name": "Test Project",
 "role": "developer",
 "agent_session_id": "",
 "notification_user_id": "",
 "api_base_url": "",
 "max_budget_usd": None,
 }
 }
def _make_mock_runner(
 events: list[AgentEvent],
 result: AgentResult | None = None,
 *,
 error: Exception | None = None,
) -> MagicMock:
 """构建 mock SDKAgentRunner 实例。"""
 async def _stream(prompt: str) -> AsyncGenerator[AgentEvent, None]:
 if error is not None:
 raise error
 for event in events:
 yield event
 mock_runner = MagicMock
 mock_runner.stream = _stream
 mock_runner.result = result
 return mock_runner
def _default_result(final_answer: str = "Hello!") -> AgentResult:
 return AgentResult(
 output=,
 status="completed",
 final_answer=final_answer,
 usage={"input_tokens": 100, "output_tokens": 50},
 metadata={"cost_usd": 0.01},
 )
def _default_events(text: str = "Hello!") -> list[AgentEvent]:
 return [
 AgentEvent(type=TEXT_DELTA, data={"text": text}),
 AgentEvent(
 type=MESSAGE_COMPLETE,
 data={"result": text, "status": "completed", "usage": {}, "model": "claude-sonnet-4-5"},
 ),
 ]
def _patch_sdk(mock_runner: MagicMock): # noqa: ANN202
 """Patch SDKAgentRunner 构造函数返回 mock_runner。"""
 return patch("orchestration.graph.SDKAgentRunner", return_value=mock_runner)
# ---------------------------------------------------------------------------
# Phase 保留测试（更新为兼容 SDK 集成后的 executing_node）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_graph_compiles -> None:
 """: StateGraph 可编译为可运行 workflow。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 assert graph is not None
@pytest.mark.asyncio
async def test_normal_flow_without_blocking(graph_config: dict[str, Any]) -> None:
 """: 无阻塞任务时 graph 完整执行 planning → executing → finalizing。"""
 mock_runner = _make_mock_runner(_default_events, _default_result)
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 result = await graph.ainvoke(
 {"user_message": "hello", "run_id": "test-run-1"},
 config=graph_config,
 )
 assert result["phase"] == "completed"
 assert result["final_answer"] == "Hello!"
@pytest.mark.asyncio
async def test_interrupt_pauses_on_blocking_tasks -> None:
 """: 有阻塞任务时 graph 在 waiting 节点暂停。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 config = {"configurable": {"thread_id": "test-interrupt-1"}}
 blocking = [{"task_type": "code_review", "task_id": "", "params": {}}]
 result = await graph.ainvoke(
 {"user_message": "review this", "run_id": "run-int-1", "blocking_tasks": blocking},
 config=config,
 )
 assert result["phase"] == "waiting"
 state = await graph.aget_state(config)
 assert "waiting" in state.next
 assert any(t.interrupts for t in state.tasks)
@pytest.mark.asyncio
async def test_resume_continues_after_interrupt -> None:
 """: Command(resume=...) 恢复 graph 并传入结果。"""
 graph = build_graph.compile(checkpointer=MemorySaver)
 config = {"configurable": {"thread_id": "test-resume-1"}}
 blocking = [{"task_type": "code_review", "task_id": "", "params": {}}]
 await graph.ainvoke(
 {"user_message": "review this", "run_id": "run-res-1", "blocking_tasks": blocking},
 config=config,
 )
 result = await graph.ainvoke(
 Command(resume={"task_id": "", "output": "review approved"}),
 config=config,
 )
 assert result["phase"] == "completed"
 assert result["final_answer"] == "review approved"
 assert result["blocking_tasks"] ==
@pytest.mark.asyncio
async def test_phase_transitions(graph_config: dict[str, Any]) -> None:
 """: graph state 中 phase 字段在每个节点正确转换。"""
 mock_runner = _make_mock_runner(_default_events, _default_result)
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 result = await graph.ainvoke(
 {"user_message": "hello", "run_id": "run-Phase"},
 config=graph_config,
 )
 assert result["phase"] == "completed"
 phases_seen: list[str] =
 async for snapshot in graph.aget_state_history(graph_config):
 p = snapshot.values.get("phase")
 if p and (not phases_seen or phases_seen[-1] != p):
 phases_seen.append(p)
 phases_seen.reverse
 assert phases_seen == ["executing", "finalizing", "completed"]
@pytest.mark.asyncio
async def test_graph_state_is_authoritative(graph_config: dict[str, Any]) -> None:
 """: graph checkpoint 保存的 state 为 authoritative source。"""
 mock_runner = _make_mock_runner(_default_events, _default_result)
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"user_message": "hello", "run_id": "run-auth-1"},
 config=graph_config,
 )
 state = await graph.aget_state(graph_config)
 assert state.values["phase"] == "completed"
 assert state.values["run_id"] == "run-auth-1"
 assert state.values["user_message"] == "hello"
# ---------------------------------------------------------------------------
# Phase 新增 SDK 集成测试
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_executing_node_runs_sdk_and_streams_events(graph_config: dict[str, Any]) -> None:
 """executing_node 运行 SDK 并通过 StreamWriter 推送事件。"""
 events = _default_events("SDK response")
 mock_runner = _make_mock_runner(events, _default_result("SDK response"))
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 streamed: list[dict[str, Any]] =
 async for chunk in graph.astream(
 {"user_message": "test", "run_id": "run-stream-1"},
 config=graph_config,
 stream_mode="custom",
 ):
 streamed.append(chunk)
 types = [e["type"] for e in streamed]
 assert TEXT_DELTA in types
 assert MESSAGE_COMPLETE in types
@pytest.mark.asyncio
async def test_executing_node_accumulates_thinking(graph_config: dict[str, Any]) -> None:
 """executing_node 累积 thinking 事件到 state。"""
 events = [
 AgentEvent(type=THINKING, data={"thinking": "Let me think about this..."}),
 AgentEvent(type=THINKING, data={"thinking": "The answer is clear."}),
 *_default_events,
 ]
 mock_runner = _make_mock_runner(events, _default_result)
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"user_message": "think hard", "run_id": "run-think-1"},
 config=graph_config,
 )
 state = await graph.aget_state(graph_config)
 thinking = state.values.get("accumulated_thinking", )
 assert len(thinking) == 2
 assert "Let me think about this..." in thinking
 assert "The answer is clear." in thinking
@pytest.mark.asyncio
async def test_executing_node_accumulates_tool_calls(graph_config: dict[str, Any]) -> None:
 """executing_node 累积 tool call 事件到 state。"""
 events = [
 AgentEvent(
 type=TOOL_USE_START,
 data={"tool_call_id": "tc-1", "tool_name": "search", "input": {"query": "test"}},
 ),
 AgentEvent(
 type=TOOL_USE_RESULT,
 data={"tool_call_id": "tc-1", "tool_name": "search", "result": "found 3 results"},
 ),
 *_default_events,
 ]
 mock_runner = _make_mock_runner(events, _default_result)
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"user_message": "search something", "run_id": "run-tool-1"},
 config=graph_config,
 )
 state = await graph.aget_state(graph_config)
 tool_calls = state.values.get("tool_calls", )
 assert len(tool_calls) == 1
 assert tool_calls[0]["name"] == "search"
 assert tool_calls[0]["result"] == "found 3 results"
 assert tool_calls[0]["input"] == {"query": "test"}
@pytest.mark.asyncio
async def test_executing_node_populates_result_metadata(graph_config: dict[str, Any]) -> None:
 """executing_node 将 SDK result 中的 usage/cost 写入 result_metadata。"""
 mock_runner = _make_mock_runner(_default_events, _default_result)
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 await graph.ainvoke(
 {"user_message": "cost check", "run_id": "run-meta-1"},
 config=graph_config,
 )
 state = await graph.aget_state(graph_config)
 meta = state.values.get("result_metadata", {})
 assert meta["status"] == "completed"
 assert meta["cost_usd"] == 0.01
 assert meta["input_tokens"] == 100
 assert meta["output_tokens"] == 50
@pytest.mark.asyncio
async def test_graph_full_flow_with_sdk(graph_config: dict[str, Any]) -> None:
 """端到端 flow: planning → executing (mock SDK) → finalizing → completed。"""
 mock_runner = _make_mock_runner(_default_events("full flow"), _default_result("full flow"))
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 result = await graph.ainvoke(
 {"user_message": "end to end", "run_id": "run-e2e-1"},
 config=graph_config,
 )
 assert result["phase"] == "completed"
 assert result["final_answer"] == "full flow"
 assert result.get("accumulated_thinking") ==
 assert result.get("tool_calls") ==
 assert result["result_metadata"]["status"] == "completed"
 phases_seen: list[str] =
 async for snapshot in graph.aget_state_history(graph_config):
 p = snapshot.values.get("phase")
 if p and (not phases_seen or phases_seen[-1] != p):
 phases_seen.append(p)
 phases_seen.reverse
 assert phases_seen == ["executing", "finalizing", "completed"]
@pytest.mark.asyncio
async def test_executing_node_handles_sdk_error(graph_config: dict[str, Any]) -> None:
 """SDK 异常时 executing_node 返回 phase=ERROR + result_metadata 包含错误。"""
 mock_runner = _make_mock_runner(, error=RuntimeError("SDK crashed"))
 mock_runner.result = None
 with _patch_sdk(mock_runner):
 graph = build_graph.compile(checkpointer=MemorySaver)
 result = await graph.ainvoke(
 {"user_message": "trigger error", "run_id": "run-err-1"},
 config=graph_config,
 )
 assert result["phase"] == "error"
 assert result["result_metadata"]["error"] == "SDK 运行异常"
