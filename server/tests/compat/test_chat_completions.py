"""ChatCompletionsView + ModelsView 集成测试（任务 3 TDD）。
测试覆盖：
 - test_chat_completions_stream_format：stream=True 返回 text/event-stream + chunk 格式 + [DONE]
 - test_invalid_request_returns_400：缺 messages → 400 + OpenAI error envelope
 - test_models_endpoint：GET /v1/models 返回 OpenAI 格式模型列表
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
 """返回 mock LangChainAgentRunner，stream yield 指定事件。"""
 runner = MagicMock
 async def _stream(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
 for evt in events:
 yield evt
 runner.stream = _stream
 return runner
@pytest.mark.asyncio
@pytest.mark.django_db
async def test_chat_completions_stream_format -> None:
 """stream=True 时返回 text/event-stream，至少 1 个 chunk + [DONE]。"""
 mock_runner = _make_mock_runner(
 AgentEvent(type=TEXT_DELTA, data={"text": "你好"}),
 AgentEvent(type=TEXT_DELTA, data={"text": "世界"}),
 AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 5, "output": 2}, "status": "completed"}),
 )
 with patch("compat.views._build_runner", new_callable=AsyncMock, return_value=mock_runner), \
 patch("compat.views.prepare_messages", new_callable=AsyncMock) as mock_prepare:
 from langchain_core.messages import HumanMessage
 mock_prepare.return_value = [HumanMessage(content="你好世界")]
 client = AsyncClient
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
 chunks_raw: list[bytes] =
 async for chunk in response.streaming_content:
 chunks_raw.append(chunk)
 content = b"".join(chunks_raw).decode
 assert "data: [DONE]" in content
 # 至少有一个带 choices 的 chunk
 chunk_found = False
 for line in content.split("\n"):
 if line.startswith("data: ") and "[DONE]" not in line:
 try:
 payload = json.loads(line[6:])
 if payload.get("choices"):
 chunk_found = True
 # 验证 OpenAI 2024 chunk 字段
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
async def test_invalid_request_returns_400 -> None:
 """缺少 messages 字段 → 返回 400 + OpenAI error envelope。"""
 client = AsyncClient
 response = await client.post(
 "/v1/chat/completions",
 data=json.dumps({"model": "friday-default"}), # 缺 messages
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
async def test_models_endpoint -> None:
 """GET /v1/models 返回 OpenAI 格式模型列表。"""
 client = AsyncClient
 response = await client.get("/v1/models/")
 assert response.status_code == 200
 data = json.loads(response.content)
 assert data["object"] == "list"
 assert isinstance(data["data"], list)
 assert len(data["data"]) >= 1
 model = data["data"][0]
 assert "id" in model
 assert model["object"] == "model"
