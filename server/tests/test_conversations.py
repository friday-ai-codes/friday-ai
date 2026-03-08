"""对话 API 集成测试。
测试 Conversation CRUD + 发送消息端点。
AgentLoop 通过 mock 避免真实 LLM 调用。
鉴权开关默认关闭，无需认证即可访问。
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from rest_framework import status
from agents.core.result import AgentResult
from chat.models import Conversation, Message
from projects.models import Project
# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def test_project(db):
 """创建测试项目（不依赖 repository）。"""
 return Project.objects.create(
 name="Test Chat Project",
 description="项目用于对话测试",
 )
@pytest.fixture
def conversation(db, test_project):
 """创建测试对话。"""
 return Conversation.objects.create(
 project=test_project,
 title="测试对话",
 )
@pytest.fixture
def messages(db, conversation):
 """创建测试消息。"""
 msg1 = Message.objects.create(
 conversation=conversation,
 role=Message.Role.USER,
 content="你好",
 )
 msg2 = Message.objects.create(
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content="你好！有什么可以帮助你的？",
 )
 return [msg1, msg2]
@pytest.fixture
def mock_agent_loop:
 """Mock AgentLoop.run 返回预定义结果。"""
 mock_result = AgentResult(
 output=,
 status="completed",
 final_answer="这是 AI 的测试回复。",
 usage={"input_tokens": 100, "output_tokens": 50},
 metadata={"iterations": 1},
 )
 with (
 patch("chat.conversation_service.AgentLoop") as mock_loop_cls,
 patch("chat.conversation_service.create_provider") as mock_provider,
 patch("chat.conversation_service.aget_setting_value") as mock_setting,
 patch("services.provider_config.ProviderConfigService") as mock_pcs,
 ):
 mock_loop_instance = MagicMock
 mock_loop_instance.run = AsyncMock(return_value=mock_result)
 mock_loop_cls.return_value = mock_loop_instance
 # 模拟 ProviderConfigService.aresolve
 from services.provider_config import ResolvedProviderConfig
 from agents.llm.providers import ProviderType
 mock_pcs.aresolve = AsyncMock(return_value=ResolvedProviderConfig(
 provider_type=ProviderType.ANTHROPIC,
 api_key="test-api-key",
 base_url="https://api.anthropic.com",
 source="system",
 ))
 # 模拟系统设置
 async def fake_setting(key):
 settings_map = {
 "anthropic_api_key": "test-api-key",
 "anthropic_base_url": None,
 "anthropic_model": "claude-sonnet-4-20250514",
 }
 return settings_map.get(key)
 mock_setting.side_effect = fake_setting
 mock_provider.return_value = MagicMock
 yield {
 "loop_cls": mock_loop_cls,
 "loop_instance": mock_loop_instance,
 "provider": mock_provider,
 "setting": mock_setting,
 "provider_config_service": mock_pcs,
 "result": mock_result,
 }
# ============================================================================
# 创建对话测试
# ============================================================================
@pytest.mark.django_db
class TestCreateConversation:
 """POST /api/chat/conversations/ 测试。"""
 def test_create_conversation_success(self, api_client, test_project):
 """创建对话成功，返回 201。"""
 response = api_client.post(
 "/api/chat/conversations/",
 {"project_id": str(test_project.id)},
 format="json",
 )
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["project_id"] == str(test_project.id)
 assert response.data["title"] == "新对话"
 assert "id" in response.data
 def test_create_conversation_with_title(self, api_client, test_project):
 """创建对话时指定标题。"""
 response = api_client.post(
 "/api/chat/conversations/",
 {"project_id": str(test_project.id), "title": "我的对话"},
 format="json",
 )
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["title"] == "我的对话"
 def test_create_conversation_invalid_project(self, api_client):
 """project_id 不存在时返回 400。"""
 response = api_client.post(
 "/api/chat/conversations/",
 {"project_id": "00000000-0000-0000-0000-000000000000"},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_create_conversation_missing_project_id(self, api_client):
 """缺少 project_id 时返回 400。"""
 response = api_client.post(
 "/api/chat/conversations/",
 {},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
# ============================================================================
# 对话列表测试
# ============================================================================
@pytest.mark.django_db
class TestConversationList:
 """GET /api/chat/conversations/ 测试。"""
 def test_list_conversations(self, api_client, conversation):
 """返回对话列表。"""
 response = api_client.get("/api/chat/conversations/")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 1
 assert response.data[0]["title"] == "测试对话"
 def test_list_conversations_excludes_deleted(self, api_client, conversation):
 """已删除的对话不显示。"""
 conversation.is_deleted = True
 conversation.save
 response = api_client.get("/api/chat/conversations/")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 0
 def test_list_conversations_ordering(self, api_client, test_project):
 """对话按 updated_at 降序排列。"""
 conv1 = Conversation.objects.create(project=test_project, title="对话 1")
 conv2 = Conversation.objects.create(project=test_project, title="对话 2")
 response = api_client.get("/api/chat/conversations/")
 assert response.status_code == status.HTTP_200_OK
 assert len(response.data) == 2
 # 最新创建的排在前面
 assert response.data[0]["title"] == "对话 2"
# ============================================================================
# 对话详情测试
# ============================================================================
@pytest.mark.django_db
class TestConversationDetail:
 """GET /api/chat/conversations/{id}/ 测试。"""
 def test_get_conversation_detail(self, api_client, conversation, messages):
 """返回对话详情含消息。"""
 response = api_client.get(f"/api/chat/conversations/{conversation.id}/")
 assert response.status_code == status.HTTP_200_OK
 assert response.data["title"] == "测试对话"
 assert len(response.data["messages"]) == 2
 assert response.data["messages"][0]["role"] == "user"
 assert response.data["messages"][1]["role"] == "assistant"
 def test_get_conversation_not_found(self, api_client):
 """对话不存在返回 404。"""
 response = api_client.get(
 "/api/chat/conversations/00000000-0000-0000-0000-000000000000/"
 )
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_get_deleted_conversation_returns_404(self, api_client, conversation):
 """已删除的对话返回 404。"""
 conversation.is_deleted = True
 conversation.save
 response = api_client.get(f"/api/chat/conversations/{conversation.id}/")
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# 删除对话测试
# ============================================================================
@pytest.mark.django_db
class TestDeleteConversation:
 """DELETE /api/chat/conversations/{id}/ 测试。"""
 def test_delete_conversation(self, api_client, conversation):
 """软删除对话，返回 204。"""
 response = api_client.delete(f"/api/chat/conversations/{conversation.id}/")
 assert response.status_code == status.HTTP_204_NO_CONTENT
 # 验证软删除
 conversation.refresh_from_db
 assert conversation.is_deleted is True
 def test_delete_nonexistent_conversation(self, api_client):
 """删除不存在的对话返回 404。"""
 response = api_client.delete(
 "/api/chat/conversations/00000000-0000-0000-0000-000000000000/"
 )
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_delete_already_deleted(self, api_client, conversation):
 """已删除的对话不可再删，返回 404。"""
 conversation.is_deleted = True
 conversation.save
 response = api_client.delete(f"/api/chat/conversations/{conversation.id}/")
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# 发送消息测试
# ============================================================================
@pytest.mark.django_db
class TestSendMessage:
 """POST /api/chat/conversations/{id}/messages/ 测试。"""
 def test_send_message_success(self, api_client, conversation, mock_agent_loop):
 """发送消息获取 AI 回复。"""
 response = api_client.post(
 f"/api/chat/conversations/{conversation.id}/messages/",
 {"content": "你好"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["message"]["role"] == "assistant"
 assert response.data["message"]["content"] == "这是 AI 的测试回复。"
 assert "usage" in response.data
 # 验证 AgentLoop 被调用
 mock_agent_loop["loop_instance"].run.assert_called_once_with("你好")
 def test_send_message_conversation_not_found(self, api_client, mock_agent_loop):
 """对话不存在返回 404。"""
 response = api_client.post(
 "/api/chat/conversations/00000000-0000-0000-0000-000000000000/messages/",
 {"content": "你好"},
 format="json",
 )
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_send_message_empty_content(self, api_client, conversation, mock_agent_loop):
 """content 为空返回 400。"""
 response = api_client.post(
 f"/api/chat/conversations/{conversation.id}/messages/",
 {"content": ""},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_send_message_missing_content(self, api_client, conversation, mock_agent_loop):
 """缺少 content 返回 400。"""
 response = api_client.post(
 f"/api/chat/conversations/{conversation.id}/messages/",
 {},
 format="json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 def test_send_message_saves_messages(self, api_client, conversation, mock_agent_loop):
 """发送消息后 user 和 assistant 消息都被保存。"""
 api_client.post(
 f"/api/chat/conversations/{conversation.id}/messages/",
 {"content": "测试消息"},
 format="json",
 )
 messages = list(
 Message.objects.filter(conversation=conversation).order_by("created_at")
 )
 assert len(messages) == 2
 assert messages[0].role == "user"
 assert messages[0].content == "测试消息"
 assert messages[1].role == "assistant"
 assert messages[1].content == "这是 AI 的测试回复。"
# ============================================================================
# Context 窗口管理测试
# ============================================================================
class TestContextManager:
 """context_manager 截断函数测试。"""
 def test_truncate_messages_within_limit(self):
 """消息数不超过限制时原样返回。"""
 from chat.context_manager import truncate_messages
 messages = [
 {"role": "user", "content": "hi"},
 {"role": "assistant", "content": "hello"},
 ]
 result = truncate_messages(messages, max_messages=50)
 assert len(result) == 2
 def test_truncate_messages_exceeds_limit(self):
 """超过限制时保留最近的消息。"""
 from chat.context_manager import truncate_messages
 messages = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
 result = truncate_messages(messages, max_messages=3)
 assert len(result) == 3
 assert result[0]["content"] == "msg 7"
 assert result[2]["content"] == "msg 9"
 def test_truncate_messages_preserves_system(self):
 """system 消息始终保留在最前面。"""
 from chat.context_manager import truncate_messages
 messages = [
 {"role": "system", "content": "system prompt"},
 *[{"role": "user", "content": f"msg {i}"} for i in range(10)],
 ]
 result = truncate_messages(messages, max_messages=3)
 assert len(result) == 4 # 1 system + 3 recent
 assert result[0]["role"] == "system"
 def test_truncate_tool_results_short_content(self):
 """tool_result content 不超过限制时不截断。"""
 from chat.context_manager import truncate_tool_results
 messages = [
 {
 "role": "user",
 "content": [
 {"type": "tool_result", "content": "short result"},
 ],
 }
 ]
 result = truncate_tool_results(messages, max_chars=2000)
 assert result[0]["content"][0]["content"] == "short result"
 def test_truncate_tool_results_long_content(self):
 """tool_result content 超过限制时截断。"""
 from chat.context_manager import truncate_tool_results
 long_content = "x" * 3000
 messages = [
 {
 "role": "user",
 "content": [
 {"type": "tool_result", "content": long_content},
 ],
 }
 ]
 result = truncate_tool_results(messages, max_chars=100)
 truncated = result[0]["content"][0]["content"]
 assert len(truncated) < 3000
 assert "内容已截断" in truncated
 assert "3000" in truncated
 def test_truncate_tool_results_non_tool_unchanged(self):
 """非 tool_result 类型的 block 不受影响。"""
 from chat.context_manager import truncate_tool_results
 messages = [
 {
 "role": "user",
 "content": [
 {"type": "text", "content": "x" * 3000},
 ],
 }
 ]
 result = truncate_tool_results(messages, max_chars=100)
 assert result[0]["content"][0]["content"] == "x" * 3000
