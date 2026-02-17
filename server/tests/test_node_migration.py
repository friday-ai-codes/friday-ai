"""Phase 迁移验证测试。
验证 AICodingNode 和 AgentLoop 工具从轮询模式迁移到回调驱动模式。
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from workflows.nodes.ai.coding import AICodingNode
class TestAICodingNodeMigration:
 """AICodingNode 迁移验证测试。"""
 @pytest.mark.asyncio
 async def test_run_repo_coding_returns_waiting_event(self):
 """验证 _run_repo_coding 返回 waiting_event 状态。"""
 node = AICodingNode
 # Mock services module imports (function-level imports)
 with patch("services.container_manager.ContainerManager") as MockManager:
 mock_manager = MagicMock
 mock_manager.start = AsyncMock(return_value="container-123")
 MockManager.return_value = mock_manager
 # Mock repository
 mock_repo = MagicMock
 mock_repo.id = 1
 mock_repo.name = "test-repo"
 mock_repo.git_url = "https://github.com/test/repo.git"
 mock_repo.credential = None
 result = await node._run_repo_coding(
 repository=mock_repo,
 tasks=[{"name": "task1", "coding_instruction": "do something"}],
 branch_name="feat/test",
 base_branch="main",
 global_context="",
 config={},
 node_execution_id="ne-123",
 )
 assert result["status"] == "waiting_event"
 assert "session_id" in result
 assert "container_id" in result
 @pytest.mark.asyncio
 async def test_run_repo_coding_uses_container_manager(self):
 """验证 _run_repo_coding 使用 ContainerManager 而非 SubAgentClient。"""
 node = AICodingNode
 with patch("services.container_manager.ContainerManager") as MockManager:
 mock_manager = MagicMock
 mock_manager.start = AsyncMock(return_value="container-456")
 MockManager.return_value = mock_manager
 # Mock repository
 mock_repo = MagicMock
 mock_repo.id = 2
 mock_repo.name = "test-repo-2"
 mock_repo.git_url = "https://github.com/test/repo2.git"
 mock_repo.credential = None
 result = await node._run_repo_coding(
 repository=mock_repo,
 tasks=[{"name": "task1", "coding_instruction": "do something"}],
 branch_name="feat/test",
 base_branch="main",
 global_context="",
 config={},
 node_execution_id="ne-456",
 )
 # 验证 ContainerManager.start 被调用
 mock_manager.start.assert_called_once
 # 验证返回状态是 waiting_event（回调驱动模式）
 assert result["status"] == "waiting_event"
 @pytest.mark.asyncio
 async def test_run_repo_coding_error_on_container_failure(self):
 """验证容器启动失败时返回 error 状态。"""
 node = AICodingNode
 with patch("services.container_manager.ContainerManager") as MockManager:
 mock_manager = MagicMock
 mock_manager.start = AsyncMock(side_effect=Exception("Docker error"))
 MockManager.return_value = mock_manager
 mock_repo = MagicMock
 mock_repo.id = 3
 mock_repo.name = "test-repo-3"
 mock_repo.git_url = "https://github.com/test/repo3.git"
 mock_repo.credential = None
 result = await node._run_repo_coding(
 repository=mock_repo,
 tasks=[{"name": "task1", "coding_instruction": "do something"}],
 branch_name="feat/test",
 base_branch="main",
 global_context="",
 config={},
 node_execution_id="ne-789",
 )
 assert result["status"] == "error"
 assert "error" in result
 assert "Docker error" in result["error"]
class TestCallbackDrivenMigration:
 """回调驱动迁移验证测试。"""
 def test_schedule_container_cleanup_available(self):
 """验证 _schedule_container_cleanup 函数可导入。"""
 from subagent.api.callbacks import _schedule_container_cleanup
 assert callable(_schedule_container_cleanup)
 def test_schedule_workflow_resume_available(self):
 """验证 _schedule_workflow_resume 函数可导入。"""
 from subagent.api.callbacks import _schedule_workflow_resume
 assert callable(_schedule_workflow_resume)
 def test_schedule_agent_loop_resume_available(self):
 """验证 _schedule_agent_loop_resume 函数可导入。"""
 from subagent.api.callbacks import _schedule_agent_loop_resume
 assert callable(_schedule_agent_loop_resume)
 def test_collect_container_stats_available(self):
 """验证 _collect_container_stats 函数可导入。"""
 from subagent.api.callbacks import _collect_container_stats
 assert callable(_collect_container_stats)
 def test_retry_configuration(self):
 """验证重试配置正确。"""
 from subagent.api.callbacks import MAX_RETRIES, RETRY_DELAYS, RETRYABLE_TASK_TYPES
 assert "explore" in RETRYABLE_TASK_TYPES
 assert "ask" in RETRYABLE_TASK_TYPES
 assert "plan" in RETRYABLE_TASK_TYPES
 assert "coding" not in RETRYABLE_TASK_TYPES
 assert MAX_RETRIES == 2
 assert RETRY_DELAYS == [30, 60]
 def test_container_config_timeouts(self):
 """验证容器超时配置正确。"""
 from services.container_config import TASK_TIMEOUTS, ZOMBIE_HEARTBEAT_SECONDS
 assert TASK_TIMEOUTS["coding"] == 1800 # 30 min
 assert TASK_TIMEOUTS["explore"] == 600 # 10 min
 assert TASK_TIMEOUTS["ask"] == 300 # 5 min
 assert TASK_TIMEOUTS["plan"] == 600 # 10 min
 assert ZOMBIE_HEARTBEAT_SECONDS == 120 # 2 min
 def test_subagent_session_duration_ms(self):
 """验证 SubAgentSession.duration_ms 属性存在。"""
 from subagent.models import SubAgentSession
 # 验证属性存在
 assert hasattr(SubAgentSession, 'duration_ms')
 def test_subagent_session_resource_fields(self):
 """验证 SubAgentSession 资源消耗字段存在。"""
 from subagent.models import SubAgentSession
 # 验证字段存在
 assert hasattr(SubAgentSession, 'cpu_usage_percent')
 assert hasattr(SubAgentSession, 'memory_usage_mb')
class TestContainerTasks:
 """容器任务函数验证测试。"""
 def test_check_container_health_available(self):
 """验证 check_container_health 函数可导入。"""
 from tasks.container_tasks import check_container_health
 assert callable(check_container_health)
 def test_detect_zombie_containers_available(self):
 """验证 detect_zombie_containers 函数可导入。"""
 from tasks.container_tasks import detect_zombie_containers
 assert callable(detect_zombie_containers)
 def test_enforce_task_timeouts_available(self):
 """验证 enforce_task_timeouts 函数可导入。"""
 from tasks.container_tasks import enforce_task_timeouts
 assert callable(enforce_task_timeouts)
 def test_cleanup_completed_containers_available(self):
 """验证 cleanup_completed_containers 函数可导入。"""
 from tasks.container_tasks import cleanup_completed_containers
 assert callable(cleanup_completed_containers)
class TestToolSuspensionBehavior:
 """工具挂起行为验证测试。"""
 def test_dispatch_coding_task_has_suspension_flag(self):
 """验证 dispatch_coding_task 标记为需要挂起。"""
 from agents.tools.base import _tool_registry
 # 检查工具注册表中的 suspension 标志
 tool_def = _tool_registry.get("dispatch_coding_task")
 assert tool_def is not None
 assert tool_def.requires_suspension is True
 def test_explore_repository_has_suspension_flag(self):
 """验证 explore_repository 标记为需要挂起。"""
 from agents.tools.base import _tool_registry
 # 检查工具注册表中的 suspension 标志
 tool_def = _tool_registry.get("explore_repository")
 assert tool_def is not None
 assert tool_def.requires_suspension is True
class TestAICodingNodeBehavior:
 """AICodingNode 行为验证测试。"""
 def test_ai_coding_node_is_blocking(self):
 """验证 AICodingNode 是阻塞节点。"""
 from workflows.nodes.ai.coding import AICodingNode
 assert AICodingNode.is_blocking is True
 def test_ai_coding_node_type(self):
 """验证 AICodingNode 节点类型。"""
 from workflows.nodes.ai.coding import AICodingNode
 assert AICodingNode.node_type == "ai_coding"
 def test_ai_coding_node_has_resume_logic(self):
 """验证 AICodingNode 有恢复逻辑。"""
 from workflows.nodes.ai.coding import AICodingNode
 node = AICodingNode
 # 验证恢复方法存在
 assert hasattr(node, '_resume_after_containers')
 assert callable(node._resume_after_containers)
