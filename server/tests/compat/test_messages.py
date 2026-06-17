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
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import AsyncClient

from agents.core.events import MESSAGE_COMPLETE, TEXT_DELTA, AgentEvent


def _make_mock_runner(*events: AgentEvent) -> MagicMock:
    """返回 mock LangChainAgentRunner，stream() yield 指定事件。"""
    runner = MagicMock()

    async def _stream(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
        for evt in events:
            yield evt

    runner.stream = _stream
    return runner


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
