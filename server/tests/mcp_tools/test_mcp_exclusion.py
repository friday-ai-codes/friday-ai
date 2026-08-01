"""MCP HTTP 读取面 fail-closed 排除守护测试（Phase 22 / EXCL-02）。

覆盖外部暴露的四个直读 bare 镜像 / 索引的 MCP 工具：
- ``get_repository_file``：镜像路径 + 索引回退路径，被排除文件 → 「已排除」错误、无 plaintext。
- ``grep_repository``：grep_mirror 结果按 file_path 过滤 matches / file_counts。
- ``list_repository_files``：被排除文件 / 纯由被排除文件构成的目录不出现。
- ``find_related_chunks``：返回邻居前过滤被排除文件（防御性兜底）。

构造的被排除文件全部命中内置全局默认（如 ``.env`` / ``secrets/``），即「开箱即用」断言：
无任何 per-repo 规则也不可见。所有断言均验证响应体不含被排除文件的路径 / 内容 / 命中行。
"""

from __future__ import annotations

import importlib
import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from rest_framework.test import APIClient

from code_relations.models import ChunkRegistry
from repositories.models import FileIndex
from services.retrieval.types import NeighborMetadata

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_matcher_cache() -> Any:
    """每个用例前后清空匹配器缓存，避免跨用例 / 跨 monkeypatch 污染。"""
    from services.exclusion import invalidate_matcher_cache

    invalidate_matcher_cache(None)
    yield
    invalidate_matcher_cache(None)


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(ref="main", commit_sha="a" * 40, matches_index=True)


# === get_repository_file：镜像路径 ===


def test_get_file_mirror_excluded_blocks_no_plaintext(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """镜像命中被排除文件 → file_excluded，绝不返回 content。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "services.repo_file_read._aread_from_mirror",
        AsyncMock(return_value=(".env", "SECRET_TOKEN=supersecret\n", _snapshot())),
    )

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": ".env"},
        format="json",
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "file_excluded"
    assert "content" not in body
    assert "supersecret" not in json.dumps(body)


def test_get_file_mirror_suffix_resolution_cannot_bypass(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """后缀解析出的 resolved_path 命中排除 → 同样拒读（防绕过）。

    requested ``env`` 本身不命中任何规则，但解析到的真实路径 ``.env`` 命中内置默认。
    """
    client, _ = mcp_client
    monkeypatch.setattr(
        "services.repo_file_read._aread_from_mirror",
        AsyncMock(return_value=(".env", "SECRET=leak\n", _snapshot())),
    )

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": "env"},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "file_excluded"
    assert "leak" not in json.dumps(response.json())


# === get_repository_file：索引回退路径（autouse 镜像禁用 → 自然走索引）===


def test_get_file_index_fallback_excluded_blocks(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """镜像不可用回退索引时，被排除文件同样拒读、无 content。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "services.repo_file_read._scroll_file_from_collection",
        AsyncMock(
            return_value=[
                {
                    "chunk_index": 0,
                    "content": "SECRET=indexleak",
                    "start_line": 1,
                    "end_line": 1,
                    "language": "text",
                }
            ]
        ),
    )

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": ".env"},
        format="json",
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "file_excluded"
    assert "indexleak" not in json.dumps(body)


def test_get_file_non_excluded_still_readable(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非排除文件不受影响，正常返回内容（防止过度拦截）。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "services.repo_file_read._scroll_file_from_collection",
        AsyncMock(
            return_value=[
                {
                    "chunk_index": 0,
                    "content": "print('hi')",
                    "start_line": 1,
                    "end_line": 1,
                    "language": "python",
                }
            ]
        ),
    )

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": "src/main.py"},
        format="json",
    )

    assert response.status_code == 200
    assert "hi" in response.json()["content"]


def test_get_file_fail_closed_on_matcher_error(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """匹配器构造异常 → fail-closed 拒读，不降级返回明文。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "services.repo_file_read._scroll_file_from_collection",
        AsyncMock(
            return_value=[
                {
                    "chunk_index": 0,
                    "content": "SECRET=failopen",
                    "start_line": 1,
                    "end_line": 1,
                    "language": "text",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "services.repo_file_read.build_matcher_for_repo",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": "src/main.py"},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "file_excluded"
    assert "failopen" not in json.dumps(response.json())


# === grep_repository ===


def _patch_grep(monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]) -> None:
    monkeypatch.setattr(
        "mcp_tools.views.ensure_mirror_commit",
        AsyncMock(return_value=_snapshot()),
    )
    monkeypatch.setattr("mcp_tools.views.grep_mirror", AsyncMock(return_value=result))


def test_grep_filters_excluded_matches_and_counts(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """grep_mirror 返回含被排除文件命中行 → 响应剔除其 matches / file_counts。"""
    client, _ = mcp_client
    _patch_grep(
        monkeypatch,
        {
            "engine": "git-grep",
            "matches": [
                {"file_path": "src/main.py", "line": 1, "kind": "match", "content": "token = 1"},
                {"file_path": ".env", "line": 1, "kind": "match", "content": "TOKEN=leaked"},
            ],
            "total_matches": 2,
            "files_with_matches": 2,
            "file_counts": [
                {"file_path": ".env", "match_count": 1},
                {"file_path": "src/main.py", "match_count": 1},
            ],
            "truncated": False,
        },
    )

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "token"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    blob = json.dumps(body)
    assert ".env" not in blob
    assert "leaked" not in blob
    assert body["total_matches"] == 1
    entry = body["repositories"][0]
    assert entry["files_with_matches"] == 1
    assert {m["file_path"] for m in entry["matches"]} == {"src/main.py"}


def test_grep_files_only_filters_excluded(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """files_only 模式下被排除文件不出现在 files 计数中。"""
    client, _ = mcp_client
    _patch_grep(
        monkeypatch,
        {
            "engine": "git-grep",
            "matches": [],
            "total_matches": 3,
            "files_with_matches": 2,
            "file_counts": [
                {"file_path": ".env", "match_count": 2},
                {"file_path": "src/main.py", "match_count": 1},
            ],
            "truncated": False,
        },
    )

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "x", "output_mode": "files_only"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert ".env" not in json.dumps(body)
    entry = body["repositories"][0]
    assert entry["files"] == [{"file_path": "src/main.py", "match_count": 1}]
    assert entry["files_with_matches"] == 1
    assert body["total_matches"] == 1


# === list_repository_files ===


def test_list_excludes_files_and_pure_excluded_dirs(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
) -> None:
    """被排除文件不列出；纯由被排除文件构成的目录不出现。"""
    client, _ = mcp_client
    FileIndex.objects.create(repository=indexed_repository, file_path=".env", file_hash="h-env")
    FileIndex.objects.create(
        repository=indexed_repository, file_path="secrets/key.txt", file_hash="h-secret"
    )

    response = client.post(
        "/api/mcp/tools/list_repository_files/",
        {"repository_id": str(indexed_repository.id), "recursive": False},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    paths = {item["path"] for item in body["items"]}
    assert ".env" not in paths
    assert "secrets" not in paths
    assert "src" in paths


def test_list_recursive_excludes_files(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
) -> None:
    client, _ = mcp_client
    FileIndex.objects.create(repository=indexed_repository, file_path=".env", file_hash="h-env")

    response = client.post(
        "/api/mcp/tools/list_repository_files/",
        {"repository_id": str(indexed_repository.id), "recursive": True},
        format="json",
    )

    assert response.status_code == 200
    paths = {item["path"] for item in response.json()["items"]}
    assert ".env" not in paths
    assert "src/main.py" in paths


# === find_related_chunks（Task 2 防御性兜底）===


def _patch_find_related(monkeypatch: pytest.MonkeyPatch, file_path: str) -> None:
    find_mock = AsyncMock(
        return_value=[
            NeighborMetadata(
                chunk_id=str(uuid.uuid4()),
                file_path=file_path,
                line_start=1,
                line_end=2,
                edge_type="CALL",
                weight=0.7,
                reason="via direct call",
                hop=1,
            )
        ]
    )
    module = importlib.import_module("services.retrieval.find_related")
    monkeypatch.setattr(module, "find_related", find_mock)


def test_find_related_filters_excluded_neighbor(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """find_related_chunks 不返回被排除文件的邻居。"""
    client, _ = mcp_client
    ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="hash",
        repository=indexed_repository,
        branch_name="",
        file_path="src/main.py",
        chunk_index=0,
    )
    _patch_find_related(monkeypatch, ".env")

    response = client.post(
        "/api/mcp/tools/find_related_chunks/",
        {"repository_id": str(indexed_repository.id), "file_path": "src/main.py", "hops": 1},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["related_chunks"] == []
    assert ".env" not in json.dumps(body)


# === 跨工具守护：同一被排除文件在四个 MCP 工具中均不可见 ===


def test_excluded_file_invisible_across_all_mcp_tools(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单一被排除文件（.env）在 grep / get_file / list / find_related 四面均不可见。"""
    client, _ = mcp_client
    secret_path = ".env"
    secret_content = "API_TOKEN=crosstoolleak"

    # 1) grep_repository
    _patch_grep(
        monkeypatch,
        {
            "engine": "git-grep",
            "matches": [
                {"file_path": secret_path, "line": 1, "kind": "match", "content": secret_content}
            ],
            "total_matches": 1,
            "files_with_matches": 1,
            "file_counts": [{"file_path": secret_path, "match_count": 1}],
            "truncated": False,
        },
    )
    grep_resp = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "API_TOKEN"},
        format="json",
    )
    assert grep_resp.status_code == 200
    assert "crosstoolleak" not in json.dumps(grep_resp.json())
    assert secret_path not in json.dumps(grep_resp.json())

    # 2) get_repository_file（镜像路径）
    monkeypatch.setattr(
        "services.repo_file_read._aread_from_mirror",
        AsyncMock(return_value=(secret_path, secret_content + "\n", _snapshot())),
    )
    file_resp = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": secret_path},
        format="json",
    )
    assert file_resp.status_code == 404
    assert file_resp.json()["error_code"] == "file_excluded"
    assert "crosstoolleak" not in json.dumps(file_resp.json())

    # 3) list_repository_files
    FileIndex.objects.create(
        repository=indexed_repository, file_path=secret_path, file_hash="h-secret"
    )
    list_resp = client.post(
        "/api/mcp/tools/list_repository_files/",
        {"repository_id": str(indexed_repository.id), "recursive": True},
        format="json",
    )
    assert list_resp.status_code == 200
    assert secret_path not in {item["path"] for item in list_resp.json()["items"]}

    # 4) find_related_chunks
    ChunkRegistry.objects.create(
        chunk_id=uuid.uuid4(),
        content_hash="hash",
        repository=indexed_repository,
        branch_name="",
        file_path="src/main.py",
        chunk_index=0,
    )
    _patch_find_related(monkeypatch, secret_path)
    related_resp = client.post(
        "/api/mcp/tools/find_related_chunks/",
        {"repository_id": str(indexed_repository.id), "file_path": "src/main.py", "hops": 1},
        format="json",
    )
    assert related_resp.status_code == 200
    assert related_resp.json()["related_chunks"] == []
    assert secret_path not in json.dumps(related_resp.json())
