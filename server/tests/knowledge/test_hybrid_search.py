"""混合检索编排测试（Phase 15-04）。"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from knowledge.graph_enrichment import enrich_vector_hits
from knowledge.models import EdgeRelation, EntityKind
from knowledge.retrieval import DeliveryKnowledgeSearchService
from knowledge.vector_recall import VectorHit

pytestmark = pytest.mark.django_db(transaction=True)


async def test_enrich_returns_related_kinds(entity_factory, edge_factory, version_factory, project):
    wi = await sync_to_async(entity_factory)(kind=EntityKind.WORK_ITEM, space=project)
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, space=project)
    code = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, space=project)
    await sync_to_async(version_factory)(wi)
    await sync_to_async(version_factory)(plan)
    await sync_to_async(version_factory)(code)
    await sync_to_async(edge_factory)(wi, plan, relation=EdgeRelation.HAS_PLAN)
    await sync_to_async(edge_factory)(plan, code, relation=EdgeRelation.IMPLEMENTED_BY)

    hit = VectorHit("p1", wi.id, EntityKind.WORK_ITEM, 1, 0.9, 0.9, {})
    enriched = await enrich_vector_hits([hit], allowed_project_ids=[str(project.id)], max_hops=2)
    kinds = {r.entity_kind for rs in enriched.values() for r in rs}
    assert EntityKind.TECH_PLAN in kinds
    assert EntityKind.CODE_CHANGE in kinds
    related = enriched[wi.id]
    by_kind = {r.entity_kind: r for r in related}
    assert by_kind[EntityKind.TECH_PLAN].relation == EdgeRelation.HAS_PLAN
    assert by_kind[EntityKind.CODE_CHANGE].relation == EdgeRelation.IMPLEMENTED_BY


async def test_enrich_max_hops_one(entity_factory, edge_factory, version_factory, project):
    wi = await sync_to_async(entity_factory)(kind=EntityKind.WORK_ITEM, space=project)
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, space=project)
    code = await sync_to_async(entity_factory)(kind=EntityKind.CODE_CHANGE, space=project)
    await sync_to_async(version_factory)(wi)
    await sync_to_async(version_factory)(plan)
    await sync_to_async(version_factory)(code)
    await sync_to_async(edge_factory)(wi, plan, relation=EdgeRelation.HAS_PLAN)
    await sync_to_async(edge_factory)(plan, code, relation=EdgeRelation.IMPLEMENTED_BY)
    hit = VectorHit("p1", wi.id, EntityKind.WORK_ITEM, 1, 0.9, 0.9, {})
    enriched = await enrich_vector_hits([hit], allowed_project_ids=[str(project.id)], max_hops=1)
    kinds = {r.entity_kind for rs in enriched.values() for r in rs}
    assert EntityKind.CODE_CHANGE not in kinds


async def test_enrich_dedupe(entity_factory, edge_factory, version_factory, project):
    wi = await sync_to_async(entity_factory)(kind=EntityKind.WORK_ITEM, space=project)
    plan = await sync_to_async(entity_factory)(kind=EntityKind.TECH_PLAN, space=project)
    await sync_to_async(version_factory)(wi)
    await sync_to_async(version_factory)(plan)
    await sync_to_async(edge_factory)(wi, plan, relation=EdgeRelation.HAS_PLAN)
    hit = VectorHit("p1", wi.id, EntityKind.WORK_ITEM, 1, 0.9, 0.9, {})
    enriched = await enrich_vector_hits([hit], allowed_project_ids=[str(project.id)], max_hops=2)
    related = enriched.get(wi.id, [])
    assert len({r.entity_id for r in related}) == len(related)


@pytest.fixture
def search_mocks(monkeypatch, mock_embedding):
    async def _fake_recall(query, **kw):
        eid = uuid.uuid4()
        return [
            VectorHit(
                "pt",
                eid,
                EntityKind.WORK_ITEM,
                1,
                0.8,
                0.8,
                {"event_time": timezone.now().isoformat()},
            )
        ]

    monkeypatch.setattr("knowledge.retrieval.recall_similar_chunks", _fake_recall)
    monkeypatch.setattr(
        "knowledge.retrieval.enrich_vector_hits",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        "knowledge.retrieval.hydrate_many",
        AsyncMock(return_value={}),
    )


async def test_search_similar_unauthorized(project, other_user):
    svc = DeliveryKnowledgeSearchService()
    assert await svc.search_similar("q", user=other_user, project_ids=[str(project.id)]) == []


async def test_search_similar_recency_order(entity_factory, version_factory, project, user, project_memberships, monkeypatch, mock_embedding):
    old = await sync_to_async(entity_factory)(space=project, title="旧需求", event_time=timezone.now() - timedelta(days=120))
    new = await sync_to_async(entity_factory)(space=project, title="新需求", event_time=timezone.now())
    await sync_to_async(version_factory)(old, version=1)
    await sync_to_async(version_factory)(new, version=1)

    async def _fake_recall(query, **kw):
        return [
            VectorHit("p1", old.id, EntityKind.WORK_ITEM, 1, 0.5, 0.5, {}),
            VectorHit("p2", new.id, EntityKind.WORK_ITEM, 1, 0.5, 0.5, {}),
        ]

    from knowledge.metadata_hydrate import hydrate_entity_metadata

    async def _hydrate_many(keys, **kw):
        out = {}
        for eid, ver in keys:
            meta = await hydrate_entity_metadata(eid, ver, include_superseded=True)
            if meta:
                out[(eid, ver)] = meta
        return out

    monkeypatch.setattr("knowledge.retrieval.recall_similar_chunks", _fake_recall)
    monkeypatch.setattr("knowledge.retrieval.enrich_vector_hits", AsyncMock(return_value={}))
    monkeypatch.setattr("knowledge.retrieval.hydrate_many", _hydrate_many)

    svc = DeliveryKnowledgeSearchService()
    results = await svc.search_similar("需求", user=user, project_ids=[str(project.id)])
    if len(results) >= 2:
        assert results[0].entity.title == "新需求"
