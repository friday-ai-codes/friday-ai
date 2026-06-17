"""AnthropicCompatAdapter — Friday AgentEvent → Anthropic Messages SSE 翻译器（57-01）。

本模块是 Anthropic Messages 兼容专属 adapter，与 OpenAI ``adapter.py`` 平行：

- SSE 为 ``event: <type>`` + ``data: <json>`` 双行帧、不发 ``[DONE]`` 哨兵；绝不复用
  OpenAI ``sse_encode``（它只产 ``data:`` 单行帧，无 ``event:`` 行，P-1）。
- usage 改名：MESSAGE_COMPLETE.usage 的 ``input``/``output`` → Anthropic
  ``input_tokens``/``output_tokens``（P-2，绝不透传原 key）。
- stop_reason 映射：completed/interrupted/max_iterations → ``end_turn``（P-3 / D-3）。
- INV-5 / TRACE-02：THINKING 不外透（静默 continue）；绝不发 ``tool_use`` content block。
- 错误不泄漏 traceback（ASVS V8.3 / P-10）。

DEVIATION D-1（同 Phase 56，见 57-RESEARCH §3 D-1）：compat ``_build_runner`` 不绑定
tools，``TOOL_USE_*`` 在本链路永不发射；可见 trace（thinking block prelude + 检索命中
计数）由 Plan 02 经 ``retrieval_to_progress`` 兑现。本 Plan 01 仅实现非流式聚合 +
``translate_stream`` 文本/收尾路径，并为 Plan 02 的 prelude/TOOL_USE 扩展预留结构
（index 单线性计数器、8 个事件骨架纯函数齐备）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from agents.core.events import ERROR, MESSAGE_COMPLETE, TEXT_DELTA, THINKING
from agents.langchain_runner import LangChainAgentRunner

# ──────────────────────────────────────────────────────────────────────────────
# SSE 双行帧编码 helper（绝不复用 OpenAI sse_encode）
# ──────────────────────────────────────────────────────────────────────────────


def anthropic_sse_encode(event_type: str, data: dict) -> bytes:
    """产 Anthropic SSE 双行帧 ``b"event: <type>\\n" + b"data: <json>\\n\\n"``。

    约束：``data["type"] == event_type``（调用方保证）。绝不复用 OpenAI ``sse_encode``。
    """
    return (
        b"event: "
        + event_type.encode()
        + b"\n"
        + b"data: "
        + json.dumps(data, ensure_ascii=False).encode()
        + b"\n\n"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 8 个事件骨架纯函数（最小合法 payload，含 type 字段）
# ──────────────────────────────────────────────────────────────────────────────


def message_start_event(msg_id: str, model: str, input_tokens: int = 0) -> dict:
    """message_start：message 骨架（content 空、stop_reason/stop_sequence null、usage）。"""
    return {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        },
    }


def content_block_start(index: int, block_type: str) -> dict:
    """content_block_start：text 或 thinking block（绝不产 tool_use，INV-5/P-5）。"""
    if block_type == "thinking":
        content_block = {"type": "thinking", "thinking": ""}
    else:
        content_block = {"type": "text", "text": ""}
    return {"type": "content_block_start", "index": index, "content_block": content_block}


def content_block_delta_text(index: int, text: str) -> dict:
    """content_block_delta：text_delta。"""
    return {
        "type": "content_block_delta",
        "index": index,
        "delta": {"type": "text_delta", "text": text},
    }


def content_block_delta_thinking(index: int, text: str) -> dict:
    """content_block_delta：thinking_delta（Plan 02 用，本 plan 仅实现纯函数 + 测形状）。"""
    return {
        "type": "content_block_delta",
        "index": index,
        "delta": {"type": "thinking_delta", "thinking": text},
    }


def content_block_stop(index: int) -> dict:
    """content_block_stop。"""
    return {"type": "content_block_stop", "index": index}


def message_delta_event(stop_reason: str, output_tokens: int) -> dict:
    """message_delta：收尾 stop_reason + 累计 output_tokens。"""
    return {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    }


def message_stop_event() -> dict:
    """message_stop。"""
    return {"type": "message_stop"}


def anthropic_error_event(message: str) -> dict:
    """error 事件（不含 traceback，P-10）。"""
    return {"type": "error", "error": {"type": "api_error", "message": message}}


# ──────────────────────────────────────────────────────────────────────────────
# 映射纯函数：stop_reason / usage 改名
# ──────────────────────────────────────────────────────────────────────────────


def _status_to_stop_reason(status: str) -> str:
    """status → Anthropic stop_reason（completed/interrupted/max_iterations → end_turn，D-3）。

    预留 max_tokens 映射位：将来截断态可返回 ``"max_tokens"``。
    """
    return "end_turn"


def _rename_usage(usage: dict | None) -> tuple[int, int]:
    """usage 改名 input/output → (input_tokens, output_tokens)（int 化、非负，P-2）。"""
    if not isinstance(usage, dict):
        return 0, 0
    input_tokens = int(usage.get("input", 0) or 0)
    output_tokens = int(usage.get("output", 0) or 0)
    return max(input_tokens, 0), max(output_tokens, 0)


# ──────────────────────────────────────────────────────────────────────────────
# AnthropicCompatAdapter：流式翻译（text/收尾路径）
# ──────────────────────────────────────────────────────────────────────────────


class AnthropicCompatAdapter:
    """Friday AgentEvent → Anthropic Messages SSE 翻译器（静态方法类）。"""

    @staticmethod
    async def translate_stream(
        runner: LangChainAgentRunner,
        prompt: str | list[Any],
        *,
        model: str,
    ) -> AsyncGenerator[bytes, None]:
        """翻译 AgentEvent 流为 Anthropic SSE 双行帧字节流（本 plan 仅 text/收尾路径）。

        路径（无 prelude/TOOL_USE，Plan 02 扩展）：
          message_start → content_block_start(text, index 0) → 每个 TEXT_DELTA 一个
          text_delta(index 0) → content_block_stop(0) → message_delta(stop_reason +
          累计 output_tokens) → message_stop。

        THINKING 及其余类型静默 continue（INV-5：THINKING 不外透；TOOL_USE_* 留 Plan 02）。
        ERROR → 发 error 事件后 return（不发 content_block_stop/message_delta/message_stop，
        不泄漏 traceback）。
        """
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        yield anthropic_sse_encode("message_start", message_start_event(msg_id, model))

        text_index = 0
        yield anthropic_sse_encode(
            "content_block_start", content_block_start(text_index, "text")
        )

        output_tokens = 0
        stop_reason = "end_turn"

        async for evt in runner.stream(prompt):
            if evt.type == TEXT_DELTA:
                yield anthropic_sse_encode(
                    "content_block_delta",
                    content_block_delta_text(text_index, evt.data.get("text", "")),
                )
            elif evt.type == MESSAGE_COMPLETE:
                stop_reason = _status_to_stop_reason(evt.data.get("status", "completed"))
                _, output_tokens = _rename_usage(evt.data.get("usage"))
                break
            elif evt.type == ERROR:
                yield anthropic_sse_encode(
                    "error",
                    anthropic_error_event(evt.data.get("message", "internal_error")),
                )
                return
            else:
                # THINKING / TOOL_USE_* / 其余：静默 continue（INV-5；TOOL_USE 留 Plan 02）
                continue

        yield anthropic_sse_encode("content_block_stop", content_block_stop(text_index))
        yield anthropic_sse_encode(
            "message_delta", message_delta_event(stop_reason, output_tokens)
        )
        yield anthropic_sse_encode("message_stop", message_stop_event())


# ──────────────────────────────────────────────────────────────────────────────
# 非流式聚合（与 translate_stream 同源翻译核：复用 _status_to_stop_reason/_rename_usage）
# ──────────────────────────────────────────────────────────────────────────────


async def aggregate_message(
    runner: LangChainAgentRunner,
    prompt: str | list[Any],
    *,
    model: str,
    msg_id: str | None = None,
) -> dict:
    """消费 runner 事件聚合为 Anthropic Messages 非流式响应形状（D-5）。

    content 仅承载 TEXT_DELTA 正文（零 trace 污染，P-8）；THINKING/其余 continue；
    ERROR → raise RuntimeError（view 捕获转 Anthropic error envelope）。usage 改名 +
    stop_reason 映射。
    """
    text_parts: list[str] = []
    status = "completed"
    input_tokens = 0
    output_tokens = 0

    async for evt in runner.stream(prompt):
        if evt.type == TEXT_DELTA:
            text_parts.append(evt.data.get("text", ""))
        elif evt.type == MESSAGE_COMPLETE:
            status = evt.data.get("status", "completed")
            input_tokens, output_tokens = _rename_usage(evt.data.get("usage"))
            break
        elif evt.type == ERROR:
            raise RuntimeError(evt.data.get("message", "internal_error"))
        elif evt.type == THINKING:
            # INV-5：THINKING 不外透
            continue
        else:
            continue

    return {
        "id": msg_id or f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "".join(text_parts)}],
        "model": model,
        "stop_reason": _status_to_stop_reason(status),
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
