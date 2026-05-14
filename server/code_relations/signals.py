"""Phase Plan：ChunkRegistry pre_delete 信号 handler。
ChunkRegistry 行被删除（增量索引重切分 / 文件被删 / 仓库被清理等场景）时：
1. **反查**（per ）：查 `ChunkEdge.target_chunk_id=being_deleted` 拿到所有
 `source_chunk_id`（即"指向 being_deleted 的 chunks"），这些 source chunks 是
 payload 中 `related_chunks` 仍引用孤儿 chunk_id 的"需要重 build 的脏 chunks"。
2. **孤儿边自动清理**（per ）：同步删除 `ChunkEdge.target_chunk_id=being_deleted`
 的所有边（ChunkEdge 没 pre_delete signal，安全；不会触发循环）。
3. **transaction.on_commit 调度增量重 build**（per ）：通过
 `transaction.on_commit(...)` 注册 commit 后回调；transaction 回滚时回调不触发
 —— 避免"dirty enqueue 已触发但实际 chunk 未删"的不一致。
4. **异常隔离**（per ）：handler 内任何异常 catch + structlog warning + 不向上
 传播 —— 用户的 delete 请求应该成功；reconcile 失败由 verify_payload_consistency
 兜底（Plan）。
**为什么是 pre_delete 不是 post_delete**（per ）：post_delete 时 ChunkRegistry
行已删，反查 ChunkEdge.target_chunk_id=deleted_id 与"删 chunk 后还存在的 ChunkEdge"
存在引用一致性盲区；pre_delete 触发时 ChunkRegistry 行还在 DB，反查语义明确。
**为什么 _schedule_reconcile 用 run_in_background 不用 asyncio.run**（per ）：
signal handler 是同步上下文；用 `asyncio.run` 会与现有 event loop 冲突
（CurrentThreadExecutor already quit 类问题）。统一走 `services.background_runner.
run_in_background` 投递到常驻 worker loop —— 与 `IndexTriggerView._schedule_index`
同模式。
"""
from __future__ import annotations
import functools
import uuid
from typing import Any
import structlog
from django.db import transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from code_relations.models import ChunkEdge, ChunkRegistry
from code_relations.tasks import enqueue_edge_build
from services.background_runner import run_in_background
__all__ = ["on_chunk_registry_pre_delete"]
logger = structlog.get_logger(__name__)
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
 向上传播 —— 用户的 ChunkRegistry.delete 应该成功（per ）。
 """
 try:
 chunk_id = instance.chunk_id
 repository_id = str(instance.repository_id)
 source_ids: list[uuid.UUID] = list(
 ChunkEdge.objects.filter(target_chunk_id=chunk_id)
 .values_list("source_chunk_id", flat=True)
 .distinct
 )
 ChunkEdge.objects.filter(target_chunk_id=chunk_id).delete
 if source_ids:
 transaction.on_commit(
 functools.partial(_schedule_reconcile, repository_id, source_ids)
 )
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
 error=str(exc),
 error_type=type(exc).__name__,
 )
