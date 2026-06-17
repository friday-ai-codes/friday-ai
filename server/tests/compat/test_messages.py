"""MessagesView 非流式 view 级集成测 + 零回归（57-01 Task 3）。

测试覆盖：
  POST /v1/messages 非流式 Anthropic Messages 形状（ANTHROPIC-01）。
  content 零污染（P-8）+ usage 改名（仅 input_tokens/output_tokens）。
  max_tokens 缺失 → 400 Anthropic envelope。
  _build_runner None → 503 Anthropic envelope。
  双注册末尾斜杠 /v1/messages/。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import AsyncClient

from agents.core.events import MESSAGE_COMPLETE, TEXT_DELTA, THINKING, AgentEvent


def _make_mock_runner(*events: AgentEvent) -> MagicMock:
    """返回 mock LangChainAgentRunner，stream() yield 指定事件。"""
    runner = MagicMock()

    async def _stream(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
        for evt in events:
            yield evt

    runner.stream = _stream
    return runner


def _parse_anthropic_frames(sse_text: str) -> list[dict]:
    """解析 Anthropic SSE 双行帧（event: + data:），返回有序 data dict 列表。"""
    frames: list[dict] = []
    for block in sse_text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        data_line = next(
            (ln for ln in block.split("\n") if ln.startswith("data: ")), None
        )
        if data_line is None:
            continue
        frames.append(json.loads(data_line.removeprefix("data: ")))
    return frames


async def _collect_stream(response: Any) -> str:
    """收集 StreamingHttpResponse 全量字节流为字符串。"""
    parts: list[bytes] = []
    async for chunk in response.streaming_content:
        parts.append(chunk)
    return b"".join(parts).decode()


def _payload(**overrides) -> dict:
    payload = {
        "model": "claude-3-5-sonnet",
        "messages": [{"role": "user", "content": "Say hello"}],
        "max_tokens": 1024,
        "stream": False,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_non_stream_shape() -> None:
    """非流式响应 Anthropic Messages 形状（ANTHROPIC-01 / 6.3）。"""
    runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "Hello, "}),
        AgentEvent(type=TEXT_DELTA, data={"text": "world!"}),
        AgentEvent(
            type=MESSAGE_COMPLETE,
            data={"status": "completed", "usage": {"input": 5, "output": 3}},
        ),
    )
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch("compat.views.prepare_messages_with_meta", new_callable=AsyncMock) as mock_prep:
        from langchain_core.messages import HumanMessage
        mock_prep.return_value = ([HumanMessage(content="Say hello")], None)

        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["id"].startswith("msg_")
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"] == [{"type": "text", "text": "Hello, world!"}]
    assert data["model"] == "friday-default"
    assert data["stop_reason"] == "end_turn"
    assert data["stop_sequence"] is None
    assert data["usage"] == {"input_tokens": 5, "output_tokens": 3}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_content_zero_pollution() -> None:
    """content 零污染（P-8）：仅 TEXT_DELTA 正文，usage 仅 input_tokens/output_tokens。"""
    runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "Hello, world!"}),
        AgentEvent(
            type=MESSAGE_COMPLETE,
            data={"status": "completed", "usage": {"input": 5, "output": 3}},
        ),
    )
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch("compat.views.prepare_messages_with_meta", new_callable=AsyncMock) as mock_prep:
        from langchain_core.messages import HumanMessage
        mock_prep.return_value = ([HumanMessage(content="Say hello")], None)

        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    data = json.loads(response.content)
    assert data["content"][0]["text"] == "Hello, world!"
    assert "input" not in data["usage"]
    assert "output" not in data["usage"]
    assert set(data["usage"].keys()) == {"input_tokens", "output_tokens"}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_max_tokens_missing_returns_400() -> None:
    """max_tokens 缺失 → 400 + Anthropic error envelope。"""
    payload = _payload()
    del payload["max_tokens"]
    client = AsyncClient()
    response = await client.post(
        "/v1/messages",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 400
    data = json.loads(response.content)
    assert data["type"] == "error"
    assert "type" in data["error"]
    assert "message" in data["error"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_runner_none_returns_503() -> None:
    """_build_runner None → 503 + Anthropic error envelope。"""
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=None), \
         patch("compat.views.prepare_messages_with_meta", new_callable=AsyncMock) as mock_prep:
        from langchain_core.messages import HumanMessage
        mock_prep.return_value = ([HumanMessage(content="Say hello")], None)

        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    assert response.status_code == 503
    data = json.loads(response.content)
    assert data["type"] == "error"
    assert "message" in data["error"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_trailing_slash_dual_registration() -> None:
    """POST /v1/messages/（带斜杠）同样 200（双注册）。"""
    runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "hi"}),
        AgentEvent(
            type=MESSAGE_COMPLETE,
            data={"status": "completed", "usage": {"input": 1, "output": 1}},
        ),
    )
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch("compat.views.prepare_messages_with_meta", new_callable=AsyncMock) as mock_prep:
        from langchain_core.messages import HumanMessage
        mock_prep.return_value = ([HumanMessage(content="hi")], None)

        client = AsyncClient()
        response = await client.post(
            "/v1/messages/",
            data=json.dumps(_payload()),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["type"] == "message"


# ──────────────────────────────────────────────────────────────────────────────
# Plan 02：流式 SSE view 级集成（ANTHROPIC-02）
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_stream_thinking_before_text() -> None:
    """流式命中 RAG → thinking block（thinking_delta 命中计数）严格先于首个 text_delta（6.3）。"""
    runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "正文"}),
        AgentEvent(
            type=MESSAGE_COMPLETE,
            data={"status": "completed", "usage": {"input": 1, "output": 1}},
        ),
    )
    search_result = SimpleNamespace(
        final_context="相关上下文",
        layers=[SimpleNamespace(result_count=2)],
        repository_ids=[],
        query="解释代码",
    )
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch(
             "compat.request_handler.LayeredSearchService.search",
             new_callable=AsyncMock, return_value=search_result,
         ):
        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload(stream=True, messages=[{"role": "user", "content": "解释代码"}])),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["Content-Type"]
        sse_text = await _collect_stream(response)

    frames = _parse_anthropic_frames(sse_text)
    types = [f["type"] for f in frames]
    # message_start → thinking block → text block → message_stop 收尾
    assert types[0] == "message_start"
    assert types[-1] == "message_stop"
    # thinking_delta 命中计数严格先于首个 text_delta
    first_thinking = next(
        (i for i, f in enumerate(frames)
         if f["type"] == "content_block_delta" and f["delta"]["type"] == "thinking_delta"),
        None,
    )
    first_text = next(
        (i for i, f in enumerate(frames)
         if f["type"] == "content_block_delta" and f["delta"]["type"] == "text_delta"),
        None,
    )
    assert first_thinking is not None, "应有 thinking block trace"
    assert first_text is not None, "应有正文 text_delta"
    assert first_thinking < first_text
    thinking_texts = [
        f["delta"]["thinking"] for f in frames
        if f["type"] == "content_block_delta" and f["delta"]["type"] == "thinking_delta"
    ]
    assert thinking_texts == ["正在检索 RAG…", "检索完成，命中 2 处"]
    # 全流任一 content_block.type ∈ {text,thinking}，无 tool_use
    assert "tool_use" not in sse_text
    for f in frames:
        if f["type"] == "content_block_start":
            assert f["content_block"]["type"] in {"text", "thinking"}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_stream_miss_degrades_no_thinking() -> None:
    """流式未命中（final_context 空）→ 无 thinking block、仅 text block + message_stop（P-7）。"""
    runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "正文"}),
        AgentEvent(
            type=MESSAGE_COMPLETE,
            data={"status": "completed", "usage": {"input": 1, "output": 1}},
        ),
    )
    search_result = SimpleNamespace(final_context="", layers=[], repository_ids=[], query="hi")
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch(
             "compat.request_handler.LayeredSearchService.search",
             new_callable=AsyncMock, return_value=search_result,
         ):
        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload(stream=True)),
            content_type="application/json",
        )

        assert response.status_code == 200
        sse_text = await _collect_stream(response)

    frames = _parse_anthropic_frames(sse_text)
    # 无 thinking block
    assert all(
        f.get("content_block", {}).get("type") != "thinking"
        for f in frames
        if f["type"] == "content_block_start"
    )
    assert any(
        f["type"] == "content_block_start" and f["content_block"]["type"] == "text"
        for f in frames
    )
    assert frames[-1]["type"] == "message_stop"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_stream_security_sentinel() -> None:
    """安全 sentinel（INV-5）：final_context/query/CoT 原文绝不出现在 SSE 全流（6.4）。"""
    runner = _make_mock_runner(
        AgentEvent(type=THINKING, data={"thinking": "SENTINEL_COT"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "正文"}),
        AgentEvent(
            type=MESSAGE_COMPLETE,
            data={"status": "completed", "usage": {"input": 1, "output": 1}},
        ),
    )
    search_result = SimpleNamespace(
        final_context="SENTINEL_CTX_secret 敏感片段",
        layers=[SimpleNamespace(result_count=3)],
        repository_ids=[],
        query="SENTINEL_Q",
    )
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch(
             "compat.request_handler.LayeredSearchService.search",
             new_callable=AsyncMock, return_value=search_result,
         ):
        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload(stream=True, messages=[{"role": "user", "content": "SENTINEL_Q"}])),
            content_type="application/json",
        )

        assert response.status_code == 200
        sse_text = await _collect_stream(response)

    assert "SENTINEL_CTX_secret" not in sse_text
    assert "SENTINEL_Q" not in sse_text
    assert "SENTINEL_COT" not in sse_text
    # 仍透出命中计数语义
    assert "命中 3 处" in sse_text


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_non_stream_content_zero_regression_on_hit() -> None:
    """命中检索下 stream=False → content 仅 TEXT_DELTA 正文、usage 仅 input/output_tokens（P-8）。"""
    runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "Hello, "}),
        AgentEvent(type=TEXT_DELTA, data={"text": "world!"}),
        AgentEvent(
            type=MESSAGE_COMPLETE,
            data={"status": "completed", "usage": {"input": 5, "output": 3}},
        ),
    )
    search_result = SimpleNamespace(
        final_context="相关上下文",
        layers=[SimpleNamespace(result_count=2)],
        repository_ids=[],
        query="Say hello",
    )
    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch(
             "compat.request_handler.LayeredSearchService.search",
             new_callable=AsyncMock, return_value=search_result,
         ):
        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload(stream=False)),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["content"] == [{"type": "text", "text": "Hello, world!"}]
    # 非流式绝不引入 thinking/检索 progress（content 零污染）
    assert all(block["type"] == "text" for block in data["content"])
    assert set(data["usage"].keys()) == {"input_tokens", "output_tokens"}


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_messages_stream_error_event_no_traceback() -> None:
    """流式 runner.stream 抛异常 → SSE 含 event: error（api_error）、不含 traceback、不发 message_stop。"""
    runner = MagicMock()

    async def _boom(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
        raise RuntimeError("internal boom traceback secret")
        yield  # pragma: no cover

    runner.stream = _boom

    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch("compat.views.prepare_messages_with_meta", new_callable=AsyncMock) as mock_prep:
        from langchain_core.messages import HumanMessage
        mock_prep.return_value = ([HumanMessage(content="hi")], None)

        client = AsyncClient()
        response = await client.post(
            "/v1/messages",
            data=json.dumps(_payload(stream=True)),
            content_type="application/json",
        )

        assert response.status_code == 200
        sse_text = await _collect_stream(response)

    assert "event: error" in sse_text
    frames = _parse_anthropic_frames(sse_text)
    err = next(f for f in frames if f["type"] == "error")
    assert err["error"]["type"] == "api_error"
    assert "boom traceback secret" not in sse_text
    assert "message_stop" not in sse_text
