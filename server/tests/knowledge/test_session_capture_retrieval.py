"""会话知识共享检索 helper 契约（Phase 144）。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    ("project_id", "expected_project_ids"),
    [
        ("project-1", ["project-1"]),
        (None, None),
    ],
)
async def test_search_session_knowledge_delegates_with_closed_filters(
    monkeypatch: pytest.MonkeyPatch,
    project_id: str | None,
    expected_project_ids: list[str] | None,
) -> None:
    """共享 helper 固定仓库、DOCUMENT 与 session_capture 三件套。"""
    from knowledge.session_capture_retrieval import search_session_knowledge

    search = AsyncMock(return_value=["result"])
    monkeypatch.setattr(
        "knowledge.session_capture_retrieval.DeliveryKnowledgeSearchService.search_similar",
        search,
    )
    user = object()

    result = await search_session_knowledge(
        "部署约束",
        user=user,
        repository_id="repository-1",
        project_id=project_id,
        top_k=7,
    )

    assert result == ["result"]
    search.assert_awaited_once_with(
        "部署约束",
        user=user,
        top_k=7,
        repository_ids=["repository-1"],
        project_ids=expected_project_ids,
        entity_kinds=["document"],
        include_document_kind=True,
        source_kinds=["session_capture"],
    )
