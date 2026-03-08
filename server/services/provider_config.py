"""ProviderConfigService — 四层配置优先级解析和凭据验证。
实现节点级 > 对话级 > 项目级 > 系统级的 Provider 配置解析，
被 ConversationService 和 AIAgentBaseNode 共用。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import structlog
from agents.llm.providers import (
 CredentialType,
 PROVIDER_REGISTRY,
 ProviderType,
)
from system.models import SettingKeys, SystemSetting
logger = structlog.get_logger(__name__)
class ProviderConfigError(Exception):
 """Provider 配置解析错误。"""
@dataclass
class ResolvedProviderConfig:
 """配置解析结果。"""
 provider_type: ProviderType
 api_key: str # 凭据值（API Key 或 Service Account JSON）
 base_url: str # 从 PROVIDER_REGISTRY 获取
 source: str # "node" | "conversation" | "project" | "system"
# PROVIDER_REGISTRY 的 env_key（大写）→ SettingKeys 的值（小写）映射。
# 特殊情况：GEMINI_API_KEY 和 GOOGLE_API_KEY 都映射到 SettingKeys.GOOGLE_API_KEY，
# GOOGLE_CLOUD_PROJECT 不直接映射凭据（Vertex 使用 Service Account JSON）。
ENV_KEY_TO_SETTING_KEY: dict[str, str] = {
 "ANTHROPIC_API_KEY": SettingKeys.ANTHROPIC_API_KEY,
 "OPENAI_API_KEY": SettingKeys.OPENAI_API_KEY,
 "GEMINI_API_KEY": SettingKeys.GOOGLE_API_KEY,
 "GOOGLE_API_KEY": SettingKeys.GOOGLE_API_KEY,
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
 Raises:
 ProviderConfigError: 四层都没有找到 provider_type
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
 raise ProviderConfigError(
 "未找到 Provider 配置。请在系统设置中配置 default_provider_type"
 )
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
 credential_type = metadata["credential_type"]
 display_name = metadata["display_name"]
 env_key = metadata["env_key"]
 # Service Account JSON 特殊处理
 if credential_type == CredentialType.SERVICE_ACCOUNT_JSON:
 setting_key = SettingKeys.GOOGLE_SERVICE_ACCOUNT_JSON
 credential = get_setting(setting_key)
 if not credential:
 raise ProviderConfigError(
 f"{display_name} 凭据未配置，请在系统设置中配置 {setting_key}"
 )
 return credential
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
 base_url = PROVIDER_REGISTRY[provider_type]["default_base_url"]
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
 # provider_type 解析：前三层不需要 DB 查询，只有系统级需要
 # 为简化逻辑，将异步 get_setting 包装为同步调用接口
 # 但系统级查找需要异步，所以分步处理
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
 if not system_pt:
 raise ProviderConfigError(
 "未找到 Provider 配置。请在系统设置中配置 default_provider_type"
 )
 provider_type = _parse_provider_type(system_pt)
 source = "system"
 # 凭据解析（需要异步 DB 查询）
 metadata = PROVIDER_REGISTRY[provider_type]
 credential_type = metadata["credential_type"]
 display_name = metadata["display_name"]
 env_key = metadata["env_key"]
 if credential_type == CredentialType.SERVICE_ACCOUNT_JSON:
 setting_key = SettingKeys.GOOGLE_SERVICE_ACCOUNT_JSON
 credential = await _get_setting_value_async(setting_key)
 if not credential:
 raise ProviderConfigError(
 f"{display_name} 凭据未配置，请在系统设置中配置 {setting_key}"
 )
 else:
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
 base_url = metadata["default_base_url"]
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
