"""Task Scheduler — FIFO 队列 + Semaphore 并发控制。"""
from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
import structlog
from .models import TaskInfo
log = structlog.get_logger
class TaskScheduler:
 def __init__(self, max_concurrent: int) -> None:
 self._queue: asyncio.Queue[TaskInfo] = asyncio.Queue
 self._semaphore = asyncio.Semaphore(max_concurrent)
 self._max_concurrent = max_concurrent
 self._active_tasks: dict[str, asyncio.Task[None]] = {}
 self._containers: dict[str, str] = {}
 self._task_callback: Callable[[TaskInfo], Awaitable[None]] | None = None
 def set_task_callback(self, callback: Callable[[TaskInfo], Awaitable[None]]) -> None:
 self._task_callback = callback
 async def submit(self, task: TaskInfo) -> None:
 await self._queue.put(task)
 log.info("task_queued", task_id=task.task_id)
 async def run(self) -> None:
 while True:
 task = await self._queue.get
 await self._semaphore.acquire
 t = asyncio.create_task(self._execute(task))
 self._active_tasks[task.task_id] = t
 async def _execute(self, task: TaskInfo) -> None:
 try:
 if self._task_callback:
 await self._task_callback(task)
 except Exception:
 log.exception("task_execution_failed", task_id=task.task_id)
 finally:
 self._semaphore.release
 self._active_tasks.pop(task.task_id, None)
 def register_container(self, task_id: str, container_id: str) -> None:
 self._containers[task_id] = container_id
 def unregister_container(self, task_id: str) -> None:
 self._containers.pop(task_id, None)
 def get_container_id(self, task_id: str) -> str | None:
 return self._containers.get(task_id)
 @property
 def active_count(self) -> int:
 return len(self._active_tasks)
 @property
 def queued_count(self) -> int:
 return self._queue.qsize
 def get_all_container_ids(self) -> list[str]:
 return list(self._containers.values)
