"""implementation 单元测试：agents.llm_factory.build_chat_model。

覆盖 Requirements：
- work item 单一工厂入口 + 5 Provider 前缀映射
- work item thinking 分派（仅 Anthropic）
- work item reasoning 分派（OpenAI o 系列 + Gemini 2.5，capabilities + 正则双检测）
- work item max_output_tokens 校验
- work item timeout 透传
- work item api_key SecretStr 脱敏（威胁 security mitigation-01/02）

测试策略（Pitfall I 实证）：init_chat_model 构造本身不触网，`--disable-socket` 安全；
无需 mock init_chat_model，直接构造验证字段注入。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel

from agents.llm_factory import build_chat_model
from services.model_capabilities import ModelCapabilitiesEntry
from services.provider_config import ProviderType, ResolvedProviderConfig


# ============================================================================
# Fixtures
# ============================================================================


def _make_resolved(
    provider_type: ProviderType,
    api_key: str = "fake-key-for-test",
    base_url: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ResolvedProviderConfig:
    """构造 ResolvedProviderConfig，简化测试模板（implementation dataclass 定义）。"""
    default_base_urls = {
        ProviderType.ANTHROPIC: "https://api.anthropic.com",
        ProviderType.OPENAI_RESPONSES: "https://api.openai.com/v1",
        ProviderType.OPENAI_CHAT: "https://api.openai.com/v1",
        ProviderType.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
        ProviderType.OLLAMA: "http://localhost:11434",
    }
    return ResolvedProviderConfig(
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url if base_url is not None else default_base_urls[provider_type],
        source="system",
        extra=extra or {},
    )


def _make_caps(
    *,
    max_input_tokens: int = 200_000,
    max_output_tokens: int = 8192,
    supports_thinking: bool = False,
    supports_reasoning: bool = False,
    provider: str = "anthropic",
    model: str = "test-model",
) -> ModelCapabilitiesEntry:
    """构造 ModelCapabilitiesEntry（六字段 Decimal 定价 + 四 supports 布尔）。"""
    return ModelCapabilitiesEntry(
        provider=provider,
        model=model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        input_cost_per_token=Decimal("0.000003"),
        output_cost_per_token=Decimal("0.000015"),
        supports_function_calling=True,
        supports_vision=True,
        supports_thinking=supports_thinking,
        supports_reasoning=supports_reasoning,
    )


# ============================================================================
# 单一工厂入口 + 5 Provider 前缀映射
# ============================================================================


@pytest.mark.parametrize(
    "provider_type,model,expected_cls",
    [
        (ProviderType.ANTHROPIC, "claude-sonnet-4-5-20250929", "ChatAnthropic"),
        (ProviderType.OPENAI_CHAT, "gpt-4o-mini", "ChatOpenAI"),
        (ProviderType.OPENAI_RESPONSES, "gpt-4o-mini", "ChatOpenAI"),
        (ProviderType.GEMINI, "gemini-2.0-flash", "ChatGoogleGenerativeAI"),
        (ProviderType.OLLAMA, "llama3.2", "ChatOllama"),
    ],
)
def test_init_chat_model_factory(
    provider_type: ProviderType, model: str, expected_cls: str
) -> None:
    """5 Provider 前缀映射后均能构造 BaseChatModel 子类实例。"""
    resolved = _make_resolved(provider_type)
    result = build_chat_model(resolved, model, timeout_seconds=5.0)
    assert isinstance(result, BaseChatModel)
    assert type(result).__name__ == expected_cls


def test_openai_responses_vs_openai_chat_distinction() -> None:
    """contract / use_responses_api=True 区分 Responses vs Chat。"""
    resolved_chat = _make_resolved(ProviderType.OPENAI_CHAT)
    resolved_resp = _make_resolved(
        ProviderType.OPENAI_RESPONSES, extra={"use_responses_api": True}
    )

    m_chat = build_chat_model(resolved_chat, "gpt-4o-mini", timeout_seconds=5.0)
    m_resp = build_chat_model(resolved_resp, "gpt-4o-mini", timeout_seconds=5.0)

    # Chat API：use_responses_api 为 None 或 False
    assert not getattr(m_chat, "use_responses_api", False)
    # Responses API：use_responses_api 为 True
    assert getattr(m_resp, "use_responses_api", False) is True


def test_output_version_v1_locked() -> None:
    """contract：显式传 output_version='v1'（不依赖 default，抗 partner 升级静默改 default）。"""
    resolved = _make_resolved(ProviderType.ANTHROPIC)
    model = build_chat_model(resolved, "claude-sonnet-4-5-20250929", timeout_seconds=5.0)
    assert getattr(model, "output_version", None) == "v1"


def test_base_url_passthrough() -> None:
    """contract：resolved.base_url 非空时透传到底层 kwargs。"""
    resolved = _make_resolved(
        ProviderType.ANTHROPIC, base_url="https://custom.moonshot.cn/anthropic"
    )
    model = build_chat_model(resolved, "claude-sonnet-4-5-20250929", timeout_seconds=5.0)
    # langchain-anthropic 把 base_url 存到 anthropic_api_url 字段
    bu = (
        getattr(model, "anthropic_api_url", None)
        or getattr(model, "base_url", None)
        or getattr(model, "openai_api_base", None)
    )
    assert bu == "https://custom.moonshot.cn/anthropic"


def test_organization_id_passthrough() -> None:
    """contract：resolved.extra['organization_id'] → kwargs['organization']。"""
    resolved = _make_resolved(
        ProviderType.OPENAI_CHAT, extra={"organization_id": "org-xyz123"}
    )
    model = build_chat_model(resolved, "gpt-4o-mini", timeout_seconds=5.0)
    org = getattr(model, "openai_organization", None) or getattr(
        model, "organization", None
    )
    assert org == "org-xyz123"


# ============================================================================
# thinking 分派（仅 Anthropic）
# ============================================================================


def test_thinking_anthropic_only() -> None:
    """supports_thinking=True + max_thinking_tokens=4096 时注入 thinking dict + temperature=1。"""
    resolved = _make_resolved(ProviderType.ANTHROPIC)
    caps = _make_caps(supports_thinking=True)
    model = build_chat_model(
        resolved,
        "claude-sonnet-4-5-20250929",
        capabilities=caps,
        max_thinking_tokens=4096,
        timeout_seconds=5.0,
    )
    thinking = getattr(model, "thinking", None)
    assert isinstance(thinking, dict)
    assert thinking.get("type") == "enabled"
    assert thinking.get("budget_tokens") == 4096
    # Anthropic 硬性要求 temperature=1
    assert getattr(model, "temperature", None) == 1


@pytest.mark.parametrize(
    "provider_type,model_name",
    [
        (ProviderType.OPENAI_CHAT, "gpt-4o-mini"),
        (ProviderType.GEMINI, "gemini-2.0-flash"),
        (ProviderType.OLLAMA, "llama3.2"),
    ],
)
def test_thinking_ignored_other_providers(
    provider_type: ProviderType, model_name: str
) -> None:
    """非 Anthropic Provider 传 max_thinking_tokens 静默忽略 + 不抛错。"""
    resolved = _make_resolved(provider_type)
    caps = _make_caps(supports_thinking=False)  # 其他 Provider capabilities 明确 False
    model = build_chat_model(
        resolved,
        model_name,
        capabilities=caps,
        max_thinking_tokens=4096,
        timeout_seconds=5.0,
    )
    # 不应注入 thinking 字段
    assert getattr(model, "thinking", None) in (None, {})


def test_thinking_requires_both_capability_and_tokens() -> None:
    """contract：supports_thinking=True 但 max_thinking_tokens=None 时不注入（严格两条件同真）。"""
    resolved = _make_resolved(ProviderType.ANTHROPIC)
    caps = _make_caps(supports_thinking=True)
    model = build_chat_model(
        resolved,
        "claude-sonnet-4-5-20250929",
        capabilities=caps,
        max_thinking_tokens=None,  # 缺第二条件
        timeout_seconds=5.0,
    )
    assert getattr(model, "thinking", None) in (None, {})


# ============================================================================
# reasoning 分派（OpenAI o 系列 / gpt-5 + Gemini 2.5）
# ============================================================================


@pytest.mark.parametrize("model_name", ["o1-mini", "o3-pro", "o4-mini", "gpt-5-turbo"])
def test_reasoning_strip_params(
    model_name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """reasoning model 下 temperature / top_p 被 pop（正则兜底）。

    断言策略（contract 实证）：直接构造对象无法断言"kwargs 内已被 pop"，因为
    langchain-openai 对 o 系列模型有自己的 default temperature=1.0 硬编码。本测试
    通过 structlog event `llm_factory_reasoning_strip_temperature` 的发射验证
    strip 分支命中，并确保 build 不抛错（与非 reasoning 分支的 kwargs 组装差异得到 log 证据）。
    """
    resolved = _make_resolved(ProviderType.OPENAI_CHAT)
    # capabilities 故意设 supports_reasoning=False，依赖正则兜底
    caps = _make_caps(supports_reasoning=False)
    model = build_chat_model(
        resolved,
        model_name,
        capabilities=caps,
        timeout_seconds=5.0,
    )
    assert isinstance(model, BaseChatModel)
    # structlog 事件必须发射（证明 strip 分支命中）
    captured = capsys.readouterr()
    assert "llm_factory_reasoning_strip_temperature" in captured.out


def test_reasoning_effort_passed_through() -> None:
    """reasoning_effort='high' 透传到底层 kwargs。"""
    resolved = _make_resolved(ProviderType.OPENAI_CHAT)
    caps = _make_caps(supports_reasoning=True)
    model = build_chat_model(
        resolved,
        "o1-mini",
        capabilities=caps,
        reasoning_effort="high",
        timeout_seconds=5.0,
    )
    effort = getattr(model, "reasoning_effort", None)
    assert effort == "high"


def test_regex_fallback_recognizes_o6() -> None:
    """capabilities.supports_reasoning=False 下正则兜底识别新 o6-preview（未覆盖模型）。"""
    resolved = _make_resolved(ProviderType.OPENAI_CHAT)
    caps = _make_caps(supports_reasoning=False)  # fixtures 未覆盖 o6
    # 不应抛错；正则 ^o[1-9] 匹配 o6
    model = build_chat_model(
        resolved,
        "o6-preview-2027",
        capabilities=caps,
        reasoning_effort="medium",
        timeout_seconds=5.0,
    )
    assert isinstance(model, BaseChatModel)
    # reasoning_effort 仍透传（证明走了 reasoning 分支）
    assert getattr(model, "reasoning_effort", None) == "medium"


# ============================================================================
# max_output_tokens 校验
# ============================================================================


def test_max_output_tokens_default() -> None:
    """不传 max_output_tokens 时默认用 capabilities.max_output_tokens。"""
    resolved = _make_resolved(ProviderType.ANTHROPIC)
    caps = _make_caps(max_output_tokens=8192)
    model = build_chat_model(
        resolved,
        "claude-sonnet-4-5-20250929",
        capabilities=caps,
        timeout_seconds=5.0,
    )
    max_tok = getattr(model, "max_tokens", None)
    assert max_tok == 8192


def test_max_output_exceeds_limit_raises() -> None:
    """max_output_tokens > capabilities.max_output_tokens 同步抛 ValueError。"""
    resolved = _make_resolved(ProviderType.ANTHROPIC)
    caps = _make_caps(max_output_tokens=8192)
    with pytest.raises(ValueError) as exc_info:
        build_chat_model(
            resolved,
            "claude-sonnet-4-5-20250929",
            capabilities=caps,
            max_output_tokens=999_999,
            timeout_seconds=5.0,
        )
    # 错误消息必含关键字（允许 planner 后续重构）
    assert "exceeds model limit" in str(exc_info.value)
    assert "999999" in str(exc_info.value) or "999_999" in str(exc_info.value)


# ============================================================================
# timeout 透传
# ============================================================================


def test_timeout_passthrough() -> None:
    """传 timeout_seconds=300.0 时底层 model.timeout 字段为 300.0（非 LangChain 60s 默认）。"""
    resolved = _make_resolved(ProviderType.ANTHROPIC)
    model = build_chat_model(
        resolved,
        "claude-sonnet-4-5-20250929",
        timeout_seconds=300.0,
    )
    # langchain-anthropic 字段名 default_request_timeout；其他 Provider 为 timeout
    timeout_val = (
        getattr(model, "default_request_timeout", None)
        or getattr(model, "timeout", None)
        or getattr(model, "request_timeout", None)
    )
    assert timeout_val == 300.0


# ============================================================================
# decode 参数透传（105-05 ROUTE-09：temperature / top_p / seed 可选形参）
# ============================================================================


def test_decode_params_passthrough_openai() -> None:
    """传 temperature/top_p/seed 时对应值到达 OpenAI 构造 kwargs（确定性 decode 固定）。"""
    resolved = _make_resolved(ProviderType.OPENAI_CHAT)
    model = build_chat_model(
        resolved,
        "gpt-4o-mini",
        timeout_seconds=5.0,
        temperature=0.0,
        top_p=1.0,
        seed=42,
    )
    assert getattr(model, "temperature", None) == 0.0
    assert getattr(model, "top_p", None) == 1.0
    assert getattr(model, "seed", None) == 42


def test_decode_params_passthrough_ollama_seed() -> None:
    """Ollama 构造支持 seed，透传生效。"""
    resolved = _make_resolved(ProviderType.OLLAMA)
    model = build_chat_model(
        resolved,
        "llama3.2",
        timeout_seconds=5.0,
        temperature=0.0,
        seed=42,
    )
    assert getattr(model, "temperature", None) == 0.0
    assert getattr(model, "seed", None) == 42


def test_decode_params_default_none_no_new_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认 None 时构造 kwargs 与现状一致——无 temperature/top_p/seed 新键（零回归面）。"""
    import agents.llm_factory as llm_factory_module

    captured: dict[str, Any] = {}
    original = llm_factory_module.init_chat_model

    def _capture(model_str: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return original(model_str, **kwargs)

    monkeypatch.setattr(llm_factory_module, "init_chat_model", _capture)
    resolved = _make_resolved(ProviderType.OPENAI_CHAT)
    build_chat_model(resolved, "gpt-4o-mini", timeout_seconds=5.0)
    assert "temperature" not in captured
    assert "top_p" not in captured
    assert "seed" not in captured


def test_seed_ignored_unsupported_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anthropic 构造不支持 seed：不注入构造 kwargs、构造不抛错（debug 静默忽略）。"""
    import agents.llm_factory as llm_factory_module

    captured: dict[str, Any] = {}
    original = llm_factory_module.init_chat_model

    def _capture(model_str: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return original(model_str, **kwargs)

    monkeypatch.setattr(llm_factory_module, "init_chat_model", _capture)
    resolved = _make_resolved(ProviderType.ANTHROPIC)
    model = build_chat_model(
        resolved,
        "claude-sonnet-4-5-20250929",
        # 显式非 reasoning capabilities：隔离 reasoning 分支的 temperature/top_p 剥除
        capabilities=_make_caps(supports_reasoning=False),
        timeout_seconds=5.0,
        temperature=0.0,
        top_p=1.0,
        seed=42,
    )
    assert isinstance(model, BaseChatModel)
    assert "seed" not in captured
    # temperature / top_p 各 Provider 通用，仍透传
    assert captured.get("temperature") == 0.0
    assert captured.get("top_p") == 1.0


# ============================================================================
# api_key SecretStr 脱敏（security mitigation-01/02）
# ============================================================================


def test_secretstr_wrapping() -> None:
    """api_key 包装为 SecretStr → repr 输出不含明文。"""
    plaintext_key = "sk-ant-real-fake-key-for-test-do-not-leak"
    resolved = _make_resolved(ProviderType.ANTHROPIC, api_key=plaintext_key)
    model = build_chat_model(
        resolved, "claude-sonnet-4-5-20250929", timeout_seconds=5.0
    )
    # repr 必不含明文（SecretStr.__repr__ 输出 '**********'）
    assert plaintext_key not in repr(model)
    # str 也不应含明文
    assert plaintext_key not in str(model)


def test_no_api_key_leak_in_exception() -> None:
    """work item + security mitigation-01：max_output_tokens 超限异常消息不含 api_key 明文。"""
    plaintext_key = "sk-ant-real-secret-key-work item-LEAK"
    resolved = _make_resolved(ProviderType.ANTHROPIC, api_key=plaintext_key)
    caps = _make_caps(max_output_tokens=8192)
    with pytest.raises(ValueError) as exc_info:
        build_chat_model(
            resolved,
            "claude-sonnet-4-5-20250929",
            capabilities=caps,
            max_output_tokens=999_999,
            timeout_seconds=5.0,
        )
    # 异常消息必不含明文 api_key
    assert plaintext_key not in str(exc_info.value)
    assert "sk-ant-real" not in str(exc_info.value)
