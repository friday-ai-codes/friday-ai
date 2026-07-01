"""PG metadata 出处补全（Phase 15-02 RETR-06）。"""

from __future__ import annotations

import uuid

from asgiref.sync import sync_to_async

from knowledge.models import CodeChangeArchive, EntityKind, EntityOrigin, KnowledgeEntityVersion
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks

__all__ = ["hydrate_entity_metadata", "hydrate_many"]


def _resolve_artifact_maps(
    type_keys: set[str], project_ids: set[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """批量解析工件类型名 + 所属项目名映射（sync 内调用，跨 app 惰性导入避免循环依赖）。

    KDEP-02：origin=artifact 命中项的 ``type_name`` / ``project_name`` 补全。
    ``type_keys`` 空 / ``project_ids`` 空时对应映射为空 dict（fail-soft）。
    """
    from initiatives.models import ArtifactType, Project

    type_name_map: dict[str, str] = {}
    if type_keys:
        type_name_map = {
            str(key): name
            for key, name in ArtifactType.objects.filter(key__in=type_keys).values_list(
                "key", "name"
            )
        }
    project_name_map: dict[str, str] = {}
    if project_ids:
        project_name_map = {
            str(pid): name
            for pid, name in Project.objects.filter(id__in=project_ids).values_list("id", "name")
        }
    return type_name_map, project_name_map


def _build_artifact_meta(
    entity,
    payload,
    type_name_map: dict[str, str],
    project_name_map: dict[str, str],
) -> dict | None:
    """origin=artifact 命中 → 工件元数据 dict；否则 None（payload 缺字段 fail-soft 置 None）。"""
    if entity.origin != EntityOrigin.ARTIFACT:
        return None
    if not isinstance(payload, dict):
        return None
    type_key = payload.get("type")
    project_id = payload.get("project_id")
    return {
        "artifact_id": payload.get("artifact_id"),
        "type_key": type_key,
        "type_name": type_name_map.get(str(type_key)) if type_key else None,
        "carrier": payload.get("carrier"),
        "url": payload.get("url"),
        "project_id": project_id,
        "project_name": project_name_map.get(str(project_id)) if project_id else None,
    }


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
        artifact_meta = None
        if entity.origin == EntityOrigin.ARTIFACT:
            payload = ver.payload if isinstance(ver.payload, dict) else {}
            type_keys = {str(payload["type"])} if payload.get("type") else set()
            project_ids = {str(payload["project_id"])} if payload.get("project_id") else set()
            type_name_map, project_name_map = _resolve_artifact_maps(type_keys, project_ids)
            artifact_meta = _build_artifact_meta(entity, payload, type_name_map, project_name_map)
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
            artifact=artifact_meta,
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

    # 批量收集 origin=artifact 命中的 type_key / project_id，一次性解析映射（避免 N+1）。
    artifact_type_keys: set[str] = set()
    artifact_project_ids: set[str] = set()
    for v in versions:
        if v.entity.origin == EntityOrigin.ARTIFACT:
            payload = v.payload if isinstance(v.payload, dict) else {}
            if payload.get("type"):
                artifact_type_keys.add(str(payload["type"]))
            if payload.get("project_id"):
                artifact_project_ids.add(str(payload["project_id"]))
    type_name_map, project_name_map = await sync_to_async(_resolve_artifact_maps)(
        artifact_type_keys, artifact_project_ids
    )

    out: dict[tuple[uuid.UUID, int], EntityMetadata] = {}
    for key in keys:
        ver = by_key.get(key)
        if ver is None:
            continue
        if not include_superseded and not ver.is_latest:
            continue
        entity = ver.entity

        def _build_one(v=ver, ent=entity) -> EntityMetadata:
            artifact_meta = _build_artifact_meta(
                ent, v.payload, type_name_map, project_name_map
            )
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
                artifact=artifact_meta,
            )

        out[key] = await sync_to_async(_build_one)()
    return out
