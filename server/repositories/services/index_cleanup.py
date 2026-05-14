"""一站式删除仓库索引衍生物 — Phase Plan / .
`IndexDeleteView` 历史上把"删 Qdrant collection / 删 FileIndex / 删 codegraph
三件套（Symbol / ImportEdge / Endpoint）"散落写在 view 函数体里，而 Phase 落
地 ``ChunkRegistry`` / ``ChunkEdge`` 后又多出两类需要级联清理的子表。继续把这些
delete 逻辑塞 view 会让 view 越来越胖，且无法被运维脚本（比如未来的 backfill /
verify_payload_consistency --reset 子命令）复用。
本模块把级联清理收敛到 ``cleanup_index(repository_id)``，返回结构化
``CleanupReport``（7 字段 — 6 个 ``*_deleted: int`` + 1 个 ``qdrant_collection_deleted: bool``），
便于：
1. 单测直接 assert 每类对象的删除计数 → 防止"忘删某子表"静默漂移。
2. 调用方（view / 脚本）以结构化数据写日志或返回给前端。
**关键不变量**：
- ``ChunkEdge`` 必须在 ``ChunkRegistry`` 之前删除（per CONTEXT ）：当下
 ``ChunkEdge.source_chunk_id / target_chunk_id`` 是 UUID 字段非 DB FK（per
 ``code_relations.models.ChunkEdge`` 注释 ），但保此序方便日后改 FK 时
 零破坏。
- 每步独立 ``try/except`` + ``log.warning`` + report 字段降级（per CONTEXT ）；
 单步失败不向上传播给用户的 DELETE 请求。Qdrant 网络异常 / ORM 死锁都不应
 阻塞"删干净本地状态"。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID
import structlog
from asgiref.sync import sync_to_async
from code_relations.models import ChunkEdge, ChunkRegistry
from codegraph.models import Endpoint, ImportEdge, Symbol
from repositories.models import FileIndex
from services.qdrant_service import QdrantService
logger = structlog.get_logger(__name__)
__all__ = ["CleanupReport", "cleanup_index"]
@dataclass(frozen=True)
class CleanupReport:
 """一仓索引清理结果。
 字段语义：
 - ``qdrant_collection_deleted``：Qdrant collection 删除是否成功（异常或返回
 False 都记 False；下游可据此决定是否需要人工介入排查）。
 - ``file_indexes_deleted`` / ``symbols_deleted`` / ``import_edges_deleted`` /
 ``endpoints_deleted`` / ``chunk_edges_deleted`` / ``chunk_registries_deleted``：
 各 Django ORM 表 ``adelete`` 返回的 (count, _) 元组中 count 部分。
 """
 qdrant_collection_deleted: bool
 file_indexes_deleted: int
 symbols_deleted: int
 import_edges_deleted: int
 endpoints_deleted: int
 chunk_edges_deleted: int
 chunk_registries_deleted: int
async def cleanup_index(repository_id: str | UUID) -> CleanupReport:
 """级联清理一个仓库的全部索引衍生物 + Qdrant collection。
 返回:class:`CleanupReport`；任何单步异常都会被吞掉并降级到对应字段（计数 0
 或 ``qdrant_collection_deleted=False``），永远不向上抛出 — view 可以放心
 返回 204（per CONTEXT ）。
 """
 repo_id = str(repository_id)
 logger.info("index_cleanup_start", repository_id=repo_id)
 qdrant_collection_deleted = await _delete_qdrant_collection(repo_id)
 file_indexes_deleted = await _delete_count(
 FileIndex, repo_id, label="file_indexes"
 )
 import_edges_deleted = await _delete_count(
 ImportEdge, repo_id, label="import_edges"
 )
 endpoints_deleted = await _delete_count(
 Endpoint, repo_id, label="endpoints"
 )
 symbols_deleted = await _delete_count(Symbol, repo_id, label="symbols")
 # ChunkEdge 必须先于 ChunkRegistry — 当前两表无 DB FK，仅语义顺序
 chunk_edges_deleted = await _delete_count(
 ChunkEdge, repo_id, label="chunk_edges"
 )
 chunk_registries_deleted = await _delete_count(
 ChunkRegistry, repo_id, label="chunk_registries"
 )
 report = CleanupReport(
 qdrant_collection_deleted=qdrant_collection_deleted,
 file_indexes_deleted=file_indexes_deleted,
 symbols_deleted=symbols_deleted,
 import_edges_deleted=import_edges_deleted,
 endpoints_deleted=endpoints_deleted,
 chunk_edges_deleted=chunk_edges_deleted,
 chunk_registries_deleted=chunk_registries_deleted,
 )
 logger.info(
 "index_cleanup_complete", repository_id=repo_id, report=asdict(report)
 )
 return report
async def _delete_qdrant_collection(repo_id: str) -> bool:
 """sync_to_async 包 Qdrant SDK 同步 API；任何异常降级为 False。"""
 try:
 ok = await sync_to_async(QdrantService.delete_collection)(repo_id)
 return bool(ok)
 except Exception as exc:
 logger.warning(
 "index_cleanup_qdrant_failed",
 repository_id=repo_id,
 error=str(exc),
 )
 return False
async def _delete_count(model: Any, repo_id: str, *, label: str) -> int:
 """通用：``Model.objects.filter(repository_id=...).adelete`` 拿计数。
 `adelete` 返回 ``(deleted_count: int, per_model: dict[str, int])`` 元组。
 单步异常吞掉 + log warning + 返回 0（per 异常隔离）。
 """
 try:
 deleted, _ = await model.objects.filter(
 repository_id=repo_id
 ).adelete
 return int(deleted)
 except Exception as exc:
 logger.warning(
 "index_cleanup_table_failed",
 repository_id=repo_id,
 table=label,
 error=str(exc),
 )
 return 0
