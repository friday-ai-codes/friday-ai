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

    if entity.space_id is None:
        return []
    allowed = await resolve_allowed_project_ids(user)
    if str(entity.space_id) not in allowed:
        return []

    hops = max_hops or int(settings.KNOWLEDGE_RETRIEVAL_GRAPH_MAX_HOPS)
    rels = relations or list(_DEFAULT_RELATIONS)

    # 逐跳 BFS 累积 neighbors，保留每个实体被发现时所经边的真实 relation
    # （graph_store.traverse 只返回 depth 无边类型，无法区分多跳 relation——
    # 旧实现对多跳实体 fallback 到 rels[0] 会误标，如把 IMPLEMENTED_BY 标成
    # HAS_PLAN。参考 graph_enrichment.py 的按层累积模式）。
    results: list[RelatedEntityDTO] = []
    seen: set[uuid.UUID] = {entity_id}
    frontier: list[tuple[uuid.UUID, int]] = [(entity_id, 0)]
    while frontier:
        current_id, depth = frontier.pop(0)
        if depth >= hops:
            continue
        edges = await graph_store.neighbors(
            current_id, relations=rels, direction=direction, as_of=as_of
        )
        for edge in edges:
            # 取「对端」实体：out 用 target，in 用 source，both 取非 current 的一端
            if direction == "out":
                other_id = edge.target_id
            elif direction == "in":
                other_id = edge.source_id
            else:
                other_id = edge.target_id if edge.source_id == current_id else edge.source_id
            if other_id is None or other_id in seen:
                continue
            seen.add(other_id)
            child_depth = depth + 1
            # 无论是否有访问权限都继续向下遍历，仅在结果中过滤（保持旧遍历可达性）
            frontier.append((other_id, child_depth))

            related_entity = await KnowledgeEntity.objects.filter(id=other_id).afirst()
            if related_entity is None or related_entity.space_id is None:
                continue
            if str(related_entity.space_id) not in allowed:
                continue
            meta = await hydrate_entity_metadata(related_entity.id, related_entity.current_version)
            results.append(
                RelatedEntityDTO(
                    entity_id=other_id,
                    entity_kind=related_entity.kind,
                    relation=edge.relation,
                    depth=child_depth,
                    metadata=meta,
                )
            )
    return results
