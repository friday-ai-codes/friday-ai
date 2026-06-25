"""GraphSearchView 端点测试 —— implementation / work item。

测试端点：POST /api/repositories/{id}/graph-search/

覆盖：
- work item RBAC/IDOR 矩阵：200（有权）/ 401（未认证）/ 403（他项目 repo_id，
  IDOR 红线）/ 404（repo 不存在）/ 400（未 INDEXED）。
- work item 返回结构：六键齐全 + neighbor 带 edge_type/reason + results chunk_id 非空。

HybridSearchService.search 用 AsyncMock 隔离向量库/图谱层。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from rest_framework.test import APIClient

from projects.models import SpaceRepository
from repositories.models import IndexStatus, Repository
from services.retrieval.types import (
    HybridSearchResult,
    LayerSnapshot,
    NeighborMetadata,
)

pytestmark = [pytest.mark.django_db(transaction=True)]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_indexed(db, project_a) -> Repository:
    """归属 project_a 的已索引仓库。"""
    repo = Repository.objects.create(
        name="graph-search-repo",
        git_url="https://github.com/test/graph-search.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )
    SpaceRepository.objects.create(space=project_a, repository=repo)
    return repo


@pytest.fixture
def repo_unindexed(db, project_a) -> Repository:
    """归属 project_a 但尚未建立索引的仓库。"""
    repo = Repository.objects.create(
        name="graph-search-unindexed",
        git_url="https://github.com/test/graph-search-unindexed.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.NOT_INDEXED,
    )
    SpaceRepository.objects.create(space=project_a, repository=repo)
    return repo


@pytest.fixture
def client_a(project_a_viewer_user) -> APIClient:
    """project_a VIEWER 用户的认证客户端（有权访问 repo_indexed）。"""
    client = APIClient()
    client.force_authenticate(user=project_a_viewer_user)
    return client


@pytest.fixture
def client_b(project_b_admin_user) -> APIClient:
    """project_b ADMIN 用户的认证客户端（对 project_a 的 repo 无权 → IDOR）。"""
    client = APIClient()
    client.force_authenticate(user=project_b_admin_user)
    return client


def _url(repo: Repository) -> str:
    return f"/api/repositories/{repo.id}/graph-search/"


def _make_mock_result() -> HybridSearchResult:
    """构造 HybridSearchService.search 的模拟返回（含 L3 items + hop1/hop2）。"""
    hop1 = NeighborMetadata(
        chunk_id="chunk-hop1",
        file_path="src/auth/login.py",
        line_start=10,
        line_end=42,
        edge_type="CALL",
        weight=0.85,
        reason="L3 命中 chunk 调用 verify_password()",
        hop=1,
    )
    hop2 = NeighborMetadata(
        chunk_id="chunk-hop2",
        file_path="src/auth/utils.py",
        line_start=None,
        line_end=None,
        edge_type="IMPORT",
        weight=0.42,
        reason="二跳：间接 import bcrypt 工具",
        hop=2,
    )
    l3 = LayerSnapshot(
        layer="L3",
        status="ok",
        result_count=1,
        items=[
            {
                "id": "chunk-l3-001",
                "score": 0.92,
                "payload": {
                    "file_path": "src/auth/login.py",
                    "content": "def login(): ...",
                    "language": "python",
                    "start_line": 1,
                    "end_line": 8,
                },
                "repository_id": "repo-1",
            }
        ],
    )
    return HybridSearchResult(
        query="auth login",
        repository_ids=["repo-1"],
        layers=[l3],
        final_context="# context",
        total_tokens=300,
        graph_context="### Graph Context\nverify_password -> bcrypt",
        hop1_neighbors=[hop1],
        hop2_neighbors=[hop2],
    )


def _patch_search() -> Any:
    return patch(
        "services.retrieval.hybrid_search.HybridSearchService.search",
        new=AsyncMock(return_value=_make_mock_result()),
    )


def _patch_search_capture() -> AsyncMock:
    """返回可断言 call_args 的 search mock（捕获透传的 branch_name）。"""
    return AsyncMock(return_value=_make_mock_result())


# ---------------------------------------------------------------------------
# RBAC/IDOR 状态码矩阵
# ---------------------------------------------------------------------------


def test_authorized_user_200(client_a: APIClient, repo_indexed: Repository) -> None:
    """有权用户（project_a VIEWER）对 INDEXED repo POST → 200。"""
    with _patch_search():
        response = client_a.post(
            _url(repo_indexed), {"query": "auth login"}, format="json"
        )
    assert response.status_code == 200, getattr(response, "data", response)


def test_idor_other_project_403(
    client_b: APIClient, repo_indexed: Repository
) -> None:
    """IDOR 红线：他项目用户（project_b）对 project_a 的 repo → 403（非 200 非 404）。"""
    with _patch_search():
        response = client_b.post(
            _url(repo_indexed), {"query": "auth login"}, format="json"
        )
    assert response.status_code == 403, getattr(response, "data", response)


def test_unauthenticated_401(
    api_client: APIClient, repo_indexed: Repository
) -> None:
    """未认证请求 → 401（IsAuthenticated 强制）。"""
    response = api_client.post(
        _url(repo_indexed), {"query": "auth login"}, format="json"
    )
    assert response.status_code in (401, 403)


def test_repo_not_found_404(client_a: APIClient) -> None:
    """不存在的 repo_id → 404（与 403 语义分明）。"""
    missing_id = uuid.uuid4()
    response = client_a.post(
        f"/api/repositories/{missing_id}/graph-search/",
        {"query": "auth login"},
        format="json",
    )
    assert response.status_code == 404


def test_not_indexed_400(
    client_a: APIClient, repo_unindexed: Repository
) -> None:
    """有权用户对未 INDEXED repo → 400。"""
    response = client_a.post(
        _url(repo_unindexed), {"query": "auth login"}, format="json"
    )
    assert response.status_code == 400


def test_empty_query_400(client_a: APIClient, repo_indexed: Repository) -> None:
    """空 query → 400（serializer validation）。"""
    with _patch_search():
        response = client_a.post(_url(repo_indexed), {"query": ""}, format="json")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 返回结构
# ---------------------------------------------------------------------------


def test_response_shape(client_a: APIClient, repo_indexed: Repository) -> None:
    """200 返回含 query/results/hop1_neighbors/hop2_neighbors/graph_context/total_tokens 六键。"""
    with _patch_search():
        response = client_a.post(
            _url(repo_indexed), {"query": "auth login"}, format="json"
        )
    assert response.status_code == 200
    data = response.json()
    required = {
        "query",
        "results",
        "hop1_neighbors",
        "hop2_neighbors",
        "graph_context",
        "total_tokens",
    }
    assert required.issubset(data.keys()), f"缺字段: {required - data.keys()}"
    assert data["query"] == "auth login"
    assert data["graph_context"].startswith("### Graph Context")
    assert data["total_tokens"] == 300


def test_neighbor_fields(client_a: APIClient, repo_indexed: Repository) -> None:
    """每条 hop1/hop2 neighbor 带 edge_type + reason（复用 _serialize_neighbor 字段集）。"""
    with _patch_search():
        response = client_a.post(
            _url(repo_indexed), {"query": "auth login"}, format="json"
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data["hop1_neighbors"]) == 1
    assert len(data["hop2_neighbors"]) == 1
    for neighbor in data["hop1_neighbors"] + data["hop2_neighbors"]:
        assert "edge_type" in neighbor
        assert "reason" in neighbor
    assert data["hop1_neighbors"][0]["edge_type"] == "CALL"
    assert data["hop2_neighbors"][0]["edge_type"] == "IMPORT"


def test_results_chunk_id_present(
    client_a: APIClient, repo_indexed: Repository
) -> None:
    """results 每项 chunk_id 非空（Pitfall 7 回归：显式映射 item["id"]）。"""
    with _patch_search():
        response = client_a.post(
            _url(repo_indexed), {"query": "auth login"}, format="json"
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 1
    item = data["results"][0]
    assert item["chunk_id"] == "chunk-l3-001"
    assert item["file_path"] == "src/auth/login.py"
    assert item["line_start"] == 1
    assert item["line_end"] == 8
    assert item["content"]
    assert item["language"] == "python"
    for r in data["results"]:
        assert r["chunk_id"], "results 项 chunk_id 不应为空"


# ---------------------------------------------------------------------------
# work item（view 层）：branch 二段归一化（code-review 296 M2 红线回归）
# ---------------------------------------------------------------------------


def test_base_branch_normalized_to_none(
    client_a: APIClient, repo_indexed: Repository
) -> None:
    """传 base 分支名（==default_branch）→ search 收到 branch_name=None（base，不漏边）。"""
    search_mock = _patch_search_capture()
    # repo_indexed.default_branch == "main"；resolve_branch_for_query 对 base 返回 base 名。
    with patch(
        "repositories.graph_search_views.resolve_branch_for_query",
        new=AsyncMock(return_value=("main", None)),
    ), patch(
        "services.retrieval.hybrid_search.HybridSearchService.search",
        new=search_mock,
    ):
        response = client_a.post(
            _url(repo_indexed),
            {"query": "auth login", "branch": "main"},
            format="json",
        )
    assert response.status_code == 200, getattr(response, "data", response)
    assert search_mock.call_args.kwargs["branch_name"] is None


def test_feature_branch_passed_through(
    client_a: APIClient, repo_indexed: Repository
) -> None:
    """传 feature 分支名（!=default_branch）→ search 收到该分支名（branch-aware overlay）。"""
    search_mock = _patch_search_capture()
    with patch(
        "repositories.graph_search_views.resolve_branch_for_query",
        new=AsyncMock(return_value=("feature-x", None)),
    ), patch(
        "services.retrieval.hybrid_search.HybridSearchService.search",
        new=search_mock,
    ):
        response = client_a.post(
            _url(repo_indexed),
            {"query": "auth login", "branch": "feature-x"},
            format="json",
        )
    assert response.status_code == 200, getattr(response, "data", response)
    assert search_mock.call_args.kwargs["branch_name"] == "feature-x"


def test_top_k_over_limit_400(
    client_a: APIClient, repo_indexed: Repository
) -> None:
    """top_k 超上界（>50）→ 400（code-review 296 M1：防资源滥用）。"""
    with _patch_search():
        response = client_a.post(
            _url(repo_indexed),
            {"query": "auth login", "top_k": 1000000},
            format="json",
        )
    assert response.status_code == 400
