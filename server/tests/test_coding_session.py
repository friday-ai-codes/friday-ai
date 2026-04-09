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
 """创建 draft 状态的 CodingSession（含 Conversation + 有效分支名）。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试对话")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案\n- 步骤 1\n- 步骤 2",
 affected_files=[{"path": "src/main.py", "change_type": "modify"}],
 branch_name="feat20260409.test-coding",
 )
 def test_confirm_only_draft(self, authenticated_client, draft_session):
 """POST /api/chat/coding-sessions/{id}/confirm/ 对 draft CodingSession 返回 200。"""
 from unittest.mock import AsyncMock, patch
 from chat.branch_service import BranchValidationResult
 from repositories.models import GitCredential
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 patch(
 "chat.branch_service.validate_branch_name",
 new_callable=AsyncMock,
 return_value=BranchValidationResult(valid=True),
 ),
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
 from chat.branch_service import BranchValidationResult
 from repositories.models import GitCredential
 from subagent.models import SubAgentSession
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 patch(
 "chat.branch_service.validate_branch_name",
 new_callable=AsyncMock,
 return_value=BranchValidationResult(valid=True),
 ),
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
 from chat.branch_service import BranchValidationResult
 from repositories.models import GitCredential
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 patch(
 "chat.branch_service.validate_branch_name",
 new_callable=AsyncMock,
 return_value=BranchValidationResult(valid=True),
 ),
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
# ============================================================================
# 查询恢复 API 测试 ( Task 3)
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestCodingSessionQueryAPI:
 """CodingSession 查询恢复 API 测试。"""
 @pytest.fixture
 def conversation_with_sessions(self, project, repository):
 """创建一个 conversation 并关联 2 个 CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="查询测试对话")
 session1 = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 方案 1",
 status=CodingSession.Status.COMPLETED,
 pr_url="https://github.com/test/repo/pull/1",
 )
 session2 = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 方案 2",
 status=CodingSession.Status.DRAFT,
 )
 return conversation, session1, session2
 def test_list_by_conversation(self, authenticated_client, conversation_with_sessions):
 """GET /api/chat/coding-sessions/?conversation_id=xxx 返回 2 条。"""
 conversation, _, _ = conversation_with_sessions
 url = f"/api/chat/coding-sessions/?conversation_id={conversation.id}"
 response = authenticated_client.get(url)
 assert response.status_code == 200
 assert len(response.data) == 2
 def test_list_empty_conversation(self, authenticated_client, project):
 """GET 带无 CodingSession 的 conversation_id 返回空列表。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="空对话")
 url = f"/api/chat/coding-sessions/?conversation_id={conversation.id}"
 response = authenticated_client.get(url)
 assert response.status_code == 200
 assert len(response.data) == 0
 def test_list_missing_param_returns_400(self, authenticated_client):
 """GET 不带 conversation_id 返回 400。"""
 url = "/api/chat/coding-sessions/"
 response = authenticated_client.get(url)
 assert response.status_code == 400
 def test_detail_returns_session(self, authenticated_client, conversation_with_sessions):
 """GET /api/chat/coding-sessions/{id}/ 返回完整字段。"""
 _, session1, _ = conversation_with_sessions
 url = f"/api/chat/coding-sessions/{session1.id}/"
 response = authenticated_client.get(url)
 assert response.status_code == 200
 assert response.data["id"] == str(session1.id)
 assert response.data["status"] == "completed"
 assert response.data["pr_url"] == "https://github.com/test/repo/pull/1"
 assert "tech_plan" in response.data
 assert "created_at" in response.data
 def test_detail_not_found_returns_404(self, authenticated_client):
 """GET 不存在 id 返回 404。"""
 import uuid
 fake_id = uuid.uuid4
 url = f"/api/chat/coding-sessions/{fake_id}/"
 response = authenticated_client.get(url)
 assert response.status_code == 404
# ============================================================================
# CodingSession awaiting_confirmation 状态扩展测试 ( Task 1)
# ============================================================================
@pytest.mark.django_db
class TestCodingSessionAwaitingConfirmationDefaults:
 """验证新增的 confirmation_step 和 suggested_commit_message 字段默认值。"""
 def test_new_fields_defaults(self, project, repository):
 """新字段 confirmation_step 和 suggested_commit_message 默认为空字符串。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="默认值测试")
 session = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案",
 )
 assert session.confirmation_step == ""
 assert session.suggested_commit_message == ""
 def test_status_choices_include_awaiting_confirmation(self):
 """Status TextChoices 包含 AWAITING_CONFIRMATION。"""
 assert hasattr(CodingSession.Status, "AWAITING_CONFIRMATION")
 assert CodingSession.Status.AWAITING_CONFIRMATION == "awaiting_confirmation"
@pytest.mark.django_db(transaction=True)
class TestCodingSessionAwaitingConfirmationStateMachine:
 """验证 awaiting_confirmation 双向状态转换。"""
 @pytest.fixture
 def running_session(self, project, repository):
 """创建 running 状态的 CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="状态转换测试")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 方案",
 status=CodingSession.Status.RUNNING,
 )
 @pytest.mark.asyncio
 async def test_amark_awaiting_confirmation_from_running(self, running_session):
 """running -> awaiting_confirmation 转换成功，设置 step 和 suggested_commit_message。"""
 await running_session.amark_awaiting_confirmation(
 step="commit_message",
 suggested_commit_message="feat: 添加用户认证",
 )
 await running_session.arefresh_from_db
 assert running_session.status == CodingSession.Status.AWAITING_CONFIRMATION
 assert running_session.confirmation_step == "commit_message"
 assert running_session.suggested_commit_message == "feat: 添加用户认证"
 @pytest.mark.asyncio
 async def test_amark_awaiting_confirmation_without_commit_message(self, running_session):
 """running -> awaiting_confirmation 不传 suggested_commit_message 时保留原值。"""
 running_session.suggested_commit_message = "旧消息"
 await running_session.asave(update_fields=["suggested_commit_message"])
 await running_session.amark_awaiting_confirmation(step="pr_review")
 await running_session.arefresh_from_db
 assert running_session.status == CodingSession.Status.AWAITING_CONFIRMATION
 assert running_session.confirmation_step == "pr_review"
 # 不传 suggested_commit_message 时保留旧值
 assert running_session.suggested_commit_message == "旧消息"
 @pytest.mark.asyncio
 async def test_amark_awaiting_confirmation_from_non_running_raises(self, running_session):
 """非 running 状态调用 amark_awaiting_confirmation 抛出 ValueError。"""
 # draft 状态
 running_session.status = CodingSession.Status.DRAFT
 await running_session.asave(update_fields=["status"])
 with pytest.raises(ValueError, match="只有 running 状态可进入等待确认"):
 await running_session.amark_awaiting_confirmation(step="commit_message")
 # completed 状态
 running_session.status = CodingSession.Status.COMPLETED
 await running_session.asave(update_fields=["status"])
 with pytest.raises(ValueError, match="只有 running 状态可进入等待确认"):
 await running_session.amark_awaiting_confirmation(step="commit_message")
 @pytest.mark.asyncio
 async def test_aresume_running_from_awaiting_confirmation(self, running_session):
 """awaiting_confirmation -> running 转换成功，清空 confirmation_step。"""
 # 先进入 awaiting_confirmation
 await running_session.amark_awaiting_confirmation(
 step="commit_message",
 suggested_commit_message="feat: test",
 )
 await running_session.arefresh_from_db
 assert running_session.status == CodingSession.Status.AWAITING_CONFIRMATION
 # 恢复 running
 await running_session.aresume_running
 await running_session.arefresh_from_db
 assert running_session.status == CodingSession.Status.RUNNING
 assert running_session.confirmation_step == ""
 @pytest.mark.asyncio
 async def test_aresume_running_from_non_awaiting_raises(self, running_session):
 """非 awaiting_confirmation 状态调用 aresume_running 抛出 ValueError。"""
 # running 状态
 with pytest.raises(ValueError, match="只有 awaiting_confirmation 状态可恢复运行"):
 await running_session.aresume_running
 # draft 状态
 running_session.status = CodingSession.Status.DRAFT
 await running_session.asave(update_fields=["status"])
 with pytest.raises(ValueError, match="只有 awaiting_confirmation 状态可恢复运行"):
 await running_session.aresume_running
@pytest.mark.django_db
class TestCodingSessionSerializerNewFields:
 """验证 CodingSessionSerializer 包含新字段。"""
 def test_serializer_includes_confirmation_step(self, project, repository):
 """CodingSessionSerializer 序列化结果包含 confirmation_step。"""
 from chat.models import Conversation
 from chat.serializers import CodingSessionSerializer
 conversation = Conversation.objects.create(project=project, title="序列化测试")
 session = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 方案",
 )
 serializer = CodingSessionSerializer(session)
 assert "confirmation_step" in serializer.data
 assert serializer.data["confirmation_step"] == ""
 def test_serializer_includes_suggested_commit_message(self, project, repository):
 """CodingSessionSerializer 序列化结果包含 suggested_commit_message。"""
 from chat.models import Conversation
 from chat.serializers import CodingSessionSerializer
 conversation = Conversation.objects.create(project=project, title="序列化测试")
 session = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 方案",
 suggested_commit_message="feat: 实现功能",
 )
 serializer = CodingSessionSerializer(session)
 assert "suggested_commit_message" in serializer.data
 assert serializer.data["suggested_commit_message"] == "feat: 实现功能"
# ============================================================================
# 分支名校验 + metadata 注入测试 ( Task 2)
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestCodingSessionConfirmBranchValidation:
 """CodingSessionConfirmView 分支名校验与 metadata 注入测试。"""
 @pytest.fixture
 def draft_session_with_branch(self, project, repository):
 """创建带有效分支名的 draft CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试编码")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 实现 user auth",
 branch_name="feat20260409.user-auth",
 )
 @pytest.fixture
 def draft_session_with_bad_branch(self, project, repository):
 """创建带非法分支名（保护分支）的 draft CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="测试编码")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 实现 user auth",
 branch_name="main",
 )
 def test_confirm_rejects_protected_branch(self, authenticated_client, draft_session_with_bad_branch):
 """分支名为 main 时 confirm 应返回 400。"""
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
 url = f"/api/chat/coding-sessions/{draft_session_with_bad_branch.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 400
 assert "errors" in response.data
 # 确认包含保护分支错误信息
 errors_str = str(response.data["errors"])
 assert "保护分支" in errors_str or "main" in errors_str
 def test_confirm_rejects_dotdot_branch(self, authenticated_client, project, repository):
 """分支名包含 .. 时 confirm 应返回 400。"""
 from unittest.mock import AsyncMock, patch
 from chat.models import Conversation
 from repositories.models import GitCredential
 conversation = Conversation.objects.create(project=project, title="dotdot 测试")
 bad_session = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 测试",
 branch_name="feat/../../etc/passwd",
 )
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
 url = f"/api/chat/coding-sessions/{bad_session.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 400
 assert "errors" in response.data
 def test_metadata_contains_branch_strategy(self, authenticated_client, draft_session_with_branch):
 """dispatch 时 metadata 应包含 env_FRIDAY_TASK_BRANCH_STRATEGY = session.branch_name，
 且 target_branch 应为 repo.default_branch。"""
 from unittest.mock import AsyncMock, patch
 from chat.branch_service import BranchValidationResult
 from repositories.models import GitCredential
 session = draft_session_with_branch
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 # mock validate_branch_name 返回有效结果（避免 DB 唯一性检查误判自身）
 patch(
 "chat.branch_service.validate_branch_name",
 new_callable=AsyncMock,
 return_value=BranchValidationResult(valid=True),
 ),
 ):
 mock_runner_qs = AsyncMock
 mock_runner_qs.acount = AsyncMock(return_value=1)
 mock_runner_objects.filter.return_value = mock_runner_qs
 mock_dispatcher = AsyncMock
 mock_get_dispatcher.return_value = mock_dispatcher
 mock_git_cred_objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 url = f"/api/chat/coding-sessions/{session.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 200, f"confirm 应返回 200，实际返回 {response.status_code}: {response.data}"
 # 从 mock_dispatcher.dispatch.call_args 提取 DispatchTask
 assert mock_dispatcher.dispatch.called, "dispatch 应被调用"
 dispatch_task = mock_dispatcher.dispatch.call_args[0][0]
 # 验证 env_FRIDAY_TASK_BRANCH_STRATEGY
 assert "env_FRIDAY_TASK_BRANCH_STRATEGY" in dispatch_task.metadata, \
 "metadata 应包含 env_FRIDAY_TASK_BRANCH_STRATEGY"
 assert dispatch_task.metadata["env_FRIDAY_TASK_BRANCH_STRATEGY"] == session.branch_name, \
 f"branch_strategy 应为 {session.branch_name}，实际为 {dispatch_task.metadata.get('env_FRIDAY_TASK_BRANCH_STRATEGY')}"
 # 验证 target_branch 为 repo.default_branch（非功能分支名）
 repo = session.repository
 assert dispatch_task.target_branch == repo.default_branch, \
 f"target_branch 应为 {repo.default_branch}，实际为 {dispatch_task.target_branch}"
 def test_target_branch_is_default_branch_not_feature_branch(
 self, authenticated_client, draft_session_with_branch
 ):
 """target_branch 始终为 repo.default_branch，而非功能分支名。"""
 from unittest.mock import AsyncMock, patch
 from chat.branch_service import BranchValidationResult
 from repositories.models import GitCredential
 session = draft_session_with_branch
 with (
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("runners.models.Runner.objects") as mock_runner_objects,
 patch("chat.services.aget_setting_value", new_callable=AsyncMock, return_value="test-key"),
 patch("repositories.models.GitCredential.objects") as mock_git_cred_objects,
 patch(
 "chat.branch_service.validate_branch_name",
 new_callable=AsyncMock,
 return_value=BranchValidationResult(valid=True),
 ),
 ):
 mock_runner_qs = AsyncMock
 mock_runner_qs.acount = AsyncMock(return_value=1)
 mock_runner_objects.filter.return_value = mock_runner_qs
 mock_dispatcher = AsyncMock
 mock_get_dispatcher.return_value = mock_dispatcher
 mock_git_cred_objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 url = f"/api/chat/coding-sessions/{session.id}/confirm/"
 response = authenticated_client.post(url)
 assert response.status_code == 200
 dispatch_task = mock_dispatcher.dispatch.call_args[0][0]
 # target_branch 不应等于功能分支名
 assert dispatch_task.target_branch != session.branch_name, \
 "target_branch 不应等于功能分支名"
 assert dispatch_task.target_branch == "main", \
 f"target_branch 应为 main，实际为 {dispatch_task.target_branch}"
