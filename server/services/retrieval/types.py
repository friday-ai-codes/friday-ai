"""检索结果数据类型 —— per 。
字段语义与 `codegraph.services.layered_search.LayerResult` /
`LayeredSearchResult` 保持完全兼容，方便 Plan wrapper 零成本 alias。
不导入任何 Django / codegraph 模块；该模块在 Django app loading 之前即可被
import（types 仅为纯 dataclass）。
"""
from __future__ import annotations
import warnings
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
@dataclass(frozen=True, slots=True)
class NeighborMetadata:
 """图谱邻居元数据（Phase 编排器一跳/二跳扩散结构，per ）。
 `line_start` / `line_end` 允许 None——历史 ChunkRegistry row 未回填行号
 （per Phase schema gap），graph_context 渲染必须 fallback 到无
 行号格式。`reason` 由 `_explain_neighbor(edge_type, source_payload)` 生成。
 """
 chunk_id: str
 file_path: str
 line_start: int | None
 line_end: int | None
 edge_type: str
 weight: float
 reason: str
 hop: int
@dataclass(slots=True)
class HybridSearchResult:
 """Hybrid（RAG + 图谱）检索最终结果，per 。
 设计选择：**不继承 RagSearchResult**——字段同名同序保兼容，
 通过 ``to_rag_result`` 显式 downcast 供 Plan callsite 兼容既有类型注解；
 规避 isinstance 检查在 Plan 误命中 HybridSearchResult 子类的风险
 （per Plan deviation -b）。
 新增字段 ``graph_context`` / ``hop1_neighbors`` / ``hop2_neighbors`` 全部
 提供默认值，existing callsite 不破坏。
 """
 query: str = ""
 repository_ids: list[str] = field(default_factory=list)
 layers: list[LayerSnapshot] = field(default_factory=list)
 final_context: str = ""
 total_tokens: int = 0
 # Phase 新增字段（默认值兼容 existing callsite）
 graph_context: str = ""
 hop1_neighbors: list[NeighborMetadata] = field(default_factory=list)
 hop2_neighbors: list[NeighborMetadata] = field(default_factory=list)
 # Phase 新增（默认；wave 跨仓扩散结果，）
 cross_repo_neighbors: list[NeighborMetadata] = field(default_factory=list)
 def to_rag_result(self) -> RagSearchResult:
 """显式 downcast 到 RagSearchResult，丢弃 graph 字段。
 用途：Plan / 既有 callsite 已 `result: RagSearchResult` 类型注解，
 需要把 HybridSearchResult 实例转为 RagSearchResult 满足类型签名。
 Deprecated (Phase):
 grep 验证生产代码无 callsite——该方法疑似 YAGNI。`HybridSearchResult`
 字段同名同序兼容 `RagSearchResult`，下游若真需要静默丢弃 graph 字段
 应在 callsite 显式构造 `RagSearchResult`，避免隐式信息丢失。
 """
 warnings.warn(
 "HybridSearchResult.to_rag_result is deprecated and will be "
 "removed in Phase cleanup; explicitly construct RagSearchResult "
 "at the callsite if you need to drop graph_context / hop1/hop2 "
 "neighbors fields.",
 DeprecationWarning,
 stacklevel=2,
 )
 return RagSearchResult(
 query=self.query,
 repository_ids=self.repository_ids,
 layers=self.layers,
 final_context=self.final_context,
 total_tokens=self.total_tokens,
 )
__all__ = [
 "HybridSearchResult",
 "LayerSnapshot",
 "NeighborMetadata",
 "RagSearchResult",
]
