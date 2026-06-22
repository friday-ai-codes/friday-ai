"""SemanticEdgeBuilder：Qdrant query_points 单点近邻（per implementation contract/08/09）。

**Pitfall 3 红线**：唯一允许的 Qdrant 调用是 `query_points(query=vector,
limit=20, score_threshold=0.85, must_not=file_path)`；禁止
`retrieve(ids=all, with_vectors=True)` + numpy/sklearn 全量两两余弦（O(n²) trap）。

实现路径（plan 06 方案 B —— scroll 单点拿 vector）：每个 dirty chunk
1. `client.scroll(scroll_filter=HasIdCondition(...), limit=1, with_vectors=True)`
   拿自身 dense vector + file_path（不走 retrieve，避免 plan 01 grep gate）
2. `client.query_points(query=vector, limit=20, score_threshold=0.85,
   query_filter=must_not[file_path=self])` 拿 top-20 跨文件近邻
3. 每个 result point → 一条 ChunkEdge[SEMANTIC] weight=clamp(qdrant_score, 0, 1)

**work item 性能注记（实测延迟 + implementation 优化点）：**

每个 dirty chunk 触发 1 次 scroll + 1 次 query_points = 2 个 Qdrant round
trip。Qdrant 单 call P50 ≈ 5ms，10k dirty chunks 串行约 100s 净网络耗时。
Pitfall 3 红线限制的是 ``retrieve(ids=all, with_vectors=True)`` 一次性多 ID
+ 大对象传输（O(n²) trap），本实现合法但 N 次往返延迟堆叠。

implementation 优化方向：批量 scroll —— 单次
``HasIdCondition(has_id=[batch of 100 ids])`` 减少 100× round trip；query_points
仍需 per-chunk（每条向量独立查询），但 fetch_self_vector 阶段可批量化。
"""

from __future__ import annotations

import asyncio
import math
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async

from code_relations.builders.base import BaseEdgeBuilder
from code_relations.models import ChunkEdge, EdgeType
from services.branch_utils import get_effective_collection_name
from services.qdrant_service import QdrantService

if TYPE_CHECKING:
    from repositories.models import Repository

logger = structlog.get_logger(__name__)

__all__ = ["SemanticEdgeBuilder"]

_SEMANTIC_LIMIT = 20
"""contract 字面：query_points top-K。

注：本 K=20 与 ``payload_sync.MAX_NEIGHBORS_PER_CHUNK=20`` 取值巧合但含义独立
（前者是 Qdrant 向量近邻 K，后者是 payload `related_chunks` 截断阈值）；
未来调整时分别评估，per work item。"""

_SEMANTIC_SCORE_THRESHOLD = 0.85
"""contract 字面：score_threshold。"""


class SemanticEdgeBuilder(BaseEdgeBuilder):
    """Qdrant 向量空间近邻 → SEMANTIC 边（per contract/08/09）。"""

    edge_type_label: str = "SemanticEdge"

    async def build(
        self,
        repository: "Repository",
        dirty_chunk_ids: list[uuid.UUID],
        *,
        branch_name: str = "",
    ) -> list[ChunkEdge]:
        if not dirty_chunk_ids:
            return []

        from qdrant_client.http import models as qmodels

        # implementation / Pitfall 2：feature 分支的 chunk 向量写在 overlay
        # collection；base（branch_name==""）落到旧 collection（字节不变）。
        # `get_effective_collection_name` 内部走同步 ORM（RepositoryBranchIndex
        # 路由），用 sync_to_async 包装避免在 async 上下文直接触发同步 DB 访问。
        #
        # 跨 collection 限制（本 phase 不解决，归 296 GSEARCH）：overlay collection
        # 仅含 diff 文件 chunks，feature chunk 的语义近邻在 overlay 内搜不到 base
        # 邻居。本 phase 仅保证 feature SEMANTIC 边写对 branch_name 且不污染 base；
        # base+overlay 合并语义检索（hop1/hop2 跨 collection）属 296 范畴。
        collection_name = await sync_to_async(get_effective_collection_name)(
            str(repository.id), branch_name
        )
        client = QdrantService.get_client()

        edges: list[ChunkEdge] = []
        skipped_no_vector = 0
        skipped_nan_score = 0

        for chunk_id in dirty_chunk_ids:
            chunk_id_str = str(chunk_id)

            vector, self_file_path, vector_name = await asyncio.to_thread(
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
            # hybrid（命名向量）collection 必须用 ``using`` 指定向量空间，否则
            # query_points 报 "Not existing vector name"（dense collection 传 None 即默认）。
            query_kwargs: dict[str, Any] = {
                "collection_name": collection_name,
                "query": vector,
                "limit": _SEMANTIC_LIMIT,
                "score_threshold": _SEMANTIC_SCORE_THRESHOLD,
                "query_filter": query_filter,
                "with_payload": False,
                "with_vectors": False,
            }
            if vector_name is not None:
                query_kwargs["using"] = vector_name
            result = await asyncio.to_thread(
                lambda kw=query_kwargs: client.query_points(**kw)
            )

            for point in result.points:
                raw_score = float(point.score)
                if math.isnan(raw_score) or math.isinf(raw_score):
                    skipped_nan_score += 1
                    continue
                weight = max(0.0, min(1.0, raw_score))  # contract 双重 clamp
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
                        branch_name=branch_name,
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
    ) -> tuple[list[float] | None, str | None, str | None]:
        """scroll 单点拿 (dense vector, file_path, vector_name)。

        vector_name：命名向量（hybrid）collection 返回 "dense"，单向量 collection
        返回 None —— 供 query_points 的 ``using`` 参数自适应，避免 hybrid collection
        上报 "Not existing vector name"。
        """
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
            return None, None, None
        p = points[0]
        payload = p.payload or {}
        file_path = payload.get("file_path")
        raw_vec = p.vector
        if raw_vec is None:
            return None, file_path, None
        if isinstance(raw_vec, dict):
            # 命名向量 collection：取 dense 空间，query 时需 using="dense"
            vec = raw_vec.get("dense")
            vector_name: str | None = "dense"
        else:
            vec = raw_vec
            vector_name = None
        if vec is None:
            return None, file_path, None
        return list(vec), file_path, vector_name
