"""OpenAICompatAdapter — Friday AgentEvent → OpenAI SSE chunk 翻译器。
翻译路径：
 LangChainAgentRunner.stream → AgentEvent
 → OpenAICompatAdapter.translate_stream → bytes (SSE encoded)
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
 AgentEvent,
)
from agents.langchain_runner import LangChainAgentRunner
from .streaming import _omit, sse_encode
class OpenAICompatAdapter:
 """Friday AgentEvent → OpenAI SSE chunk 翻译器（静态方法类）。"""
 @staticmethod
 async def translate_stream(
 runner: LangChainAgentRunner,
 prompt: str | list[Any],
 *,
 model: str,
 include_usage: bool = False,
 ) -> AsyncGenerator[bytes, None]:
 """翻译 AgentEvent 流为 OpenAI SSE chunk 字节流。
 关键约束（Pitfall 1 / ）：
 - include_usage=False：所有 chunk 不带 usage 字段
 - include_usage=True：中间 chunk usage=null，最后追加 choices= + usage 非空 chunk
 """
 chat_id = f"chatcmpl-{uuid.uuid4.hex[:24]}"
 created = int(time.time)
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
 #：THINKING → delta.reasoning_content（DeepSeek/o1 事实标准）
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
 # 流式错误：yield error envelope 后 return（T-：不泄露 traceback）
 yield b"data: " + json.dumps({
 "error": {
 "message": evt.data.get("message", "internal_error"),
 "type": "server_error",
 "code": "internal_error",
 }
 }, ensure_ascii=False).encode + b"\n\n"
 return
 else:
 # TOOL_USE_START / TOOL_USE_RESULT / BUDGET_WARNING / 其他：暂不 emit
 # (tool_calls 双向映射) 时再补
 continue
 # Pitfall 1：include_usage=True 时最后追加 choices= + usage 非空 chunk
 if include_usage and final_usage is not None:
 yield sse_encode({
 **common,
 "choices":,
 "usage": {
 "prompt_tokens": int(final_usage.get("input", 0) or 0),
 "completion_tokens": int(final_usage.get("output", 0) or 0),
 "total_tokens": int(
 (final_usage.get("input", 0) or 0)
 + (final_usage.get("output", 0) or 0)
 ),
 },
 })
