"""ChunkRegistry pre_delete 信号 handler。

ChunkRegistry 行被删除（增量索引重切分 / 文件被删 / 仓库被清理等场景）时：

1. **反查**（per contract）：查 `ChunkEdge.target_chunk_id=being_deleted` 拿到所有
   `source_chunk_id`（即"指向 being_deleted 的 chunks"），这些 source chunks 是
   payload 中 `related_chunks` 仍引用孤儿 chunk_id 的"需要重 build 的脏 chunks"。
2. **孤儿边自动清理**（per contract）：同步删除 `ChunkEdge.target_chunk_id=being_deleted`
   的所有边（ChunkEdge 没 pre_delete signal，安全；不会触发循环）。
3. **transaction.on_commit 调度增量重 build**（per contract）：通过
   `transaction.on_commit(...)` 注册 commit 后回调；transaction 回滚时回调不触发
   —— 避免"dirty enqueue 已触发但实际 chunk 未删"的不一致。
4. **异常隔离**（per contract）：handler 内任何异常 catch + structlog warning + 不向上
   传播 —— 用户的 delete 请求应该成功；reconcile 失败由 verify_payload_consistency
   兜底（plan）。

**为什么是 pre_delete 不是 post_delete**（per contract）：post_delete 时 ChunkRegistry
行已删，反查 ChunkEdge.target_chunk_id=deleted_id 与"删 chunk 后还存在的 ChunkEdge"
存在引用一致性盲区；pre_delete 触发时 ChunkRegistry 行还在 DB，反查语义明确。

**为什么 _schedule_reconcile 用 run_in_background 不用 asyncio.run**（per contract）：
signal handler 是同步上下文；用 `asyncio.run` 会与现有 event loop 冲突
（CurrentThreadExecutor already quit 类问题）。统一走 `services.background_runner.
run_in_background` 投递到常驻 worker loop。（注：index 入队已于 Phase 61 迁移到
`DurableTaskService.defer`，`IndexTriggerView._schedule_index` 不再是 run_in_background
范式；本处 edge reconcile 仍走 run_in_background 常驻 worker loop。）
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import structlog
from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from code_relations.models import ChunkEdge, ChunkRegistry
from code_relations.tasks import enqueue_edge_build
from services.background_runner import run_in_background

# `__all__` 仅声明 module 级显式 public 接口；handler 由 @receiver 副作用注册，
# `apps.py::ready()` 仅 `import` 模块即生效，无消费方需要直接调用。保留空 list
# 是显式说明"本模块无 public 导出"，避免 `__all__ = ["on_chunk_registry_pre_delete"]`
# 给读者"这是 public API"的误导（per work item）。
__all__: list[str] = []

logger = structlog.get_logger(__name__)


# 事务局部累积器（per work item / context contract）：批量删 N 个 ChunkRegistry 行时，
# 每条 pre_delete 不再单独 schedule reconcile —— 累积到 thread-local dict，commit
# 时一次性 flush 调一次 `_schedule_reconcile(repo_id, dirty_set)`，避免 N 个并发
# `enqueue_edge_build` task 把 builders / payload_sync 重复跑 N 遍。
#
# 设计决策（rollback 边界）：每次 `_accumulate_dirty` 都 `transaction.on_commit`
# 注册 flush；多次注册的 flush 是 idempotent —— 首个 flush 走 snapshot + clear，
# 后续 flush 看到空 dict 直接 no-op。rollback 时所有 on_commit 被丢弃 →
# `_schedule_reconcile` 不会被调（满足 `test_reconcile_not_triggered_on_rollback`
# 契约）；遗留的 thread-local 数据会被下一次 commit 顺带 flush（产生少量无害的
# 多余 reconcile，但不会数据损坏）。
_local = threading.local()


def _get_pending() -> dict[str, set[uuid.UUID]]:
    """thread-local pending dict： `{repository_id: {source_chunk_id, ...}}`。"""
    pending = getattr(_local, "pending", None)
    if pending is None:
        pending = {}
        _local.pending = pending
    return pending


def _flush_pending() -> None:
    """on_commit 回调：snapshot + clear pending → 调一次 `_schedule_reconcile`。

    多次注册的 flush 都指向本函数；首次 flush 拿走全部 pending 数据并清空，
    后续 flush 看到空 dict 直接 no-op。
    """
    pending = _get_pending()
    snapshot = {repo_id: sorted(sources) for repo_id, sources in pending.items()}
    pending.clear()
    for repo_id, source_ids in snapshot.items():
        _schedule_reconcile(repo_id, source_ids)


def _accumulate_dirty(repository_id: str, source_ids: list[uuid.UUID]) -> None:
    """累积 dirty source_chunk_ids 到 thread-local，注册 commit 后批量 flush。"""
    pending = _get_pending()
    pending.setdefault(repository_id, set()).update(source_ids)
    transaction.on_commit(_flush_pending)


def _schedule_reconcile(repository_id: str, source_ids: list[uuid.UUID]) -> None:
    """transaction commit 后通过 background_runner 投递 enqueue_edge_build。

    必须传 factory 而不是 coroutine（per `run_in_background` docstring）：
    coroutine 只能在创建它的 event loop 里 await，跨线程提交需要 worker loop
    在自己上下文里 call factory 新鲜创建 coroutine 对象。

    异常隔离：内部 try/except 兜底 —— `run_in_background` 启动失败不应回流到
    transaction commit 链路（commit 已经发生；reconcile 失败仅 log warning，
    后续 verify_payload_consistency 兜底）。
    """
    try:
        run_in_background(
            lambda: enqueue_edge_build(repository_id, source_ids),
            name=f"chunkregistry-reconcile-{repository_id}",
        )
        logger.info(
            "chunk_registry_reconcile_scheduled",
            repository_id=repository_id,
            dirty_sources=len(source_ids),
        )
    except Exception as exc:
        logger.warning(
            "chunk_registry_reconcile_schedule_failed",
            repository_id=repository_id,
            dirty_sources=len(source_ids),
            error=str(exc),
            error_type=type(exc).__name__,
        )


@receiver(pre_delete, sender=ChunkRegistry)
def on_chunk_registry_pre_delete(
    sender: type[ChunkRegistry],
    instance: ChunkRegistry,
    **kwargs: Any,
) -> None:
    """ChunkRegistry.pre_delete 信号 handler。

    顶层 try/except 包住全部逻辑：handler 内任何错误 catch + log warning + 不
    向上传播 —— 用户的 ChunkRegistry.delete() 应该成功（per contract）。
    """
    try:
        if instance.repository_id is None:
            return

        chunk_id = instance.chunk_id
        repository_id = str(instance.repository_id)

        source_ids: list[uuid.UUID] = list(
            ChunkEdge.objects.filter(target_chunk_id=chunk_id)
            .values_list("source_chunk_id", flat=True)
            .distinct()
        )

        ChunkEdge.objects.filter(target_chunk_id=chunk_id).delete()

        if source_ids:
            _accumulate_dirty(repository_id, source_ids)
            logger.debug(
                "chunk_registry_pre_delete_reconcile_queued",
                repository_id=repository_id,
                chunk_id=str(chunk_id),
                dirty_sources=len(source_ids),
            )
        else:
            logger.debug(
                "chunk_registry_pre_delete_no_inbound_edges",
                repository_id=repository_id,
                chunk_id=str(chunk_id),
            )
    except Exception as exc:
        logger.warning(
            "chunk_registry_pre_delete_handler_failed",
            chunk_id=str(getattr(instance, "chunk_id", "")),
            repository_id=str(getattr(instance, "repository_id", "")),
            error=str(exc),
            error_type=type(exc).__name__,
        )
