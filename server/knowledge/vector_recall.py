"""delivery_knowledge 向量分路召回（Phase 15-02，P1/P5/P6 防线）。

强制 is_latest + project_id + repository_id filter；allowed 空时零 Qdrant 调用。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from qdrant_client import models

from knowledge.collection import DELIVERY_KNOWLEDGE_COLLECTION
from knowledge.models import EntityKind
from services.embedding import EmbeddingService
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)

__all__ = ["VectorHit", "recall_similar_chunks"]

# Phase 100 KNOW-02：learning_case（经验案例）纳入 demand 分路白名单，
# search_similar(entity_kinds=["learning_case"]) 经 demand 分路可召回。
_DEMAND_KINDS = (EntityKind.WORK_ITEM, EntityKind.TECH_PLAN, EntityKind.LEARNING_CASE)
# 项目上下文读路径（CTX-01）额外纳入 DOCUMENT 召回——项目 5 文件/记忆/工件物化为
# DOCUMENT 实体，仅在 ``include_document_kind=True`` 时叠加到无仓库 demand 分路（不影响
# 全局代码检索的既有 demand/code 分路）。
_DOCUMENT_KINDS = (EntityKind.DOCUMENT,)
_CODE_KINDS = (EntityKind.CODE_CHANGE,)
_RRF_K = 60


@dataclass(frozen=True, slots=True)
class VectorHit:
    """单条向量召回命中。"""

    point_id: str
    entity_id: uuid.UUID
    entity_kind: str
    version: int
    score: float
    rrf_score: float
    payload: dict[str, Any]


def _build_knowledge_must_filter(
    *,
    allowed_project_ids: list[str],
    allowed_repository_ids: list[str],
    entity_kinds: list[str] | None,
    include_superseded: bool,
    require_repository: bool = True,
) -> models.Filter:
    """构建 knowledge 检索 must filter（P1/P6，私有无 bypass 出口）。"""
    must: list[models.Condition] = []
    if not include_superseded:
        must.append(models.FieldCondition(key="is_latest", match=models.MatchValue(value=True)))
    if allowed_project_ids:
        must.append(
            models.FieldCondition(
                key="project_id",
                match=models.MatchAny(any=allowed_project_ids),
            )
        )
    if require_repository:
        if allowed_repository_ids:
            must.append(
                models.FieldCondition(
                    key="repository_id",
                    match=models.MatchAny(any=allowed_repository_ids),
                )
            )
    elif allowed_repository_ids:
        # demand 分路：无仓库实体 payload 为 ""，需 OR 匹配
        must.append(
            models.FieldCondition(
                key="repository_id",
                match=models.MatchAny(any=[*allowed_repository_ids, ""]),
            )
        )
    if entity_kinds:
        must.append(
            models.FieldCondition(key="entity_kind", match=models.MatchAny(any=entity_kinds))
        )
    return models.Filter(must=must)


async def _hybrid_query(
    query_dense: list[float],
    query_sparse: dict[str, Any],
    *,
    limit: int,
    query_filter: models.Filter,
) -> list[dict[str, Any]]:
    """hybrid dense+sparse RRF 查询（注入完整 models.Filter）。"""

    def _run() -> list[dict[str, Any]]:
        client = QdrantService.get_client()
        sparse_vector = models.SparseVector(
            indices=query_sparse["indices"],
            values=query_sparse["values"],
        )
        results = client.query_points(
            collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
            prefetch=[
                models.Prefetch(query=query_dense, using="dense", limit=limit, filter=query_filter),
                models.Prefetch(
                    query=sparse_vector, using="sparse", limit=limit, filter=query_filter
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [
            {"id": str(r.id), "score": r.score, "payload": r.payload or {}} for r in results.points
        ]

    return await sync_to_async(_run)()


def _to_vector_hit(raw: dict[str, Any], rrf_score: float) -> VectorHit | None:
    payload = raw.get("payload") or {}
    entity_id_raw = payload.get("entity_id")
    if not entity_id_raw:
        return None
    return VectorHit(
        point_id=str(raw["id"]),
        entity_id=uuid.UUID(str(entity_id_raw)),
        entity_kind=str(payload.get("entity_kind", "")),
        version=int(payload.get("version") or 0),
        score=float(raw.get("score") or 0.0),
        rrf_score=rrf_score,
        payload=payload,
    )


def _rrf_fuse(
    list_a: list[VectorHit], list_b: list[VectorHit], *, k: int = _RRF_K
) -> list[VectorHit]:
    """跨路 RRF 融合（按 point_id 排名）。"""
    scores: dict[str, float] = {}
    hits_by_point: dict[str, VectorHit] = {}

    for rank, hit in enumerate(list_a, start=1):
        scores[hit.point_id] = scores.get(hit.point_id, 0.0) + 1.0 / (k + rank)
        hits_by_point[hit.point_id] = hit
    for rank, hit in enumerate(list_b, start=1):
        scores[hit.point_id] = scores.get(hit.point_id, 0.0) + 1.0 / (k + rank)
        hits_by_point.setdefault(hit.point_id, hit)

    fused: list[VectorHit] = []
    for point_id, rrf in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        base = hits_by_point[point_id]
        fused.append(
            VectorHit(
                point_id=base.point_id,
                entity_id=base.entity_id,
                entity_kind=base.entity_kind,
                version=base.version,
                score=base.score,
                rrf_score=rrf,
                payload=base.payload,
            )
        )
    return fused


def _dedupe_by_entity(hits: list[VectorHit]) -> list[VectorHit]:
    """entity_id 去重，保留最高 RRF 分。"""
    best: dict[uuid.UUID, VectorHit] = {}
    for hit in hits:
        prev = best.get(hit.entity_id)
        if prev is None or hit.rrf_score > prev.rrf_score:
            best[hit.entity_id] = hit
    return sorted(best.values(), key=lambda h: h.rrf_score, reverse=True)


async def recall_similar_chunks(
    query: str,
    *,
    allowed_project_ids: list[str],
    allowed_repository_ids: list[str],
    top_k: int = 10,
    entity_kinds: list[str] | None = None,
    include_superseded: bool = False,
    include_document_kind: bool = False,
) -> list[VectorHit]:
    """分路 hybrid 召回 + 跨路 RRF + entity 去重。

    ``include_document_kind=True``（项目上下文读路径 CTX-01）时，无仓库 demand 分路额外
    纳入 ``DOCUMENT`` 实体召回（项目 5 文件/记忆/工件物化），不放宽 project_id/repository_id
    权限闸（visibility 仍由 ``allowed_project_ids`` 收口，无泄漏）。
    """
    if not allowed_project_ids:
        return []

    demand_limit = max(1, math.ceil(top_k * 0.7))
    if allowed_repository_ids:
        code_limit = max(1, math.ceil(top_k * 0.3))
    else:
        code_limit = 0

    # Phase 100 KNOW-02 吞参修复：显式传入 entity_kinds 时各分路取「传入 kinds ∩ 分路白名单」
    # 严格过滤——交集为空则该分路不发 Qdrant 查询；两分路皆空直接返回 []（信息泄露防线：
    # 未知 kind 绝不回退全量放大召回面）。entity_kinds=None 时保持既有分路口径零回归。
    demand_allowed = list(_DEMAND_KINDS)
    if include_document_kind:
        demand_allowed = [*demand_allowed, *_DOCUMENT_KINDS]
    if entity_kinds is None:
        demand_kinds = demand_allowed
        code_kinds = list(_CODE_KINDS)
    else:
        demand_kinds = [k for k in entity_kinds if k in demand_allowed]
        code_kinds = [k for k in entity_kinds if k in _CODE_KINDS]
        if not demand_kinds and not code_kinds:
            # 短路在 embedding 之前，省一次远程调用
            return []

    query_dense = await EmbeddingService.generate_embedding(query)
    if not query_dense:
        return []
    query_sparse = await sync_to_async(SparseEncoderService.encode)(query)
    if not query_sparse.get("indices"):
        return []

    demand_hits: list[VectorHit] = []
    if demand_kinds:
        demand_filter = _build_knowledge_must_filter(
            allowed_project_ids=allowed_project_ids,
            allowed_repository_ids=allowed_repository_ids,
            entity_kinds=demand_kinds,
            include_superseded=include_superseded,
            require_repository=False,
        )
        demand_raw = await _hybrid_query(
            query_dense, query_sparse, limit=demand_limit, query_filter=demand_filter
        )
        demand_hits = [h for r in demand_raw if (h := _to_vector_hit(r, 0.0))]

    code_hits: list[VectorHit] = []
    if code_limit > 0 and code_kinds:
        code_filter = _build_knowledge_must_filter(
            allowed_project_ids=allowed_project_ids,
            allowed_repository_ids=allowed_repository_ids,
            entity_kinds=code_kinds,
            include_superseded=include_superseded,
            require_repository=True,
        )
        code_raw = await _hybrid_query(
            query_dense, query_sparse, limit=code_limit, query_filter=code_filter
        )
        code_hits = [h for r in code_raw if (h := _to_vector_hit(r, 0.0))]

    fused = _rrf_fuse(demand_hits, code_hits)
    deduped = _dedupe_by_entity(fused)
    logger.info(
        "knowledge_vector_recall_completed",
        query_len=len(query),
        demand=len(demand_hits),
        code=len(code_hits),
        result_count=len(deduped[:top_k]),
        entity_kinds=entity_kinds,
    )
    return deduped[:top_k]
