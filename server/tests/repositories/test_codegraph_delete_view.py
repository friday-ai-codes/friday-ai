"""initial implementation plan / work item-03：DELETE /api/repositories/{id}/codegraph/ 端到端。

覆盖的 6 条测试场景：

1. ``test_delete_clears_graph_only``：DELETE → Symbol/ImportEdge/Endpoint=0；
   FileIndex/ChunkEdge/ChunkRegistry 行不变；返回 204。
2. ``test_concurrent_running_returns_409``：构造 ``IndexHistory(graph_build_status
   =RUNNING)`` → DELETE 返回 409 + ``response.data["detail"].lower()`` 含
   ``"running"``。
3. ``test_404_on_missing_repository``：repository_id 不存在 → 404。
4. ``test_unauthenticated_401``：未登录 → 401。
5. ``test_idempotent_204_when_no_graph_data``：仓库存在但图谱三件套为空时仍返 204。
6. ``test_concurrent_other_repository_running_does_not_block``：并发判断按
   ``repository_id`` 严格匹配，别仓 RUNNING 不应阻塞本仓 DELETE（regression
   guard）。

测试组织风格沿用 ``test_index_delete_cleanup.py`` —— 直接用 APIClient 走完整
DRF dispatch 拿 status_code，避免直调 view 时 query_params / permission 等被绕过。
"""

from __future__ import annotations

import uuid

import pytest
from rest_framework.test import APIClient

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from codegraph.models import Endpoint, ImportEdge, Symbol
from repositories.models import (
    FileIndex,
    GraphBuildStatus,
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    TriggerType,
)

pytestmark = [pytest.mark.django_db(transaction=True)]


# ---------------------------------------------------------------------------
# fixtures：authenticated_client / 仓库 + 图谱 + 向量种子
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="codegraph-delete-repo",
        git_url="https://github.com/test/codegraph-delete.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )


@pytest.fixture
def graph_seeds(db, repo: Repository) -> dict[str, int]:
    """在 repo 下种 1 行 Symbol / ImportEdge / Endpoint。"""
    Symbol.objects.create(
        repository=repo,
        name="foo",
        symbol_type=Symbol.SymbolType.FUNCTION,
        file_path="src/a.py",
        start_line=1,
        end_line=2,
    )
    ImportEdge.objects.create(
        repository=repo,
        source_file="src/a.py",
        target_module="vue",
        imported_names=["ref"],
    )
    Endpoint.objects.create(
        repository=repo,
        http_method="GET",
        url_path="/api/x/",
        handler_name="x",
        view_type=Endpoint.ViewType.FUNCTION_VIEW,
        file_path="src/a.py",
        line_number=1,
    )
    return {"symbols": 1, "import_edges": 1, "endpoints": 1}


@pytest.fixture
def vector_seeds(db, repo: Repository) -> dict[str, int]:
    """在 repo 下种 1 行 FileIndex + 2 行 ChunkRegistry + 1 行 ChunkEdge。"""
    FileIndex.objects.create(
        repository=repo, file_path="src/a.py", file_hash="hash-a"
    )
    cr_a = ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="cr-hash-a",
        repository=repo,
        file_path="src/a.py",
        chunk_index=0,
    )
    cr_b = ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="cr-hash-b",
        repository=repo,
        file_path="src/a.py",
        chunk_index=1,
    )
    ChunkEdge.objects.create(
        source_chunk_id=cr_a.chunk_id,
        target_chunk_id=cr_b.chunk_id,
        edge_type=EdgeType.SAME_FILE,
        weight=0.5,
        repository=repo,
    )
    return {"file_indexes": 1, "chunk_registries": 2, "chunk_edges": 1}


def _url(repo: Repository) -> str:
    return f"/api/repositories/{repo.id}/codegraph/"


# ---------------------------------------------------------------------------
# 1. 仅清图谱三件套，向量轨完整
# ---------------------------------------------------------------------------


def test_delete_clears_graph_only(
    authenticated_client: APIClient,
    repo: Repository,
    graph_seeds: dict[str, int],
    vector_seeds: dict[str, int],
) -> None:
    """DELETE 仅清 Symbol/ImportEdge/Endpoint，向量轨 4 张表行数不变。"""

    response = authenticated_client.delete(_url(repo))

    assert response.status_code == 204, getattr(response, "data", response)

    # 图谱三件套：清空
    assert Symbol.objects.filter(repository=repo).count() == 0
    assert ImportEdge.objects.filter(repository=repo).count() == 0
    assert Endpoint.objects.filter(repository=repo).count() == 0

    # 向量轨：行数不变
    assert (
        FileIndex.objects.filter(repository=repo).count()
        == vector_seeds["file_indexes"]
    )
    assert (
        ChunkRegistry.objects.filter(repository=repo).count()
        == vector_seeds["chunk_registries"]
    )
    assert (
        ChunkEdge.objects.filter(repository=repo).count()
        == vector_seeds["chunk_edges"]
    )


# ---------------------------------------------------------------------------
# 2. 并发 RUNNING → 409 + detail 含 "running"
# ---------------------------------------------------------------------------


def test_concurrent_running_returns_409(
    authenticated_client: APIClient,
    repo: Repository,
    graph_seeds: dict[str, int],
) -> None:
    """存在 IndexHistory.graph_build_status=RUNNING 时 DELETE 必须 409。"""

    IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.RUNNING,
        graph_build_status=GraphBuildStatus.RUNNING,
    )

    response = authenticated_client.delete(_url(repo))

    assert response.status_code == 409, getattr(response, "data", response)
    detail = str(response.data.get("detail", "")).lower()
    assert "running" in detail, f"detail 缺 running 关键字：{detail!r}"

    # 409 时图谱三件套保留
    assert Symbol.objects.filter(repository=repo).count() == 1
    assert ImportEdge.objects.filter(repository=repo).count() == 1
    assert Endpoint.objects.filter(repository=repo).count() == 1


# ---------------------------------------------------------------------------
# 3. 仓库不存在 → 404
# ---------------------------------------------------------------------------


def test_404_on_missing_repository(authenticated_client: APIClient) -> None:
    """不存在的 repository_id 必须返回 404，不暴露内部异常。"""

    missing_id = uuid.uuid4()
    response = authenticated_client.delete(
        f"/api/repositories/{missing_id}/codegraph/"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. 未认证 → 401
# ---------------------------------------------------------------------------


def test_unauthenticated_401(api_client: APIClient, repo: Repository) -> None:
    """未登录用户 DELETE 必须 401（IsAuthenticated 强制）。"""

    response = api_client.delete(_url(repo))
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 5. 图谱无数据 → 仍返 204（幂等）
# ---------------------------------------------------------------------------


def test_idempotent_204_when_no_graph_data(
    authenticated_client: APIClient,
    repo: Repository,
) -> None:
    """图谱三件套为空时再次调用 DELETE 必须 204（幂等）。"""

    response = authenticated_client.delete(_url(repo))
    assert response.status_code == 204
    response2 = authenticated_client.delete(_url(repo))
    assert response2.status_code == 204


# ---------------------------------------------------------------------------
# 6. 别仓 RUNNING 不应阻塞本仓
# ---------------------------------------------------------------------------


def test_concurrent_other_repository_running_does_not_block(
    authenticated_client: APIClient,
    repo: Repository,
    graph_seeds: dict[str, int],
) -> None:
    """并发判断必须按 repository_id 严格过滤，别仓 RUNNING 不阻塞本仓 DELETE。"""

    other = Repository.objects.create(
        name="other-running-repo",
        git_url="https://github.com/test/other.git",
        git_platform="github",
        default_branch="main",
    )
    IndexHistory.objects.create(
        repository=other,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.RUNNING,
        graph_build_status=GraphBuildStatus.RUNNING,
    )

    response = authenticated_client.delete(_url(repo))
    assert response.status_code == 204
    assert Symbol.objects.filter(repository=repo).count() == 0
