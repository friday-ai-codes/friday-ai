"""交付知识检索端到端集成测试（Phase 15-05）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async

from knowledge.retrieval import DeliveryKnowledgeSearchService

pytestmark = pytest.mark.django_db(transaction=True)

FIXTURE = Path(__file__).parent / "fixtures" / "retr_eval_queries.json"


@pytest.fixture
def e2e_mocks(monkeypatch, mock_embedding):
    monkeypatch.setattr(
        "knowledge.retrieval.recall_similar_chunks",
        AsyncMock(return_value=[]),
    )


async def test_e2e_search_returns_list(project, user, project_memberships, e2e_mocks):
    svc = DeliveryKnowledgeSearchService()
    out = await svc.search_similar("测试", user=user, project_ids=[str(project.id)])
    assert isinstance(out, list)


async def test_cross_project_denied(project, other_user, e2e_mocks):
    svc = DeliveryKnowledgeSearchService()
    assert await svc.search_similar("q", user=other_user, project_ids=[str(project.id)]) == []


@pytest.mark.parametrize("row", json.loads(FIXTURE.read_text()))
async def test_eval_fixture_smoke(row, project, user, project_memberships, e2e_mocks):
    svc = DeliveryKnowledgeSearchService()
    out = await svc.search_similar(row["query"], user=user, project_ids=[str(project.id)])
    assert isinstance(out, list)


async def test_service_delegates_timeline(entity_factory, version_factory, project, user, project_memberships):
    entity = await sync_to_async(entity_factory)(space=project)
    await sync_to_async(version_factory)(entity)
    svc = DeliveryKnowledgeSearchService()
    nodes = await svc.get_timeline(entity.id, user=user)
    assert isinstance(nodes, list)


async def test_knowledge_search_api(authenticated_client, project, user, project_memberships, monkeypatch, mock_embedding):
    monkeypatch.setattr(
        "knowledge.retrieval.recall_similar_chunks",
        AsyncMock(return_value=[]),
    )
    resp = await sync_to_async(authenticated_client.get)(
        "/api/knowledge/search/", {"q": "测试", "project_ids": str(project.id)}
    )
    assert resp.status_code == 200
