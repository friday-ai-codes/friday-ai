"""implementation 核心工厂入口 —— build_chat_model thin wrapper。

单一入口把 ResolvedProviderConfig + model 字符串映射为 LangChain BaseChatModel，
capabilities 驱动 thinking / reasoning / max_tokens / timeout / base_url 分派，
api_key 用 pydantic.SecretStr 包装防泄漏（security mitigation-01/02 缓解）。

职责边界（明确不做的事）：
- 不调 LLM（仅构造对象；实测 init_chat_model 构造本身不触网 —— RESEARCH Pitfall I）
- 不做 tool binding（归 implementation plan Runner：model.bind_tools(tools)）
- 不计成本（归调用方 implementation AIAgentBaseNode + pricing.calculate_cost_v2）
- 不持有状态（纯函数；每次调用构造新 BaseChatModel 实例）

上游调用方：
- implementation plan LangChainAgentRunner._build_model()
- implementation plan FakeChatModel monkeypatch 正是替换此函数
- implementation AIAgentBaseNode / AIPromptNode / AIVariableExtractorNode

决策依据：
- context contract~10（签名 / prefix / SecretStr / thinking / reasoning /
  max_output / timeout / base_url / extra / mypy）
- context contract（output_version='v1' 锁死，抗 partner 静默改 default）
- RESEARCH Pattern 1 work item（权威模板，live venv 实证）
- PATTERNS §2 llm_factory pattern map
"""

from __future__ import annotations

import re
from typing import Any, Literal

import structlog
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from services.model_capabilities import ModelCapabilities, ModelCapabilitiesEntry
from services.provider_config import (
    PROVIDER_REGISTRY,
    ProviderType,
    ResolvedProviderConfig,
)

logger = structlog.get_logger(__name__)

# 正则兜底：OpenAI o 系列（o1/o2/.../o9/o4-mini）+ gpt-5（contract 第二重检测）
# capabilities.supports_reasoning 未覆盖的新模型时通过此正则识别
_REASONING_MODEL_PATTERN = re.compile(r"^(o[1-9]|o4-mini|gpt-5)(-.*)?$")


def content_to_text(content: Any) -> str:
    """LangChain message content → 纯文本。

    reasoning 模型（如经 anthropic 兼容代理的 deepseek/glm）返回的 content 是
    content_blocks 列表（reasoning + text），直接 str() 会得到 Python repr
    （单引号），下游 json.loads 必然失败——这里只拼接 text block。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content) if content is not None else ""


def build_chat_model(
    resolved: ResolvedProviderConfig,
    model: str,
    *,
    capabilities: ModelCapabilitiesEntry | None = None,
    max_output_tokens: int | None = None,
    timeout_seconds: float = 600.0,
    max_thinking_tokens: int | None = None,
    reasoning_effort: Literal["low", "medium", "high"] | None = None,
    streaming: bool = True,
    max_retries: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    seed: int | None = None,
) -> BaseChatModel:
    """单一工厂入口（contract）：capabilities 驱动 kwargs 分派。

    Args:
        resolved: implementation 四层解析后的 Provider 配置（含 api_key 明文 / base_url /
            provider_type / extra）。本函数立即把 api_key 包装为 SecretStr。
        model: 模型标识，如 "claude-sonnet-4-5-20250929" / "gpt-4o-mini" / "o1-mini"。
        capabilities: 模型能力与定价。None 时内部调 ModelCapabilities.get() 兜底查询
            （implementation P2 永不 raise）。
        max_output_tokens: 显式覆盖 capabilities.max_output_tokens；超过 capabilities
            时同步抛 ValueError（不静默截断，contract / work item）。
        timeout_seconds: 请求超时秒数。默认 600.0（覆盖 LangChain 60s 默认，避免工作
            流长任务误截；contract / work item）。
        max_thinking_tokens: Anthropic thinking budget。仅当 capabilities.supports_thinking=
            True 且非零时注入；其他 Provider 静默忽略 + logger.debug 记录
            （contract / work item）。
        reasoning_effort: OpenAI o 系列 / gpt-5 的 reasoning_effort 档位。命中 reasoning
            分支时透传；未命中时不附加（contract / work item）。
        streaming: 是否启用 streaming（大多数场景 True；title_service 单 turn 同步调用
            可 False）。
        temperature: 可选采样温度透传（默认 None = 不注入，行为与现状一致）。
            确定性场景（如仓库路由 Stage 1）传 0.0 固定 decode——注意 thinking
            分支（Anthropic 硬性 temperature=1）与 reasoning 分支（o 系列不接受
            temperature）的既有约束优先于此透传。
        top_p: 可选 nucleus sampling 透传（默认 None = 不注入）。reasoning 分支
            同样会剥除（OpenAI o 系列 API 约束）。
        seed: 可选采样种子透传（默认 None = 不注入）。仅 OpenAI / Ollama 构造
            支持；其他 Provider（Anthropic / Gemini）不支持时不传并记
            ``llm_decode_param_ignored`` debug 日志静默忽略——幂等主防线是
            输入哈希缓存 + 排列输出，decode 固定是第三道防线（105-RESEARCH）。

    Returns:
        BaseChatModel 子类实例（ChatAnthropic / ChatOpenAI / ChatGoogleGenerativeAI /
        ChatOllama 之一）。

    Raises:
        ValueError: max_output_tokens 超过 capabilities.max_output_tokens 时同步抛出
            （含关键字 "exceeds model limit"，provider / model 信息冗余日志）。
    """
    if capabilities is None:
        capabilities = ModelCapabilities.get(str(resolved.provider_type), model)

    prefix = PROVIDER_REGISTRY[resolved.provider_type].langchain_prefix  # contract

    kwargs: dict[str, Any] = {
        "api_key": SecretStr(resolved.api_key),  # contract 防泄漏（work item）
        "timeout": timeout_seconds,  # contract（work item）
        "streaming": streaming,
        "output_version": "v1",  # contract 锁死 v1 content blocks schema
    }
    if resolved.base_url:
        kwargs["base_url"] = resolved.base_url  # contract

    # 可选覆盖客户端重试次数。默认 None = 沿用 LangChain 默认（max_retries=2 → 最多 3 次）。
    # 对"快速失败即降级"的短任务（如仓库分级路由 Stage 1）传 0，避免超时后 3× 叠加空等。
    if max_retries is not None:
        kwargs["max_retries"] = max_retries

    # 可选 decode 参数透传（105-05 ROUTE-09）：默认 None = 不注入任何新键（零回归面）。
    # 注入点刻意放在 thinking / reasoning 分派之前——thinking 的 temperature=1
    # 硬性要求与 reasoning 的 temperature/top_p 剥除仍按既有约束优先生效。
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if seed is not None:
        # seed 仅 OpenAI（Chat/Responses）与 Ollama 构造支持；Anthropic / Gemini
        # 构造无 seed 形参，传入会构造失败——不传并 debug 记录，静默忽略。
        if resolved.provider_type in (
            ProviderType.OPENAI_CHAT,
            ProviderType.OPENAI_RESPONSES,
            ProviderType.OLLAMA,
        ):
            kwargs["seed"] = seed
        else:
            logger.debug(
                "llm_decode_param_ignored",
                param="seed",
                provider_type=str(resolved.provider_type),
                model=model,
                category="sampling",
                component="llm_factory",
            )

    # contract thinking 分派（work item，仅 Anthropic 系列支持）
    if capabilities.supports_thinking and max_thinking_tokens:
        kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": max_thinking_tokens,
        }
        kwargs["temperature"] = 1  # Anthropic thinking 硬性要求
        logger.info(
            "llm_factory_thinking_injected",
            provider=str(resolved.provider_type),
            model=model,
            budget_tokens=max_thinking_tokens,
        )
    elif max_thinking_tokens:
        # 其他 Provider 传了 max_thinking_tokens：静默忽略（v21.0 跨 Provider 契约）
        logger.debug(
            "llm_factory_thinking_param_ignored_by_provider",
            provider=str(resolved.provider_type),
            model=model,
        )

    # contract reasoning 分派（work item）—— capabilities + 正则双重检测
    is_reasoning = capabilities.supports_reasoning or bool(
        _REASONING_MODEL_PATTERN.match(model)
    )
    if is_reasoning:
        # reasoning model 不接受 temperature / top_p（OpenAI o 系列 API 约束）
        kwargs.pop("temperature", None)
        kwargs.pop("top_p", None)
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        logger.info(
            "llm_factory_reasoning_strip_temperature",
            provider=str(resolved.provider_type),
            model=model,
            reasoning_effort=reasoning_effort,
        )

    # contract max_output_tokens 校验 + 默认（work item）
    if (
        max_output_tokens is not None
        and max_output_tokens > capabilities.max_output_tokens
    ):
        raise ValueError(
            f"max_output_tokens {max_output_tokens} exceeds model limit "
            f"{capabilities.max_output_tokens} "
            f"(provider={resolved.provider_type}, model={model})"
        )
    effective_max_out = max_output_tokens or capabilities.max_output_tokens
    # langchain 1.x init_chat_model 自动把 max_tokens 映射到 Gemini 的 max_output_tokens
    kwargs["max_tokens"] = effective_max_out

    # contract Provider 特有字段透传（OpenAI organization / Responses API 区分）
    if resolved.extra.get("organization_id"):
        kwargs["organization"] = resolved.extra["organization_id"]
    if resolved.extra.get("use_responses_api"):
        kwargs["use_responses_api"] = True

    return init_chat_model(f"{prefix}:{model}", **kwargs)
