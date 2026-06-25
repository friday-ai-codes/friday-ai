"""PG metadata 出处补全（Phase 15-02 RETR-06）。"""

from __future__ import annotations

import uuid

from asgiref.sync import sync_to_async

from knowledge.models import CodeChangeArchive, EntityKind, KnowledgeEntityVersion
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks

__all__ = ["hydrate_entity_metadata", "hydrate_many"]


def _feishu_url(entity, version) -> str | None:
    if entity.source_kind != "feishu_work_item":
        return None
    payload = version.payload if isinstance(version.payload, dict) else {}
    if payload.get("feishu_url"):
        return str(payload["feishu_url"])
    if entity.space_id and entity.source_id:
        key = entity.space.feishu_project_key if entity.space else ""
        if key:
            return f"https://project.feishu.cn/{key}/story/detail/{entity.source_id}"
    return None


def _build_provenance(entity, version) -> ProvenanceLinks:
    feishu = _feishu_url(entity, version)
    mr_url: str | None = None
    session_link: str | None = None

    if entity.kind == EntityKind.CODE_CHANGE:
        archive = (
            CodeChangeArchive.objects.filter(
                source_kind=entity.source_kind, source_id=entity.source_id
            )
            .order_by("-created_at")
            .first()
        )
        if archive and archive.mr_url:
            mr_url = archive.mr_url

    if entity.kind == EntityKind.TECH_PLAN:
        payload = version.payload if isinstance(version.payload, dict) else {}
        session_link = payload.get("session_link") or payload.get("session_id")

    return ProvenanceLinks(feishu_url=feishu, mr_url=mr_url, session_link=session_link)


def _superseded_hint(entity_id: uuid.UUID, version: KnowledgeEntityVersion) -> str | None:
    if version.is_latest:
        return None
    max_v = (
        KnowledgeEntityVersion.objects.filter(entity_id=entity_id)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    if max_v and max_v > version.version:
        return f"superseded by v{max_v}"
    return None


async def hydrate_entity_metadata(
    entity_id: uuid.UUID,
    version: int,
    *,
    include_superseded: bool = False,
) -> EntityMetadata | None:
    """从 PG 补全单条 EntityMetadata。"""
    try:
        ver = await KnowledgeEntityVersion.objects.select_related(
            "entity", "entity__space", "entity__repository"
        ).aget(entity_id=entity_id, version=version)
    except KnowledgeEntityVersion.DoesNotExist:
        return None

    if not include_superseded and not ver.is_latest:
        return None

    entity = ver.entity

    def _build() -> EntityMetadata:
        provenance = _build_provenance(entity, ver)
        return EntityMetadata(
            entity_id=entity.id,
            entity_kind=entity.kind,
            version=ver.version,
            title=entity.title,
            valid_at=ver.valid_at,
            invalid_at=ver.invalid_at,
            source_kind=entity.source_kind,
            source_id=entity.source_id,
            origin=entity.origin,
            event_time=ver.event_time,
            space_id=str(entity.space_id) if entity.space_id else None,
            repository_id=str(entity.repository_id) if entity.repository_id else None,
            provenance=provenance,
            superseded_hint=_superseded_hint(entity.id, ver),
        )

    return await sync_to_async(_build)()


async def hydrate_many(
    keys: list[tuple[uuid.UUID, int]],
    *,
    include_superseded: bool = False,
) -> dict[tuple[uuid.UUID, int], EntityMetadata]:
    """批量 hydrate，减少 N+1。"""
    if not keys:
        return {}

    entity_ids = {eid for eid, _ in keys}
    versions = await sync_to_async(list)(
        KnowledgeEntityVersion.objects.select_related(
            "entity", "entity__space", "entity__repository"
        ).filter(entity_id__in=entity_ids)
    )
    by_key = {(v.entity_id, v.version): v for v in versions}
    out: dict[tuple[uuid.UUID, int], EntityMetadata] = {}
    for key in keys:
        ver = by_key.get(key)
        if ver is None:
            continue
        if not include_superseded and not ver.is_latest:
            continue
        entity = ver.entity

        def _build_one(v=ver, ent=entity) -> EntityMetadata:
            return EntityMetadata(
                entity_id=ent.id,
                entity_kind=ent.kind,
                version=v.version,
                title=ent.title,
                valid_at=v.valid_at,
                invalid_at=v.invalid_at,
                source_kind=ent.source_kind,
                source_id=ent.source_id,
                origin=ent.origin,
                event_time=v.event_time,
                space_id=str(ent.space_id) if ent.space_id else None,
                repository_id=str(ent.repository_id) if ent.repository_id else None,
                provenance=_build_provenance(ent, v),
                superseded_hint=_superseded_hint(ent.id, v),
            )

        out[key] = await sync_to_async(_build_one)()
    return out
