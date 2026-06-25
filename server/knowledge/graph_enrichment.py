"""向量命中图扩散 enrich（Phase 15-04）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.conf import settings

from knowledge.graph_store import graph_store
from knowledge.metadata_hydrate import hydrate_entity_metadata
from knowledge.models import EdgeRelation, EntityKind, KnowledgeEntity
from knowledge.retrieval_types import RelatedEntityDTO
from knowledge.vector_recall import VectorHit

__all__ = ["enrich_vector_hits"]

_ENRICH_RELATIONS = [
    EdgeRelation.HAS_PLAN,
    EdgeRelation.IMPLEMENTED_BY,
    EdgeRelation.RELATES_TO,
]
_CODE_KINDS = frozenset({EntityKind.CODE_CHANGE})


async def enrich_vector_hits(
    hits: list[VectorHit],
    *,
    allowed_project_ids: list[str],
    allowed_repository_ids: list[str] | None = None,
    max_hops: int | None = None,
    as_of: datetime | None = None,
) -> dict[uuid.UUID, list[RelatedEntityDTO]]:
    """对每个 anchor 做图扩散并 hydrate 关联实体。"""
    if not hits or not allowed_project_ids:
        return {}

    hops = max_hops or int(settings.KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS)
    allowed = set(allowed_project_ids)
    allowed_repos = set(allowed_repository_ids or [])
    out: dict[uuid.UUID, list[RelatedEntityDTO]] = {}

    for hit in hits:
        related: list[RelatedEntityDTO] = []
        seen: set[uuid.UUID] = {hit.entity_id}
        # BFS 逐跳 neighbors，保留真实 relation（traverse 只返回 depth 无边类型）
        frontier: list[tuple[uuid.UUID, int]] = [(hit.entity_id, 0)]
        while frontier:
            current_id, depth = frontier.pop(0)
            if depth >= hops:
                continue
            edges = await graph_store.neighbors(
                current_id,
                relations=list(_ENRICH_RELATIONS),
                direction="out",
                as_of=as_of,
            )
            for edge in edges:
                target_id = edge.target_id
                if target_id is None or target_id in seen:
                    continue
                seen.add(target_id)
                entity = await KnowledgeEntity.objects.filter(id=target_id).afirst()
                if entity is None or entity.space_id is None:
                    continue
                if str(entity.space_id) not in allowed:
                    continue
                if allowed_repos:
                    repo = str(entity.repository_id) if entity.repository_id else ""
                    if repo and repo not in allowed_repos:
                        continue
                    if not repo and entity.kind in _CODE_KINDS:
                        continue
                meta = await hydrate_entity_metadata(entity.id, entity.current_version)
                child_depth = depth + 1
                related.append(
                    RelatedEntityDTO(
                        entity_id=target_id,
                        entity_kind=entity.kind,
                        relation=edge.relation,
                        depth=child_depth,
                        metadata=meta,
                    )
                )
                if child_depth < hops:
                    frontier.append((target_id, child_depth))
        out[hit.entity_id] = related
    return out
