"""
OpenAI Responses API Provider 实现。
使用 OpenAI Responses API（client.responses.create）而非 Chat Completions API。
支持 Codex 变体（codex_mode=True）。
"""
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
import openai
import structlog
from tenacity import (
 RetryCallState,
 retry,
 retry_if_exception_type,
 stop_after_attempt,
 wait_exponential,
)
from agents.llm.base import LLMConfig
from agents.llm.types import LLMResponse, ToolCall
from agents.tools.base import ToolDefinition
logger = structlog.get_logger
def _log_retry(retry_state: RetryCallState) -> None:
 wait_time = retry_state.next_action.sleep if retry_state.next_action else 0 # type: ignore[union-attr]
 logger.warning("llm_retry", attempt=retry_state.attempt_number, wait=wait_time)
class OpenAIResponsesProvider:
 """OpenAI Responses API Provider。
 使用 client.responses.create 而非 chat.completions.create。
 Responses API 使用 input/instructions 参数替代 messages 数组。
 codex_mode=True 时启用 Codex 特有行为。
 """
 def __init__(
 self,
 config: LLMConfig | None = None,
 api_key: str | None = None,
 base_url: str | None = None,
 model: str = "",
 codex_mode: bool = False,
 ) -> None:
 if config is not None:
 self.model = config.model
 self.max_tokens = config.max_tokens
 self.temperature = config.temperature
 resolved_api_key = config.api_key or os.environ.get("OPENAI_API_KEY", "")
 resolved_base_url = config.base_url
 else:
 self.model = model
 self.max_tokens = 4096
 self.temperature = 0.0
 resolved_api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
 resolved_base_url = base_url
 self.codex_mode = codex_mode
 client_kwargs: dict[str, Any] = {"api_key": resolved_api_key or "dummy"}
 if resolved_base_url:
 client_kwargs["base_url"] = resolved_base_url
 self.client = openai.AsyncOpenAI(**client_kwargs)
 @retry(
 stop=stop_after_attempt(3),
 wait=wait_exponential(multiplier=1, min=1, max=60),
 retry=retry_if_exception_type((openai.RateLimitError, openai.APIConnectionError)),
 before_sleep=_log_retry,
 )
 async def chat(
 self,
 messages: list[dict[str, Any]],
 tools: list[dict[str, Any]] | None = None,
 max_tokens: int | None = None,
 ) -> LLMResponse:
 """发送 Responses API 请求，将 Anthropic 格式 messages 转换为 input/instructions。"""
 instructions, input_messages = _convert_messages_to_responses_format(messages)
 responses_tools = _convert_tools_to_responses_format(tools) if tools else None
 kwargs: dict[str, Any] = {
 "model": self.model,
 "input": input_messages,
 }
 if instructions:
 kwargs["instructions"] = instructions
 if responses_tools:
 kwargs["tools"] = responses_tools
 response = await self.client.responses.create(**kwargs)
 result = _parse_responses_response(response)
 logger.info(
 "llm_chat_complete",
 model=self.model,
 provider="openai_responses",
 codex_mode=self.codex_mode,
 input_tokens=result.usage.get("input_tokens", 0),
 output_tokens=result.usage.get("output_tokens", 0),
 stop_reason=result.stop_reason,
 tool_calls=len(result.tool_calls),
 )
 return result
 @retry(
 stop=stop_after_attempt(3),
 wait=wait_exponential(multiplier=1, min=1, max=60),
 retry=retry_if_exception_type((openai.RateLimitError, openai.APIConnectionError)),
 before_sleep=_log_retry,
 )
 async def stream_chat(
 self,
 messages: list[dict[str, Any]],
 tools: list[dict[str, Any]] | None = None,
 max_tokens: int | None = None,
 on_text: Callable[[str], Awaitable[None]] | None = None,
 ) -> LLMResponse:
 """流式 Responses API 请求。"""
 instructions, input_messages = _convert_messages_to_responses_format(messages)
 responses_tools = _convert_tools_to_responses_format(tools) if tools else None
 kwargs: dict[str, Any] = {
 "model": self.model,
 "input": input_messages,
 "stream": True,
 }
 if instructions:
 kwargs["instructions"] = instructions
 if responses_tools:
 kwargs["tools"] = responses_tools
 text_parts: list[str] =
 tool_calls: list[ToolCall] =
 raw_content: list[dict[str, Any]] =
 usage: dict[str, int] = {}
 stream = await self.client.responses.create(**kwargs)
 async for event in stream:
 event_type = getattr(event, "type", "")
 if event_type == "response.output_text.delta":
 delta = getattr(event, "delta", "")
 if delta and on_text:
 await on_text(delta)
 text_parts.append(delta)
 elif event_type == "response.completed":
 resp = getattr(event, "response", None)
 if resp:
 # 从完成事件中提取完整信息
 completed_result = _parse_responses_response(resp)
 tool_calls = completed_result.tool_calls
 raw_content = completed_result.raw_content
 usage = completed_result.usage
 content = "".join(text_parts)
 if not raw_content and content:
 raw_content = [{"type": "text", "text": content}]
 result = LLMResponse(
 content=content,
 raw_content=raw_content,
 tool_calls=tool_calls,
 usage=usage,
 stop_reason="end_turn",
 )
 logger.info(
 "llm_stream_chat_complete",
 model=self.model,
 provider="openai_responses",
 codex_mode=self.codex_mode,
 input_tokens=result.usage.get("input_tokens", 0),
 output_tokens=result.usage.get("output_tokens", 0),
 stop_reason=result.stop_reason,
 tool_calls=len(result.tool_calls),
 )
 return result
 def get_tool_schema(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
 """返回 Anthropic 格式 schemas（转换在 chat 内部进行）。"""
 return [
 {"name": t.name, "description": t.description, "input_schema": t.parameters}
 for t in tools
 ]
# === Format conversion helpers ===
def _convert_messages_to_responses_format(
 messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]] | str]:
 """将 Anthropic 格式 messages 转换为 Responses API 的 instructions + input。
 Returns:
 (instructions, input_messages) 元组
 """
 instructions = ""
 input_messages: list[dict[str, Any]] =
 for msg in messages:
 role = msg.get("role", "user")
 content = msg.get("content", "")
 if role == "system":
 # system 消息变为 instructions 参数
 instructions = content if isinstance(content, str) else str(content)
 continue
 # Responses API 接受 {"role": ..., "content": ...} 格式的消息列表
 if isinstance(content, str):
 input_messages.append({"role": role, "content": content})
 elif isinstance(content, list):
 # 处理 Anthropic content blocks
 text_parts =
 for block in content:
 if isinstance(block, dict):
 if block.get("type") == "text":
 text_parts.append(block.get("text", ""))
 elif block.get("type") == "tool_use":
 # 工具调用块作为 assistant 消息的一部分
 pass
 elif block.get("type") == "tool_result":
 # 工具结果
 pass
 elif isinstance(block, str):
 text_parts.append(block)
 if text_parts:
 input_messages.append({"role": role, "content": "\n".join(text_parts)})
 # 如果只有一条 user 消息，直接传字符串
 if len(input_messages) == 1 and input_messages[0]["role"] == "user":
 return instructions, input_messages[0]["content"]
 return instructions, input_messages
def _convert_tools_to_responses_format(
 tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
 """将 Anthropic 格式 tools 转换为 Responses API 格式。"""
 return [
 {
 "type": "function",
 "name": t["name"],
 "description": t.get("description", ""),
 "parameters": t.get("input_schema", {}),
 }
 for t in tools
 ]
def _parse_responses_response(response: Any) -> LLMResponse:
 """解析 Responses API 响应为 LLMResponse。"""
 text_parts: list[str] =
 tool_calls: list[ToolCall] =
 raw_content: list[dict[str, Any]] =
 # Responses API 的 output 是一个列表
 output = getattr(response, "output", ) or
 for item in output:
 item_type = getattr(item, "type", "")
 if item_type == "message":
 # 消息输出项
 msg_content = getattr(item, "content", ) or
 for part in msg_content:
 part_type = getattr(part, "type", "")
 if part_type == "output_text":
 text = getattr(part, "text", "")
 text_parts.append(text)
 raw_content.append({"type": "text", "text": text})
 elif item_type == "function_call":
 # 工具调用
 call_id = getattr(item, "call_id", "") or getattr(item, "id", "")
 name = getattr(item, "name", "")
 arguments_str = getattr(item, "arguments", "{}")
 try:
 args = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
 except json.JSONDecodeError:
 args = {"raw": arguments_str}
 tool_calls.append(ToolCall(id=call_id, name=name, arguments=args))
 raw_content.append({
 "type": "tool_use",
 "id": call_id,
 "name": name,
 "input": args,
 })
 # 尝试从 output_text 属性获取文本（简便方式）
 if not text_parts:
 output_text = getattr(response, "output_text", None)
 if output_text:
 text_parts.append(output_text)
 raw_content.append({"type": "text", "text": output_text})
 # Usage
 usage: dict[str, int] = {}
 resp_usage = getattr(response, "usage", None)
 if resp_usage:
 usage = {
 "input_tokens": getattr(resp_usage, "input_tokens", 0) or 0,
 "output_tokens": getattr(resp_usage, "output_tokens", 0) or 0,
 }
 stop_reason = getattr(response, "status", "completed")
 if stop_reason == "completed":
 stop_reason = "end_turn" if not tool_calls else "tool_use"
 return LLMResponse(
 content="\n".join(text_parts),
 raw_content=raw_content,
 tool_calls=tool_calls,
 usage=usage,
 stop_reason=stop_reason,
 )
