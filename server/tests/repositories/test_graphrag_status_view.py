"""``GraphRagStatusView`` 集成测试（initial implementation）。

GET /api/repositories/{id}/index/graphrag-status/ —— 以真实 ``ChunkEdge`` 表计数为
权威事实来源，修复旧前端读 ``IndexHistory.edge_count`` 快照（时序漏写停在 0）导致的
"0 语义边"误显示。
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from repositories.models import Repository


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="graphrag_user",
        email="graphrag@example.com",
        password="graphragpass123",
    )


@pytest.fixture
def auth_client(api_client: APIClient, user) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="GraphRAG Repo",
        git_url="https://github.com/test/graphrag-repo.git",
        git_platform="github",
        default_branch="main",
    )


def _url(repository_id: uuid.UUID | str) -> str:
    return f"/api/repositories/{repository_id}/index/graphrag-status/"


def _make_edges(repo: Repository, n: int) -> None:
    from code_relations.models import ChunkEdge
    from code_relations.utils import generate_chunk_id

    for i in range(n):
        ChunkEdge.objects.create(
            source_chunk_id=generate_chunk_id(str(repo.id), f"a{i}.py", 0),
            target_chunk_id=generate_chunk_id(str(repo.id), f"b{i}.py", 0),
            edge_type="CALL",
            weight=0.5,
            repository=repo,
        )


@pytest.mark.django_db
def test_returns_real_chunk_edge_count(auth_client: APIClient, repo: Repository) -> None:
    """有 ChunkEdge → edge_count 反映真实表计数，status=completed（不被快照误导）。"""
    _make_edges(repo, 3)

    resp = auth_client.get(_url(repo.id))

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["edge_count"] == 3
    assert resp.data["status"] == "completed"


@pytest.mark.django_db
def test_zero_edges_reports_pending(auth_client: APIClient, repo: Repository) -> None:
    """无边且无历史 → edge_count=0 + status=pending。"""
    resp = auth_client.get(_url(repo.id))

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["edge_count"] == 0
    assert resp.data["status"] == "pending"
    assert resp.data["last_synced_at"] is None


@pytest.mark.django_db
def test_real_count_ignores_stale_index_history_snapshot(
    auth_client: APIClient, repo: Repository
) -> None:
    """核心回归：IndexHistory.edge_count 快照=0（时序漏写），但真实 ChunkEdge 有边
    → 端点必须返回真实计数 + completed，而非被快照的 0/pending 误导。
    """
    from repositories.models import IndexHistory, IndexHistoryStatus

    # 模拟时序 bug 留下的脏快照：graph_build_status=pending、edge_count=0
    IndexHistory.objects.create(
        repository=repo,
        trigger_type="manual",
        status=IndexHistoryStatus.COMPLETED,
        graph_build_status="pending",
        edge_count=0,
    )
    _make_edges(repo, 5)

    resp = auth_client.get(_url(repo.id))

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["edge_count"] == 5, "必须读真实 ChunkEdge 表，而非快照的 0"
    assert resp.data["status"] == "completed", "有真实边即 completed，不被 pending 快照误导"


@pytest.mark.django_db
def test_404_for_missing_repo(auth_client: APIClient) -> None:
    resp = auth_client.get(_url(uuid.uuid4()))
    assert resp.status_code == status.HTTP_404_NOT_FOUND
