"""ContainerManager 单元测试 + SubAgentSession 模型测试。"""
import json
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
User = get_user_model
# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def mock_docker_client:
 """Mock docker.from_env 返回的客户端。"""
 client = MagicMock
 client.ping.return_value = True
 client.info.return_value = {
 "ServerVersion": "24.0.0",
 "ContainersRunning": 0,
 }
 container = MagicMock
 container.id = "abc123def456789012345678"
 container.status = "running"
 client.containers.run.return_value = container
 client.containers.get.return_value = container
 client.containers.list.return_value =
 client.images.get.return_value = MagicMock
 client.networks.list.return_value =
 return client
@pytest.fixture
def container_manager(mock_docker_client):
 """创建使用 mock Docker 客户端的 ContainerManager。"""
 with patch("docker.from_env", return_value=mock_docker_client):
 from services.container_manager import ContainerManager
 manager = ContainerManager
 # Mock ContainerExecutor 的异步方法
 manager._executor.start_execution = AsyncMock(
 return_value="abc123def456789012345678"
 )
 manager._executor._remove_container_by_name = AsyncMock
 manager._executor.stop_execution = AsyncMock(return_value=True)
 manager._executor.get_logs = AsyncMock(return_value="mock logs")
 manager._executor.get_status = AsyncMock(return_value=None)
 manager._executor.cleanup_finished_containers = AsyncMock(return_value=0)
 return manager
@pytest.fixture
def sample_config(agent_session):
 """创建测试用 ContainerConfig（绑定 agent_session 以满足 FK 约束）。"""
 from services.container_manager import ContainerConfig
 from subagent.models import generate_execution_id
 return ContainerConfig(
 session_id=generate_execution_id,
 task_type="coding",
 repo_url="https://github.com/test/repo.git",
 branch="main",
 target_branch="feature/test",
 work_item_id="",
 main_session_id=agent_session.session_id,
 claude_api_key="test-key",
 )
@pytest.fixture
def agent_session(db, user):
 """创建测试用 AgentSession（依赖 conftest 中的 user 和 project fixture）。"""
 from agents.models import AgentSession
 from projects.models import Project
 project = Project.objects.create(
 name="Test CM Project",
 feishu_project_key="test-cm-key",
 )
 return AgentSession.objects.create(
 session_id="main-session-test-cm-1",
 project=project,
 user=user,
 status=AgentSession.Status.RUNNING,
 )
# ============================================================================
# ContainerManager 初始化测试
# ============================================================================
class TestContainerManagerInit:
 def test_init_verifies_docker_daemon(self, mock_docker_client):
 """验证 __init__ 调用 client.ping 。"""
 with patch("docker.from_env", return_value=mock_docker_client):
 from services.container_manager import ContainerManager
 ContainerManager
 mock_docker_client.ping.assert_called
 mock_docker_client.info.assert_called
 def test_init_raises_when_docker_unavailable(self):
 """Docker 不可用时抛出 RuntimeError 。"""
 import docker as docker_lib
 client = MagicMock
 client.ping.side_effect = docker_lib.errors.DockerException(
 "connection refused"
 )
 client.networks.list.return_value =
 with patch("docker.from_env", return_value=client):
 from services.container_manager import ContainerManager
 with pytest.raises(RuntimeError, match="Docker daemon 不可用"):
 ContainerManager
# ============================================================================
# 容器命名测试
# ============================================================================
class TestContainerNaming:
 def test_container_name_uses_uuid(self, container_manager):
 """容器名格式为 friday-exec-{12位hex} (, C3)。"""
 name = container_manager._generate_container_name
 assert name.startswith("friday-exec-")
 hex_part = name[len("friday-exec-"):]
 assert len(hex_part) == 12
 # 验证是合法 hex
 int(hex_part, 16)
 def test_container_name_unique(self, container_manager):
 """多次调用生成不同名字。"""
 names = {container_manager._generate_container_name for _ in range(100)}
 assert len(names) == 100
# ============================================================================
# start 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestContainerManagerStart:
 @pytest.mark.asyncio
 async def test_start_creates_session_in_db(self, container_manager, sample_config):
 """start 创建 SubAgentSession 记录 (C1)。"""
 from subagent.models import SubAgentSession
 sample_config.work_item_id = ""
 container_id = await container_manager.start(sample_config)
 assert container_id
 session = await SubAgentSession.objects.filter(
 session_id=sample_config.session_id
 ).afirst
 assert session is not None
 assert session.status == SubAgentSession.Status.RUNNING
 assert session.container_id != ""
 assert session.container_name.startswith("friday-exec-")
 @pytest.mark.asyncio
 async def test_start_writes_context_json(
 self, container_manager, sample_config, tmp_path
 ):
 """start 在传输目录写入 context.json。"""
 container_manager._executor.transfers_dir = str(tmp_path)
 sample_config.work_item_id = ""
 await container_manager.start(sample_config)
 friday_dir = tmp_path / sample_config.session_id / ".friday"
 context_file = friday_dir / "context.json"
 assert context_file.exists
 data = json.loads(context_file.read_text)
 assert data["session_id"] == sample_config.session_id
 assert data["task_type"] == "coding"
 @pytest.mark.asyncio
 async def test_start_marks_failed_on_docker_error(
 self, container_manager, sample_config
 ):
 """Docker 启动失败时 session 标记为 ERROR。"""
 from subagent.models import SubAgentSession
 sample_config.work_item_id = ""
 container_manager._executor.start_execution = AsyncMock(
 side_effect=RuntimeError("Docker API error")
 )
 with pytest.raises(RuntimeError, match="Docker API error"):
 await container_manager.start(sample_config)
 session = await SubAgentSession.objects.filter(
 session_id=sample_config.session_id
 ).afirst
 assert session is not None
 assert session.status == SubAgentSession.Status.ERROR
 assert "Docker API error" in session.last_error
# ============================================================================
# 重复提交检测测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestDuplicateDetection:
 @pytest.mark.asyncio
 async def test_duplicate_detection_returns_existing(
 self, container_manager, sample_config, agent_session
 ):
 """重复提交返回已有 session 。"""
 from subagent.models import SubAgentSession, generate_execution_id
 existing = await SubAgentSession.objects.acreate(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 work_item_id="",
 target_branch="feature/test",
 container_id="existing-container-id-12345",
 container_name="friday-exec-existing",
 )
 # Mock: get_status 在 _check_duplicate 中通过 self.get_status 调用
 # 而 get_status 内部调用 self._executor.get_status
 container_manager._executor.get_status = AsyncMock(
 return_value={
 "container_id": "existing-cont",
 "status": "running",
 "state": {},
 "created": None,
 }
 )
 container_id = await container_manager.start(sample_config)
 assert container_id == "existing-container-id-12345"
 @pytest.mark.asyncio
 async def test_duplicate_detection_skips_without_work_item_id(
 self, container_manager, sample_config
 ):
 """无 work_item_id 时不检测。"""
 sample_config.work_item_id = ""
 container_id = await container_manager.start(sample_config)
 assert container_id
 @pytest.mark.asyncio
 async def test_duplicate_detection_corrects_stale_status(
 self, container_manager, sample_config, agent_session
 ):
 """容器已退出但数据库仍为 RUNNING 时修正状态。"""
 from subagent.models import SubAgentSession, generate_execution_id
 stale = await SubAgentSession.objects.acreate(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 work_item_id="",
 target_branch="feature/test",
 container_id="stale-container-id",
 container_name="friday-exec-stale",
 )
 # Docker 返回 None → 容器已退出
 container_manager._executor.get_status = AsyncMock(return_value=None)
 container_id = await container_manager.start(sample_config)
 assert container_id # 新容器启动
 await stale.arefresh_from_db
 assert stale.status == SubAgentSession.Status.ERROR
# ============================================================================
# restart 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestRestart:
 @pytest.mark.asyncio
 async def test_restart_creates_new_session(
 self, container_manager, sample_config, agent_session
 ):
 """restart 生成新 session_id 。"""
 from subagent.models import SubAgentSession, generate_execution_id
 old_session = await SubAgentSession.objects.acreate(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 work_item_id="",
 target_branch="feature/test",
 container_id="old-container-id",
 container_name="friday-exec-old",
 )
 original_session_id = sample_config.session_id
 container_id = await container_manager.restart(sample_config)
 assert container_id
 assert sample_config.session_id != original_session_id
 assert sample_config.session_id.startswith("exec-")
 await old_session.arefresh_from_db
 assert old_session.status == SubAgentSession.Status.CANCELLED
# ============================================================================
# stop 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestStop:
 @pytest.mark.asyncio
 async def test_stop_updates_db(self, container_manager, agent_session):
 """stop 更新数据库状态。"""
 from subagent.models import SubAgentSession, generate_execution_id
 session = await SubAgentSession.objects.acreate(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 container_id="container-to-stop",
 container_name="friday-exec-stop",
 )
 result = await container_manager.stop(session.session_id, force=True)
 assert result is True
 await session.arefresh_from_db
 assert session.status == SubAgentSession.Status.CANCELLED
 @pytest.mark.asyncio
 async def test_stop_fallback_to_label(self, container_manager):
 """数据库无记录时通过 Docker label 查找。"""
 mock_container = MagicMock
 mock_container.id = "label-found-container-id"
 container_manager._executor.client.containers.list.return_value = [
 mock_container
 ]
 result = await container_manager.stop("nonexistent-session", force=False)
 assert result is True
# ============================================================================
# get_status 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestGetStatus:
 @pytest.mark.asyncio
 async def test_get_status_combines_db_and_docker(
 self, container_manager, agent_session
 ):
 """get_status 合并数据库和 Docker 信息。"""
 from subagent.models import SubAgentSession, generate_execution_id
 session = await SubAgentSession.objects.acreate(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 container_id="status-container-id",
 container_name="friday-exec-status",
 started_at=timezone.now,
 )
 container_manager._executor.get_status = AsyncMock(
 return_value={
 "container_id": "status-conta",
 "status": "running",
 "state": {"Running": True},
 "created": "2026-02-12T00:00:00Z",
 }
 )
 status = await container_manager.get_status(session.session_id)
 assert status is not None
 assert status["session_id"] == session.session_id
 assert status["status"] == "running"
 assert status["docker_status"] == "running"
 assert status["container_name"] == "friday-exec-status"
 @pytest.mark.asyncio
 async def test_get_status_returns_none_for_unknown(self, container_manager):
 """未知 session 返回 None。"""
 status = await container_manager.get_status("nonexistent")
 assert status is None
# ============================================================================
# 环境变量测试
# ============================================================================
@pytest.mark.django_db
class TestEnvironment:
 def test_environment_variables_use_friday_prefix(
 self, container_manager, sample_config
 ):
 """环境变量统一使用 FRIDAY_* 前缀 。"""
 env = container_manager._build_environment(sample_config)
 for key in env:
 assert key.startswith("FRIDAY_"), f"环境变量 {key} 未使用 FRIDAY_* 前缀"
 def test_environment_includes_git_config(self, container_manager, sample_config):
 """环境变量包含 Git 配置。"""
 env = container_manager._build_environment(sample_config)
 assert env["FRIDAY_GIT_REPO_URL"] == "https://github.com/test/repo.git"
 assert env["FRIDAY_GIT_BRANCH"] == "main"
 assert env["FRIDAY_GIT_TARGET_BRANCH"] == "feature/test"
 def test_environment_includes_claude_config(self, container_manager, sample_config):
 """环境变量包含 Claude 配置。"""
 env = container_manager._build_environment(sample_config)
 assert env["FRIDAY_CLAUDE_API_KEY"] == "test-key"
# ============================================================================
# cleanup 测试
# ============================================================================
@pytest.mark.django_db(transaction=True)
class TestCleanup:
 @pytest.mark.asyncio
 async def test_cleanup_removes_old_containers(
 self, container_manager, agent_session
 ):
 """cleanup 清理过期容器。"""
 from subagent.models import SubAgentSession, generate_execution_id
 await SubAgentSession.objects.acreate(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo.git",
 task_type="coding",
 status=SubAgentSession.Status.COMPLETED,
 container_id="old-completed-container",
 container_name="friday-exec-old",
 completed_at=timezone.now - timedelta(hours=48),
 )
 mock_container = MagicMock
 container_manager._executor.client.containers.get.return_value = mock_container
 total = await container_manager.cleanup(older_than_hours=24)
 assert total >= 1
# ============================================================================
# SubAgentSession 模型测试
# ============================================================================
@pytest.mark.django_db
class TestSubAgentSessionModel:
 def test_generate_execution_id_format(self):
 """验证 execution ID 格式。"""
 from subagent.models import generate_execution_id
 eid = generate_execution_id
 assert eid.startswith("exec-")
 assert len(eid) == 21 # "exec-" (5) + 16 hex chars
 def test_generate_execution_id_unique(self):
 """验证 execution ID 唯一性。"""
 from subagent.models import generate_execution_id
 ids = {generate_execution_id for _ in range(100)}
 assert len(ids) == 100
 def test_status_choices_include_new_states(self):
 """Status 包含 Phase 新增状态。"""
 from subagent.models import SubAgentSession
 status_values = [s.value for s in SubAgentSession.Status]
 assert "pending" in status_values
 assert "timeout" in status_values
 assert "cancelled" in status_values
 assert len(status_values) == 7
 def test_mark_running_sets_fields(self, agent_session):
 """mark_running 设置 container_id、container_name、started_at。"""
 from subagent.models import SubAgentSession, generate_execution_id
 session = SubAgentSession.objects.create(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo",
 task_type="coding",
 status=SubAgentSession.Status.PENDING,
 )
 session.mark_running("container-abc123", "friday-exec-abc123")
 session.refresh_from_db
 assert session.status == SubAgentSession.Status.RUNNING
 assert session.container_id == "container-abc123"
 assert session.container_name == "friday-exec-abc123"
 assert session.started_at is not None
 def test_mark_completed_sets_completed_at(self, agent_session):
 """mark_completed 设置 completed_at。"""
 from subagent.models import SubAgentSession, generate_execution_id
 session = SubAgentSession.objects.create(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 )
 session.mark_completed
 session.refresh_from_db
 assert session.status == SubAgentSession.Status.COMPLETED
 assert session.completed_at is not None
 def test_mark_failed_sets_error(self, agent_session):
 """mark_failed 设置 last_error。"""
 from subagent.models import SubAgentSession, generate_execution_id
 session = SubAgentSession.objects.create(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo",
 task_type="coding",
 status=SubAgentSession.Status.RUNNING,
 )
 session.mark_failed("something went wrong")
 session.refresh_from_db
 assert session.status == SubAgentSession.Status.ERROR
 assert session.last_error == "something went wrong"
 def test_duration_ms(self, agent_session):
 """duration_ms 计算正确。"""
 from subagent.models import SubAgentSession, generate_execution_id
 now = timezone.now
 session = SubAgentSession.objects.create(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo",
 task_type="coding",
 started_at=now - timedelta(seconds=5),
 completed_at=now,
 )
 assert session.duration_ms is not None
 assert session.duration_ms >= 4000
 def test_duration_ms_none_when_incomplete(self, agent_session):
 """未完成时 duration_ms 为 None。"""
 from subagent.models import SubAgentSession, generate_execution_id
 session = SubAgentSession.objects.create(
 session_id=generate_execution_id,
 main_session=agent_session,
 repo_url="https://github.com/test/repo",
 task_type="coding",
 )
 assert session.duration_ms is None
