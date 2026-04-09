"""CodingSession dispatch service 单元测试 ( Task 2)。"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from chat.models import CodingSession
@pytest.mark.django_db(transaction=True)
class TestCheckRunnerOnline:
 """check_runner_online 函数测试。"""
 @pytest.mark.asyncio
 async def test_check_runner_online_success(self):
 """有在线 Runner 时返回 True。"""
 from chat.coding_session_service import check_runner_online
 with patch("runners.models.Runner") as mock_runner_cls:
 mock_qs = AsyncMock
 mock_qs.acount = AsyncMock(return_value=1)
 mock_runner_cls.objects.filter.return_value = mock_qs
 result = await check_runner_online
 assert result is True
 mock_runner_cls.objects.filter.assert_called_once
 @pytest.mark.asyncio
 async def test_check_runner_online_no_runners(self):
 """无在线 Runner 时重试 3 次后返回 False。"""
 from chat.coding_session_service import check_runner_online
 with patch("runners.models.Runner") as mock_runner_cls:
 mock_qs = AsyncMock
 mock_qs.acount = AsyncMock(return_value=0)
 mock_runner_cls.objects.filter.return_value = mock_qs
 # mock sleep 加速测试
 with patch("chat.coding_session_service.asyncio.sleep", new_callable=AsyncMock):
 result = await check_runner_online
 assert result is False
 assert mock_runner_cls.objects.filter.call_count == 3
@pytest.mark.django_db(transaction=True)
class TestBuildDispatchMetadata:
 """build_dispatch_metadata 函数测试。"""
 @pytest.fixture
 def coding_session_with_repo(self, project, repository):
 """创建带 repository 的 CodingSession。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="metadata 测试")
 return CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 方案",
 branch_name="feat20260409.test",
 )
 @pytest.mark.asyncio
 async def test_build_dispatch_metadata_with_token(self, coding_session_with_repo):
 """有 Git token 时 metadata 包含 access_token 和 auth_type。"""
 from chat.coding_session_service import build_dispatch_metadata
 from repositories.models import GitCredential
 session = coding_session_with_repo
 repo = session.repository
 mock_cred = MagicMock(spec=GitCredential)
 mock_cred.encrypted_token = "encrypted_test_token"
 with (
 patch(
 "chat.services.aget_setting_value",
 new_callable=AsyncMock,
 return_value="test-api-key",
 ),
 patch("repositories.models.GitCredential") as mock_git_cred_cls,
 patch(
 "common.encryption.decrypt_value",
 return_value="decrypted_token",
 ),
 ):
 mock_git_cred_cls.objects.aget = AsyncMock(return_value=mock_cred)
 mock_git_cred_cls.DoesNotExist = GitCredential.DoesNotExist
 env_metadata, repo_url = await build_dispatch_metadata(repo, session)
 assert "env_FRIDAY_TASK_GIT_ACCESS_TOKEN" in env_metadata
 assert env_metadata["env_FRIDAY_TASK_GIT_ACCESS_TOKEN"] == "decrypted_token"
 assert env_metadata["env_FRIDAY_TASK_GIT_AUTH_TYPE"] == "token"
 assert env_metadata["env_FRIDAY_TASK_BRANCH_STRATEGY"] == "feat20260409.test"
 @pytest.mark.asyncio
 async def test_build_dispatch_metadata_without_token(self, coding_session_with_repo):
 """无 Git token 时 metadata 不包含 access_token。"""
 from chat.coding_session_service import build_dispatch_metadata
 from repositories.models import GitCredential
 session = coding_session_with_repo
 repo = session.repository
 with (
 patch(
 "chat.services.aget_setting_value",
 new_callable=AsyncMock,
 return_value="test-key",
 ),
 patch("repositories.models.GitCredential") as mock_git_cred_cls,
 ):
 mock_git_cred_cls.objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 mock_git_cred_cls.DoesNotExist = GitCredential.DoesNotExist
 env_metadata, repo_url = await build_dispatch_metadata(repo, session)
 assert "env_FRIDAY_TASK_GIT_ACCESS_TOKEN" not in env_metadata
 assert "env_FRIDAY_TASK_CLAUDE_API_KEY" in env_metadata
@pytest.mark.django_db(transaction=True)
class TestDispatchCodingTask:
 """dispatch_coding_task 函数集成测试。"""
 @pytest.fixture
 def confirmed_session(self, project, repository):
 """创建 confirmed 状态的 CodingSession（含完整关联）。"""
 from chat.models import Conversation
 conversation = Conversation.objects.create(project=project, title="dispatch 测试")
 session = CodingSession.objects.create(
 conversation=conversation,
 repository=repository,
 tech_plan="## 技术方案\n- 步骤 1",
 status=CodingSession.Status.CONFIRMED,
 branch_name="feat20260409.dispatch-test",
 )
 return session
 @pytest.mark.asyncio
 async def test_dispatch_coding_task_success(self, confirmed_session):
 """完整 dispatch 流程成功，返回 session_id。"""
 from chat.branch_service import BranchValidationResult
 from chat.coding_session_service import dispatch_coding_task
 from repositories.models import GitCredential
 # 预加载关联对象（模拟 select_related）
 session = await CodingSession.objects.select_related(
 "repository", "conversation__project"
 ).aget(id=confirmed_session.id)
 with (
 patch(
 "chat.coding_session_service.check_runner_online",
 new_callable=AsyncMock,
 return_value=True,
 ),
 patch(
 "chat.coding_session_service.build_dispatch_metadata",
 new_callable=AsyncMock,
 return_value=({"env_FRIDAY_TASK_CLAUDE_API_KEY": "key"}, "https://git.example.com/repo.git"),
 ),
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("repositories.models.GitCredential") as mock_git_cred_cls,
 patch(
 "chat.branch_service.validate_branch_name",
 new_callable=AsyncMock,
 return_value=BranchValidationResult(valid=True),
 ),
 ):
 mock_dispatcher = AsyncMock
 mock_get_dispatcher.return_value = mock_dispatcher
 mock_git_cred_cls.objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 mock_git_cred_cls.DoesNotExist = GitCredential.DoesNotExist
 result = await dispatch_coding_task(
 session,
 task_type="coding",
 prompt="测试 prompt",
 )
 assert isinstance(result, str)
 assert result.startswith("coding-")
 mock_dispatcher.dispatch.assert_called_once
 dispatch_task = mock_dispatcher.dispatch.call_args[0][0]
 assert dispatch_task.task_type == "coding"
 assert dispatch_task.prompt == "测试 prompt"
 @pytest.mark.asyncio
 async def test_dispatch_coding_task_with_extra_metadata(self, confirmed_session):
 """extra_metadata 被合并到 dispatch 的 metadata 中。"""
 from chat.branch_service import BranchValidationResult
 from chat.coding_session_service import dispatch_coding_task
 from repositories.models import GitCredential
 # 预加载关联对象
 session = await CodingSession.objects.select_related(
 "repository", "conversation__project"
 ).aget(id=confirmed_session.id)
 with (
 patch(
 "chat.coding_session_service.check_runner_online",
 new_callable=AsyncMock,
 return_value=True,
 ),
 patch(
 "chat.coding_session_service.build_dispatch_metadata",
 new_callable=AsyncMock,
 return_value=({"env_FRIDAY_TASK_CLAUDE_API_KEY": "key"}, "https://git.example.com/repo.git"),
 ),
 patch("runners.dispatcher.get_dispatcher") as mock_get_dispatcher,
 patch("repositories.models.GitCredential") as mock_git_cred_cls,
 patch(
 "chat.branch_service.validate_branch_name",
 new_callable=AsyncMock,
 return_value=BranchValidationResult(valid=True),
 ),
 ):
 mock_dispatcher = AsyncMock
 mock_get_dispatcher.return_value = mock_dispatcher
 mock_git_cred_cls.objects.aget = AsyncMock(side_effect=GitCredential.DoesNotExist)
 mock_git_cred_cls.DoesNotExist = GitCredential.DoesNotExist
 await dispatch_coding_task(
 session,
 task_type="coding",
 extra_metadata={"env_FRIDAY_TASK_COMMIT_MESSAGE": "feat: test commit"},
 prompt="",
 )
 dispatch_task = mock_dispatcher.dispatch.call_args[0][0]
 assert "env_FRIDAY_TASK_COMMIT_MESSAGE" in dispatch_task.metadata
 assert dispatch_task.metadata["env_FRIDAY_TASK_COMMIT_MESSAGE"] == "feat: test commit"
 @pytest.mark.asyncio
 async def test_dispatch_coding_task_no_runner_raises(self, confirmed_session):
 """Runner 不在线时抛出 RuntimeError。"""
 from chat.coding_session_service import dispatch_coding_task
 session = await CodingSession.objects.select_related(
 "repository", "conversation__project"
 ).aget(id=confirmed_session.id)
 with patch(
 "chat.coding_session_service.check_runner_online",
 new_callable=AsyncMock,
 return_value=False,
 ):
 with pytest.raises(RuntimeError, match="没有可用的 Runner"):
 await dispatch_coding_task(session, prompt="test")
