"""CodingSession 模型测试 — 状态机、辅助方法、默认值 + API 测试。"""
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
# ============================================================================
# Confirm API 测试 ( Task 1)
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestCodingSessionConfirmAPI:
 """CodingSession confirm API 端点测试。"""
 @pytest.fixture
 def draft_session(self, project, repository):
 """创建 draft 状态的 CodingSession（含 Conversation）。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试对话")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案\n- 步骤 1\n- 步骤 2",
 affected_files=[{"path": "src/main.py", "change_type": "modify"}],
 )
 def test_confirm_only_draft(self, authenticated_client, draft_session):
 """POST /api/chat/coding-sessions/{id}/confirm/ 对 draft CodingSession 返回 200。"""
 from unittest.mock import AsyncMock, patch
 from repositories.models import GitCredential
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 ):
 mock_runner_qs = AsyncMock
 mock_runner_qs.acount = AsyncMock(return_value=1)
 mock_runner_objects.filter.return_value = mock_runner_qs
 mock_dispatcher = AsyncMock
 mock_get_dispatcher.return_value = mock_dispatcher
 mock_git_cred_objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 200
 draft_session.refresh_from_db
 assert draft_session.status == CodingSession.Status.RUNNING
 def test_confirm_non_draft_returns_400(self, authenticated_client, draft_session):
 """POST confirm 对 non-draft 状态返回 400。"""
 draft_session.status = CodingSession.Status.CONFIRMED
 draft_session.save(update_fields=["status"])
 url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 400
 def test_confirm_creates_subagent_session(self, authenticated_client, draft_session):
 """confirm 后创建了 SubAgentSession（task_type=coding）。"""
 from unittest.mock import AsyncMock, patch
 from repositories.models import GitCredential
 from subagent.models import SubAgentSession
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 ):
 mock_runner_qs = AsyncMock
 mock_runner_qs.acount = AsyncMock(return_value=1)
 mock_runner_objects.filter.return_value = mock_runner_qs
 mock_dispatcher = AsyncMock
 mock_get_dispatcher.return_value = mock_dispatcher
 mock_git_cred_objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 200
 draft_session.refresh_from_db
 assert draft_session.subagent_session is not None
 sub_session = SubAgentSession.objects.get(id=draft_session.subagent_session_id)
 assert sub_session.task_type == SubAgentSession.TaskType.CODING
 def test_confirm_dispatches_task(self, authenticated_client, draft_session):
 """confirm 后 dispatch 被调用且 DispatchTask.task_type="coding"。"""
 from unittest.mock import AsyncMock, patch
 from repositories.models import GitCredential
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 ):
 mock_runner_qs = AsyncMock
 mock_runner_qs.acount = AsyncMock(return_value=1)
 mock_runner_objects.filter.return_value = mock_runner_qs
 mock_dispatcher = AsyncMock
 mock_get_dispatcher.return_value = mock_dispatcher
 mock_git_cred_objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 200
 mock_dispatcher.dispatch.assert_called_once
 dispatch_task = mock_dispatcher.dispatch.call_args[0][0]
 assert dispatch_task.task_type == "coding"
 def test_confirm_not_found_returns_404(self, authenticated_client):
 """传入不存在 UUID 返回 404。"""
 import uuid
 fake_id = uuid.uuid4
 url = f"/api/chat/coding-sessions/{fake_id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 404
 def test_confirm_unauthenticated_returns_401(self, api_client, draft_session):
 """未认证请求返回 401。"""
 url = f"/api/chat/coding-sessions/{draft_session.id}/confirm/"
 response = api_client.post(url)
 assert response.status_code in (401, 403)
# ============================================================================
# 回调处理扩展测试 ( Task 2)
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestCodingSessionCallback:
 """CodingSession 回调处理扩展测试。"""
 @pytest.fixture
 def running_session_with_subagent(self, project, repository):
 """创建 running 状态的 CodingSession + 关联 SubAgentSession。"""
 from agents.models import AgentSession
 from chat.models import Conversation
 from subagent.models import SubAgentSession
 conversation = Conversation.objects.create(project=project, title="回调测试对话")
 agent_session = AgentSession.objects.create(
 session_id="agent-coding-test-001",
 project=project,
 status=AgentSession.Status.RUNNING,
 )
 sub_session = SubAgentSession.objects.create(
 session_id="coding-test-001",
 main_session=agent_session,
 task_type=SubAgentSession.TaskType.CODING,
 status=SubAgentSession.Status.RUNNING,
 repo_url="https://github.com/test/repo.git",
 )
 coding_session = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案",
 status=CodingSession.Status.RUNNING,
 subagent_session=sub_session,
 )
 return coding_session, sub_session
 @pytest.mark.asyncio
 async def test_callback_updates_pr_url(self, running_session_with_subagent):
 """completed 回调后 CodingSession.status=completed, pr_url 被回填。"""
 from subagent.api.callbacks import _update_coding_session_on_complete
 from subagent.models import TaskResult
 coding_session, sub_session = running_session_with_subagent
 # 创建 TaskResult with pr_url
 await TaskResult.objects.acreate(
 session=sub_session,
 result_type=TaskResult.ResultType.GIT,
 pr_url="https://github.com/test/repo/pull/1",
 raw_output={"text": "done"},
 )
 await sub_session.amark_completed
 await _update_coding_session_on_complete(sub_session)
 await coding_session.arefresh_from_db
 assert coding_session.status == CodingSession.Status.COMPLETED
 assert coding_session.pr_url == "https://github.com/test/repo/pull/1"
 @pytest.mark.asyncio
 async def test_callback_failed_updates_error(self, running_session_with_subagent):
 """failed 回调后 CodingSession.status=failed, error_message 被设置。"""
 from subagent.api.callbacks import _update_coding_session_on_fail
 coding_session, sub_session = running_session_with_subagent
 await _update_coding_session_on_fail(sub_session, "容器执行超时")
 await coding_session.arefresh_from_db
 assert coding_session.status == CodingSession.Status.FAILED
 assert coding_session.error_message == "容器执行超时"
 @pytest.mark.asyncio
 async def test_callback_no_coding_session_passes(self, project):
 """无关联 CodingSession 的 session 回调不报错。"""
 from agents.models import AgentSession
 from subagent.api.callbacks import _update_coding_session_on_complete, _update_coding_session_on_fail
 from subagent.models import SubAgentSession
 agent_session = await AgentSession.objects.acreate(
 session_id="agent-no-coding-001",
 project=project,
 status=AgentSession.Status.RUNNING,
 )
 sub_session = await SubAgentSession.objects.acreate(
 session_id="no-coding-001",
 main_session=agent_session,
 task_type=SubAgentSession.TaskType.EXPLORE,
 status=SubAgentSession.Status.COMPLETED,
 repo_url="https://github.com/test/repo.git",
 )
 # 不应抛出异常
 await _update_coding_session_on_complete(sub_session)
 await _update_coding_session_on_fail(sub_session, "some error")
