"""
Provider 类型系统：ProviderType 枚举、元数据注册表。
为 v8.1 多模型 Provider 支持提供类型安全的基础，
替代散布在代码中的魔法字符串。
"""
from enum import StrEnum
from typing import TypedDict
class ProviderType(StrEnum):
 """LLM Provider 类型枚举。值为小写字符串，可直接存储到 DB CharField。"""
 ANTHROPIC = "anthropic"
 OPENAI_RESPONSES = "openai-responses"
 OPENAI_CODEX_RESPONSES = "openai-codex-responses"
 OPENAI_COMPLETIONS = "openai-completions"
 GOOGLE_VERTEX = "google-vertex"
 GOOGLE_GEMINI_CLI = "google-gemini-cli"
 GOOGLE_ANTIGRAVITY = "google-antigravity"
class CredentialType(StrEnum):
 """凭据类型枚举。"""
 API_KEY = "api_key"
 SERVICE_ACCOUNT_JSON = "service_account_json"
class ApiFormat(StrEnum):
 """API 协议格式枚举，决定工厂函数路由到哪个 Provider 实现类。"""
 ANTHROPIC = "anthropic"
 OPENAI_RESPONSES = "openai_responses"
 OPENAI_COMPLETIONS = "openai_completions"
 GOOGLE_GENAI = "google_genai"
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
 ProviderType.OPENAI_RESPONSES: {
 "display_name": "OpenAI Responses",
 "api_format": ApiFormat.OPENAI_RESPONSES,
 "credential_type": CredentialType.API_KEY,
 "default_base_url": "https://api.openai.com/v1",
 "env_key": "OPENAI_API_KEY",
 },
 ProviderType.OPENAI_CODEX_RESPONSES: {
 "display_name": "OpenAI Codex",
 "api_format": ApiFormat.OPENAI_RESPONSES,
 "credential_type": CredentialType.API_KEY,
 "default_base_url": "https://api.openai.com/v1",
 "env_key": "OPENAI_API_KEY",
 },
 ProviderType.OPENAI_COMPLETIONS: {
 "display_name": "OpenAI Completions",
 "api_format": ApiFormat.OPENAI_COMPLETIONS,
 "credential_type": CredentialType.API_KEY,
 "default_base_url": "https://api.openai.com/v1",
 "env_key": "OPENAI_API_KEY",
 },
 ProviderType.GOOGLE_VERTEX: {
 "display_name": "Google Vertex AI",
 "api_format": ApiFormat.GOOGLE_GENAI,
 "credential_type": CredentialType.SERVICE_ACCOUNT_JSON,
 "default_base_url": "",
 "env_key": "GOOGLE_CLOUD_PROJECT",
 },
 ProviderType.GOOGLE_GEMINI_CLI: {
 "display_name": "Google Gemini",
 "api_format": ApiFormat.GOOGLE_GENAI,
 "credential_type": CredentialType.API_KEY,
 "default_base_url": "",
 "env_key": "GEMINI_API_KEY",
 },
 ProviderType.GOOGLE_ANTIGRAVITY: {
 "display_name": "Google Antigravity",
 "api_format": ApiFormat.GOOGLE_GENAI,
 "credential_type": CredentialType.API_KEY,
 "default_base_url": "",
 "env_key": "GOOGLE_API_KEY",
 },
}
