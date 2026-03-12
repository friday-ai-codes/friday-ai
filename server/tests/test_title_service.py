"""标题生成服务测试。
测试 Phase 的异步对话标题自动生成功能：
- should_generate_title 首条消息判断
- generate_title 标题生成 + DB 更新 + 错误处理
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from chat.models import Conversation, Message
from projects.models import Project
# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def test_project(db):
 """创建测试项目。"""
 return Project.objects.create(name="Title Test Project")
@pytest.fixture
def conversation(db, test_project):
 """创建测试对话。"""
 return Conversation.objects.create(project=test_project, title="新对话")
@pytest.fixture
def first_message(db, conversation):
 """创建首条用户消息。"""
 return Message.objects.create(
 conversation=conversation,
 role=Message.Role.USER,
 content="帮我分析一下项目架构",
 )
# ============================================================================
# should_generate_title 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestShouldGenerateTitle:
 """should_generate_title 首条消息判断测试。"""
 async def test_first_message_returns_true(self, conversation, first_message):
 """对话有且仅有 1 条 user 消息时返回 True。"""
 from chat.title_service import should_generate_title
 assert await should_generate_title(str(conversation.id)) is True
 async def test_multiple_messages_returns_false(self, conversation, first_message):
 """多条 user 消息时返回 False。"""
 from chat.title_service import should_generate_title
 # 添加第二条消息
 await Message.objects.acreate(
 conversation=conversation,
 role=Message.Role.USER,
 content="第二条消息",
 )
 assert await should_generate_title(str(conversation.id)) is False
 async def test_no_messages_returns_false(self, conversation):
 """无消息时返回 False。"""
 from chat.title_service import should_generate_title
 assert await should_generate_title(str(conversation.id)) is False
# ============================================================================
# generate_title 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestGenerateTitle:
 """generate_title 标题生成测试。"""
 async def test_generate_title_success(self, conversation, first_message):
 """成功生成标题并更新数据库。"""
 from chat.title_service import generate_title
 # Mock anthropic.AsyncAnthropic 返回
 mock_text_block = MagicMock
 mock_text_block.text = "项目架构分析"
 mock_response = MagicMock
 mock_response.content = [mock_text_block]
 with (
 patch("chat.title_service.anthropic") as mock_anthropic_mod,
 patch(
 "chat.title_service.aget_setting_value",
 new_callable=AsyncMock,
 ) as mock_setting,
 ):
 mock_setting.side_effect = lambda key: {
 "anthropic_api_key": "test-key",
 "anthropic_base_url": None,
 "anthropic_model": None,
 }.get(key)
 mock_client = AsyncMock
 mock_client.messages.create = AsyncMock(return_value=mock_response)
 mock_anthropic_mod.AsyncAnthropic.return_value = mock_client
 result = await generate_title(str(conversation.id), "帮我分析一下项目架构")
 assert result == "项目架构分析"
 # 验证数据库更新
 await conversation.arefresh_from_db
 assert conversation.title == "项目架构分析"
 async def test_generate_title_api_error_returns_none(self, conversation, first_message):
 """API 错误时返回 None，不 raise。"""
 from chat.title_service import generate_title
 with (
 patch("chat.title_service.anthropic") as mock_anthropic_mod,
 patch(
 "chat.title_service.aget_setting_value",
 new_callable=AsyncMock,
 ) as mock_setting,
 ):
 mock_setting.side_effect = lambda key: {
 "anthropic_api_key": "test-key",
 "anthropic_base_url": None,
 "anthropic_model": None,
 }.get(key)
 mock_client = AsyncMock
 mock_client.messages.create = AsyncMock(side_effect=Exception("API Error"))
 mock_anthropic_mod.AsyncAnthropic.return_value = mock_client
 result = await generate_title(str(conversation.id), "test")
 assert result is None
 # 标题未变
 await conversation.arefresh_from_db
 assert conversation.title == "新对话"
 async def test_generate_title_no_api_key_returns_none(self, conversation, first_message):
 """无 API key 时返回 None。"""
 from chat.title_service import generate_title
 with patch(
 "chat.title_service.aget_setting_value",
 new_callable=AsyncMock,
 ) as mock_setting:
 mock_setting.return_value = None
 result = await generate_title(str(conversation.id), "test")
 assert result is None
 async def test_generate_title_empty_response_returns_none(self, conversation, first_message):
 """LLM 返回空内容时返回 None。"""
 from chat.title_service import generate_title
 mock_text_block = MagicMock
 mock_text_block.text = " "
 mock_response = MagicMock
 mock_response.content = [mock_text_block]
 with (
 patch("chat.title_service.anthropic") as mock_anthropic_mod,
 patch(
 "chat.title_service.aget_setting_value",
 new_callable=AsyncMock,
 ) as mock_setting,
 ):
 mock_setting.side_effect = lambda key: {
 "anthropic_api_key": "test-key",
 "anthropic_base_url": None,
 "anthropic_model": None,
 }.get(key)
 mock_client = AsyncMock
 mock_client.messages.create = AsyncMock(return_value=mock_response)
 mock_anthropic_mod.AsyncAnthropic.return_value = mock_client
 result = await generate_title(str(conversation.id), "test")
 assert result is None
