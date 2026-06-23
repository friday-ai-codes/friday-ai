"""任务分发器 — 标签匹配 + 最少任务优先 + 内存队列。"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import structlog
from channels.layers import get_channel_layer
from django.utils import timezone

from runners.protocol import MessageType, make_request

logger = structlog.get_logger()

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
        self._pending: asyncio.Queue[DispatchTask] = asyncio.Queue()
        self._log = structlog.get_logger()

    async def dispatch(self, task: DispatchTask) -> None:
        if not await self._try_assign(task):
            self._pending.put_nowait(task)
            self._log.info("task_queued", task_id=task.task_id)

    async def _try_assign(self, task: DispatchTask) -> bool:
        runners = await self._find_matching_runners(task.tags)
        if not runners:
            return False

        from tools.registry import RemoteToolRegistry

        remote_tools = await RemoteToolRegistry.aget_tools_payload()

        for runner in runners:
            if runner.current_tasks < runner.concurrent:
                # 幂等兜底：同一 session 已有 active(assigned/running) assignment 时
                # 不重复派发（多见于 WS 重连恢复 / 并发触发），避免起第二个容器导致
                # push non-fast-forward 冲突，也避免 current_tasks 被重复 +1。
                if await self._has_active_assignment(task.session_id):
                    self._log.info(
                        "dispatch_skipped_active_assignment",
                        task_id=task.task_id,
                        session_id=task.session_id,
                    )
                    return True
                channel_layer = get_channel_layer()
                await channel_layer.send(
                    runner.channel_name,
                    {
                        "type": "runner.message",
                        "message": make_request(
                            MessageType.TASK_ASSIGN,
                            {
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
                            },
                        ),
                    },
                )
                await self._increment_tasks(runner)
                await self._create_assignment(runner, task)
                self._log.info("task_dispatched", task_id=task.task_id, runner=str(runner.id))
                await channel_layer.group_send(
                    "runner_monitor",
                    {
                        "type": "monitor.event",
                        "data": {
                            "event": "task.status_changed",
                            "runner_id": str(runner.id),
                            "data": {
                                "task_id": task.task_id,
                                "session_id": task.session_id,
                                "status": "assigned",
                                "task_type": task.task_type,
                            },
                        },
                    },
                )
                await self._log_dispatch_event(runner, task)
                return True
        return False

    async def _find_matching_runners(self, tags: list[str]) -> list:
        from runners.models import Runner

        stale_threshold = timezone.now() - timedelta(seconds=HEARTBEAT_STALE_SECONDS)

        # 自动修正心跳超时但仍标记为 online 的 Runner
        await Runner.objects.filter(
            status="online",
            last_heartbeat__lt=stale_threshold,
        ).aupdate(status="offline", channel_name="")

        runners = [
            r
            async for r in Runner.objects.filter(
                status="online",
                is_active=True,
                is_paused=False,
            ).exclude(channel_name="")
        ]
        tag_set = set(tags)
        matched = [r for r in runners if tag_set.issubset(set(r.tags))]
        matched.sort(key=lambda r: r.current_tasks)
        return matched

    async def _increment_tasks(self, runner) -> None:
        from django.db import models as db_models

        from runners.models import Runner

        await Runner.objects.filter(id=runner.id).aupdate(
            current_tasks=db_models.F("current_tasks") + 1
        )

    async def _has_active_assignment(self, session_id: str) -> bool:
        """该 session 是否已有 assigned/running 的 assignment（派发幂等判据）。"""
        from runners.models import RunnerTaskAssignment

        return await RunnerTaskAssignment.objects.filter(
            session__session_id=session_id,
            status__in=[
                RunnerTaskAssignment.Status.ASSIGNED,
                RunnerTaskAssignment.Status.RUNNING,
            ],
        ).aexists()

    async def _create_assignment(self, runner: object, task: DispatchTask) -> None:
        from runners.models import RunnerTaskAssignment
        from subagent.models import SubAgentSession

        session = await SubAgentSession.objects.filter(session_id=task.session_id).afirst()
        if session:
            await RunnerTaskAssignment.objects.acreate(runner=runner, session=session)  # type: ignore[misc]
            session.runner = runner  # type: ignore[assignment]
            await session.asave(update_fields=["runner", "updated_at"])

    async def _log_dispatch_event(self, runner: object, task: DispatchTask) -> None:
        from runners.models import RunnerEvent

        await RunnerEvent.objects.acreate(
            runner=runner,  # type: ignore[misc]
            event_type="task_assigned",
            detail={"task_id": task.task_id, "session_id": task.session_id},
        )

    async def cancel(self, task_id: str) -> bool:
        """向 Runner 发送取消信号。通过 RunnerTaskAssignment 找到 Runner 的 channel。

        Returns:
            True 表示取消信号已发送，False 表示未找到 assignment。
        """
        from runners.models import RunnerTaskAssignment

        assignment = await (
            RunnerTaskAssignment.objects.filter(
                session__session_id=task_id,
                status__in=[
                    RunnerTaskAssignment.Status.ASSIGNED,
                    RunnerTaskAssignment.Status.RUNNING,
                ],
            )
            .select_related("runner")
            .afirst()
        )
        if not assignment or not assignment.runner.channel_name:
            self._log.warning("cancel_no_assignment", task_id=task_id)
            return False

        channel_layer = get_channel_layer()
        await channel_layer.send(
            assignment.runner.channel_name,
            {
                "type": "runner.message",
                "message": make_request(
                    MessageType.TASK_CANCEL,
                    {"task_id": task_id},
                ),
            },
        )
        self._log.info(
            "task_cancel_sent",
            task_id=task_id,
            runner_id=str(assignment.runner.id),
        )
        return True

    async def drain_pending(self) -> None:
        """把内存待派发队列里的任务尽量分配给当前有空槽的 runner。

        在三种时机调用：① runner 上线/重连（``on_runner_online``）；② 任务被拒
        重排（``on_task_rejected`` 后由调用方触发）；③ **任务完成/失败释放并发槽位**
        （``consumers._handle_task_completed/_handle_task_failed``）。

        ：此前仅在 runner 重连时排空 ``_pending``，任务完成释放槽位时**不**续派，
        导致批量派发（如几百个仓库的 repo_summary）只跑前 ``runner.concurrent`` 个、
        其余永久卡在内存队列直到 runner 重连或超时。新增本方法在完成时续派，使队列
        随空槽连续消费、批量任务能逐个跑完。

        逐个尝试 ``_try_assign``；遇到第一个无法分配的（无空槽/无匹配 runner）即停止
        并把它放回队列，避免空转（剩余任务等下一次释放槽位/重连再排）。
        """
        while not self._pending.empty():
            try:
                task = self._pending.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not await self._try_assign(task):
                self._pending.put_nowait(task)
                break

    async def on_runner_online(self, runner_id: uuid.UUID) -> None:
        await self.drain_pending()

    async def on_task_rejected(self, task_id: str, task: DispatchTask) -> None:
        self._pending.put_nowait(task)
        self._log.info("task_requeued", task_id=task_id)


_dispatcher: TaskDispatcher | None = None


def get_dispatcher() -> TaskDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = TaskDispatcher()
    return _dispatcher
