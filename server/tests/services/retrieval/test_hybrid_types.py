"""`NeighborMetadata` + `HybridSearchResult` 行为测试（per implementation contract / contract）。

覆盖 4 条 assertion：

1. HybridSearchResult 构造后 graph_context/hop1_neighbors/hop2_neighbors 走默认值
2. to_rag_result() downcast：5 个 RagSearchResult 字段守恒（query / repository_ids /
   layers / final_context / total_tokens）
3. NeighborMetadata 是 frozen dataclass，setattr 抛 FrozenInstanceError
4. RagSearchResult 兼容路径：to_rag_result() 返回值确为 RagSearchResult 实例
   （Plan 选 to_rag_result() 显式转换路径而非继承，implementation notes contract-b）
"""

from __future__ import annotations

import dataclasses

import pytest

from services.retrieval.types import (
    HybridSearchResult,
    LayerSnapshot,
    NeighborMetadata,
    RagSearchResult,
)


def test_hybrid_search_result_defaults_for_new_fields() -> None:
    result = HybridSearchResult(
        query="hello",
        repository_ids=["repo-a"],
        layers=[LayerSnapshot(layer="L3", status="ok")],
        final_context="rag body",
        total_tokens=42,
    )
    assert result.graph_context == ""
    assert result.hop1_neighbors == []
    assert result.hop2_neighbors == []


def test_hybrid_search_result_to_rag_result_preserves_fields() -> None:
    layers = [LayerSnapshot(layer="L3", status="ok", result_count=2)]
    hybrid = HybridSearchResult(
        query="q",
        repository_ids=["r1", "r2"],
        layers=layers,
        final_context="ctx",
        total_tokens=99,
        graph_context="## graph",
        hop1_neighbors=[],
        hop2_neighbors=[],
    )
    downcast = hybrid.to_rag_result()
    assert isinstance(downcast, RagSearchResult)
    assert downcast.query == hybrid.query
    assert downcast.repository_ids == hybrid.repository_ids
    assert downcast.layers == hybrid.layers
    assert downcast.final_context == hybrid.final_context
    assert downcast.total_tokens == hybrid.total_tokens


def test_neighbor_metadata_frozen() -> None:
    nm = NeighborMetadata(
        chunk_id="00000000-0000-0000-0000-000000000001",
        file_path="src/foo.py",
        line_start=1,
        line_end=20,
        edge_type="CALL",
        weight=0.85,
        reason="caller of foo() via direct call",
        hop=1,
    )
    assert dataclasses.is_dataclass(NeighborMetadata)
    assert NeighborMetadata.__dataclass_params__.frozen is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        nm.weight = 0.5  # type: ignore[misc]


def test_neighbor_metadata_allows_nullable_line_fields() -> None:
    """contract fallback：line_start / line_end 必须接受 None（历史 chunk 未回填）。"""
    nm = NeighborMetadata(
        chunk_id="00000000-0000-0000-0000-000000000002",
        file_path="src/legacy.py",
        line_start=None,
        line_end=None,
        edge_type="IMPORT",
        weight=0.5,
        reason="imported by module foo",
        hop=1,
    )
    assert nm.line_start is None
    assert nm.line_end is None
