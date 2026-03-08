"""Tests for the Provider type system: ProviderType enum, PROVIDER_REGISTRY, and create_provider factory."""
import pytest
class TestProviderTypeEnum:
 """Tests for ProviderType StrEnum."""
 def test_provider_type_enum_has_7_members(self) -> None:
 from agents.llm.providers import ProviderType
 assert len(ProviderType) == 7
 def test_provider_type_values_are_strings(self) -> None:
 from agents.llm.providers import ProviderType
 for member in ProviderType:
 assert isinstance(member.value, str)
 assert isinstance(member, str) # StrEnum 特性
 def test_provider_type_from_string(self) -> None:
 from agents.llm.providers import ProviderType
 assert ProviderType("anthropic") == ProviderType.ANTHROPIC
 assert ProviderType("openai-responses") == ProviderType.OPENAI_RESPONSES
 assert ProviderType("openai-codex-responses") == ProviderType.OPENAI_CODEX_RESPONSES
 assert ProviderType("openai-completions") == ProviderType.OPENAI_COMPLETIONS
 assert ProviderType("google-vertex") == ProviderType.GOOGLE_VERTEX
 assert ProviderType("google-gemini-cli") == ProviderType.GOOGLE_GEMINI_CLI
 assert ProviderType("google-antigravity") == ProviderType.GOOGLE_ANTIGRAVITY
 def test_provider_type_invalid_raises_value_error(self) -> None:
 from agents.llm.providers import ProviderType
 with pytest.raises(ValueError):
 ProviderType("invalid-provider")
class TestProviderRegistry:
 """Tests for PROVIDER_REGISTRY metadata."""
 def test_registry_covers_all_providers(self) -> None:
 from agents.llm.providers import PROVIDER_REGISTRY, ProviderType
 assert set(PROVIDER_REGISTRY.keys) == set(ProviderType)
 def test_registry_metadata_fields(self) -> None:
 from agents.llm.providers import PROVIDER_REGISTRY
 required_fields = {"display_name", "api_format", "credential_type", "default_base_url", "env_key"}
 for provider_type, metadata in PROVIDER_REGISTRY.items:
 for field in required_fields:
 assert field in metadata, f"{provider_type}: missing field '{field}'"
 def test_openai_three_providers_share_api_key_env(self) -> None:
 from agents.llm.providers import PROVIDER_REGISTRY, ProviderType
 assert PROVIDER_REGISTRY[ProviderType.OPENAI_RESPONSES]["env_key"] == "OPENAI_API_KEY"
 assert PROVIDER_REGISTRY[ProviderType.OPENAI_CODEX_RESPONSES]["env_key"] == "OPENAI_API_KEY"
 assert PROVIDER_REGISTRY[ProviderType.OPENAI_COMPLETIONS]["env_key"] == "OPENAI_API_KEY"
 def test_google_vertex_uses_service_account(self) -> None:
 from agents.llm.providers import PROVIDER_REGISTRY, CredentialType, ProviderType
 assert PROVIDER_REGISTRY[ProviderType.GOOGLE_VERTEX]["credential_type"] == CredentialType.SERVICE_ACCOUNT_JSON
class TestCreateProviderFactory:
 """Tests for the create_provider factory function."""
 def test_create_provider_with_enum_anthropic(self) -> None:
 from agents.llm.base import create_provider
 from agents.llm.claude import ClaudeProvider
 from agents.llm.providers import ProviderType
 provider = create_provider(ProviderType.ANTHROPIC)
 assert isinstance(provider, ClaudeProvider)
 def test_create_provider_with_enum_openai_completions(self) -> None:
 from agents.llm.base import create_provider
 from agents.llm.openai_completions import OpenAICompletionsProvider
 from agents.llm.providers import ProviderType
 provider = create_provider(ProviderType.OPENAI_COMPLETIONS, api_key="test-key", model="gpt-4o")
 assert isinstance(provider, OpenAICompletionsProvider)
 def test_create_provider_backward_compat_anthropic(self) -> None:
 from agents.llm.base import create_provider
 from agents.llm.claude import ClaudeProvider
 provider = create_provider("anthropic")
 assert isinstance(provider, ClaudeProvider)
 def test_create_provider_backward_compat_openai(self) -> None:
 """现有代码传入 "openai" 字符串，应映射到 OPENAI_COMPLETIONS。"""
 from agents.llm.base import create_provider
 from agents.llm.openai_completions import OpenAICompletionsProvider
 provider = create_provider("openai", api_key="test-key", model="gpt-4o")
 assert isinstance(provider, OpenAICompletionsProvider)
 def test_create_provider_openai_responses_not_implemented(self) -> None:
 from agents.llm.base import create_provider
 from agents.llm.providers import ProviderType
 with pytest.raises(NotImplementedError):
 create_provider(ProviderType.OPENAI_RESPONSES, api_key="test-key", model="gpt-4.1")
 def test_create_provider_google_not_implemented(self) -> None:
 from agents.llm.base import create_provider
 from agents.llm.providers import ProviderType
 with pytest.raises(NotImplementedError):
 create_provider(ProviderType.GOOGLE_VERTEX, api_key="test-key", model="gemini-2.5-flash")
 def test_create_provider_invalid_type(self) -> None:
 from agents.llm.base import create_provider
 with pytest.raises(ValueError):
 create_provider("invalid")
