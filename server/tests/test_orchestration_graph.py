from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig
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


@pytest.fixture()
def graph_config() -> RunnableConfig:
    """带 Chat runner 运行时配置的 graph config。"""
    return cast(RunnableConfig, {
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
    })


def _make_mock_runner(
    events: list[AgentEvent],
    result: AgentResult | None = None,
    *,
    error: Exception | None = None,
) -> MagicMock:
    """构建 mock SDKAgentRunner 实例。"""

    async def _stream(prompt: str, **kwargs) -> AsyncGenerator[AgentEvent, None]:
        if error is not None:
            raise error
        for event in events:
            yield event

    mock_runner = MagicMock()
    mock_runner.stream = _stream
    mock_runner.result = result
    return mock_runner


def _default_result(final_answer: str = "Hello!") -> AgentResult:
    return AgentResult(
        output=[],
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


def _patch_sdk(mock_runner: MagicMock):  # noqa: ANN202
    """Patch ChatAnthropicRunner 构造函数返回 mock_runner。"""
    return patch("orchestration.graph.ChatAnthropicRunner", return_value=mock_runner)


# ---------------------------------------------------------------------------
# implementation 保留测试（更新为兼容 SDK 集成后的 executing_node）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_compiles() -> None:
    """StateGraph 可编译为可运行 workflow。"""
    graph = build_graph().compile(checkpointer=MemorySaver())
    assert graph is not None


@pytest.mark.asyncio
async def test_normal_flow_without_blocking(graph_config: RunnableConfig) -> None:
    """无阻塞任务时 graph 完整执行 planning → executing → finalizing。"""
    mock_runner = _make_mock_runner(_default_events(), _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {"user_message": "hello", "run_id": "test-run-1"},
            config=graph_config,
        )

    assert result["phase"] == "completed"
    assert result["final_answer"] == "Hello!"


@pytest.mark.asyncio
async def test_interrupt_pauses_on_blocking_tasks(graph_config: RunnableConfig) -> None:
    """SDK tool 返回 __blocking_task__ 标记时 graph 在 waiting 节点暂停。"""
    blocking_result = {
        "__blocking_task__": True,
        "task_type": "deep_analysis",
        "task_id": "contract",
        "params": {"query": "review this"},
    }
    events = [
        AgentEvent(
            type=TOOL_USE_START,
            data={"tool_call_id": "tc-block-1", "tool_name": "deep_analysis", "input": {}},
        ),
        AgentEvent(
            type=TOOL_USE_RESULT,
            data={"tool_call_id": "tc-block-1", "tool_name": "deep_analysis", "result": blocking_result},
        ),
        *_default_events(),
    ]
    mock_runner = _make_mock_runner(events, _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {"user_message": "review this", "run_id": "run-int-1"},
            config=graph_config,
        )

    assert result["phase"] == "waiting"

    state = await graph.aget_state(graph_config)
    assert "waiting" in state.next
    assert any(t.interrupts for t in state.tasks)


@pytest.mark.asyncio
async def test_resume_continues_after_interrupt(graph_config: RunnableConfig) -> None:
    """Command(resume=list[BlockingTaskResult]) 恢复 graph 回到 executing。"""
    blocking_result = {
        "__blocking_task__": True,
        "task_type": "deep_analysis",
        "task_id": "contract",
        "params": {"query": "review this"},
    }
    events_first = [
        AgentEvent(
            type=TOOL_USE_START,
            data={"tool_call_id": "tc-block-1", "tool_name": "deep_analysis", "input": {}},
        ),
        AgentEvent(
            type=TOOL_USE_RESULT,
            data={"tool_call_id": "tc-block-1", "tool_name": "deep_analysis", "result": blocking_result},
        ),
        *_default_events(),
    ]
    mock_runner_first = _make_mock_runner(events_first, _default_result())
    mock_runner_second = _make_mock_runner(
        _default_events("综合回答"), _default_result("综合回答"),
    )

    with _patch_sdk(mock_runner_first):
        graph = build_graph().compile(checkpointer=MemorySaver())
        await graph.ainvoke(
            {"user_message": "review this", "run_id": "run-res-1"},
            config=graph_config,
        )

    resume_results = [
        {"task_id": "contract", "task_type": "deep_analysis", "success": True, "output": "分析结果", "error": ""},
    ]

    with _patch_sdk(mock_runner_second):
        result = await graph.ainvoke(
            Command(resume=resume_results),
            config=graph_config,
        )

    assert result["phase"] == "completed"
    assert result["final_answer"] == "综合回答"
    assert result["blocking_tasks"] == []
    assert result.get("blocking_results") == []


@pytest.mark.asyncio
async def test_phase_transitions(graph_config: RunnableConfig) -> None:
    """graph state 中 phase 字段在每个节点正确转换。"""
    mock_runner = _make_mock_runner(_default_events(), _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {"user_message": "hello", "run_id": "run-phase-1"},
            config=graph_config,
        )

    assert result["phase"] == "completed"

    phases_seen: list[str] = []
    async for snapshot in graph.aget_state_history(graph_config):
        p = snapshot.values.get("phase")
        if p and (not phases_seen or phases_seen[-1] != p):
            phases_seen.append(p)

    phases_seen.reverse()
    assert phases_seen == ["executing", "finalizing", "completed"]


@pytest.mark.asyncio
async def test_graph_state_is_authoritative(graph_config: RunnableConfig) -> None:
    """graph checkpoint 保存的 state 为 authoritative source。"""
    mock_runner = _make_mock_runner(_default_events(), _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        await graph.ainvoke(
            {"user_message": "hello", "run_id": "run-auth-1"},
            config=graph_config,
        )

    state = await graph.aget_state(graph_config)
    assert state.values["phase"] == "completed"
    assert state.values["run_id"] == "run-auth-1"
    assert state.values["user_message"] == "hello"


# ---------------------------------------------------------------------------
# implementation 新增 SDK 集成测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executing_node_runs_sdk_and_streams_events(graph_config: RunnableConfig) -> None:
    """executing_node 运行 SDK 并通过 StreamWriter 推送事件。"""
    events = _default_events("SDK response")
    mock_runner = _make_mock_runner(events, _default_result("SDK response"))

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        streamed: list[dict[str, Any]] = []
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
async def test_executing_node_accumulates_thinking(graph_config: RunnableConfig) -> None:
    """executing_node 累积 thinking 事件到 state。"""
    events = [
        AgentEvent(type=THINKING, data={"thinking": "Let me think about this..."}),
        AgentEvent(type=THINKING, data={"thinking": "The answer is clear."}),
        *_default_events(),
    ]
    mock_runner = _make_mock_runner(events, _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        await graph.ainvoke(
            {"user_message": "think hard", "run_id": "run-think-1"},
            config=graph_config,
        )

    state = await graph.aget_state(graph_config)
    thinking = state.values.get("accumulated_thinking", [])
    assert len(thinking) == 2
    assert "Let me think about this..." in thinking
    assert "The answer is clear." in thinking


@pytest.mark.asyncio
async def test_executing_node_accumulates_tool_calls(graph_config: RunnableConfig) -> None:
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
        *_default_events(),
    ]
    mock_runner = _make_mock_runner(events, _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        await graph.ainvoke(
            {"user_message": "search something", "run_id": "run-tool-1"},
            config=graph_config,
        )

    state = await graph.aget_state(graph_config)
    tool_calls = state.values.get("tool_calls", [])
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "search"
    assert tool_calls[0]["result"] == "found 3 results"
    assert tool_calls[0]["input"] == {"query": "test"}


@pytest.mark.asyncio
async def test_executing_node_populates_result_metadata(graph_config: RunnableConfig) -> None:
    """executing_node 将 SDK result 中的 usage/cost 写入 result_metadata。"""
    mock_runner = _make_mock_runner(_default_events(), _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
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
async def test_graph_full_flow_with_sdk(graph_config: RunnableConfig) -> None:
    """端到端 flow: planning → executing (mock SDK) → finalizing → completed。"""
    mock_runner = _make_mock_runner(_default_events("full flow"), _default_result("full flow"))

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {"user_message": "end to end", "run_id": "run-e2e-1"},
            config=graph_config,
        )

    assert result["phase"] == "completed"
    assert result["final_answer"] == "full flow"
    assert result.get("accumulated_thinking") == []
    assert result.get("tool_calls") == []
    assert result["result_metadata"]["status"] == "completed"

    phases_seen: list[str] = []
    async for snapshot in graph.aget_state_history(graph_config):
        p = snapshot.values.get("phase")
        if p and (not phases_seen or phases_seen[-1] != p):
            phases_seen.append(p)
    phases_seen.reverse()
    assert phases_seen == ["executing", "finalizing", "completed"]


@pytest.mark.asyncio
async def test_executing_node_handles_sdk_error(graph_config: RunnableConfig) -> None:
    """SDK 异常时 executing_node 返回 phase=ERROR + result_metadata 包含错误。"""
    mock_runner = _make_mock_runner([], error=RuntimeError("SDK crashed"))
    mock_runner.result = None

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {"user_message": "trigger error", "run_id": "run-err-1"},
            config=graph_config,
        )

    assert result["phase"] == "error"
    # 非用户可读领域异常统一降级为通用文案（_user_facing_runner_error），不泄漏内部细节
    assert result["result_metadata"]["error"] == "服务内部错误，请稍后重试"


# ---------------------------------------------------------------------------
# implementation 新增 — blocking task 提取、循环拓扑、结果注入
# ---------------------------------------------------------------------------


def _blocking_task_events(
    *task_defs: tuple[str, str],
) -> list[AgentEvent]:
    """生成包含 __blocking_task__ 标记的 tool call 事件序列。

    task_defs: (task_id, task_type) 元组序列。
    """
    events: list[AgentEvent] = []
    for task_id, task_type in task_defs:
        events.append(AgentEvent(
            type=TOOL_USE_START,
            data={"tool_call_id": f"tc-{task_id}", "tool_name": task_type, "input": {}},
        ))
        events.append(AgentEvent(
            type=TOOL_USE_RESULT,
            data={
                "tool_call_id": f"tc-{task_id}",
                "tool_name": task_type,
                "result": {
                    "__blocking_task__": True,
                    "task_type": task_type,
                    "task_id": task_id,
                    "params": {},
                },
            },
        ))
    events.extend(_default_events())
    return events


@pytest.mark.asyncio
async def test_waiting_resumes_to_executing(graph_config: RunnableConfig) -> None:
    """resume 后 graph 回到 executing（非 finalizing）。"""
    events_first = _blocking_task_events(("bt-1", "deep_analysis"))
    mock_runner_first = _make_mock_runner(events_first, _default_result())
    mock_runner_second = _make_mock_runner(
        _default_events("结果综合"), _default_result("结果综合"),
    )

    with _patch_sdk(mock_runner_first):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {"user_message": "分析代码", "run_id": "run-work-item"},
            config=graph_config,
        )
    assert result["phase"] == "waiting"

    resume_results = [
        {"task_id": "bt-1", "task_type": "deep_analysis", "success": True, "output": "分析完成", "error": ""},
    ]
    with _patch_sdk(mock_runner_second):
        result = await graph.ainvoke(
            Command(resume=resume_results),
            config=graph_config,
        )

    assert result["phase"] == "completed"

    phases_seen: list[str] = []
    async for snapshot in graph.aget_state_history(graph_config):
        p = snapshot.values.get("phase")
        if p and (not phases_seen or phases_seen[-1] != p):
            phases_seen.append(p)
    phases_seen.reverse()
    assert "executing" in phases_seen
    assert "waiting" in phases_seen


@pytest.mark.asyncio
async def test_multiple_blocking_tasks_collected(graph_config: RunnableConfig) -> None:
    """同一轮 SDK 运行中多个 blocking tasks 都被收集。"""
    events = _blocking_task_events(
        ("bt-a", "deep_analysis"),
        ("bt-b", "deep_analysis"),
    )
    mock_runner = _make_mock_runner(events, _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {"user_message": "多任务分析", "run_id": "run-work-item"},
            config=graph_config,
        )

    assert result["phase"] == "waiting"
    blocking_tasks = result.get("blocking_tasks", [])
    assert len(blocking_tasks) == 2
    task_ids = {t["task_id"] for t in blocking_tasks}
    assert task_ids == {"bt-a", "bt-b"}


@pytest.mark.asyncio
async def test_blocking_tasks_win_over_relev_low_confidence(graph_config: RunnableConfig) -> None:
    """coding-plan workflow hotfix 回归保护（284 DEBUG）：

    同一轮 SDK 运行中既有 analyze_repository_relevance（低置信结果）又有
    deep_analysis blocking task 时，graph 必须优先走 WAITING 路径而不是
    WAITING_CLARIFICATION —— 否则 blocking task 派发的副作用（SubAgentSession
    + 容器）会被 clarification interrupt 孤立，BarrierManager 永远收不到
    barrier 注册，deep_analysis_completion callback 静默丢失。
    """
    events: list[AgentEvent] = [
        # LLM 第一步：调 analyze_repository_relevance，返回 4 个极接近的候选
        # (top2/top1 = 0.992 → 在 0.92 阈值下仍是 low_confidence)
        AgentEvent(
            type=TOOL_USE_START,
            data={
                "tool_call_id": "tc-relev-1",
                "tool_name": "analyze_repository_relevance",
                "input": {"query": "entrance", "space_id": "sp-1"},
            },
        ),
        AgentEvent(
            type=TOOL_USE_RESULT,
            data={
                "tool_call_id": "tc-relev-1",
                "tool_name": "analyze_repository_relevance",
                "result": {
                    "data": {
                        "candidates": [
                            {"repository_id": "r1", "repository_name": "repo-a", "score": 0.7765, "level": "high", "evidence": "e1", "selected_by_ai": True},
                            {"repository_id": "r2", "repository_name": "repo-b", "score": 0.7704, "level": "high", "evidence": "e2", "selected_by_ai": True},
                            {"repository_id": "r3", "repository_name": "repo-c", "score": 0.7602, "level": "high", "evidence": "e3", "selected_by_ai": True},
                            {"repository_id": "r4", "repository_name": "repo-d", "score": 0.7567, "level": "high", "evidence": "e4", "selected_by_ai": True},
                        ],
                        "threshold": 0.5,
                        "total_candidates": 4,
                    },
                },
            },
        ),
        # LLM 第二步：派发 deep_analysis blocking task（典型 Test 4 场景）
        AgentEvent(
            type=TOOL_USE_START,
            data={"tool_call_id": "tc-block-1", "tool_name": "deep_analysis", "input": {}},
        ),
        AgentEvent(
            type=TOOL_USE_RESULT,
            data={
                "tool_call_id": "tc-block-1",
                "tool_name": "deep_analysis",
                "result": {
                    "__blocking_task__": True,
                    "task_type": "deep_analysis",
                    "task_id": "bt-deep-1",
                    "params": {},
                },
            },
        ),
    ]
    events.extend(_default_events())
    mock_runner = _make_mock_runner(events, _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        result = await graph.ainvoke(
            {
                "user_message": "分析下 study-app 和 problem-app 里 entrance 字段",
                "run_id": "run-work-item",
            },
            config=graph_config,
        )

    # 关键断言：phase 必须是 waiting（blocking 路径），不是 waiting_clarification
    assert result["phase"] == "waiting", (
        f"Expected blocking_tasks 优先于 pending_clarification，实际 phase={result['phase']}。"
        f"修复回退？详见 project docs"
    )
    blocking_tasks = result.get("blocking_tasks", [])
    assert len(blocking_tasks) == 1
    assert blocking_tasks[0]["task_id"] == "bt-deep-1"
    # pending_clarification 不应被写入 state
    assert not result.get("pending_clarification")


@pytest.mark.asyncio
async def test_blocking_marker_suppresses_premature_text_events(graph_config: RunnableConfig) -> None:
    """blocking tool 返回后，后续同轮正文不应再透传给前端。"""
    events = [
        AgentEvent(
            type=TOOL_USE_START,
            data={"tool_call_id": "tc-block-1", "tool_name": "deep_analysis", "input": {}},
        ),
        AgentEvent(
            type=TOOL_USE_RESULT,
            data={
                "tool_call_id": "tc-block-1",
                "tool_name": "deep_analysis",
                "result": {
                    "__blocking_task__": True,
                    "task_type": "deep_analysis",
                    "task_id": "bt-cut-1",
                    "params": {},
                },
            },
        ),
        AgentEvent(type=THINKING, data={"thinking": "不该继续暴露这段思考"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "我还拿不到结果"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"result": "我还拿不到结果", "status": "completed"}),
    ]
    mock_runner = _make_mock_runner(events, _default_result("我还拿不到结果"))

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        streamed_types: list[str] = []
        async for chunk in graph.astream(
            {"user_message": "分析代码", "run_id": "run-work-item"},
            config=graph_config,
            stream_mode=["custom", "values"],
            version="v2",
        ):
            if chunk["type"] == "custom":
                streamed_types.append(chunk["data"]["type"])

    assert TOOL_USE_START in streamed_types
    assert TOOL_USE_RESULT in streamed_types
    assert THINKING not in streamed_types
    assert TEXT_DELTA not in streamed_types
    assert MESSAGE_COMPLETE not in streamed_types


@pytest.mark.asyncio
async def test_blocking_results_injection(graph_config: RunnableConfig) -> None:
    """二次 executing 运行注入 blocking_results 生成最终回答。"""
    events_first = _blocking_task_events(("bt-inj-1", "deep_analysis"))
    mock_runner_first = _make_mock_runner(events_first, _default_result())

    with _patch_sdk(mock_runner_first):
        graph = build_graph().compile(checkpointer=MemorySaver())
        await graph.ainvoke(
            {"user_message": "请分析这段代码", "run_id": "run-work-item"},
            config=graph_config,
        )

    resume_results = [
        {
            "task_id": "bt-inj-1",
            "task_type": "deep_analysis",
            "success": True,
            "output": "代码中存在 3 个潜在问题",
            "error": "",
        },
    ]

    mock_runner_second = _make_mock_runner(
        _default_events("根据分析结果，以下是建议"),
        _default_result("根据分析结果，以下是建议"),
    )

    with _patch_sdk(mock_runner_second):
        result = await graph.ainvoke(
            Command(resume=resume_results),
            config=graph_config,
        )

    assert result["phase"] == "completed"
    assert result["final_answer"] == "根据分析结果，以下是建议"
    assert result.get("blocking_results") == []


@pytest.mark.skip(
    reason=(
        "OBSOLETE — implementation wait-execute loop 阈值在 v22.0 节点错误处理后调整为 2，"
        "且 OrchestrationRun.run_id 字段升级为 UUID（旧测试用 string run_id 导致 "
        "_persist_run_phase 静默失败 → phase 状态错乱）。需在 v24.0 重写为 UUID + "
        "新阈值断言。"
    )
)
@pytest.mark.asyncio
async def test_loop_count_prevents_infinite_loops(graph_config: RunnableConfig) -> None:
    """wait-execute 循环超过 2 次时强制走 finalizing。"""
    blocking_events = _blocking_task_events(("bt-loop", "deep_analysis"))

    mock_runner_1 = _make_mock_runner(blocking_events, _default_result())
    mock_runner_2 = _make_mock_runner(blocking_events, _default_result())
    mock_runner_3 = _make_mock_runner(blocking_events, _default_result("强制结束"))

    resume_results = [
        {"task_id": "bt-loop", "task_type": "deep_analysis", "success": True, "output": "结果", "error": ""},
    ]

    with _patch_sdk(mock_runner_1):
        graph = build_graph().compile(checkpointer=MemorySaver())
        r = await graph.ainvoke(
            {"user_message": "循环测试", "run_id": "run-work-item"},
            config=graph_config,
        )
    assert r["phase"] == "waiting"

    with _patch_sdk(mock_runner_2):
        r = await graph.ainvoke(Command(resume=resume_results), config=graph_config)
    assert r["phase"] == "waiting"

    with _patch_sdk(mock_runner_3):
        r = await graph.ainvoke(Command(resume=resume_results), config=graph_config)

    assert r["phase"] == "completed"
    assert r.get("wait_execute_loops", 0) >= 2


@pytest.mark.asyncio
async def test_blocking_results_cleared_after_second_run(graph_config: RunnableConfig) -> None:
    """blocking_results 在二次运行后被清空。"""
    events_first = _blocking_task_events(("bt-clr-1", "deep_analysis"))
    mock_runner_first = _make_mock_runner(events_first, _default_result())
    mock_runner_second = _make_mock_runner(
        _default_events("清理验证"), _default_result("清理验证"),
    )

    with _patch_sdk(mock_runner_first):
        graph = build_graph().compile(checkpointer=MemorySaver())
        await graph.ainvoke(
            {"user_message": "清理测试", "run_id": "run-work-item"},
            config=graph_config,
        )

    resume_results = [
        {"task_id": "bt-clr-1", "task_type": "deep_analysis", "success": True, "output": "ok", "error": ""},
    ]
    with _patch_sdk(mock_runner_second):
        result = await graph.ainvoke(
            Command(resume=resume_results),
            config=graph_config,
        )

    assert result["phase"] == "completed"
    assert result.get("blocking_results") == []


# ---------------------------------------------------------------------------
# _persist_run_phase 单元测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_run_phase_calls_aupdate() -> None:
    """_persist_run_phase 调用 aupdate(phase=X)。"""
    from unittest.mock import AsyncMock, patch as _patch

    from orchestration.graph import _persist_run_phase

    mock_aupdate = AsyncMock(return_value=1)
    with _patch("orchestration.models.OrchestrationRun") as mock_cls:
        mock_cls.objects.filter.return_value.aupdate = mock_aupdate
        await _persist_run_phase("run-123", "executing")
    mock_aupdate.assert_awaited_once_with(phase="executing")


@pytest.mark.asyncio
async def test_persist_run_phase_swallows_exception() -> None:
    """DB 写入失败时 log warning 不抛异常。"""
    from unittest.mock import AsyncMock, patch as _patch

    from orchestration.graph import _persist_run_phase

    mock_aupdate = AsyncMock(side_effect=RuntimeError("db down"))
    with _patch("orchestration.models.OrchestrationRun") as mock_cls:
        mock_cls.objects.filter.return_value.aupdate = mock_aupdate
        # 不应抛异常
        await _persist_run_phase("run-fail", "executing")


# ---------------------------------------------------------------------------
# planning_node 单元测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planning_node_emits_phase_transition() -> None:
    """planning_node 发射 PHASE_TRANSITION executing 事件。"""
    from unittest.mock import AsyncMock, patch as _patch

    from agents.core.events import PHASE_TRANSITION
    from orchestration.graph import planning_node

    writer = MagicMock()
    state: dict[str, Any] = {"user_message": "hello", "run_id": "test-run-1"}

    with _patch("orchestration.models.OrchestrationRun") as mock_cls:
        mock_cls.objects.filter.return_value.aupdate = AsyncMock(return_value=1)
        result = await planning_node(state, writer)

    writer.assert_called_once()
    call_args = writer.call_args[0][0]
    assert call_args["type"] == PHASE_TRANSITION
    assert call_args["data"]["phase"] == "executing"
    assert result["phase"] == "executing"


@pytest.mark.asyncio
async def test_planning_node_persists_before_emit() -> None:
    """work item+02: planning_node 先落库再推 SSE。"""
    from unittest.mock import AsyncMock, patch as _patch

    from orchestration.graph import planning_node

    call_order: list[str] = []
    mock_aupdate = AsyncMock(return_value=1, side_effect=lambda **kw: call_order.append("db"))
    writer = MagicMock(side_effect=lambda *a: call_order.append("sse"))

    state: dict[str, Any] = {"user_message": "hi", "run_id": "run-order"}
    with _patch("orchestration.models.OrchestrationRun") as mock_cls:
        mock_cls.objects.filter.return_value.aupdate = mock_aupdate
        await planning_node(state, writer)

    assert call_order == ["db", "sse"], f"期望先 DB 再 SSE，实际顺序: {call_order}"


# ---------------------------------------------------------------------------
# work item 集成测试: planning_node 在 graph 端到端流中发射 PHASE_TRANSITION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planning_node_phase_transition_in_stream(graph_config: RunnableConfig) -> None:
    """work item 集成: graph astream 中 planning_node 发射的 PHASE_TRANSITION executing 事件可见。"""
    from agents.core.events import PHASE_TRANSITION

    mock_runner = _make_mock_runner(_default_events(), _default_result())

    with _patch_sdk(mock_runner):
        graph = build_graph().compile(checkpointer=MemorySaver())
        streamed: list[dict[str, Any]] = []
        async for chunk in graph.astream(
            {"user_message": "integration test", "run_id": "run-int-pt-1"},
            config=graph_config,
            stream_mode="custom",
        ):
            streamed.append(chunk)

    # planning_node 和 executing_node 都会发射 PHASE_TRANSITION executing，
    # 所以至少应有 2 个 phase_transition 事件
    pt_events = [e for e in streamed if e.get("type") == PHASE_TRANSITION]
    assert len(pt_events) >= 2, f"期望至少 2 个 phase_transition 事件，实际: {len(pt_events)}"
    # 第一个应该来自 planning_node（executing）
    assert pt_events[0]["data"]["phase"] == "executing"
    # 最后一个应该是 finalizing（从 _execute_first_run）
    assert pt_events[-1]["data"]["phase"] == "finalizing"
