"""implementation：PROVIDER_REGISTRY 5 Provider 契约测试 + Pydantic credential_schema 脱敏测试。

覆盖 Requirement: contract（5 Provider 元数据形状契约）。
威胁参考: security mitigation（凭证 repr 泄漏）/ security mitigation（ValidationError 回显明文）。

本文件 implementation 完全重写：
- 旧版断言 `len(ProviderType) == 1`（implementation 遗留），在 5 Provider 扩展下自然失效。
- 新版覆盖 7 个 unit test + TokenUsage 5 个 unit test（合并同文件以减少新建开销）。
"""

from __future__ import annotations

import dataclasses

import pytest


# =============================================================================
# Test 1-7: PROVIDER_REGISTRY 5 Provider + Pydantic credential_schema 契约
# =============================================================================


def test_registry_contains_five_providers() -> None:
    """Test 1：PROVIDER_REGISTRY 键集合精确为 5 种 ProviderType。"""
    from services.provider_config import PROVIDER_REGISTRY, ProviderType

    assert set(PROVIDER_REGISTRY.keys()) == {
        ProviderType.ANTHROPIC,
        ProviderType.OPENAI_RESPONSES,
        ProviderType.OPENAI_CHAT,
        ProviderType.GEMINI,
        ProviderType.OLLAMA,
    }


def test_registry_metadata_dataclass_frozen() -> None:
    """Test 2：ProviderMetadata 是 @dataclass(frozen=True)，改字段抛 FrozenInstanceError。"""
    from services.provider_config import PROVIDER_REGISTRY, ProviderMetadata, ProviderType

    meta = PROVIDER_REGISTRY[ProviderType.ANTHROPIC]
    assert isinstance(meta, ProviderMetadata)
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.display_name = "hacked"  # type: ignore[misc]


def test_registry_langchain_prefix_populated() -> None:
    """Test 3：5 个 entry 的 langchain_prefix 与 implementation init_chat_model 预期对齐。"""
    from services.provider_config import PROVIDER_REGISTRY, ProviderType

    expected = {
        ProviderType.ANTHROPIC: "anthropic",
        ProviderType.OPENAI_RESPONSES: "openai",
        ProviderType.OPENAI_CHAT: "openai",
        ProviderType.GEMINI: "google_genai",
        ProviderType.OLLAMA: "ollama",
    }
    for pt, prefix in expected.items():
        assert PROVIDER_REGISTRY[pt].langchain_prefix == prefix


def test_credential_schema_secretstr_repr() -> None:
    """Test 4 (security mitigation)：SecretStr 字段在 repr 时显示 **********，不泄漏 api_key 明文。"""
    from services.provider_config import AnthropicCredentialSchema

    c = AnthropicCredentialSchema(api_key="sk-ant-leaktest12345")  # type: ignore[arg-type]
    assert repr(c.api_key) == "SecretStr('**********')"
    assert "sk-ant-leaktest" not in repr(c)


def test_credential_schema_validate_decrypted_config() -> None:
    """Test 5：4 个 schema 各自 .model_validate({合法字典}) 成功；model_dump_json 默认排除 api_key 明文。"""
    from services.provider_config import (
        AnthropicCredentialSchema,
        GeminiCredentialSchema,
        OllamaCredentialSchema,
        OpenAICredentialSchema,
    )

    anth = AnthropicCredentialSchema.model_validate({"api_key": "sk-ant-test"})
    assert anth.base_url == "https://api.anthropic.com"

    oai = OpenAICredentialSchema.model_validate(
        {"api_key": "sk-openai-test", "organization_id": "org-1"}
    )
    assert oai.organization_id == "org-1"
    assert oai.base_url == "https://api.openai.com/v1"

    gem = GeminiCredentialSchema.model_validate({"api_key": "AIza-test"})
    assert gem.api_key.get_secret_value() == "AIza-test"

    oll = OllamaCredentialSchema.model_validate({"base_url": "http://localhost:11434"})
    assert oll.bearer_token is None

    # model_dump_json 默认用 SecretStr repr 输出脱敏值，不会回显明文
    dumped = anth.model_dump_json()
    assert "sk-ant-test" not in dumped


def test_credential_schema_hide_input_in_errors_T225_05() -> None:
    """Test 6 (security mitigation)：故意触发 ValidationError（base_url 类型错），断言消息不含 api_key 明文。"""
    from pydantic import ValidationError

    from services.provider_config import OpenAICredentialSchema

    with pytest.raises(ValidationError) as exc_info:
        OpenAICredentialSchema.model_validate(
            {"api_key": "fixture-api-key-value", "base_url": 12345}
        )
    message = str(exc_info.value)
    # hide_input_in_errors=True 下 Pydantic 不再 echo input_value
    assert "fixture-api-key-value" not in message


def test_provider_type_strenum_values() -> None:
    """Test 7：ProviderType 枚举值即字符串，直接可存 DB CharField（避免字符串漂移）。"""
    from services.provider_config import ProviderType

    assert ProviderType.ANTHROPIC == "anthropic"
    assert ProviderType.OPENAI_RESPONSES == "openai_responses"
    assert ProviderType.OPENAI_CHAT == "openai_chat"
    assert ProviderType.GEMINI == "gemini"
    assert ProviderType.OLLAMA == "ollama"


# =============================================================================
# TokenUsage TypedDict 5 个 unit test（Task 2 合并到本文件）
# =============================================================================


def test_token_usage_import() -> None:
    """Test 1：TokenUsage TypedDict 可从 agents.types 导入。"""
    from agents.types import TokenUsage

    assert TokenUsage is not None


def test_token_usage_construct_with_fields() -> None:
    """Test 2：构造含 input/output 字段的 TokenUsage 成功。"""
    from agents.types import TokenUsage

    usage: TokenUsage = {"input": 100, "output": 50}
    assert usage["input"] == 100
    assert usage["output"] == 50


def test_token_usage_empty_dict_valid() -> None:
    """Test 3：空字典也合法（total=False，字段全部可选）。"""
    from agents.types import TokenUsage

    usage: TokenUsage = {}
    assert usage == {}


def test_token_usage_field_set_matches_spec() -> None:
    """Test 4：字段集合精确为 {input, cached_input, cache_creation, output, reasoning, vision}。"""
    from agents.types import TokenUsage

    expected_fields = {
        "input",
        "cached_input",
        "cache_creation",
        "output",
        "reasoning",
        "vision",
    }
    assert set(TokenUsage.__annotations__.keys()) == expected_fields


def test_token_usage_is_typed_dict() -> None:
    """Test 5：TokenUsage 是 typing.TypedDict 子类。"""
    from agents.types import TokenUsage

    # TypedDict 的标志属性：__total__（total=False 时为 False）
    assert hasattr(TokenUsage, "__annotations__")
    assert TokenUsage.__total__ is False
