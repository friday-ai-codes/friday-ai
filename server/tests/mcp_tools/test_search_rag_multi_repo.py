"""search_rag_chunks 多仓 / 全仓检索守护测试（Phase 26 Plan 05，REPO-02）。

覆盖 REPO-02 多仓 MCP RAG 检索能力，且每仓仍经 Phase 22 ``search_rag`` chokepoint
fail-closed 排除：

- Test 1 多仓召回 + 来源标注：``repository_ids=[a,b]`` 跨仓召回，每条结果 repo_id 标注来源仓。
- Test 2 跨仓 fail-closed：某仓命中被排除文件（内置默认 ``*secret*.json``）跨仓不可见。
- Test 3 单仓向后兼容：仅 ``repository_id`` 时响应形状 / 行为与既有单仓一致。
- Test 4 all_repositories 范围：只检索已索引非删除仓（未索引 / 已删不在范围，不越权）。
- Test 5 不存在仓跳过：含无效 UUID 时有效仓正常召回，无效仓被跳过不致命。

测试经**真实** ``build_matcher_for_repo``（仅 builtin 默认），仅 mock embedding /
sparse / ``BranchAwareSearchService.search`` 的重型副作用，确保排除走真实 chokepoint。
设 ``ENABLE_GRAPHRAG_ENRICHMENT=False`` 强制走 ``_search_rag_only`` → ``search_rag`` 路径。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rest_framework.test import APIClient

from repositories.models import IndexStatus, Repository

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_matcher_cache() -> Any:
    """每个用例前后清空匹配器缓存，避免跨用例 / 跨 monkeypatch 污染。"""
    from services.exclusion import invalidate_matcher_cache

    invalidate_matcher_cache(None)
    yield
    invalidate_matcher_cache(None)


@pytest.fixture(autouse=True)
def _force_rag_only(settings: Any) -> None:
    """强制走 _search_rag_only → search_rag chokepoint（避免图谱编排重型依赖）。"""
    settings.ENABLE_GRAPHRAG_ENRICHMENT = False


def _make_indexed_repo(name: str) -> Repository:
    return Repository.objects.create(
        name=name,
        git_url=f"https://github.com/test/{name}.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )


def _item(file_path: str, *, score: float, chunk_index: int = 0) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "score": score,
        "payload": {
            "file_path": file_path,
            "chunk_index": chunk_index,
            "content": f"// {file_path}",
            "start_line": 1,
            "end_line": 2,
            "language": "python",
        },
    }


def _patch_rag_deps(
    monkeypatch: pytest.MonkeyPatch, *, results_by_repo: dict[str, list[dict[str, Any]]]
) -> None:
    """patch embedding / sparse / BranchAwareSearchService.search 的重型副作用。

    ``build_matcher_for_repo`` 保持真实实现，确保排除经真实 chokepoint 生效。
    """
    monkeypatch.setattr(
        "services.embedding.EmbeddingService.generate_embedding",
        AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    monkeypatch.setattr(
        "services.sparse_encoder.SparseEncoderService.encode",
        MagicMock(return_value={"indices": [1], "values": [1.0]}),
    )

    async def _search(repo_id: str, *a: Any, **kw: Any) -> list[dict[str, Any]]:
        return results_by_repo.get(str(repo_id), [])

    monkeypatch.setattr(
        "services.branch_search.BranchAwareSearchService.search",
        AsyncMock(side_effect=_search),
    )


# ============================================================================
# Test 1: 多仓召回 + 来源仓库标注
# ============================================================================


def test_multi_repo_recall_tags_source(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """repository_ids=[a,b] 跨仓召回，每条结果 repo_id 标注来源仓；response 回显 repository_ids。"""
    client, _ = mcp_client
    repo_a = _make_indexed_repo("repo-a")
    repo_b = _make_indexed_repo("repo-b")
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={
            str(repo_a.id): [_item("src/a.py", score=0.9)],
            str(repo_b.id): [_item("src/b.py", score=0.8)],
        },
    )

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_ids": [str(repo_a.id), str(repo_b.id)], "query": "auth"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body["repository_ids"]) == {str(repo_a.id), str(repo_b.id)}
    by_path = {r["file_path"]: r["repo_id"] for r in body["results"]}
    assert by_path["src/a.py"] == str(repo_a.id)
    assert by_path["src/b.py"] == str(repo_b.id)
    # 多仓模式下标量 repository_id 置 None（向后兼容字段仍在）
    assert body["repository_id"] is None


# ============================================================================
# Test 2: 跨仓 fail-closed（被排除文件跨仓不可见）
# ============================================================================


def test_multi_repo_failclosed_excludes_secret_across_repos(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仓 b 命中内置默认排除文件（config/secret.json）→ 跨仓结果中不可见。"""
    client, _ = mcp_client
    repo_a = _make_indexed_repo("repo-a")
    repo_b = _make_indexed_repo("repo-b")
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={
            str(repo_a.id): [_item("src/a.py", score=0.9)],
            str(repo_b.id): [
                _item("config/secret.json", score=0.95),
                _item("src/b.py", score=0.7),
            ],
        },
    )

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_ids": [str(repo_a.id), str(repo_b.id)], "query": "token"},
        format="json",
    )

    assert response.status_code == 200
    import json as _json

    body = response.json()
    blob = _json.dumps(body)
    assert "secret.json" not in blob
    paths = {r["file_path"] for r in body["results"]}
    assert paths == {"src/a.py", "src/b.py"}


# ============================================================================
# Test 3: 单仓向后兼容（省略多仓参数）
# ============================================================================


def test_single_repo_backward_compatible(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅传 repository_id → 响应形状与既有单仓一致（repository_id 字段在、results 仅来自该仓）。"""
    client, _ = mcp_client
    repo_a = _make_indexed_repo("repo-a")
    _make_indexed_repo("repo-b")  # 存在但不应被检索
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={str(repo_a.id): [_item("src/a.py", score=0.9)]},
    )

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_id": str(repo_a.id), "query": "auth"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == str(repo_a.id)
    assert body["repository_ids"] == [str(repo_a.id)]
    assert {r["repo_id"] for r in body["results"]} == {str(repo_a.id)}
    assert {r["file_path"] for r in body["results"]} == {"src/a.py"}


# ============================================================================
# Test 4: all_repositories 范围（仅已索引非删除仓）
# ============================================================================


def test_all_repositories_only_indexed_non_deleted(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """all_repositories=true 只检索已索引非删除仓（未索引 / 已删除仓不在范围，不越权）。"""
    client, _ = mcp_client
    repo_a = _make_indexed_repo("repo-a-indexed")
    # 未索引仓：不应进入检索范围
    Repository.objects.create(
        name="repo-not-indexed",
        git_url="https://github.com/test/not-indexed.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.NOT_INDEXED,
    )
    # 已删除仓（即便 INDEXED）：不应进入检索范围
    Repository.objects.create(
        name="repo-deleted",
        git_url="https://github.com/test/deleted.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        is_deleted=True,
    )
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={str(repo_a.id): [_item("src/a.py", score=0.9)]},
    )

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"all_repositories": True, "query": "auth"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_ids"] == [str(repo_a.id)]
    assert {r["repo_id"] for r in body["results"]} == {str(repo_a.id)}


# ============================================================================
# Test 5: 不存在仓跳过（不致命）
# ============================================================================


def test_multi_repo_skips_nonexistent_repo(
    mcp_client: tuple[APIClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """repository_ids 含不存在 UUID + 有效仓 → 有效仓正常召回，不存在仓被跳过不致命。"""
    client, _ = mcp_client
    repo_a = _make_indexed_repo("repo-a")
    ghost_id = str(uuid.uuid4())
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={str(repo_a.id): [_item("src/a.py", score=0.9)]},
    )

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_ids": [str(repo_a.id), ghost_id], "query": "auth"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_ids"] == [str(repo_a.id)]
    assert ghost_id not in {r["repo_id"] for r in body["results"]}
    assert {r["file_path"] for r in body["results"]} == {"src/a.py"}
