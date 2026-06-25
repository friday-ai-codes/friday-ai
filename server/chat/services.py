"""Chat service for LLM API calls.

Provides a unified interface for calling LLM APIs via protocol abstraction.
ChatService is a thin facade that delegates to ProviderProtocol implementations.

Serializer Async Pattern (contract):
    在 async view 中使用 DRF/adrf serializer 的统一模式：
    - is_valid(): 无 DB 查询时直接调用；有 DB 验证时用 await sync_to_async(s.is_valid)(raise_exception=True)
    - save(): 使用 await serializer.asave()（adrf serializer）或 await sync_to_async(serializer.save)()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Optional

import structlog

from common.encryption import decrypt_value
from projects.models import Space
from system.models import SystemSetting

if TYPE_CHECKING:
    from chat.protocols.base import ProviderProtocol

logger = structlog.get_logger(__name__)

# Default timeout for API calls (30 seconds)
DEFAULT_TIMEOUT = 30.0

# Default base URL for OpenAI-compatible API
DEFAULT_BASE_URL = "https://api.openai.com"

# 合法的 provider_type 值（chat 协议系统）
VALID_PROVIDER_TYPES = frozenset({"openai_chat", "openai_response", "anthropic", "gemini"})


@dataclass
class ChatMessage:
    """Chat message structure."""

    role: Literal["user", "assistant", "system"]
    content: str


@dataclass
class ChatCompletionResult:
    """Chat completion result."""

    content: str
    model: str
    usage: Optional[dict[str, int]] = None


@dataclass
class Model:
    """Model information."""

    id: str
    name: str
    created: Optional[int] = None


class ChatServiceError(Exception):
    """Chat service error."""

    pass


class ChatService:
    """Service for LLM API calls.

    Thin facade that delegates to a ProviderProtocol implementation.
    Public interface (chat_completion, get_models) remains unchanged.
    """

    def __init__(self, protocol: ProviderProtocol) -> None:
        """Initialize chat service.

        Args:
            protocol: Provider protocol instance to delegate calls to
        """
        self._protocol = protocol

    async def get_models(self) -> list[Model]:
        """Get available models from the API.

        Returns:
            List of available models

        Raises:
            ChatServiceError: If the API call fails
        """
        return await self._protocol.get_models()

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model: str,
        max_tokens: int = 4096,
    ) -> ChatCompletionResult:
        """Send a chat completion request.

        Args:
            messages: List of chat messages
            model: Model ID to use
            max_tokens: Maximum tokens in response

        Returns:
            Chat completion result

        Raises:
            ChatServiceError: If the API call fails
        """
        return await self._protocol.send_message(messages, model, max_tokens)


def get_setting_value(key: str) -> Optional[str]:
    """获取系统设置值（自动解密）。"""
    try:
        setting = SystemSetting.objects.get(key=key)
        if not setting.value:
            return None
        if setting.is_encrypted:
            return decrypt_value(setting.value)
        return setting.value
    except SystemSetting.DoesNotExist:
        return None
    except ValueError as e:
        raise ChatServiceError(str(e))


async def aget_setting_value(key: str) -> Optional[str]:
    """获取系统设置值（自动解密）— async 版本。"""
    try:
        setting = await SystemSetting.objects.aget(key=key)
        if not setting.value:
            return None
        if setting.is_encrypted:
            return decrypt_value(setting.value)
        return setting.value
    except SystemSetting.DoesNotExist:
        return None
    except ValueError as e:
        raise ChatServiceError(str(e))


def _create_protocol(provider_type: str, api_key: str, base_url: str) -> ProviderProtocol:
    """根据 provider_type 创建协议实例。

    Args:
        provider_type: 协议类型标识
        api_key: API 密钥
        base_url: API 基础 URL

    Returns:
        ProviderProtocol 实例

    Raises:
        ChatServiceError: provider_type 不合法或尚未实现
    """
    if provider_type not in VALID_PROVIDER_TYPES:
        raise ChatServiceError(
            f"不支持的 provider_type: '{provider_type}'，"
            f"支持的值: {', '.join(sorted(VALID_PROVIDER_TYPES))}"
        )
    if provider_type == "openai_chat":
        from chat.protocols.openai_chat import OpenAIChatProtocol

        return OpenAIChatProtocol(api_key=api_key, base_url=base_url)
    # Phase 将添加 openai_response, anthropic, gemini 协议实现
    raise ChatServiceError(
        f"Provider 类型 '{provider_type}' 尚未实现，" f"当前仅支持: openai_chat"
    )


def _load_project_credential_sync(project_id: int) -> tuple[str, str]:
    """同步读项目级默认 ProviderCredential(anthropic)。

    Returns:
        (api_key, base_url) 元组；缺失则返回 ("", "")。
    """
    from system.models import ProviderCredential
    from services.provider_config import (
        PROVIDER_REGISTRY,
        ProviderType,
    )

    try:
        project = Space.objects.get(id=project_id)
    except Space.DoesNotExist:
        raise ChatServiceError(f"找不到空间: {project_id}")

    # 优先走 project.default_provider_credential_id FK
    cred: Any = None
    fk_id = getattr(project, "default_provider_credential_id_id", None)
    if fk_id:
        try:
            cred = ProviderCredential.objects.get(id=fk_id, is_active=True)
        except ProviderCredential.DoesNotExist:
            cred = None
    # 回退到项目级 anthropic default
    if cred is None:
        cred = ProviderCredential.objects.filter(
            scope="project",
            scope_id=project.id,
            provider_type="anthropic",
            name="default",
            is_active=True,
        ).first()
    if cred is None:
        return "", ""

    try:
        raw_cfg = cred.get_decrypted_config()
        schema_cls = PROVIDER_REGISTRY[ProviderType.ANTHROPIC].credential_schema
        validated = schema_cls.model_validate(raw_cfg)
    except Exception:  # noqa: BLE001
        return "", ""
    api_key_value = ""
    if hasattr(validated, "api_key") and validated.api_key is not None:
        secret = validated.api_key
        api_key_value = (
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        )
    base_url = getattr(validated, "base_url", "") or cred.base_url or ""
    return api_key_value, base_url


async def _aload_project_credential_async(project_id: int) -> tuple[str, str]:
    """异步读项目级默认 ProviderCredential(anthropic)。"""
    from system.models import ProviderCredential
    from services.provider_config import (
        PROVIDER_REGISTRY,
        ProviderType,
    )

    try:
        project = await Space.objects.aget(id=project_id)
    except Space.DoesNotExist:
        raise ChatServiceError(f"找不到空间: {project_id}")

    cred: Any = None
    fk_id = getattr(project, "default_provider_credential_id_id", None)
    if fk_id:
        try:
            cred = await ProviderCredential.objects.aget(id=fk_id, is_active=True)
        except ProviderCredential.DoesNotExist:
            cred = None
    if cred is None:
        cred = await ProviderCredential.objects.filter(
            scope="project",
            scope_id=project.id,
            provider_type="anthropic",
            name="default",
            is_active=True,
        ).afirst()
    if cred is None:
        return "", ""

    try:
        raw_cfg = cred.get_decrypted_config()
        schema_cls = PROVIDER_REGISTRY[ProviderType.ANTHROPIC].credential_schema
        validated = schema_cls.model_validate(raw_cfg)
    except Exception:  # noqa: BLE001
        return "", ""
    api_key_value = ""
    if hasattr(validated, "api_key") and validated.api_key is not None:
        secret = validated.api_key
        api_key_value = (
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        )
    base_url = getattr(validated, "base_url", "") or cred.base_url or ""
    return api_key_value, base_url


def _load_system_credential_sync() -> tuple[str, str]:
    """同步读系统级默认 ProviderCredential(anthropic)。"""
    from system.models import ProviderCredential
    from services.provider_config import (
        PROVIDER_REGISTRY,
        ProviderType,
    )

    cred = ProviderCredential.objects.filter(
        scope="system",
        provider_type="anthropic",
        name="default",
        is_active=True,
    ).first()
    if cred is None:
        return "", ""
    try:
        raw_cfg = cred.get_decrypted_config()
        schema_cls = PROVIDER_REGISTRY[ProviderType.ANTHROPIC].credential_schema
        validated = schema_cls.model_validate(raw_cfg)
    except Exception:  # noqa: BLE001
        return "", ""
    api_key_value = ""
    if hasattr(validated, "api_key") and validated.api_key is not None:
        secret = validated.api_key
        api_key_value = (
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
        )
    base_url = getattr(validated, "base_url", "") or cred.base_url or ""
    return api_key_value, base_url


def get_chat_service(
    source: Literal["system", "project"],
    project_id: Optional[int] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ChatService:
    """Get a ChatService instance with the appropriate configuration.

    implementation（contract/contract）：从 ProviderCredential 读取凭证
    （替代 v8.1 Space.claude_* / SettingKeys.ANTHROPIC_* 路径）。
    """
    final_api_key = api_key
    final_base_url = base_url

    if source == "project":
        if not project_id:
            raise ChatServiceError("使用空间配置时必须提供 space_id")
        proj_api_key, proj_base_url = _load_project_credential_sync(project_id)
        if not final_api_key and proj_api_key:
            final_api_key = proj_api_key
        if not final_base_url and proj_base_url:
            final_base_url = proj_base_url

    if not final_api_key or not final_base_url:
        sys_api_key, sys_base_url = _load_system_credential_sync()
        if not final_api_key:
            final_api_key = sys_api_key
        if not final_base_url:
            final_base_url = sys_base_url

    if not final_api_key:
        raise ChatServiceError("未配置 API Key，请在系统设置或项目设置中配置")

    # Provider 协议默认 openai_chat（SettingKeys.DEFAULT_PROVIDER_TYPE 已硬删）
    provider_type = "openai_chat"
    protocol = _create_protocol(provider_type, final_api_key, final_base_url or DEFAULT_BASE_URL)
    return ChatService(protocol=protocol)


async def aget_chat_service(
    source: Literal["system", "project"],
    project_id: Optional[int] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ChatService:
    """Get a ChatService instance — async 版本。

    implementation（contract/contract）：从 ProviderCredential 读取凭证
    （替代 v8.1 Space.claude_* / SettingKeys.ANTHROPIC_* 路径）。
    """
    from services.provider_config import aget_legacy_anthropic_config

    final_api_key = api_key
    final_base_url = base_url

    if source == "project":
        if not project_id:
            raise ChatServiceError("使用空间配置时必须提供 space_id")
        proj_api_key, proj_base_url = await _aload_project_credential_async(project_id)
        if not final_api_key and proj_api_key:
            final_api_key = proj_api_key
        if not final_base_url and proj_base_url:
            final_base_url = proj_base_url

    if not final_api_key or not final_base_url:
        legacy = await aget_legacy_anthropic_config()
        if not final_api_key:
            final_api_key = legacy["api_key"]
        if not final_base_url:
            final_base_url = legacy["base_url"]

    if not final_api_key:
        raise ChatServiceError("未配置 API Key，请在系统设置或项目设置中配置")

    provider_type = "openai_chat"
    protocol = _create_protocol(provider_type, final_api_key, final_base_url or DEFAULT_BASE_URL)
    return ChatService(protocol=protocol)
