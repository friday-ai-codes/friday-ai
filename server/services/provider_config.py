"""ProviderConfigService — 四层配置优先级解析和凭据验证。
实现节点级 > 对话级 > 项目级 > 系统级的 Provider 配置解析，
被 ConversationService 和 AIAgentBaseNode 共用。
ProviderType / ApiFormat / CredentialType / PROVIDER_REGISTRY 从
agents.llm.providers 迁移至此，避免对已删除模块的依赖。
Phase（v21.0）：扩展为 5 种 ProviderType（anthropic / openai_responses /
openai_chat / gemini / ollama），ProviderMetadata 迁移为 @dataclass(frozen=True)
（Pitfall 26 规避），新增 4 个 Pydantic credential_schema 类统一承载凭证字段
校验与脱敏（SecretStr + ConfigDict(hide_input_in_errors=True)，缓解
T- / T- 凭证泄漏威胁）。
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
import structlog
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from system.models import SettingKeys, SystemSetting
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
 """API 协议格式枚举，决定 Phase Runner 工厂分派路由。"""
 ANTHROPIC = "anthropic"
 OPENAI_RESPONSES = "openai_responses"
 OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
 GEMINI = "gemini"
 OLLAMA_NATIVE = "ollama_native"
# === Pydantic credential_schema 类（Phase 决策 1） ===
#
# 每个类必须 model_config = ConfigDict(hide_input_in_errors=True)
# —— 这是 T- 缓解的强制契约，防止 ValidationError.errors 中
# 回显原始 api_key 明文。
# SecretStr 字段在 repr/log 时自动返回 "**********"，缓解 T-。
class AnthropicCredentialSchema(BaseModel):
 """Anthropic 凭证字段。"""
 model_config = ConfigDict(hide_input_in_errors=True)
 api_key: SecretStr = Field(..., description="Anthropic API Key（sk-ant-...）")
 base_url: str = Field(
 default="https://api.anthropic.com",
 description="覆盖默认端点（Moonshot Anthropic 兼容 / one-api 网关）",
 )
class OpenAICredentialSchema(BaseModel):
 """OpenAI 凭证字段（Responses API 与 Chat Completions 共享）。"""
 model_config = ConfigDict(hide_input_in_errors=True)
 api_key: SecretStr = Field(..., description="OpenAI API Key（sk-...）")
 base_url: str = Field(
 default="https://api.openai.com/v1",
 description="覆盖默认端点（DeepSeek / Qwen / OpenRouter 走这里）",
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
 langchain_prefix: str # Phase init_chat_model 前缀（本 phase 仅声明字符串）
 credential_schema: type[BaseModel] # Pydantic 类引用，service 层 .model_validate 入口
 health_check_path: str = "/v1/models" # 健康检查端点路径（D4 锁定，registry 集中管理）
 health_check_method: str = "GET"
 supports_thinking: bool = False # 仅 Anthropic
 supports_reasoning: bool = False # OpenAI o1/o3/gpt-5 + Gemini 2.5
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
 """配置解析结果。"""
 provider_type: ProviderType
 api_key: str # 凭据值（API Key）
 base_url: str # 从 PROVIDER_REGISTRY 获取
 source: str # "node" | "conversation" | "project" | "system"
# PROVIDER_REGISTRY 的 env_key（大写）→ SettingKeys 的值（小写）映射。
ENV_KEY_TO_SETTING_KEY: dict[str, str] = {
 "ANTHROPIC_API_KEY": SettingKeys.ANTHROPIC_API_KEY,
}
def _get_setting_value_sync(key: str) -> str | None:
 """同步获取系统设置值（自动解密）。"""
 from common.encryption import decrypt_value
 try:
 setting = SystemSetting.objects.get(key=key)
 if not setting.value:
 return None
 if setting.is_encrypted:
 return decrypt_value(setting.value)
 return setting.value
 except SystemSetting.DoesNotExist:
 return None
async def _get_setting_value_async(key: str) -> str | None:
 """异步获取系统设置值（自动解密）。"""
 from common.encryption import decrypt_value
 try:
 setting = await SystemSetting.objects.aget(key=key)
 if not setting.value:
 return None
 if setting.is_encrypted:
 return decrypt_value(setting.value)
 return setting.value
 except SystemSetting.DoesNotExist:
 return None
def _resolve_provider_type(
 node_config: dict[str, Any] | None,
 conversation: Any | None,
 project: Any | None,
 get_setting: Any,
) -> tuple[ProviderType, str]:
 """从四层配置中解析 provider_type。
 返回 (ProviderType, source) 元组。
 四层都没有时默认使用 ANTHROPIC。
 """
 # 1. 节点级
 if node_config and node_config.get("provider_type"):
 pt_str = node_config["provider_type"]
 return _parse_provider_type(pt_str), "node"
 # 2. 对话级
 if conversation is not None and getattr(conversation, "provider_type", None):
 pt_str = conversation.provider_type
 return _parse_provider_type(pt_str), "conversation"
 # 3. 项目级
 if project is not None and getattr(project, "default_provider_type", None):
 pt_str = project.default_provider_type
 return _parse_provider_type(pt_str), "project"
 # 4. 系统级
 system_pt = get_setting(SettingKeys.DEFAULT_PROVIDER_TYPE)
 if system_pt:
 return _parse_provider_type(system_pt), "system"
 # 默认使用 Anthropic
 return ProviderType.ANTHROPIC, "system"
def _parse_provider_type(value: str) -> ProviderType:
 """将字符串转换为 ProviderType 枚举。"""
 try:
 return ProviderType(value)
 except ValueError:
 raise ProviderConfigError(f"不支持的 Provider 类型: {value}")
def _resolve_credential(
 provider_type: ProviderType,
 get_setting: Any,
) -> str:
 """根据 Provider 类型查找凭据。
 Raises:
 ProviderConfigError: 凭据未配置
 """
 metadata = PROVIDER_REGISTRY[provider_type]
 display_name = metadata.display_name
 env_key = metadata.env_key
 # API Key 类型
 setting_key = ENV_KEY_TO_SETTING_KEY.get(env_key)
 if not setting_key:
 raise ProviderConfigError(
 f"{display_name} 的凭据键 {env_key} 没有对应的系统设置映射"
 )
 credential = get_setting(setting_key)
 if not credential:
 raise ProviderConfigError(
 f"{display_name} 凭据未配置，请在系统设置中配置 {setting_key}"
 )
 return credential
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
 """同步解析 Provider 配置。
 Args:
 node_config: 节点级配置（含 provider_type 键）
 conversation: 对话实例（含 provider_type 字段）
 project: 项目实例（含 default_provider_type 字段）
 Returns:
 ResolvedProviderConfig 配置解析结果
 Raises:
 ProviderConfigError: 配置缺失或凭据未配置
 """
 provider_type, source = _resolve_provider_type(
 node_config, conversation, project, _get_setting_value_sync
 )
 credential = _resolve_credential(provider_type, _get_setting_value_sync)
 # base_url: 系统设置优先，回退到注册表默认值
 base_url = (
 _get_setting_value_sync(SettingKeys.ANTHROPIC_BASE_URL)
 or PROVIDER_REGISTRY[provider_type].default_base_url
 )
 logger.info(
 "provider_config_resolved",
 provider_type=str(provider_type),
 source=source,
 )
 return ResolvedProviderConfig(
 provider_type=provider_type,
 api_key=credential,
 base_url=base_url,
 source=source,
 )
 @staticmethod
 async def aresolve(
 node_config: dict[str, Any] | None = None,
 conversation: Any | None = None,
 project: Any | None = None,
 ) -> ResolvedProviderConfig:
 """异步解析 Provider 配置。
 Args:
 node_config: 节点级配置（含 provider_type 键）
 conversation: 对话实例（含 provider_type 字段）
 project: 项目实例（含 default_provider_type 字段）
 Returns:
 ResolvedProviderConfig 配置解析结果
 Raises:
 ProviderConfigError: 配置缺失或凭据未配置
 """
 # 1-3 层：同步检查（不涉及 DB）
 if node_config and node_config.get("provider_type"):
 provider_type = _parse_provider_type(node_config["provider_type"])
 source = "node"
 elif conversation is not None and getattr(conversation, "provider_type", None):
 provider_type = _parse_provider_type(conversation.provider_type)
 source = "conversation"
 elif project is not None and getattr(project, "default_provider_type", None):
 provider_type = _parse_provider_type(project.default_provider_type)
 source = "project"
 else:
 # 4. 系统级（需要异步 DB 查询）
 system_pt = await _get_setting_value_async(SettingKeys.DEFAULT_PROVIDER_TYPE)
 if system_pt:
 provider_type = _parse_provider_type(system_pt)
 else:
 # 默认使用 Anthropic
 provider_type = ProviderType.ANTHROPIC
 source = "system"
 # 凭据解析（需要异步 DB 查询）
 metadata = PROVIDER_REGISTRY[provider_type]
 display_name = metadata.display_name
 env_key = metadata.env_key
 setting_key = ENV_KEY_TO_SETTING_KEY.get(env_key)
 if not setting_key:
 raise ProviderConfigError(
 f"{display_name} 的凭据键 {env_key} 没有对应的系统设置映射"
 )
 credential = await _get_setting_value_async(setting_key)
 if not credential:
 raise ProviderConfigError(
 f"{display_name} 凭据未配置，请在系统设置中配置 {setting_key}"
 )
 # base_url: 系统设置优先，回退到注册表默认值
 base_url = (
 await _get_setting_value_async(SettingKeys.ANTHROPIC_BASE_URL)
 or metadata.default_base_url
 )
 logger.info(
 "provider_config_resolved",
 provider_type=str(provider_type),
 source=source,
 )
 return ResolvedProviderConfig(
 provider_type=provider_type,
 api_key=credential,
 base_url=base_url,
 source=source,
 )
