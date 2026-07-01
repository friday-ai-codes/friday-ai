"""ArtifactAssociationService 双向查询测试（Phase 98-03 Task 1，KDEP-09）。

- 正向 get_artifact_associations：读边 metadata 返回 repositories/capabilities/keywords；
  不可见工件返回 None（fail-closed）。
- 反向 find_artifacts_by_repository：给定仓库返回相关工件；capability/keyword 过滤；
  不可见仓库返回 []。
- find_artifacts_by_capability / find_artifacts_by_keyword：可见仓库集合内聚合去重。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from initiatives.models import Artifact, ArtifactType, ProjectVisibility
from initiatives.models import Project as InitiativeProject
from initiatives.services.knowledge_graph import repository_node_id
from knowledge.artifact_associations import ArtifactAssociationService
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEdge,
    KnowledgeEntity,
    generate_entity_id,
)

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _build(space, repository, *, source="artifact", node_paths=None, keywords=None, score=0.8):
    """建 Artifact + document 实体 + repository 节点 + artifact→repo RELATES_TO 边。"""
    node_paths = node_paths if node_paths is not None else ["backend/auth/login"]
    keywords = keywords if keywords is not None else ["login"]
    iproj = InitiativeProject.objects.create(
        space=space, name="项目A", feishu_project_key="", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    atype = ArtifactType.objects.create(key="prd", name="PRD", carrier="markdown", ragable=True)
    artifact = Artifact.objects.create(
        project=iproj, type=atype, carrier="markdown", title="登录方案", version=1
    )
    doc_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    doc = KnowledgeEntity.objects.create(
        id=doc_id,
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.ARTIFACT,
        source_kind="artifact",
        source_id=str(artifact.id),
        title="登录方案",
        space_id=space.id,
        event_time=timezone.now(),
    )
    repo_node_id = repository_node_id(repository.id)
    repo_node = KnowledgeEntity.objects.create(
        id=repo_node_id,
        kind=EntityKind.REPOSITORY,
        origin=EntityOrigin.PROJECT,
        source_kind="repository",
        source_id=str(repository.id),
        title=repository.name,
        repository_id=repository.id,
        event_time=timezone.now(),
    )
    KnowledgeEdge.objects.create(
        source_entity=doc,
        target_entity=repo_node,
        relation=EdgeRelation.RELATES_TO,
        valid_at=timezone.now(),
        metadata={
            "source": source,
            "artifact_id": str(artifact.id),
            "node_paths": node_paths,
            "keywords": keywords,
            "score": score,
        },
    )
    return artifact, iproj


async def test_forward_returns_repositories_capabilities_keywords(
    project, repository, user, project_memberships
):
    artifact, _ = await _build(
        project, repository, node_paths=["backend/auth/login", "web/ui"], keywords=["login", "ui"]
    )
    svc = ArtifactAssociationService()
    result = await svc.get_artifact_associations(artifact.id, user=user)

    assert result is not None
    assert len(result["repositories"]) == 1
    repo = result["repositories"][0]
    assert repo["repository_id"] == str(repository.id)
    assert repo["repo_name"] == repository.name
    assert repo["node_paths"] == ["backend/auth/login", "web/ui"]
    assert repo["score"] == 0.8
    assert result["capabilities"] == ["backend/auth/login", "web/ui"]
    assert result["keywords"] == ["login", "ui"]


async def test_forward_invisible_artifact_returns_none(project, repository, other_user):
    """other_user 无 membership → 工件不可见 → None（fail-closed）。"""
    artifact, _ = await _build(project, repository)
    result = await ArtifactAssociationService().get_artifact_associations(
        artifact.id, user=other_user
    )
    assert result is None


async def test_forward_missing_artifact_returns_none(user):
    result = await ArtifactAssociationService().get_artifact_associations(
        uuid.uuid4(), user=user
    )
    assert result is None


async def test_reverse_by_repository_returns_artifacts(
    project, repository, user, project_memberships
):
    artifact, iproj = await _build(project, repository)
    rows = await ArtifactAssociationService().find_artifacts_by_repository(
        repository.id, user=user
    )
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == str(artifact.id)
    assert rows[0]["title"] == "登录方案"
    assert rows[0]["type_key"] == "prd"
    assert rows[0]["project_id"] == str(iproj.id)


async def test_reverse_capability_filter(project, repository, user, project_memberships):
    artifact, _ = await _build(project, repository, node_paths=["backend/auth/login"])
    svc = ArtifactAssociationService()
    hit = await svc.find_artifacts_by_repository(
        repository.id, user=user, capability_path="backend/auth"
    )
    assert len(hit) == 1
    miss = await svc.find_artifacts_by_repository(
        repository.id, user=user, capability_path="frontend/xxx"
    )
    assert miss == []


async def test_reverse_keyword_filter(project, repository, user, project_memberships):
    await _build(project, repository, keywords=["login", "auth"])
    svc = ArtifactAssociationService()
    assert len(await svc.find_artifacts_by_repository(repository.id, user=user, keyword="login")) == 1
    assert await svc.find_artifacts_by_repository(repository.id, user=user, keyword="nope") == []


async def test_reverse_invisible_repository_returns_empty(project, repository, other_user):
    await _build(project, repository)
    rows = await ArtifactAssociationService().find_artifacts_by_repository(
        repository.id, user=other_user
    )
    assert rows == []


async def test_find_by_capability_over_visible_repos(
    project, repository, user, project_memberships
):
    artifact, _ = await _build(project, repository, node_paths=["backend/auth/login"])
    rows = await ArtifactAssociationService().find_artifacts_by_capability(
        "backend/auth", user=user
    )
    assert {r["artifact_id"] for r in rows} == {str(artifact.id)}


async def test_find_by_keyword_over_visible_repos(
    project, repository, user, project_memberships
):
    artifact, _ = await _build(project, repository, keywords=["login"])
    rows = await ArtifactAssociationService().find_artifacts_by_keyword("login", user=user)
    assert {r["artifact_id"] for r in rows} == {str(artifact.id)}


async def test_no_user_returns_empty(project, repository):
    await _build(project, repository)
    svc = ArtifactAssociationService()
    assert await svc.get_artifact_associations(uuid.uuid4(), user=None) is None
    assert await svc.find_artifacts_by_capability("x", user=None) == []
