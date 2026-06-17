"""anthropic_adapter.py 单元 + 集成测试（Plan 57-01 Task 2）。

测试覆盖：
  编码 helper：双行帧 event:+data:
  8 事件骨架纯函数最小 payload 形状
  映射纯函数：_status_to_stop_reason / _rename_usage
  AnthropicCompatAdapter.translate_stream：text 路径顺序、ERROR 不发 message_stop、
    stop_reason 映射、绝不发 tool_use block
  aggregate_message：非流式聚合形状 + ERROR raise
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest

from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    THINKING,
    AgentEvent,
)
from compat.anthropic_adapter import (
    AnthropicCompatAdapter,
    _rename_usage,
    _status_to_stop_reason,
    aggregate_message,
    anthropic_error_event,
    anthropic_sse_encode,
    content_block_delta_text,
    content_block_delta_thinking,
    content_block_start,
    content_block_stop,
    message_delta_event,
    message_start_event,
    message_stop_event,
)


def _make_runner(*events: AgentEvent) -> MagicMock:
    """返回 mock runner，stream() yield 指定 AgentEvent 列表。"""
    runner = MagicMock()

    async def _stream(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
        for evt in events:
            yield evt

    runner.stream = _stream
    return runner


async def _collect_events(gen: AsyncGenerator[bytes, None]) -> list[dict[str, Any]]:
    """解析 Anthropic 双行帧，返回 (event_type, data) 的 data dict 列表。"""
    events: list[dict[str, Any]] = []
    async for raw in gen:
        text = raw.decode()
        assert text.startswith("event: "), f"缺 event: 行: {text!r}"
        lines = text.split("\n")
        event_type = lines[0].removeprefix("event: ")
        data_line = next(line for line in lines if line.startswith("data: "))
        data = json.loads(data_line.removeprefix("data: "))
        assert data["type"] == event_type, "data.type 必须与 event: 类型一致"
        events.append(data)
    return events


# ──────────────────────────────────────────────────────────────────────────────
# 编码 helper
# ──────────────────────────────────────────────────────────────────────────────


def test_anthropic_sse_encode_double_frame() -> None:
    """anthropic_sse_encode 产 event:+data: 双行帧。"""
    raw = anthropic_sse_encode("message_stop", {"type": "message_stop"})
    text = raw.decode()
    assert text.startswith("event: message_stop\n")
    assert "data: " in text
    assert text.endswith("\n\n")
    data_line = text.split("\n")[1]
    assert json.loads(data_line.removeprefix("data: "))["type"] == "message_stop"


# ──────────────────────────────────────────────────────────────────────────────
# 8 事件骨架形状
# ──────────────────────────────────────────────────────────────────────────────


def test_message_start_event_shape() -> None:
    evt = message_start_event("msg_abc", "friday-default", input_tokens=5)
    assert evt["type"] == "message_start"
    msg = evt["message"]
    assert msg["id"] == "msg_abc"
    assert msg["type"] == "message"
    assert msg["role"] == "assistant"
    assert msg["model"] == "friday-default"
    assert msg["content"] == []
    assert msg["stop_reason"] is None
    assert msg["stop_sequence"] is None
    assert msg["usage"] == {"input_tokens": 5, "output_tokens": 0}


def test_content_block_start_types() -> None:
    text_evt = content_block_start(0, "text")
    assert text_evt["type"] == "content_block_start"
    assert text_evt["index"] == 0
    assert text_evt["content_block"]["type"] == "text"
    thinking_evt = content_block_start(1, "thinking")
    assert thinking_evt["content_block"]["type"] == "thinking"


def test_content_block_delta_shapes() -> None:
    text_evt = content_block_delta_text(0, "hi")
    assert text_evt["delta"]["type"] == "text_delta"
    assert text_evt["delta"]["text"] == "hi"
    thinking_evt = content_block_delta_thinking(0, "think")
    assert thinking_evt["delta"]["type"] == "thinking_delta"
    assert thinking_evt["delta"]["thinking"] == "think"


def test_content_block_stop_index() -> None:
    evt = content_block_stop(3)
    assert evt["type"] == "content_block_stop"
    assert evt["index"] == 3


def test_message_delta_event_shape() -> None:
    evt = message_delta_event("end_turn", 7)
    assert evt["type"] == "message_delta"
    assert evt["delta"]["stop_reason"] == "end_turn"
    assert evt["delta"]["stop_sequence"] is None
    assert evt["usage"]["output_tokens"] == 7


def test_message_stop_and_error_event() -> None:
    assert message_stop_event()["type"] == "message_stop"
    err = anthropic_error_event("boom")
    assert err["type"] == "error"
    assert err["error"]["type"] == "api_error"
    assert err["error"]["message"] == "boom"


# ──────────────────────────────────────────────────────────────────────────────
# 映射纯函数
# ──────────────────────────────────────────────────────────────────────────────


def test_status_to_stop_reason() -> None:
    assert _status_to_stop_reason("completed") == "end_turn"
    assert _status_to_stop_reason("interrupted") == "end_turn"
    assert _status_to_stop_reason("max_iterations") == "end_turn"


def test_rename_usage() -> None:
    assert _rename_usage({"input": 5, "output": 2}) == (5, 2)
    assert _rename_usage(None) == (0, 0)
    assert _rename_usage({}) == (0, 0)


# ──────────────────────────────────────────────────────────────────────────────
# adapter text 路径集成
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_translate_stream_text_path_order() -> None:
    """text 路径事件顺序 + usage 改名 + 无 tool_use/thinking block。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "你好"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "世界"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed", "usage": {"input": 5, "output": 2}}),
    )
    events = await _collect_events(
        AnthropicCompatAdapter.translate_stream(runner, "test", model="friday-default")
    )
    types = [e["type"] for e in events]
    assert types == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    # content block 仅 text
    assert events[1]["content_block"]["type"] == "text"
    # message_delta stop_reason + output_tokens
    assert events[-2]["delta"]["stop_reason"] == "end_turn"
    assert events[-2]["usage"]["output_tokens"] == 2


@pytest.mark.asyncio
async def test_translate_stream_error_no_message_stop() -> None:
    """ERROR → 含 event: error 帧、其后无 message_stop、全流不含后续正文。"""
    runner = _make_runner(
        AgentEvent(type=ERROR, data={"message": "X"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "不应出现"}),
    )
    raw = b""
    async for chunk in AnthropicCompatAdapter.translate_stream(
        runner, "test", model="friday-default"
    ):
        raw += chunk
    text = raw.decode()
    assert "event: error" in text
    assert "message_stop" not in text
    assert "不应出现" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["interrupted", "max_iterations"])
async def test_translate_stream_status_maps_end_turn(status: str) -> None:
    """interrupted/max_iterations → message_delta.stop_reason==end_turn。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "x"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"status": status, "usage": {"input": 1, "output": 1}}),
    )
    events = await _collect_events(
        AnthropicCompatAdapter.translate_stream(runner, "test", model="friday-default")
    )
    delta = next(e for e in events if e["type"] == "message_delta")
    assert delta["delta"]["stop_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_translate_stream_never_tool_use_thinking_silent() -> None:
    """THINKING 静默不外透；全流无 tool_use block（TRACE-02/P-5/INV-5）。"""
    runner = _make_runner(
        AgentEvent(type=THINKING, data={"thinking": "内部思考"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "正文"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed", "usage": {"input": 1, "output": 1}}),
    )
    raw = b""
    async for chunk in AnthropicCompatAdapter.translate_stream(
        runner, "test", model="friday-default"
    ):
        raw += chunk
    text = raw.decode()
    assert "tool_use" not in text
    assert "内部思考" not in text
    events = await _collect_events(
        AnthropicCompatAdapter.translate_stream(
            _make_runner(
                AgentEvent(type=TEXT_DELTA, data={"text": "正文"}),
                AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed", "usage": {}}),
            ),
            "test",
            model="friday-default",
        )
    )
    for e in events:
        if e["type"] == "content_block_start":
            assert e["content_block"]["type"] in {"text", "thinking"}


# ──────────────────────────────────────────────────────────────────────────────
# aggregate_message 非流式核
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_message_shape() -> None:
    """非流式聚合返回 Anthropic Messages 形状 dict。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "你好"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "世界"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"status": "completed", "usage": {"input": 5, "output": 2}}),
    )
    msg = await aggregate_message(runner, "test", model="friday-default")
    assert msg["id"].startswith("msg_")
    assert msg["type"] == "message"
    assert msg["role"] == "assistant"
    assert msg["content"] == [{"type": "text", "text": "你好世界"}]
    assert msg["model"] == "friday-default"
    assert msg["stop_reason"] == "end_turn"
    assert msg["stop_sequence"] is None
    assert msg["usage"] == {"input_tokens": 5, "output_tokens": 2}


@pytest.mark.asyncio
async def test_aggregate_message_error_raises() -> None:
    """ERROR runner → raise RuntimeError。"""
    runner = _make_runner(AgentEvent(type=ERROR, data={"message": "boom"}))
    with pytest.raises(RuntimeError, match="boom"):
        await aggregate_message(runner, "test", model="friday-default")
