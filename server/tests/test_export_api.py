"""飞书文档导出 API 测试。
覆盖 Project.feishu_doc_folder_token 字段、ExportToFeishuView endpoint、
以及 markdown_to_blocks 转换层。
"""
import uuid
import pytest
from django.test import override_settings
from chat.models import Conversation, Message
from projects.models import Project
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
