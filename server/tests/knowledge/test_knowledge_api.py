"""Knowledge JWT REST API 测试（Phase 16-05）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from knowledge.models import EntityKind
from knowledge.retrieval_types import TimelineNodeDTO

pytestmark = pytest.mark.django_db


def test_entity_detail_ok(entity_factory, version_factory, project, user, project_memberships, authenticated_client):
    entity = entity_factory(space=project, kind=EntityKind.WORK_ITEM)
    version_factory(entity, version=1, content="需求正文")
    resp = authenticated_client.get(f"/api/knowledge/entities/{entity.id}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity_id"] == str(entity.id)
    assert body["kind"] == EntityKind.WORK_ITEM
    assert "provenance" in body


def test_entity_other_user_404(other_user, entity_factory, version_factory, project):
    from rest_framework.test import APIClient

    entity = entity_factory(space=project)
    version_factory(entity)
    client = APIClient()
    client.force_authenticate(user=other_user)
    resp = client.get(f"/api/knowledge/entities/{entity.id}/")
    assert resp.status_code == 404


def test_invalid_as_of_400(authenticated_client):
    resp = authenticated_client.get(
        f"/api/knowledge/entities/{uuid.uuid4()}/",
        {"as_of": "invalid"},
    )
    assert resp.status_code == 400


def test_timeline_as_of_passthrough(entity_factory, version_factory, project, user, project_memberships, authenticated_client):
    entity = entity_factory(space=project)
    version_factory(entity)
    with patch(
        "knowledge.api.views._service.get_timeline",
        new=AsyncMock(return_value=[TimelineNodeDTO(
            entity_id=entity.id,
            version=1,
            kind=entity.kind,
            title=entity.title,
            summary="s",
            valid_at=None,
            invalid_at=None,
            event_time=None,
        )]),
    ) as mock_tl:
        resp = authenticated_client.get(
            f"/api/knowledge/timeline/{entity.id}/",
            {"as_of": "2026-05-01T00:00:00+08:00"},
        )
    assert resp.status_code == 200
    assert mock_tl.await_args.kwargs["as_of"] is not None


# ---- KDEP-02：工件命中搜索结果携带元数据 + access_scope 越权守护 ----


def test_search_artifact_hit_carries_metadata(
    entity_factory, version_factory, project, user, project_memberships, authenticated_client
):
    """origin=artifact 命中 → 结果项携带工件类型名/载体/url/artifact_id/所属项目名。"""
    import uuid as _uuid

    from initiatives.models import ArtifactType
    from initiatives.models import Project as InitiativeProject
    from knowledge.models import EntityKind, EntityOrigin
    from knowledge.vector_recall import VectorHit

    iproject = InitiativeProject.objects.create(
        space=project, name="需求项目", feishu_project_key=""
    )
    ArtifactType.objects.create(key="prd", name="PRD", carrier="markdown", ragable=True)
    artifact_id = str(_uuid.uuid4())
    entity = entity_factory(
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.ARTIFACT,
        source_kind="artifact",
        source_id=artifact_id,
        space=project,
        title="PRD 文档",
    )
    payload = {
        "artifact_id": artifact_id,
        "project_id": str(iproject.id),
        "type": "prd",
        "carrier": "markdown",
        "url": "https://x.feishu.cn/docx/tok",
        "version": 1,
    }
    version_factory(entity, version=1, content="PRD 正文", payload=payload)

    hit = VectorHit(
        point_id=str(_uuid.uuid4()),
        entity_id=entity.id,
        entity_kind=EntityKind.DOCUMENT,
        version=1,
        score=0.9,
        rrf_score=0.9,
        payload=payload,
    )
    with patch(
        "knowledge.retrieval.recall_similar_chunks", new=AsyncMock(return_value=[hit])
    ) as mock_recall:
        resp = authenticated_client.get("/api/knowledge/search/", {"q": "PRD"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert item["origin"] == "artifact"
    assert item["source_kind"] == "artifact"
    assert item["artifact"]["type_name"] == "PRD"
    assert item["artifact"]["type_key"] == "prd"
    assert item["artifact"]["carrier"] == "markdown"
    assert item["artifact"]["artifact_id"] == artifact_id
    assert item["artifact"]["url"] == "https://x.feishu.cn/docx/tok"
    assert item["artifact"]["project_name"] == "需求项目"
    # access_scope 收口：recall 在当前用户可见 Space 内检索（document 召回不放宽权限闸）
    assert mock_recall.await_args.kwargs["include_document_kind"] is True
    assert str(project.id) in mock_recall.await_args.kwargs["allowed_project_ids"]


def test_search_non_member_no_visible_artifacts(other_user):
    """越权：非任何项目成员 → 无可见 project，搜索返回空（access_scope fail-closed）。"""
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=other_user)
    with patch(
        "knowledge.retrieval.recall_similar_chunks",
        new=AsyncMock(side_effect=AssertionError("越权用户不应触达向量召回")),
    ):
        resp = client.get("/api/knowledge/search/", {"q": "PRD"})
    assert resp.status_code == 200
    assert resp.json() == []
