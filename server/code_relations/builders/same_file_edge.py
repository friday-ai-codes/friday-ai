"""SameFileEdgeBuilder：同文件 chunk 两两弱关联（per Phase/14/15）。"""
from __future__ import annotations
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING
import structlog
from asgiref.sync import sync_to_async
from code_relations.builders.base import BaseEdgeBuilder
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
if TYPE_CHECKING:
 from repositories.models import Repository
logger = structlog.get_logger(__name__)
__all__ = ["SameFileEdgeBuilder"]
_SAMEFILE_FANOUT_THRESHOLD = 50 # n > 50 时切换到「相邻 5 个」模式
_SAMEFILE_NEIGHBOR_WINDOW = 5
_SAMEFILE_WEIGHT = 0.3 # 固定权重
class SameFileEdgeBuilder(BaseEdgeBuilder):
 """同文件内 chunk 两两建 SAME_FILE 边（弱关联）。
 - n ≤ 50：全配对 (i, j) for i < j（O(n²/2)）
 - n > 50：仅相邻 5 个配对 (i, i+1..i+5)，避免单文件 1000 chunks 爆 50万边
 - 单向 source < target（uuid 字典序），节省一半存储
 - weight=0.3 固定提示性弱关联
 """
 edge_type_label: str = "SameFileEdge"
 async def build(
 self,
 repository: "Repository",
 dirty_chunk_ids: list[uuid.UUID],
 *,
 branch_name: str = "",
 ) -> list[ChunkEdge]:
 # 全扫策略（per CONTEXT ）：本 phase 接受全仓 ChunkRegistry
 # 重建全文件 SAME_FILE 边集；dirty_chunk_ids 暂未用于过滤，仅靠
 # bulk_insert_edges 的 ignore_conflicts 兜底去重。Phase 应改造为
 # 「dirty file_path 反查 → file_path__in 过滤」增量化。
 del dirty_chunk_ids # noqa: F841 — Phase 全扫策略，Phase 增量化
 @sync_to_async
 def _load_rows -> list[tuple[str, int, uuid.UUID]]:
 return list(
 ChunkRegistry.objects.filter(
 repository_id=repository.id, branch_name=branch_name
 )
 .order_by("file_path", "chunk_index")
 .values_list("file_path", "chunk_index", "chunk_id")
 )
 rows = await _load_rows
 files: dict[str, list[tuple[int, uuid.UUID]]] = defaultdict(list)
 for fp, idx, cid in rows:
 files[fp].append((idx, cid))
 edges: list[ChunkEdge] =
 for fp, items in files.items:
 items.sort(key=lambda t: t[0])
 n = len(items)
 if n <= 1:
 continue
 if n <= _SAMEFILE_FANOUT_THRESHOLD:
 pairs: list[tuple[int, int]] = [
 (i, j) for i in range(n) for j in range(i + 1, n)
 ]
 else:
 pairs = [
 (i, j)
 for i in range(n)
 for j in range(
 i + 1, min(n, i + 1 + _SAMEFILE_NEIGHBOR_WINDOW)
 )
 ]
 for i, j in pairs:
 a_idx, a_cid = items[i]
 b_idx, b_cid = items[j]
 src_cid, tgt_cid = (
 (a_cid, b_cid) if str(a_cid) < str(b_cid) else (b_cid, a_cid)
 )
 edges.append(
 ChunkEdge(
 source_chunk_id=src_cid,
 target_chunk_id=tgt_cid,
 edge_type=EdgeType.SAME_FILE,
 weight=_SAMEFILE_WEIGHT,
 metadata={
 "file_path": fp,
 "chunk_index_diff": abs(b_idx - a_idx),
 },
 repository=repository,
 branch_name=branch_name,
 )
 )
 logger.info(
 "same_file_edge_build_complete",
 repository_id=str(repository.id),
 files=len(files),
 edges_built=len(edges),
 )
 return edges
