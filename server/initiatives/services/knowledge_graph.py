"""ProjectKnowledgeGraphService —— 项目纳入交付知识图谱 + KLINK 边（KLINK-01/02）。

复用既有 ``KnowledgeEntity`` / ``KnowledgeEdge`` 脊柱，**不另起炉灶**：

- 把 ``Project`` / ``Repository`` / ``Space`` 投影为知识图谱**参考节点**
  （``KnowledgeEntity``，``kind=project/repository/space``，无内容版本、不进向量/召回，
  仅作图节点）。本 service 是 PROJECT/REPOSITORY/SPACE 三类参考节点的**唯一写者**。
- 项目↔知识（KLINK-01）/ 项目↔仓库/空间/项目（KLINK-02）的边全部经 ``graph_store``
  （边唯一写者，幂等可重入）建模、查询。

设计纪律：
- **不与 Phase 77/78 操作态表双写**——``ProjectRelation`` / ``ProjectWorkItemLink`` /
  ``Project.space`` FK 仍是操作态源；KnowledgeEdge 由本 service 单向派生/补建，
  作为统一可查询/可视图层。``sync_relations_from_operational`` 从操作态补建边。
- 查询用 ``direction="both"``——边方向（项目→知识 / 工件→项目）不敏感于"列出项目全部关联"。
- 边幂等：``add_edge`` 前先 ``neighbors`` 去重，``IntegrityError`` 视为并发已建（warning 放弃）。
- async ORM 经 ``sync_to_async``；``valid_at`` 用 aware ``timezone.now()``（P2 防线）。
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.utils import timezone

from audit.services import taxonomy
from audit.services.audit_service import AuditService
from knowledge.graph_store import graph_store
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEntity,
    generate_entity_id,
)

logger = structlog.get_logger(__name__)

__all__ = ["ProjectKnowledgeGraphService", "ProjectGraphError"]

_COMPONENT = "initiatives"


class ProjectGraphError(Exception):
    """项目图谱操作非法（如关联不存在的知识实体，API 层转 400/404）。"""


def project_node_id(project_id: Any) -> uuid.UUID:
    """项目图谱节点 id（``generate_entity_id("project","project",id)`` 派生唯一入口）。"""
    return generate_entity_id(EntityKind.PROJECT, "project", str(project_id))


def repository_node_id(repository_id: Any) -> uuid.UUID:
    return generate_entity_id(EntityKind.REPOSITORY, "repository", str(repository_id))


def space_node_id(space_id: Any) -> uuid.UUID:
    return generate_entity_id(EntityKind.SPACE, "space", str(space_id))


class ProjectKnowledgeGraphService:
    """项目知识图谱节点 + KLINK 边唯一写入/查询入口。"""

    # ---- 参考节点（PROJECT/REPOSITORY/SPACE，本 service 唯一写者）----

    @sync_to_async
    def ensure_project_node(self, project: Any) -> uuid.UUID:
        """确保项目图谱节点存在（幂等 get_or_create，无内容版本）。"""
        node_id = project_node_id(project.id)
        KnowledgeEntity.objects.get_or_create(
            id=node_id,
            defaults={
                "kind": EntityKind.PROJECT,
                "origin": EntityOrigin.PROJECT,
                "source_kind": "project",
                "source_id": str(project.id),
                "title": (project.name or str(project.id))[:500],
                "space_id": getattr(project, "space_id", None),
                "event_time": timezone.now(),
            },
        )
        return node_id

    @sync_to_async
    def ensure_repository_node(self, repository: Any) -> uuid.UUID:
        node_id = repository_node_id(repository.id)
        title = (
            getattr(repository, "name", None)
            or getattr(repository, "full_name", None)
            or str(repository.id)
        )
        KnowledgeEntity.objects.get_or_create(
            id=node_id,
            defaults={
                "kind": EntityKind.REPOSITORY,
                "origin": EntityOrigin.PROJECT,
                "source_kind": "repository",
                "source_id": str(repository.id),
                "title": str(title)[:500],
                "repository_id": repository.id,
                "event_time": timezone.now(),
            },
        )
        return node_id

    @sync_to_async
    def ensure_space_node(self, space: Any) -> uuid.UUID:
        node_id = space_node_id(space.id)
        KnowledgeEntity.objects.get_or_create(
            id=node_id,
            defaults={
                "kind": EntityKind.SPACE,
                "origin": EntityOrigin.PROJECT,
                "source_kind": "space",
                "source_id": str(space.id),
                "title": (getattr(space, "name", None) or str(space.id))[:500],
                "space_id": space.id,
                "event_time": timezone.now(),
            },
        )
        return node_id

    # ---- KLINK 边（经 graph_store，幂等）----

    async def _add_edge_idempotent(
        self,
        *,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation: str,
        metadata: dict | None = None,
    ) -> bool:
        """幂等建边：已有同 target 活跃出边 → 跳过（``metadata`` 非空则覆盖）；
        并发撞约束 → warning 放弃。

        Returns:
            True 表示新建了边，False 表示已存在（或已 upsert metadata）/并发放弃。
        """
        existing = await graph_store.neighbors(source_id, relations=[relation], direction="out")
        hit = next((e for e in existing if e.target_id == target_id), None)
        if hit is not None:
            # 幂等 upsert：活跃边已存在。传入 metadata → 覆盖为最新（KDEP-08）；
            # 既有无 metadata 调用路径行为不变（继续跳过）。
            if metadata is not None:
                await graph_store.update_edge_metadata(hit.edge_id, metadata=metadata)
            return False
        try:
            await graph_store.add_edge(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                valid_at=timezone.now(),
                metadata=metadata,
            )
            return True
        except IntegrityError as exc:
            logger.warning(
                "project_graph_edge_conflict",
                source_id=str(source_id),
                target_id=str(target_id),
                relation=relation,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def link_knowledge(
        self,
        *,
        project: Any,
        entity_id: uuid.UUID,
        relation: str = EdgeRelation.REFERENCES,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """KLINK-01：把一个已存在的知识实体关联到项目（项目→知识 出边）。

        ``entity_id`` 必须是既有 ``KnowledgeEntity``，否则 ``ProjectGraphError``。
        """
        if not await KnowledgeEntity.objects.filter(id=entity_id).aexists():
            raise ProjectGraphError(f"知识实体 {entity_id} 不存在")
        node_id = await self.ensure_project_node(project)
        created = await self._add_edge_idempotent(
            source_id=node_id, target_id=entity_id, relation=relation
        )
        if created:
            await self._emit_linked(
                project=project,
                target_kind="knowledge",
                target_id=entity_id,
                relation=relation,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            )
        return created

    async def link_project(
        self,
        *,
        project: Any,
        other_project: Any,
        relation: str = EdgeRelation.RELATES_TO,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """KLINK-02：项目↔项目（图层）。"""
        node_id = await self.ensure_project_node(project)
        other_id = await self.ensure_project_node(other_project)
        created = await self._add_edge_idempotent(
            source_id=node_id, target_id=other_id, relation=relation
        )
        if created:
            await self._emit_linked(
                project=project,
                target_kind="project",
                target_id=other_id,
                relation=relation,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            )
        return created

    async def link_repository(
        self,
        *,
        project: Any,
        repository: Any,
        relation: str = EdgeRelation.RELATES_TO,
        metadata: dict | None = None,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """KLINK-02 / KDEP-08：项目↔仓库（图层）。

        ``metadata`` 非空时透传（首建写入 / 已存在则 upsert 覆盖），承载
        ``source/association_id/score/confidence/matched_node_paths``（verified 关联派生）。
        """
        node_id = await self.ensure_project_node(project)
        repo_id = await self.ensure_repository_node(repository)
        created = await self._add_edge_idempotent(
            source_id=node_id, target_id=repo_id, relation=relation, metadata=metadata
        )
        if created:
            await self._emit_linked(
                project=project,
                target_kind="repository",
                target_id=repo_id,
                relation=relation,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            )
        return created

    async def unlink_repository(
        self,
        *,
        project: Any,
        repository: Any,
        relation: str = EdgeRelation.RELATES_TO,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """KDEP-08：失效项目→仓库派生边（真相源离开 verified → 派生边失效置位）。

        定位 project→repo 活跃 ``RELATES_TO`` 出边并逐条 ``invalidate_edge`` 失效置位
        （单向派生一致性）；无匹配活跃边 → 幂等 no-op 返回 ``False``。

        Returns:
            True 表示失效了至少一条边，False 表示无活跃边（幂等 no-op）。
        """
        node_id = await self.ensure_project_node(project)
        repo_id = repository_node_id(repository.id)
        existing = await graph_store.neighbors(node_id, relations=[relation], direction="out")
        invalidated = False
        for edge in existing:
            if edge.target_id == repo_id:
                await graph_store.invalidate_edge(edge.edge_id, invalid_at=timezone.now())
                invalidated = True
        if invalidated:
            logger.info(
                "project_graph_repository_unlinked",
                project_id=str(getattr(project, "id", project)),
                repository_id=str(repository.id),
                relation=relation,
                initiated_by_user_id=str(initiated_by_user_id) if initiated_by_user_id else "system",
                component=_COMPONENT,
                category="caller",
            )
        return invalidated

    async def link_space(
        self,
        *,
        project: Any,
        space: Any,
        relation: str = EdgeRelation.RELATES_TO,
        actor: Any = None,
        initiated_by_user_id: Any = None,
    ) -> bool:
        """KLINK-02：项目↔空间（图层）。"""
        node_id = await self.ensure_project_node(project)
        space_id = await self.ensure_space_node(space)
        created = await self._add_edge_idempotent(
            source_id=node_id, target_id=space_id, relation=relation
        )
        if created:
            await self._emit_linked(
                project=project,
                target_kind="space",
                target_id=space_id,
                relation=relation,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            )
        return created

    async def sync_relations_from_operational(
        self, *, project: Any, actor: Any = None, initiated_by_user_id: Any = None
    ) -> int:
        """从 Phase 77/78 操作态表单向派生 KLINK 边（不双写，幂等补建）。

        - ``Project.space`` FK → 项目↔空间边；
        - ``ProjectRelation``（related_projects）→ 项目↔项目边；
        - ``RepoAssociation(status=verified)`` → 项目↔仓库边（KDEP-08，单向派生，
          metadata 携 source=repo_association 等；RepoAssociation 只读、不双写真相源）。

        Returns:
            新建的边数。
        """
        created = 0
        space = await sync_to_async(lambda: project.space)()
        if space is not None and await self.link_space(
            project=project, space=space, actor=actor, initiated_by_user_id=initiated_by_user_id
        ):
            created += 1

        related = await sync_to_async(
            lambda: list(project.related_projects.all())
        )()
        for other in related:
            if await self.link_project(
                project=project,
                other_project=other,
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            ):
                created += 1

        # KDEP-08：verified RepoAssociation 单向派生项目→仓库边（真相源只读）。
        # 延迟 import 避免 initiatives 内循环依赖（参照 repo_association_service 写法）。
        from initiatives.models import RepoAssociation, RepoAssociationStatus

        verified_assocs = await sync_to_async(
            lambda: list(
                RepoAssociation.objects.filter(
                    project=project, status=RepoAssociationStatus.VERIFIED
                ).select_related("repository")
            )
        )()
        verified_repo_edges = 0
        for assoc in verified_assocs:
            if await self.link_repository(
                project=project,
                repository=assoc.repository,
                metadata=self._association_edge_metadata(assoc),
                actor=actor,
                initiated_by_user_id=initiated_by_user_id,
            ):
                verified_repo_edges += 1
        created += verified_repo_edges

        logger.info(
            "project_graph_synced_from_operational",
            project_id=str(project.id),
            edges_created=created,
            verified_repo_edges=verified_repo_edges,
            component=_COMPONENT,
            category="caller",
        )
        return created

    @staticmethod
    def _association_edge_metadata(assoc: Any) -> dict:
        """从 RepoAssociation 组装派生边 metadata（KDEP-08 契约）。"""
        return {
            "source": "repo_association",
            "association_id": str(assoc.id),
            "score": float(assoc.score or 0.0),
            "confidence": assoc.confidence or "",
            "matched_node_paths": list(assoc.matched_node_paths or []),
        }

    # ---- 查询（KLINK-02 可查询）----

    async def query_graph(
        self,
        *,
        project: Any,
        relations: list[str] | None = None,
        direction: str = "both",
        max_hops: int = 1,
    ) -> list[dict[str, Any]]:
        """查询项目在交付知识图谱中的关联（KLINK-02）。

        ``direction="both"`` 列出项目全部关联（项目→知识/项目/仓库/空间 出边 +
        工件→项目 入边）。``max_hops>1`` 走多跳遍历（仅返回实体 id + 跳数）。
        """
        node_id = await self.ensure_project_node(project)
        if max_hops > 1:
            results = await graph_store.traverse(
                node_id, max_hops=max_hops, relations=relations, direction=direction
            )
            entity_ids = [r.entity_id for r in results]
            metas = await self._hydrate_nodes(entity_ids)
            depth_by_id = {r.entity_id: r.depth for r in results}
            return [{**metas[eid], "depth": depth_by_id.get(eid, 1)} for eid in entity_ids if eid in metas]

        edges = await graph_store.neighbors(node_id, relations=relations, direction=direction)
        # 收集对端实体 id（排除起点本身）。
        target_ids: list[uuid.UUID] = []
        edge_meta: list[tuple[uuid.UUID, str]] = []  # (对端 id, relation)
        for e in edges:
            other = e.target_id if e.source_id == node_id else e.source_id
            if other is None or other == node_id:
                continue
            target_ids.append(other)
            edge_meta.append((other, e.relation))
        metas = await self._hydrate_nodes(target_ids)
        out: list[dict[str, Any]] = []
        for other, relation in edge_meta:
            meta = metas.get(other)
            if meta is None:
                continue
            out.append({**meta, "relation": relation})
        return out

    async def _hydrate_nodes(
        self, entity_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """批量取实体节点元信息（kind/title/source_kind/source_id）。"""
        if not entity_ids:
            return {}
        result: dict[uuid.UUID, dict[str, Any]] = {}
        async for ent in KnowledgeEntity.objects.filter(id__in=entity_ids):
            result[ent.id] = {
                "entity_id": str(ent.id),
                "kind": ent.kind,
                "title": ent.title,
                "source_kind": ent.source_kind,
                "source_id": ent.source_id,
            }
        return result

    async def _emit_linked(
        self,
        *,
        project: Any,
        target_kind: str,
        target_id: uuid.UUID,
        relation: str,
        actor: Any,
        initiated_by_user_id: Any,
    ) -> None:
        actor_id = initiated_by_user_id or getattr(actor, "id", None)
        await AuditService.aemit(
            action=taxonomy.ACTION_PROJECT_KNOWLEDGE_LINKED,
            actor=actor,
            target_type="project",
            target_id=getattr(project, "id", project),
            target_repr=getattr(project, "name", str(getattr(project, "id", project))),
            after={
                "target_kind": target_kind,
                "target_entity_id": str(target_id),
                "relation": relation,
            },
            metadata={
                "component": _COMPONENT,
                "category": "caller",
                "initiated_by_user_id": str(actor_id) if actor_id else "system",
            },
            source="api",
        )
