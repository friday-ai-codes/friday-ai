"""仓库章程 AI 起草的 durable 入队 helper。

summary 成功回写后 best-effort 入队 ``durable_charter_draft``；失败吞掉、不阻塞回调。
"""

from __future__ import annotations

import time

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)


async def enqueue_charter_draft(
    repository_id: str,
    *,
    initiated_by_user_id: str | None = None,
) -> str | None:
    """把章程起草收进 durable 队列（``durable_charter_draft``）。

    - 幂等键 ``charter:{repository_id}``，槽位锁 ``charter-slot-*``。
    - 失败 swallow + ``enqueue_charter_draft_failed``，返回 ``None``，不抛。
    """
    from durable.concurrency import acharacter_lock
    from durable.queues import QUEUE_CHARTER
    from durable.service import DurableTaskService

    started = time.monotonic()
    try:
        lock = await acharacter_lock(str(repository_id))
        job_id = await DurableTaskService.defer(
            "durable_charter_draft",
            {"repository_id": str(repository_id)},
            queue=QUEUE_CHARTER,
            idempotency_key=f"charter:{repository_id}",
            lock=lock,
            initiated_by_user_id=initiated_by_user_id,
        )
        try:
            logger.info(
                "enqueue_charter_draft_completed",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id or "system",
                job_id=job_id,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬已成功入队的业务
            pass
        return job_id
    except Exception as exc:  # noqa: BLE001 — 入队失败不阻塞 summary 回调
        try:
            logger.warning(
                "enqueue_charter_draft_failed",
                category="caller",
                component="charter_service",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id or "system",
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬 summary 回调
            pass
        return None
