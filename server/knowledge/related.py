"""图关联实体查询（Phase 15-03 RETR-02）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from django.conf import settings

from knowledge.access_scope import resolve_allowed_project_ids
from knowledge.graph_store import graph_store
from knowledge.metadata_hydrate import hydrate_entity_metadata
from knowledge.models import EdgeRelation, KnowledgeEntity
from knowledge.retrieval_types import RelatedEntityDTO

__all__ = ["fetch_related_entities"]

_DEFAULT_RELATIONS = [
    EdgeRelation.HAS_PLAN,
    EdgeRelation.IMPLEMENTED_BY,
    EdgeRelation.RELATES_TO,
]


async def fetch_related_entities(
    entity_id: uuid.UUID,
    *,
    user,
    direction: str = "both",
    max_hops: int | None = None,
    relations: list[str] | None = None,
    as_of: datetime | None = None,
) -> list[RelatedEntityDTO]:
    """基于 GraphStore 多跳遍历返回关联实体。"""
    try:
        entity = await KnowledgeEntity.objects.aget(id=entity_id)
    except KnowledgeEntity.DoesNotExist:
        return []

    if entity.project_id is None:
        return []
    allowed = await resolve_allowed_project_ids(user)
    if str(entity.project_id) not in allowed:
        return []

    hops = max_hops or int(settings.KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS)
    rels = relations or list(_DEFAULT_RELATIONS)
    traversed = await graph_store.traverse(
        entity_id,
        max_hops=hops,
        relations=rels,
        direction=direction,
        as_of=as_of,
    )
    if not traversed:
        return []

    # 收集邻居边 relation 信息（单跳精确；多跳用 traverse depth）
    neighbor_edges = await graph_store.neighbors(
        entity_id, relations=rels, direction=direction, as_of=as_of
    )
    relation_by_target: dict[uuid.UUID, str] = {}
    for edge in neighbor_edges:
        tid = edge.target_id if edge.source_id == entity_id else edge.source_id
        if tid:
            relation_by_target[tid] = edge.relation

    results: list[RelatedEntityDTO] = []
    seen: set[uuid.UUID] = set()
    for item in traversed:
        if item.entity_id in seen:
            continue
        seen.add(item.entity_id)
        related_entity = await KnowledgeEntity.objects.filter(id=item.entity_id).afirst()
        if related_entity is None or related_entity.project_id is None:
            continue
        if str(related_entity.project_id) not in allowed:
            continue
        meta = await hydrate_entity_metadata(related_entity.id, related_entity.current_version)
        results.append(
            RelatedEntityDTO(
                entity_id=item.entity_id,
                entity_kind=related_entity.kind,
                relation=relation_by_target.get(item.entity_id, rels[0]),
                depth=item.depth,
                metadata=meta,
            )
        )
    return results
