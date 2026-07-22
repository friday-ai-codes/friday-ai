"""DeliveryKnowledgeRecallAdapter 测试（RECALL-01 / KNOW-04）。

覆盖 SearchResultDTO 映射 / created_by None fail-closed 空召回（不伪造 actor）/
检索异常 best-effort 空召回 / routing 候选仓收窄 repository_ids / entity_kinds 映射，
以及 KNOW-04 新行为：新默认 5-kind 集合 / settings 可配置 kinds（含
include_document_kind 动态传参）/ 每 kind 限额截断 / RetrievalTrace 写入与
best-effort 吞异常。search_similar 全程 mock，不触真实向量库；
arecord_retrieval_trace 统一 monkeypatch 为 AsyncMock（autouse），不触真实 ledger。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import override_settings

from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
from knowledge.retrieval_types import EntityMetadata, SearchResultDTO
from services.process_runtime import DeliveryKnowledgeRecallAdapter
from services.process_runtime.recall_adapter import RECALL_ENTITY_KINDS

User = get_user_model()

_DEFAULT_KINDS = ["work_item", "tech_plan", "code_change", "document", "learning_case"]


def _search_result(
    *, kind: str = "work_item", score: float = 0.9, title: str = "相似需求 A"
) -> SearchResultDTO:
    entity = EntityMetadata(
        entity_id=uuid.uuid4(),
        entity_kind=kind,
        version=1,
        title=title,
        valid_at=None,
        invalid_at=None,
        source_kind="feishu_work_item",
        source_id="pk:story:1",
        origin="feishu",
        event_time=None,
        space_id=None,
        repository_id=None,
    )
    return SearchResultDTO(score=score, vector_score=0.8, recency_score=0.5, entity=entity)


def _patch_search(monkeypatch, mock: AsyncMock) -> None:
    monkeypatch.setattr("knowledge.retrieval.DeliveryKnowledgeSearchService.search_similar", mock)


@pytest.fixture(autouse=True)
def trace_mock(monkeypatch) -> AsyncMock:
    """统一 mock recall_adapter 延迟 import 引用的 arecord_retrieval_trace（不触真实 ledger）。"""
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr("interactions.ledger.arecord_retrieval_trace", mock)
    return mock


async def _make_session(**stage_state) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="recall",
        stage_state=stage_state or {"decomposition": {"requirement_text": "做登录"}},
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_maps_search_result_dto(monkeypatch) -> None:
    """SearchResultDTO 映射为 {entity_id, kind, title, score}，query/kinds 透传。"""
    dto = _search_result()
    _patch_search(monkeypatch, AsyncMock(return_value=[dto]))
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="recall",
        stage_state={"decomposition": {"requirement_text": "做登录"}},
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
    assert result["kinds"] == _DEFAULT_KINDS


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_created_by_none_graceful_empty(monkeypatch) -> None:
    """created_by None → 透传 user=None（不伪造 actor），fail-closed 空召回不抛。"""
    mock = AsyncMock(return_value=[])
    _patch_search(monkeypatch, mock)
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="recall",
        stage_state={"decomposition": {"requirement_text": "x"}},
    )
    assert session.created_by is None
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert result["hits"] == []
    # 验证未伪造 actor 绕过权限：传给 search_similar 的 user 必须为 None
    assert mock.await_args.kwargs["user"] is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_created_by_real_user_loads_actor_without_sync_error(monkeypatch) -> None:
    """带真实 created_by 用户：从 DB aget（不预取 created_by）→ 召回不抛
    SynchronousOnlyOperation 且 actor 经 sync_to_async 正确解析透传给 search_similar。

    覆盖 CR-01 —— 旧实现在 async 上下文直接访问 ``session.created_by`` 懒加载 FK 会崩。
    """
    mock = AsyncMock(return_value=[])
    _patch_search(monkeypatch, mock)
    actor = await sync_to_async(User.objects.create_user)(username="recall-actor", password="x")
    created = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="recall",
        stage_state={"decomposition": {"requirement_text": "做登录"}},
        created_by=actor,
    )
    # 关键：不 select_related("created_by") 重新加载，强制走 FK 懒加载路径
    session = await ConvergenceSession.objects.aget(id=created.id)
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert result["hits"] == []
    # actor 经 sync_to_async 解析后正确透传（按 pk 相等）
    assert mock.await_args.kwargs["user"] == actor


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_search_exception_returns_empty(monkeypatch) -> None:
    """search_similar 抛异常 → best-effort 空召回不向上抛。"""
    _patch_search(monkeypatch, AsyncMock(side_effect=RuntimeError("boom")))
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="recall",
        stage_state={"decomposition": {"requirement_text": "x"}},
    )
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert result["hits"] == []


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_repository_ids_from_routing(monkeypatch) -> None:
    """routing 候选仓收窄召回 → search_similar 收到 repository_ids=候选 repo_id 列表。"""
    mock = AsyncMock(return_value=[])
    _patch_search(monkeypatch, mock)
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="recall",
        stage_state={
            "decomposition": {"requirement_text": "x"},
            "routing": {"candidates": [{"repo_id": "r1", "confidence": "high"}]},
        },
    )
    await DeliveryKnowledgeRecallAdapter().recall(session)
    assert mock.await_args.kwargs["repository_ids"] == ["r1"]


def test_entity_kinds_constant() -> None:
    """RECALL_ENTITY_KINDS 默认集合扩为 5 kinds（KNOW-04：+ document/learning_case）。"""
    assert [str(k) for k in RECALL_ENTITY_KINDS] == _DEFAULT_KINDS


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_kinds_configurable(monkeypatch) -> None:
    """kinds 经 settings 可配置；include_document_kind 按 kinds 是否含 document 动态传。"""
    mock = AsyncMock(return_value=[])
    _patch_search(monkeypatch, mock)
    session = await _make_session()

    with override_settings(PROCESS_RECALL_ENTITY_KINDS=["work_item"]):
        result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert mock.await_args.kwargs["entity_kinds"] == ["work_item"]
    assert mock.await_args.kwargs["include_document_kind"] is False
    assert result["kinds"] == ["work_item"]

    # 默认配置：document 在 kinds 中 → include_document_kind=True
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert mock.await_args.kwargs["entity_kinds"] == _DEFAULT_KINDS
    assert mock.await_args.kwargs["include_document_kind"] is True
    assert result["kinds"] == _DEFAULT_KINDS


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_per_kind_limit_truncates(monkeypatch) -> None:
    """每 kind 限额截断：任一 kind 命中数不超其配置上限，合并后保持 score 降序。"""
    dtos = [
        _search_result(kind="work_item", score=s, title=f"需求 {i}")
        for i, s in enumerate([0.9, 0.85, 0.8, 0.75, 0.7, 0.65])
    ] + [
        _search_result(kind="learning_case", score=0.6, title="经验 1"),
        _search_result(kind="learning_case", score=0.55, title="经验 2"),
    ]
    _patch_search(monkeypatch, AsyncMock(return_value=dtos))
    session = await _make_session()

    with override_settings(PROCESS_RECALL_KIND_LIMITS={"work_item": 2}):
        result = await DeliveryKnowledgeRecallAdapter().recall(session)

    hits = result["hits"]
    kinds_count: dict[str, int] = {}
    for hit in hits:
        kinds_count[hit["kind"]] = kinds_count.get(hit["kind"], 0) + 1
    assert kinds_count == {"work_item": 2, "learning_case": 2}
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_retrieval_trace_written(monkeypatch, trace_mock: AsyncMock) -> None:
    """召回成功 → arecord_retrieval_trace 被 await，payload 含指标与 session_id 关联键。"""
    _patch_search(monkeypatch, AsyncMock(return_value=[_search_result()]))
    session = await _make_session()
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert result["hits"]

    assert trace_mock.await_count == 1
    kwargs = trace_mock.await_args.kwargs
    payload = kwargs["payload"]
    assert payload["source"] == "process_recall"
    assert payload["session_id"] == str(session.id)
    assert payload["result_count"] == 1
    assert payload["top_score"] == 0.9
    assert "duration_ms" in payload
    assert payload["per_kind_counts"] == {"work_item": 1}
    assert payload["scores"] == [0.9]
    assert kwargs["source"] == "process_runtime"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_trace_failure_does_not_break_recall(monkeypatch, trace_mock: AsyncMock) -> None:
    """arecord_retrieval_trace 抛异常 → best-effort 吞掉，recall() 仍正常返回 hits。"""
    _patch_search(monkeypatch, AsyncMock(return_value=[_search_result()]))
    trace_mock.side_effect = RuntimeError("trace boom")
    session = await _make_session()
    result = await DeliveryKnowledgeRecallAdapter().recall(session)
    assert len(result["hits"]) == 1
    assert trace_mock.await_count == 1
