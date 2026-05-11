"""Tests for chat protocol abstraction (Phase).
Tests cover:
- ProviderProtocol abstract interface
- OpenAIChatProtocol request building and response parsing
- ChatService facade delegation
- Error handling
- Fallback logic removal verification
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from chat.protocols.base import ProviderProtocol
from chat.protocols.openai_chat import OpenAIChatProtocol
from chat.services import (
 ChatCompletionResult,
 ChatMessage,
 ChatService,
 ChatServiceError,
 Model,
 get_chat_service,
)
# --- ProviderProtocol Interface Tests ---
class TestProviderProtocolInterface:
 """验证 ProviderProtocol 是 ABC 且包含正确的抽象方法。"""
 def test_cannot_instantiate_directly(self) -> None:
 """ProviderProtocol 是抽象类，不能直接实例化。"""
 with pytest.raises(TypeError):
 ProviderProtocol(api_key="test", base_url="https://api.test.com") # type: ignore[abstract]
 def test_has_send_message_abstract_method(self) -> None:
 """ProviderProtocol 定义了 send_message 抽象方法。"""
 assert hasattr(ProviderProtocol, "send_message")
 # 验证是抽象方法
 assert getattr(ProviderProtocol.send_message, "__isabstractmethod__", False)
 def test_has_get_models_abstract_method(self) -> None:
 """ProviderProtocol 定义了 get_models 抽象方法。"""
 assert hasattr(ProviderProtocol, "get_models")
 assert getattr(ProviderProtocol.get_models, "__isabstractmethod__", False)
 def test_has_error_handling_helpers(self) -> None:
 """ProviderProtocol 提供共享的错误处理辅助方法。"""
 assert hasattr(ProviderProtocol, "_handle_http_error")
 assert hasattr(ProviderProtocol, "_handle_timeout")
 assert hasattr(ProviderProtocol, "_handle_request_error")
# --- OpenAIChatProtocol Tests ---
class TestOpenAIChatSendMessage:
 """测试 OpenAIChatProtocol.send_message 请求构建和响应解析。"""
 @pytest.fixture
 def protocol(self) -> OpenAIChatProtocol:
 return OpenAIChatProtocol(
 api_key="test-key",
 base_url="https://api.test.com",
 )
 @pytest.fixture
 def sample_messages(self) -> list[ChatMessage]:
 return [
 ChatMessage(role="system", content="You are helpful."),
 ChatMessage(role="user", content="Hello!"),
 ]
 @pytest.fixture
 def mock_chat_response(self) -> dict:
 return {
 "id": "chatcmpl-123",
 "object": "chat.completion",
 "model": "gpt-4",
 "choices": [
 {
 "index": 0,
 "message": {
 "role": "assistant",
 "content": "Hi there!",
 },
 "finish_reason": "stop",
 }
 ],
 "usage": {
 "prompt_tokens": 10,
 "completion_tokens": 5,
 "total_tokens": 15,
 },
 }
 async def test_sends_correct_request(
 self,
 protocol: OpenAIChatProtocol,
 sample_messages: list[ChatMessage],
 mock_chat_response: dict,
 ) -> None:
 """验证请求 URL、headers、payload 正确。"""
 mock_response = MagicMock(spec=httpx.Response)
 mock_response.status_code = 200
 mock_response.json.return_value = mock_chat_response
 mock_response.raise_for_status = MagicMock
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 result = await protocol.send_message(
 messages=sample_messages,
 model="gpt-4",
 max_tokens=1024,
 )
 # 验证请求 URL
 call_args = mock_client.post.call_args
 assert call_args[0][0] == "https://api.test.com/v1/chat/completions"
 # 验证 headers
 headers = call_args[1]["headers"]
 assert headers["Authorization"] == "Bearer test-key"
 assert headers["Content-Type"] == "application/json"
 # 验证 payload
 payload = call_args[1]["json"]
 assert payload["model"] == "gpt-4"
 assert payload["max_tokens"] == 1024
 assert len(payload["messages"]) == 2
 assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}
 assert payload["messages"][1] == {"role": "user", "content": "Hello!"}
 # 验证返回结果
 assert isinstance(result, ChatCompletionResult)
 assert result.content == "Hi there!"
 assert result.model == "gpt-4"
 assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
 async def test_empty_choices_raises_error(
 self,
 protocol: OpenAIChatProtocol,
 sample_messages: list[ChatMessage],
 ) -> None:
 """空 choices 数组应抛出 ChatServiceError。"""
 mock_response = MagicMock(spec=httpx.Response)
 mock_response.status_code = 200
 mock_response.json.return_value = {"choices": }
 mock_response.raise_for_status = MagicMock
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 with pytest.raises(ChatServiceError, match="API 返回空响应"):
 await protocol.send_message(sample_messages, "gpt-4")
class TestOpenAIChatGetModels:
 """测试 OpenAIChatProtocol.get_models 响应解析。"""
 @pytest.fixture
 def protocol(self) -> OpenAIChatProtocol:
 return OpenAIChatProtocol(
 api_key="test-key",
 base_url="https://api.test.com",
 )
 async def test_parses_models_response(self, protocol: OpenAIChatProtocol) -> None:
 """正确解析 /v1/models 响应。"""
 mock_response = MagicMock(spec=httpx.Response)
 mock_response.status_code = 200
 mock_response.json.return_value = {
 "data": [
 {"id": "gpt-4", "created": 1687882410},
 {"id": "gpt-3.5-turbo", "created": 1677610602},
 ]
 }
 mock_response.raise_for_status = MagicMock
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.get = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 models = await protocol.get_models
 # 验证请求
 call_args = mock_client.get.call_args
 assert call_args[0][0] == "https://api.test.com/v1/models"
 # 验证结果
 assert len(models) == 2
 assert isinstance(models[0], Model)
 assert models[0].id == "gpt-4"
 assert models[0].name == "gpt-4"
 assert models[0].created == 1687882410
 assert models[1].id == "gpt-3.5-turbo"
class TestOpenAIChatErrorHandling:
 """测试 OpenAIChatProtocol 错误处理。"""
 @pytest.fixture
 def protocol(self) -> OpenAIChatProtocol:
 return OpenAIChatProtocol(
 api_key="test-key",
 base_url="https://api.test.com",
 )
 @pytest.fixture
 def sample_messages(self) -> list[ChatMessage]:
 return [ChatMessage(role="user", content="Hello")]
 async def test_401_unauthorized(
 self, protocol: OpenAIChatProtocol, sample_messages: list[ChatMessage]
 ) -> None:
 """401 错误应返回 'API Key 无效或已过期'。"""
 mock_response = MagicMock(spec=httpx.Response)
 mock_response.status_code = 401
 mock_response.json.return_value = {"error": {"message": "Invalid API key"}}
 http_error = httpx.HTTPStatusError("", request=MagicMock, response=mock_response)
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(side_effect=http_error)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 with pytest.raises(ChatServiceError, match="API Key 无效或已过期"):
 await protocol.send_message(sample_messages, "gpt-4")
 async def test_403_forbidden(
 self, protocol: OpenAIChatProtocol, sample_messages: list[ChatMessage]
 ) -> None:
 """403 错误应返回 'API Key 没有访问权限'。"""
 mock_response = MagicMock(spec=httpx.Response)
 mock_response.status_code = 403
 http_error = httpx.HTTPStatusError("", request=MagicMock, response=mock_response)
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(side_effect=http_error)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 with pytest.raises(ChatServiceError, match="API Key 没有访问权限"):
 await protocol.send_message(sample_messages, "gpt-4")
 async def test_429_rate_limit(
 self, protocol: OpenAIChatProtocol, sample_messages: list[ChatMessage]
 ) -> None:
 """429 错误应返回 '请求过于频繁'。"""
 mock_response = MagicMock(spec=httpx.Response)
 mock_response.status_code = 429
 http_error = httpx.HTTPStatusError("", request=MagicMock, response=mock_response)
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(side_effect=http_error)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 with pytest.raises(ChatServiceError, match="请求过于频繁"):
 await protocol.send_message(sample_messages, "gpt-4")
 async def test_timeout_error(
 self, protocol: OpenAIChatProtocol, sample_messages: list[ChatMessage]
 ) -> None:
 """超时应返回 '请求超时'。"""
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 with pytest.raises(ChatServiceError, match="请求超时"):
 await protocol.send_message(sample_messages, "gpt-4")
 async def test_network_error(
 self, protocol: OpenAIChatProtocol, sample_messages: list[ChatMessage]
 ) -> None:
 """网络错误应返回 '网络请求失败'。"""
 with patch("chat.protocols.openai_chat.httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(
 side_effect=httpx.RequestError("Connection refused", request=MagicMock)
 )
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=False)
 mock_client_cls.return_value = mock_client
 with pytest.raises(ChatServiceError, match="网络请求失败"):
 await protocol.send_message(sample_messages, "gpt-4")
# --- ChatService Facade Tests ---
class TestChatServiceDelegation:
 """验证 ChatService 正确委托给协议实例。"""
 async def test_chat_completion_delegates_to_protocol(self) -> None:
 """chat_completion 应委托给 protocol.send_message。"""
 mock_protocol = AsyncMock(spec=ProviderProtocol)
 expected_result = ChatCompletionResult(content="Hello!", model="gpt-4")
 mock_protocol.send_message = AsyncMock(return_value=expected_result)
 service = ChatService(protocol=mock_protocol)
 messages = [ChatMessage(role="user", content="Hi")]
 result = await service.chat_completion(messages=messages, model="gpt-4", max_tokens=1024)
 mock_protocol.send_message.assert_called_once_with(messages, "gpt-4", 1024)
 assert result is expected_result
 async def test_get_models_delegates_to_protocol(self) -> None:
 """get_models 应委托给 protocol.get_models。"""
 mock_protocol = AsyncMock(spec=ProviderProtocol)
 expected_models = [Model(id="gpt-4", name="gpt-4")]
 mock_protocol.get_models = AsyncMock(return_value=expected_models)
 service = ChatService(protocol=mock_protocol)
 result = await service.get_models
 mock_protocol.get_models.assert_called_once
 assert result is expected_models
# --- Fallback Logic Removal Tests ---
class TestFallbackLogicRemoved:
 """验证回退逻辑已被完全移除。"""
 def test_no_legacy_protocol_error_method(self) -> None:
 """ChatService 不应有 _is_legacy_protocol_error 方法。"""
 assert not hasattr(ChatService, "_is_legacy_protocol_error")
 def test_no_responses_api_method(self) -> None:
 """ChatService 不应有 _chat_via_responses_api 方法。"""
 assert not hasattr(ChatService, "_chat_via_responses_api")
 def test_no_extract_responses_content_method(self) -> None:
 """ChatService 不应有 _extract_responses_api_content 方法。"""
 assert not hasattr(ChatService, "_extract_responses_api_content")
 def test_no_get_headers_method(self) -> None:
 """ChatService 不应有 _get_headers 方法（已移至协议类）。"""
 assert not hasattr(ChatService, "_get_headers")
# --- Provider Type Configuration Tests (Plan, updated Phase) ---
class TestSettingKeysProviderConfig:
 """验证 SettingKeys 包含新的 Provider 配置键（Phase）。"""
 def test_default_provider_type_key_removed(self) -> None:
 """SettingKeys.DEFAULT_PROVIDER_TYPE 已硬删（Phase Plan）。"""
 from system.models import SettingKeys as SK
 assert not hasattr(SK, "DEFAULT_PROVIDER_TYPE")
 def test_old_keys_removed(self) -> None:
 """旧的 PROVIDER_TYPE 和 LLM_PROVIDER_TYPE 已删除。"""
 from system.models import SettingKeys as SK
 assert not hasattr(SK, "PROVIDER_TYPE")
 assert not hasattr(SK, "LLM_PROVIDER_TYPE")
class TestValidProviderTypes:
 """验证 VALID_PROVIDER_TYPES 常量。"""
 def test_contains_exactly_four_values(self) -> None:
 """VALID_PROVIDER_TYPES 应恰好包含四个值。"""
 from chat.services import VALID_PROVIDER_TYPES
 assert len(VALID_PROVIDER_TYPES) == 4
 def test_contains_expected_values(self) -> None:
 """VALID_PROVIDER_TYPES 应包含四种协议类型。"""
 from chat.services import VALID_PROVIDER_TYPES
 expected = {"openai_chat", "openai_response", "anthropic", "gemini"}
 assert VALID_PROVIDER_TYPES == expected
class TestCreateProtocol:
 """验证 _create_protocol 工厂辅助函数。"""
 def test_openai_chat_returns_correct_protocol(self) -> None:
 """openai_chat 应返回 OpenAIChatProtocol 实例。"""
 from chat.services import _create_protocol
 protocol = _create_protocol("openai_chat", "test-key", "https://api.test.com")
 assert isinstance(protocol, OpenAIChatProtocol)
 assert protocol.api_key == "test-key"
 assert protocol.base_url == "https://api.test.com"
 def test_invalid_type_raises_error(self) -> None:
 """非法 provider_type 应抛出 ChatServiceError 并列出合法值。"""
 from chat.services import _create_protocol
 with pytest.raises(ChatServiceError, match="不支持的 provider_type") as exc_info:
 _create_protocol("invalid_type", "key", "url")
 error_msg = str(exc_info.value)
 assert "anthropic" in error_msg
 assert "gemini" in error_msg
 assert "openai_chat" in error_msg
 assert "openai_response" in error_msg
 def test_unimplemented_openai_response_raises_error(self) -> None:
 """openai_response 合法但尚未实现，应给友好错误。"""
 from chat.services import _create_protocol
 with pytest.raises(ChatServiceError, match="尚未实现"):
 _create_protocol("openai_response", "key", "url")
 def test_unimplemented_anthropic_raises_error(self) -> None:
 """anthropic 合法但尚未实现，应给友好错误。"""
 from chat.services import _create_protocol
 with pytest.raises(ChatServiceError, match="尚未实现"):
 _create_protocol("anthropic", "key", "url")
 def test_unimplemented_gemini_raises_error(self) -> None:
 """gemini 合法但尚未实现，应给友好错误。"""
 from chat.services import _create_protocol
 with pytest.raises(ChatServiceError, match="尚未实现"):
 _create_protocol("gemini", "key", "url")
class TestFactoryProviderTypeRouting:
 """验证工厂函数的 provider_type 路由。"""
 @patch("chat.services._load_system_credential_sync")
 def test_factory_default_provider_type(self, mock_load_cred: MagicMock) -> None:
 """无 DEFAULT_PROVIDER_TYPE 设置时默认使用 openai_chat。"""
 mock_load_cred.return_value = ("test-api-key", "https://api.test.com")
 service = get_chat_service(source="system")
 assert isinstance(service, ChatService)
 # 验证内部协议是 OpenAIChatProtocol
 assert isinstance(service._protocol, OpenAIChatProtocol)
 @patch("chat.services._load_system_credential_sync")
 def test_factory_reads_provider_type(self, mock_load_cred: MagicMock) -> None:
 """工厂函数使用系统凭证创建服务。"""
 mock_load_cred.return_value = ("test-api-key", "https://api.test.com")
 service = get_chat_service(source="system")
 assert isinstance(service._protocol, OpenAIChatProtocol)
