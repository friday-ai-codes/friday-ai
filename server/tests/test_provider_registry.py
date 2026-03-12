"""Tests for the Provider type system: ProviderType enum and PROVIDER_REGISTRY.
After Phase cleanup, create_provider and individual Provider classes
(ClaudeProvider, etc.) are deleted — SDK replaces LLM Provider layer.
"""
import pytest
class TestProviderTypeEnum:
 """Tests for ProviderType StrEnum."""
 def test_provider_type_enum_has_1_member(self) -> None:
 from services.provider_config import ProviderType
 assert len(ProviderType) == 1
 def test_provider_type_values_are_strings(self) -> None:
 from services.provider_config import ProviderType
 for member in ProviderType:
 assert isinstance(member.value, str)
 assert isinstance(member, str) # StrEnum 特性
 def test_provider_type_from_string(self) -> None:
 from services.provider_config import ProviderType
 assert ProviderType("anthropic") == ProviderType.ANTHROPIC
 def test_provider_type_invalid_raises_value_error(self) -> None:
 from services.provider_config import ProviderType
 with pytest.raises(ValueError):
 ProviderType("invalid-provider")
class TestProviderRegistry:
 """Tests for PROVIDER_REGISTRY metadata."""
 def test_registry_covers_all_providers(self) -> None:
 from services.provider_config import PROVIDER_REGISTRY, ProviderType
 assert set(PROVIDER_REGISTRY.keys) == set(ProviderType)
 def test_registry_metadata_fields(self) -> None:
 from services.provider_config import PROVIDER_REGISTRY
 required_fields = {"display_name", "api_format", "credential_type", "default_base_url", "env_key"}
 for provider_type, metadata in PROVIDER_REGISTRY.items:
 for field in required_fields:
 assert field in metadata, f"{provider_type}: missing field '{field}'"
