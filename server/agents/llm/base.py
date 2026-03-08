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
 provider_type: "ProviderType | str" = "anthropic",
 api_key: str | None = None,
 base_url: str | None = None,
 model: str = "",
 **kwargs: Any,
) -> Any:
 """通过 ProviderType 枚举或字符串创建 LLM Provider 实例。
 向后兼容：接受字符串参数（如 "anthropic"、"openai"），自动转换为 ProviderType。
 Args:
 provider_type: Provider 类型（ProviderType 枚举或字符串）
 api_key: API key
 base_url: Custom API base URL
 model: Model identifier
 **kwargs: Provider 特有参数（如 Google 的 project/location）
 Returns:
 LLMProvider instance
 Raises:
 ValueError: 不支持的 Provider 类型
 NotImplementedError: Provider 尚未实现
 """
 from agents.llm.providers import ApiFormat, ProviderType, PROVIDER_REGISTRY
 # 向后兼容：字符串参数转换为 ProviderType
 if isinstance(provider_type, str) and not isinstance(provider_type, ProviderType):
 # "openai" 是历史遗留值，映射到 OPENAI_COMPLETIONS
 if provider_type == "openai":
 provider_type = ProviderType.OPENAI_COMPLETIONS
 else:
 try:
 provider_type = ProviderType(provider_type)
 except ValueError:
 raise ValueError(f"不支持的 Provider 类型: {provider_type}")
 metadata = PROVIDER_REGISTRY[provider_type]
 match metadata["api_format"]:
 case ApiFormat.ANTHROPIC:
 from agents.llm.claude import ClaudeProvider
 return ClaudeProvider(api_key=api_key, base_url=base_url, model=model)
 case ApiFormat.OPENAI_COMPLETIONS:
 from agents.llm.openai_completions import OpenAICompletionsProvider
 return OpenAICompletionsProvider(api_key=api_key, base_url=base_url, model=model)
 case ApiFormat.OPENAI_RESPONSES:
 from agents.llm.openai_responses import OpenAIResponsesProvider
 return OpenAIResponsesProvider(
 api_key=api_key,
 base_url=base_url,
 model=model,
 codex_mode=(provider_type == ProviderType.OPENAI_CODEX_RESPONSES),
 )
 case ApiFormat.GOOGLE_GENAI:
 from agents.llm.google import GoogleProvider
 if provider_type == ProviderType.GOOGLE_ANTIGRAVITY:
 raise NotImplementedError("Google Antigravity Provider 待产品确认后实现")
 return GoogleProvider(
 api_key=api_key,
 model=model,
 vertex_mode=(provider_type == ProviderType.GOOGLE_VERTEX),
 **kwargs,
 )
 raise ValueError(f"不支持的 API 格式: {metadata['api_format']}")
