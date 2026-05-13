"""services.retrieval —— RAG 检索包骨架（per ）。
本包是 Phase RAG 解耦的核心入口：
- `types`：`RagSearchResult` / `LayerSnapshot` 数据类
- `token_budget`：`estimate_tokens` / `trim_to_budget` / `split_budget` 纯函数
- `rag_search`：`search_rag` 抽出 LayeredSearchService L3 dense+sparse 检索
Plan 将在此包内追加 `hybrid_search.HybridSearchService` 编排器，
合并 RAG 主线 + 图谱 enrichment 两条路径。
"""
from __future__ import annotations
from services.retrieval.rag_search import search_rag
from services.retrieval.token_budget import (
 DEFAULT_ENCODING,
 TOKEN_BUFFER_RATIO,
 estimate_tokens,
 split_budget,
 trim_to_budget,
)
from services.retrieval.types import LayerSnapshot, RagSearchResult
__all__ = [
 "DEFAULT_ENCODING",
 "LayerSnapshot",
 "RagSearchResult",
 "TOKEN_BUFFER_RATIO",
 "estimate_tokens",
 "search_rag",
 "split_budget",
 "trim_to_budget",
]
