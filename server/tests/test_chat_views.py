"""ChatCompletionsView 和 ModelsView HTTP 集成测试。
验证 chat 端点的端到端 HTTP 行为（mock LLM service）：
- 认证控制（401）
- 参数校验（400）
- 成功响应（200）
- 业务错误（ChatServiceError → 400）
- 系统错误（Exception → 500）
"""
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken
from system.models import SettingKeys, SystemSetting
User = get_user_model
# ---------------------------------------------------------------------------
# Mock 数据结构
# ---------------------------------------------------------------------------
@dataclass
class MockModel:
 """模拟 chat.services.Model 数据类。"""
 id: str
 name: str
 created: int
@dataclass
class MockCompletionResult:
 """模拟 chat.services.ChatCompletionResult 数据类。"""
 content: str
 model: str
 usage: dict
def make_mock_service(
 completion_result=None,
 models_result=None,
 raise_chat_error=None,
 raise_unexpected=None,
):
 """构造 mock ChatService。
 Args:
 completion_result: 自定义 chat_completion 返回值
 models_result: 自定义 get_models 返回值
 raise_chat_error: 让 service 方法抛出 ChatServiceError
 raise_unexpected: 让 service 方法抛出 Exception
 """
 from chat.services import ChatServiceError
 service = MagicMock
 if raise_chat_error:
 service.chat_completion = AsyncMock(
 side_effect=ChatServiceError(raise_chat_error)
 )
 service.get_models = AsyncMock(
 side_effect=ChatServiceError(raise_chat_error)
 )
 elif raise_unexpected:
 service.chat_completion = AsyncMock(
 side_effect=Exception(raise_unexpected)
 )
 service.get_models = AsyncMock(side_effect=Exception(raise_unexpected))
 else:
 service.chat_completion = AsyncMock(
 return_value=completion_result
 or MockCompletionResult(
 content="Hello!",
 model="gpt-4",
 usage={
 "prompt_tokens": 10,
 "completion_tokens": 5,
 "total_tokens": 15,
 },
 )
 )
 service.get_models = AsyncMock(
 return_value=models_result
 or [
 MockModel(id="gpt-4", name="", created=1700000000),
 ]
 )
 return service
# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
async def user_and_token(db):
 """创建测试用户并生成 JWT token。"""
 user = await User.objects.acreate_user(
 username="testuser",
 password="testpass123",
 )
 token = await sync_to_async(RefreshToken.for_user)(user)
 return user, str(token.access_token)
@pytest.fixture
def auth_headers(user_and_token):
 """返回带 Authorization header 的 dict（供 headers= 参数使用）。"""
 _, access_token = user_and_token
 return {"authorization": f"Bearer {access_token}"}
# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
COMPLETIONS_URL = "/api/chat/completions/"
MODELS_URL = "/api/chat/models/"
VALID_PAYLOAD = {
 "model": "gpt-4",
 "messages": [{"role": "user", "content": "Hello"}],
}
# ---------------------------------------------------------------------------
# ChatCompletionsView 测试
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestChatCompletionsView:
 """ChatCompletionsView POST 端点 HTTP 集成测试。"""
 async def test_unauthenticated_returns_401(self):
 """未认证 POST 请求返回 401 Unauthorized。"""
 client = AsyncClient
 resp = await client.post(
 COMPLETIONS_URL,
 data=VALID_PAYLOAD,
 content_type="application/json",
 )
 assert resp.status_code == 401
 async def test_valid_request_returns_200(self, auth_headers):
 """认证用户发送合法请求返回 200 和 AI 响应内容。"""
 client = AsyncClient
 mock_svc = make_mock_service
 with patch(
 "chat.views.aget_chat_service",
 AsyncMock(return_value=mock_svc),
 ):
 resp = await client.post(
 COMPLETIONS_URL,
 data=VALID_PAYLOAD,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 200
 data = resp.json
 assert "content" in data
 assert data["content"] == "Hello!"
 assert "model" in data
 assert data["model"] == "gpt-4"
 assert "usage" in data
 assert data["usage"]["total_tokens"] == 15
 async def test_missing_model_returns_400(self, auth_headers):
 """缺少必填字段 model 返回 400 Bad Request。"""
 client = AsyncClient
 payload = {"messages": [{"role": "user", "content": "Hello"}]}
 resp = await client.post(
 COMPLETIONS_URL,
 data=payload,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 400
 async def test_missing_messages_returns_400(self, auth_headers):
 """缺少必填字段 messages 返回 400 Bad Request。"""
 client = AsyncClient
 payload = {"model": "gpt-4"}
 resp = await client.post(
 COMPLETIONS_URL,
 data=payload,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 400
 async def test_chat_service_error_returns_400(self, auth_headers):
 """ChatServiceError 返回 400 Bad Request。"""
 client = AsyncClient
 mock_svc = make_mock_service(raise_chat_error="API key invalid")
 with patch(
 "chat.views.aget_chat_service",
 AsyncMock(return_value=mock_svc),
 ):
 resp = await client.post(
 COMPLETIONS_URL,
 data=VALID_PAYLOAD,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 400
 assert "error" in resp.json
 async def test_unexpected_error_returns_500(self, auth_headers):
 """意外异常返回 500 Internal Server Error。"""
 client = AsyncClient
 with patch(
 "chat.views.aget_chat_service",
 AsyncMock(side_effect=Exception("unexpected")),
 ):
 resp = await client.post(
 COMPLETIONS_URL,
 data=VALID_PAYLOAD,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 500
 assert "error" in resp.json
# ---------------------------------------------------------------------------
# ModelsView 测试
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
class TestModelsView:
 """ModelsView GET 端点 HTTP 集成测试。"""
 async def test_unauthenticated_returns_401(self):
 """未认证 GET 请求返回 401 Unauthorized（鉴权开关开启时）。"""
 # ChatAuthPermission 默认放行；需要开启鉴权开关才能检查认证
 await SystemSetting.objects.acreate(
 key=SettingKeys.CHAT_AUTH_ENABLED, value="true"
 )
 client = AsyncClient
 resp = await client.get(MODELS_URL)
 assert resp.status_code == 401
 async def test_valid_request_returns_200(self, auth_headers):
 """认证用户请求返回 200 和模型列表。"""
 client = AsyncClient
 mock_svc = make_mock_service
 with patch(
 "chat.views.aget_chat_service",
 AsyncMock(return_value=mock_svc),
 ):
 resp = await client.get(MODELS_URL, headers=auth_headers)
 assert resp.status_code == 200
 data = resp.json
 assert "models" in data
 assert len(data["models"]) > 0
 assert data["models"][0]["id"] == "gpt-4"
 assert data["models"][0]["name"] == ""
 async def test_chat_service_error_returns_400(self, auth_headers):
 """ChatServiceError 返回 400 Bad Request。"""
 client = AsyncClient
 mock_svc = make_mock_service(raise_chat_error="Service unavailable")
 with patch(
 "chat.views.aget_chat_service",
 AsyncMock(return_value=mock_svc),
 ):
 resp = await client.get(MODELS_URL, headers=auth_headers)
 assert resp.status_code == 400
