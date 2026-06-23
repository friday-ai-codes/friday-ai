"""DurableTaskService：durable 任务的统一入口（业务侧唯一门面）。

业务代码只 import 本模块的 `DurableTaskService` 与 `durable.queues` 的队列常量，
**绝不直接 import procrastinate**。后端选择（Procrastinate / in-process fallback）
经唯一权威判定 `_use_procrastinate(engine, backend)` 决定，并在方法体内**局部
import** 对应后端，确保 procrastinate 仅在真正启用时被加载。

循环 import 约束（关键）
=======================
settings.py 在 `django.setup()` 期会 `from durable.service import _use_procrastinate`
复用同一判定（Plan 60-03 的 `procrastinate.contrib.django` 条件注册）。因此本模块
**顶层只放 stdlib / typing 导入，绝不在顶层 `from django.conf import settings`
或访问 settings 属性**——所有 settings 读取一律放在函数体内局部，避免循环 import。
"""

from __future__ import annotations

import datetime
from typing import Any


def _use_procrastinate(engine: str, backend: str) -> bool:
    """唯一权威后端判定（纯函数、模块级、零 Django 依赖）。

    这是后端选择的 single source of truth：service 与 settings.py 共用同一函数，
    禁止另写等价判据。

    语义（amended：production 默认 Postgres 即 durable 开箱即用）：
    当且仅当 默认 DB 引擎含 ``postgresql`` 且 ``DURABLE_TASK_BACKEND ∈
    {auto, procrastinate}`` 时返回 True（启用 Procrastinate durable 后端）。

    真值表：
    - ``("postgresql", "auto")``        → True   （auto + Postgres，durable 开箱即用）
    - ``("sqlite", "auto")``            → False  （dev / pytest，in-process fallback）
    - ``("postgresql", "procrastinate")`` → True
    - ``("postgresql", "inprocess")``   → False  （强制 fallback，即便 Postgres）
    - ``("sqlite", "procrastinate")``   → False  （非 Postgres，fail-soft 回退）

    Args:
        engine: Django ``DATABASES["default"]["ENGINE"]`` 字符串。
        backend: ``DURABLE_TASK_BACKEND`` 值（auto / procrastinate / inprocess / ...）。
    """
    return ("postgresql" in (engine or "").lower()) and (
        (backend or "auto").strip().lower() in {"auto", "procrastinate"}
    )


def use_procrastinate_backend() -> bool:
    """读取 settings 后委托 `_use_procrastinate` 判定是否启用 Procrastinate。

    fail-soft：当显式要求 ``backend="procrastinate"`` 但引擎非 postgresql 时，
    记一条 warning 后回退 fallback（返回 False），**不在启动期 raise**（dev 安全）。
    """
    from django.conf import settings

    engine = settings.DATABASES["default"]["ENGINE"]
    backend = getattr(settings, "DURABLE_TASK_BACKEND", "auto")

    result = _use_procrastinate(engine, backend)
    if (
        not result
        and (backend or "").strip().lower() == "procrastinate"
        and "postgresql" not in (engine or "").lower()
    ):
        import structlog

        structlog.get_logger(__name__).warning(
            "durable_backend_fallback_non_postgres",
            engine=engine,
            backend=backend,
        )
    return result


class DurableTaskService:
    """durable 任务统一入口：Postgres → Procrastinate / 否则 in-process fallback。

    所有方法按 `use_procrastinate_backend()` 在**方法体内局部 import** 对应后端
    后委托——局部 import 是适配层隔离的命门，模块顶层绝不 import procrastinate。
    """

    @staticmethod
    async def defer(
        task: str,
        payload: dict[str, Any],
        *,
        queue: str,
        priority: int = 0,
        idempotency_key: str | None = None,
        run_at: datetime.datetime | None = None,
        lock: str | None = None,
    ) -> str:
        """入队一个 durable 任务，返回 job id。

        ``lock``：Procrastinate 原生 doing 并发锁（同 lock 串行执行），与
        ``idempotency_key``（= queueing_lock，todo 去重）正交并存。索引/图谱用
        ``lock=index-slot-{N}`` 槽位池实现可配上限的并发治理（CONC-01）；
        in-process fallback 无 doing 并发概念，``lock`` 被忽略（dev/pytest 串行）。
        """
        if use_procrastinate_backend():
            from durable.backends import procrastinate_backend

            return await procrastinate_backend.defer(
                task,
                payload,
                queue=queue,
                priority=priority,
                idempotency_key=idempotency_key,
                run_at=run_at,
                lock=lock,
            )
        from durable.backends import in_process_backend

        return await in_process_backend.defer(
            task,
            payload,
            queue=queue,
            priority=priority,
            idempotency_key=idempotency_key,
            run_at=run_at,
            lock=lock,
        )

    @staticmethod
    async def get(job_id: str) -> dict[str, Any]:
        """查询 job 当前状态（结构化 dict）。"""
        if use_procrastinate_backend():
            from durable.backends import procrastinate_backend

            return await procrastinate_backend.get(job_id)
        from durable.backends import in_process_backend

        return await in_process_backend.get(job_id)

    @staticmethod
    async def cancel(job_id: str) -> bool:
        """取消一个尚未完成的 job，返回是否成功取消。"""
        if use_procrastinate_backend():
            from durable.backends import procrastinate_backend

            return await procrastinate_backend.cancel(job_id)
        from durable.backends import in_process_backend

        return await in_process_backend.cancel(job_id)

    @staticmethod
    async def has_active_by_key(idempotency_key: str) -> bool:
        """按 idempotency_key（=queueing_lock）查是否有在途 job，区别于按数字 job id 的 `get`。

        活跃集：procrastinate={todo, doing}、in-process={pending, running}。
        传 deterministic key（如 ``"index:{repo_id}"``）给 ``get`` 会因 ``int(job_id)``
        失败恒返 unknown、令 reconcile 误判，本门面按 queueing_lock 查给出正确判定
        （Plan 03 reconcile 不误杀在途任务的前置接口）。
        """
        if use_procrastinate_backend():
            from durable.backends import procrastinate_backend

            return await procrastinate_backend.has_active_by_key(idempotency_key)
        from durable.backends import in_process_backend

        return await in_process_backend.has_active_by_key(idempotency_key)

    @staticmethod
    async def retry_stalled() -> int:
        """重投 stalled 任务，返回重投数量（in-process 后端恒为 0）。"""
        if use_procrastinate_backend():
            from durable.backends import procrastinate_backend

            return await procrastinate_backend.retry_stalled()
        from durable.backends import in_process_backend

        return await in_process_backend.retry_stalled()


__all__ = ["DurableTaskService", "_use_procrastinate", "use_procrastinate_backend"]
