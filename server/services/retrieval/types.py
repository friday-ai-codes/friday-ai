"""检索结果数据类型 —— per 。
字段语义与 `codegraph.services.layered_search.LayerResult` /
`LayeredSearchResult` 保持完全兼容，方便 Plan wrapper 零成本 alias。
不导入任何 Django / codegraph 模块；该模块在 Django app loading 之前即可被
import（types 仅为纯 dataclass）。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
@dataclass(slots=True)
class LayerSnapshot:
 """单层检索结果快照。
 字段命名与 `LayerResult` 完全一致（layer / status / result_count / items /
 error / extra），用于跨层抽取检索结果时统一传递语义。
 """
 layer: str
 status: str
 result_count: int = 0
 items: list[dict[str, Any]] = field(default_factory=list)
 error: str | None = None
 extra: dict[str, Any] | None = None
@dataclass(slots=True)
class RagSearchResult:
 """RAG 检索最终结果。
 字段语义与 `LayeredSearchResult` 兼容（query / repository_ids / layers /
 final_context / total_tokens），便于 HybridSearchService 编排时直接复用。
 """
 query: str
 repository_ids: list[str]
 layers: list[LayerSnapshot]
 final_context: str
 total_tokens: int
__all__ = ["LayerSnapshot", "RagSearchResult"]
