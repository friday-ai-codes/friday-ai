"""
LLM Provider abstraction for the Agent framework.
Defines the Protocol for LLM providers and configuration dataclass,
enabling multi-provider support without changing agent loop code.
"""
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
