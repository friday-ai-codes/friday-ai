"""工件↔仓库/能力/关键词双向查询服务（Phase 98-03，KDEP-09）。

查询全部经 ``graph_store.neighbors`` 单跳收口（不裸写遍历 SQL），关键词/能力从边
``metadata`` 读取（不查实体表，research §2.4）。所有查询强制 ``access_scope`` fail-closed：
越权工件/仓库不可见，无可见范围返回空结构。查询/补全异常 best-effort 捕获返回空，绝不反噬请求。

契约（98-01/98-02 建立）：``artifact→repo`` / ``project→repo`` ``KnowledgeEdge(RELATES_TO)``，
``metadata`` 含 ``source``（"artifact"）/``node_paths``/``keywords``/``score`` 等。本服务正向/反向
查询仅认 ``metadata.source=="artifact"`` 的工件路由边。

观测：``artifact_associations_queried``（category=caller, component=knowledge, +方向/命中数/duration_ms）；
异常 ``artifact_associations_query_failed`` warning。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from knowledge.access_scope import resolve_allowed_project_ids, resolve_allowed_repository_ids
from knowledge.graph_store import graph_store
from knowledge.models import EdgeRelation, EntityKind, KnowledgeEntity, generate_entity_id

logger = structlog.get_logger(__name__)

__all__ = ["ArtifactAssociationService"]

_COMPONENT = "knowledge"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        text = str(v)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _capability_matches(node_paths: list[str], capability_path: str) -> bool:
    """capability_path 命中 node_paths：成员相等 或 前缀关系（任一方向）。"""
    target = str(capability_path).strip()
    if not target:
        return True
    for path in node_paths or []:
        p = str(path)
        if p == target or p.startswith(target) or target.startswith(p):
            return True
    return False


class ArtifactAssociationService:
    """无状态双向关联查询服务（供 API 层与 Phase 99 复用）。"""

    async def get_artifact_associations(
        self, artifact_id: Any, *, user
    ) -> dict | None:
        """正向：给定工件 → 相关仓库 / 能力(node_paths) / 关键词。

        工件不可见（space 不在 allowed）→ 返回 ``None``（端点转 404）。可见则遍历该
        document 实体的 ``RELATES_TO`` 出边（``metadata.source=="artifact"``），返回
        ``{repositories:[{repository_id, repo_name, node_paths, keywords, score}],
        capabilities:[去重 node_paths], keywords:[去重 keywords]}``。
        """
        started = time.perf_counter()
        try:
            entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact_id))
            entity = await KnowledgeEntity.objects.filter(id=entity_id).afirst()
            if entity is None or entity.space_id is None:
                return None
            allowed = await resolve_allowed_project_ids(user)
            if str(entity.space_id) not in allowed:
                return None

            edges = await graph_store.neighbors(
                entity_id, relations=[EdgeRelation.RELATES_TO], direction="out"
            )
            repo_edges = [
                e
                for e in edges
                if isinstance(e.metadata, dict)
                and e.metadata.get("source") == "artifact"
                and e.target_id is not None
            ]
            repo_titles = await self._hydrate_repo_titles(
                [e.target_id for e in repo_edges]
            )

            repositories: list[dict] = []
            all_node_paths: list[str] = []
            all_keywords: list[str] = []
            for e in repo_edges:
                meta = e.metadata
                node_paths = list(meta.get("node_paths") or [])
                keywords = list(meta.get("keywords") or [])
                all_node_paths.extend(node_paths)
                all_keywords.extend(keywords)
                repo_meta = repo_titles.get(e.target_id, {})
                repositories.append(
                    {
                        "repository_id": repo_meta.get("source_id"),
                        "repo_name": repo_meta.get("title"),
                        "node_paths": node_paths,
                        "keywords": keywords,
                        "score": meta.get("score"),
                    }
                )

            result = {
                "repositories": repositories,
                "capabilities": _dedupe_preserve_order(all_node_paths),
                "keywords": _dedupe_preserve_order(all_keywords),
            }
            logger.info(
                "artifact_associations_queried",
                direction="forward",
                artifact_id=str(artifact_id),
                repo_count=len(repositories),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return result
        except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬请求
            logger.warning(
                "artifact_associations_query_failed",
                direction="forward",
                artifact_id=str(artifact_id),
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return None

    async def find_artifacts_by_repository(
        self,
        repository_id: Any,
        *,
        user,
        capability_path: str | None = None,
        keyword: str | None = None,
    ) -> list[dict]:
        """反向（仓库锚）：给定仓库 → 相关工件（可按 capability_path / keyword 过滤）。

        仓库不可见 → ``[]``。可见则遍历 repo 节点 ``RELATES_TO`` 入边
        （``metadata.source=="artifact"``），补全工件标题/类型/project 并按其 space
        二次 access_scope 过滤（fail-closed 双维）。
        """
        started = time.perf_counter()
        try:
            allowed_repos = await resolve_allowed_repository_ids(user, [str(repository_id)])
            if not allowed_repos:
                return []

            repo_node = generate_entity_id(
                EntityKind.REPOSITORY, "repository", str(repository_id)
            )
            edges = await graph_store.neighbors(
                repo_node, relations=[EdgeRelation.RELATES_TO], direction="in"
            )
            matched: list[tuple[uuid.UUID, dict]] = []
            for e in edges:
                meta = e.metadata
                if not isinstance(meta, dict) or meta.get("source") != "artifact":
                    continue
                if e.source_id is None:
                    continue
                node_paths = list(meta.get("node_paths") or [])
                if capability_path and not _capability_matches(node_paths, capability_path):
                    continue
                if keyword and keyword not in list(meta.get("keywords") or []):
                    continue
                matched.append((e.source_id, meta))

            if not matched:
                return []

            # source 实体 → artifact document → 补全 Artifact，按 space 二次过滤（fail-closed）。
            allowed_spaces = await resolve_allowed_project_ids(user)
            if not allowed_spaces:
                return []
            entity_ids = [eid for eid, _ in matched]
            artifact_meta = await self._hydrate_artifacts(entity_ids, allowed_spaces)

            results: list[dict] = []
            for eid, meta in matched:
                info = artifact_meta.get(eid)
                if info is None:
                    continue
                results.append(
                    {
                        **info,
                        "node_paths": list(meta.get("node_paths") or []),
                        "keywords": list(meta.get("keywords") or []),
                        "score": meta.get("score"),
                    }
                )
            logger.info(
                "artifact_associations_queried",
                direction="reverse_repository",
                repository_id=str(repository_id),
                artifact_count=len(results),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return results
        except Exception as exc:  # noqa: BLE001 — best-effort，绝不反噬请求
            logger.warning(
                "artifact_associations_query_failed",
                direction="reverse_repository",
                repository_id=str(repository_id),
                error=redact_secrets_in_text(str(exc)),
                error_type=type(exc).__name__,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                component=_COMPONENT,
                category="caller",
            )
            return []

    async def find_artifacts_by_capability(
        self, capability_path: str, *, user
    ) -> list[dict]:
        """反向（无仓库锚，能力）：在 user 可见仓库集合内逐仓过滤，聚合去重工件。"""
        return await self._find_artifacts_over_visible_repos(
            user=user, capability_path=capability_path, keyword=None
        )

    async def find_artifacts_by_keyword(self, keyword: str, *, user) -> list[dict]:
        """反向（无仓库锚，关键词）：在 user 可见仓库集合内逐仓过滤，聚合去重工件。"""
        return await self._find_artifacts_over_visible_repos(
            user=user, capability_path=None, keyword=keyword
        )

    async def _find_artifacts_over_visible_repos(
        self, *, user, capability_path: str | None, keyword: str | None
    ) -> list[dict]:
        allowed_repos = await resolve_allowed_repository_ids(user)
        if not allowed_repos:
            return []
        aggregated: dict[str, dict] = {}
        for rid in allowed_repos:
            rows = await self.find_artifacts_by_repository(
                rid, user=user, capability_path=capability_path, keyword=keyword
            )
            for row in rows:
                aggregated.setdefault(row["artifact_id"], row)
        return list(aggregated.values())

    async def _hydrate_repo_titles(
        self, entity_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict]:
        """批量取仓库图谱节点的 source_id（repository_id）/ title（repo_name）。"""
        if not entity_ids:
            return {}
        result: dict[uuid.UUID, dict] = {}
        async for ent in KnowledgeEntity.objects.filter(
            id__in=entity_ids, kind=EntityKind.REPOSITORY
        ):
            result[ent.id] = {"source_id": ent.source_id, "title": ent.title}
        return result

    @sync_to_async
    def _hydrate_artifacts(
        self, entity_ids: list[uuid.UUID], allowed_spaces: list[str]
    ) -> dict[uuid.UUID, dict]:
        """document 实体 → Artifact 元数据补全 + 二次 space access_scope 过滤（fail-closed）。

        同步实现（经 sync_to_async 调用）：先取 document 实体的 source_id（=artifact_id），
        再按 ``allowed_spaces``（``resolve_allowed_project_ids`` 产出的可见 space id）过滤
        Artifact，返回 ``{entity_id: {artifact_id,title,type_key,project_id,project_name}}``。
        """
        from initiatives.models import Artifact

        # document 实体 → artifact_id 映射（source_kind=artifact）。
        entities = {
            ent.id: ent.source_id
            for ent in KnowledgeEntity.objects.filter(
                id__in=entity_ids, kind=EntityKind.DOCUMENT, source_kind="artifact"
            )
        }
        if not entities:
            return {}

        artifact_ids = list(entities.values())
        artifacts_qs = (
            Artifact.objects.filter(id__in=artifact_ids)
            .filter(project__space_id__in=allowed_spaces)
            .select_related("type", "project")
        )
        artifacts = {str(a.id): a for a in artifacts_qs}

        result: dict[uuid.UUID, dict] = {}
        for entity_id, artifact_id in entities.items():
            a = artifacts.get(str(artifact_id))
            if a is None:
                continue
            result[entity_id] = {
                "artifact_id": str(a.id),
                "title": a.title,
                "type_key": a.type.key,
                "project_id": str(a.project_id),
                "project_name": a.project.name,
            }
        return result
