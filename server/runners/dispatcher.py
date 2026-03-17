"""任务分发器 — 标签匹配 + 最少任务优先 + 内存队列。"""
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
import structlog
from channels.layers import get_channel_layer
from django.utils import timezone
from runners.protocol import MessageType, make_request
logger = structlog.get_logger
# 心跳超时阈值（秒）：3 倍心跳间隔（Runner 每 30 秒心跳）
HEARTBEAT_STALE_SECONDS = 90
@dataclass
class DispatchTask:
 task_id: str
 task_type: str
 tags: list[str]
 image: str
 repo_url: str
 branch: str
 target_branch: str
 prompt: str
 timeout: int
 node_execution_id: str
 session_id: str
 metadata: dict = field(default_factory=dict)
class TaskDispatcher:
 """任务分发器 — AICodingNode 唯一的任务执行入口。"""
 def __init__(self) -> None:
 self._pending: asyncio.Queue[DispatchTask] = asyncio.Queue
 self._log = structlog.get_logger
 async def dispatch(self, task: DispatchTask) -> None:
 if not await self._try_assign(task):
 self._pending.put_nowait(task)
 self._log.info("task_queued", task_id=task.task_id)
 async def _try_assign(self, task: DispatchTask) -> bool:
 runners = await self._find_matching_runners(task.tags)
 if not runners:
 return False
 from tools.registry import RemoteToolRegistry
 remote_tools = await RemoteToolRegistry.aget_tools_payload
 for runner in runners:
 if runner.current_tasks < runner.concurrent:
 channel_layer = get_channel_layer
 await channel_layer.send(
 runner.channel_name,
 {
 "type": "runner.message",
 "message": make_request(MessageType.TASK_ASSIGN, {
 "task_id": task.task_id,
 "task_type": task.task_type,
 "image": task.image,
 "repo_url": task.repo_url,
 "branch": task.branch,
 "target_branch": task.target_branch,
 "prompt": task.prompt,
 "timeout": task.timeout,
 "session_id": task.session_id,
 "metadata": task.metadata,
 "remote_tools": remote_tools,
 }),
 },
 )
 await self._increment_tasks(runner)
 await self._create_assignment(runner, task)
 self._log.info("task_dispatched", task_id=task.task_id, runner=str(runner.id))
 await channel_layer.group_send("runner_monitor", {
 "type": "monitor.event",
 "data": {
 "event": "task.status_changed",
 "runner_id": str(runner.id),
 "data": {"task_id": task.task_id, "session_id": task.session_id, "status": "assigned", "task_type": task.task_type},
 },
 })
 await self._log_dispatch_event(runner, task)
 return True
 return False
 async def _find_matching_runners(self, tags: list[str]) -> list:
 from runners.models import Runner
 stale_threshold = timezone.now - timedelta(seconds=HEARTBEAT_STALE_SECONDS)
 # 自动修正心跳超时但仍标记为 online 的 Runner
 await Runner.objects.filter(
 status="online",
 last_heartbeat__lt=stale_threshold,
 ).aupdate(status="offline", channel_name="")
 runners = [
 r async for r in Runner.objects.filter(
 status="online", is_active=True, is_paused=False,
 ).exclude(channel_name="")
 ]
 tag_set = set(tags)
 matched = [r for r in runners if tag_set.issubset(set(r.tags))]
 matched.sort(key=lambda r: r.current_tasks)
 return matched
 async def _increment_tasks(self, runner) -> None: # type: ignore[no-untyped-def]
 from django.db import models as db_models
 from runners.models import Runner
 await Runner.objects.filter(id=runner.id).aupdate(
 current_tasks=db_models.F("current_tasks") + 1
 )
 async def _create_assignment(self, runner: object, task: DispatchTask) -> None:
 from runners.models import RunnerTaskAssignment
 from subagent.models import SubAgentSession
 session = await SubAgentSession.objects.filter(session_id=task.session_id).afirst
 if session:
 await RunnerTaskAssignment.objects.acreate(runner=runner, session=session) # type: ignore[misc]
 session.runner = runner # type: ignore[assignment]
 await session.asave(update_fields=["runner", "updated_at"])
 async def _log_dispatch_event(self, runner: object, task: DispatchTask) -> None:
 from runners.models import RunnerEvent
 await RunnerEvent.objects.acreate(
 runner=runner, # type: ignore[misc]
 event_type="task_assigned",
 detail={"task_id": task.task_id, "session_id": task.session_id},
 )
 async def on_runner_online(self, runner_id: uuid.UUID) -> None:
 while not self._pending.empty:
 try:
 task = self._pending.get_nowait
 except asyncio.QueueEmpty:
 break
 if not await self._try_assign(task):
 self._pending.put_nowait(task)
 break
 async def on_task_rejected(self, task_id: str, task: DispatchTask) -> None:
 self._pending.put_nowait(task)
 self._log.info("task_requeued", task_id=task_id)
_dispatcher: TaskDispatcher | None = None
def get_dispatcher -> TaskDispatcher:
 global _dispatcher
 if _dispatcher is None:
 _dispatcher = TaskDispatcher
 return _dispatcher
