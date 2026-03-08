"""
OpenAI-compatible LLM provider implementation.
Supports any OpenAI-compatible API (OpenRouter, vLLM, LiteLLM, etc.).
Handles bidirectional message format conversion between Anthropic format
(used internally by AgentLoop) and OpenAI format.
"""
import json
import os
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
class OpenAICompletionsProvider:
 """LLM provider for OpenAI-compatible APIs.
 Converts between Anthropic message format (used by AgentLoop)
 and OpenAI chat completion format.
 """
 def __init__(
 self,
 config: LLMConfig | None = None,
 api_key: str | None = None,
 base_url: str | None = None,
 model: str = "",
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
 """Send chat completion, converting Anthropic format to/from OpenAI."""
 oai_messages = _convert_messages_to_openai(messages)
 oai_tools = _convert_tools_to_openai(tools) if tools else None
 kwargs: dict[str, Any] = {
 "model": self.model,
 "max_tokens": max_tokens or self.max_tokens,
 "messages": oai_messages,
 }
 if oai_tools:
 kwargs["tools"] = oai_tools
 response = await self.client.chat.completions.create(**kwargs)
 result = _parse_openai_response(response)
 logger.info(
 "llm_chat_complete",
 model=self.model,
 input_tokens=result.usage.get("input_tokens", 0),
 output_tokens=result.usage.get("output_tokens", 0),
 stop_reason=result.stop_reason,
 tool_calls=len(result.tool_calls),
 )
 return result
 def get_tool_schema(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
 """Return Anthropic-format schemas (conversion happens in chat)."""
 return [
 {"name": t.name, "description": t.description, "input_schema": t.parameters}
 for t in tools
 ]
# === Format conversion helpers ===
def _convert_messages_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
 """Convert Anthropic-format messages to OpenAI format."""
 result: list[dict[str, Any]] =
 for msg in messages:
 role = msg.get("role", "user")
 content = msg.get("content")
 # Simple string content
 if isinstance(content, str):
 result.append({"role": role, "content": content})
 continue
 # List content (Anthropic content blocks)
 if isinstance(content, list):
 if role == "assistant":
 result.append(_convert_assistant_blocks(content))
 elif role == "user":
 # Check if it's tool_result blocks
 if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
 result.extend(_convert_tool_results(content))
 else:
 # Regular user content blocks
 text_parts =
 for block in content:
 if isinstance(block, dict) and block.get("type") == "text":
 text_parts.append(block.get("text", ""))
 elif isinstance(block, str):
 text_parts.append(block)
 result.append({"role": "user", "content": "\n".join(text_parts) or str(content)})
 continue
 result.append({"role": role, "content": str(content) if content else ""})
 return result
def _convert_assistant_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
 """Convert Anthropic assistant content blocks to OpenAI assistant message."""
 text_parts: list[str] =
 tool_calls: list[dict[str, Any]] =
 for block in blocks:
 if not isinstance(block, dict):
 continue
 if block.get("type") == "text":
 text_parts.append(block.get("text", ""))
 elif block.get("type") == "tool_use":
 tool_calls.append({
 "id": block.get("id", ""),
 "type": "function",
 "function": {
 "name": block.get("name", ""),
 "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
 },
 })
 msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
 if tool_calls:
 msg["tool_calls"] = tool_calls
 return msg
def _convert_tool_results(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
 """Convert Anthropic tool_result blocks to OpenAI tool messages."""
 result: list[dict[str, Any]] =
 for block in blocks:
 if not isinstance(block, dict):
 continue
 content = block.get("content", "")
 if isinstance(content, dict) or isinstance(content, list):
 content = json.dumps(content, ensure_ascii=False)
 result.append({
 "role": "tool",
 "tool_call_id": block.get("tool_use_id", ""),
 "content": str(content),
 })
 return result
def _convert_tools_to_openai(
 tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
 """Convert Anthropic tool schemas to OpenAI format."""
 return [
 {
 "type": "function",
 "function": {
 "name": t["name"],
 "description": t.get("description", ""),
 "parameters": t.get("input_schema", {}),
 },
 }
 for t in tools
 ]
def _parse_openai_response(response: Any) -> LLMResponse:
 """Parse OpenAI response into LLMResponse with Anthropic-format raw_content."""
 choice = response.choices[0] if response.choices else None
 if not choice:
 return LLMResponse(content="", raw_content=, usage={}, stop_reason="error")
 message = choice.message
 text = message.content or ""
 tool_calls: list[ToolCall] =
 raw_content: list[dict[str, Any]] =
 if text:
 raw_content.append({"type": "text", "text": text})
 if message.tool_calls:
 for tc in message.tool_calls:
 try:
 args = json.loads(tc.function.arguments) if tc.function.arguments else {}
 except json.JSONDecodeError:
 args = {"raw": tc.function.arguments}
 tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
 raw_content.append({
 "type": "tool_use",
 "id": tc.id,
 "name": tc.function.name,
 "input": args,
 })
 usage = {}
 if response.usage:
 usage = {
 "input_tokens": response.usage.prompt_tokens or 0,
 "output_tokens": response.usage.completion_tokens or 0,
 }
 stop_reason = choice.finish_reason or "end_turn"
 return LLMResponse(
 content=text,
 raw_content=raw_content,
 tool_calls=tool_calls,
 usage=usage,
 stop_reason=stop_reason,
 )
