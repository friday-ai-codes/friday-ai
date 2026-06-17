"""OpenAICompatAdapter — Friday AgentEvent → OpenAI SSE chunk 翻译器（contract/contract/contract）。

翻译路径：
    LangChainAgentRunner.stream() → AgentEvent
    → OpenAICompatAdapter.translate_stream() → bytes (SSE encoded)
    → ChatCompletionsView → 客户端
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any, Literal

from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    THINKING,
    TOOL_USE_RESULT,
    TOOL_USE_START,
)
from agents.langchain_runner import LangChainAgentRunner

from .progress import make_reasoning_chunk, tool_event_to_progress
from .streaming import sse_encode


class OpenAICompatAdapter:
    """Friday AgentEvent → OpenAI SSE chunk 翻译器（静态方法类）。"""

    @staticmethod
    async def translate_stream(
        runner: LangChainAgentRunner,
        prompt: str | list[Any],
        *,
        model: str,
        include_usage: bool = False,
        prelude_texts: list[str] | None = None,
    ) -> AsyncGenerator[bytes, None]:
        """翻译 AgentEvent 流为 OpenAI SSE chunk 字节流。

        关键约束（Pitfall 1 / contract）：
        - include_usage=False：所有 chunk 不带 usage 字段
        - include_usage=True：中间 chunk usage=null，最后追加 choices=[] + usage 非空 chunk

        prelude_texts（Plan 02 / TRACE-01 可见效果）：可选 progress 文本列表，在
        role=assistant 首 chunk 之后、runner 正文流之前逐条以 ``delta.reasoning_content``
        透出（复用 ``make_reasoning_chunk``）。仅 view 层在**命中 RAG 时**注入（由
        ``retrieval_to_progress`` 派生命中计数语义，绝不内联 final_context/query，INV-5）；
        为 None/空时不产任何 chunk —— 与 Plan 01 行为逐字等价（既有测试不回退）。
        """
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        common: dict[str, Any] = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
        }

        # 首 chunk：role=assistant（OpenAI 协议约定）
        yield sse_encode({
            **common,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        })

        # prelude：role chunk 之后、正文之前透出检索 progress（TRACE-01 可见）。
        # 空/None → 不产任何 chunk（零回归 byte-eq）。
        for text in prelude_texts or []:
            yield make_reasoning_chunk(common, text, include_usage)

        finish_reason: Literal["stop", "length", "tool_calls"] = "stop"
        final_usage: dict[str, Any] | None = None

        async for evt in runner.stream(prompt):
            if evt.type == TEXT_DELTA:
                chunk: dict[str, Any] = {
                    **common,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": evt.data.get("text", "")},
                        "finish_reason": None,
                    }],
                }
                if include_usage:
                    chunk["usage"] = None
                yield sse_encode(chunk)

            elif evt.type == THINKING:
                # contract：THINKING → delta.reasoning_content（DeepSeek/o1 事实标准）
                chunk = {
                    **common,
                    "choices": [{
                        "index": 0,
                        "delta": {"reasoning_content": evt.data.get("thinking", "")},
                        "finish_reason": None,
                    }],
                }
                if include_usage:
                    chunk["usage"] = None
                yield sse_encode(chunk)

            elif evt.type == MESSAGE_COMPLETE:
                # 收尾 chunk：finish_reason 非空，delta 为空
                status = evt.data.get("status", "completed")
                if status == "interrupted":
                    # OpenAI 无 interrupted，用 stop 表征
                    finish_reason = "stop"
                if include_usage:
                    final_usage = evt.data.get("usage") or {}
                finish_chunk: dict[str, Any] = {
                    **common,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason,
                    }],
                }
                if include_usage:
                    finish_chunk["usage"] = None
                yield sse_encode(finish_chunk)
                break

            elif evt.type == ERROR:
                # 流式错误：yield error envelope 后 return（security mitigation：不泄露 traceback）
                yield b"data: " + json.dumps({
                    "error": {
                        "message": evt.data.get("message", "internal_error"),
                        "type": "server_error",
                        "code": "internal_error",
                    }
                }, ensure_ascii=False).encode() + b"\n\n"
                return

            elif evt.type in (TOOL_USE_START, TOOL_USE_RESULT):
                # 内部工具事件 → delta.reasoning_content progress（TRACE-01 机制）。
                # 仅 helper 命中（TOOL_USE_START 且工具名在映射表）才 emit；返 None
                # 则 continue，与现状降级逐字等价、不产空 chunk。绝不写 delta.tool_calls /
                # finish_reason=tool_calls（TRACE-02 / INV-5）。
                # DEVIATION（56-RESEARCH D-1）：当前 compat _build_runner 不绑定 tools，
                # 此分支为前向兼容 / Phase 57 复用预埋；真实 RAG 检索 progress 由 Plan 02
                # 在 view 层合成。
                progress = tool_event_to_progress(evt)
                if progress is not None:
                    yield make_reasoning_chunk(common, progress, include_usage)

            else:
                # BUDGET_WARNING / 其余未知类型：静默降级（TOOL_USE_* 已独立分支映射）
                continue

        # Pitfall 1：include_usage=True 时最后追加 choices=[] + usage 非空 chunk
        if include_usage and final_usage is not None:
            yield sse_encode({
                **common,
                "choices": [],
                "usage": {
                    "prompt_tokens": int(final_usage.get("input", 0) or 0),
                    "completion_tokens": int(final_usage.get("output", 0) or 0),
                    "total_tokens": int(
                        (final_usage.get("input", 0) or 0)
                        + (final_usage.get("output", 0) or 0)
                    ),
                },
            })
