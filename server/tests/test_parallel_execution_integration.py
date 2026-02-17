"""并行执行集成测试（Phase）。
验证：
1. 资源充足时立即启动
2. 资源不足时入队等待
3. 容器完成后自动启动队列任务
4. FIFO 顺序保证
5. 资源阈值正确触发
"""
from unittest.mock import AsyncMock, patch
import pytest
from services.container_manager import ContainerConfig
from services.parallel_scheduler import ParallelExecutionScheduler
from services.resource_monitor import ResourceAvailability, ResourceMetrics
@pytest.fixture
def scheduler:
 """创建新的调度器实例。"""
 return ParallelExecutionScheduler
@pytest.fixture
def configs:
 """创建多个测试配置。"""
 return [
 ContainerConfig(session_id=f"session-{i:03d}", task_type="coding")
 for i in range(5)
 ]
class TestResourceAwareScheduling:
 """测试资源感知调度。"""
 @pytest.mark.asyncio
 @patch("services.parallel_scheduler.get_running_container_count_async")
 @patch("services.parallel_scheduler.check_resource_availability")
 async def test_immediate_start_when_available(
 self, mock_check, mock_count, scheduler, configs
 ):
 """资源可用时立即启动。"""
 mock_count.return_value = 0
 mock_check.return_value = ResourceAvailability(
 can_start=True,
 reason="资源充足",
 metrics=ResourceMetrics(30, 40, 16, 8),
 max_concurrency=4,
 current_running=0,
 )
 with patch.object(
 scheduler._manager, "start", new_callable=AsyncMock
 ) as mock_start:
 mock_start.return_value = "container-001"
 result = await scheduler.enqueue_immediate(configs[0])
 assert result == "container-001"
 assert scheduler.queue_size == 0
 @pytest.mark.asyncio
 @patch("services.parallel_scheduler.get_running_container_count_async")
 @patch("services.parallel_scheduler.check_resource_availability")
 async def test_queue_when_cpu_high(self, mock_check, mock_count, scheduler, configs):
 """CPU 过高时入队。"""
 mock_count.return_value = 2
 mock_check.return_value = ResourceAvailability(
 can_start=False,
 reason="CPU 使用率过高 (85% >= 80%)",
 metrics=ResourceMetrics(85, 40, 16, 8),
 max_concurrency=4,
 current_running=2,
 )
 with patch.object(scheduler, "_process_queue", new_callable=AsyncMock):
 result = await scheduler.enqueue_immediate(configs[0])
 assert result is None
 assert scheduler.queue_size == 1
 @pytest.mark.asyncio
 @patch("services.parallel_scheduler.get_running_container_count_async")
 @patch("services.parallel_scheduler.check_resource_availability")
 async def test_queue_when_memory_high(
 self, mock_check, mock_count, scheduler, configs
 ):
 """内存过高时入队。"""
 mock_count.return_value = 2
 mock_check.return_value = ResourceAvailability(
 can_start=False,
 reason="内存使用率过高 (85% >= 80%)",
 metrics=ResourceMetrics(50, 85, 4, 8),
 max_concurrency=4,
 current_running=2,
 )
 with patch.object(scheduler, "_process_queue", new_callable=AsyncMock):
 result = await scheduler.enqueue_immediate(configs[0])
 assert result is None
 assert scheduler.queue_size == 1
 @pytest.mark.asyncio
 @patch("services.parallel_scheduler.get_running_container_count_async")
 @patch("services.parallel_scheduler.check_resource_availability")
 async def test_queue_when_max_concurrency_reached(
 self, mock_check, mock_count, scheduler, configs
 ):
 """达到最大并发时入队。"""
 mock_count.return_value = 4
 mock_check.return_value = ResourceAvailability(
 can_start=False,
 reason="已达最大并发数 (4/4)",
 metrics=ResourceMetrics(50, 60, 16, 8),
 max_concurrency=4,
 current_running=4,
 )
 with patch.object(scheduler, "_process_queue", new_callable=AsyncMock):
 result = await scheduler.enqueue_immediate(configs[0])
 assert result is None
 assert scheduler.queue_size == 1
class TestFIFOOrdering:
 """测试 FIFO 顺序。"""
 @pytest.mark.asyncio
 async def test_fifo_queue_order(self, scheduler, configs):
 """验证 FIFO 入队顺序。"""
 with patch.object(scheduler, "_process_queue", new_callable=AsyncMock):
 for config in configs:
 await scheduler.enqueue(config)
 assert scheduler.queue_size == 5
 # 验证顺序
 for i, task in enumerate(scheduler._queue):
 assert task.config.session_id == f"session-{i:03d}"
 @pytest.mark.asyncio
 @patch("services.parallel_scheduler.get_running_container_count_async")
 @patch("services.parallel_scheduler.check_resource_availability")
 async def test_fifo_dequeue_order(
 self, mock_check, mock_count, scheduler, configs
 ):
 """验证 FIFO 出队顺序。"""
 # 先入队所有任务（资源不可用）
 mock_count.return_value = 4
 mock_check.return_value = ResourceAvailability(
 can_start=False,
 reason="已达最大并发数",
 metrics=ResourceMetrics(50, 60, 16, 8),
 max_concurrency=4,
 current_running=4,
 )
 with patch.object(scheduler, "_process_queue", new_callable=AsyncMock):
 for config in configs:
 await scheduler.enqueue(config)
 assert scheduler.queue_size == 5
 # 模拟资源可用，处理队列
 started_order: list[str] =
 mock_check.return_value = ResourceAvailability(
 can_start=True,
 reason="资源充足",
 metrics=ResourceMetrics(30, 40, 16, 8),
 max_concurrency=4,
 current_running=0,
 )
 with patch.object(
 scheduler._manager, "start", new_callable=AsyncMock
 ) as mock_start:
 async def track_start(config: ContainerConfig) -> str:
 started_order.append(config.session_id)
 return f"container-{config.session_id}"
 mock_start.side_effect = track_start
 # 处理整个队列
 scheduler._processing = False
 await scheduler._process_queue
 # 验证 FIFO 顺序
 assert started_order == [
 "session-000",
 "session-001",
 "session-002",
 "session-003",
 "session-004",
 ]
class TestAutoScheduling:
 """测试自动调度。"""
 @pytest.mark.asyncio
 @patch("services.parallel_scheduler.get_running_container_count_async")
 @patch("services.parallel_scheduler.check_resource_availability")
 async def test_container_completion_triggers_queue_processing(
 self, mock_check, mock_count, scheduler, configs
 ):
 """容器完成后自动处理队列。"""
 # 入队一个任务
 mock_count.return_value = 4
 mock_check.return_value = ResourceAvailability(
 can_start=False,
 reason="已达最大并发数",
 metrics=ResourceMetrics(50, 60, 16, 8),
 max_concurrency=4,
 current_running=4,
 )
 with patch.object(scheduler, "_process_queue", new_callable=AsyncMock):
 await scheduler.enqueue(configs[0])
 assert scheduler.queue_size == 1
 # 模拟容器完成，资源变得可用
 mock_count.return_value = 3
 mock_check.return_value = ResourceAvailability(
 can_start=True,
 reason="资源充足",
 metrics=ResourceMetrics(50, 60, 16, 8),
 max_concurrency=4,
 current_running=3,
 )
 with patch.object(
 scheduler._manager, "start", new_callable=AsyncMock
 ) as mock_start:
 mock_start.return_value = "container-new"
 # 通知容器完成
 await scheduler.on_container_completed("some-completed-session")
 # 验证队列任务被启动
 assert scheduler.queue_size == 0
 mock_start.assert_called_once
class TestGetQueueStatus:
 """测试队列状态查询。"""
 @pytest.mark.asyncio
 @patch("services.parallel_scheduler.get_running_container_count_async")
 @patch("services.parallel_scheduler.check_resource_availability")
 async def test_status_includes_all_info(self, mock_check, mock_count, scheduler):
 """验证状态包含所有必要信息。"""
 mock_count.return_value = 2
 mock_check.return_value = ResourceAvailability(
 can_start=True,
 reason="资源充足",
 metrics=ResourceMetrics(45.5, 62.3, 12.5, 8),
 max_concurrency=6,
 current_running=2,
 )
 status = await scheduler.get_queue_status
 assert "queue_size" in status
 assert "running_count" in status
 assert "max_concurrency" in status
 assert "can_start_new" in status
 assert "cpu_percent" in status
 assert "memory_percent" in status
 assert status["running_count"] == 2
 assert status["max_concurrency"] == 6
 assert status["can_start_new"] is True
class TestClearQueue:
 """测试清空队列。"""
 @pytest.mark.asyncio
 async def test_clear_queue_removes_all_tasks(self, scheduler, configs):
 """验证清空队列移除所有任务。"""
 with patch.object(scheduler, "_process_queue", new_callable=AsyncMock):
 for config in configs:
 await scheduler.enqueue(config)
 assert scheduler.queue_size == 5
 cleared = scheduler.clear_queue
 assert cleared == 5
 assert scheduler.queue_size == 0
