"""纯 PG 迭代轨迹查询（Phase 15-03 RETR-03，零 Qdrant）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from asgiref.sync import sync_to_async
from django.db.models import Q

from knowledge.access_scope import resolve_allowed_project_ids
from knowledge.graph_store import require_aware
from knowledge.metadata_hydrate import hydrate_entity_metadata
from knowledge.models import EdgeRelation, KnowledgeEdge, KnowledgeEntity, KnowledgeEntityVersion
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, TimelineNodeDTO

__all__ = ["build_entity_timeline"]


async def _assert_entity_access(entity: KnowledgeEntity, user) -> bool:
    if entity.space_id is None:
        return False
    allowed = await resolve_allowed_project_ids(user)
    return str(entity.space_id) in allowed


def _version_queryset(
    entity_id: uuid.UUID,
    include_superseded: bool,
    as_of: datetime | None = None,
):
    qs = KnowledgeEntityVersion.objects.filter(entity_id=entity_id)
    if as_of is not None:
        require_aware(as_of, "as_of")
        qs = qs.filter(
            Q(valid_at__lte=as_of) & (Q(invalid_at__isnull=True) | Q(invalid_at__gt=as_of))
        )
    elif not include_superseded:
        qs = qs.filter(Q(is_latest=True) | Q(invalid_at__isnull=True))
    return qs.order_by("version")


async def _code_change_edges_for_entity(
    entity_id: uuid.UUID,
    *,
    as_of: datetime | None = None,
) -> list[tuple[uuid.UUID, int, datetime]]:
    """经 IMPLEMENTED_BY 出边反查 code_change entity。

    返回 (target_id, target_version, edge_valid_at) 三元组；``edge_valid_at``
    用于在 timeline 构建时按版本时间窗口归属（避免所有版本节点共享同一批
    code_change，造成"串味"）。
    """
    edges: list[tuple[uuid.UUID, int, datetime]] = []
    qs = KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        relation=EdgeRelation.IMPLEMENTED_BY,
        target_entity_id__isnull=False,
    )
    if as_of is None:
        qs = qs.filter(invalid_at__isnull=True, expired_at__isnull=True)
    else:
        require_aware(as_of, "as_of")
        qs = qs.filter(
            Q(valid_at__lte=as_of)
            & (Q(invalid_at__isnull=True) | Q(invalid_at__gt=as_of))
            & Q(created_at__lte=as_of)
            & (Q(expired_at__isnull=True) | Q(expired_at__gt=as_of))
        )
    qs = qs.select_related("target_entity").order_by("valid_at")
    async for edge in qs:
        target = edge.target_entity
        if target is None:
            continue
        edges.append((target.id, target.current_version or 1, edge.valid_at))
    return edges


async def build_entity_timeline(
    entity_id: uuid.UUID,
    *,
    user,
    include_superseded: bool = False,
    as_of: datetime | None = None,
) -> list[TimelineNodeDTO]:
    """按 version 升序返回迭代轨迹；挂接 code_change 按 event_time 排序。"""
    try:
        entity = await KnowledgeEntity.objects.aget(id=entity_id)
    except KnowledgeEntity.DoesNotExist:
        return []

    if not await _assert_entity_access(entity, user):
        return []

    versions = await sync_to_async(list)(
        _version_queryset(entity_id, include_superseded, as_of=as_of)
    )
    code_change_edges = await _code_change_edges_for_entity(entity_id, as_of=as_of)

    nodes: list[TimelineNodeDTO] = []
    for ver in versions:
        if not include_superseded and not ver.is_latest and ver.invalid_at is not None:
            continue
        # 按版本时间窗口 [valid_at, invalid_at) 归属 code_change：边在该版本生效
        # 期间变为有效才挂到此节点，避免不同版本节点共享同一批 code_change。
        keys = [
            (eid, ver_no)
            for eid, ver_no, edge_valid_at in code_change_edges
            if (ver.valid_at is None or edge_valid_at >= ver.valid_at)
            and (ver.invalid_at is None or edge_valid_at < ver.invalid_at)
        ]
        code_changes = []
        for eid, ver_no in keys:
            meta = await hydrate_entity_metadata(eid, ver_no, include_superseded=True)
            if meta is None:
                # fallback：边存在但版本 hydrate 失败时仍挂接最小 metadata
                target = await KnowledgeEntity.objects.filter(id=eid).afirst()
                if target:
                    meta = EntityMetadata(
                        entity_id=target.id,
                        entity_kind=target.kind,
                        version=ver_no,
                        title=target.title,
                        valid_at=ver.valid_at,
                        invalid_at=None,
                        source_kind=target.source_kind,
                        source_id=target.source_id,
                        origin=target.origin,
                        event_time=target.event_time,
                        space_id=str(target.space_id) if target.space_id else None,
                        repository_id=str(target.repository_id) if target.repository_id else None,
                        provenance=ProvenanceLinks(),
                    )
            if meta:
                code_changes.append(meta)
        code_changes.sort(key=lambda m: m.event_time or m.valid_at or ver.event_time)
        version_meta = await hydrate_entity_metadata(
            entity.id, ver.version, include_superseded=True
        )
        provenance = version_meta.provenance if version_meta else ProvenanceLinks()
        nodes.append(
            TimelineNodeDTO(
                entity_id=entity.id,
                version=ver.version,
                kind=entity.kind,
                title=entity.title,
                summary=(ver.content or "")[:200],
                valid_at=ver.valid_at,
                invalid_at=ver.invalid_at,
                event_time=ver.event_time,
                provenance=provenance,
                code_changes=tuple(code_changes),
            )
        )
    return nodes
