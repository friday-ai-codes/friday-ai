"""ConversationService 扩展集成测试：角色 + 模型。
测试 Phase 新增的角色参数传递和对话级模型选择功能。
使用 AsyncClient + mock AgentLoop.run 避免真实 LLM 调用。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch
import pytest
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken
User = get_user_model
# ============================================================================
# Mock 数据
# ============================================================================
@dataclass
class MockAgentResult:
 """模拟 AgentResult。"""
 output: list = field(default_factory=list)
 final_answer: str = "mock answer"
 status: str = "completed"
 usage: dict = field(default_factory=lambda: {"input_tokens": 10, "output_tokens": 5})
 metadata: dict = field(default_factory=lambda: {"iterations": 1, "tool_calls_count": 0})
# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
async def user_and_token(db):
 """创建测试用户并生成 JWT token。"""
 user = await User.objects.acreate_user(
 username="testuser111",
 password="testpass123",
 )
 token = RefreshToken.for_user(user)
 return user, str(token.access_token)
@pytest.fixture
def auth_headers(user_and_token):
 """带 Authorization header 的 dict。"""
 _, access_token = user_and_token
 return {"authorization": f"Bearer {access_token}"}
# ============================================================================
# 创建对话 + 模型选择测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestCreateConversationWithModel:
 """创建对话时指定模型的测试。"""
 async def test_create_with_model(self, auth_headers, project):
 """创建对话时指定 model 参数，返回中包含 model 字段。"""
 client = AsyncClient
 payload = {
 "project_id": str(project.id),
 "title": "测试对话",
 "model": "claude-sonnet-4-20250514",
 }
 resp = await client.post(
 "/api/chat/conversations/",
 data=payload,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 201
 data = resp.json
 assert data["model"] == "claude-sonnet-4-20250514"
 async def test_create_without_model(self, auth_headers, project):
 """创建对话不指定 model，默认为空字符串。"""
 client = AsyncClient
 payload = {
 "project_id": str(project.id),
 }
 resp = await client.post(
 "/api/chat/conversations/",
 data=payload,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 201
 data = resp.json
 assert data["model"] == ""
# ============================================================================
# 发送消息 + 角色测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestSendMessageWithRole:
 """发送消息时传递角色参数的测试。"""
 async def test_send_message_with_role_pm(self, auth_headers, project):
 """发送消息时指定 role="pm"，mock 验证 _build_system_prompt 收到角色参数。"""
 from chat.conversation_service import ConversationService
 # 创建对话
 conversation = await ConversationService.create_conversation(
 project_id=str(project.id),
 title="角色测试对话",
 )
 client = AsyncClient
 payload = {
 "content": "项目进度如何？",
 "role": "pm",
 }
 mock_result = MockAgentResult
 with patch(
 "chat.conversation_service.AgentLoop"
 ) as MockLoop, patch(
 "chat.conversation_service._build_system_prompt",
 wraps=__import__(
 "chat.conversation_service", fromlist=["_build_system_prompt"]
 )._build_system_prompt,
 ) as mock_prompt:
 mock_instance = MockLoop.return_value
 mock_instance.run = AsyncMock(return_value=mock_result)
 # mock aget_setting_value 以避免 DB 查询
 with patch(
 "chat.conversation_service.aget_setting_value",
 new_callable=AsyncMock,
 side_effect=lambda key: {
 "anthropic_api_key": "test-key",
 "anthropic_base_url": None,
 "anthropic_model": "default-model",
 }.get(key),
 ), patch(
 "services.provider_config.ProviderConfigService"
 ) as mock_pcs:
 from agents.llm.providers import ProviderType
 from services.provider_config import ResolvedProviderConfig
 mock_pcs.aresolve = AsyncMock(return_value=ResolvedProviderConfig(
 provider_type=ProviderType.ANTHROPIC,
 api_key="test-key",
 base_url="https://api.anthropic.com",
 source="system",
 ))
 resp = await client.post(
 f"/api/chat/conversations/{conversation.id}/messages/",
 data=payload,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 200
 # 验证 _build_system_prompt 被调用时传入了 role="pm"
 mock_prompt.assert_called_once
 call_kwargs = mock_prompt.call_args
 assert call_kwargs[1].get("role") == "pm" or (
 len(call_kwargs[0]) >= 2 and call_kwargs[0][1] == "pm"
 )
# ============================================================================
# 对话级模型选择测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestConversationModelSelection:
 """对话级 LLM 模型选择测试。"""
 async def test_send_message_uses_conversation_model(self, auth_headers, project):
 """对话指定了模型时，create_provider 使用该模型。"""
 from chat.conversation_service import ConversationService
 # 创建指定模型的对话
 conversation = await ConversationService.create_conversation(
 project_id=str(project.id),
 title="模型测试对话",
 model="claude-opus-4-20250514",
 )
 client = AsyncClient
 payload = {"content": "hello"}
 mock_result = MockAgentResult
 with patch(
 "chat.conversation_service.AgentLoop"
 ) as MockLoop, patch(
 "chat.conversation_service.create_provider"
 ) as mock_create_provider, patch(
 "chat.conversation_service.aget_setting_value",
 new_callable=AsyncMock,
 side_effect=lambda key: {
 "anthropic_api_key": "test-key",
 "anthropic_base_url": None,
 "anthropic_model": "default-model",
 }.get(key),
 ), patch(
 "services.provider_config.ProviderConfigService"
 ) as mock_pcs:
 from agents.llm.providers import ProviderType
 from services.provider_config import ResolvedProviderConfig
 mock_pcs.aresolve = AsyncMock(return_value=ResolvedProviderConfig(
 provider_type=ProviderType.ANTHROPIC,
 api_key="test-key",
 base_url="https://api.anthropic.com",
 source="system",
 ))
 mock_create_provider.return_value = "mock_provider"
 mock_instance = MockLoop.return_value
 mock_instance.run = AsyncMock(return_value=mock_result)
 resp = await client.post(
 f"/api/chat/conversations/{conversation.id}/messages/",
 data=payload,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 200
 # 验证 create_provider 使用了对话级模型
 mock_create_provider.assert_called_once
 call_kwargs = mock_create_provider.call_args
 assert call_kwargs[1]["model"] == "claude-opus-4-20250514"
 async def test_send_message_falls_back_to_system_model(self, auth_headers, project):
 """对话未指定模型时，使用系统默认模型。"""
 from chat.conversation_service import ConversationService
 # 创建未指定模型的对话
 conversation = await ConversationService.create_conversation(
 project_id=str(project.id),
 title="默认模型对话",
 )
 client = AsyncClient
 payload = {"content": "hello"}
 mock_result = MockAgentResult
 with patch(
 "chat.conversation_service.AgentLoop"
 ) as MockLoop, patch(
 "chat.conversation_service.create_provider"
 ) as mock_create_provider, patch(
 "chat.conversation_service.aget_setting_value",
 new_callable=AsyncMock,
 side_effect=lambda key: {
 "anthropic_api_key": "test-key",
 "anthropic_base_url": None,
 "anthropic_model": "system-default-model",
 }.get(key),
 ), patch(
 "services.provider_config.ProviderConfigService"
 ) as mock_pcs:
 from agents.llm.providers import ProviderType
 from services.provider_config import ResolvedProviderConfig
 mock_pcs.aresolve = AsyncMock(return_value=ResolvedProviderConfig(
 provider_type=ProviderType.ANTHROPIC,
 api_key="test-key",
 base_url="https://api.anthropic.com",
 source="system",
 ))
 mock_create_provider.return_value = "mock_provider"
 mock_instance = MockLoop.return_value
 mock_instance.run = AsyncMock(return_value=mock_result)
 resp = await client.post(
 f"/api/chat/conversations/{conversation.id}/messages/",
 data=payload,
 content_type="application/json",
 headers=auth_headers,
 )
 assert resp.status_code == 200
 # 验证使用系统默认模型（对话 model 为空）
 mock_create_provider.assert_called_once
 call_kwargs = mock_create_provider.call_args
 assert call_kwargs[1]["model"] == "system-default-model"
