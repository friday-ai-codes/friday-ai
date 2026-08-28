"""DeliveryKnowledgeSearchService 参数透传契约（Phase 144）。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from knowledge.retrieval import DeliveryKnowledgeSearchService

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    ("source_kinds", "expected"),
    [
        (["session_capture"], ["session_capture"]),
        (None, None),
    ],
)
async def test_search_similar_passes_source_kinds_to_vector_recall(
    monkeypatch: pytest.MonkeyPatch,
    source_kinds: list[str] | None,
    expected: list[str] | None,
) -> None:
    """显式闭集与默认 None 均原样透传，不在 service 层改写。"""
    monkeypatch.setattr(
        "knowledge.retrieval.resolve_allowed_project_ids",
        AsyncMock(return_value=["project-1"]),
    )
    monkeypatch.setattr(
        "knowledge.retrieval.resolve_allowed_repository_ids",
        AsyncMock(return_value=["repository-1"]),
    )
    recall = AsyncMock(return_value=[])
    monkeypatch.setattr("knowledge.retrieval.recall_similar_chunks", recall)

    result = await DeliveryKnowledgeSearchService().search_similar(
        "部署约束",
        user=object(),
        repository_ids=["repository-1"],
        project_ids=["project-1"],
        entity_kinds=["document"],
        include_document_kind=True,
        source_kinds=source_kinds,
    )

    assert result == []
    assert recall.await_args.kwargs["source_kinds"] == expected
