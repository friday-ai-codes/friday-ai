"""ProjectKnowledgeGraphService 守护测试：KLINK-01（项目↔知识）+ KLINK-02（项目↔仓库/空间/项目）。"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import Project
from initiatives.services.knowledge_graph import (
    ProjectGraphError,
    ProjectKnowledgeGraphService,
    project_node_id,
)
from knowledge.models import (
    EntityKind,
    EntityOrigin,
    KnowledgeEntity,
    generate_entity_id,
)
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_space(key="kg") -> Space:
    return Space.objects.create(name="S", feishu_project_key=f"kg-{key}")


@sync_to_async
def _make_project(space, name="P") -> Project:
    return Project.objects.create(space=space, name=name, feishu_project_key="")


@sync_to_async
def _make_repo() -> Repository:
    return Repository.objects.create(name="repo", git_url="https://x/repo.git")


@sync_to_async
def _make_knowledge_entity() -> KnowledgeEntity:
    sid = uuid.uuid4().hex
    return KnowledgeEntity.objects.create(
        id=generate_entity_id(EntityKind.DOCUMENT, "feishu_document", sid),
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.FEISHU,
        source_kind="feishu_document",
        source_id=sid,
        title="知识",
        event_time=timezone.now(),
    )


async def test_link_knowledge_creates_edge_and_query() -> None:
    svc = ProjectKnowledgeGraphService()
    space = await _make_space("k1")
    project = await _make_project(space)
    entity = await _make_knowledge_entity()

    created = await svc.link_knowledge(project=project, entity_id=entity.id)
    assert created is True
    # 项目图谱节点已建
    assert await KnowledgeEntity.objects.filter(
        id=project_node_id(project.id), kind=EntityKind.PROJECT
    ).aexists()
    # 查询可见知识关联（direction=both）
    nodes = await svc.query_graph(project=project)
    entity_ids = {n["entity_id"] for n in nodes}
    assert str(entity.id) in entity_ids
    # 审计
    assert await AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_KNOWLEDGE_LINKED
    ).aexists()


async def test_link_knowledge_idempotent() -> None:
    svc = ProjectKnowledgeGraphService()
    space = await _make_space("k2")
    project = await _make_project(space)
    entity = await _make_knowledge_entity()
    assert await svc.link_knowledge(project=project, entity_id=entity.id) is True
    assert await svc.link_knowledge(project=project, entity_id=entity.id) is False


async def test_link_knowledge_missing_entity_raises() -> None:
    svc = ProjectKnowledgeGraphService()
    space = await _make_space("k3")
    project = await _make_project(space)
    with pytest.raises(ProjectGraphError):
        await svc.link_knowledge(project=project, entity_id=uuid.uuid4())


async def test_link_space_and_project_and_repo() -> None:
    svc = ProjectKnowledgeGraphService()
    space = await _make_space("k4")
    project = await _make_project(space, name="A")
    other = await _make_project(space, name="B")
    repo = await _make_repo()

    assert await svc.link_space(project=project, space=space) is True
    assert await svc.link_project(project=project, other_project=other) is True
    assert await svc.link_repository(project=project, repository=repo) is True

    nodes = await svc.query_graph(project=project)
    kinds = {n["kind"] for n in nodes}
    assert {EntityKind.SPACE, EntityKind.PROJECT, EntityKind.REPOSITORY} <= kinds


async def test_sync_relations_from_operational() -> None:
    svc = ProjectKnowledgeGraphService()
    space = await _make_space("k5")
    project = await _make_project(space)
    created = await svc.sync_relations_from_operational(project=project)
    # 至少派生出项目↔空间边
    assert created >= 1
    nodes = await svc.query_graph(project=project)
    assert any(n["kind"] == EntityKind.SPACE for n in nodes)
