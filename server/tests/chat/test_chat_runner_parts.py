"""parts contract：chat_runner.stream 接入 PartsCollector + parts
归档 + ERROR 路径 parts 携带契约（major #1）+ implementation DEBUG 保护区不退化。

测试矩阵（contract 测试要求 ≥ 7 条）：
1. test_stream_text_only_yields_single_text_part
2. test_stream_text_tool_text_yields_three_parts_with_correct_order_and_closure
3. test_stream_thinking_does_not_close_text_part
4. test_stream_parallel_tool_calls_share_batch_id_and_become_sibling_tool_use_parts
5. test_stream_interrupted_during_text_part_flushes_to_done（回归 work-item）
6. test_stream_context_window_exceeded_still_emits_collected_parts_in_message_complete
7. test_stream_max_turns_exhausted_degraded_path_includes_parts
8. test_error_path_message_complete_carries_partial_parts（major #1 强制单测）

测试 seam 与 ``tests/test_chat_runner.py`` 完全对齐（_disable_history_load
autouse + patch ``_build_model`` / ``_build_tool_specs``）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk

from agents.chat_runner import ChatAnthropicRunner, ChatRunnerConfig
from agents.core.events import ERROR, MESSAGE_COMPLETE
from agents.langchain_runner import ContextWindowExceededError
from agents.tools.base import ToolResult


def _make_config(max_turns: int = 30) -> ChatRunnerConfig:
    return ChatRunnerConfig(
        system_prompt="你是测试助手",
        model="claude-sonnet-4-5",
        space_id="proj-1",
        session_id="sess-1",
        conversation_id="conv-parts",
        api_key="sk-test",
        max_turns=max_turns,
    )


@pytest.fixture(autouse=True)
def _disable_history_load() -> AsyncGenerator[None, None]:
    with patch(
        "agents.chat_runner._load_history_messages",
        new=AsyncMock(return_value=[]),
    ):
        yield


def _make_bound_model(chunks: list[AIMessageChunk]) -> SimpleNamespace:
    async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        for chunk in chunks:
            yield chunk

    return SimpleNamespace(astream=_astream)


def _make_scripted_bound_model(scripts: list[list[AIMessageChunk]]) -> SimpleNamespace:
    iter_state = {"call_count": 0}

    async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        idx = iter_state["call_count"]
        iter_state["call_count"] += 1
        if idx >= len(scripts):
            yield AIMessageChunk(content="done")
            return
        for chunk in scripts[idx]:
            yield chunk

    bound = SimpleNamespace(
        astream=_astream,
        bind_tools=lambda _tools: SimpleNamespace(astream=_astream),
    )
    return bound


def _completion_event_parts(events: list[Any]) -> list[dict[str, Any]]:
    """从 events 中找到最终的 MESSAGE_COMPLETE 事件的 parts 字段。"""
    completes = [e for e in events if e.type == MESSAGE_COMPLETE]
    assert completes, "expected at least one MESSAGE_COMPLETE event"
    parts = completes[-1].data.get("parts")
    assert isinstance(parts, list), f"parts must be a list, got {type(parts)}"
    return parts


# =========================================================================
# 1. text-only：单 text part
# =========================================================================
@pytest.mark.asyncio
async def test_stream_text_only_yields_single_text_part() -> None:
    runner = ChatAnthropicRunner(_make_config())
    bound = _make_bound_model([
        AIMessageChunk(content="你"),
        AIMessageChunk(
            content="好",
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 2}},
        ),
    ])
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value={}),
    ):
        events = [event async for event in runner.stream("hi")]

    parts = _completion_event_parts(events)
    assert len(parts) == 1
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == "你好"
    assert parts[0]["state"] == "done"


# =========================================================================
# 2. text → tool → text：3 parts，封口顺序正确
# =========================================================================
@pytest.mark.asyncio
async def test_stream_text_tool_text_yields_three_parts_with_correct_order_and_closure() -> None:
    runner = ChatAnthropicRunner(_make_config())

    turn1 = [
        AIMessageChunk(content="先思考一下，"),
        AIMessageChunk(
            content="",
            tool_calls=[{
                "name": "search_repository_code",
                "args": {"query": "foo"},
                "id": "call_1",
                "type": "tool_call",
            }],
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 5}},
        ),
    ]
    turn2 = [
        AIMessageChunk(
            content="基于检索结果：found",
            response_metadata={"usage": {"input_tokens": 5, "output_tokens": 3}},
        ),
    ]
    bound = _make_scripted_bound_model([turn1, turn2])
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound

    async def _execute(_args: dict[str, object]) -> ToolResult:
        return ToolResult(success=True, output={"matches": ["a.py"]})

    tool_specs = {
        "search_repository_code": SimpleNamespace(
            tool=object(), execute=_execute, definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("找 foo")]

    parts = _completion_event_parts(events)
    types = [p["type"] for p in parts]
    assert types == ["text", "tool_use", "text"]
    assert parts[0]["text"] == "先思考一下，"
    assert parts[0]["state"] == "done"  # 被 tool 封口
    assert parts[1]["name"] == "search_repository_code"
    assert parts[1]["status"] == "done"
    assert parts[2]["text"] == "基于检索结果：found"
    assert parts[2]["state"] == "done"
    # index 单调
    assert [p["index"] for p in parts] == [0, 1, 2]


# =========================================================================
# 3. thinking 不封口 text（用 content_blocks 直接驱动 _extract_content_blocks）
# =========================================================================
class _FakeChunk:
    """绕过 AIMessageChunk content_blocks 归一化，直接喂 raw blocks。

    ``_extract_content_blocks`` 优先读 ``content_blocks``，list 即返回；用本类可
    精确控制 text / thinking 交替顺序。``+`` 兼容 chat_runner 的 ``full_message``
    累积（不影响测试断言，因为只关心 collector 派生的 parts）。
    """

    def __init__(self, blocks: list[dict[str, Any]], *, usage: dict[str, int] | None = None) -> None:
        self.content_blocks = blocks
        self.content = blocks
        self.tool_calls: list[dict[str, Any]] = []
        self.text = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
        self.usage_metadata = usage or {}
        self.response_metadata = {"usage": usage} if usage else {}

    def __add__(self, other: Any) -> "_FakeChunk":
        merged = _FakeChunk(self.content_blocks + getattr(other, "content_blocks", []))
        merged.tool_calls = self.tool_calls + getattr(other, "tool_calls", [])
        usage = self.usage_metadata or getattr(other, "usage_metadata", {})
        merged.usage_metadata = usage
        merged.response_metadata = {"usage": usage} if usage else {}
        return merged


@pytest.mark.asyncio
async def test_stream_thinking_does_not_close_text_part() -> None:
    runner = ChatAnthropicRunner(_make_config())

    async def _astream(_messages: list[object]) -> AsyncGenerator[Any, None]:
        yield _FakeChunk([{"type": "text", "text": "正文前半"}])
        yield _FakeChunk([{"type": "thinking", "thinking": "中间推理"}])
        yield _FakeChunk(
            [{"type": "text", "text": "正文后半"}],
            usage={"input_tokens": 5, "output_tokens": 3},
        )

    bound = SimpleNamespace(astream=_astream)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound

    # 关键：把 isinstance(chunk, AIMessageChunk) 放宽，不然 _FakeChunk 会被跳过
    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value={}),
        patch("agents.chat_runner.AIMessageChunk", _FakeChunk),
    ):
        events = [event async for event in runner.stream("hi")]

    parts = _completion_event_parts(events)
    types = [p["type"] for p in parts]
    assert types == ["text", "thinking", "text"]
    # final 状态都是 done（flush_all 在 message_complete 路径调用）
    assert all(p.get("state") == "done" for p in parts)


# =========================================================================
# 4. 并行 tool_calls 共享 batch_id
# =========================================================================
@pytest.mark.asyncio
async def test_stream_parallel_tool_calls_share_batch_id_and_become_sibling_tool_use_parts() -> None:
    runner = ChatAnthropicRunner(_make_config())

    turn1 = [
        AIMessageChunk(
            content="",
            tool_calls=[
                {
                    "name": "search_repository_code",
                    "args": {"query": "a"},
                    "id": "call_a",
                    "type": "tool_call",
                },
                {
                    "name": "search_repository_code",
                    "args": {"query": "b"},
                    "id": "call_b",
                    "type": "tool_call",
                },
            ],
            response_metadata={"usage": {"input_tokens": 5, "output_tokens": 5}},
        ),
    ]
    turn2 = [
        AIMessageChunk(
            content="完成",
            response_metadata={"usage": {"input_tokens": 3, "output_tokens": 2}},
        ),
    ]
    bound = _make_scripted_bound_model([turn1, turn2])
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound

    async def _execute(_args: dict[str, object]) -> ToolResult:
        return ToolResult(success=True, output={"ok": True})

    tool_specs = {
        "search_repository_code": SimpleNamespace(
            tool=object(), execute=_execute, definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("两个查询")]

    parts = _completion_event_parts(events)
    tool_parts = [p for p in parts if p["type"] == "tool_use"]
    assert len(tool_parts) == 2
    batch_ids = {p["batch_id"] for p in tool_parts}
    assert len(batch_ids) == 1
    assert next(iter(batch_ids)) is not None
    assert next(iter(batch_ids)).startswith("batch_")


# =========================================================================
# 5. 中断时已收集的 text part flush 到 done（回归 work-item）
# =========================================================================
@pytest.mark.asyncio
async def test_stream_interrupted_during_text_part_flushes_to_done() -> None:
    """R4：CancelledError 路径必须 flush_all + 把 parts 写入 message_complete。"""
    runner = ChatAnthropicRunner(_make_config())

    async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        yield AIMessageChunk(content="正在输出")
        raise asyncio.CancelledError("user clicked stop")

    bound = SimpleNamespace(astream=_astream)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value={}),
    ):
        events: list[Any] = []
        with pytest.raises(asyncio.CancelledError):
            async for event in runner.stream("hi"):
                events.append(event)

    parts = _completion_event_parts(events)
    assert len(parts) == 1
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == "正在输出"
    assert parts[0]["state"] == "done"
    # status 字段必带 interrupted（兼容老 final answer 路径）
    completion = [e for e in events if e.type == MESSAGE_COMPLETE][-1]
    assert completion.data["status"] == "interrupted"


# =========================================================================
# 6. ContextWindowExceededError 仍然要在 message_complete 里携带已收集 parts
# =========================================================================
class _RaiseContextExceeded:
    def __init__(self, message: str) -> None:
        self.message = message

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        raise ContextWindowExceededError(self.message)


@pytest.mark.asyncio
async def test_stream_context_window_exceeded_still_emits_collected_parts_in_message_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R4 + major #1：context exceeded 路径既发 ERROR 又发 MESSAGE_COMPLETE 带 parts。"""
    runner = ChatAnthropicRunner(_make_config())
    monkeypatch.setattr(
        "agents.chat_runner._check_chat_context_window",
        _RaiseContextExceeded(
            "context too long: 200 tokens > budget 100 "
            "(max_input=300, max_output=50, buffer=50)"
        ),
    )

    fake_model = MagicMock()
    fake_model.bind_tools.return_value = SimpleNamespace(astream=lambda _m: iter([]))

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value={}),
    ):
        events = [event async for event in runner.stream("hi")]

    # ERROR 事件不消失（结构化 SSE error 契约保持）
    assert any(e.type == ERROR for e in events)
    # MESSAGE_COMPLETE 带 parts 字段（哪怕 parts 是空也是 list）
    parts = _completion_event_parts(events)
    assert isinstance(parts, list)


# =========================================================================
# 7. max_turns 用尽 graceful degrade 路径含 parts
# =========================================================================
@pytest.mark.asyncio
async def test_stream_max_turns_exhausted_degraded_path_includes_parts() -> None:
    """max_turns=2：第 0 轮调 tool，第 1 轮 force-final 但仍调 tool（无 final
    text）→ turn 用尽进入 degraded 分支；message_complete 带已收集 tool parts。"""
    config = _make_config(max_turns=2)
    runner = ChatAnthropicRunner(config)

    def _tool_only_chunk(call_id: str) -> AIMessageChunk:
        return AIMessageChunk(
            content="",
            tool_calls=[{
                "name": "search_repository_code",
                "args": {"query": "x"},
                "id": call_id,
                "type": "tool_call",
            }],
            response_metadata={"usage": {"input_tokens": 5, "output_tokens": 5}},
        )

    # 第 0 轮调 tool（with tools），第 1 轮 force-final（用 model.astream）仍
    # 调 tool —— 第 1 轮 turn done 后 budget 用尽，跳进 max_turns degraded 分支。
    scripts = [[_tool_only_chunk("call_x")], [_tool_only_chunk("call_y")]]
    bound = _make_scripted_bound_model(scripts)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound
    fake_model.astream = bound.astream  # force-final 走原 model.astream

    async def _execute(_args: dict[str, object]) -> ToolResult:
        return ToolResult(success=True, output={"ok": True})

    tool_specs = {
        "search_repository_code": SimpleNamespace(
            tool=object(), execute=_execute, definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("hi")]

    parts = _completion_event_parts(events)
    # 至少一个 tool_use part 在
    assert any(p["type"] == "tool_use" for p in parts)
    # message_complete payload 带 degraded marker
    completes = [e for e in events if e.type == MESSAGE_COMPLETE]
    assert completes[-1].data.get("degraded") is True


# =========================================================================
# 8. ERROR 路径 message_complete 携带 partial parts（major #1 强制单测）
# =========================================================================
@pytest.mark.asyncio
async def test_error_path_message_complete_carries_partial_parts() -> None:
    """generic Exception 路径：必须既发 ERROR 又发 MESSAGE_COMPLETE 带已收集 parts。

    场景：stream 中段抛 RuntimeError（非 Cancelled / 非 ContextWindow）。
    """
    runner = ChatAnthropicRunner(_make_config())

    async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        yield AIMessageChunk(content="已生成一部分")
        raise RuntimeError("boom")

    bound = SimpleNamespace(astream=_astream)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value={}),
    ):
        events = [event async for event in runner.stream("hi")]

    assert any(e.type == ERROR for e in events)
    parts = _completion_event_parts(events)
    # 已收集的 text part 必须在 parts 中，state 强制 done
    text_parts = [p for p in parts if p["type"] == "text"]
    assert len(text_parts) == 1
    assert text_parts[0]["text"] == "已生成一部分"
    assert text_parts[0]["state"] == "done"
