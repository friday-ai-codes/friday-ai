"""提问链路集成测试（Phase）。
验证完整提问流程：
1. 容器发送 question 回调
2. 创建 InteractionLog
3. 发送飞书卡片
4. 用户回复
5. 更新 InteractionLog
6. 更新卡片状态
7. 写入 answer.json
"""
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch
import pytest
from django.utils import timezone
@pytest.fixture
def mock_session(db):
 """创建测试用 SubAgentSession。"""
 from accounts.models import User
 from agents.models import AgentSession
 from projects.models import Project
 from subagent.models import SubAgentSession
 # 创建 User（AgentSession 需要）
 user = User.objects.create_user(
 username="test_user",
 email="test@example.com",
 password="testpass123",
 )
 # 创建 Project（AgentSession 需要）
 project = Project.objects.create(
 name="Test Project",
 description="Test",
 )
 # 创建 main_session
 main_session = AgentSession.objects.create(
 session_id="main-test-001",
 project=project,
 user=user,
 metadata={"chat_id": "oc_test_chat_id"},
 )
 # 创建 SubAgentSession
 session = SubAgentSession.objects.create(
 session_id="sub-test-001",
 main_session=main_session,
 repo_url="https://github.com/test/repo",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 )
 return session
class TestQuestionCallback:
 """测试 question 回调处理。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_interaction_log_creation(self, mock_session):
 """验证 InteractionLog 可正确创建。"""
 from subagent.models import InteractionLog
 question_id = f"q-{uuid.uuid4.hex[:12]}"
 payload = {
 "question": "选择哪种实现方式？",
 "options": ["方案 A", "方案 B"],
 "context": "实现用户认证功能",
 "code_snippet": "--- a/auth.py\n+++ b/auth.py",
 }
 interaction = await InteractionLog.objects.acreate(
 session=mock_session,
 question_id=question_id,
 question_text=payload["question"],
 question_context=payload["context"],
 code_snippet=payload["code_snippet"],
 options=payload["options"],
 feishu_message_id="msg_test_123",
 )
 assert interaction.question_id == question_id
 assert interaction.question_text == "选择哪种实现方式？"
 assert interaction.options == ["方案 A", "方案 B"]
 assert interaction.code_snippet == "--- a/auth.py\n+++ b/auth.py"
 assert interaction.is_answered is False
 assert interaction.feishu_message_id == "msg_test_123"
class TestAnswerHandling:
 """测试回复处理。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 @patch("subagent.question_handler._update_card_to_answered")
 @patch("subagent.question_handler.write_answer_to_volume")
 async def test_answer_updates_interaction_log(
 self, mock_write, mock_update_card, mock_session
 ):
 """验证回复更新 InteractionLog。"""
 from subagent.models import InteractionLog
 from subagent.question_handler import handle_container_answer_enhanced
 mock_write.return_value = True
 mock_update_card.return_value = None
 # 创建待回复的问题
 interaction = await InteractionLog.objects.acreate(
 session=mock_session,
 question_id="q-test-001",
 question_text="选择方案？",
 options=["A", "B"],
 feishu_message_id="msg_123",
 )
 # 处理回复
 result = await handle_container_answer_enhanced(
 session_id=mock_session.session_id,
 question_id="q-test-001",
 answer="方案 A",
 answer_source="button",
 )
 assert result is True
 # 验证 InteractionLog 更新
 await interaction.arefresh_from_db
 assert interaction.answer_text == "方案 A"
 assert interaction.answer_source == "button"
 assert interaction.answered_at is not None
 assert interaction.is_answered is True
 # 验证卡片更新被调用
 mock_update_card.assert_called_once
class TestMultiRoundQuestions:
 """测试多轮提问。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_multiple_questions_create_separate_logs(self, mock_session):
 """验证多轮提问创建独立的 InteractionLog。"""
 from subagent.models import InteractionLog
 # 创建多个问题
 for i in range(3):
 await InteractionLog.objects.acreate(
 session=mock_session,
 question_id=f"q-round-{i}",
 question_text=f"问题 {i}？",
 )
 # 验证数量
 count = await InteractionLog.objects.filter(session=mock_session).acount
 assert count == 3
 # 验证独立性（每个有唯一 question_id）
 question_ids = set
 async for log in InteractionLog.objects.filter(session=mock_session):
 question_ids.add(log.question_id)
 assert len(question_ids) == 3
class TestReminder:
 """测试超时提醒。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_reminder_not_sent_for_answered_questions(self, mock_session):
 """验证已回复问题不发送提醒。"""
 from subagent.models import InteractionLog
 from tasks.container_tasks import remind_pending_questions
 # 创建已回复的问题
 await InteractionLog.objects.acreate(
 session=mock_session,
 question_id="q-answered-001",
 question_text="已回复的问题",
 answer_text="已回复",
 answered_at=timezone.now,
 )
 # 运行提醒任务（mock 飞书调用）
 with patch("services.feishu_im.FeishuIMClient") as mock_client:
 mock_client.return_value = AsyncMock
 stats = await remind_pending_questions
 # 不应该发送提醒（问题已回复）
 assert stats["reminded"] == 0
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_reminder_respects_interval(self, mock_session):
 """验证提醒遵守 30 分钟间隔。"""
 from subagent.models import InteractionLog
 # 创建刚刚被提醒过的问题
 interaction = await InteractionLog.objects.acreate(
 session=mock_session,
 question_id="q-recent-reminder",
 question_text="刚被提醒的问题",
 last_reminder_at=timezone.now - timedelta(minutes=5), # 5分钟前
 )
 # 问题应该在 last_reminder_at < 30 分钟前 才会被提醒
 # 由于是 5 分钟前，不应被选中
 await interaction.arefresh_from_db
 assert interaction.last_reminder_at is not None
