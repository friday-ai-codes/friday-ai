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
# ============================================================================
# Phase：create_sessions_for_plan service 层单元测试
# ============================================================================
@pytest.fixture
def coding_plan_for_service(db, project):
 """Conversation + CodingPlan 用于 service 层批量创建测试。"""
 from chat.models import CodingPlan, Conversation
 conversation = Conversation.objects.create(project=project, title="service 测试")
 return CodingPlan.objects.create(
 conversation=conversation,
 tech_plan="## 多仓 fan-out 方案",
 affected_files=[{"file_path": "src/x.py", "change_type": "modify"}],
 title="多仓方案",
 )
@pytest.fixture
def three_repos_for_service(db, project):
 """3 个 Repository 全部 attach 到 project。"""
 from repositories.models import Repository
 repos =
 for name in ["repo-svc-a", "repo-svc-b", "repo-svc-c"]:
 r = Repository.objects.create(
 name=name,
 git_url=f"https://gitlab.com/test/{name}.git",
 git_platform="gitlab",
 default_branch="main",
 )
 project.repositories.add(r)
 repos.append(r)
 return repos
@pytest.fixture
def orphan_repo(db):
 """孤儿 Repository（不属于任何 project）。"""
 from repositories.models import Repository
 return Repository.objects.create(
 name="orphan-svc",
 git_url="https://gitlab.com/test/orphan-svc.git",
 git_platform="gitlab",
 default_branch="main",
 )
@pytest.mark.django_db(transaction=True)
class TestCreateSessionsForPlan:
 """ service 层批量创建语义测试。"""
 @pytest.mark.asyncio
 async def test_branch_template_repo_substitution(
 self, coding_plan_for_service, three_repos_for_service
 ) -> None:
 """branch_template 含 ${repo} → 每仓库 branch_name 都嵌入自己的 repo.name。"""
 from chat.coding_session_service import create_sessions_for_plan
 result = await create_sessions_for_plan(
 plan=coding_plan_for_service,
 repository_ids=[r.id for r in three_repos_for_service],
 branch_template="feat20260520.${repo}.feature-x",
 )
 assert len(result.created) == 3
 assert len(result.failed) == 0
 names = {i.repository_id: i.branch_name for i in result.created}
 for r in three_repos_for_service:
 assert names[r.id] == f"feat20260520.{r.name}.feature-x"
 @pytest.mark.asyncio
 async def test_repository_not_in_project_fails(
 self, coding_plan_for_service, orphan_repo
 ) -> None:
 """orphan_repo 不属于 coding_plan.conversation.project → failed。"""
 from chat.coding_session_service import create_sessions_for_plan
 result = await create_sessions_for_plan(
 plan=coding_plan_for_service,
 repository_ids=[orphan_repo.id],
 )
 assert len(result.created) == 0
 assert len(result.failed) == 1
 assert "无权访问" in result.failed[0].error
 @pytest.mark.asyncio
 async def test_independent_transaction_per_repo(
 self, coding_plan_for_service, three_repos_for_service
 ) -> None:
 """repo_a 预置 active session → repo_a failed，repo_b/c 仍 created（事务独立）。"""
 from asgiref.sync import sync_to_async
 from chat.coding_session_service import create_sessions_for_plan
 from chat.models import CodingSession
 repo_a, repo_b, repo_c = three_repos_for_service
 await sync_to_async(CodingSession.objects.create)(
 conversation=coding_plan_for_service.conversation,
 coding_plan=coding_plan_for_service,
 repository=repo_a,
 tech_plan="x",
 status=CodingSession.Status.RUNNING,
 )
 result = await create_sessions_for_plan(
 plan=coding_plan_for_service,
 repository_ids=[r.id for r in three_repos_for_service],
 branch_template="feat20260520.${repo}.task",
 )
 assert len(result.failed) == 1
 assert result.failed[0].repository_id == repo_a.id
 assert len(result.created) == 2
 drafts = await sync_to_async(
 lambda: set(
 CodingSession.objects.filter(
 coding_plan=coding_plan_for_service,
 status=CodingSession.Status.DRAFT,
 ).values_list("repository_id", flat=True)
 )
 )
 assert {repo_b.id, repo_c.id} == drafts
