"""并行执行调度器（Phase）。
资源感知的 FIFO 任务队列，控制容器并发启动。
用户决策：
- FIFO 排序：先入先出，不实现优先级队列
- 无依赖设计：每个任务完全独立
- 动态并发：基于服务器资源自动计算
- 资源阈值：CPU 80% / 内存 80% 时暂停新任务
"""
import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine
import structlog
from django.utils import timezone
from services.container_manager import ContainerConfig, ContainerManager
from services.resource_monitor import (
 check_resource_availability,
 get_running_container_count_async,
)
logger = structlog.get_logger(__name__)
@dataclass
class QueuedTask:
 """队列中的待执行任务。"""
 config: ContainerConfig
 enqueued_at: datetime = field(default_factory=timezone.now)
 # 回调函数，任务启动后调用（可选）
 on_started: Callable[[str], Coroutine[Any, Any, None]] | None = None
class ParallelExecutionScheduler:
 """资源感知的并行执行调度器。
 职责：
 - 维护待执行任务队列（FIFO）
 - 检查资源阈值决定是否启动新容器
 - 监控正在运行的容器数量
 - 容器完成时尝试启动队列中下一个任务
 使用方式：
 1. 通过 enqueue 入队任务
 2. 调度器自动在资源可用时启动
 3. 容器完成后通过 on_container_completed 通知
 单例模式：通过 get_scheduler 获取全局实例
 """
 _instance: "ParallelExecutionScheduler | None" = None
 def __init__(self) -> None:
 self._queue: deque[QueuedTask] = deque
 self._lock = asyncio.Lock
 self._manager = ContainerManager
 self._processing = False
 @classmethod
 def get_instance(cls) -> "ParallelExecutionScheduler":
 """获取全局调度器实例（单例）。"""
 if cls._instance is None:
 cls._instance = cls
 return cls._instance
 @property
 def queue_size(self) -> int:
 """当前队列大小。"""
 return len(self._queue)
 async def enqueue(
 self,
 config: ContainerConfig,
 on_started: Callable[[str], Coroutine[Any, Any, None]] | None = None,
 ) -> str:
 """入队任务（FIFO）。
 任务入队后，调度器会在资源可用时自动启动。
 Args:
 config: 容器启动配置
 on_started: 可选回调，任务启动后调用
 Returns:
 session_id（用于追踪任务状态）
 """
 async with self._lock:
 task = QueuedTask(
 config=config,
 on_started=on_started,
 )
 self._queue.append(task)
 logger.info(
 "task_enqueued",
 session_id=config.session_id,
 queue_size=len(self._queue),
 )
 # 尝试启动队列中的任务
 await self._process_queue
 return config.session_id
 async def enqueue_immediate(
 self,
 config: ContainerConfig,
 ) -> str | None:
 """立即启动任务（跳过队列，用于兼容现有代码）。
 如果资源可用则立即启动，否则返回 None 并入队等待。
 Args:
 config: 容器启动配置
 Returns:
 container_id（成功启动）或 None（入队等待）
 """
 # 检查资源可用性
 running_count = await get_running_container_count_async
 availability = await check_resource_availability(running_count)
 if availability.can_start:
 # 资源可用，立即启动
 container_id = await self._manager.start(config)
 logger.info(
 "task_started_immediately",
 session_id=config.session_id,
 container_id=container_id,
 )
 return container_id
 else:
 # 资源不足，入队等待
 await self.enqueue(config)
 logger.info(
 "task_queued_resource_unavailable",
 session_id=config.session_id,
 reason=availability.reason,
 )
 return None
 async def on_container_completed(self, session_id: str) -> None:
 """容器完成时回调。
 减少运行计数，尝试启动队列中下一个任务。
 Args:
 session_id: 完成的容器 session_id
 """
 logger.info("container_completed_notification", session_id=session_id)
 # 尝试启动队列中的任务
 await self._process_queue
 async def _process_queue(self) -> None:
 """处理队列中的任务。
 在资源可用时启动队列头部的任务。
 使用锁防止并发处理。
 """
 if self._processing:
 return
 self._processing = True
 try:
 while self._queue:
 # 检查资源可用性
 running_count = await get_running_container_count_async
 availability = await check_resource_availability(running_count)
 if not availability.can_start:
 logger.debug(
 "queue_processing_paused",
 reason=availability.reason,
 queue_size=len(self._queue),
 )
 break
 # 取出队头任务
 async with self._lock:
 if not self._queue:
 break
 task = self._queue.popleft
 # 启动容器
 try:
 container_id = await self._manager.start(task.config)
 logger.info(
 "queued_task_started",
 session_id=task.config.session_id,
 container_id=container_id,
 wait_time_seconds=int(
 (timezone.now - task.enqueued_at).total_seconds
 ),
 )
 # 调用启动回调
 if task.on_started:
 await task.on_started(container_id)
 except Exception as e:
 logger.error(
 "queued_task_start_failed",
 session_id=task.config.session_id,
 error=str(e),
 )
 # 启动失败，不重新入队（避免无限重试）
 finally:
 self._processing = False
 async def get_queue_status(self) -> dict:
 """获取队列状态。
 Returns:
 包含队列大小、运行中容器数、资源状态的字典
 """
 running_count = await get_running_container_count_async
 availability = await check_resource_availability(running_count)
 return {
 "queue_size": len(self._queue),
 "running_count": running_count,
 "max_concurrency": availability.max_concurrency,
 "can_start_new": availability.can_start,
 "resource_status": availability.reason,
 "cpu_percent": availability.metrics.cpu_percent,
 "memory_percent": availability.metrics.memory_percent,
 }
 def clear_queue(self) -> int:
 """清空队列（用于测试或紧急情况）。
 Returns:
 被清除的任务数
 """
 count = len(self._queue)
 self._queue.clear
 logger.warning("queue_cleared", cleared_count=count)
 return count
# 便捷函数
def get_scheduler -> ParallelExecutionScheduler:
 """获取全局调度器实例。"""
 return ParallelExecutionScheduler.get_instance
