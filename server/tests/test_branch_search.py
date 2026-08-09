"""BranchAwareSearchService 单元测试。

测试分支感知检索合并逻辑：overlay + base 并行查询、BranchFileIndex 过滤、
去重、排序、降级路径。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.branch_search import BranchAwareSearchService


def _make_result(
    file_path: str,
    chunk_index: int,
    score: float,
    *,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造模拟搜索结果。"""
    payload: dict[str, Any] = {
        "file_path": file_path,
        "chunk_index": chunk_index,
    }
    if extra_payload:
        payload.update(extra_payload)
    return {"id": f"{file_path}:{chunk_index}", "score": score, "payload": payload}


def _make_branch_index(
    *,
    is_base: bool = False,
    status: str = "indexed",
    collection_name: str | None = "code_index_repo1_br_feat_abc12345",
    repository_id: str = "repo1",
    branch_name: str = "feature/x",
) -> MagicMock:
    """构造模拟 RepositoryBranchIndex 对象。"""
    bi = MagicMock()
    bi.is_base_branch = is_base
    bi.status = status
    bi.collection_name = collection_name
    bi.repository_id = repository_id
    bi.branch_name = branch_name
    return bi


# ---------------------------------------------------------------------------
# 辅助 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _patch_branch_utils():
    """统一 patch branch_utils async 函数。"""
    with (
        patch("services.branch_search.is_branch_index_enabled_async") as mock_enabled,
        patch("services.branch_search.resolve_branch_for_query") as mock_resolve,
        patch("services.branch_search.get_branch_file_changes") as mock_changes,
    ):
        mock_enabled.return_value = True
        mock_changes.return_value = (set(), set(), set())
        yield mock_enabled, mock_resolve, mock_changes


@pytest.fixture()
def _patch_qdrant():
    """统一 patch QdrantService 搜索方法。"""
    with (
        patch("services.branch_search.QdrantService") as mock_qs,
    ):
        mock_qs.get_collection_name.return_value = "code_index_repo1"
        mock_qs.search.return_value = []
        mock_qs.hybrid_search.return_value = []
        mock_qs.search_by_name.return_value = []
        mock_qs.hybrid_search_by_name.return_value = []
        yield mock_qs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBranchAwareSearchService:
    """BranchAwareSearchService.search 行为测试。"""

    async def test_base_branch_direct_search(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """base 分支查询 → 直接调用单 collection 搜索，不做合并。"""
        mock_enabled, mock_resolve, _ = _patch_branch_utils
        mock_qs = _patch_qdrant

        base_bi = _make_branch_index(is_base=True, branch_name="main")
        mock_resolve.return_value = ("main", base_bi)
        mock_qs.search.return_value = [_make_result("a.py", 0, 0.9)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="main"
        )

        mock_qs.search.assert_called_once()
        assert len(results) == 1
        assert results[0]["payload"]["file_path"] == "a.py"

    async def test_inherited_branch_uses_base(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """inherited 状态分支 → 直接查 base collection。"""
        _, mock_resolve, _ = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index(status="inherited", is_base=False)
        mock_resolve.return_value = ("dev", bi)
        mock_qs.search.return_value = [_make_result("b.py", 0, 0.8)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="dev"
        )

        mock_qs.search.assert_called_once()
        assert len(results) == 1

    async def test_feature_branch_merge(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """功能分支 → 并行查 overlay + base → 合并结果。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = ({"new.py"}, set(), set())

        mock_qs.search_by_name.return_value = [_make_result("new.py", 0, 0.95)]
        mock_qs.search.return_value = [_make_result("old.py", 0, 0.85)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="feature/x"
        )

        assert len(results) == 2
        assert results[0]["score"] >= results[1]["score"]

    async def test_deleted_file_filtered(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """base 结果中 file_path 在 deleted_files 集合 → 被过滤。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = (set(), set(), {"removed.py"})

        mock_qs.search_by_name.return_value = []
        mock_qs.search.return_value = [
            _make_result("removed.py", 0, 0.9),
            _make_result("kept.py", 0, 0.8),
        ]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="feature/x"
        )

        paths = [r["payload"]["file_path"] for r in results]
        assert "removed.py" not in paths
        assert "kept.py" in paths

    async def test_modified_file_overlay_wins(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """base 结果中 modified 文件 → 被过滤，overlay 版本保留。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = (set(), {"mod.py"}, set())

        mock_qs.search_by_name.return_value = [_make_result("mod.py", 0, 0.95)]
        mock_qs.search.return_value = [_make_result("mod.py", 0, 0.7)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="feature/x"
        )

        assert len(results) == 1
        assert results[0]["score"] == 0.95

    async def test_chunk_dedup_by_file_path_and_index(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """同 (file_path, chunk_index) 不重复，overlay 优先。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = (set(), set(), set())

        mock_qs.search_by_name.return_value = [_make_result("file.py", 0, 0.9)]
        mock_qs.search.return_value = [_make_result("file.py", 0, 0.8)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="feature/x"
        )

        assert len(results) == 1
        assert results[0]["score"] == 0.9

    async def test_results_sorted_by_score(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """合并结果按 score 降序排序。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = (set(), set(), set())

        mock_qs.search_by_name.return_value = [
            _make_result("a.py", 0, 0.5),
            _make_result("b.py", 0, 0.95),
        ]
        mock_qs.search.return_value = [
            _make_result("c.py", 0, 0.75),
        ]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="feature/x"
        )

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_results_limited_to_top_k(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """合并后截断到 top_k。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = (set(), set(), set())

        mock_qs.search_by_name.return_value = [
            _make_result(f"o{i}.py", 0, 0.9 - i * 0.01) for i in range(5)
        ]
        mock_qs.search.return_value = [
            _make_result(f"b{i}.py", 0, 0.8 - i * 0.01) for i in range(5)
        ]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="feature/x", top_k=3
        )

        assert len(results) == 3

    async def test_overlay_collection_missing_fallback(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """overlay 查询异常 → 降级返回 base 结果 + log warning。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = (set(), set(), set())

        mock_qs.search_by_name.side_effect = Exception("collection not found")
        mock_qs.search.return_value = [_make_result("base.py", 0, 0.85)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name="feature/x"
        )

        assert len(results) == 1
        assert results[0]["payload"]["file_path"] == "base.py"

    async def test_branch_index_not_enabled_fallback(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """无 RepositoryBranchIndex → 走旧路径。"""
        mock_enabled, _, _ = _patch_branch_utils
        mock_qs = _patch_qdrant

        mock_enabled.return_value = False
        mock_qs.search.return_value = [_make_result("legacy.py", 0, 0.9)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10
        )

        mock_qs.search.assert_called_once()
        assert results[0]["payload"]["file_path"] == "legacy.py"

    async def test_no_branch_specified_uses_base(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """branch_name=None → 回退到 base_branch。"""
        _, mock_resolve, _ = _patch_branch_utils
        mock_qs = _patch_qdrant

        base_bi = _make_branch_index(is_base=True, branch_name="main")
        mock_resolve.return_value = ("main", base_bi)
        mock_qs.search.return_value = [_make_result("main.py", 0, 0.9)]

        results = await BranchAwareSearchService.search(
            "repo1", [0.1] * 10, branch_name=None
        )

        mock_qs.search.assert_called_once()
        assert len(results) == 1

    async def test_hybrid_search_mode(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """传入 query_sparse 时使用 hybrid_search_by_name。"""
        _, mock_resolve, mock_changes = _patch_branch_utils
        mock_qs = _patch_qdrant

        bi = _make_branch_index()
        mock_resolve.return_value = ("feature/x", bi)
        mock_changes.return_value = (set(), set(), set())

        mock_qs.hybrid_search_by_name.return_value = [
            _make_result("h.py", 0, 0.92)
        ]
        mock_qs.hybrid_search.return_value = [_make_result("hb.py", 0, 0.88)]

        sparse = {"indices": [1, 2], "values": [0.5, 0.3]}
        results = await BranchAwareSearchService.search(
            "repo1",
            [0.1] * 10,
            query_sparse=sparse,
            branch_name="feature/x",
        )

        mock_qs.hybrid_search_by_name.assert_called_once()
        mock_qs.hybrid_search.assert_called_once()
        assert len(results) == 2

    async def test_default_filters_exclude_commit_kind(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """代码检索默认排除 kind=commit，避免提交摘要挤占源码召回。"""
        from services.qdrant_service import QdrantService

        mock_enabled, _, _ = _patch_branch_utils
        mock_qs = _patch_qdrant
        mock_enabled.return_value = False
        mock_qs.search.return_value = []

        await BranchAwareSearchService.search("repo1", [0.1] * 10)

        filters = mock_qs.search.call_args.kwargs.get("filters") or {}
        assert filters.get(QdrantService.EXCLUDE_KEY) == {"kind": "commit"}

    async def test_explicit_exclude_key_respected(
        self, _patch_branch_utils, _patch_qdrant
    ):
        """调用方显式传 EXCLUDE_KEY（含空 dict）时不覆盖其意图。"""
        from services.qdrant_service import QdrantService

        mock_enabled, _, _ = _patch_branch_utils
        mock_qs = _patch_qdrant
        mock_enabled.return_value = False
        mock_qs.search.return_value = []

        await BranchAwareSearchService.search(
            "repo1",
            [0.1] * 10,
            filters={QdrantService.EXCLUDE_KEY: {}},
        )

        filters = mock_qs.search.call_args.kwargs.get("filters") or {}
        assert filters.get(QdrantService.EXCLUDE_KEY) == {}
