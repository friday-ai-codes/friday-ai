"""容器知识 MCP 链路服务端回归测试（Phase 103-02 AGENT-02）。

两块覆盖：

**第七面排除回归**：容器知识 MCP 白名单工具 = ``get_repository_file`` /
``grep_repository`` / ``search_rag_chunks`` 三视图（读仓面），排除面（EXCL-02
fail-closed）经服务端 HTTP 工具面天然继承——v0.5 六面（索引/browse/RAG/get_file/
grep/list）之外补"容器白名单视角"的第七面回归钉：被排除文件经容器转调路径
同样不可见、不泄明文。fixture 与调用方式镜像 ``test_mcp_exclusion.py`` 先例。

**关联键**：容器 handler 请求带 ``X-Friday-Session-Id``（dispatch 链 task_id），
服务端 ``begin_interaction_run`` 读头入 ``InteractionRun.raw_request['task_session_id']``，
run/task 可关联查询；不带头 → raw_request 无该键（存量行为零变化）。
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionRun

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


def _rag_item(file_path: str, *, score: float, content: str = "x") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "score": score,
        "payload": {
            "file_path": file_path,
            "chunk_index": 0,
            "content": content,
            "start_line": 1,
            "end_line": 2,
            "language": "text",
        },
    }


def _patch_rag_deps(monkeypatch: pytest.MonkeyPatch, *, results: list[dict[str, Any]]) -> None:
    """patch embedding / sparse / BranchAwareSearchService.search 重型副作用。

    **不** mock ``build_matcher_for_repo``：让 ``search_rag`` 内的真实匹配器
    （内置全局默认规则，如 ``.env``）执行 fail-closed 过滤——这正是被测面。
    """
    monkeypatch.setattr(
        "services.embedding.EmbeddingService.generate_embedding",
        AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    monkeypatch.setattr(
        "services.sparse_encoder.SparseEncoderService.encode",
        MagicMock(return_value={"indices": [1], "values": [1.0]}),
    )
    monkeypatch.setattr(
        "services.branch_search.BranchAwareSearchService.search",
        AsyncMock(return_value=results),
    )


# =========================================================================
# 第七面排除回归：容器知识 MCP 白名单工具 = 此三视图，排除面天然继承，
# 此为容器链第七面回归钉（fail-closed 继承断言）。
# =========================================================================


def test_container_get_repository_file_excluded_blocks_no_plaintext(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) get_repository_file 读被排除文件 → 拒绝且响应不含文件明文。

    容器知识 MCP 白名单工具 = get_repository_file/grep_repository/search_rag_chunks
    三视图，排除面天然继承，此为容器链第七面回归钉。
    """
    client, _ = mcp_client
    monkeypatch.setattr(
        "mcp_tools.views.GetRepositoryFileView._read_from_mirror",
        AsyncMock(return_value=(".env", "SECRET_TOKEN=containerleak\n", _snapshot())),
    )

    response = client.post(
        "/api/mcp/tools/get_repository_file/",
        {"repository_id": str(indexed_repository.id), "file_path": ".env"},
        format="json",
        HTTP_X_FRIDAY_SESSION_ID="task-abc",
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "file_excluded"
    assert "content" not in body
    assert "containerleak" not in json.dumps(body)


def test_container_grep_repository_filters_excluded_paths(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(b) grep_repository 命中集不含被排除路径（matches / file_counts 均剔除）。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "mcp_tools.views.ensure_mirror_commit",
        AsyncMock(return_value=_snapshot()),
    )
    monkeypatch.setattr(
        "mcp_tools.views.grep_mirror",
        AsyncMock(
            return_value={
                "engine": "git-grep",
                "matches": [
                    {
                        "file_path": "src/main.py",
                        "line": 1,
                        "kind": "match",
                        "content": "token = 1",
                    },
                    {
                        "file_path": ".env",
                        "line": 1,
                        "kind": "match",
                        "content": "TOKEN=containergrepleak",
                    },
                ],
                "total_matches": 2,
                "files_with_matches": 2,
                "file_counts": [
                    {"file_path": ".env", "match_count": 1},
                    {"file_path": "src/main.py", "match_count": 1},
                ],
                "truncated": False,
            }
        ),
    )

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "token"},
        format="json",
        HTTP_X_FRIDAY_SESSION_ID="task-abc",
    )

    assert response.status_code == 200
    blob = json.dumps(response.json())
    assert ".env" not in blob
    assert "containergrepleak" not in blob
    assert {m["file_path"] for m in response.json()["repositories"][0]["matches"]} == {
        "src/main.py"
    }


def test_container_search_rag_chunks_filters_excluded_candidates(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
) -> None:
    """(c) search_rag_chunks 返回 chunks 不含被排除路径内容。

    mock 底层 provider（embedding/sparse/BranchAwareSearchService）返回含 ``.env``
    的候选，让 ``HybridSearchService`` → ``search_rag`` 内真实匹配器（内置全局默认）
    fail-closed 滤除——view 侧无法绕过该 chokepoint。
    """
    client, _ = mcp_client
    # 强制 rag-only 路径（不依赖 provider 图谱能力），排除过滤在 search_rag 内执行。
    settings.ENABLE_GRAPHRAG_ENRICHMENT = False
    _patch_rag_deps(
        monkeypatch,
        results=[
            _rag_item(".env", score=0.95, content="API_TOKEN=containerragleak"),
            _rag_item("src/main.py", score=0.8, content="def main(): pass"),
        ],
    )

    response = client.post(
        "/api/mcp/tools/search_rag_chunks/",
        {"repository_id": str(indexed_repository.id), "query": "token"},
        format="json",
        HTTP_X_FRIDAY_SESSION_ID="task-abc",
    )

    assert response.status_code == 200
    body = response.json()
    paths = {r["file_path"] for r in body["results"]}
    assert ".env" not in paths
    assert "src/main.py" in paths
    assert "containerragleak" not in json.dumps(body)


# =========================================================================
# 关联键：X-Friday-Session-Id → InteractionRun.raw_request["task_session_id"]
# =========================================================================


def test_session_id_header_recorded_in_run_raw_request(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """带 X-Friday-Session-Id 调 MCP 工具端点 → run.raw_request['task_session_id'] 等于头值。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "mcp_tools.views.ensure_mirror_commit",
        AsyncMock(return_value=_snapshot()),
    )
    monkeypatch.setattr(
        "mcp_tools.views.grep_mirror",
        AsyncMock(
            return_value={
                "engine": "git-grep",
                "matches": [],
                "total_matches": 0,
                "files_with_matches": 0,
                "file_counts": [],
                "truncated": False,
            }
        ),
    )

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "x"},
        format="json",
        HTTP_X_FRIDAY_SESSION_ID="task-session-42",
    )

    assert response.status_code == 200
    run = InteractionRun.objects.get(run_id=response.json()["run_id"])
    assert run.raw_request["task_session_id"] == "task-session-42"
    # 可按关联键反查（run/task 关联查询路径）
    assert InteractionRun.objects.filter(raw_request__task_session_id="task-session-42").exists()


def test_oversize_session_id_header_clamped_to_64(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超长 X-Friday-Session-Id 截断到 64 字符入库（103 审查 IN-05：合法值恒 ≤64，
    恶意/异常调用方不得塞 KB 级串污染留痕）。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "mcp_tools.views.ensure_mirror_commit",
        AsyncMock(return_value=_snapshot()),
    )
    monkeypatch.setattr(
        "mcp_tools.views.grep_mirror",
        AsyncMock(
            return_value={
                "engine": "git-grep",
                "matches": [],
                "total_matches": 0,
                "files_with_matches": 0,
                "file_counts": [],
                "truncated": False,
            }
        ),
    )

    oversize = "s" * 500
    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "x"},
        format="json",
        HTTP_X_FRIDAY_SESSION_ID=oversize,
    )

    assert response.status_code == 200
    run = InteractionRun.objects.get(run_id=response.json()["run_id"])
    assert run.raw_request["task_session_id"] == "s" * 64


def test_no_session_id_header_leaves_raw_request_unchanged(
    mcp_client: tuple[APIClient, str],
    indexed_repository: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不带头 → raw_request 无 task_session_id 键（存量行为零变化）。"""
    client, _ = mcp_client
    monkeypatch.setattr(
        "mcp_tools.views.ensure_mirror_commit",
        AsyncMock(return_value=_snapshot()),
    )
    monkeypatch.setattr(
        "mcp_tools.views.grep_mirror",
        AsyncMock(
            return_value={
                "engine": "git-grep",
                "matches": [],
                "total_matches": 0,
                "files_with_matches": 0,
                "file_counts": [],
                "truncated": False,
            }
        ),
    )

    response = client.post(
        "/api/mcp/tools/grep_repository/",
        {"repository_id": str(indexed_repository.id), "pattern": "x"},
        format="json",
    )

    assert response.status_code == 200
    run = InteractionRun.objects.get(run_id=response.json()["run_id"])
    assert "task_session_id" not in run.raw_request
