"""payload `related_chunks` 一跳快照聚合（per Phase/24/25）。
单次 SQL 拉取所有 dirty source 的边 + Python group-by + top-N 截取 + 5KB 截断；
输出 `list[(point_id_str, payload_dict)]` 给 `QdrantService.batch_set_payload`
一次性写入 Qdrant（：6 builder 全部完成后**统一**调一次，不是每 builder
独立 sync）。
设计要点：
- 单次 `.filter(source_chunk_id__in=dirty_chunk_ids)` + Python `defaultdict`
 分组，避免 N+1。
- `.only(4 字段)` 限定列宽（100k×20=200万行 × 64 byte ≈ 13 MB 可接受）。
- 排序键 `(-weight, chunk_id_str)`：weight desc 主键 + chunk_id 字典序稳定
 破平局，保证多次运行 payload 一致（diff-friendly）。
- 5KB 截断阶梯 20→15→10→5→1：理论 20 邻居 ≈ 1.6 KB 通常不触顶，超长 metadata
 下保证 payload 不爆破 Qdrant 内存。
"""
from __future__ import annotations
import json
import uuid
from collections import defaultdict
from typing import Any
import structlog
from code_relations.constants import MAX_NEIGHBORS_PER_CHUNK, MAX_PAYLOAD_SIZE_BYTES
logger = structlog.get_logger(__name__)
__all__ = ["aggregate_top_neighbors"]
_TRUNCATE_STEPS: tuple[int, ...] = (20, 15, 10, 5, 1)
"""5KB 超限时的 top-N 截断阶梯（per ）。"""
async def aggregate_top_neighbors(
 repository_id: str | uuid.UUID,
 dirty_chunk_ids: list[uuid.UUID],
) -> list[tuple[str, dict[str, Any]]]:
 """聚合 dirty chunks 的 top-N 邻居，返回 batch_set_payload 接受的 updates 列表。
 Args:
 repository_id: 仓库 ID（str 或 UUID 均可，Django ORM 自动转换）
 dirty_chunk_ids: 本次 indexer 写入或更新的 chunk_id 列表
 Returns:
 `list[(point_id_str, {"related_chunks": [[chunk_id, edge_type, weight], ...]})]`
 - 空 dirty_chunk_ids → 立即返回 ``，零 SQL 调用
 - dirty 中无任何边的 chunk → 不出现在 updates（不写空 payload）
 - 每条 updates 的 `related_chunks` 长度 ≤ `MAX_NEIGHBORS_PER_CHUNK`，
 且 `len(json.dumps(payload).encode) ≤ MAX_PAYLOAD_SIZE_BYTES`
 """
 if not dirty_chunk_ids:
 return
 from code_relations.models import ChunkEdge
 qs = (
 ChunkEdge.objects.filter(
 repository_id=repository_id,
 source_chunk_id__in=dirty_chunk_ids,
 )
 .only("source_chunk_id", "target_chunk_id", "edge_type", "weight")
 .order_by("source_chunk_id", "-weight")
 )
 groups: dict[uuid.UUID, list[tuple[uuid.UUID, str, float]]] = defaultdict(list)
 async for edge in qs:
 groups[edge.source_chunk_id].append(
 (edge.target_chunk_id, str(edge.edge_type), float(edge.weight))
 )
 updates: list[tuple[str, dict[str, Any]]] =
 truncated_count = 0
 for src, neighbors in groups.items:
 neighbors.sort(key=lambda t: (-t[2], str(t[0])))
 top = neighbors[:MAX_NEIGHBORS_PER_CHUNK]
 payload = _build_payload(top)
 if len(json.dumps(payload).encode) > MAX_PAYLOAD_SIZE_BYTES:
 for limit in _TRUNCATE_STEPS:
 if limit >= len(top):
 continue
 top = top[:limit]
 payload = _build_payload(top)
 if len(json.dumps(payload).encode) <= MAX_PAYLOAD_SIZE_BYTES:
 truncated_count += 1
 break
 updates.append((str(src), payload))
 logger.info(
 "payload_aggregate_complete",
 repository_id=str(repository_id),
 dirty_chunks=len(dirty_chunk_ids),
 chunks_with_edges=len(groups),
 updates=len(updates),
 truncated=truncated_count,
 )
 return updates
def _build_payload(
 neighbors: list[tuple[uuid.UUID, str, float]],
) -> dict[str, Any]:
 """构造 `{"related_chunks": [[chunk_id_str, edge_type_str, weight_float], ...]}`。"""
 return {
 "related_chunks": [
 [str(cid), edge_type, weight] for cid, edge_type, weight in neighbors
 ],
 }
