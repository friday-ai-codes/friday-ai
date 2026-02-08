"""
Claude LLM provider implementation using Anthropic SDK.
Provides the ClaudeProvider class with automatic retry for rate limits
and network errors, token usage tracking, and tool_use support.
"""
import os
from typing import Any
import anthropic
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
 """Log retry attempts for observability."""
 wait_time = (
 retry_state.next_action.sleep if retry_state.next_action else 0 # type: ignore[union-attr]
 )
 logger.warning(
 "llm_retry",
 attempt=retry_state.attempt_number,
 wait=wait_time,
 )
class ClaudeProvider:
 """
 LLM provider implementation for Anthropic's Claude models.
 Supports tool_use API, automatic retry with exponential backoff,
 and token usage tracking.
 Example:
 provider = ClaudeProvider(model="claude-sonnet-4-20250514")
 response = await provider.chat([
 {"role": "user", "content": "Hello!"}
 ])
 print(response.content)
 """
 def __init__(
 self,
 config: LLMConfig | None = None,
 api_key: str | None = None,
 base_url: str | None = None,
 model: str = "claude-sonnet-4-20250514",
 ) -> None:
 """
 Initialize the Claude provider.
 Args:
 config: LLMConfig object (takes precedence over individual params)
 api_key: Anthropic API key (uses ANTHROPIC_API_KEY env var if None)
 base_url: Custom API base URL
 model: Model identifier to use
 """
 if config is not None:
 self.model = config.model
 self.max_tokens = config.max_tokens
 self.temperature = config.temperature
 resolved_api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
 resolved_base_url = config.base_url
 else:
 self.model = model
 self.max_tokens = 4096
 self.temperature = 0.0
 resolved_api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
 resolved_base_url = base_url
 # Initialize async client
 client_kwargs: dict[str, Any] = {}
 if resolved_api_key:
 client_kwargs["api_key"] = resolved_api_key
 if resolved_base_url:
 client_kwargs["base_url"] = resolved_base_url
 self.client = anthropic.AsyncAnthropic(**client_kwargs)
 @retry(
 stop=stop_after_attempt(3),
 wait=wait_exponential(multiplier=1, min=1, max=60),
 retry=retry_if_exception_type(
 (
 anthropic.RateLimitError,
 anthropic.APIConnectionError,
 )
 ),
 before_sleep=_log_retry,
 )
 async def chat(
 self,
 messages: list[dict[str, Any]],
 tools: list[dict[str, Any]] | None = None,
 max_tokens: int | None = None,
 ) -> LLMResponse:
 """
 Send a chat completion request to Claude.
 Automatically retries on rate limit or connection errors with
 exponential backoff. System messages are extracted and passed
 separately as required by the Anthropic API.
 Args:
 messages: List of message dicts with 'role' and 'content'
 tools: Optional list of tool schemas in Anthropic format
 max_tokens: Maximum tokens for response (uses default if None)
 Returns:
 LLMResponse with parsed content, tool calls, and usage
 """
 # Separate system message from chat messages
 system_content: str | None = None
 chat_messages: list[dict[str, Any]] =
 for msg in messages:
 if msg.get("role") == "system":
 system_content = msg.get("content", "")
 else:
 chat_messages.append(msg)
 # Build request kwargs
 kwargs: dict[str, Any] = {
 "model": self.model,
 "max_tokens": max_tokens or self.max_tokens,
 "messages": chat_messages,
 }
 if system_content:
 kwargs["system"] = system_content
 if tools:
 kwargs["tools"] = tools
 # Make the API call
 response = await self.client.messages.create(**kwargs)
 # Parse and log
 result = self._parse_response(response)
 logger.info(
 "llm_chat_complete",
 model=self.model,
 input_tokens=result.usage.get("input_tokens", 0),
 output_tokens=result.usage.get("output_tokens", 0),
 stop_reason=result.stop_reason,
 tool_calls=len(result.tool_calls),
 )
 return result
 def _parse_response(self, response: anthropic.types.Message) -> LLMResponse:
 """
 Parse an Anthropic Message into LLMResponse.
 Extracts text content, tool_use blocks, and usage metrics.
 Args:
 response: Raw Anthropic Message object
 Returns:
 Structured LLMResponse
 """
 text_parts: list[str] =
 tool_calls: list[ToolCall] =
 for block in response.content:
 if block.type == "text":
 text_parts.append(block.text)
 elif block.type == "tool_use":
 tool_calls.append(
 ToolCall(
 id=block.id,
 name=block.name,
 arguments=dict(block.input) if block.input else {},
 )
 )
 return LLMResponse(
 content="\n".join(text_parts),
 raw_content=list(response.content),
 tool_calls=tool_calls,
 usage={
 "input_tokens": response.usage.input_tokens,
 "output_tokens": response.usage.output_tokens,
 },
 stop_reason=response.stop_reason,
 )
 def get_tool_schema(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
 """
 Convert tool definitions to Anthropic's tool format.
 Args:
 tools: List of ToolDefinition objects
 Returns:
 List of tool schemas in Anthropic format
 """
 schemas: list[dict[str, Any]] =
 for tool in tools:
 schemas.append(
 {
 "name": tool.name,
 "description": tool.description,
 "input_schema": tool.parameters,
 }
 )
 return schemas
