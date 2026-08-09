"""建仓/触发路径的代码索引 durable 入队 helper。

镜像 ``enqueue_repo_summary``：best-effort、幂等、槽位锁；入队失败不抛、不阻塞建仓。
图谱仍由 indexer 内 ``auto_after_index`` 条件触发，**禁止**在此入队 ``durable_graph``。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from common.logging import redact_secrets_in_text
from repositories.models import (
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    TriggerType,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _IndexClaim:
    """行锁内原子认领结果。"""

    previous_status: str
    history: IndexHistory


def _claim_index_enqueue_sync(repository_id: str) -> _IndexClaim | str:
    """在事务 + ``select_for_update`` 下检查状态、置 INDEXING、创建 RUNNING history。

    Returns:
        ``_IndexClaim`` 表示认领成功；字符串 ``"not_found"`` / ``"already_indexing"`` 表示跳过。
    """
    with transaction.atomic():
        try:
            repo = Repository.objects.select_for_update().get(
                id=repository_id, is_deleted=False
            )
        except Repository.DoesNotExist:
            return "not_found"

        if repo.index_status == IndexStatus.INDEXING:
            return "already_indexing"

        previous_status = repo.index_status
        # 对齐 IndexTriggerView / reindex-all：清空进度残留，避免 UI 误读旧 N/N。
        Repository.objects.filter(id=repository_id).update(
            index_status=IndexStatus.INDEXING,
            index_error=None,
            index_total_chunks=0,
            index_processed_chunks=0,
            index_write_total=0,
            index_write_processed=0,
            current_indexing_file="",
            indexed_files_processed=0,
            indexed_files_total=0,
        )
        history = IndexHistory.objects.create(
            repository_id=repository_id,
            trigger_type=TriggerType.MANUAL,
            status=IndexHistoryStatus.RUNNING,
            started_at=timezone.now(),
        )
        return _IndexClaim(previous_status=previous_status, history=history)


_claim_index_enqueue = sync_to_async(_claim_index_enqueue_sync, thread_sensitive=True)


async def enqueue_repo_index(
    repository_id: str,
    *,
    initiated_by_user_id: str | None = None,
    trigger: str = "create",
) -> str | None:
    """把 full index 收进 durable 队列（``durable_index``）。

    - 仓库不存在 / 已 ``INDEXING`` → 跳过，返回 ``None``。
    - 成功：事务行锁内创建 ``IndexHistory`` RUNNING + 置 ``index_status=INDEXING``，
      再 ``defer("durable_index", ...)``（defer 在锁外，避免持锁做 IO），幂等键 ``index:{repo_id}``。
    - defer 失败：best-effort 回滚（history→FAILED、repo 恢复先前状态），返回 ``None``，不抛。
    - 整段异常吞掉并打 ``enqueue_repo_index_failed``（category=caller）。

    Returns:
        durable job id；跳过/失败返回 ``None``。
    """
    started = time.monotonic()
    history: IndexHistory | None = None
    previous_status: str | None = None
    try:
        claim = await _claim_index_enqueue(str(repository_id))
        if isinstance(claim, str):
            logger.info(
                "enqueue_repo_index_skipped",
                category="sampling",
                component="repositories",
                repository_id=str(repository_id),
                reason=claim,
                initiated_by_user_id=initiated_by_user_id or "system",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None

        previous_status = claim.previous_status
        history = claim.history

        from durable import QUEUE_INDEX, DurableTaskService
        from durable.concurrency import aindex_lock

        job_id = await DurableTaskService.defer(
            "durable_index",
            {
                "repository_id": str(repository_id),
                "history_id": str(history.id),
                "branch": None,
                "trigger": trigger,
            },
            queue=QUEUE_INDEX,
            idempotency_key=f"index:{repository_id}",
            lock=await aindex_lock(str(repository_id)),
            initiated_by_user_id=initiated_by_user_id,
        )
        try:
            logger.info(
                "enqueue_repo_index_completed",
                category="caller",
                component="repositories",
                repository_id=str(repository_id),
                history_id=str(history.id),
                job_id=job_id,
                trigger=trigger,
                initiated_by_user_id=initiated_by_user_id or "system",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬已成功入队的业务
            pass
        return job_id
    except Exception as exc:  # noqa: BLE001 — 入队失败不阻塞建仓
        await _rollback_index_enqueue(
            repository_id=str(repository_id),
            history=history,
            previous_status=previous_status,
            error=exc,
        )
        try:
            logger.warning(
                "enqueue_repo_index_failed",
                category="caller",
                component="repositories",
                repository_id=str(repository_id),
                initiated_by_user_id=initiated_by_user_id or "system",
                error=redact_secrets_in_text(str(exc)),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬建仓
            pass
        return None


async def _rollback_index_enqueue(
    *,
    repository_id: str,
    history: IndexHistory | None,
    previous_status: str | None,
    error: BaseException,
) -> None:
    """defer 失败时不得留下 INDEXING / RUNNING history（对齐 reindex-all 失败隔离）。"""
    safe_err = redact_secrets_in_text(str(error))[:1000]
    try:
        if history is not None:
            await IndexHistory.objects.filter(id=history.id).aupdate(
                status=IndexHistoryStatus.FAILED,
                error_message=safe_err,
            )
    except Exception:  # noqa: BLE001 — 回滚 best-effort
        pass
    try:
        restore = previous_status if previous_status is not None else IndexStatus.NOT_INDEXED
        # 若先前已是 INDEXING（竞态），勿回写 INDEXING；标 FAILED 可见失败。
        if restore == IndexStatus.INDEXING:
            restore = IndexStatus.FAILED
        await Repository.objects.filter(id=repository_id).aupdate(
            index_status=restore,
            index_error=safe_err or None,
        )
    except Exception:  # noqa: BLE001 — 回滚 best-effort
        pass
