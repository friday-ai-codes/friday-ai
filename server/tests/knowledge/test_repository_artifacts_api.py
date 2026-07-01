"""RepositoryArtifactsView 反查端点测试（Phase 99-02，KDEP-11 反向支撑）。

- 已认证用户对可见仓库 GET → 200 + {artifacts:[...]}，每项带确定性 entity_id；
- 不可见/越权仓库 → 200 + 空列表（find_artifacts_by_repository fail-closed）；
- 未认证 → 401。
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from initiatives.models import Artifact, ArtifactType, ProjectVisibility
from initiatives.models import Project as InitiativeProject
from initiatives.services.knowledge_graph import repository_node_id
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEdge,
    KnowledgeEntity,
    generate_entity_id,
)

pytestmark = pytest.mark.django_db


def _build(space, repository):
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
    repo_node = KnowledgeEntity.objects.create(
        id=repository_node_id(repository.id),
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
            "source": "artifact",
            "artifact_id": str(artifact.id),
            "node_paths": ["backend/auth/login"],
            "keywords": ["login"],
            "score": 0.8,
        },
    )
    return artifact


def _url(repository_id) -> str:
    return f"/api/knowledge/repositories/{repository_id}/artifacts/"


def test_repository_artifacts_visible_returns_200_with_entity_id(
    project, repository, user, project_memberships, authenticated_client
):
    artifact = _build(project, repository)
    resp = authenticated_client.get(_url(repository.id))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["artifacts"]) == 1
    row = body["artifacts"][0]
    assert row["artifact_id"] == str(artifact.id)
    assert row["entity_id"] == str(
        generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    )
    assert row["node_paths"] == ["backend/auth/login"]


def test_repository_artifacts_invisible_returns_empty(project, repository, other_user):
    _build(project, repository)
    client = APIClient()
    client.force_authenticate(user=other_user)
    resp = client.get(_url(repository.id))
    assert resp.status_code == 200
    assert resp.json()["artifacts"] == []


def test_repository_artifacts_unauthenticated_returns_401(project, repository):
    _build(project, repository)
    resp = APIClient().get(_url(repository.id))
    assert resp.status_code == 401


def test_repository_artifacts_unknown_repo_returns_empty(user, authenticated_client):
    resp = authenticated_client.get(_url(uuid.uuid4()))
    assert resp.status_code == 200
    assert resp.json()["artifacts"] == []
