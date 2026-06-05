from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionRun, RetrievalTrace

pytestmark = pytest.mark.django_db


def test_route_repositories_returns_enriched_candidates(
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
                    final_score=0.91,
                    match_reason="名称和摘要命中",
                )
            ]
        ),
    )

    response = client.post(
        "/api/mcp/tools/route_repositories/",
        {"query": "auth", "top_k": 3},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ranked_repos"][0]["repo_id"] == str(indexed_repository.id)
    assert body["ranked_repos"][0]["description"] == "用于 MCP 测试的仓库"
    assert body["ranked_repos"][0]["reason"] == "名称和摘要命中"
    assert InteractionRun.objects.filter(run_id=body["run_id"]).exists()
    assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.ROUTING).count() == 1
