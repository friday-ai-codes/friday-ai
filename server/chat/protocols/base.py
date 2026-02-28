"""ProviderProtocol: AI Provider 协议基类。
定义所有协议实现必须遵循的接口，以及共享的错误处理逻辑。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
import httpx
from chat.services import ChatCompletionResult, ChatMessage, ChatServiceError, Model
# 与 ChatService 保持一致的默认超时
DEFAULT_TIMEOUT = 30.0
class ProviderProtocol(ABC):
 """AI Provider 协议基类。
 每个协议实现封装完整的请求生命周期：
 - 构建请求头和请求体
 - 发送 HTTP 请求
 - 解析响应
 - 统一错误处理
 """
 def __init__(
 self,
 api_key: str,
 base_url: str,
 timeout: float = DEFAULT_TIMEOUT,
 ) -> None:
 self.api_key = api_key
 self.base_url = base_url.rstrip("/")
 self.timeout = timeout
 @abstractmethod
 async def send_message(
 self,
 messages: list[ChatMessage],
 model: str,
 max_tokens: int = 4096,
 ) -> ChatCompletionResult:
 """发送对话请求。
 Args:
 messages: 对话消息列表
 model: 模型 ID
 max_tokens: 最大输出 token 数
 Returns:
 ChatCompletionResult: 对话结果
 Raises:
 ChatServiceError: API 调用失败时
 """
 ...
 @abstractmethod
 async def get_models(self) -> list[Model]:
 """获取可用模型列表。
 Returns:
 list[Model]: 可用模型列表
 Raises:
 ChatServiceError: API 调用失败时
 """
 ...
 def _handle_http_error(self, e: httpx.HTTPStatusError) -> ChatServiceError:
 """统一 HTTP 错误处理。子类可覆写添加协议特定逻辑。"""
 status_code = e.response.status_code
 if status_code == 401:
 return ChatServiceError("API Key 无效或已过期")
 elif status_code == 403:
 return ChatServiceError("API Key 没有访问权限")
 elif status_code == 429:
 return ChatServiceError("请求过于频繁，请稍后重试")
 try:
 error_data = e.response.json
 error = error_data.get("error", {})
 error_msg = error.get("message", str(e)) if isinstance(error, dict) else str(error)
 except Exception:
 error_msg = str(e)
 return ChatServiceError(f"API 请求失败: {error_msg}")
 def _handle_timeout(self) -> ChatServiceError:
 """返回超时错误。"""
 return ChatServiceError("请求超时，请检查网络连接和 Base URL 配置")
 def _handle_request_error(self, e: httpx.RequestError) -> ChatServiceError:
 """返回网络请求错误。"""
 return ChatServiceError(f"网络请求失败: {e!s}")
