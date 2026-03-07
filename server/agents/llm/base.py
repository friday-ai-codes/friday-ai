"""
LLM Provider abstraction for the Agent framework.
Defines the Protocol for LLM providers and configuration dataclass,
enabling multi-provider support without changing agent loop code.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from agents.llm.types import LLMResponse
from agents.tools.base import ToolDefinition
class LLMProvider(Protocol):
 """
 Protocol defining the interface for LLM providers.
 Any LLM provider (Claude, GPT, etc.) must implement this interface
 to be used with the agent loop.
 """
 async def chat(
 self,
 messages: list[dict[str, Any]],
 tools: list[dict[str, Any]] | None = None,
 max_tokens: int = 4096,
 ) -> LLMResponse:
 """
 Send a chat completion request with optional tools.
 Args:
 messages: List of message dicts with 'role' and 'content'
 tools: Optional list of tool schemas in provider-specific format
 max_tokens: Maximum tokens for the response
 Returns:
 LLMResponse with parsed content, tool calls, and usage
 """
 ...
 async def stream_chat(
 self,
 messages: list[dict[str, Any]],
 tools: list[dict[str, Any]] | None = None,
 max_tokens: int = 4096,
 on_text: Callable[[str], Awaitable[None]] | None = None,
 ) -> LLMResponse:
 """
 Stream a chat completion, invoking on_text for each text delta.
 Args:
 messages: List of message dicts with 'role' and 'content'
 tools: Optional list of tool schemas in provider-specific format
 max_tokens: Maximum tokens for the response
 on_text: Async callback invoked for each text delta chunk
 Returns:
 LLMResponse with parsed content, tool calls, and usage
 """
 ...
 def get_tool_schema(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
 """
 Convert tool definitions to provider-specific schema format.
 Args:
 tools: List of ToolDefinition objects from the registry
 Returns:
 List of tool schemas in the format expected by the provider
 """
 ...
@dataclass
class LLMConfig:
 """
 Configuration for an LLM provider.
 Attributes:
 model: Model identifier (e.g., 'claude-sonnet-4-20250514')
 max_tokens: Default maximum tokens for responses
 temperature: Sampling temperature (0 for deterministic)
 api_key: API key (uses environment variable if None)
 base_url: Custom API base URL (uses default if None)
 """
 model: str
 max_tokens: int = 4096
 temperature: float = 0.0
 api_key: str | None = None
 base_url: str | None = None
def create_provider(
 provider_type: str = "anthropic",
 api_key: str | None = None,
 base_url: str | None = None,
 model: str = "",
) -> Any:
 """Create an LLM provider by type.
 Args:
 provider_type: "anthropic" or "openai"
 api_key: API key
 base_url: Custom API base URL
 model: Model identifier
 Returns:
 LLMProvider instance
 """
 if provider_type == "openai":
 from agents.llm.openai import OpenAIProvider
 return OpenAIProvider(api_key=api_key, base_url=base_url, model=model)
 from agents.llm.claude import ClaudeProvider
 return ClaudeProvider(api_key=api_key, base_url=base_url, model=model)
