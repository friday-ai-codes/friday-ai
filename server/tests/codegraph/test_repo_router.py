"""RepoRouter 两阶段路由 + Route API 端点测试 —— implementation (per contract/contract/contract)."""

from unittest.mock import AsyncMock, patch

import pytest

from codegraph.services.repo_summaries_channel import route_repo_summaries

# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


def _make_qdrant_result(repo_id: str, repo_name: str, score: float,
                        tech_stack: dict | None = None,
                        api_domains: list | None = None,
                        primary_symbols: list | None = None,
                        description: str = "",
                        ) -> dict:
    """构建 mock Qdrant hybrid_search_by_name 返回的单个结果。"""
    import json

    payload: dict = {
        "repository_id": repo_id,
        "repo_name": repo_name,
        "description": description,
    }
    if tech_stack is not None:
        payload["tech_stack"] = json.dumps(tech_stack)
    if api_domains is not None:
        payload["api_domains"] = json.dumps(api_domains)
    if primary_symbols is not None:
        payload["primary_symbols"] = json.dumps(primary_symbols)

    return {"id": repo_id, "score": score, "payload": payload}


def _make_sparse_result(indices=None, values=None):
    """构建 mock sparse encode 返回。"""
    if indices is None:
        indices = [1, 2, 3]
    if values is None:
        values = [0.1, 0.2, 0.3]
    return {"indices": indices, "values": values}


# ---------------------------------------------------------------------------
# TestRepoSummariesChannel — 统一服务内部摘要回退通道测试
# ---------------------------------------------------------------------------


class TestRepoSummariesChannel:
    """repo_summaries BM25+dense+关键词微调测试。"""

    @pytest.mark.asyncio
    async def test_route_stage1_bm25_stage2_rerank(self):
        """验证 Stage 1 BM25 筛选 Top-10 + Stage 2 Embedding 精排 Top-3。"""
        mock_results = [
            _make_qdrant_result(f"repo-{i}", f"test-repo-{i}", 0.9 - i * 0.05,
                                tech_stack={"python": 80, "django": 20},
                                description="A Django REST API repository")
            for i in range(10)
        ]

        with (
            patch("codegraph.services.repo_summaries_channel.SparseEncoderService.encode",
                  return_value=_make_sparse_result()),
            patch("services.embedding.EmbeddingService.generate_embedding",
                  new_callable=AsyncMock, return_value=[0.1] * 1024),
            patch("codegraph.services.repo_summaries_channel.QdrantService.hybrid_search_multi_by_name",
                  return_value=mock_results),
        ):
            results = await route_repo_summaries("Django API", top_k=3)

            assert len(results) == 3
            for r in results:
                assert r.repo_id.startswith("repo-")
                assert r.repo_name.startswith("test-repo-")
                assert 0.0 <= r.bm25_score <= 1.0
                assert 0.0 <= r.embedding_score <= 1.0
                assert 0.0 <= r.final_score <= 1.0
                assert len(r.match_reason) > 0
            # 验证 final_score 降序
            for i in range(len(results) - 1):
                assert results[i].final_score >= results[i + 1].final_score

    @pytest.mark.asyncio
    async def test_route_empty_collection_returns_empty(self):
        """验证 repo_summaries 无数据时返回空列表。"""
        with (
            patch("codegraph.services.repo_summaries_channel.SparseEncoderService.encode",
                  return_value=_make_sparse_result()),
            patch("services.embedding.EmbeddingService.generate_embedding",
                  new_callable=AsyncMock, return_value=[0.1] * 1024),
            patch("codegraph.services.repo_summaries_channel.QdrantService.hybrid_search_multi_by_name",
                  return_value=[]),
        ):
            results = await route_repo_summaries("Nonexistent repo")
            assert results == []

    @pytest.mark.asyncio
    async def test_route_top_k_parameter(self):
        """验证 top_k=5 返回 5 条结果。"""
        mock_results = [
            _make_qdrant_result(f"repo-{i}", f"test-repo-{i}", 0.9 - i * 0.05,
                                tech_stack={"python": 80},
                                description="A Python repository")
            for i in range(10)
        ]

        with (
            patch("codegraph.services.repo_summaries_channel.SparseEncoderService.encode",
                  return_value=_make_sparse_result()),
            patch("services.embedding.EmbeddingService.generate_embedding",
                  new_callable=AsyncMock, return_value=[0.1] * 1024),
            patch("codegraph.services.repo_summaries_channel.QdrantService.hybrid_search_multi_by_name",
                  return_value=mock_results),
        ):
            results = await route_repo_summaries("Python", top_k=5)
            assert len(results) == 5

    @pytest.mark.asyncio
    async def test_route_sparse_encode_failure_returns_empty(self):
        """验证 sparse 编码失败时返回空列表。"""
        with patch("codegraph.services.repo_summaries_channel.SparseEncoderService.encode",
                   return_value={"indices": [], "values": []}):
            results = await route_repo_summaries("test query")
            assert results == []

    @pytest.mark.asyncio
    async def test_route_final_score_formula(self):
        """验证 final_score = bm25_score * 0.4 + embedding_score * 0.6。"""
        mock_results = [
            _make_qdrant_result("repo-1", "test-repo", 0.8,
                                tech_stack={"python": 80, "django": 20},
                                description="Django REST API repo")
        ]

        with (
            patch("codegraph.services.repo_summaries_channel.SparseEncoderService.encode",
                  return_value=_make_sparse_result()),
            patch("services.embedding.EmbeddingService.generate_embedding",
                  new_callable=AsyncMock, return_value=[0.1] * 1024),
            patch("codegraph.services.repo_summaries_channel.QdrantService.hybrid_search_multi_by_name",
                  return_value=mock_results),
        ):
            results = await route_repo_summaries("Django API")
            assert len(results) == 1
            r = results[0]
            expected_final = round(r.bm25_score * 0.4 + r.embedding_score * 0.6, 4)
            assert r.final_score == expected_final

    @pytest.mark.asyncio
    async def test_match_reason_tech_stack(self):
        """验证 tech_stack 匹配生成正确的 match_reason。"""
        mock_results = [
            _make_qdrant_result("repo-1", "django-api", 0.85,
                                tech_stack={"python": 80, "django": 20},
                                description="Django REST API repository")
        ]

        with (
            patch("codegraph.services.repo_summaries_channel.SparseEncoderService.encode",
                  return_value=_make_sparse_result()),
            patch("services.embedding.EmbeddingService.generate_embedding",
                  new_callable=AsyncMock, return_value=[0.1] * 1024),
            patch("codegraph.services.repo_summaries_channel.QdrantService.hybrid_search_multi_by_name",
                  return_value=mock_results),
        ):
            results = await route_repo_summaries("python django api")
            assert len(results) == 1
            assert "matched tech_stack:" in results[0].match_reason
            assert "python" in results[0].match_reason.lower()
            assert "django" in results[0].match_reason.lower()


# ---------------------------------------------------------------------------
# TestRepoRouteView — POST /api/repositories/route/ API 端点测试
# ---------------------------------------------------------------------------


class TestRepoRouteView:
    """POST /api/repositories/route/ API 端点测试（per contract/work item）。

    使用同步 DRF APIClient（adrf async views 由 Django AsyncToSync 自动适配，
    per test_provider_credential_api.py 模式）。
    """

    @pytest.fixture
    def route_user(self, db):
        """创建测试用户以供 API 认证。"""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return User.objects.create_user(
            username="route_test_user",
            email="route_test@example.com",
            password="testpass123",
        )

    @pytest.mark.django_db(transaction=True)
    def test_route_api_returns_200_with_results(self, route_user):
        """验证 API 端点返回 200 + 结构化 JSON（per work item）。"""
        from rest_framework.test import APIClient

        from codegraph.services.repo_router_v2 import (
            RepoRouteCandidateV2,
            RepoRouteResultV2,
        )

        mock_result = RepoRouteResultV2(
            candidates=[
                RepoRouteCandidateV2(
                    repo_id="repo-1",
                    repo_name="test-repo",
                    score=0.74,
                    confidence="low",
                    reasoning="matched tech_stack: python, django",
                )
            ],
            router_version="v1_fallback",
            auto_selected=False,
            degraded=True,
            degrade_reason="no_node_index",
        )

        with patch(
            "codegraph.services.repo_router_v2.RepoRouterV2.route",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            client = APIClient()
            client.force_authenticate(user=route_user)

            response = client.post(
                "/api/repositories/route/",
                {"query": "Django API", "top_k": 3},
                format="json",
            )

            assert response.status_code == 200
            assert response.data["query"] == "Django API"
            assert len(response.data["ranked_repos"]) == 1
            assert response.data["total"] == 1
            repo = response.data["ranked_repos"][0]
            assert repo["repo_id"] == "repo-1"
            assert repo["repo_name"] == "test-repo"
            assert "score" in repo
            assert "match_reason" in repo

    @pytest.mark.django_db(transaction=True)
    def test_route_api_unauthenticated_returns_401(self):
        """验证无认证调用返回 401。"""
        from rest_framework.test import APIClient

        client = APIClient()
        response = client.post(
            "/api/repositories/route/",
            {"query": "Django API"},
            format="json",
        )

        assert response.status_code == 401

    @pytest.mark.django_db(transaction=True)
    def test_route_api_empty_query_returns_400(self, route_user):
        """验证空 query 返回 400 验证错误（security mitigation mitigation）。"""
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=route_user)

        response = client.post(
            "/api/repositories/route/",
            {"query": ""},
            format="json",
        )

        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_route_api_top_k_exceeds_max_returns_400(self, route_user):
        """验证 top_k > 10 返回 400 验证错误（security mitigation mitigation）。"""
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=route_user)

        response = client.post(
            "/api/repositories/route/",
            {"query": "Django", "top_k": 20},
            format="json",
        )

        assert response.status_code == 400
