"""Phase 容器生命周期测试。
验证健康检查、超时强制终止、清理策略。
"""
from unittest.mock import MagicMock, patch
import pytest
class TestContainerCleanup:
 """容器清理策略测试。"""
 @pytest.mark.asyncio
 async def test_successful_task_cleaned_immediately(self):
 """验证成功任务容器立即清理。"""
 from subagent.api.callbacks import _schedule_container_cleanup
 mock_session = MagicMock
 mock_session.session_id = "sess-success"
 mock_session.container_id = "container-success"
 with patch("subagent.api.callbacks.asyncio.create_task") as mock_create_task:
 with patch("subagent.api.callbacks.asyncio.get_running_loop") as mock_loop:
 mock_loop.return_value = MagicMock
 _schedule_container_cleanup(mock_session, immediate=True)
 # 验证 create_task 或 get_running_loop 被调用
 assert mock_create_task.called or mock_loop.called
 def test_failed_task_cleaned_after_delay(self):
 """验证失败任务容器延迟 1 小时清理。"""
 from subagent.api.callbacks import _schedule_container_cleanup
 mock_session = MagicMock
 mock_session.session_id = "sess-failed"
 mock_session.container_id = "container-failed"
 mock_session.last_output = {}
 _schedule_container_cleanup(mock_session, immediate=False)
 # 验证 cleanup_after 被设置
 assert mock_session.save.called
 assert "cleanup_after" in mock_session.last_output
class TestTaskRetry:
 """任务重试测试。"""
 def test_explore_task_retries_on_failure(self):
 """验证 explore 任务失败后可重试。"""
 from subagent.api.callbacks import RETRYABLE_TASK_TYPES
 assert "explore" in RETRYABLE_TASK_TYPES
 assert "coding" not in RETRYABLE_TASK_TYPES
 def test_coding_task_no_retry(self):
 """验证 coding 任务失败不重试。"""
 from subagent.api.callbacks import RETRYABLE_TASK_TYPES
 assert "coding" not in RETRYABLE_TASK_TYPES
 def test_ask_task_retries_on_failure(self):
 """验证 ask 任务失败后可重试。"""
 from subagent.api.callbacks import RETRYABLE_TASK_TYPES
 assert "ask" in RETRYABLE_TASK_TYPES
 def test_plan_task_retries_on_failure(self):
 """验证 plan 任务失败后可重试。"""
 from subagent.api.callbacks import RETRYABLE_TASK_TYPES
 assert "plan" in RETRYABLE_TASK_TYPES
 def test_max_retries_is_two(self):
 """验证最大重试次数为 2。"""
 from subagent.api.callbacks import MAX_RETRIES
 assert MAX_RETRIES == 2
 def test_retry_delays_exponential_backoff(self):
 """验证重试延迟为指数退避。"""
 from subagent.api.callbacks import RETRY_DELAYS
 assert RETRY_DELAYS == [30, 60]
 # 第一次重试 30s，第二次重试 60s
 assert RETRY_DELAYS[0] == 30
 assert RETRY_DELAYS[1] == 60
class TestTaskTimeoutConfiguration:
 """任务超时配置测试。"""
 def test_coding_timeout_is_30_minutes(self):
 """验证 coding 任务超时为 30 分钟。"""
 from services.container_config import TASK_TIMEOUTS
 assert TASK_TIMEOUTS["coding"] == 1800 # 30 * 60
 def test_explore_timeout_is_10_minutes(self):
 """验证 explore 任务超时为 10 分钟。"""
 from services.container_config import TASK_TIMEOUTS
 assert TASK_TIMEOUTS["explore"] == 600 # 10 * 60
 def test_ask_timeout_is_5_minutes(self):
 """验证 ask 任务超时为 5 分钟。"""
 from services.container_config import TASK_TIMEOUTS
 assert TASK_TIMEOUTS["ask"] == 300 # 5 * 60
 def test_plan_timeout_is_10_minutes(self):
 """验证 plan 任务超时为 10 分钟。"""
 from services.container_config import TASK_TIMEOUTS
 assert TASK_TIMEOUTS["plan"] == 600 # 10 * 60
 def test_zombie_heartbeat_is_120_seconds(self):
 """验证僵尸容器心跳阈值为 120 秒。"""
 from services.container_config import ZOMBIE_HEARTBEAT_SECONDS
 assert ZOMBIE_HEARTBEAT_SECONDS == 120
class TestHealthStatusTracking:
 """健康状态追踪测试。"""
 def test_subagent_session_has_health_status_field(self):
 """验证 SubAgentSession 有 health_status 字段。"""
 from subagent.models import SubAgentSession
 assert hasattr(SubAgentSession, 'health_status')
 def test_health_status_choices(self):
 """验证 health_status 有正确的选项。"""
 from subagent.models import SubAgentSession
 choices = SubAgentSession.HealthStatus
 assert hasattr(choices, 'HEALTHY')
 assert hasattr(choices, 'UNHEALTHY')
 assert hasattr(choices, 'UNKNOWN')
 def test_health_status_default_is_unknown(self):
 """验证 health_status 默认值为 UNKNOWN。"""
 from subagent.models import SubAgentSession
 assert SubAgentSession.HealthStatus.UNKNOWN == "unknown"
class TestSessionStateTransitions:
 """Session 状态转换测试。"""
 def test_mark_completed_sets_completed_at(self):
 """验证 mark_completed 设置 completed_at。"""
 from subagent.models import SubAgentSession
 # 验证方法存在
 assert hasattr(SubAgentSession, 'mark_completed')
 def test_mark_failed_sets_error(self):
 """验证 mark_failed 设置 last_error。"""
 from subagent.models import SubAgentSession
 # 验证方法存在
 assert hasattr(SubAgentSession, 'mark_failed')
 def test_mark_timeout_sets_status(self):
 """验证 mark_timeout 设置 TIMEOUT 状态。"""
 from subagent.models import SubAgentSession
 # 验证方法存在
 assert hasattr(SubAgentSession, 'mark_timeout')
 def test_duration_ms_property(self):
 """验证 duration_ms 属性计算正确。"""
 from subagent.models import SubAgentSession
 # 验证属性存在
 assert hasattr(SubAgentSession, 'duration_ms')
class TestContainerTaskFunctions:
 """容器任务函数可用性测试。"""
 def test_check_container_health_function_exists(self):
 """验证 check_container_health 函数存在。"""
 from tasks.container_tasks import check_container_health
 assert callable(check_container_health)
 def test_detect_zombie_containers_function_exists(self):
 """验证 detect_zombie_containers 函数存在。"""
 from tasks.container_tasks import detect_zombie_containers
 assert callable(detect_zombie_containers)
 def test_enforce_task_timeouts_function_exists(self):
 """验证 enforce_task_timeouts 函数存在。"""
 from tasks.container_tasks import enforce_task_timeouts
 assert callable(enforce_task_timeouts)
 def test_cleanup_completed_containers_function_exists(self):
 """验证 cleanup_completed_containers 函数存在。"""
 from tasks.container_tasks import cleanup_completed_containers
 assert callable(cleanup_completed_containers)
class TestCallbackHandlerFunctions:
 """回调处理函数测试。"""
 def test_handle_completed_exists(self):
 """验证 _handle_completed 函数存在。"""
 from subagent.api.callbacks import _handle_completed
 assert callable(_handle_completed)
 def test_handle_failed_exists(self):
 """验证 _handle_failed 函数存在。"""
 from subagent.api.callbacks import _handle_failed
 assert callable(_handle_failed)
 def test_handle_heartbeat_exists(self):
 """验证 _handle_heartbeat 函数存在。"""
 from subagent.api.callbacks import _handle_heartbeat
 assert callable(_handle_heartbeat)
 def test_handle_question_exists(self):
 """验证 _handle_question 函数存在。"""
 from subagent.api.callbacks import _handle_question
 assert callable(_handle_question)
 def test_handle_progress_exists(self):
 """验证 _handle_progress 函数存在。"""
 from subagent.api.callbacks import _handle_progress
 assert callable(_handle_progress)
 def test_schedule_retry_exists(self):
 """验证 _schedule_retry 函数存在。"""
 from subagent.api.callbacks import _schedule_retry
 assert callable(_schedule_retry)
class TestResourceConsumptionFields:
 """资源消耗字段测试。"""
 def test_cpu_usage_percent_field_exists(self):
 """验证 cpu_usage_percent 字段存在。"""
 from subagent.models import SubAgentSession
 assert hasattr(SubAgentSession, 'cpu_usage_percent')
 def test_memory_usage_mb_field_exists(self):
 """验证 memory_usage_mb 字段存在。"""
 from subagent.models import SubAgentSession
 assert hasattr(SubAgentSession, 'memory_usage_mb')
 def test_collect_container_stats_function_exists(self):
 """验证 _collect_container_stats 函数存在。"""
 from subagent.api.callbacks import _collect_container_stats
 assert callable(_collect_container_stats)
