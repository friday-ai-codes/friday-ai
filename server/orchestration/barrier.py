"""BarrierManager — all_of 汇聚逻辑。

管理 run_id 下所有 blocking tasks 的完成状态。
收到每个任务的完成回调时，检查是否全部到达 terminal 状态。
全部完成后调用 on_complete 回调（由 conversation_service 注册）。

存储策略：内存 dict + asyncio.Lock（单进程场景足够）。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from orchestration.contracts import BlockingTaskRequest, BlockingTaskResult

logger = structlog.get_logger()

DEFAULT_TIMEOUT_SECONDS = 30 * 60  # 30 分钟


@dataclass
class BarrierState:
    """单个 run_id 的 barrier 状态。"""

    thread_id: str
    tasks: dict[str, BlockingTaskRequest]
    results: dict[str, BlockingTaskResult]
    on_complete: Callable[[list[BlockingTaskResult]], Awaitable[None]]
    graph_config: dict[str, Any]
    on_progress: Callable[[int, int], Awaitable[None]] | None = None
    timeout_task: asyncio.Task[None] | None = None
    created_at: float = field(default_factory=time.monotonic)


class BarrierManager:
    """all_of barrier 管理器 — 全部任务到达 terminal 状态后触发 resume 回调。"""

    def __init__(self) -> None:
        self._barriers: dict[str, BarrierState] = {}
        self._task_to_run: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        run_id: str,
        thread_id: str,
        tasks: list[BlockingTaskRequest],
        graph_config: dict[str, Any],
        on_complete: Callable[[list[BlockingTaskResult]], Awaitable[None]],
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> None:
        """注册 barrier — 将 tasks 绑定到 run_id，启动安全超时。"""
        task_map = {t["task_id"]: t for t in tasks}

        state = BarrierState(
            thread_id=thread_id,
            tasks=task_map,
            results={},
            on_complete=on_complete,
            graph_config=graph_config,
            on_progress=on_progress,
        )

        self._barriers[run_id] = state
        for task_id in task_map:
            self._task_to_run[task_id] = run_id

        state.timeout_task = asyncio.create_task(
            self._handle_timeout(run_id, timeout_seconds)
        )

        logger.info(
            "barrier_registered",
            run_id=run_id,
            thread_id=thread_id,
            task_count=len(tasks),
            timeout_seconds=timeout_seconds,
        )

    async def task_completed(self, task_id: str, result: BlockingTaskResult) -> bool:
        """通知单个任务完成。返回 True 表示 barrier 已满足（全部完成）。"""
        run_id = self._task_to_run.get(task_id)
        if run_id is None:
            logger.debug("barrier_task_unknown", task_id=task_id)
            return False

        async with self._lock:
            barrier = self._barriers.get(run_id)
            if barrier is None:
                return False

            if task_id in barrier.results:
                return False

            barrier.results[task_id] = result

            await self._persist_progress(run_id, len(barrier.results), len(barrier.tasks))

            if barrier.on_progress is not None:
                try:
                    await barrier.on_progress(len(barrier.results), len(barrier.tasks))
                except Exception:
                    logger.debug("barrier_on_progress_error", run_id=run_id)

            if len(barrier.results) < len(barrier.tasks):
                logger.info(
                    "barrier_task_recorded",
                    run_id=run_id,
                    task_id=task_id,
                    progress=f"{len(barrier.results)}/{len(barrier.tasks)}",
                )
                return False

            # all_of 满足
            if barrier.timeout_task and not barrier.timeout_task.done():
                barrier.timeout_task.cancel()

            results = list(barrier.results.values())
            self._cleanup(run_id)

        logger.info("barrier_satisfied", run_id=run_id, task_count=len(results))
        try:
            await barrier.on_complete(results)
        except Exception:
            logger.exception("barrier_on_complete_error", run_id=run_id)
        return True

    async def cancel_all(self, run_id: str) -> None:
        """取消所有未完成任务并触发 on_complete。"""
        async with self._lock:
            barrier = self._barriers.get(run_id)
            if barrier is None:
                return

            if barrier.timeout_task and not barrier.timeout_task.done():
                barrier.timeout_task.cancel()

            for task_id, req in barrier.tasks.items():
                if task_id not in barrier.results:
                    barrier.results[task_id] = {
                        "task_id": task_id,
                        "task_type": req["task_type"],
                        "success": False,
                        "output": "",
                        "error": "用户取消",
                    }

            await self._persist_progress(run_id, len(barrier.results), len(barrier.tasks))
            results = list(barrier.results.values())
            self._cleanup(run_id)

        logger.info("barrier_cancelled", run_id=run_id)
        try:
            await barrier.on_complete(results)
        except Exception:
            logger.exception("barrier_on_complete_error", run_id=run_id)

    async def _handle_timeout(self, run_id: str, timeout_seconds: float) -> None:
        """安全超时 — 未完成任务标记 timed_out，触发 on_complete。"""
        await asyncio.sleep(timeout_seconds)

        async with self._lock:
            barrier = self._barriers.get(run_id)
            if barrier is None:
                return

            for task_id, req in barrier.tasks.items():
                if task_id not in barrier.results:
                    barrier.results[task_id] = {
                        "task_id": task_id,
                        "task_type": req["task_type"],
                        "success": False,
                        "output": "",
                        "error": "barrier timeout",
                    }

            await self._persist_progress(run_id, len(barrier.results), len(barrier.tasks))
            results = list(barrier.results.values())
            self._cleanup(run_id)

        logger.warning("barrier_timeout", run_id=run_id)
        try:
            await barrier.on_complete(results)
        except Exception:
            logger.exception("barrier_on_complete_error", run_id=run_id)

    async def _persist_progress(self, run_id: str, completed: int, total: int) -> None:
        """持久化进度到 OrchestrationRun.metadata（read-modify-write 保护已有字段）。"""
        try:
            from orchestration.models import OrchestrationRun

            orch_run = await OrchestrationRun.objects.filter(run_id=run_id).afirst()
            if orch_run:
                metadata = orch_run.metadata or {}
                metadata["progress"] = {"completed": completed, "total": total}
                await OrchestrationRun.objects.filter(run_id=run_id).aupdate(metadata=metadata)
        except Exception:
            logger.warning("barrier_progress_persist_failed", run_id=run_id, exc_info=True)

    def _cleanup(self, run_id: str) -> None:
        """从内部映射中移除 barrier 数据。"""
        barrier = self._barriers.pop(run_id, None)
        if barrier:
            for task_id in barrier.tasks:
                self._task_to_run.pop(task_id, None)

    def has_barrier_for_thread(self, thread_id: str) -> bool:
        """检查是否存在指定 thread_id 的活跃 barrier。"""
        return any(b.thread_id == thread_id for b in self._barriers.values())

    def get_pending_tasks(self, run_id: str) -> list[dict[str, Any]]:
        """返回指定 run_id 下尚未到达 terminal 状态的 blocking tasks。"""
        barrier = self._barriers.get(run_id)
        if barrier is None:
            return []
        return [
            dict(barrier.tasks[tid])
            for tid in barrier.tasks
            if tid not in barrier.results
        ]


_barrier_manager: BarrierManager | None = None


def get_barrier_manager() -> BarrierManager:
    """获取全局 BarrierManager 单例。"""
    global _barrier_manager
    if _barrier_manager is None:
        _barrier_manager = BarrierManager()
    return _barrier_manager
