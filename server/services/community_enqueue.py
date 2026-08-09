"""社区重建 durable 入队 helper（Phase 125 / MOD-01 / D-03）。

边/图构建完成后 best-effort 入队 ``durable_community_rebuild``；失败吞掉、不阻塞钩子。
"""

from __future__ import annotations

import time

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)


async def enqueue_community_rebuild(
    repository_id: str,
    *,
    branch_name: str = "",
    initiated_by_user_id: str | None = None,
) -> str | None:
    """把社区重建收进 durable ``QUEUE_GRAPH``（``durable_community_rebuild``）。

    - 幂等键 / queueing_lock ``community:{repository_id}:{branch}``。
    - 失败 swallow + ``enqueue_community_rebuild_failed``，返回 ``None``，不抛。
    """
    from durable.queues import QUEUE_GRAPH
    from durable.service import DurableTaskService

    started = time.monotonic()
    branch = branch_name or ""
    try:
        job_id = await DurableTaskService.defer(
            "durable_community_rebuild",
            {
                "repository_id": str(repository_id),
                "branch_name": branch,
            },
            queue=QUEUE_GRAPH,
            idempotency_key=f"community:{repository_id}:{branch}",
            initiated_by_user_id=initiated_by_user_id,
        )
        try:
            logger.info(
                "enqueue_community_rebuild_completed",
                category="caller",
                component="code_graph",
                repository_id=str(repository_id),
                branch_name=branch,
                initiated_by_user_id=initiated_by_user_id or "system",
                job_id=job_id,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬已成功入队的业务
            pass
        return job_id
    except Exception as exc:  # noqa: BLE001 — 入队失败不阻塞图/边钩子
        try:
            logger.warning(
                "enqueue_community_rebuild_failed",
                category="caller",
                component="code_graph",
                repository_id=str(repository_id),
                branch_name=branch,
                initiated_by_user_id=initiated_by_user_id or "system",
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬钩子
            pass
        return None
