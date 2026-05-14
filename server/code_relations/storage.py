"""ChunkEdge 批量写入入口（统一在 orchestrator 末尾调一次）。"""
from __future__ import annotations
from collections.abc import Sequence
from typing import TYPE_CHECKING
import structlog
if TYPE_CHECKING:
 from code_relations.models import ChunkEdge
logger = structlog.get_logger(__name__)
__all__ = ["bulk_insert_edges"]
async def bulk_insert_edges(
 edges: Sequence["ChunkEdge"],
 *,
 batch_size: int = 1000,
) -> int:
 """批量写入 ChunkEdge，unique 三元组冲突静默 ignore（per ）。
 多个 builder 可能为同对 (source, target, edge_type) 同时产出边；
 unique 约束 + ignore_conflicts 让 DB 层去重，不必 builder 自己协调。
 返回值：abulk_create 在不同后端语义不同 —— PostgreSQL 等支持 RETURNING 的
 后端返回真实 inserted 行数；SQLite 返回 len(input)，无法区分新增 vs 冲突
 （Django 已知行为）。orchestrator 仅记录此值供观测，不做精确去重判定。
 """
 from code_relations.models import ChunkEdge
 if not edges:
 return 0
 edges_list = list(edges)
 total_created = 0
 for i in range(0, len(edges_list), batch_size):
 chunk = edges_list[i: i + batch_size]
 created = await ChunkEdge.objects.abulk_create(
 chunk,
 ignore_conflicts=True,
 batch_size=batch_size,
 )
 total_created += len(created)
 logger.info(
 "chunk_edges_bulk_inserted",
 total_input=len(edges_list),
 total_created=total_created,
 )
 return total_created
