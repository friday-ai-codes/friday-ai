"""启动 reconcile 的 durable 在途判定 helper（MIGRATE-02）。

语义
====
启动期 reconcile 把 RUNNING 的 IndexHistory / GraphBuildHistory（及仓库聚合态）
标 FAILED 之前，先查该 repo 是否有**在途 durable job 接管**：有则保留 RUNNING，
绝不误杀在途任务（多副本下另一 worker 仍在跑）。

判定经 ``DurableTaskService.has_active_by_key(idempotency_key)`` 门面，按 queueing_lock
（=idempotency_key，如 ``"index:{repo_id}"`` / ``"graph:{repo_id}"``）查活跃集
（procrastinate={todo, doing}）。**绝不**走按数字 job id 的单 job 查询
路径——后者传 deterministic key 会因 ``int(job_id)`` 失败恒返 ``unknown``，令判定误为
False 而误杀在途任务。

后端差异
========
- durable 后端（Postgres + Procrastinate）：委托 ``has_active_by_key`` 真实判定。
- 非 durable 后端（SQLite / in-process，默认 dev / pytest）：``use_procrastinate_backend()``
  为 False 即直接返回 False —— in-process 重启即丢、不承诺续跑，故 reconcile 维持
  旧"标 FAILED"行为，不留僵尸 RUNNING。

fail-safe
=========
整段 ``try/except`` 吞异常返 False（朝"标 FAILED"侧兜底）：判定接口绝不因查询异常
而保留僵尸 RUNNING，也绝不让同步 daemon 线程崩溃。

同步入口
========
``has_active_durable_job_sync`` 经 ``async_to_sync`` 包装异步门面，供 ``AppConfig.ready``
的同步 daemon 线程安全调用，绝不在同步上下文裸 await 异步门面。

约束：本模块对 procrastinate **零直接依赖** —— 在途判定一律经 ``DurableTaskService``
门面（门面内部按后端局部加载队列实现），保持适配层隔离（DURABLE-01）。
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


async def has_active_durable_job(idempotency_key: str) -> bool:
    """查某 ``idempotency_key`` 是否有在途 durable job（有接管则 reconcile 保留 RUNNING）。

    - durable 后端：经 ``DurableTaskService.has_active_by_key`` 按 queueing_lock 查
      活跃集（todo / doing；延迟 job 仍为 todo + scheduled_at）。
    - 非 durable 后端（SQLite / in-process）：``use_procrastinate_backend()`` False →
      直接返回 False（维持旧"标 FAILED"，不留僵尸 RUNNING）。
    - 任何异常 fail-safe 返回 False（朝"标 FAILED"侧兜底）。
    """
    try:
        from durable.service import DurableTaskService, use_procrastinate_backend

        if not use_procrastinate_backend():
            # 非 durable：in-process 重启即丢、不承诺续跑 → 维持旧标 FAILED 行为。
            return False
        return await DurableTaskService.has_active_by_key(idempotency_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "has_active_durable_job_failed",
            idempotency_key=idempotency_key,
            error=str(exc),
        )
        return False


def has_active_durable_job_sync(idempotency_key: str) -> bool:
    """``has_active_durable_job`` 的同步入口（``async_to_sync`` 包装）。

    供 ``AppConfig.ready`` 的同步 daemon 线程调用，绝不在同步上下文裸 await 异步门面；
    任何异常 fail-safe 返回 False。
    """
    try:
        from asgiref.sync import async_to_sync

        return async_to_sync(has_active_durable_job)(idempotency_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "has_active_durable_job_sync_failed",
            idempotency_key=idempotency_key,
            error=str(exc),
        )
        return False


__all__ = ["has_active_durable_job", "has_active_durable_job_sync"]
