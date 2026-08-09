"""Semgrep 扫描 durable 入队 helper（Phase 127 / TAINT-01 / D-02 / D-04）。

建 MR 路径 best-effort 入队 ``durable_semgrep_scan``；失败吞掉、返回 ``None``，不阻断。
"""

from __future__ import annotations

import time

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["enqueue_semgrep_scan"]


async def enqueue_semgrep_scan(
    repository_id: str,
    *,
    mr_key: str,
    source_sha: str,
    target_sha: str,
    branch_name: str = "",
    initiated_by_user_id: str | None = None,
) -> str | None:
    """把 diff-aware Semgrep 扫描收进 ``QUEUE_SCAN``（``durable_semgrep_scan``）。

    - 幂等键 ``semgrep:{repository_id}:{mr_key}``
    - 槽位锁 ``scan-slot-*``（N=``CONCURRENCY_SCAN_MAX`` 默认 2）
    - 失败 swallow + ``enqueue_semgrep_scan_failed``，返回 ``None``，不抛
    """
    from durable.concurrency import ascan_lock
    from durable.queues import QUEUE_SCAN
    from durable.service import DurableTaskService

    started = time.monotonic()
    repo_id = str(repository_id)
    key = mr_key or ""
    try:
        lock = await ascan_lock(repo_id)
        job_id = await DurableTaskService.defer(
            "durable_semgrep_scan",
            {
                "repository_id": repo_id,
                "mr_key": key,
                "source_sha": source_sha or "",
                "target_sha": target_sha or "",
                "branch_name": branch_name or "",
                "initiated_by_user_id": initiated_by_user_id,
            },
            queue=QUEUE_SCAN,
            idempotency_key=f"semgrep:{repo_id}:{key}",
            lock=lock,
            initiated_by_user_id=initiated_by_user_id,
        )
        try:
            logger.info(
                "enqueue_semgrep_scan_completed",
                category="caller",
                component="code_graph",
                repository_id=repo_id,
                mr_key=key,
                initiated_by_user_id=initiated_by_user_id or "system",
                job_id=job_id,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬已成功入队
            pass
        return job_id
    except Exception as exc:  # noqa: BLE001 — 入队失败不阻塞建 MR
        try:
            logger.warning(
                "enqueue_semgrep_scan_failed",
                category="caller",
                component="code_graph",
                repository_id=repo_id,
                mr_key=key,
                initiated_by_user_id=initiated_by_user_id or "system",
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬建 MR
            pass
        return None
