"""恢复调度：启动时扫描租约过期的 RUNNING 任务并按 kind 路由续跑。

恢复语义：
- 仅领取租约过期（lease_expires_at < now）的 RUNNING 行 —— 多副本下不会误抢
  另一个 Pod 仍在跑的活任务。
- 领取用 ``claim_expired`` 原子 CAS（attempt+1 + 续租），保证 exactly-once。
- attempt 超过 max_attempts 不再续跑，标 FAILED（避免毒任务无限重启）。
- 未注册 handler 的 kind 跳过（如 workflow / chat 在本轮仅留接口）。
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from django.db import close_old_connections

from resumable.locks import InstanceLock
from resumable.models import ResumableTask, ResumableTaskStatus
from resumable.service import claim_expired, sweep_expired

logger = structlog.get_logger(__name__)

# kind -> handler(task)；handler 负责按 payload 重建并经 submit_resumable 续跑。
RESUME_HANDLERS: dict[str, Callable[[ResumableTask], None]] = {}


def register_handler(kind: str, fn: Callable[[ResumableTask], None]) -> None:
    RESUME_HANDLERS[kind] = fn


def _mark_exhausted(task: ResumableTask) -> None:
    ResumableTask.objects.filter(
        id=task.id, status=ResumableTaskStatus.RUNNING
    ).update(
        status=ResumableTaskStatus.FAILED,
        lease_owner="",
        lease_expires_at=None,
        last_error="超过最大重试次数，停止自动恢复",
    )


def run_recovery() -> dict[str, int]:
    """执行一轮恢复扫描。返回 {scanned, recovered, exhausted, skipped}。"""
    result = {"scanned": 0, "recovered": 0, "exhausted": 0, "skipped": 0}

    # 集群级互斥（仅 Redis 启用时生效）：避免多 Pod 同时扫描；DB CAS 仍兜底。
    with InstanceLock("resumable:recovery", ttl=60) as lock:
        if not lock.acquired:
            logger.info("resumable_recovery_skipped_locked")
            return result

        close_old_connections()
        candidates = sweep_expired()
        result["scanned"] = len(candidates)

        for task in candidates:
            handler = RESUME_HANDLERS.get(task.kind)
            if handler is None:
                # 无 handler（如 workflow/chat 本轮未接入）：不动，留给各自机制。
                result["skipped"] += 1
                continue

            if (task.attempt or 0) >= (task.max_attempts or 0):
                _mark_exhausted(task)
                result["exhausted"] += 1
                continue

            if not claim_expired(str(task.id)):
                # 已被其他副本领取。
                result["skipped"] += 1
                continue

            try:
                handler(task)
                result["recovered"] += 1
                logger.info(
                    "resumable_task_recovered",
                    kind=task.kind,
                    target_id=task.target_id,
                    attempt=(task.attempt or 0) + 1,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "resumable_task_recover_failed",
                    kind=task.kind,
                    target_id=task.target_id,
                    error=str(exc),
                )

    return result


def recoverable_target_ids(kind: str) -> set[str]:
    """返回某 kind 下仍可被恢复（RUNNING 且 attempt 未超限）的 target_id 集合。

    供既有 startup reconciler（repositories/codegraph）排除——这些目标会由
    RecoveryScheduler 续跑，不应被无脑标 FAILED。
    """
    close_old_connections()
    ids: set[str] = set()
    qs = ResumableTask.objects.filter(
        kind=kind, status=ResumableTaskStatus.RUNNING
    ).values_list("target_id", "attempt", "max_attempts")
    for target_id, attempt, max_attempts in qs:
        if (attempt or 0) < (max_attempts or 0):
            ids.add(str(target_id))
    return ids
