"""``IndexStatsView`` 的 ``?branch=`` branch-aware 计数测试（implementation，work item）。

GET /api/repositories/{id}/index/stats/?branch=<分支>

口径裁定（Open Question 2）：本 phase chunks_total 收窄保 Qdrant base collection
points 不变，仅图谱/ChunkEdge 维度（响应 edge_count 字段）做 base+overlay 合并。
故以下用例只校验 edge_count 的 branch-aware 行为 + 缺省向后兼容（既有字段不漂移）。
Qdrant 依赖用 monkeypatch 隔离，避免真实向量库。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from repositories.models import Repository, RepositoryBranchIndex
from services.qdrant_service import QdrantService


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db: object) -> object:
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="index_stats_branch_user",
        email="index_stats_branch@example.com",
        password="indexstatspass123",
    )


@pytest.fixture
def auth_client(api_client: APIClient, user: object) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def repo(db: object) -> Repository:
    return Repository.objects.create(
        name="Index Stats Branch Repo",
        git_url="https://github.com/test/index-stats-branch-repo.git",
        git_platform="github",
        default_branch="main",
        index_total_chunks=100,
    )


@pytest.fixture(autouse=True)
def _stub_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离 Qdrant：固定 base collection 统计，确保 chunks_total 口径稳定。"""

    def _fake_stats(repository_id: str) -> dict[str, Any]:
        return {"points_count": 100, "language_distribution": {"python": 50}}

    monkeypatch.setattr(QdrantService, "get_collection_stats", staticmethod(_fake_stats))


def _url(repository_id: uuid.UUID | str) -> str:
    return f"/api/repositories/{repository_id}/index/stats/"


def _make_edges(repo: Repository, n: int, branch_name: str = "") -> None:
    from code_relations.models import ChunkEdge
    from code_relations.utils import generate_chunk_id

    prefix = branch_name or "base"
    for i in range(n):
        ChunkEdge.objects.create(
            source_chunk_id=generate_chunk_id(str(repo.id), f"{prefix}_a{i}.py", 0),
            target_chunk_id=generate_chunk_id(str(repo.id), f"{prefix}_b{i}.py", 0),
            edge_type="CALL",
            weight=0.5,
            repository=repo,
            branch_name=branch_name,
        )


def _enable_branch_index(repo: Repository, feature: str) -> None:
    RepositoryBranchIndex.objects.create(
        repository=repo,
        branch_name=repo.default_branch,
        is_base_branch=True,
    )
    RepositoryBranchIndex.objects.create(
        repository=repo,
        branch_name=feature,
        is_base_branch=False,
    )


@pytest.mark.django_db
def test_index_stats_branch_merges(
    auth_client: APIClient, repo: Repository
) -> None:
    """work item：不同 branch 参数下图谱/ChunkEdge 维度（edge_count）合并生效。

    chunks_total 收窄保 base 不变（口径裁定），故两次请求 chunks_total 相同，
    仅 edge_count 随 branch 不同（feature=base+overlay，缺省=base）。
    """
    _enable_branch_index(repo, feature="feat-x")
    _make_edges(repo, 3, branch_name="")  # base
    _make_edges(repo, 2, branch_name="feat-x")  # overlay

    resp_feat = auth_client.get(_url(repo.id), {"branch": "feat-x"})
    resp_default = auth_client.get(_url(repo.id))

    assert resp_feat.status_code == status.HTTP_200_OK
    assert resp_default.status_code == status.HTTP_200_OK

    # edge_count branch-aware：feature=5（3+2），缺省=3（仅 base）
    assert resp_feat.data["edge_count"] == 5
    assert resp_default.data["edge_count"] == 3
    assert resp_feat.data["edge_count"] != resp_default.data["edge_count"]

    # chunks_total 口径收窄：始终为 base collection points，不随 branch 漂移
    assert resp_feat.data["chunks_total"] == resp_default.data["chunks_total"] == 100


@pytest.mark.django_db
def test_index_stats_default_backward_compat(
    auth_client: APIClient, repo: Repository
) -> None:
    """work item：缺省不传 branch 时既有字段与现状一致（向后兼容）。"""
    _make_edges(repo, 4, branch_name="")  # 存量纯 base

    resp = auth_client.get(_url(repo.id))

    assert resp.status_code == status.HTTP_200_OK
    # 既有字段保持现状口径
    assert resp.data["chunks_total"] == 100
    assert resp.data["language_distribution"] == {"python": 50}
    assert resp.data["coverage_percent"] == 100.0
    # 新增 edge_count = 干净 base 计数
    assert resp.data["edge_count"] == 4
