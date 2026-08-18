"""仓库章程 AI 起草的 durable 入队 helper。

summary 成功回写后按 mode=bootstrap|supplement best-effort 入队；失败吞掉、不阻塞回调。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)


async def enqueue_charter_draft(
    repository_id: str,
    *,
    initiated_by_user_id: str | None = None,
    mode: str = "bootstrap",
    fingerprint: str | None = None,
) -> str | None:
    """把章程起草/补充收进 durable 队列（``durable_charter_draft``）。

    - ``mode``: ``bootstrap``（无行首次）或 ``supplement``（有行无 runner charter）。
    - ``fingerprint``: 可选，传给 worker 做门禁持久化。
    - 幂等键含 mode，避免 bootstrap/supplement 互相顶掉。
    - 失败 swallow + ``enqueue_charter_draft_failed``，返回 ``None``，不抛。
    """
    from durable.concurrency import acharacter_lock
    from durable.queues import QUEUE_CHARTER
    from durable.service import DurableTaskService

    started = time.monotonic()
    mode_norm = mode if mode in ("bootstrap", "supplement") else "bootstrap"
    payload: dict[str, Any] = {
        "repository_id": str(repository_id),
        "mode": mode_norm,
    }
    if fingerprint:
        payload["fingerprint"] = str(fingerprint)[:64]

    try:
        lock = await acharacter_lock(str(repository_id))
        job_id = await DurableTaskService.defer(
            "durable_charter_draft",
            payload,
            queue=QUEUE_CHARTER,
            idempotency_key=f"charter:{mode_norm}:{repository_id}",
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
                mode=mode_norm,
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
                mode=mode_norm,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬 summary 回调
            pass
        return None
