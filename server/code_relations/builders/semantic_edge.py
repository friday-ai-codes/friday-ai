"""SemanticEdgeBuilder：Qdrant query_points 单点近邻（per Phase/08/09）。
**Pitfall 3 红线**：唯一允许的 Qdrant 调用是 `query_points(query=vector,
limit=20, score_threshold=0.85, must_not=file_path)`；禁止
`retrieve(ids=all, with_vectors=True)` + numpy/sklearn 全量两两余弦（O(n²) trap）。
实现路径（Plan 方案 B —— scroll 单点拿 vector）：每个 dirty chunk
1. `client.scroll(scroll_filter=HasIdCondition(...), limit=1, with_vectors=True)`
 拿自身 dense vector + file_path（不走 retrieve，避免 Plan grep gate）
2. `client.query_points(query=vector, limit=20, score_threshold=0.85,
 query_filter=must_not[file_path=self])` 拿 top-20 跨文件近邻
3. 每个 result point → 一条 ChunkEdge[SEMANTIC] weight=clamp(qdrant_score, 0, 1)
"""
from __future__ import annotations
import asyncio
import math
import uuid
from typing import TYPE_CHECKING, Any
import structlog
from code_relations.builders.base import BaseEdgeBuilder
from code_relations.models import ChunkEdge, EdgeType
from services.qdrant_service import QdrantService
if TYPE_CHECKING:
 from repositories.models import Repository
logger = structlog.get_logger(__name__)
__all__ = ["SemanticEdgeBuilder"]
_SEMANTIC_LIMIT = 20 # 字面
_SEMANTIC_SCORE_THRESHOLD = 0.85 # 字面
class SemanticEdgeBuilder(BaseEdgeBuilder):
 """Qdrant 向量空间近邻 → SEMANTIC 边（per ）。"""
 edge_type_label: str = "SemanticEdge"
 async def build(
 self,
 repository: "Repository",
 dirty_chunk_ids: list[uuid.UUID],
 ) -> list[ChunkEdge]:
 if not dirty_chunk_ids:
 return
 from qdrant_client.http import models as qmodels
 collection_name = QdrantService.get_collection_name(str(repository.id))
 client = QdrantService.get_client
 edges: list[ChunkEdge] =
 skipped_no_vector = 0
 skipped_nan_score = 0
 for chunk_id in dirty_chunk_ids:
 chunk_id_str = str(chunk_id)
 vector, self_file_path = await asyncio.to_thread(
 self._fetch_self_vector, client, collection_name, chunk_id_str
 )
 if vector is None or self_file_path is None:
 skipped_no_vector += 1
 continue
 query_filter = qmodels.Filter(
 must_not=[
 qmodels.FieldCondition(
 key="file_path",
 match=qmodels.MatchValue(value=self_file_path),
 ),
 ],
 )
 result = await asyncio.to_thread(
 client.query_points,
 collection_name=collection_name,
 query=vector,
 limit=_SEMANTIC_LIMIT,
 score_threshold=_SEMANTIC_SCORE_THRESHOLD,
 query_filter=query_filter,
 with_payload=False,
 with_vectors=False,
 )
 for point in result.points:
 raw_score = float(point.score)
 if math.isnan(raw_score) or math.isinf(raw_score):
 skipped_nan_score += 1
 continue
 weight = max(0.0, min(1.0, raw_score)) # 双重 clamp
 try:
 target_cid = uuid.UUID(str(point.id))
 except (TypeError, ValueError):
 continue
 if target_cid == chunk_id:
 continue
 edges.append(
 ChunkEdge(
 source_chunk_id=chunk_id,
 target_chunk_id=target_cid,
 edge_type=EdgeType.SEMANTIC,
 weight=weight,
 metadata={"qdrant_score": raw_score},
 repository=repository,
 )
 )
 logger.info(
 "semantic_edge_build_complete",
 repository_id=str(repository.id),
 dirty_chunks=len(dirty_chunk_ids),
 edges_built=len(edges),
 skipped_no_vector=skipped_no_vector,
 skipped_nan_score=skipped_nan_score,
 )
 return edges
 @staticmethod
 def _fetch_self_vector(
 client: Any,
 collection_name: str,
 chunk_id_str: str,
 ) -> tuple[list[float] | None, str | None]:
 """scroll 单点拿 (dense vector, file_path)；hybrid 模式取 vector['dense']。"""
 from qdrant_client.http import models as qmodels
 scroll_result = client.scroll(
 collection_name=collection_name,
 scroll_filter=qmodels.Filter(
 must=[qmodels.HasIdCondition(has_id=[chunk_id_str])]
 ),
 limit=1,
 with_payload=["file_path"],
 with_vectors=True,
 )
 points, _ = scroll_result
 if not points:
 return None, None
 p = points[0]
 payload = p.payload or {}
 file_path = payload.get("file_path")
 raw_vec = p.vector
 if raw_vec is None:
 return None, file_path
 if isinstance(raw_vec, dict):
 vec = raw_vec.get("dense")
 else:
 vec = raw_vec
 if vec is None:
 return None, file_path
 return list(vec), file_path
