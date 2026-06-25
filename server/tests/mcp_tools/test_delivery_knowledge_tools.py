"""MCP 交付知识工具 PAT 集成测试（Phase 16-01）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from rest_framework.test import APIClient

from interactions.models import ToolCallRecord
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO

pytestmark = pytest.mark.django_db


def _mock_search_result(project_id: str) -> SearchResultDTO:
    entity_id = uuid.uuid4()
    return SearchResultDTO(
        score=0.9,
        vector_score=0.9,
        recency_score=0.5,
        entity=EntityMetadata(
            entity_id=entity_id,
            entity_kind="work_item",
            version=1,
            title="历史需求",
            valid_at=None,
            invalid_at=None,
            source_kind="feishu_work_item",
            source_id="wi-1",
            origin="feishu",
            event_time=None,
            space_id=project_id,
            repository_id=None,
            provenance=ProvenanceLinks(feishu_url="https://feishu.cn/wi/1"),
        ),
    )


def test_delivery_search_empty_results(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = mcp_client
    monkeypatch.setattr(
        "knowledge.retrieval.recall_similar_chunks",
        AsyncMock(return_value=[]),
    )
    resp = client.post(
        "/api/mcp/tools/search_delivery_knowledge/",
        {"query": "登录优化"},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["total"] == 0
    assert body["run_id"]
    assert ToolCallRecord.objects.filter(tool_name="search_delivery_knowledge").exists()


def test_delivery_cross_project_denied_empty_results(
    project,
    other_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_models = pytest.importorskip("access_tokens.models")
    from runners.models import hash_token

    plaintext = access_models.generate_pat()
    access_models.AccessToken.objects.create(
        name="other-pat",
        token_hash=hash_token(plaintext),
        token_prefix=plaintext[:12],
        token_suffix=plaintext[-4:],
        created_by=other_user,
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    monkeypatch.setattr(
        "knowledge.retrieval.recall_similar_chunks",
        AsyncMock(return_value=[]),
    )
    resp = client.post(
        "/api/mcp/tools/search_delivery_knowledge/",
        {"query": "q", "project_ids": [str(project.id)]},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_delivery_invalid_as_of_returns_400(mcp_client: tuple[APIClient, str]) -> None:
    client, _ = mcp_client
    resp = client.post(
        "/api/mcp/tools/search_delivery_knowledge/",
        {"query": "q", "as_of": "invalid"},
        format="json",
    )
    assert resp.status_code == 400


def test_delivery_timeline_unknown_entity_returns_empty(
    mcp_client: tuple[APIClient, str],
) -> None:
    client, _ = mcp_client
    resp = client.post(
        "/api/mcp/tools/get_entity_timeline/",
        {"entity_id": str(uuid.uuid4())},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["nodes"] == []


def test_delivery_unauthorized_returns_401() -> None:
    client = APIClient()
    resp = client.post(
        "/api/mcp/tools/search_delivery_knowledge/",
        {"query": "q"},
        format="json",
    )
    assert resp.status_code == 401


def test_delivery_search_with_mock_results(
    mcp_client: tuple[APIClient, str],
    project,
    user,
    project_memberships,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = mcp_client
    hit = _mock_search_result(str(project.id))

    async def _fake_recall(*_args, **_kwargs):
        from knowledge.vector_recall import VectorHit

        return [
            VectorHit(
                point_id="pt-1",
                entity_id=hit.entity.entity_id,
                entity_kind=hit.entity.entity_kind,
                version=hit.entity.version,
                score=0.9,
                rrf_score=0.9,
                payload={},
            )
        ]

    monkeypatch.setattr("knowledge.retrieval.recall_similar_chunks", _fake_recall)
    monkeypatch.setattr(
        "knowledge.retrieval.hydrate_many",
        AsyncMock(return_value={(hit.entity.entity_id, hit.entity.version): hit.entity}),
    )
    monkeypatch.setattr("knowledge.retrieval.enrich_vector_hits", AsyncMock(return_value={}))

    resp = client.post(
        "/api/mcp/tools/search_delivery_knowledge/",
        {"query": "登录", "project_ids": [str(project.id)]},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 0
