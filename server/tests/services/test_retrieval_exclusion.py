"""RAG 检索面 fail-closed 排除守护测试（Phase 22 Plan 03，EXCL-02）。

覆盖 RAG 单一 chokepoint + 图谱邻居渲染两块：
- ``search_rag``：在收集 / 截断前对每项按 ``repository_id + payload.file_path`` 判定排除，
  命中即丢弃 + ``exclusion.blocked`` surface="rag"；matcher 每 repo 只建一次；判定异常 fail-closed。
- ``HybridSearchService._search_graph_capable``：图谱邻居（hop1/hop2/cross-repo）渲染剔除
  被排除 file_path，``graph_context`` / ``final_context`` / 返回的邻居列表均不含被排除项。

另含跨面 fail-closed 守护测试（Task 3）：同一被排除文件在 索引扫描 / browse_file_content /
RAG 三面均不可见。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.exclusion import ExclusionMatcher, ExclusionRuleSpec
from services.retrieval.rag_search import search_rag
from services.retrieval.types import LayerSnapshot, NeighborMetadata


def _item(
    file_path: str, *, score: float, chunk_index: int = 0, content: str = "x"
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "score": score,
        "payload": {
            "file_path": file_path,
            "chunk_index": chunk_index,
            "content": content,
        },
    }


def _patch_rag_deps(
    monkeypatch: pytest.MonkeyPatch, *, results_by_repo: dict[str, list[dict[str, Any]]]
) -> None:
    """patch embedding / sparse / BranchAwareSearchService.search 的重型副作用。"""
    monkeypatch.setattr(
        "services.embedding.EmbeddingService.generate_embedding",
        AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    monkeypatch.setattr(
        "services.sparse_encoder.SparseEncoderService.encode",
        MagicMock(return_value={"indices": [1], "values": [1.0]}),
    )

    async def _search(repo_id: str, *a: Any, **kw: Any) -> list[dict[str, Any]]:
        return results_by_repo.get(repo_id, [])

    monkeypatch.setattr(
        "services.branch_search.BranchAwareSearchService.search",
        AsyncMock(side_effect=_search),
    )


def _builtin_matcher(repo_id: str = "") -> ExclusionMatcher:
    # 用 ``*.env`` 让根 ``.env`` 与嵌套 / 同名变体（如 ``secrets.env``）均命中，
    # 据此验证 hop1（``.env``）与 hop2（``secrets.env``）被排除邻居均被剔除。
    return ExclusionMatcher(
        [ExclusionRuleSpec(pattern="*.env", rule_type="glob", source="global")],
        repository_id=repo_id,
    )


# ============================================================================
# Task 1a: search_rag fail-closed 过滤
# ============================================================================


async def test_search_rag_drops_excluded_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """命中排除规则的 file_path 不进入 LayerSnapshot.items，正常文件保留。"""
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={
            "repo-a": [
                _item("src/app.py", score=0.9),
                _item(".env", score=0.95),
            ]
        },
    )
    monkeypatch.setattr(
        "services.retrieval.rag_search.build_matcher_for_repo",
        AsyncMock(return_value=_builtin_matcher("repo-a")),
    )

    snap = await search_rag("q", repo_ids=["repo-a"])

    paths = {it["payload"]["file_path"] for it in snap.items}
    assert paths == {"src/app.py"}
    assert ".env" not in paths


async def test_search_rag_logs_exclusion_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """命中排除产生 exclusion.blocked surface="rag" 审计埋点。"""
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={"repo-a": [_item(".env", score=0.9)]},
    )
    monkeypatch.setattr(
        "services.retrieval.rag_search.build_matcher_for_repo",
        AsyncMock(return_value=_builtin_matcher("repo-a")),
    )
    log_mock = MagicMock()
    monkeypatch.setattr("services.retrieval.rag_search.log_exclusion_blocked", log_mock)

    await search_rag("q", repo_ids=["repo-a"])

    assert log_mock.called
    assert log_mock.call_args.kwargs["surface"] == "rag"


async def test_search_rag_builds_matcher_once_per_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个 repo 的 matcher 只构建一次（避免逐项加载）。"""
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={
            "repo-a": [_item("a.py", score=0.9), _item("b.py", score=0.8)],
            "repo-b": [_item("c.py", score=0.7)],
        },
    )
    build_mock = AsyncMock(side_effect=lambda rid: _builtin_matcher(rid))
    monkeypatch.setattr("services.retrieval.rag_search.build_matcher_for_repo", build_mock)

    await search_rag("q", repo_ids=["repo-a", "repo-b"])

    assert build_mock.await_count == 2
    assert {c.args[0] for c in build_mock.await_args_list} == {"repo-a", "repo-b"}


async def test_search_rag_failclosed_on_matcher_judgement_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """matcher.is_excluded 抛异常 → 该项被丢弃（fail-closed），不向上抛。"""
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={"repo-a": [_item("src/app.py", score=0.9)]},
    )
    boom_matcher = MagicMock()
    boom_matcher.is_excluded.side_effect = RuntimeError("matcher exploded")
    monkeypatch.setattr(
        "services.retrieval.rag_search.build_matcher_for_repo",
        AsyncMock(return_value=boom_matcher),
    )

    snap = await search_rag("q", repo_ids=["repo-a"])

    assert snap.status == "ok"
    assert snap.items == []


async def test_search_rag_failclosed_on_matcher_build_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_matcher_for_repo 抛异常 → 整个 repo 结果不可见（fail-closed），不向上抛。"""
    _patch_rag_deps(
        monkeypatch,
        results_by_repo={"repo-a": [_item("src/app.py", score=0.9)]},
    )
    monkeypatch.setattr(
        "services.retrieval.rag_search.build_matcher_for_repo",
        AsyncMock(side_effect=RuntimeError("db down")),
    )

    snap = await search_rag("q", repo_ids=["repo-a"])

    assert snap.status == "ok"
    assert snap.items == []


# ============================================================================
# Task 1b: 图谱邻居渲染 fail-closed 过滤（graph_capable 路径）
# ============================================================================


def _neighbor(file_path: str, *, weight: float, hop: int) -> NeighborMetadata:
    return NeighborMetadata(
        chunk_id=str(uuid.uuid4()),
        file_path=file_path,
        line_start=1,
        line_end=2,
        edge_type="CALL",
        weight=weight,
        reason="via call",
        hop=hop,
    )


async def _run_graph_capable(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rag_items: list[dict[str, Any]],
    hop1: list[NeighborMetadata],
    hop2: list[NeighborMetadata],
    matcher: ExclusionMatcher,
) -> Any:
    from services.code_intel.local_provider import LocalProvider
    from services.retrieval.hybrid_search import HybridSearchService

    rag_snapshot = LayerSnapshot(
        layer="L3", status="ok", result_count=len(rag_items), items=rag_items
    )

    with (
        patch(
            "services.retrieval.hybrid_search.search_rag",
            new=AsyncMock(return_value=rag_snapshot),
        ),
        patch(
            "services.retrieval.hybrid_search.resolve_neighbor_metadata",
            new=AsyncMock(return_value=hop1),
        ),
        patch(
            "services.retrieval.hybrid_search.expand_hop2",
            new=AsyncMock(return_value=hop2),
        ),
        patch(
            "services.retrieval.hybrid_search.expand_cross_repo",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "services.retrieval.hybrid_search.build_matcher_for_repo",
            new=AsyncMock(return_value=matcher),
        ),
        patch.object(LocalProvider, "lookup_symbols", new=AsyncMock(return_value=[])),
    ):
        return await HybridSearchService(LocalProvider()).search(
            "q", repository_ids=["repo-a"], enable_graph_enrichment=True
        )


async def test_graph_capable_filters_excluded_neighbors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """hop1/hop2 中被排除 file_path 的邻居不出现在 graph_context / 返回邻居列表。"""
    result = await _run_graph_capable(
        monkeypatch,
        rag_items=[_item("src/app.py", score=0.9)],
        hop1=[_neighbor("src/auth.py", weight=0.9, hop=1), _neighbor(".env", weight=0.8, hop=1)],
        hop2=[_neighbor("config/secret.json", weight=0.5, hop=2)],
        matcher=ExclusionMatcher(
            [
                ExclusionRuleSpec(pattern=".env", rule_type="glob", source="global"),
                ExclusionRuleSpec(pattern="*secret*.json", rule_type="glob", source="global"),
            ],
            repository_id="repo-a",
        ),
    )

    from services.retrieval.types import HybridSearchResult

    assert isinstance(result, HybridSearchResult)
    assert ".env" not in result.graph_context
    assert "secret.json" not in result.graph_context
    assert ".env" not in result.final_context
    # 正常邻居保留
    assert "src/auth.py" in result.graph_context
    # 返回的邻居列表也剔除被排除项
    h1_paths = {n.file_path for n in result.hop1_neighbors}
    assert ".env" not in h1_paths
    assert "src/auth.py" in h1_paths


async def test_graph_capable_failclosed_neighbor_on_matcher_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """邻居判定异常 → 该邻居被剔除（fail-closed），不抛出。"""
    boom = MagicMock()
    boom.is_excluded.side_effect = RuntimeError("boom")

    result = await _run_graph_capable(
        monkeypatch,
        rag_items=[_item("src/app.py", score=0.9)],
        hop1=[_neighbor("src/auth.py", weight=0.9, hop=1)],
        hop2=[],
        matcher=boom,
    )

    # fail-closed：判定异常 → 邻居全部剔除，但不抛错
    assert "src/auth.py" not in result.graph_context
    assert {n.file_path for n in result.hop1_neighbors} == set()
