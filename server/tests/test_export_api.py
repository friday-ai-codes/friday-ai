"""飞书文档导出 API 测试。
覆盖 Project.feishu_doc_folder_token 字段、ExportToFeishuView endpoint、
以及 markdown_to_blocks 转换层。
"""
import uuid
from unittest.mock import AsyncMock, patch
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from chat.models import Conversation, Message
from projects.models import Project
User = get_user_model
# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def conversation_with_messages(db):
 """创建 Project + Conversation + Messages 用于导出测试。"""
 project = Project.objects.create(
 name="导出测试项目",
 feishu_doc_folder_token="test_folder_token",
 feishu_app_id="cli_test",
 feishu_app_secret_encrypted="test_secret",
 )
 conversation = Conversation.objects.create(
 project=project,
 title="测试对话",
 )
 msg_assistant_1 = Message.objects.create(
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content="AAA",
 )
 msg_assistant_2 = Message.objects.create(
 conversation=conversation,
 role=Message.Role.ASSISTANT,
 content="BBB",
 )
 msg_user = Message.objects.create(
 conversation=conversation,
 role=Message.Role.USER,
 content="用户消息",
 )
 return {
 "project": project,
 "conversation": conversation,
 "msg_assistant_1": msg_assistant_1,
 "msg_assistant_2": msg_assistant_2,
 "msg_user": msg_user,
 }
@pytest.fixture
def export_client(db):
 """创建已认证的 API 客户端。"""
 user = User.objects.create_user(
 username="export_test_user",
 email="export@test.com",
 password="testpass123",
 )
 client = APIClient
 client.force_authenticate(user=user)
 return client
# ============================================================================
# Task 1: Project model 字段测试
# ============================================================================
@pytest.mark.django_db
class TestProjectFolderTokenField:
 """Project.feishu_doc_folder_token 字段测试。"""
 def test_project_folder_token_field(self):
 """Project 实例可设置和读取 feishu_doc_folder_token。"""
 project = Project.objects.create(
 name="test",
 feishu_doc_folder_token="my_folder_token",
 )
 project.refresh_from_db
 assert project.feishu_doc_folder_token == "my_folder_token"
 def test_project_folder_token_default_blank(self):
 """新建 Project 的 feishu_doc_folder_token 默认为空字符串。"""
 project = Project.objects.create(name="test_default")
 project.refresh_from_db
 assert project.feishu_doc_folder_token == ""
 def test_fixture_creates_conversation_and_messages(self, conversation_with_messages):
 """fixture 创建 conversation + assistant message 成功。"""
 data = conversation_with_messages
 assert data["conversation"].project == data["project"]
 assert data["msg_assistant_1"].role == Message.Role.ASSISTANT
 assert data["msg_assistant_2"].role == Message.Role.ASSISTANT
 assert data["msg_user"].role == Message.Role.USER
# ============================================================================
# Task 2: ExportToFeishuView API 测试
# ============================================================================
MOCK_DOC_RESULT = {
 "document_id": "doxcnTEST",
 "url": "https://feishu.cn/docx/doxcnTEST",
}
@pytest.mark.django_db
class TestExportToFeishuView:
 """ExportToFeishuView endpoint 测试。"""
 @patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
 new_callable=AsyncMock,
 )
 def test_export_success(self, mock_create_client, export_client, conversation_with_messages):
 """POST 有效 message_ids + title -> 200 + {document_id, url, title}。"""
 mock_client = AsyncMock
 mock_client.create_document.return_value = MOCK_DOC_RESULT
 mock_create_client.return_value = mock_client
 data = conversation_with_messages
 conv_id = str(data["conversation"].id)
 msg_ids = [str(data["msg_assistant_1"].id), str(data["msg_assistant_2"].id)]
 response = export_client.post(
 f"/api/chat/conversations/{conv_id}/export-to-feishu/",
 {"message_ids": msg_ids, "title": "测试文档"},
 format="json",
 )
 assert response.status_code == 200
 assert response.data["document_id"] == "doxcnTEST"
 assert response.data["url"] == "https://feishu.cn/docx/doxcnTEST"
 assert response.data["title"] == "测试文档"
 @patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
 new_callable=AsyncMock,
 )
 def test_export_filters_cross_conversation_messages(
 self, mock_create_client, export_client, conversation_with_messages
 ):
 """message_ids 包含其他对话的消息 ID -> 被过滤，仅返回当前对话的 assistant 消息。"""
 mock_client = AsyncMock
 mock_client.create_document.return_value = MOCK_DOC_RESULT
 mock_create_client.return_value = mock_client
 data = conversation_with_messages
 conv_id = str(data["conversation"].id)
 # 创建另一个对话及其消息
 other_conv = Conversation.objects.create(
 project=data["project"],
 title="其他对话",
 )
 other_msg = Message.objects.create(
 conversation=other_conv,
 role=Message.Role.ASSISTANT,
 content="OTHER",
 )
 msg_ids = [
 str(data["msg_assistant_1"].id),
 str(other_msg.id), # 不属于当前对话
 ]
 response = export_client.post(
 f"/api/chat/conversations/{conv_id}/export-to-feishu/",
 {"message_ids": msg_ids, "title": "测试文档"},
 format="json",
 )
 assert response.status_code == 200
 # 验证 create_document 调用参数中只包含当前对话的消息内容
 call_args = mock_client.create_document.call_args
 assert "AAA" in call_args.kwargs.get("content", call_args[1].get("content", ""))
 assert "OTHER" not in call_args.kwargs.get("content", call_args[1].get("content", ""))
 @patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
 new_callable=AsyncMock,
 )
 def test_export_only_user_messages_returns_400(
 self, mock_create_client, export_client, conversation_with_messages
 ):
 """message_ids 仅包含 user 角色消息 -> 400 '未找到可导出的消息'。"""
 data = conversation_with_messages
 conv_id = str(data["conversation"].id)
 response = export_client.post(
 f"/api/chat/conversations/{conv_id}/export-to-feishu/",
 {"message_ids": [str(data["msg_user"].id)], "title": "测试文档"},
 format="json",
 )
 assert response.status_code == 400
 assert "未找到可导出的消息" in response.data["error"]
 def test_export_not_configured_returns_400(self, export_client, db):
 """未配置 folder_token -> 400 + error_type='not_configured'。"""
 project = Project.objects.create(
 name="无配置项目",
 feishu_doc_folder_token="",
 feishu_app_id="cli_test",
 feishu_app_secret_encrypted="test_secret",
 )
 conv = Conversation.objects.create(project=project, title="测试")
 msg = Message.objects.create(
 conversation=conv,
 role=Message.Role.ASSISTANT,
 content="内容",
 )
 response = export_client.post(
 f"/api/chat/conversations/{conv.id}/export-to-feishu/",
 {"message_ids": [str(msg.id)], "title": "测试文档"},
 format="json",
 )
 assert response.status_code == 400
 assert response.data["error_type"] == "not_configured"
 @patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
 new_callable=AsyncMock,
 )
 def test_export_permission_denied_returns_403(
 self, mock_create_client, export_client, conversation_with_messages
 ):
 """PermissionDeniedError -> 403 + error_type='permission_denied'。"""
 from services.feishu_doc import PermissionDeniedError
 mock_client = AsyncMock
 mock_client.create_document.side_effect = PermissionDeniedError("无权限")
 mock_create_client.return_value = mock_client
 data = conversation_with_messages
 conv_id = str(data["conversation"].id)
 response = export_client.post(
 f"/api/chat/conversations/{conv_id}/export-to-feishu/",
 {
 "message_ids": [str(data["msg_assistant_1"].id)],
 "title": "测试文档",
 },
 format="json",
 )
 assert response.status_code == 403
 assert response.data["error_type"] == "permission_denied"
 @patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
 new_callable=AsyncMock,
 )
 def test_export_api_error_returns_502(
 self, mock_create_client, export_client, conversation_with_messages
 ):
 """FeishuDocAPIError -> 502 + error_type='api_error'。"""
 from services.feishu_doc import FeishuDocAPIError
 mock_client = AsyncMock
 mock_client.create_document.side_effect = FeishuDocAPIError("API 错误")
 mock_create_client.return_value = mock_client
 data = conversation_with_messages
 conv_id = str(data["conversation"].id)
 response = export_client.post(
 f"/api/chat/conversations/{conv_id}/export-to-feishu/",
 {
 "message_ids": [str(data["msg_assistant_1"].id)],
 "title": "测试文档",
 },
 format="json",
 )
 assert response.status_code == 502
 assert response.data["error_type"] == "api_error"
 def test_export_conversation_not_found_returns_404(self, export_client, db):
 """对话不存在 -> 404。"""
 fake_id = str(uuid.uuid4)
 response = export_client.post(
 f"/api/chat/conversations/{fake_id}/export-to-feishu/",
 {"message_ids": [str(uuid.uuid4)], "title": "测试文档"},
 format="json",
 )
 assert response.status_code == 404
 @patch(
 "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
 new_callable=AsyncMock,
 )
 def test_export_messages_joined_with_separator(
 self, mock_create_client, export_client, conversation_with_messages
 ):
 """多条消息用 \\n\\n---\\n\\n 分隔拼接。"""
 mock_client = AsyncMock
 mock_client.create_document.return_value = MOCK_DOC_RESULT
 mock_create_client.return_value = mock_client
 data = conversation_with_messages
 conv_id = str(data["conversation"].id)
 msg_ids = [str(data["msg_assistant_1"].id), str(data["msg_assistant_2"].id)]
 response = export_client.post(
 f"/api/chat/conversations/{conv_id}/export-to-feishu/",
 {"message_ids": msg_ids, "title": "测试文档"},
 format="json",
 )
 assert response.status_code == 200
 call_args = mock_client.create_document.call_args
 content = call_args.kwargs.get("content", call_args[1].get("content", ""))
 assert "AAA\n\n---\n\nBBB" in content
# ============================================================================
# Task 2: markdown_to_blocks 转换层测试
# ============================================================================
@pytest.mark.django_db
class TestMarkdownToBlocks:
 """markdown_to_blocks 转换层单元测试（直接调用，不 mock）。"""
 def test_markdown_to_blocks_basic(self):
 """段落、标题、代码块正确转为飞书 Block 结构。"""
 from services.feishu_doc import markdown_to_blocks
 md = "普通段落\n\n# 一级标题\n\n```python\nprint('hello')\n```"
 blocks = markdown_to_blocks(md)
 # 至少包含 3 种类型的 block
 block_types = [b["block_type"] for b in blocks]
 assert 2 in block_types, "应包含 paragraph block (type=2)"
 assert 3 in block_types, "应包含 heading1 block (type=3)"
 assert 14 in block_types, "应包含 code block (type=14)"
 def test_code_block_language_mapping(self):
 """含 python 标记的代码块转换后 language 字段为正确飞书语言码。"""
 from services.feishu_doc import _get_language_code, markdown_to_blocks
 md = "```python\nprint('hello')\n```"
 blocks = markdown_to_blocks(md)
 code_blocks = [b for b in blocks if b["block_type"] == 14]
 assert len(code_blocks) >= 1
 code_block = code_blocks[0]
 lang_code = code_block["code"]["style"]["language"]
 # python 在飞书的语言码为 81
 assert lang_code == 81
 # 同时验证 _get_language_code 直接映射
 assert _get_language_code("python") == 81
 assert _get_language_code("js") == 53
 assert _get_language_code("typescript") == 97
