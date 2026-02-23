"""Chat service for LLM API calls.
Provides a unified interface for calling LLM APIs (Claude/OpenAI compatible).
Serializer Async Pattern:
 在 async view 中使用 DRF/adrf serializer 的统一模式：
 - is_valid: 无 DB 查询时直接调用；有 DB 验证时用 await sync_to_async(s.is_valid)(raise_exception=True)
 - save: 使用 await serializer.asave（adrf serializer）或 await sync_to_async(serializer.save)
"""
from dataclasses import dataclass
from typing import Literal, Optional
import httpx
import structlog
from common.encryption import decrypt_value
from projects.models import Project
from system.models import SettingKeys, SystemSetting
logger = structlog.get_logger(__name__)
# Default timeout for API calls (30 seconds)
DEFAULT_TIMEOUT = 30.0
# Default base URL for Anthropic API
DEFAULT_BASE_URL = "https://api.anthropic.com"
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
 """Service for LLM API calls."""
 def __init__(
 self,
 api_key: str,
 base_url: Optional[str] = None,
 timeout: float = DEFAULT_TIMEOUT,
 ):
 """Initialize chat service.
 Args:
 api_key: API key for the LLM provider
 base_url: Base URL for the API (defaults to Anthropic API)
 timeout: Request timeout in seconds
 """
 self.api_key = api_key
 self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
 self.timeout = timeout
 def _get_headers(self) -> dict[str, str]:
 """Get request headers."""
 return {
 "Authorization": f"Bearer {self.api_key}",
 "Content-Type": "application/json",
 "x-api-key": self.api_key, # For Anthropic API compatibility
 }
 async def get_models(self) -> list[Model]:
 """Get available models from the API.
 Returns:
 List of available models
 Raises:
 ChatServiceError: If the API call fails
 """
 url = f"{self.base_url}/v1/models"
 logger.info("正在获取模型列表", url=url)
 try:
 async with httpx.AsyncClient(timeout=self.timeout) as client:
 response = await client.get(url, headers=self._get_headers)
 response.raise_for_status
 data = response.json
 models =
 for model_data in data.get("data", ):
 models.append(
 Model(
 id=model_data.get("id", ""),
 name=model_data.get("id", ""), # Use id as name if not provided
 created=model_data.get("created"),
 )
 )
 logger.info("模型列表获取成功", count=len(models))
 return models
 except httpx.TimeoutException:
 logger.error("获取模型列表请求超时")
 raise ChatServiceError("请求超时，请检查网络连接和 Base URL 配置")
 except httpx.HTTPStatusError as e:
 logger.error("获取模型列表 HTTP 错误", status_code=e.response.status_code)
 if e.response.status_code == 401:
 raise ChatServiceError("API Key 无效或已过期")
 elif e.response.status_code == 403:
 raise ChatServiceError("API Key 没有访问权限")
 else:
 raise ChatServiceError(f"API 请求失败: {e.response.status_code}")
 except httpx.RequestError as e:
 logger.error("获取模型列表网络错误", error=str(e))
 raise ChatServiceError(f"网络请求失败: {str(e)}")
 except Exception as e:
 logger.error("获取模型列表未知错误", error=str(e))
 raise ChatServiceError(f"获取模型列表失败: {str(e)}")
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
 url = f"{self.base_url}/v1/chat/completions"
 logger.info("正在发送对话请求", url=url, model=model)
 payload = {
 "model": model,
 "messages": [{"role": m.role, "content": m.content} for m in messages],
 "max_tokens": max_tokens,
 }
 try:
 async with httpx.AsyncClient(timeout=self.timeout) as client:
 response = await client.post(
 url,
 headers=self._get_headers,
 json=payload,
 )
 response.raise_for_status
 data = response.json
 # Extract content from response
 choices = data.get("choices", )
 if not choices:
 raise ChatServiceError("API 返回空响应")
 message = choices[0].get("message", {})
 content = message.get("content", "")
 result = ChatCompletionResult(
 content=content,
 model=data.get("model", model),
 usage=data.get("usage"),
 )
 logger.info(
 "对话请求成功",
 model=result.model,
 usage=result.usage,
 )
 return result
 except httpx.TimeoutException:
 logger.error("对话请求超时")
 raise ChatServiceError("请求超时，请稍后重试")
 except httpx.HTTPStatusError as e:
 logger.error(
 "对话请求 HTTP 错误",
 status_code=e.response.status_code,
 )
 if e.response.status_code == 401:
 raise ChatServiceError("API Key 无效或已过期")
 elif e.response.status_code == 403:
 raise ChatServiceError("API Key 没有访问权限")
 elif e.response.status_code == 429:
 raise ChatServiceError("请求过于频繁，请稍后重试")
 else:
 # Try to extract error message from response
 try:
 error_data = e.response.json
 error_msg = error_data.get("error", {}).get("message", str(e))
 except Exception:
 error_msg = str(e)
 raise ChatServiceError(f"API 请求失败: {error_msg}")
 except httpx.RequestError as e:
 logger.error("对话请求网络错误", error=str(e))
 raise ChatServiceError(f"网络请求失败: {str(e)}")
 except ChatServiceError:
 raise
 except Exception as e:
 logger.error("对话请求未知错误", error=str(e))
 raise ChatServiceError(f"对话请求失败: {str(e)}")
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
def get_chat_service(
 source: Literal["system", "project"],
 project_id: Optional[int] = None,
 api_key: Optional[str] = None,
 base_url: Optional[str] = None,
) -> ChatService:
 """Get a ChatService instance with the appropriate configuration.
 Args:
 source: Configuration source ("system" or "project")
 project_id: Project ID (required if source is "project")
 api_key: Override API key (for testing unsaved config)
 base_url: Override base URL (for testing unsaved config)
 Returns:
 Configured ChatService instance
 Raises:
 ChatServiceError: If configuration is missing or invalid
 """
 final_api_key = api_key
 final_base_url = base_url
 if source == "project":
 if not project_id:
 raise ChatServiceError("使用项目配置时必须提供 project_id")
 try:
 project = Project.objects.get(id=project_id)
 except Project.DoesNotExist:
 raise ChatServiceError(f"找不到项目: {project_id}")
 # Use project config if not overridden
 if not final_api_key and project.claude_api_key_encrypted:
 final_api_key = decrypt_value(project.claude_api_key_encrypted)
 if not final_base_url and project.claude_base_url:
 final_base_url = project.claude_base_url
 # Fall back to system config if not set
 if not final_api_key:
 final_api_key = get_setting_value(SettingKeys.ANTHROPIC_API_KEY)
 if not final_base_url:
 final_base_url = get_setting_value(SettingKeys.ANTHROPIC_BASE_URL)
 if not final_api_key:
 raise ChatServiceError("未配置 API Key，请在系统设置或项目设置中配置")
 return ChatService(
 api_key=final_api_key,
 base_url=final_base_url,
 )
async def aget_chat_service(
 source: Literal["system", "project"],
 project_id: Optional[int] = None,
 api_key: Optional[str] = None,
 base_url: Optional[str] = None,
) -> ChatService:
 """Get a ChatService instance — async 版本。"""
 final_api_key = api_key
 final_base_url = base_url
 if source == "project":
 if not project_id:
 raise ChatServiceError("使用项目配置时必须提供 project_id")
 try:
 project = await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 raise ChatServiceError(f"找不到项目: {project_id}")
 if not final_api_key and project.claude_api_key_encrypted:
 final_api_key = decrypt_value(project.claude_api_key_encrypted)
 if not final_base_url and project.claude_base_url:
 final_base_url = project.claude_base_url
 if not final_api_key:
 final_api_key = await aget_setting_value(SettingKeys.ANTHROPIC_API_KEY)
 if not final_base_url:
 final_base_url = await aget_setting_value(SettingKeys.ANTHROPIC_BASE_URL)
 if not final_api_key:
 raise ChatServiceError("未配置 API Key，请在系统设置或项目设置中配置")
 return ChatService(
 api_key=final_api_key,
 base_url=final_base_url,
 )
