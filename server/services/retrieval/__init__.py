"""services.retrieval —— RAG 检索包骨架（per contract）。

本包是 implementation RAG 解耦的核心入口：

- `types`：`RagSearchResult` / `LayerSnapshot` 数据类
- `token_budget`：`estimate_tokens` / `trim_to_budget` / `split_budget` 纯函数
- `rag_search`：`search_rag` 抽出 LayeredSearchService L3 dense+sparse 检索

plan 将在此包内追加 `hybrid_search.HybridSearchService` 编排器，
合并 RAG 主线 + 图谱 enrichment 两条路径。
"""

from __future__ import annotations

from services.retrieval.budget import (
    GRAPHRAG_BUDGET_RATIO_DEFAULT,
    HybridBudget,
)
from services.retrieval.find_related import (
    explain_neighbor,
    find_related,
)
from services.retrieval.hop1_reader import (
    extract_hop1_neighbors_raw,
    resolve_neighbor_metadata,
)
from services.retrieval.hop2_expander import (
    assert_hops_within_limit,
    expand_hop2,
    fetch_hop2_edges,
)
from services.retrieval.hybrid_search import HybridSearchService
from services.retrieval.rag_search import search_rag
from services.retrieval.token_budget import (
    DEFAULT_ENCODING,
    TOKEN_BUFFER_RATIO,
    estimate_tokens,
    split_budget,
    trim_to_budget,
)
from services.retrieval.types import (
    HybridSearchResult,
    LayerSnapshot,
    NeighborMetadata,
    RagSearchResult,
)

__all__ = [
    "DEFAULT_ENCODING",
    "GRAPHRAG_BUDGET_RATIO_DEFAULT",
    "HybridBudget",
    "HybridSearchResult",
    "HybridSearchService",
    "LayerSnapshot",
    "NeighborMetadata",
    "RagSearchResult",
    "TOKEN_BUFFER_RATIO",
    "assert_hops_within_limit",
    "estimate_tokens",
    "expand_hop2",
    "explain_neighbor",
    "extract_hop1_neighbors_raw",
    "fetch_hop2_edges",
    "find_related",
    "resolve_neighbor_metadata",
    "search_rag",
    "split_budget",
    "trim_to_budget",
]
