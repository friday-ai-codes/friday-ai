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
