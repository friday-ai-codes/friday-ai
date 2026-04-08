"""CodingSession 模型测试 — 状态机、辅助方法、默认值。"""
import pytest
from chat.models import CodingSession
@pytest.mark.django_db
class TestCodingSessionDefaults:
 """验证 CodingSession 创建时的默认值。"""
 def test_coding_session_model_defaults(self, project, repository):
 """创建 CodingSession 后 status 默认为 draft，revision_count 默认为 0。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试对话")
 session = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案\n- 步骤 1",
 )
 assert session.status == CodingSession.Status.DRAFT
 assert session.revision_count == 0
 assert session.pr_url == ""
 assert session.error_message == ""
 assert session.branch_name == ""
 assert session.subagent_session is None
@pytest.mark.django_db(transaction=True)
class TestCodingSessionStateMachine:
 """验证 CodingSession 状态转换方法的约束。"""
 @pytest.fixture
 def draft_session(self, project, repository):
 """创建 draft 状态的 CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试对话")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 初始方案",
 )
 @pytest.mark.asyncio
 async def test_aconfirm_from_draft(self, draft_session):
 """draft -> confirmed 转换成功。"""
 await draft_session.aconfirm
 await draft_session.arefresh_from_db
 assert draft_session.status == CodingSession.Status.CONFIRMED
 @pytest.mark.asyncio
 async def test_aconfirm_from_non_draft_raises(self, draft_session):
 """非 draft 状态调用 aconfirm 抛出 ValueError。"""
 # confirmed 状态
 await draft_session.aconfirm
 with pytest.raises(ValueError, match="只有 draft 状态可确认"):
 await draft_session.aconfirm
 # running 状态
 draft_session.status = CodingSession.Status.RUNNING
 await draft_session.asave(update_fields=["status"])
 with pytest.raises(ValueError, match="只有 draft 状态可确认"):
 await draft_session.aconfirm
 # completed 状态
 draft_session.status = CodingSession.Status.COMPLETED
 await draft_session.asave(update_fields=["status"])
 with pytest.raises(ValueError, match="只有 draft 状态可确认"):
 await draft_session.aconfirm
 # failed 状态
 draft_session.status = CodingSession.Status.FAILED
 await draft_session.asave(update_fields=["status"])
 with pytest.raises(ValueError, match="只有 draft 状态可确认"):
 await draft_session.aconfirm
 @pytest.mark.asyncio
 async def test_amark_running_sets_subagent(self, draft_session):
 """confirmed -> running 转换成功。"""
 draft_session.status = CodingSession.Status.CONFIRMED
 await draft_session.asave(update_fields=["status"])
 await draft_session.amark_running
 await draft_session.arefresh_from_db
 assert draft_session.status == CodingSession.Status.RUNNING
 @pytest.mark.asyncio
 async def test_amark_completed_sets_pr_url(self, draft_session):
 """running -> completed 转换成功，并设置 pr_url。"""
 draft_session.status = CodingSession.Status.RUNNING
 await draft_session.asave(update_fields=["status"])
 await draft_session.amark_completed(pr_url="https://github.com/test/repo/pull/1")
 await draft_session.arefresh_from_db
 assert draft_session.status == CodingSession.Status.COMPLETED
 assert draft_session.pr_url == "https://github.com/test/repo/pull/1"
 @pytest.mark.asyncio
 async def test_amark_failed_sets_error(self, draft_session):
 """running -> failed 转换成功，并设置 error_message。"""
 draft_session.status = CodingSession.Status.RUNNING
 await draft_session.asave(update_fields=["status"])
 await draft_session.amark_failed(error="容器执行超时")
 await draft_session.arefresh_from_db
 assert draft_session.status == CodingSession.Status.FAILED
 assert draft_session.error_message == "容器执行超时"
 @pytest.mark.asyncio
 async def test_aupdate_plan_increments_revision(self, draft_session):
 """aupdate_plan 更新 tech_plan 并递增 revision_count。"""
 assert draft_session.revision_count == 0
 await draft_session.aupdate_plan(
 tech_plan="## 更新后方案\n- 新步骤",
 affected_files=[{"path": "src/main.py", "change_type": "modify"}],
 )
 await draft_session.arefresh_from_db
 assert draft_session.revision_count == 1
 assert draft_session.tech_plan == "## 更新后方案\n- 新步骤"
 assert draft_session.affected_files == [{"path": "src/main.py", "change_type": "modify"}]
