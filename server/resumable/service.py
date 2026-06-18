"""可恢复任务核心服务：登记、租约、心跳、领取、统一提交入口。

DB 是真相源。所有 ORM 操作提供同步实现 + ``sync_to_async`` 异步包装，
异步包装统一在 ``services.background_runner`` 的常驻 worker loop 上调用，
避免绑死 ASGI 请求生命周期（与索引/图谱既有调度同模式）。
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from resumable.models import ResumableTask, ResumableTaskStatus
from services.background_runner import run_in_background

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# 进程实例标识：hostname + pid + 随机后缀。重启后 pid/后缀变化，
# 老进程持有的租约对新进程而言必然"非自己持有"，过期后即可被领取续跑。
INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def lease_ttl_seconds() -> int:
    return int(getattr(settings, "RESUMABLE_LEASE_TTL_SECONDS", 90))


def heartbeat_interval_seconds() -> int:
    return int(getattr(settings, "RESUMABLE_HEARTBEAT_INTERVAL_SECONDS", 30))


# ---------------------------------------------------------------------------
# 同步 DB 操作（真相源读写）
# ---------------------------------------------------------------------------


def register_running(
    *,
    kind: str,
    target_id: str,
    payload: dict[str, Any],
    name: str,
    bump_attempt: bool = False,
) -> ResumableTask:
    """登记 / 刷新一个 RUNNING 任务行并占用租约（update_or_create）。

    ``bump_attempt=True`` 时 attempt+1（恢复续跑路径调用），否则保留原值。
    """
    now = timezone.now()
    expires = now + datetime.timedelta(seconds=lease_ttl_seconds())
    task, created = ResumableTask.objects.get_or_create(
        kind=kind,
        target_id=str(target_id),
        defaults={
            "status": ResumableTaskStatus.RUNNING,
            "payload": payload,
            "name": name,
            "lease_owner": INSTANCE_ID,
            "lease_expires_at": expires,
            "heartbeat_at": now,
            "attempt": 1,
        },
    )
    if not created:
        task.status = ResumableTaskStatus.RUNNING
        task.payload = payload
        task.name = name
        task.lease_owner = INSTANCE_ID
        task.lease_expires_at = expires
        task.heartbeat_at = now
        task.last_error = ""
        if bump_attempt:
            task.attempt = (task.attempt or 0) + 1
        task.save(
            update_fields=[
                "status",
                "payload",
                "name",
                "lease_owner",
                "lease_expires_at",
                "heartbeat_at",
                "last_error",
                "attempt",
                "updated_at",
            ]
        )
    return task


def heartbeat(*, kind: str, target_id: str) -> bool:
    """刷新租约 + 心跳；仅当本实例仍持有且任务仍 RUNNING 时生效。"""
    now = timezone.now()
    expires = now + datetime.timedelta(seconds=lease_ttl_seconds())
    updated = ResumableTask.objects.filter(
        kind=kind,
        target_id=str(target_id),
        lease_owner=INSTANCE_ID,
        status=ResumableTaskStatus.RUNNING,
    ).update(lease_expires_at=expires, heartbeat_at=now)
    return updated == 1


def mark_completed(*, kind: str, target_id: str) -> None:
    ResumableTask.objects.filter(kind=kind, target_id=str(target_id)).update(
        status=ResumableTaskStatus.COMPLETED,
        lease_owner="",
        lease_expires_at=None,
    )


def mark_failed(*, kind: str, target_id: str, error: str) -> None:
    ResumableTask.objects.filter(kind=kind, target_id=str(target_id)).update(
        status=ResumableTaskStatus.FAILED,
        lease_owner="",
        lease_expires_at=None,
        last_error=(error or "")[:4000],
    )


def mark_cancelled(*, kind: str, target_id: str) -> None:
    ResumableTask.objects.filter(kind=kind, target_id=str(target_id)).update(
        status=ResumableTaskStatus.CANCELLED,
        lease_owner="",
        lease_expires_at=None,
    )


def claim_expired(task_id: str) -> bool:
    """原子领取一个租约过期的 RUNNING 任务（DB CAS，多副本 exactly-once）。

    返回 True 表示本实例成功领取（attempt+1 + 续租），False 表示已被他人领取
    或状态/租约已变更。
    """
    from django.db.models import F

    now = timezone.now()
    expires = now + datetime.timedelta(seconds=lease_ttl_seconds())
    updated = ResumableTask.objects.filter(
        id=task_id,
        status=ResumableTaskStatus.RUNNING,
        lease_expires_at__lt=now,
    ).update(
        lease_owner=INSTANCE_ID,
        lease_expires_at=expires,
        heartbeat_at=now,
        attempt=F("attempt") + 1,
    )
    return updated == 1


# ---------------------------------------------------------------------------
# 异步包装
# ---------------------------------------------------------------------------

aregister_running = sync_to_async(register_running, thread_sensitive=True)
aheartbeat = sync_to_async(heartbeat, thread_sensitive=True)
amark_completed = sync_to_async(mark_completed, thread_sensitive=True)
amark_failed = sync_to_async(mark_failed, thread_sensitive=True)
amark_cancelled = sync_to_async(mark_cancelled, thread_sensitive=True)


# ---------------------------------------------------------------------------
# 统一提交入口
# ---------------------------------------------------------------------------


async def _heartbeat_loop(kind: str, target_id: str) -> None:
    interval = heartbeat_interval_seconds()
    while True:
        await asyncio.sleep(interval)
        try:
            await aheartbeat(kind=kind, target_id=target_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resumable_heartbeat_failed",
                kind=kind,
                target_id=str(target_id),
                error=str(exc),
            )


def wrap_resumable(
    *,
    kind: str,
    target_id: str,
    payload: dict[str, Any],
    name: str,
    coro_factory: Callable[[], Awaitable[T]],
    bump_attempt: bool = False,
) -> Callable[[], Awaitable[T]]:
    """把一个 coro_factory 包成"可恢复任务"工厂：登记 + 心跳 + 终态收尾。

    返回的工厂仍是无参 callable（适配 ``run_in_background``）。登记 / 心跳 /
    终态全部在 worker loop 内通过异步 ORM 完成，调用方（可能在 async 视图里）
    无需触碰 ORM，避免 ``SynchronousOnlyOperation``。

    设计为返回工厂而非直接调度，是为了让各调用方仍用自己模块级的
    ``run_in_background``（保持既有可观测性 / 测试 patch 点不变）。
    """

    async def _wrapped() -> T:
        # 登记是 best-effort：DB 瞬时不可用不应阻断真实业务（断点恢复退化为
        # 由既有 reconciler 兜底），故 suppress 后继续执行。
        try:
            await aregister_running(
                kind=kind,
                target_id=str(target_id),
                payload=payload,
                name=name,
                bump_attempt=bump_attempt,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resumable_register_failed",
                kind=kind,
                target_id=str(target_id),
                error=str(exc),
            )
        hb_task = asyncio.create_task(_heartbeat_loop(kind, str(target_id)))
        try:
            result = await coro_factory()
        except asyncio.CancelledError:
            # 取消 = 用户显式停止（cancel_background_task），标 CANCELLED 不再续跑。
            with contextlib.suppress(Exception):
                await amark_cancelled(kind=kind, target_id=str(target_id))
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                await amark_failed(kind=kind, target_id=str(target_id), error=str(exc))
            raise
        else:
            with contextlib.suppress(Exception):
                await amark_completed(kind=kind, target_id=str(target_id))
            return result
        finally:
            hb_task.cancel()
            with contextlib.suppress(BaseException):
                await hb_task

    return _wrapped


def submit_resumable(
    *,
    kind: str,
    target_id: str,
    payload: dict[str, Any],
    name: str,
    coro_factory: Callable[[], Awaitable[T]],
    bump_attempt: bool = False,
) -> Any:
    """登记可恢复任务并经 background_runner 执行（``wrap_resumable`` + 调度）。

    与 ``run_in_background`` 同样返回 ``concurrent.futures.Future``。
    """
    wrapped = wrap_resumable(
        kind=kind,
        target_id=target_id,
        payload=payload,
        name=name,
        coro_factory=coro_factory,
        bump_attempt=bump_attempt,
    )
    return run_in_background(wrapped, name=name)


def sweep_expired(now: datetime.datetime | None = None) -> list[ResumableTask]:
    """返回当前所有租约过期的 RUNNING 任务（未领取）。供 RecoveryScheduler 使用。"""
    close_old_connections()
    now = now or timezone.now()
    return list(
        ResumableTask.objects.filter(
            status=ResumableTaskStatus.RUNNING,
            lease_expires_at__lt=now,
        )
    )
