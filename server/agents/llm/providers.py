"""
Provider 类型系统：ProviderType 枚举、元数据注册表。
为 Provider 支持提供类型安全的基础，
替代散布在代码中的魔法字符串。
"""
from enum import StrEnum
from typing import TypedDict
class ProviderType(StrEnum):
 """LLM Provider 类型枚举。值为小写字符串，可直接存储到 DB CharField。"""
 ANTHROPIC = "anthropic"
class CredentialType(StrEnum):
 """凭据类型枚举。"""
 API_KEY = "api_key"
class ApiFormat(StrEnum):
 """API 协议格式枚举，决定工厂函数路由到哪个 Provider 实现类。"""
 ANTHROPIC = "anthropic"
class ProviderMetadata(TypedDict):
 """Provider 元数据，描述每个 Provider 的特征。"""
 display_name: str
 api_format: ApiFormat
 credential_type: CredentialType
 default_base_url: str
 env_key: str
PROVIDER_REGISTRY: dict[ProviderType, ProviderMetadata] = {
 ProviderType.ANTHROPIC: {
 "display_name": "Anthropic Claude",
 "api_format": ApiFormat.ANTHROPIC,
 "credential_type": CredentialType.API_KEY,
 "default_base_url": "https://api.anthropic.com",
 "env_key": "ANTHROPIC_API_KEY",
 },
}
