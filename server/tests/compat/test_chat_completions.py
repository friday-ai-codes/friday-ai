"""ChatCompletionsView + ModelsView 集成测试（任务 3 TDD）。

测试覆盖：
  - test_chat_completions_stream_format：stream=True 返回 text/event-stream + chunk 格式 + [DONE]
  - test_invalid_request_returns_400：缺 messages → 400 + OpenAI error envelope
  - test_models_endpoint：GET /v1/models 返回 OpenAI 格式模型列表
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from types import SimpleNamespace
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


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_chat_completions_stream_format() -> None:
    """stream=True 时返回 text/event-stream，至少 1 个 chunk + [DONE]（work item/02）。"""
    mock_runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "你好"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "世界"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 5, "output": 2}, "status": "completed"}),
    )

    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=mock_runner), \
         patch("compat.views.prepare_messages_with_meta", new_callable=AsyncMock) as mock_prepare:
        from langchain_core.messages import HumanMessage
        mock_prepare.return_value = ([HumanMessage(content="你好世界")], None)

        client = AsyncClient()
        response = await client.post(
            "/v1/chat/completions",
            data=json.dumps({
                "model": "friday-default",
                "messages": [{"role": "user", "content": "你好世界"}],
                "stream": True,
            }),
            content_type="application/json",
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.get("Content-Type", "")

    chunks_raw: list[bytes] = []
    async for chunk in response.streaming_content:
        chunks_raw.append(chunk)
    content = b"".join(chunks_raw).decode()
    assert "data: [DONE]" in content

    # 至少有一个带 choices 的 chunk
    chunk_found = False
    for line in content.split("\n"):
        if line.startswith("data: ") and "[DONE]" not in line:
            try:
                payload = json.loads(line[6:])
                if payload.get("choices"):
                    chunk_found = True
                    # 验证 OpenAI 2024 chunk 字段（contract）
                    assert "id" in payload
                    assert payload["object"] == "chat.completion.chunk"
                    assert "created" in payload
                    assert "model" in payload
                    break
            except json.JSONDecodeError:
                pass
    assert chunk_found, "应至少有一个带 choices 的 OpenAI chunk"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_non_streaming_response() -> None:
    """stream=False（默认）返回完整 OpenAI ChatCompletion 对象，choices 非空（work item 修复验证）。"""
    mock_runner = _make_mock_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "Hello, "}),
        AgentEvent(type=TEXT_DELTA, data={"text": "world!"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 5, "output": 3}, "status": "completed"}),
    )

    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=mock_runner), \
         patch("compat.views.prepare_messages_with_meta", new_callable=AsyncMock) as mock_prepare:
        from langchain_core.messages import HumanMessage
        mock_prepare.return_value = ([HumanMessage(content="Say hello")], None)

        client = AsyncClient()
        response = await client.post(
            "/v1/chat/completions",
            data=json.dumps({
                "model": "friday-default",
                "messages": [{"role": "user", "content": "Say hello"}],
                "stream": False,
            }),
            content_type="application/json",
        )

    assert response.status_code == 200
    data = json.loads(response.content)

    # 验证顶层 OpenAI ChatCompletion 字段
    assert data["object"] == "chat.completion"
    assert "id" in data and data["id"].startswith("chatcmpl-")
    assert "created" in data
    assert data["model"] == "friday-default"

    # 验证 choices 非空且内容正确（work item 核心验证）
    assert isinstance(data["choices"], list)
    assert len(data["choices"]) == 1
    choice = data["choices"][0]
    assert choice["index"] == 0
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == "Hello, world!"
    assert choice["finish_reason"] == "stop"

    # 验证 usage 字段存在
    assert "usage" in data
    assert "prompt_tokens" in data["usage"]
    assert "completion_tokens" in data["usage"]
    assert "total_tokens" in data["usage"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_openai_compat_accepts_image_url_content_parts_and_uses_text_query() -> None:
    """OpenAI-style text + image_url parts pass schema and keep RAG query text-only."""
    captured: dict[str, Any] = {}

    runner = MagicMock()

    async def _stream(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
        captured["prompt"] = prompt
        yield AgentEvent(type=TEXT_DELTA, data={"text": "看到了"})
        yield AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 5, "output": 2}, "status": "completed"})

    runner.stream = _stream

    data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    search_result = SimpleNamespace(final_context="")

    with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=runner), \
         patch("compat.request_handler.LayeredSearchService.search", new_callable=AsyncMock, return_value=search_result) as mock_search:
        client = AsyncClient()
        response = await client.post(
            "/v1/chat/completions",
            data=json.dumps({
                "model": "friday-default",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "描述这张截图"},
                            {"type": "image_url", "image_url": {"url": data_url, "detail": "low"}},
                        ],
                    }
                ],
                "stream": False,
            }),
            content_type="application/json",
        )

    assert response.status_code == 200
    mock_search.assert_awaited_once()
    assert mock_search.await_args.kwargs["query"] == "描述这张截图"
    prompt = captured["prompt"]
    user_message = prompt[-1]
    assert isinstance(user_message.content, list)
    assert user_message.content[0] == {"type": "text", "text": "描述这张截图"}
    assert user_message.content[1]["type"] == "image_url"
    assert user_message.content[1]["image_url"]["url"] == data_url


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_invalid_request_returns_400() -> None:
    """缺少 messages 字段 → 返回 400 + OpenAI error envelope（work item）。"""
    client = AsyncClient()
    response = await client.post(
        "/v1/chat/completions",
        data=json.dumps({"model": "friday-default"}),  # 缺 messages
        content_type="application/json",
    )

    assert response.status_code == 400
    data = json.loads(response.content)
    assert "error" in data
    assert "message" in data["error"]
    assert "type" in data["error"]
    assert "code" in data["error"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_models_endpoint() -> None:
    """GET /v1/models 返回 OpenAI 格式模型列表。"""
    client = AsyncClient()
    response = await client.get("/v1/models/")

    assert response.status_code == 200
    data = json.loads(response.content)
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    assert len(data["data"]) >= 1
    model = data["data"][0]
    assert "id" in model
    assert model["object"] == "model"
