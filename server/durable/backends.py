"""durable 后端实现：协议 + in-process fallback + Procrastinate 占位。

适配层隔离的"命门"在此：业务代码只见 `durable.service.DurableTaskService`，
后端选择（Procrastinate / in-process）藏在这一层后面。**只有本模块**（以及
Plan 60-03 产出的 `durable.tasks` / `durable.management`）允许直接 import
procrastinate；其余业务代码经 grep 守护断言零直接 import（DURABLE-01 核心约束）。

本 plan（60-01）只让 `InProcessBackend` 完整可用（复用 `services.background_runner`
的常驻 worker loop），保证 SQLite / 无 `DATABASE_URL` 的 dev / pytest 开箱即用、
不触达 Postgres。`ProcrastinateBackend` 仅留占位 stub，真正实现由 Plan 60-03 落地。
"""

from __future__ import annotations

import datetime
import threading
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import structlog
from asgiref.sync import sync_to_async

from services.background_runner import cancel_background_task, run_in_background

logger = structlog.get_logger(__name__)


class DurableBackend(Protocol):
    """durable 后端协议：所有后端（Procrastinate / in-process）的统一异步契约。

    `DurableTaskService` 经 `_use_procrastinate()` 在两实现间选择，业务侧不感知。
    """

    async def defer(
        self,
        task: str,
        payload: dict[str, Any],
        *,
        queue: str,
        priority: int = 0,
        idempotency_key: str | None = None,
        run_at: datetime.datetime | None = None,
    ) -> str:
        """入队一个任务，返回 job id 字符串。"""
        ...

    async def get(self, job_id: str) -> dict[str, Any]:
        """查询 job 当前状态，返回结构化 dict。"""
        ...

    async def cancel(self, job_id: str) -> bool:
        """取消一个尚未完成的 job，返回是否成功取消。"""
        ...

    async def retry_stalled(self) -> int:
        """重投 stalled 任务，返回重投数量。"""
        ...


# ---------------------------------------------------------------------------
# In-process fallback（非 durable，dev / pytest 用）
# ---------------------------------------------------------------------------

# 任务处理器注册表：task 名 → async handler(payload)。本 plan 不注册任何业务
# 任务（迁移由 Phase 61/62 做）；未注册的 task 在 fallback 下记录为 no-op 成功，
# 保证 dev / pytest 不因"无 Postgres + 无已接任务"而报错。
_handlers: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {}
# 模块级 in-flight job 状态注册表（job_id → 状态 dict）。fallback 非 durable，
# 状态仅进程内可见、进程重启即丢——这正是它"非 durable"的语义。
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def register_handler(task: str, handler: Callable[[dict[str, Any]], Awaitable[Any]]) -> None:
    """登记 in-process fallback 下某个 task 名对应的 async handler。

    供后续阶段在 fallback 路径下接入真实任务；本 plan 不调用。
    """
    _handlers[task] = handler


def _set_job_state(job_id: str, **fields: Any) -> None:
    with _jobs_lock:
        state = _jobs.setdefault(job_id, {"job_id": job_id})
        state.update(fields)


class InProcessBackend:
    """进程内非 durable 后端：复用 `background_runner` 的常驻 daemon worker loop。

    无 Postgres / SQLite 场景下的 fallback。不承诺持久化、重启续跑或跨副本可见，
    仅保证"defer/get/cancel/retry_stalled 接口可用且不报错"，让 `make dev` / pytest
    无需 Postgres 即可跑通入队语义。
    """

    async def defer(
        self,
        task: str,
        payload: dict[str, Any],
        *,
        queue: str,
        priority: int = 0,
        idempotency_key: str | None = None,
        run_at: datetime.datetime | None = None,
    ) -> str:
        # idempotency_key 直接用作 background_runner 的 name：同 key 二次 defer
        # 会覆盖同名注册（行为可预期、可观测），不静默吞。无 key 时派生稳定 id。
        job_id = idempotency_key or f"durable:{queue}:{uuid.uuid4().hex}"
        _set_job_state(
            job_id,
            status="pending",
            task=task,
            queue=queue,
            priority=priority,
        )

        handler = _handlers.get(task)

        def _factory() -> Awaitable[Any]:
            return self._run_job(job_id, task, payload, handler, run_at)

        run_in_background(_factory, name=job_id)
        return job_id

    async def _run_job(
        self,
        job_id: str,
        task: str,
        payload: dict[str, Any],
        handler: Callable[[dict[str, Any]], Awaitable[Any]] | None,
        run_at: datetime.datetime | None,
    ) -> Any:
        # run_at 延迟调度：fallback 用进程内 sleep 逼近 schedule_at（非 durable）。
        if run_at is not None:
            now = datetime.datetime.now(tz=run_at.tzinfo)
            delay = (run_at - now).total_seconds()
            if delay > 0:
                import asyncio

                await asyncio.sleep(delay)

        _set_job_state(job_id, status="running")
        try:
            if handler is None:
                # 未注册任务：fallback 下记一条 debug 后视作 no-op 成功，
                # 不阻断 dev / pytest（真实任务接入由后续阶段做）。
                logger.debug("durable_inprocess_noop_task", task=task, job_id=job_id)
                result = None
            else:
                result = await handler(payload)
        except Exception as exc:  # noqa: BLE001
            _set_job_state(job_id, status="failed", error=str(exc))
            logger.warning(
                "durable_inprocess_job_failed",
                task=task,
                job_id=job_id,
                error=str(exc),
            )
            raise
        else:
            _set_job_state(job_id, status="succeeded")
            return result

    async def get(self, job_id: str) -> dict[str, Any]:
        with _jobs_lock:
            state = _jobs.get(job_id)
            if state is not None:
                return dict(state)
        # 未知 job（从未 defer 过 / 进程重启后丢失）：返回结构化 unknown，不抛。
        return {"job_id": job_id, "status": "unknown"}

    async def cancel(self, job_id: str) -> bool:
        cancelled = await sync_to_async(cancel_background_task, thread_sensitive=False)(job_id)
        if cancelled:
            _set_job_state(job_id, status="cancelled")
        return bool(cancelled)

    async def retry_stalled(self) -> int:
        # in-process fallback 非 durable，无 lease / heartbeat / stalled 概念，
        # 故为安全 no-op（返回 0）。真正的 stalled rescue 是 Procrastinate 后端
        # 的 periodic 任务（Plan 60-03）。
        return 0


def _reset_for_tests() -> None:
    """测试钩子：清空 in-process job 状态注册表（handler 注册保留）。"""
    with _jobs_lock:
        _jobs.clear()


# ---------------------------------------------------------------------------
# Procrastinate 后端占位（真正实现由 Plan 60-03 落地）
# ---------------------------------------------------------------------------


class ProcrastinateBackend:
    """Procrastinate durable 后端占位。

    本 plan 仅保证符号存在，供 `service.py` 懒局部 import 选择后端时可解析；
    SQLite / fallback 路径永不触达此类。所有方法体在 Plan 60-03 实现前抛
    NotImplementedError，避免被误用。
    """

    async def defer(
        self,
        task: str,
        payload: dict[str, Any],
        *,
        queue: str,
        priority: int = 0,
        idempotency_key: str | None = None,
        run_at: datetime.datetime | None = None,
    ) -> str:
        raise NotImplementedError("procrastinate backend 由 Plan 60-03 实现")

    async def get(self, job_id: str) -> dict[str, Any]:
        raise NotImplementedError("procrastinate backend 由 Plan 60-03 实现")

    async def cancel(self, job_id: str) -> bool:
        raise NotImplementedError("procrastinate backend 由 Plan 60-03 实现")

    async def retry_stalled(self) -> int:
        raise NotImplementedError("procrastinate backend 由 Plan 60-03 实现")


# 模块级单例：service.py 懒局部 import 这两个符号委托。
in_process_backend = InProcessBackend()
procrastinate_backend = ProcrastinateBackend()


__all__ = [
    "DurableBackend",
    "InProcessBackend",
    "ProcrastinateBackend",
    "in_process_backend",
    "procrastinate_backend",
    "register_handler",
]
