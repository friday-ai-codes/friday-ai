"""一站式删除仓库索引衍生物 — Phase Plan / + Phase Plan.
`IndexDeleteView` 历史上把"删 Qdrant collection / 删 FileIndex / 删 codegraph
三件套（Symbol / ImportEdge / Endpoint）"散落写在 view 函数体里，而 Phase 落
地 ``ChunkRegistry`` / ``ChunkEdge`` 后又多出两类需要级联清理的子表。继续把这些
delete 逻辑塞 view 会让 view 越来越胖，且无法被运维脚本（比如未来的 backfill /
verify_payload_consistency --reset 子命令）复用。
本模块把级联清理收敛到 ``cleanup_index(repository_id, *, keep_graph=False)``，
返回结构化 ``CleanupReport``（8 字段 — 6 个 ``*_deleted: int`` + 1 个
``qdrant_collection_deleted: bool`` + 1 个 ``graph_artifacts_cleared: bool``），
便于：
1. 单测直接 assert 每类对象的删除计数 → 防止"忘删某子表"静默漂移。
2. 调用方（view / 脚本）以结构化数据写日志或返回给前端。
**Phase Plan 关键设计**：
- ``cleanup_index`` 内部拆分为 ``_cleanup_vector_artifacts``（Qdrant + FileIndex
 + ChunkEdge + ChunkRegistry）/ ``_cleanup_graph_artifacts``（Symbol +
 ImportEdge + Endpoint）两段；外层 ``cleanup_index(keep_graph=False)`` 默认
 调两者保现有调用方 byte-equivalent（IndexDeleteView /
 verify_payload_consistency --reset 等不变）。
- ``keep_graph=True`` 时仅调向量段，跳过图谱段；``CleanupReport`` 末位
 ``graph_artifacts_cleared`` 取 False 让上游能在 structlog 中分流统计。
**关键不变量**：
- ``ChunkEdge`` 必须在 ``ChunkRegistry`` 之前删除（per CONTEXT ）：当下
 ``ChunkEdge.source_chunk_id / target_chunk_id`` 是 UUID 字段非 DB FK（per
 ``code_relations.models.ChunkEdge`` 注释 ），但保此序方便日后改 FK 时
 零破坏。
- 向量段顺序固定：Qdrant → FileIndex → ChunkEdge → ChunkRegistry。
- 图谱段顺序固定：Symbol → ImportEdge → Endpoint（与 graph_writer per-file
 delete 同序，per Phase CONTEXT D-Discretion）。
- 每步独立 ``try/except`` + ``log.warning`` + report 字段降级（per CONTEXT
 ）；单步失败不向上传播给用户的 DELETE 请求。Qdrant 网络异常 / ORM 死锁
 都不应阻塞"删干净本地状态"。
- ``CleanupReport`` 末位追加 ``graph_artifacts_cleared`` 字段保 ``@dataclass``
 字段位置兼容 → 下游 ``asdict(report)`` / structlog 字段顺序零漂移。
"""
from __future__ import annotations
import asyncio
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
__all__ = [
 "CleanupReport",
 "_cleanup_graph_artifacts",
 "_cleanup_vector_artifacts",
 "cleanup_index",
]
# Qdrant collection 删除单步上限（per ）：collection delete 一般 < 5s，
# 30s 给足重试空间但避免网络分区下永久挂起阻塞整个 DELETE 请求。
_QDRANT_DELETE_TIMEOUT_SECONDS = 30.0
@dataclass(frozen=True)
class CleanupReport:
 """一仓索引清理结果。
 字段语义：
 - ``qdrant_collection_deleted``：Qdrant collection 删除是否成功（异常或返回
 False 都记 False；下游可据此决定是否需要人工介入排查）。
 - ``file_indexes_deleted`` / ``symbols_deleted`` / ``import_edges_deleted`` /
 ``endpoints_deleted`` / ``chunk_edges_deleted`` / ``chunk_registries_deleted``：
 各 Django ORM 表 ``adelete`` 返回的 (count, _) 元组中 count 部分。
 - ``graph_artifacts_cleared``：本次调用是否执行了图谱段（Symbol /
 ImportEdge / Endpoint）清理；``keep_graph=True`` 时为 False，否则 True。
 字段位置必须保持末位以维持 @dataclass 字段顺序兼容（避免下游
 ``asdict(report)`` 调用方字段顺序漂移）。
 """
 qdrant_collection_deleted: bool
 file_indexes_deleted: int
 symbols_deleted: int
 import_edges_deleted: int
 endpoints_deleted: int
 chunk_edges_deleted: int
 chunk_registries_deleted: int
 graph_artifacts_cleared: bool
async def _cleanup_vector_artifacts(repo_id: str) -> dict[str, Any]:
 """清理向量轨衍生物：Qdrant collection + FileIndex + ChunkEdge + ChunkRegistry。
 顺序锁定（Phase 不变量）：
 Qdrant → FileIndex → ChunkEdge → ChunkRegistry
 返回 4 字段 dict（key 与 ``CleanupReport`` 字段名一一对应）：
 qdrant_collection_deleted / file_indexes_deleted /
 chunk_edges_deleted / chunk_registries_deleted
 每步独立异常隔离（per ），单步失败降级为 0 / False。
 """
 qdrant_collection_deleted = await _delete_qdrant_collection(repo_id)
 file_indexes_deleted = await _delete_count(
 FileIndex, repo_id, label="file_indexes"
 )
 # ChunkEdge 必须先于 ChunkRegistry — 当前两表无 DB FK，仅语义顺序
 chunk_edges_deleted = await _delete_count(
 ChunkEdge, repo_id, label="chunk_edges"
 )
 #：ChunkRegistry 走 `_raw_delete` 绕过 pre_delete signal —— 整仓
 # cleanup 场景下 ChunkEdge 已先全删，handler 内 `filter(target=).values_list`
 # + `filter(target=).delete` 对每行 ChunkRegistry 都是空查 + 空删（100k
 # chunks 仓库 → 200k 条多余 SQL，cleanup 时长翻倍）。`_raw_delete` 直接
 # 单条 DELETE WHERE repository_id=...，跳过 signal/cascade 但本表无 FK
 # 入边、且 cleanup 场景下不需要 reconcile 调度。
 chunk_registries_deleted = await _delete_chunk_registries_raw(repo_id)
 return {
 "qdrant_collection_deleted": qdrant_collection_deleted,
 "file_indexes_deleted": file_indexes_deleted,
 "chunk_edges_deleted": chunk_edges_deleted,
 "chunk_registries_deleted": chunk_registries_deleted,
 }
async def _cleanup_graph_artifacts(repo_id: str) -> dict[str, int]:
 """清理图谱三件套：Symbol + ImportEdge + Endpoint。
 顺序锁定（与 graph_writer per-file delete 同序）：
 Symbol → ImportEdge → Endpoint
 返回 3 字段 dict（key 与 ``CleanupReport`` 字段名一一对应）：
 symbols_deleted / import_edges_deleted / endpoints_deleted
 每步独立异常隔离（per ），单步失败降级为 0。
 """
 symbols_deleted = await _delete_count(Symbol, repo_id, label="symbols")
 import_edges_deleted = await _delete_count(
 ImportEdge, repo_id, label="import_edges"
 )
 endpoints_deleted = await _delete_count(
 Endpoint, repo_id, label="endpoints"
 )
 return {
 "symbols_deleted": symbols_deleted,
 "import_edges_deleted": import_edges_deleted,
 "endpoints_deleted": endpoints_deleted,
 }
async def cleanup_index(
 repository_id: str | UUID,
 *,
 keep_graph: bool = False,
) -> CleanupReport:
 """级联清理一个仓库的全部索引衍生物 + Qdrant collection。
 Args:
 repository_id: 仓库 ID（str 或 UUID 都行，内部 ``str(...)``）。
 keep_graph: ``True`` 时仅清向量轨（Qdrant + FileIndex + ChunkEdge +
 ChunkRegistry），跳过图谱三件套（Symbol / ImportEdge / Endpoint）。
 默认 ``False``——既有所有调用方（IndexDeleteView /
 verify_payload_consistency --reset 等）行为 byte-equivalent
 不变，per Phase GRAPH- 兼容性约束。
 Returns:class:`CleanupReport`；任何单步异常都会被吞掉并降级到对应字段
 （计数 0 或 ``qdrant_collection_deleted=False``），永远不向上抛出 — view
 可以放心返回 204（per CONTEXT ）。``graph_artifacts_cleared`` 按
 ``keep_graph`` 取反：``keep_graph=False`` → True，反之 False。
 """
 repo_id = str(repository_id)
 logger.info(
 "index_cleanup_start", repository_id=repo_id, keep_graph=keep_graph
 )
 vector = await _cleanup_vector_artifacts(repo_id)
 if keep_graph:
 graph: dict[str, int] = {
 "symbols_deleted": 0,
 "import_edges_deleted": 0,
 "endpoints_deleted": 0,
 }
 graph_artifacts_cleared = False
 else:
 graph = await _cleanup_graph_artifacts(repo_id)
 graph_artifacts_cleared = True
 report = CleanupReport(
 qdrant_collection_deleted=bool(vector["qdrant_collection_deleted"]),
 file_indexes_deleted=int(vector["file_indexes_deleted"]),
 symbols_deleted=int(graph["symbols_deleted"]),
 import_edges_deleted=int(graph["import_edges_deleted"]),
 endpoints_deleted=int(graph["endpoints_deleted"]),
 chunk_edges_deleted=int(vector["chunk_edges_deleted"]),
 chunk_registries_deleted=int(vector["chunk_registries_deleted"]),
 graph_artifacts_cleared=graph_artifacts_cleared,
 )
 logger.info(
 "index_cleanup_complete",
 repository_id=repo_id,
 keep_graph=keep_graph,
 report=asdict(report),
 )
 return report
async def _delete_qdrant_collection(repo_id: str) -> bool:
 """sync_to_async 包 Qdrant SDK 同步 API；任何异常降级为 False。：加 `asyncio.wait_for` timeout 保护 —— Qdrant 网络分区时
 `delete_collection` 可能永久 hang，整个 DELETE 请求会被挂死；超时后
 降级为 False，本地 ORM 状态仍可继续 cleanup。
 """
 try:
 ok = await asyncio.wait_for(
 sync_to_async(QdrantService.delete_collection)(repo_id),
 timeout=_QDRANT_DELETE_TIMEOUT_SECONDS,
 )
 return bool(ok)
 except asyncio.TimeoutError:
 logger.warning(
 "index_cleanup_qdrant_timeout",
 repository_id=repo_id,
 timeout=_QDRANT_DELETE_TIMEOUT_SECONDS,
 )
 return False
 except Exception as exc:
 logger.warning(
 "index_cleanup_qdrant_failed",
 repository_id=repo_id,
 error=str(exc),
 )
 return False
async def _delete_chunk_registries_raw(repo_id: str) -> int:
 """整仓 cleanup：用 `_raw_delete` 跳过 pre_delete signal 噪音。
 `_raw_delete` 单条 SQL `DELETE WHERE repository_id=...` 直接落盘，
 返回受影响行数；不触发任何 signal、不走 Django cascade。前置约束：
 调用前 ChunkEdge 已先删，本表无 FK 入边，cleanup 场景下无需 reconcile。
 """
 try:
 def _do_delete -> int:
 qs = ChunkRegistry.objects.filter(repository_id=repo_id)
 return int(qs._raw_delete(qs.db))
 return await sync_to_async(_do_delete)
 except Exception as exc:
 logger.warning(
 "index_cleanup_table_failed",
 repository_id=repo_id,
 table="chunk_registries",
 error=str(exc),
 )
 return 0
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
