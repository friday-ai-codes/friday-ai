"""DeliveryKnowledgeRecallAdapter 测试（RECALL-01）。

覆盖 SearchResultDTO 映射 / created_by None fail-closed 空召回（不伪造 actor）/
检索异常 best-effort 空召回 / routing 候选仓收窄 repository_ids / entity_kinds 映射。
search_similar 全程 mock，不触真实向量库。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from knowledge.retrieval_types import EntityMetadata, SearchResultDTO
from services.plan_orchestration import DeliveryKnowledgeRecallAdapter
from services.plan_orchestration.recall_adapter import RECALL_ENTITY_KINDS


def _search_result() -> SearchResultDTO:
    entity = EntityMetadata(
        entity_id=uuid.uuid4(),
        entity_kind="work_item",
        version=1,
        title="相似需求 A",
        valid_at=None,
        invalid_at=None,
        source_kind="feishu_work_item",
        source_id="pk:story:1",
        origin="feishu",
        event_time=None,
        project_id=None,
        repository_id=None,
    )
    return SearchResultDTO(score=0.9, vector_score=0.8, recency_score=0.5, entity=entity)


def _patch_search(monkeypatch, mock: AsyncMock) -> None:
    monkeypatch.setattr(
        "knowledge.retrieval.DeliveryKnowledgeSearchService.search_similar", mock
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_maps_search_result_dto(monkeypatch) -> None:
    """SearchResultDTO 映射为 {entity_id, kind, title, score}，query/kinds 透传。"""
    dto = _search_result()
    _patch_search(monkeypatch, AsyncMock(return_value=[dto]))
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.RECALLING,
        decomposition={"requirement_text": "做登录"},
    )
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    hit = result["hits"][0]
    assert hit == {
        "entity_id": str(dto.entity.entity_id),
        "kind": "work_item",
        "title": "相似需求 A",
        "score": 0.9,
    }
    assert result["query"] == "做登录"
    assert result["kinds"] == ["work_item", "tech_plan", "code_change"]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_created_by_none_graceful_empty(monkeypatch) -> None:
    """created_by None → 透传 user=None（不伪造 actor），fail-closed 空召回不抛。"""
    mock = AsyncMock(return_value=[])
    _patch_search(monkeypatch, mock)
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.RECALLING,
        decomposition={"requirement_text": "x"},
    )
    assert session.created_by is None
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert result["hits"] == []
    # 验证未伪造 actor 绕过权限：传给 search_similar 的 user 必须为 None
    assert mock.await_args.kwargs["user"] is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_search_exception_returns_empty(monkeypatch) -> None:
    """search_similar 抛异常 → best-effort 空召回不向上抛。"""
    _patch_search(monkeypatch, AsyncMock(side_effect=RuntimeError("boom")))
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.RECALLING,
        decomposition={"requirement_text": "x"},
    )
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert result["hits"] == []


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_repository_ids_from_routing(monkeypatch) -> None:
    """routing 候选仓收窄召回 → search_similar 收到 repository_ids=候选 repo_id 列表。"""
    mock = AsyncMock(return_value=[])
    _patch_search(monkeypatch, mock)
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.RECALLING,
        decomposition={"requirement_text": "x"},
        routing={"candidates": [{"repo_id": "r1", "confidence": "high"}]},
    )
    await DeliveryKnowledgeRecallAdapter().recall(session)
    assert mock.await_args.kwargs["repository_ids"] == ["r1"]


def test_entity_kinds_constant() -> None:
    """RECALL_ENTITY_KINDS 映射到 work_item/tech_plan/code_change。"""
    assert [str(k) for k in RECALL_ENTITY_KINDS] == ["work_item", "tech_plan", "code_change"]
