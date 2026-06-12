"""纯 PG 迭代轨迹查询（Phase 15-03 RETR-03，零 Qdrant）。"""

from __future__ import annotations

import uuid

from asgiref.sync import sync_to_async
from django.db.models import Q

from knowledge.access_scope import resolve_allowed_project_ids
from knowledge.metadata_hydrate import hydrate_entity_metadata
from knowledge.models import EdgeRelation, KnowledgeEntity, KnowledgeEntityVersion, KnowledgeEdge
from knowledge.retrieval_types import TimelineNodeDTO

__all__ = ["build_entity_timeline"]


async def _assert_entity_access(entity: KnowledgeEntity, user) -> bool:
    if entity.project_id is None:
        return False
    allowed = await resolve_allowed_project_ids(user)
    return str(entity.project_id) in allowed


def _version_queryset(entity_id: uuid.UUID, include_superseded: bool):
    qs = KnowledgeEntityVersion.objects.filter(entity_id=entity_id)
    if not include_superseded:
        qs = qs.filter(Q(is_latest=True) | Q(invalid_at__isnull=True))
    return qs.order_by("version")


async def _code_change_keys_for_version(entity_id: uuid.UUID) -> list[tuple[uuid.UUID, int]]:
    """经 IMPLEMENTED_BY 出边反查 code_change entity。"""
    keys: list[tuple[uuid.UUID, int]] = []
    qs = KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        relation=EdgeRelation.IMPLEMENTED_BY,
        target_entity_id__isnull=False,
        invalid_at__isnull=True,
        expired_at__isnull=True,
    ).select_related("target_entity").order_by("valid_at")
    async for edge in qs:
        target = edge.target_entity
        if target is None:
            continue
        keys.append((target.id, target.current_version or 1))
    return keys


async def build_entity_timeline(
    entity_id: uuid.UUID,
    *,
    user,
    include_superseded: bool = False,
) -> list[TimelineNodeDTO]:
    """按 version 升序返回迭代轨迹；挂接 code_change 按 event_time 排序。"""
    try:
        entity = await KnowledgeEntity.objects.aget(id=entity_id)
    except KnowledgeEntity.DoesNotExist:
        return []

    if not await _assert_entity_access(entity, user):
        return []

    versions = await sync_to_async(list)(_version_queryset(entity_id, include_superseded))

    nodes: list[TimelineNodeDTO] = []
    for ver in versions:
        if not include_superseded and not ver.is_latest and ver.invalid_at is not None:
            continue
        keys = await _code_change_keys_for_version(entity_id)
        code_changes = []
        for eid, ver_no in keys:
            meta = await hydrate_entity_metadata(eid, ver_no, include_superseded=True)
            if meta is None:
                # fallback：边存在但版本 hydrate 失败时仍挂接最小 metadata
                target = await KnowledgeEntity.objects.filter(id=eid).afirst()
                if target:
                    from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks

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
                        project_id=str(target.project_id) if target.project_id else None,
                        repository_id=str(target.repository_id) if target.repository_id else None,
                        provenance=ProvenanceLinks(),
                    )
            if meta:
                code_changes.append(meta)
        code_changes.sort(key=lambda m: m.event_time or m.valid_at or ver.event_time)
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
                code_changes=tuple(code_changes),
            )
        )
    return nodes
