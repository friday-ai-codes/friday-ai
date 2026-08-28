"""会话知识检索共享入口（Phase 144，RECALL-01）。"""

from __future__ import annotations

from typing import Any

from knowledge.retrieval import DeliveryKnowledgeSearchService
from knowledge.retrieval_types import SearchResultDTO

__all__ = ["search_session_knowledge"]


async def search_session_knowledge(
    query: str,
    *,
    user: Any,
    repository_id: str,
    project_id: str | None = None,
    top_k: int = 5,
) -> list[SearchResultDTO]:
    """按仓库检索已入图的会话精华，项目仅作为可选 AND 收窄条件。"""
    return await DeliveryKnowledgeSearchService().search_similar(
        query,
        user=user,
        top_k=top_k,
        repository_ids=[repository_id],
        project_ids=[project_id] if project_id else None,
        entity_kinds=["document"],
        include_document_kind=True,
        source_kinds=["session_capture"],
    )
