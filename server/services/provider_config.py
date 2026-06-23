"""ProviderConfigService — 四层配置优先级解析和凭据验证。

实现节点级 > 对话级 > 项目级 > 系统级的 Provider 配置解析，
被 ConversationService 和 AIAgentBaseNode 共用。

ProviderType / ApiFormat / CredentialType / PROVIDER_REGISTRY 从
agents.llm.providers 迁移至此，避免对已删除模块的依赖。

implementation（v21.0）：扩展为 5 种 ProviderType（anthropic / openai_responses /
openai_chat / gemini / ollama），ProviderMetadata 迁移为 @dataclass(frozen=True)
（Pitfall 26 规避），新增 4 个 Pydantic credential_schema 类统一承载凭证字段
校验与脱敏（SecretStr + ConfigDict(hide_input_in_errors=True)，缓解
security mitigation / security mitigation 凭证泄漏威胁）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Union
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

# implementation（contract/contract）：SettingKeys.ANTHROPIC_* 4 常量 +
# SettingKeys.DEFAULT_PROVIDER_TYPE 常量硬删；provider_config 不再依赖 SystemSetting 行。

if TYPE_CHECKING:
    from system.models import ProviderCredential

# === Provider 类型定义（从 agents.llm.providers 迁移） ===


class ProviderType(StrEnum):
    """LLM Provider 类型枚举。值为小写字符串，可直接存储到 DB CharField。"""

    ANTHROPIC = "anthropic"
    OPENAI_RESPONSES = "openai_responses"
    OPENAI_CHAT = "openai_chat"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class CredentialType(StrEnum):
    """凭据类型枚举。"""

    API_KEY = "api_key"
    API_KEY_WITH_ORG = "api_key_with_org"
    API_KEY_OPTIONAL = "api_key_optional"


class ApiFormat(StrEnum):
    """API 协议格式枚举，决定 implementation Runner 工厂分派路由。"""

    ANTHROPIC = "anthropic"
    OPENAI_RESPONSES = "openai_responses"
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    GEMINI = "gemini"
    OLLAMA_NATIVE = "ollama_native"


# === Pydantic credential_schema 类（implementation 决策 1） ===
#
# 每个类必须 model_config = ConfigDict(hide_input_in_errors=True)
# —— 这是 security mitigation 缓解的强制契约，防止 ValidationError.errors() 中
# 回显原始 api_key 明文。
# SecretStr 字段在 repr/log 时自动返回 "**********"，缓解 security mitigation。


class AnthropicCredentialSchema(BaseModel):
    """Anthropic 凭证字段。"""

    model_config = ConfigDict(hide_input_in_errors=True)

    api_key: SecretStr = Field(..., description="Anthropic API Key（sk-ant-...）")
    base_url: str = Field(
        default="https://api.anthropic.com",
        description="覆盖默认端点（支持 Anthropic 协议格式的兼容端点）",
    )


class OpenAICredentialSchema(BaseModel):
    """OpenAI 凭证字段（Responses API 与 Chat Completions 共享）。"""

    model_config = ConfigDict(hide_input_in_errors=True)

    api_key: SecretStr = Field(..., description="OpenAI API Key（sk-...）")
    base_url: str = Field(
        default="https://api.openai.com/v1",
        description="覆盖默认端点（支持 OpenAI 协议格式的兼容端点）",
    )
    organization_id: str | None = Field(
        default=None,
        description="OpenAI organization ID（可选，多 org 账户用）",
    )


class GeminiCredentialSchema(BaseModel):
    """Gemini 凭证字段（AI Studio 路径）。"""

    model_config = ConfigDict(hide_input_in_errors=True)

    api_key: SecretStr = Field(..., description="Google AI Studio API Key（AIza...）")


class OllamaCredentialSchema(BaseModel):
    """Ollama 凭证字段。"""

    model_config = ConfigDict(hide_input_in_errors=True)

    base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama 实例 URL（通常 localhost；远程时用 HTTPS）",
    )
    bearer_token: SecretStr | None = Field(
        default=None,
        description="反向代理 / 网关鉴权用（OpenWebUI / Cloudflare Tunnel），本地部署通常留空",
    )


@dataclass(frozen=True)
class ProviderMetadata:
    """Provider 元数据。

    @dataclass(frozen=True) 防止 Pitfall 26（TypedDict total= 矛盾）。
    新增字段必须带默认值以避免破坏已有字面量。
    """

    display_name: str
    api_format: ApiFormat
    credential_type: CredentialType
    default_base_url: str
    env_key: str
    langchain_prefix: str  # implementation init_chat_model 前缀（本 phase 仅声明字符串）
    credential_schema: type[BaseModel]  # Pydantic 类引用，service 层 .model_validate() 入口
    health_check_path: str = "/v1/models"  # contract 健康检查端点路径（D4 锁定，registry 集中管理）
    health_check_method: str = "GET"
    supports_thinking: bool = False  # 仅 Anthropic
    supports_reasoning: bool = False  # OpenAI o1/o3/gpt-5 + Gemini 2.5
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True


PROVIDER_REGISTRY: dict[ProviderType, ProviderMetadata] = {
    ProviderType.ANTHROPIC: ProviderMetadata(
        display_name="Anthropic Claude",
        api_format=ApiFormat.ANTHROPIC,
        credential_type=CredentialType.API_KEY,
        default_base_url="https://api.anthropic.com",
        env_key="ANTHROPIC_API_KEY",
        langchain_prefix="anthropic",
        credential_schema=AnthropicCredentialSchema,
        health_check_path="/v1/messages/count_tokens",
        health_check_method="POST",
        supports_thinking=True,
        supports_vision=True,
    ),
    ProviderType.OPENAI_RESPONSES: ProviderMetadata(
        display_name="OpenAI (Responses API)",
        api_format=ApiFormat.OPENAI_RESPONSES,
        credential_type=CredentialType.API_KEY_WITH_ORG,
        default_base_url="https://api.openai.com/v1",
        env_key="OPENAI_API_KEY",
        langchain_prefix="openai",
        credential_schema=OpenAICredentialSchema,
        health_check_path="/models",
        supports_reasoning=True,
        supports_vision=True,
    ),
    ProviderType.OPENAI_CHAT: ProviderMetadata(
        display_name="OpenAI (Chat Completions)",
        api_format=ApiFormat.OPENAI_CHAT_COMPLETIONS,
        credential_type=CredentialType.API_KEY_WITH_ORG,
        default_base_url="https://api.openai.com/v1",
        env_key="OPENAI_API_KEY",
        langchain_prefix="openai",
        credential_schema=OpenAICredentialSchema,
        health_check_path="/models",
        supports_reasoning=True,
        supports_vision=True,
    ),
    ProviderType.GEMINI: ProviderMetadata(
        display_name="Google Gemini",
        api_format=ApiFormat.GEMINI,
        credential_type=CredentialType.API_KEY,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        env_key="GOOGLE_API_KEY",
        langchain_prefix="google_genai",
        credential_schema=GeminiCredentialSchema,
        health_check_path="/models",
        supports_reasoning=True,
        supports_vision=True,
    ),
    ProviderType.OLLAMA: ProviderMetadata(
        display_name="Ollama",
        api_format=ApiFormat.OLLAMA_NATIVE,
        credential_type=CredentialType.API_KEY_OPTIONAL,
        default_base_url="http://localhost:11434",
        env_key="",
        langchain_prefix="ollama",
        credential_schema=OllamaCredentialSchema,
        health_check_path="/api/tags",
    ),
}

logger = structlog.get_logger(__name__)


class ProviderConfigError(Exception):
    """Provider 配置解析错误。"""


@dataclass
class ResolvedProviderConfig:
    """配置解析结果。implementation 扩展 credential_id / extra 字段（向后兼容默认值）。"""

    provider_type: ProviderType
    api_key: str  # 凭据值（API Key）
    base_url: str  # 从 PROVIDER_REGISTRY 获取
    source: str  # "node" | "conversation" | "project" | "system"

    # implementation 新增（默认值保持向后兼容；ChatAnthropicRunner 等现有调用方零改动）
    credential_id: UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # 并发治理（CONC-02）：该凭证的 LLM 并发上限（0=不限）。由解析时从
    # ProviderCredential.max_concurrency 透传，供 LLM 调用 chokepoint 按凭证限流。
    max_concurrency: int = 0


@dataclass(frozen=True)
class ProviderMissingError:
    """凭证解析失败的结构化错误（contract）。

    返回给上层（implementation API 层 / implementation 工作流节点）的 Result 模式错误对象。
    code 字段 Literal 锁定，前端可基于此分支转 HTTP 4xx + i18n 提示。
    """

    code: Literal["provider_credential_missing"] = "provider_credential_missing"
    missing_provider: str = ""  # e.g. "openai_responses" / "anthropic"
    recommended_action: str = ""  # e.g. "请在系统设置添加 OpenAI 凭证"
    source_attempted: str = ""  # 四层中哪一层断流："system" / "project" / "conversation" / "node"


# Result 模式 Union 类型（implementation / 229 调用方 isinstance 分派）
AResolveResult = Union[ResolvedProviderConfig, ProviderMissingError]


# ============================================================================
# implementation contract contract：四层 Provider 解析 Inspector dataclass
# ============================================================================


@dataclass
class ResolutionChainEntry:
    """四层 Provider 解析链中的单层条目。

    用于前端 ResolvedSourceBadge.vue 的 tooltip 展开优先级链表；
    每层记录该层原始凭证的可见字段（非活跃凭证清为 None），以及本层是否为 winning source。

    implementation contract contract 契约。
    """

    layer: Literal["node", "conversation", "project", "system"]
    provider_type: str | None
    model: str | None
    credential_id: UUID | None
    active: bool


@dataclass
class ResolvedProviderChain:
    """ProviderConfigService.aresolve_with_chain 返回值。

    winning 字段为最终解析的 ResolvedProviderConfig（同 aresolve_or_error）；
    chain 字段为固定 4 层（顺序：node → conversation → project → system）的列表，
    前端据此渲染完整优先级链 tooltip + winning source 加粗标识。
    """

    winning: ResolvedProviderConfig
    chain: list[ResolutionChainEntry]


def _parse_uuid_or_none(value: Any) -> UUID | None:
    """字符串 / UUID 实例 / None → UUID | None（容错）。"""
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


# ============================================================================
# v8.1 SettingKeys.ANTHROPIC_* 硬删后 legacy 兼容层
# 从 ProviderCredential(scope=system, provider_type=anthropic, name=default) 读配置。
# ============================================================================


async def aget_legacy_anthropic_config() -> dict[str, str]:
    """implementation 替代 SettingKeys.ANTHROPIC_* 读取路径。

    从系统级 default anthropic ProviderCredential 读 api_key / base_url / default_model。
    若无凭证返回空字符串字典（keys 固定）。供既有 legacy 路径平滑过渡使用。

    Returns:
        {
            "api_key": str,  # 解密后的 Anthropic API key，可能为空
            "base_url": str,
            "default_model": str,
            "small_model": str,  # 与 SettingKeys.ANTHROPIC_SMALL_MODEL 兼容；
                                # ProviderCredential 无 small_model 列，返回空字符串。
        }
    """
    from system.models import ProviderCredential

    empty_result = {
        "api_key": "",
        "base_url": "",
        "default_model": "",
        "small_model": "",
    }

    # is_default 优先 + name='default' 回退（向后兼容未迁移库）
    try:
        cred = await ProviderCredential.objects.aget(
            scope="system",
            provider_type="anthropic",
            is_default=True,
            is_active=True,
        )
    except ProviderCredential.DoesNotExist:
        try:
            cred = await ProviderCredential.objects.aget(
                scope="system",
                provider_type="anthropic",
                name="default",
                is_active=True,
            )
        except ProviderCredential.DoesNotExist:
            return empty_result

    try:
        raw_cfg = cred.get_decrypted_config()
        schema_cls = PROVIDER_REGISTRY[ProviderType.ANTHROPIC].credential_schema
        validated = schema_cls.model_validate(raw_cfg)
    except (ValidationError, Exception):  # noqa: BLE001
        return empty_result

    api_key_value = ""
    if hasattr(validated, "api_key") and validated.api_key is not None:
        secret = validated.api_key
        api_key_value = (
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        )
    base_url = getattr(validated, "base_url", "") or cred.base_url or ""
    default_model = cred.default_model or ""

    return {
        "api_key": api_key_value,
        "base_url": base_url,
        "default_model": default_model,
        "small_model": "",  # ProviderCredential 无此字段
    }


# ============================================================================
# Claude Code 编码容器配置：Claude Code 编码容器专属配置
# 存储于 SystemSetting(key=claude_code_config)，value 为 JSON：
#   {"credential_id": str, "model_mapping": {"opus": str, "sonnet": str, "haiku": str}}
# ============================================================================

CLAUDE_CODE_MODEL_TIERS = ("opus", "sonnet", "haiku")


def _empty_claude_code_config() -> dict[str, Any]:
    return {
        "credential_id": "",
        "model_mapping": {tier: "" for tier in CLAUDE_CODE_MODEL_TIERS},
    }


def _bound_model_ids_from_credential(credential: "ProviderCredential") -> set[str]:
    """从 ProviderCredential.available_models 读取已绑定模型 ID，兼容历史 string[]。"""
    model_ids: set[str] = set()
    raw_models = credential.available_models or []
    if not isinstance(raw_models, list):
        return model_ids
    for item in raw_models:
        if isinstance(item, str):
            model_id = item.strip()
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
        else:
            model_id = ""
        if model_id:
            model_ids.add(model_id)
    return model_ids


async def aget_claude_code_config() -> dict[str, Any]:
    """读取 Claude Code 配置。缺省返回空配置（keys 固定）。

    Returns:
        {"credential_id": str, "model_mapping": {"opus": str, "sonnet": str, "haiku": str}}
    """
    import json as _json

    from system.models import SettingKeys, SystemSetting

    try:
        setting = await SystemSetting.objects.aget(key=SettingKeys.CLAUDE_CODE_CONFIG)
    except SystemSetting.DoesNotExist:
        return _empty_claude_code_config()

    if not setting.value:
        return _empty_claude_code_config()
    try:
        parsed = _json.loads(setting.value)
    except (ValueError, TypeError):
        return _empty_claude_code_config()
    if not isinstance(parsed, dict):
        return _empty_claude_code_config()

    mapping_raw = parsed.get("model_mapping")
    mapping = {
        tier: (mapping_raw.get(tier, "") if isinstance(mapping_raw, dict) else "")
        for tier in CLAUDE_CODE_MODEL_TIERS
    }
    return {
        "credential_id": str(parsed.get("credential_id") or ""),
        "model_mapping": mapping,
    }


async def aset_claude_code_config(
    credential_id: str | None,
    model_mapping: dict[str, str],
) -> dict[str, Any]:
    """写入 Claude Code 配置。

    若 credential_id 非空，校验对应 ProviderCredential 存在且 is_active。
    model_mapping 仅保留 opus/sonnet/haiku 三键（其余忽略）。

    Raises:
        ProviderConfigError: credential_id 指向不存在 / 已禁用凭证。
    """
    import json as _json

    from system.models import ProviderCredential, SettingKeys, SystemSetting

    cred_id_str = str(credential_id or "").strip()
    if cred_id_str:
        parsed_id = _parse_uuid_or_none(cred_id_str)
        if parsed_id is None:
            raise ProviderConfigError("credential_id 不是合法 UUID")
        try:
            credential = await ProviderCredential.objects.aget(
                id=parsed_id, is_active=True
            )
        except ProviderCredential.DoesNotExist:
            raise ProviderConfigError("所选凭证不存在或已禁用")
        if credential.provider_type != ProviderType.ANTHROPIC.value:
            raise ProviderConfigError("Claude Code 只能选择 Anthropic 类型 Provider 凭证")

        model_ids = _bound_model_ids_from_credential(credential)
        if not model_ids:
            raise ProviderConfigError("所选凭证没有模型列表，请先添加或刷新模型")

        # 校验时剥掉 Claude Code 的 `[1m]` 类上下文声明后缀再比对凭证模型列表
        # （存储仍存带后缀原文，dispatch 时直通容器 env 由 Claude Code 解析）。
        from services.model_capabilities import strip_context_suffix

        base_model_ids = {strip_context_suffix(m) for m in model_ids}
        invalid_models = [
            model
            for model in (
                str(model_mapping.get(tier, "") or "").strip()
                for tier in CLAUDE_CODE_MODEL_TIERS
            )
            if model and strip_context_suffix(model) not in base_model_ids
        ]
        if invalid_models:
            raise ProviderConfigError(
                "模型不在所选凭证的模型列表中: " + ", ".join(invalid_models)
            )

    clean_mapping = (
        {
            tier: str(model_mapping.get(tier, "") or "").strip()
            for tier in CLAUDE_CODE_MODEL_TIERS
        }
        if cred_id_str
        else {tier: "" for tier in CLAUDE_CODE_MODEL_TIERS}
    )
    payload = {"credential_id": cred_id_str, "model_mapping": clean_mapping}

    await SystemSetting.objects.aupdate_or_create(
        key=SettingKeys.CLAUDE_CODE_CONFIG,
        defaults={"value": _json.dumps(payload, ensure_ascii=False), "is_encrypted": False},
    )
    logger.info(
        "claude_code_config_updated",
        has_credential=bool(cred_id_str),
        mapped_tiers=[t for t, v in clean_mapping.items() if v],
    )
    return payload


async def aget_claude_code_runtime_config() -> dict[str, str]:
    """解析 Claude Code 运行时配置（供 dispatch / PR 草稿共用）。

    优先用 CC 专属配置选定的凭证 + 三档模型映射；未配置 credential_id 时回退
    aget_legacy_anthropic_config()（系统默认 anthropic 凭证），保持旧行为。

    Returns:
        {
            "api_key": str, "base_url": str,
            "opus_model": str, "sonnet_model": str, "haiku_model": str,
            "default_model": str,  # 主模型兜底（sonnet 档 or 凭证 default_model）
        }
    """
    cc = await aget_claude_code_config()
    cred_id = _parse_uuid_or_none(cc.get("credential_id"))
    mapping = cc.get("model_mapping", {})

    if cred_id is not None:
        cred = await _fetch_credential_by_id(cred_id)
        if cred is not None:
            try:
                raw_cfg = cred.get_decrypted_config()
                schema_cls = PROVIDER_REGISTRY[
                    _parse_provider_type(str(cred.provider_type))
                ].credential_schema
                validated = schema_cls.model_validate(raw_cfg)
            except (ValidationError, Exception):  # noqa: BLE001
                validated = None
            api_key = ""
            base_url = ""
            if validated is not None:
                secret = getattr(validated, "api_key", None)
                if secret is not None:
                    api_key = (
                        secret.get_secret_value()
                        if hasattr(secret, "get_secret_value")
                        else str(secret)
                    )
                base_url = getattr(validated, "base_url", "") or cred.base_url or ""
            opus = mapping.get("opus", "") or ""
            sonnet = mapping.get("sonnet", "") or ""
            haiku = mapping.get("haiku", "") or ""
            return {
                "api_key": api_key,
                "base_url": base_url,
                "opus_model": opus,
                "sonnet_model": sonnet,
                "haiku_model": haiku,
                "default_model": sonnet or cred.default_model or "",
            }

    # 回退 legacy 系统默认 anthropic 凭证
    legacy = await aget_legacy_anthropic_config()
    return {
        "api_key": legacy["api_key"],
        "base_url": legacy["base_url"],
        "opus_model": "",
        "sonnet_model": "",
        "haiku_model": legacy["small_model"],
        "default_model": legacy["default_model"],
    }


# implementation（contract/contract）：ENV_KEY_TO_SETTING_KEY + SettingKeys.ANTHROPIC_*
# 全部硬删；legacy 路径走 aget_legacy_anthropic_config() 读 ProviderCredential。


# implementation（contract/contract）：_get_setting_value_sync/_get_setting_value_async 硬删。
# provider_config 不再读 SystemSetting 行；凭证解析全部走 ProviderCredential 表。


def _resolve_provider_type(
    node_config: dict[str, Any] | None,
    conversation: Any | None,
    project: Any | None,
    get_setting: Any,  # 保留签名向后兼容；implementation 不再读 SettingKeys.DEFAULT_PROVIDER_TYPE
) -> tuple[ProviderType, str]:
    """从四层配置中解析 provider_type。

    implementation（contract/contract）：v8.1 SettingKeys.DEFAULT_PROVIDER_TYPE +
    Conversation.provider_type + Project.default_provider_type 硬删后，
    provider_type 由 ProviderCredential 层承载；本函数仅按 node_config 层探测，
    其他层返回默认 ANTHROPIC（由 _resolve_credential_async 走 ProviderCredential FK 四层）。
    """
    # 1. 节点级（node_config 仍可携带 provider_type 显式覆盖）
    if node_config and node_config.get("provider_type"):
        pt_str = node_config["provider_type"]
        return _parse_provider_type(pt_str), "node"

    # 2-4 层：v8.1 legacy 字段已硬删，provider_type 由 ProviderCredential 承载
    # 默认使用 Anthropic（最终 provider_type 由 _resolve_credential_async 查到的
    # credential.provider_type 决定，此处仅兜底 system 层未命中场景）
    return ProviderType.ANTHROPIC, "system"


def _parse_provider_type(value: str) -> ProviderType:
    """将字符串转换为 ProviderType 枚举。"""
    try:
        return ProviderType(value)
    except ValueError:
        raise ProviderConfigError(f"不支持的 Provider 类型: {value}")


# === implementation contract 重构：纯函数 + IO 分层（Pitfall 28 sync/async drift 规避）===


async def _fetch_credential_by_id(credential_id: UUID) -> "ProviderCredential | None":
    """IO 函数：异步查单行凭证（按 UUID）。"""
    from system.models import ProviderCredential

    try:
        return await ProviderCredential.objects.aget(
            id=credential_id, is_active=True
        )
    except ProviderCredential.DoesNotExist:
        return None


async def _fetch_system_default_credential(
    provider_type: ProviderType,
) -> "ProviderCredential | None":
    """IO 函数：异步查系统级 default 凭证。

    优先按 is_default=True 定位（新口径）；捕获 DoesNotExist 后回退旧逻辑
    name="default"（向后兼容尚未跑 0007 迁移的库），仍 miss 返回 None。
    """
    from system.models import ProviderCredential

    try:
        return await ProviderCredential.objects.aget(
            scope="system",
            provider_type=str(provider_type),
            is_default=True,
            is_active=True,
        )
    except ProviderCredential.DoesNotExist:
        # 回退：未迁移库仍靠 name='default' 定位
        try:
            return await ProviderCredential.objects.aget(
                scope="system",
                provider_type=str(provider_type),
                name="default",
                is_active=True,
            )
        except ProviderCredential.DoesNotExist:
            return None


async def _resolve_credential_async(
    provider_type: ProviderType,
    node_config: dict[str, Any] | None,
    conversation: Any | None,
    project: Any | None,
) -> tuple["ProviderCredential | None", str]:
    """纯逻辑函数：按四层优先级查 ProviderCredential。

    返回 (credential, source_attempted)。
    implementation / 229 引入 conversation.provider_credential_id /
    project.default_provider_credential_id 字段后自动启用。
    """
    # 1. 节点级 FK
    if node_config and node_config.get("provider_credential_id"):
        cred = await _fetch_credential_by_id(
            UUID(str(node_config["provider_credential_id"]))
        )
        if cred is not None:
            return cred, "node"
    # 2. 对话级 FK（implementation/229 加字段后启用）
    #    注意：Django ORM 对 FK 字段 `provider_credential_id` 生成实际 DB 列
    #    `provider_credential_id_id`；访问字段名会返回 ProviderCredential 实例
    #    （触发同步查询，async 上下文会 SynchronousOnlyOperation）。
    #    这里读 `_id` 列直接拿 UUID，避免触发同步 DB 访问。
    conv_fk = (
        getattr(conversation, "provider_credential_id_id", None)
        if conversation is not None
        else None
    )
    if conv_fk:
        cred = await _fetch_credential_by_id(UUID(str(conv_fk)))
        if cred is not None:
            return cred, "conversation"
    # 3. 项目级 FK（implementation/229 加字段后启用）
    #    同 conv_fk：读 `default_provider_credential_id_id` 列拿 UUID。
    proj_fk = (
        getattr(project, "default_provider_credential_id_id", None)
        if project is not None
        else None
    )
    if proj_fk:
        cred = await _fetch_credential_by_id(UUID(str(proj_fk)))
        if cred is not None:
            return cred, "project"
    # 4. 系统级 default
    cred = await _fetch_system_default_credential(provider_type)
    if cred is not None:
        return cred, "system"
    return None, "system"


# implementation（contract/contract）：_resolve_from_system_setting_legacy 函数硬删。
# SystemSetting.ANTHROPIC_* 4 行已通过 data_migrations.seed_provider_credentials
# 导入为 ProviderCredential（implementation contract 已落地）；降级路径不再需要。


class ProviderConfigService:
    """四层配置优先级解析服务。

    解析顺序：节点级 > 对话级 > 项目级 > 系统级。
    被 ConversationService 和 AIAgentBaseNode 共用。
    """

    @staticmethod
    def resolve(
        node_config: dict[str, Any] | None = None,
        conversation: Any | None = None,
        project: Any | None = None,
    ) -> ResolvedProviderConfig:
        """同步解析 Provider 配置（implementation contract/contract 后仅保留向后兼容 stub）。

        legacy SettingKeys.ANTHROPIC_* 硬删后，同步路径不再支持
        从 SystemSetting 降级。调用方应迁移到 aresolve_or_error。

        Raises:
            ProviderConfigError: 同步上下文下凭证解析不再支持
        """
        raise ProviderConfigError(
            "同步 resolve() 已在 implementation 硬删；请使用 "
            "ProviderConfigService.aresolve_or_error(...) 异步接口"
        )

    @staticmethod
    async def aresolve_or_error(
        node_config: dict[str, Any] | None = None,
        conversation: Any | None = None,
        project: Any | None = None,
    ) -> AResolveResult:
        """contract Result 模式入口。不抛异常，返回 ResolvedProviderConfig | ProviderMissingError。

        implementation（contract/contract）：SettingKeys.DEFAULT_PROVIDER_TYPE +
        Conversation.provider_type + Project.default_provider_type 硬删后，
        provider_type 仅通过 node_config 显式覆盖；其他层由 ProviderCredential 承载。

        四层优先级：节点 FK > 对话 FK > 项目 FK > 系统 default ProviderCredential。
        全部未命中或 Pydantic 校验失败 → ProviderMissingError。
        """
        # 1. provider_type 探测：仅支持 node_config 显式；其他层由 ProviderCredential 承载
        try:
            if node_config and node_config.get("provider_type"):
                provider_type = _parse_provider_type(node_config["provider_type"])
            else:
                # 默认 Anthropic；最终 provider_type 由 _resolve_credential_async
                # 查到的 ProviderCredential.provider_type 决定
                provider_type = ProviderType.ANTHROPIC
        except ProviderConfigError as e:
            return ProviderMissingError(
                missing_provider="",
                recommended_action=str(e),
                source_attempted="system",
            )

        # 2. 四层优先级查 ProviderCredential（FK）
        credential, source = await _resolve_credential_async(
            provider_type, node_config, conversation, project
        )

        if credential is None:
            # 全部未命中 → 结构化错误
            metadata = PROVIDER_REGISTRY[provider_type]
            return ProviderMissingError(
                missing_provider=str(provider_type),
                recommended_action=(
                    f"{metadata.display_name} 凭据未配置，"
                    f"请在系统设置添加 {metadata.display_name} 凭证"
                ),
                source_attempted=source,
            )

        # 命中凭证后实际 provider_type 以 credential 为准（支持多 Provider 场景）
        try:
            provider_type = _parse_provider_type(str(credential.provider_type))
        except ProviderConfigError:
            pass  # 保留默认 provider_type

        # 5. 解密 + Pydantic credential_schema 校验
        #    security mitigation / security mitigation 缓解：失败时不把 ValidationError 内容写入日志
        try:
            raw_config = credential.get_decrypted_config()
            schema_cls = PROVIDER_REGISTRY[provider_type].credential_schema
            validated = schema_cls.model_validate(raw_config)
        except ValidationError:
            # 不在 logger 中写 raw_config 或 ValidationError.errors() 的 input_value（security mitigation）
            logger.error(
                "provider_credential_schema_invalid",
                provider=str(provider_type),
                credential_id=str(credential.id),
                error_summary="schema_validate_failed",
            )
            return ProviderMissingError(
                missing_provider=str(provider_type),
                recommended_action=(
                    f"凭证字段校验失败（{PROVIDER_REGISTRY[provider_type].display_name}），"
                    f"请检查必填字段"
                ),
                source_attempted=source,
            )
        except Exception as e:
            # 解密失败 / JSON parse 失败
            logger.error(
                "provider_credential_decrypt_failed",
                provider=str(provider_type),
                credential_id=str(credential.id),
                error_type=type(e).__name__,
            )
            return ProviderMissingError(
                missing_provider=str(provider_type),
                recommended_action=(
                    f"凭证解密失败（{PROVIDER_REGISTRY[provider_type].display_name}）"
                ),
                source_attempted=source,
            )

        # 6. 装入 ResolvedProviderConfig（SecretStr → 明文仅在最终返回时 unwrap）
        api_key_value = ""
        if hasattr(validated, "api_key") and validated.api_key is not None:
            secret = validated.api_key
            api_key_value = (
                secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
            )
        base_url_value = (
            getattr(validated, "base_url", "")
            or PROVIDER_REGISTRY[provider_type].default_base_url
        )
        # extra 字段：剔除 api_key / base_url / bearer_token 等已被解构字段，
        # 剩余 Provider-specific 字段（如 OpenAI organization_id）
        extra: dict[str, Any] = {}
        dumped = validated.model_dump(exclude={"api_key", "base_url", "bearer_token"})
        for k, v in dumped.items():
            extra[k] = v
        # 注入 credential.default_model 到 extra（供调用方
        # 做 model fallback 使用，替代既有 aget_claude_config(project).model 路径）
        if credential.default_model:
            extra["default_model"] = credential.default_model

        logger.info(
            "provider_config_resolved",
            provider_type=str(provider_type),
            source=source,
            credential_id=str(credential.id),
        )
        return ResolvedProviderConfig(
            provider_type=provider_type,
            api_key=api_key_value,
            base_url=base_url_value,
            source=source,
            credential_id=credential.id,
            extra=extra,
            max_concurrency=int(getattr(credential, "max_concurrency", 0) or 0),
        )

    @staticmethod
    async def aresolve(
        node_config: dict[str, Any] | None = None,
        conversation: Any | None = None,
        project: Any | None = None,
    ) -> ResolvedProviderConfig:
        """向后兼容：失败时仍抛 ProviderConfigError。

        ChatAnthropicRunner / orchestration/coding_graph.py 等现有调用方零改动。
        新代码（implementation/229）应直接用 aresolve_or_error 走 Result 模式。

        Raises:
            ProviderConfigError: 配置缺失或凭据校验失败
        """
        result = await ProviderConfigService.aresolve_or_error(
            node_config, conversation, project
        )
        if isinstance(result, ProviderMissingError):
            raise ProviderConfigError(result.recommended_action or "Provider 凭证缺失")
        return result

    # ------------------------------------------------------------------
    # implementation contract contract：完整四层优先级链路解析
    # ------------------------------------------------------------------

    @staticmethod
    async def aresolve_with_chain(
        node_config: dict[str, Any] | None = None,
        conversation: Any | None = None,
        project: Any | None = None,
    ) -> "ResolvedProviderChain | ProviderMissingError":
        """implementation contract contract：返回四层解析链路 + winning source。

        逻辑：
            1. 从 node_config / conversation / project 读取各层原始 credential_id
               （读 `{field}_id` 列避免 async 下触发 SynchronousOnlyOperation）
            2. 对每层 credential_id 异步查 ProviderCredential（is_active=True），
               填充 provider_type；指向已删除 / 已禁用凭证的条目清 credential_id=None
            3. 委托 aresolve_or_error 拿 winning source
            4. 标记对应层 active=True，填补 winning 层的 provider_type / model

        返回：
            - ResolvedProviderChain（winning + chain[4]）
            - ProviderMissingError（与 aresolve_or_error 同语义）
        """
        # 1. 构建 chain 骨架（4 层，顺序固定）
        node_cfg = node_config or {}
        node_model = node_cfg.get("model") if isinstance(node_cfg, dict) else None

        chain: list[ResolutionChainEntry] = [
            ResolutionChainEntry(
                layer="node",
                provider_type=None,
                model=node_model,
                credential_id=_parse_uuid_or_none(
                    node_cfg.get("provider_credential_id") if isinstance(node_cfg, dict) else None
                ),
                active=False,
            ),
            ResolutionChainEntry(
                layer="conversation",
                provider_type=None,
                model=getattr(conversation, "model", None) if conversation is not None else None,
                credential_id=_parse_uuid_or_none(
                    getattr(conversation, "provider_credential_id_id", None)
                    if conversation is not None
                    else None
                ),
                active=False,
            ),
            ResolutionChainEntry(
                layer="project",
                provider_type=None,
                model=None,
                credential_id=_parse_uuid_or_none(
                    getattr(project, "default_provider_credential_id_id", None)
                    if project is not None
                    else None
                ),
                active=False,
            ),
            ResolutionChainEntry(
                layer="system",
                provider_type=None,
                model=None,
                credential_id=None,  # system 层由 aresolve_or_error 定位 default 凭证，无本地 FK
                active=False,
            ),
        ]

        # 2. 对 node / conversation / project 层的 credential_id 异步读 provider_type；
        #    指向非活跃 / 已删除凭证的条目清零（视为不可用，不阻塞继续向下层解析）
        from system.models import ProviderCredential

        for entry in chain[:3]:
            if entry.credential_id:
                try:
                    cred = await ProviderCredential.objects.aget(
                        id=entry.credential_id, is_active=True
                    )
                    entry.provider_type = str(cred.provider_type)
                except ProviderCredential.DoesNotExist:
                    entry.credential_id = None

        # 3. 委托 aresolve_or_error 拿 winning
        result = await ProviderConfigService.aresolve_or_error(
            node_config=node_config,
            conversation=conversation,
            project=project,
        )
        if isinstance(result, ProviderMissingError):
            logger.info(
                "provider_config.resolve_chain_missing",
                missing_provider=result.missing_provider,
                source_attempted=result.source_attempted,
            )
            return result

        # 4. 标记 winning 层
        for entry in chain:
            if entry.layer == result.source:
                entry.active = True
                if not entry.provider_type:
                    entry.provider_type = str(result.provider_type)
                if not entry.model:
                    entry.model = result.extra.get("model") if result.extra else None
                # system 层 credential_id 填补（winning=system 时）
                if entry.credential_id is None and result.credential_id is not None:
                    entry.credential_id = result.credential_id
                break

        logger.info(
            "provider_config.resolve_chain_computed",
            winning_source=result.source,
            chain_length=len(chain),
            provider_type=str(result.provider_type),
        )
        return ResolvedProviderChain(winning=result, chain=chain)
