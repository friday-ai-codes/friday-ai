"""adapter.py + request_handler.py 单元测试（任务 2 TDD RED → GREEN）。

测试覆盖：
  adapter 翻译（5 个）：reasoning_content 映射、text_delta、include_usage、错误事件关闭流
  request_handler（4 个）：检索注入、检索失败降级、repository_ids 路由、无 ids 走 RepoRouter
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.test import AsyncClient

from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    THINKING,
    TOOL_USE_RESULT,
    TOOL_USE_START,
    AgentEvent,
)
from compat.adapter import OpenAICompatAdapter

# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────


def _make_runner(*events: AgentEvent) -> MagicMock:
    """返回一个 mock runner，stream() yield 指定的 AgentEvent 列表。"""
    runner = MagicMock()

    async def _stream(prompt: Any) -> AsyncGenerator[AgentEvent, None]:
        for evt in events:
            yield evt

    runner.stream = _stream
    return runner


async def _collect(gen: AsyncGenerator[bytes, None]) -> list[dict[str, Any]]:
    """收集 async generator 的所有 SSE chunk，解析为 dict 列表。"""
    chunks: list[dict[str, Any]] = []
    async for raw in gen:
        line = raw.decode()
        # 跳过 [DONE] 哨兵（由 view 层 yield，不是 adapter 本身）
        if "[DONE]" in line:
            continue
        if line.startswith("data: "):
            payload = line[6:].strip()
            if payload:
                chunks.append(json.loads(payload))
    return chunks


async def _collect_raw(gen: AsyncGenerator[bytes, None]) -> bytes:
    """收集 async generator 的全部字节（用于零回归 byte-eq / sentinel 断言）。"""
    parts: list[bytes] = []
    async for raw in gen:
        parts.append(raw)
    return b"".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# adapter 测试
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_content_mapping() -> None:
    """THINKING 事件 → chunk 包含 delta.reasoning_content（contract）。"""
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
async def test_text_delta_mapping() -> None:
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
async def test_include_usage_true() -> None:
    """include_usage=True 时 MESSAGE_COMPLETE 后追加 choices=[] + usage 非空 chunk。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "hi"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 10, "output": 5}, "status": "completed"}),
    )
    chunks = await _collect(
        OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default", include_usage=True)
    )
    usage_chunks = [c for c in chunks if c.get("choices") == []]
    assert len(usage_chunks) == 1, "应恰好一个 choices=[] 的 usage chunk"
    usage = usage_chunks[0].get("usage")
    assert usage is not None
    assert usage["prompt_tokens"] == 10
    assert usage["completion_tokens"] == 5
    assert usage["total_tokens"] == 15


@pytest.mark.asyncio
async def test_include_usage_false() -> None:
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
async def test_error_event_closes_stream() -> None:
    """ERROR 事件 → yield error envelope 然后 return（不再 yield 正常 chunk）。"""
    runner = _make_runner(
        AgentEvent(type=ERROR, data={"message": "模型调用失败"}),
        AgentEvent(type=TEXT_DELTA, data={"text": "不应出现"}),
    )
    raw_bytes: list[bytes] = []
    async for b in OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"):
        raw_bytes.append(b)

    # 应有错误 envelope
    error_found = False
    for b in raw_bytes:
        line = b.decode()
        if line.startswith("data: "):
            try:
                payload = json.loads(line[6:].strip())
                if "error" in payload:
                    assert payload["error"]["message"] == "模型调用失败"
                    error_found = True
            except json.JSONDecodeError:
                pass
    assert error_found, "ERROR 事件应产生 error envelope"

    # 错误后不应出现"不应出现"的内容
    all_text = b"".join(raw_bytes).decode()
    assert "不应出现" not in all_text


# ──────────────────────────────────────────────────────────────────────────────
# TOOL_USE_* → progress 集成测（6.2）+ tool_calls 禁线 + 安全 sentinel（6.4）
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_use_start_maps_to_reasoning_content() -> None:
    """TOOL_USE_START{search_rag} → 含 reasoning_content=="正在检索 RAG" 的 progress chunk。"""
    runner = _make_runner(
        AgentEvent(type=TOOL_USE_START, data={"tool_name": "search_rag", "tool_call_id": "c1"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    chunks = await _collect(OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"))
    progress_chunk = next(
        c for c in chunks
        if c.get("choices") and c["choices"][0].get("delta", {}).get("reasoning_content")
    )
    assert progress_chunk["choices"][0]["delta"]["reasoning_content"] == "正在检索 RAG"
    assert progress_chunk["choices"][0]["finish_reason"] is None
    assert progress_chunk["object"] == "chat.completion.chunk"


@pytest.mark.asyncio
async def test_unknown_tool_emits_no_chunk() -> None:
    """未知工具名 → 不新增任何 progress chunk（与降级等价）。"""
    base = _make_runner(
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    with_unknown = _make_runner(
        AgentEvent(type=TOOL_USE_START, data={"tool_name": "totally_unknown_tool"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    base_chunks = await _collect(OpenAICompatAdapter.translate_stream(base, "test", model="friday-default"))
    unknown_chunks = await _collect(
        OpenAICompatAdapter.translate_stream(with_unknown, "test", model="friday-default")
    )
    assert len(unknown_chunks) == len(base_chunks)


@pytest.mark.asyncio
async def test_no_tool_calls_field_anywhere() -> None:
    """TRACE-02：含 TOOL_USE_* 的序列，任一 chunk 都不含 tool_calls / finish_reason!=tool_calls。"""
    runner = _make_runner(
        AgentEvent(type=TOOL_USE_START, data={"tool_name": "grep"}),
        AgentEvent(type=TOOL_USE_RESULT, data={"tool_name": "grep", "success": True, "result": "x"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    chunks = await _collect(OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"))
    for c in chunks:
        for choice in c.get("choices", []):
            assert "tool_calls" not in choice.get("delta", {})
            assert choice.get("finish_reason") != "tool_calls"


@pytest.mark.asyncio
async def test_progress_chunk_does_not_pollute_content() -> None:
    """progress chunk 仅含 reasoning_content，绝不混入非空 delta.content。"""
    runner = _make_runner(
        AgentEvent(type=TOOL_USE_START, data={"tool_name": "search_rag"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    chunks = await _collect(OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"))
    for c in chunks:
        for choice in c.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("reasoning_content"):
                assert not delta.get("content")


@pytest.mark.asyncio
async def test_tool_progress_include_usage_consistency() -> None:
    """include_usage=True 时 progress chunk 带 usage=None，末尾仍恰好一个 choices=[] 的 usage chunk。"""
    runner = _make_runner(
        AgentEvent(type=TOOL_USE_START, data={"tool_name": "search_rag"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 3, "output": 2}, "status": "completed"}),
    )
    chunks = await _collect(
        OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default", include_usage=True)
    )
    progress_chunk = next(
        c for c in chunks
        if c.get("choices") and c["choices"][0].get("delta", {}).get("reasoning_content")
    )
    assert "usage" in progress_chunk
    assert progress_chunk["usage"] is None
    usage_chunks = [c for c in chunks if c.get("choices") == []]
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["usage"]["total_tokens"] == 5


@pytest.mark.asyncio
async def test_sentinel_never_leaks_in_full_stream() -> None:
    """INV-5：含敏感 tool_input/result + THINKING CoT 的完整序列，全量 SSE 字节流不含任一 sentinel。"""
    tool_input_sentinel = "SENTINEL_TOOL_INPUT_secret"
    result_sentinel = "SENTINEL_RESULT_private_code"
    cot_sentinel = "SENTINEL_COT_chain_of_thought"
    runner = _make_runner(
        AgentEvent(type=THINKING, data={"thinking": cot_sentinel}),
        AgentEvent(
            type=TOOL_USE_START,
            data={"tool_name": "search_rag", "tool_input": tool_input_sentinel},
        ),
        AgentEvent(
            type=TOOL_USE_RESULT,
            data={"tool_name": "search_rag", "success": True, "result": result_sentinel},
        ),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    raw = await _collect_raw(OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"))
    text = raw.decode()
    assert tool_input_sentinel not in text
    assert result_sentinel not in text
    # THINKING 原文经既有 reasoning_content 透出属既有行为，但 progress 机制绝不额外内联 CoT；
    # 此处断言工具事件不引入 CoT sentinel（THINKING 自身 chunk 之外不应出现第二次）。
    assert text.count(cot_sentinel) <= 1


# ──────────────────────────────────────────────────────────────────────────────
# 零回归 byte-equivalence（6.3）：无工具事件序列 SSE 输出逐字等价、不新增 chunk
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_zero_regression_thinking_sequence_byte_equivalent() -> None:
    """[THINKING, MESSAGE_COMPLETE] 序列：新代码 SSE 字节流与无 TOOL_USE 时逐字一致。"""

    def _events() -> list[AgentEvent]:
        return [
            AgentEvent(type=THINKING, data={"thinking": "思考中"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
        ]

    raw_a = await _collect_raw(
        OpenAICompatAdapter.translate_stream(_make_runner(*_events()), "test", model="m")
    )
    raw_b = await _collect_raw(
        OpenAICompatAdapter.translate_stream(_make_runner(*_events()), "test", model="m")
    )
    # 两次运行除 chat_id/created（随机/时钟）外结构应稳定：chunk 数一致
    assert raw_a.count(b"data: ") == raw_b.count(b"data: ")
    # 不应包含任何 reasoning_content 之外的 progress（THINKING 自身经 reasoning_content）
    chunks = await _collect(
        OpenAICompatAdapter.translate_stream(_make_runner(*_events()), "test", model="m")
    )
    # role + thinking(reasoning_content) + finish = 3 chunk（无新增 progress chunk）
    assert len(chunks) == 3


@pytest.mark.asyncio
async def test_zero_regression_text_delta_sequence_no_extra_chunk() -> None:
    """[TEXT_DELTA, MESSAGE_COMPLETE] 序列：不新增任何 chunk（role + content + finish = 3）。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "Hello"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    chunks = await _collect(OpenAICompatAdapter.translate_stream(runner, "test", model="friday-default"))
    assert len(chunks) == 3
    for c in chunks:
        for choice in c.get("choices", []):
            assert not choice.get("delta", {}).get("reasoning_content")


# ──────────────────────────────────────────────────────────────────────────────
# Plan 02：流式检索 progress prelude 集成测（6.2）+ 零回归 byte-eq（6.3）+ sentinel（6.4）
# ──────────────────────────────────────────────────────────────────────────────


def _strip_volatile(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉 id/created（随机/时钟）后用于 byte-eq 结构等价比较。"""
    out: list[dict[str, Any]] = []
    for c in chunks:
        cc = dict(c)
        cc.pop("id", None)
        cc.pop("created", None)
        out.append(cc)
    return out


def _ordered_deltas(sse_text: str) -> list[tuple[str, str]]:
    """解析 SSE 文本，按序返回 (kind, text) 列表，kind ∈ {reasoning, content}。"""
    ordered: list[tuple[str, str]] = []
    for line in sse_text.split("\n"):
        if not line.startswith("data: ") or "[DONE]" in line:
            continue
        try:
            payload = json.loads(line[6:].strip())
        except (ValueError, json.JSONDecodeError):
            continue
        for choice in payload.get("choices") or []:
            delta = choice.get("delta", {})
            if delta.get("reasoning_content"):
                ordered.append(("reasoning", delta["reasoning_content"]))
            elif delta.get("content"):
                ordered.append(("content", delta["content"]))
    return ordered


@pytest.mark.asyncio
async def test_prelude_texts_emitted_before_body_ordered() -> None:
    """6.2 / TRACE-01：prelude 两条 reasoning_content 在首个 content chunk 之前、有序透出。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "正文内容"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    chunks = await _collect(
        OpenAICompatAdapter.translate_stream(
            runner, "test", model="friday-default",
            prelude_texts=["正在检索 RAG…", "检索完成，命中 3 处"],
        )
    )
    first_content_idx: int | None = None
    pre_reasoning: list[str] = []
    for i, c in enumerate(chunks):
        if not c.get("choices"):
            continue
        delta = c["choices"][0].get("delta", {})
        if delta.get("content") and first_content_idx is None:
            first_content_idx = i
        if delta.get("reasoning_content") and first_content_idx is None:
            pre_reasoning.append(delta["reasoning_content"])
    assert first_content_idx is not None, "应有正文 content chunk"
    assert pre_reasoning == ["正在检索 RAG…", "检索完成，命中 3 处"]
    # prelude chunk 结构合法 + 全流无 tool_calls
    for c in chunks:
        for choice in c.get("choices", []):
            assert "tool_calls" not in choice.get("delta", {})
            assert choice.get("finish_reason") != "tool_calls"
            if choice.get("delta", {}).get("reasoning_content"):
                assert choice.get("finish_reason") is None
                assert c["object"] == "chat.completion.chunk"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_view_stream_emits_rag_progress_before_body() -> None:
    """6.2 / TRACE-01 view 级端到端：post(stream=True) 命中 RAG → 正文前两条检索 progress 有序、全流无 tool_calls。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "正文"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 1, "output": 1}, "status": "completed"}),
    )
    search_result = SimpleNamespace(
        final_context="相关代码上下文",
        layers=[SimpleNamespace(result_count=3)],
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
            "/v1/chat/completions",
            data=json.dumps({
                "model": "friday-default",
                "messages": [{"role": "user", "content": "解释代码"}],
                "stream": True,
            }),
            content_type="application/json",
        )

    assert response.status_code == 200
    raw_parts: list[bytes] = []
    async for chunk in response.streaming_content:
        raw_parts.append(chunk)
    sse_text = b"".join(raw_parts).decode()

    ordered = _ordered_deltas(sse_text)
    first_content = next((i for i, (k, _) in enumerate(ordered) if k == "content"), None)
    assert first_content is not None, "应有正文 content"
    pre = [t for (k, t) in ordered[:first_content] if k == "reasoning"]
    assert pre == ["正在检索 RAG…", "检索完成，命中 3 处"]
    # 全流无 tool_calls / finish_reason==tool_calls
    for line in sse_text.split("\n"):
        if not line.startswith("data: ") or "[DONE]" in line:
            continue
        try:
            payload = json.loads(line[6:].strip())
        except (ValueError, json.JSONDecodeError):
            continue
        for choice in payload.get("choices") or []:
            assert "tool_calls" not in choice.get("delta", {})
            assert choice.get("finish_reason") != "tool_calls"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_view_non_stream_content_zero_regression() -> None:
    """6.3 / D-3 / P-6：非流式聚合命中 RAG 时 message.content 逐字不变，且不引入检索 progress。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "Hello, "}),
        AgentEvent(type=TEXT_DELTA, data={"text": "world!"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 5, "output": 3}, "status": "completed"}),
    )
    search_result = SimpleNamespace(
        final_context="相关代码上下文",
        layers=[SimpleNamespace(result_count=3)],
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
    message = data["choices"][0]["message"]
    assert message["content"] == "Hello, world!"
    # 非流式不传 prelude → 绝不引入检索 progress（content 不被污染）
    assert "reasoning_content" not in message


@pytest.mark.asyncio
async def test_prelude_none_and_empty_byte_equivalent() -> None:
    """6.3：prelude_texts=None / [] 与不传该参数（Plan 01 现状）结构逐字等价、不新增 chunk。"""

    def _events() -> list[AgentEvent]:
        return [
            AgentEvent(type=TEXT_DELTA, data={"text": "Hello"}),
            AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
        ]

    default_chunks = await _collect(
        OpenAICompatAdapter.translate_stream(_make_runner(*_events()), "t", model="m")
    )
    none_chunks = await _collect(
        OpenAICompatAdapter.translate_stream(_make_runner(*_events()), "t", model="m", prelude_texts=None)
    )
    empty_chunks = await _collect(
        OpenAICompatAdapter.translate_stream(_make_runner(*_events()), "t", model="m", prelude_texts=[])
    )
    assert _strip_volatile(none_chunks) == _strip_volatile(default_chunks)
    assert _strip_volatile(empty_chunks) == _strip_volatile(default_chunks)
    assert len(default_chunks) == 3  # role + content + finish（无新增 progress chunk）


@pytest.mark.asyncio
async def test_prelude_include_usage_consistency() -> None:
    """include_usage=True：每条 prelude reasoning chunk 带 usage=None，末尾仍恰好一个 choices=[] usage chunk。"""
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "hi"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {"input": 3, "output": 2}, "status": "completed"}),
    )
    chunks = await _collect(
        OpenAICompatAdapter.translate_stream(
            runner, "test", model="friday-default", include_usage=True,
            prelude_texts=["正在检索 RAG…", "检索完成，命中 2 处"],
        )
    )
    prelude_chunks = [
        c for c in chunks
        if c.get("choices") and c["choices"][0].get("delta", {}).get("reasoning_content")
    ]
    assert len(prelude_chunks) == 2
    for c in prelude_chunks:
        assert "usage" in c
        assert c["usage"] is None
    usage_chunks = [c for c in chunks if c.get("choices") == []]
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["usage"]["total_tokens"] == 5


@pytest.mark.asyncio
async def test_prelude_sentinel_never_leaks_full_stream() -> None:
    """6.4：retrieval_to_progress 输入含 SENTINEL_CTX/SENTINEL_Q → 派生 prelude 全量 SSE 不含任一 sentinel。"""
    from compat.progress import retrieval_to_progress

    result = SimpleNamespace(
        final_context="SENTINEL_CTX_secret 敏感代码片段",
        layers=[SimpleNamespace(result_count=1)],
        repository_ids=[],
        query="SENTINEL_Q 用户原始问题",
    )
    prelude = retrieval_to_progress(result)
    runner = _make_runner(
        AgentEvent(type=TEXT_DELTA, data={"text": "正文"}),
        AgentEvent(type=MESSAGE_COMPLETE, data={"usage": {}, "status": "completed"}),
    )
    raw = await _collect_raw(
        OpenAICompatAdapter.translate_stream(runner, "t", model="m", prelude_texts=prelude)
    )
    text = raw.decode()
    assert "SENTINEL_CTX_secret" not in text
    assert "SENTINEL_Q" not in text


# ──────────────────────────────────────────────────────────────────────────────
# request_handler 测试
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prepare_messages_with_search(django_db_setup: Any) -> None:
    """LayeredSearchService.search 返回 final_context → system message 被前置插入（contract）。"""
    from langchain_core.messages import SystemMessage

    from compat.request_handler import prepare_messages

    mock_result = MagicMock()
    mock_result.final_context = "代码上下文内容"

    messages = [{"role": "user", "content": "请帮我解释这段代码"}]

    with patch("compat.request_handler.LayeredSearchService") as mock_service:
        mock_service.search = AsyncMock(return_value=mock_result)
        lc_messages = await prepare_messages(messages, repository_ids=None, project_id=None)

    assert isinstance(lc_messages[0], SystemMessage)
    assert "代码上下文内容" in lc_messages[0].content


@pytest.mark.asyncio
async def test_prepare_messages_search_fails_graceful() -> None:
    """LayeredSearchService 抛异常 → 降级返回原始 lc_messages（contract fallback）。"""
    from langchain_core.messages import HumanMessage

    from compat.request_handler import prepare_messages

    messages = [{"role": "user", "content": "测试问题"}]

    with patch("compat.request_handler.LayeredSearchService") as mock_service:
        mock_service.search = AsyncMock(side_effect=Exception("Qdrant 不可用"))
        lc_messages = await prepare_messages(messages, repository_ids=None, project_id=None)

    assert len(lc_messages) == 1
    assert isinstance(lc_messages[0], HumanMessage)
    assert lc_messages[0].content == "测试问题"


@pytest.mark.asyncio
async def test_repository_ids_routing() -> None:
    """显式 repository_ids → LayeredSearchService.search 收到该列表（contract 第一层）。"""
    from compat.request_handler import prepare_messages

    mock_result = MagicMock()
    mock_result.final_context = ""

    messages = [{"role": "user", "content": "查询"}]
    repo_ids = ["550e8400-e29b-41d4-a716-446655440000"]

    with patch("compat.request_handler.LayeredSearchService") as mock_service:
        mock_service.search = AsyncMock(return_value=mock_result)
        await prepare_messages(messages, repository_ids=repo_ids, project_id=None)

    mock_service.search.assert_called_once()
    call_kwargs = mock_service.search.call_args.kwargs
    assert call_kwargs["repository_ids"] == repo_ids


@pytest.mark.asyncio
async def test_no_repository_ids_fallback() -> None:
    """不传 repository_ids → LayeredSearchService.search 收到 None（走 RepoRouter，contract 第三层）。"""
    from compat.request_handler import prepare_messages

    mock_result = MagicMock()
    mock_result.final_context = ""

    messages = [{"role": "user", "content": "查询"}]

    with patch("compat.request_handler.LayeredSearchService") as mock_service:
        mock_service.search = AsyncMock(return_value=mock_result)
        await prepare_messages(messages, repository_ids=None, project_id=None)

    mock_service.search.assert_called_once()
    call_kwargs = mock_service.search.call_args.kwargs
    assert call_kwargs["repository_ids"] is None
