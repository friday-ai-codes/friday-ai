"""adapter.py + request_handler.py 单元测试（任务 2 TDD RED → GREEN）。
测试覆盖：
 adapter 翻译（5 个）：reasoning_content 映射、text_delta、include_usage、错误事件关闭流
 request_handler（4 个）：检索注入、检索失败降级、repository_ids 路由、无 ids 走 RepoRouter
"""
from __future__ import annotations
import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agents.core.events import (
 ERROR,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 AgentEvent,
)
from compat.adapter import OpenAICompatAdapter
# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────
def _make_runner(*events: AgentEvent) -> MagicMock:
 """返回一个 mock runner，stream yield 指定的 AgentEvent 列表。"""
 runner = MagicMock
 async def _stream(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
 for evt in events:
 yield evt
 runner.stream = _stream
 return runner
async def _collect(gen: AsyncGenerator[bytes, None]) -> list[dict[str, Any]]:
 """收集 async generator 的所有 SSE chunk，解析为 dict 列表。"""
 chunks: list[dict[str, Any]] =
 async for raw in gen:
 line = raw.decode
 # 跳过 [DONE] 哨兵（由 view 层 yield，不是 adapter 本身）
 if "[DONE]" in line:
 continue
 if line.startswith("data: "):
 payload = line[6:].strip
 if payload:
 chunks.append(json.loads(payload))
 return chunks
# ──────────────────────────────────────────────────────────────────────────────
# adapter 测试
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_reasoning_content_mapping -> None:
 """THINKING 事件 → chunk 包含 delta.reasoning_content。"""
 runner = _make_runner(
 AgentEvent(type=THINKING, data={"thinking": "我在思考..."}),
 AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 10, "output": 5}, "status": "completed"}),
 )
 chunks = await _collect(OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"))
 # 首 chunk 是 role=assistant，第二个是 reasoning_content
 reasoning_chunk = next(
 c for c in chunks
 if c.get("choices") and c["choices"][0].get("delta", {}).get("reasoning_content")
 )
 assert reasoning_chunk["choices"][0]["delta"]["reasoning_content"] == "我在思考..."
@pytest.mark.asyncio
async def test_text_delta_mapping -> None:
 """TEXT_DELTA 事件 → chunk 包含 delta.content。"""
 runner = _make_runner(
 AgentEvent(type=TEXT_DELTA, data={"text": "Hello"}),
 AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
 )
 chunks = await _collect(OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"))
 content_chunk = next(
 c for c in chunks
 if c.get("choices") and c["choices"][0].get("delta", {}).get("content")
 )
 assert content_chunk["choices"][0]["delta"]["content"] == "Hello"
@pytest.mark.asyncio
async def test_include_usage_true -> None:
 """include_usage=True 时 MESSAGE_COMPLETE 后追加 choices= + usage 非空 chunk。"""
 runner = _make_runner(
 AgentEvent(type=TEXT_DELTA, data={"text": "hi"}),
 AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 10, "output": 5}, "status": "completed"}),
 )
 chunks = await _collect(
 OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default", include_usage=True)
 )
 usage_chunks = [c for c in chunks if c.get("choices") == ]
 assert len(usage_chunks) == 1, "应恰好一个 choices= 的 usage chunk"
 usage = usage_chunks[0].get("usage")
 assert usage is not None
 assert usage["prompt_tokens"] == 10
 assert usage["completion_tokens"] == 5
 assert usage["total_tokens"] == 15
@pytest.mark.asyncio
async def test_include_usage_false -> None:
 """include_usage=False（默认）时所有 chunk 不含 usage 字段。"""
 runner = _make_runner(
 AgentEvent(type=TEXT_DELTA, data={"text": "hi"}),
 AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 10, "output": 5}, "status": "completed"}),
 )
 chunks = await _collect(
 OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default", include_usage=False)
 )
 for chunk in chunks:
 assert "usage" not in chunk, f"include_usage=False 时不应有 usage 字段：{chunk}"
@pytest.mark.asyncio
async def test_error_event_closes_stream -> None:
 """ERROR 事件 → yield error envelope 然后 return（不再 yield 正常 chunk）。"""
 runner = _make_runner(
 AgentEvent(type=ERROR, data={"message": "模型调用失败"}),
 AgentEvent(type=TEXT_DELTA, data={"text": "不应出现"}),
 )
 raw_bytes: list[bytes] =
 async for b in OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"):
 raw_bytes.append(b)
 # 应有错误 envelope
 error_found = False
 for b in raw_bytes:
 line = b.decode
 if line.startswith("data: "):
 try:
 payload = json.loads(line[6:].strip)
 if "error" in payload:
 assert payload["error"]["message"] == "模型调用失败"
 error_found = True
 except json.JSONDecodeError:
 pass
 assert error_found, "ERROR 事件应产生 error envelope"
 # 错误后不应出现"不应出现"的内容
 all_text = b"".join(raw_bytes).decode
 assert "不应出现" not in all_text
# ──────────────────────────────────────────────────────────────────────────────
# request_handler 测试
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_prepare_messages_with_search(django_db_setup: Any) -> None:
 """LayeredSearchService.search 返回 final_context → system message 被前置插入。"""
 from compat.request_handler import prepare_messages
 from langchain_core.messages import SystemMessage
 mock_result = MagicMock
 mock_result.final_context = "代码上下文内容"
 messages = [{"role": "user", "content": "请帮我解释这段代码"}]
 with patch("compat.request_handler.LayeredSearchService") as mock_service:
 mock_service.search = AsyncMock(return_value=mock_result)
 lc_messages = await prepare_messages(messages, repository_ids=None, project_id=None)
 assert isinstance(lc_messages[0], SystemMessage)
 assert "代码上下文内容" in lc_messages[0].content
@pytest.mark.asyncio
async def test_prepare_messages_search_fails_graceful -> None:
 """LayeredSearchService 抛异常 → 降级返回原始 lc_messages（ fallback）。"""
 from compat.request_handler import prepare_messages
 from langchain_core.messages import HumanMessage
 messages = [{"role": "user", "content": "测试问题"}]
 with patch("compat.request_handler.LayeredSearchService") as mock_service:
 mock_service.search = AsyncMock(side_effect=Exception("Qdrant 不可用"))
 lc_messages = await prepare_messages(messages, repository_ids=None, project_id=None)
 assert len(lc_messages) == 1
 assert isinstance(lc_messages[0], HumanMessage)
 assert lc_messages[0].content == "测试问题"
@pytest.mark.asyncio
async def test_repository_ids_routing -> None:
 """显式 repository_ids → LayeredSearchService.search 收到该列表（ 第一层）。"""
 from compat.request_handler import prepare_messages
 mock_result = MagicMock
 mock_result.final_context = ""
 messages = [{"role": "user", "content": "查询"}]
 repo_ids = ["550e8400-e29b-41d4-a716-446655440000"]
 with patch("compat.request_handler.LayeredSearchService") as mock_service:
 mock_service.search = AsyncMock(return_value=mock_result)
 await prepare_messages(messages, repository_ids=repo_ids, project_id=None)
 mock_service.search.assert_called_once
 call_kwargs = mock_service.search.call_args.kwargs
 assert call_kwargs["repository_ids"] == repo_ids
@pytest.mark.asyncio
async def test_no_repository_ids_fallback -> None:
 """不传 repository_ids → LayeredSearchService.search 收到 None（走 RepoRouter， 第三层）。"""
 from compat.request_handler import prepare_messages
 mock_result = MagicMock
 mock_result.final_context = ""
 messages = [{"role": "user", "content": "查询"}]
 with patch("compat.request_handler.LayeredSearchService") as mock_service:
 mock_service.search = AsyncMock(return_value=mock_result)
 await prepare_messages(messages, repository_ids=None, project_id=None)
 mock_service.search.assert_called_once
 call_kwargs = mock_service.search.call_args.kwargs
 assert call_kwargs["repository_ids"] is None
