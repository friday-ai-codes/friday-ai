from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionRun, RetrievalTrace
from services.retrieval.types import HybridSearchResult, LayerSnapshot

pytestmark = pytest.mark.django_db


def test_mcp_read_flow_creates_replayable_traces(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _plaintext = mcp_client
    monkeypatch.setattr(
        "codegraph.services.repo_router.RepoRouter.route",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    repo_id=str(indexed_repository.id),
                    final_score=1.0,
                    match_reason="matched",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "services.retrieval.hybrid_search.HybridSearchService.search",
        AsyncMock(
            return_value=HybridSearchResult(
                query="auth",
                repository_ids=[str(indexed_repository.id)],
                layers=[
                    LayerSnapshot(
                        layer="L3",
                        status="ok",
                        result_count=1,
                        items=[
                            {
                                "id": "11111111-1111-1111-1111-111111111111",
                                "score": 1,
                                "payload": {"file_path": "src/main.py", "content": "x"},
                            }
                        ],
                    )
                ],
                final_context="ctx",
            )
        ),
    )
    monkeypatch.setattr(
        "services.repo_file_read._scroll_file_from_collection",
        AsyncMock(return_value=[{"chunk_index": 0, "content": "x", "start_line": 1, "end_line": 1}]),
    )

    assert client.post("/api/mcp/tools/route_repositories/", {"query": "auth"}, format="json").status_code == 200
    assert client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_id": str(indexed_repository.id), "query": "auth"},
        format="json",
    ).status_code == 200
    assert client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": "src/main.py"},
        format="json",
    ).status_code == 200

    assert InteractionRun.objects.filter(source="mcp").count() == 3
    kinds = set(RetrievalTrace.objects.values_list("kind", flat=True))
    assert {"routing", "chunk", "file"} <= kinds
