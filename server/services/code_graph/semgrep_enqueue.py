"""Semgrep 扫描 durable 入队 helper（Phase 127 / TAINT-01 / D-02 / D-04）。

建 MR 路径 best-effort 入队 ``durable_semgrep_scan``；失败吞掉、返回 ``None``，不阻断。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = ["enqueue_semgrep_scan", "enqueue_semgrep_scan_for_branches"]


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


async def enqueue_semgrep_scan_for_branches(
    repository_id: str,
    *,
    mr_key: str,
    source_branch: str,
    target_branch: str,
    client: Any = None,
    source_sha: str = "",
    target_sha: str = "",
    initiated_by_user_id: str | None = None,
) -> str | None:
    """建 MR 挂点入口：先解析两端真实 sha，再决定入队还是跳过（D-04）。

    ``run_semgrep_scan`` 对空 ``source_sha`` / ``target_sha`` 只会 fail-open 返回
    ``unavailable``，所以两端必须都解析到才入队；否则记
    ``enqueue_semgrep_scan_skipped_missing_sha`` 并返回 ``None``，把 MR 描述里的
    pending stub 原样留着（人工可读＞永久 unavailable 假结论）。

    Returns:
        job id；跳过 / 入队失败 → ``None``（永不 raise，不阻断建 MR）。
    """
    from services.code_graph.semgrep_sha import resolve_scan_shas

    repo_id = str(repository_id or "")
    key = mr_key or ""
    try:
        resolved_source, resolved_target = await resolve_scan_shas(
            repository_id=repo_id,
            source_branch=source_branch or "",
            target_branch=target_branch or "",
            client=client,
            source_sha=source_sha or "",
            target_sha=target_sha or "",
        )
    except Exception:  # noqa: BLE001 — 解析异常等价于"解析不到"
        resolved_source, resolved_target = "", ""

    if not resolved_source or not resolved_target:
        try:
            logger.warning(
                "enqueue_semgrep_scan_skipped_missing_sha",
                category="caller",
                component="code_graph",
                repository_id=repo_id,
                mr_key=key,
                initiated_by_user_id=initiated_by_user_id or "system",
                source_branch=source_branch or "",
                target_branch=target_branch or "",
                source_sha_resolved=bool(resolved_source),
                target_sha_resolved=bool(resolved_target),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬建 MR
            pass
        return None

    return await enqueue_semgrep_scan(
        repo_id,
        mr_key=key,
        source_sha=resolved_source,
        target_sha=resolved_target,
        branch_name=source_branch or "",
        initiated_by_user_id=initiated_by_user_id,
    )
