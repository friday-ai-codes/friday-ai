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
# Procrastinate durable 后端（Postgres 路径）
# ---------------------------------------------------------------------------


class ProcrastinateBackend:
    """Procrastinate durable 后端：把统一接口委托给 `procrastinate.contrib.django.app`。

    适配层隔离的"命门"：**只有本模块**直接 import procrastinate，业务侧经
    `DurableTaskService` 看不见队列实现。仅当 `_use_procrastinate()` 为真
    （Postgres + backend∈{auto,procrastinate}）时才会被 `service.py` 局部 import
    并触达——SQLite / fallback 路径永不到此。

    `defer/get/cancel/retry_stalled` 全部异步委托 Procrastinate：
    - `defer`：按 `task` 名取已注册任务，`configure(queueing_lock=idempotency_key,
      priority=..., schedule_at=run_at)` 后 `defer_async(**payload)`；queueing_lock
      命中（`AlreadyEnqueued`）按幂等语义吞并返回既有 job 标识。
    - `retry_stalled`：`get_stalled_jobs()`（基于 worker heartbeat，**不传 deprecated
      nb_seconds**，慢≠死）+ `retry_job()` 重投，返回重投计数；供
      `DurableTaskService.retry_stalled` 直接路径与 `tasks.retry_stalled_durable_jobs`
      periodic 复用同一实现。
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
        from procrastinate import exceptions
        from procrastinate.contrib.django import app

        # 按调用方传入的稳定逻辑名查注册表：`durable.tasks` 的每个 @app.task 都显式
        # 声明 `name=`（如 "durable_ping"），与此处查找键是同一 single source of
        # truth——绝不依赖 procrastinate 默认的函数全路径注册名（会与逻辑名不匹配）。
        task_obj = app.tasks.get(task)
        if task_obj is None:
            raise KeyError(
                f"durable 任务 {task!r} 未在 procrastinate app 注册"
                "（确认 durable.tasks 已被 DurableConfig.ready() 导入触发 @app.task，"
                "且 @app.task(name=...) 的显式名与本逻辑名一致）"
            )

        # 仅在显式给出时才透传对应配置项：queueing_lock 让同 key 在 todo 唯一（幂等
        # 入队），schedule_at 落 run_at（延迟调度），priority 影响领取顺序。
        configure_options: dict[str, Any] = {"queue": queue, "priority": priority}
        if idempotency_key is not None:
            configure_options["queueing_lock"] = idempotency_key
        if run_at is not None:
            configure_options["schedule_at"] = run_at

        deferrer = task_obj.configure(**configure_options)
        try:
            job_id = await deferrer.defer_async(**payload)
        except exceptions.AlreadyEnqueued:
            # queueing_lock 命中：todo 已有同 lock 的 job。幂等语义——不报错，
            # 查回既有 job 标识返回（记 info，便于观测）。
            existing = await self._find_job_by_queueing_lock(idempotency_key)
            logger.info(
                "durable_procrastinate_already_enqueued",
                task=task,
                queue=queue,
                idempotency_key=idempotency_key,
                existing_job_id=existing,
            )
            return existing if existing is not None else str(idempotency_key)
        return str(job_id)

    @staticmethod
    async def _find_job_by_queueing_lock(idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        from procrastinate.contrib.django import app

        jobs = list(await app.job_manager.list_jobs_async(queueing_lock=idempotency_key))
        if not jobs:
            return None
        return str(jobs[0].id)

    async def get(self, job_id: str) -> dict[str, Any]:
        # 非数字 / None job_id 优雅返回 unknown，对齐 in-process 后端"从不抛"语义
        # （WR-01）：幂等兜底路径可能返回非数字标识，直接 int() 会崩。
        try:
            jid = int(job_id)
        except (TypeError, ValueError):
            return {"job_id": job_id, "status": "unknown"}
        from procrastinate.contrib.django import app

        jobs = list(await app.job_manager.list_jobs_async(id=jid))
        if not jobs:
            # 未知 / 已被清理的 job：返回结构化 unknown，不抛（与 in-process 一致）。
            return {"job_id": job_id, "status": "unknown"}
        job = jobs[0]
        status = job.status.value if hasattr(job.status, "value") else str(job.status)
        return {
            "job_id": str(job.id),
            "status": status,
            "task": job.task_name,
            "queue": job.queue,
            "priority": job.priority,
            "queueing_lock": job.queueing_lock,
            "scheduled_at": job.scheduled_at,
            "attempts": job.attempts,
        }

    async def cancel(self, job_id: str) -> bool:
        # 非数字 / None job_id 优雅返回 False，对齐 in-process 后端"从不抛"语义（WR-01）。
        try:
            jid = int(job_id)
        except (TypeError, ValueError):
            return False
        from procrastinate.contrib.django import app

        # cancel_job_by_id_async 仅能取消尚未被领取（todo）的 job，返回是否成功。
        return bool(await app.job_manager.cancel_job_by_id_async(jid))

    async def retry_stalled(self) -> int:
        from procrastinate.contrib.django import app

        # 基于 worker heartbeat 判定 stalled（默认 seconds_since_heartbeat=30），
        # 绝不传 deprecated 的 nb_seconds（会误杀仍在跑的慢任务，违反"慢≠死"）。
        stalled_jobs = list(await app.job_manager.get_stalled_jobs())
        count = 0
        for job in stalled_jobs:
            await app.job_manager.retry_job(job)
            count += 1
        if count:
            logger.info("durable_procrastinate_retry_stalled", retried=count)
        return count


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
