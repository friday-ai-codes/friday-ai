"""向量命中图扩散 enrich（Phase 15-04）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.conf import settings

from knowledge.graph_store import graph_store
from knowledge.metadata_hydrate import hydrate_entity_metadata
from knowledge.models import EdgeRelation, KnowledgeEntity
from knowledge.retrieval_types import RelatedEntityDTO
from knowledge.vector_recall import VectorHit

__all__ = ["enrich_vector_hits"]

_ENRICH_RELATIONS = [
    EdgeRelation.HAS_PLAN,
    EdgeRelation.IMPLEMENTED_BY,
    EdgeRelation.RELATES_TO,
]


async def enrich_vector_hits(
    hits: list[VectorHit],
    *,
    allowed_project_ids: list[str],
    max_hops: int | None = None,
    as_of: datetime | None = None,
) -> dict[uuid.UUID, list[RelatedEntityDTO]]:
    """对每个 anchor 做图扩散并 hydrate 关联实体。"""
    if not hits or not allowed_project_ids:
        return {}

    hops = max_hops or int(settings.KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS)
    allowed = set(allowed_project_ids)
    out: dict[uuid.UUID, list[RelatedEntityDTO]] = {}

    for hit in hits:
        traversed = await graph_store.traverse(
            hit.entity_id,
            max_hops=hops,
            relations=list(_ENRICH_RELATIONS),
            direction="out",
            as_of=as_of,
        )
        related: list[RelatedEntityDTO] = []
        seen: set[uuid.UUID] = {hit.entity_id}
        for item in traversed:
            if item.entity_id in seen:
                continue
            seen.add(item.entity_id)
            entity = await KnowledgeEntity.objects.filter(id=item.entity_id).afirst()
            if entity is None or entity.project_id is None:
                continue
            if str(entity.project_id) not in allowed:
                continue
            meta = await hydrate_entity_metadata(entity.id, entity.current_version)
            related.append(
                RelatedEntityDTO(
                    entity_id=item.entity_id,
                    entity_kind=entity.kind,
                    relation=EdgeRelation.RELATES_TO,
                    depth=item.depth,
                    metadata=meta,
                )
            )
        out[hit.entity_id] = related
    return out
