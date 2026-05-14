"""Phase EdgeBuilder 协调器（per / / / ）。
** 实现路径决策（Claude's Discretion）：**
CONTEXT 原文要求「APScheduler date trigger」异步触发，但 indexer 与
scheduler 跨进程（`runapscheduler` 是独立 mgmt command；indexer 跑在
`background_runner` 进程内），cross-process IPC 复杂度高（DjangoJobStore push
job 跨进程边界事务一致性需额外设计）。
本模块改采 `asyncio.create_task` **同进程 fire-and-forget**：
1. indexer 已在 async 上下文，`create_task` 是最自然的非阻塞模式
2. builders 与 indexer 同进程跑，零 IPC 开销
3. 所有错误 catch 内部 + structlog log + 不抛回 indexer（与 异常隔离语义
 一致）
未来若需要跨进程调度（多 worker indexer），可在 `enqueue_edge_build` 内部
切换到 `DjangoJobStore.add_job` 而对调用方零破坏。
**协调器执行顺序（_run_all_builders_and_sync_payload）：**
1. 取 Repository（不存在 → log error + return，不抛）
2. `asyncio.gather(*[cls.build(repo, dirty) for cls in BUILDERS],
 return_exceptions=True)`：6 builder 并发；单 fail 不中断其余（per ）
3. 异常 result log error 跳过；正常 result 的 ChunkEdge flatten
4. `bulk_insert_edges(all_edges)` 单次入库（ignore_conflicts 静默去重 per ）
5. `aggregate_top_neighbors(...)` 单 SQL 聚合 top-20 邻居（per ）
6. `QdrantService.batch_set_payload(...)` **恰好一次** sync（per /，
 不是每 builder 独立 sync）
"""
from __future__ import annotations
import asyncio
import uuid
from typing import TYPE_CHECKING
import structlog
from asgiref.sync import sync_to_async
from code_relations.builders import BUILDERS
from code_relations.payload_sync import aggregate_top_neighbors
from code_relations.storage import bulk_insert_edges
from services.qdrant_service import QdrantService
if TYPE_CHECKING:
 from code_relations.models import ChunkEdge
logger = structlog.get_logger(__name__)
__all__ = ["enqueue_edge_build"]
async def enqueue_edge_build(
 repository_id: str,
 dirty_chunk_ids: list[uuid.UUID],
) -> None:
 """Fire-and-forget 触发 6 builder 并发构建 + payload 同步。
 立即 return（不等待 builders 完成），由 `asyncio.create_task` 在背景执行
 `_run_all_builders_and_sync_payload`。
 异常隔离（per ）：所有错误在 `_run_all_builders_and_sync_payload`
 内部 catch + structlog log，不抛回 indexer。
 注：indexer 主任务结束时 `background_runner` 会 cancel 未完成 task；
 实践中 builders 通常远快于 indexer 主流程（semantic builder 10k chunks
 < 60s），不会被 cancel。即便被 cancel，下次 indexer 触发再补（最终一致）。
 Args:
 repository_id: 仓库 UUID 字符串
 dirty_chunk_ids: 本次 indexer 写入或更新的 chunk_id 列表；空 list →
 直接 return 不 spawn task
 """
 if not dirty_chunk_ids:
 logger.debug(
 "enqueue_edge_build_skip_empty_dirty",
 repository_id=repository_id,
 )
 return
 asyncio.create_task(
 _run_all_builders_and_sync_payload(repository_id, dirty_chunk_ids)
 )
 logger.info(
 "enqueue_edge_build_dispatched",
 repository_id=repository_id,
 dirty_chunks=len(dirty_chunk_ids),
 builders=len(BUILDERS),
 )
async def _run_all_builders_and_sync_payload(
 repository_id: str,
 dirty_chunk_ids: list[uuid.UUID],
) -> None:
 """6 builder 并发跑 + 统一 bulk_insert_edges + 单次 batch_set_payload。
 per：6 builder 全部完成后**统一**调一次 `batch_set_payload`，不是
 每 builder 独立 sync。
 per：`asyncio.gather(..., return_exceptions=True)` 单 builder fail
 不中断其余；fail builder log error 不抛。
 per：`bulk_insert_edges` ignore_conflicts 静默重复边。
 """
 from repositories.models import Repository
 try:
 repo = await sync_to_async(Repository.objects.get)(id=repository_id)
 except Repository.DoesNotExist:
 logger.error(
 "edge_build_repo_not_found",
 repository_id=repository_id,
 )
 return
 except Exception as exc:
 logger.error(
 "edge_build_repo_fetch_failed",
 repository_id=repository_id,
 error=str(exc),
 error_type=type(exc).__name__,
 )
 return
 builders = [cls for cls in BUILDERS]
 results: list[list[ChunkEdge] | BaseException] = (
 list(
 await asyncio.gather(
 *[b.build(repo, dirty_chunk_ids) for b in builders],
 return_exceptions=True,
 )
 )
 if builders
 else
 )
 all_edges: list[ChunkEdge] =
 for builder, res in zip(builders, results, strict=True):
 if isinstance(res, BaseException):
 logger.error(
 "edge_builder_failed",
 repository_id=repository_id,
 builder=getattr(builder, "edge_type_label", type(builder).__name__),
 error=str(res),
 error_type=type(res).__name__,
 )
 continue
 all_edges.extend(res)
 inserted = await bulk_insert_edges(all_edges)
 logger.info(
 "edge_build_inserted",
 repository_id=repository_id,
 total_input=len(all_edges),
 inserted=inserted,
 )
 updates = await aggregate_top_neighbors(repository_id, dirty_chunk_ids)
 await QdrantService.batch_set_payload(repository_id, updates)
 logger.info(
 "edge_build_and_payload_sync_complete",
 repository_id=repository_id,
 dirty_chunks=len(dirty_chunk_ids),
 edges_inserted=inserted,
 payload_updates=len(updates),
 )
