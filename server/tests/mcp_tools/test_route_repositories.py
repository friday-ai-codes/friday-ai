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
        "codegraph.services.repo_router_v2.RepoRouterV2.route",
        AsyncMock(
            return_value=SimpleNamespace(
                candidates=[
                    SimpleNamespace(
                        repo_id=str(indexed_repository.id),
                        repo_name=indexed_repository.name,
                        score=0.91,
                        confidence="high",
                        reasoning="名称和摘要命中",
                        sub_project="",
                        sub_project_paths=[],
                        matched_node_paths=["认证模块 > 登录"],
                    )
                ],
                router_version="v2",
                auto_selected=True,
            )
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
    # description 统一来源于 ai_summary（overview_text），手动简介字段已移除
    assert body["ranked_repos"][0]["description"] == "测试仓库摘要"
    assert body["ranked_repos"][0]["reason"] == "名称和摘要命中"
    assert body["ranked_repos"][0]["confidence"] == "high"
    assert body["ranked_repos"][0]["matched_node_paths"] == ["认证模块 > 登录"]
    assert body["router_version"] == "v2"
    assert body["auto_selected"] is True
    assert InteractionRun.objects.filter(run_id=body["run_id"]).exists()
    assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.ROUTING).count() == 1
