"""HybridBudget —— Phase 编排器 token 预算分配策略（per / ）。
`HybridBudget(rag=0.6, graph=0.4).allocate(8000)` 返回
`{"rag": 4320, "graph": 2880}`：
- buffer：`max_tokens * TOKEN_BUFFER_RATIO`（复用 token_budget.py 的 0.9，
 剩 10% 冗余防 `estimate_tokens` 误差）
- 默认 rag=0.6 / graph=0.4（per ROADMAP ）
- `from_settings` 读 `settings.GRAPHRAG_BUDGET_RATIO`（默认 0.6），ratio
 ∉ [0.1, 0.9] 自动 clamp 到边界并 structlog warning
 事件名 `hybrid_budget_ratio_clamped`，字段 `requested` / `clamped`
**Pitfall 5 grep gate**：本模块**不读** codegraph 启用开关——图谱启停全部走
`isinstance(provider, GraphCapableProvider)` 守卫，本模块只关心 RAG/图谱
预算比例。CI 的 `rg "settings\\.ENABLE_CODEGRAP[H]" server/services/retrieval/`
必须 0 命中（**故意不在源码中写出该 setting 的完整 attribute 形式**以满足 grep gate）。
"""
from __future__ import annotations
from dataclasses import dataclass
import structlog
from services.retrieval.token_budget import TOKEN_BUFFER_RATIO
logger = structlog.get_logger(__name__)
GRAPHRAG_BUDGET_RATIO_DEFAULT: float = 0.6
"""settings.GRAPHRAG_BUDGET_RATIO 缺省值（rag=0.6 / graph=0.4，per ）。"""
RATIO_MIN: float = 0.1
"""ratio 下界——防止把 RAG 主线压到几乎不可用（per clamp）。"""
RATIO_MAX: float = 0.9
"""ratio 上界——防止把图谱 enrichment 完全挤掉（per clamp）。"""
@dataclass(frozen=True, slots=True)
class HybridBudget:
 """token 预算双比例策略类（frozen + slots，不可修改）。
 Attributes:
 rag: RAG 主线分配比例，默认 0.6（per ROADMAP ）
 graph: 图谱 enrichment 分配比例，默认 0.4
 Note:
 rag + graph 通常应等于 1.0；超出时 ``allocate`` 不会校验
 （token_budget.split_budget 在 ratios sum > 1.0 时才抛 ValueError，
 本类 ``from_settings`` 构造路径保证 rag + graph == 1.0）。
 """
 rag: float = 0.6
 graph: float = 0.4
 def allocate(self, max_tokens: int) -> dict[str, int]:
 """按 buffer_ratio 折算后再按 rag/graph 切分子预算。
 例：``HybridBudget.allocate(8000)`` →
 effective = int(8000 * 0.9) = 7200 →
 {"rag": int(7200 * 0.6) = 4320, "graph": int(7200 * 0.4) = 2880}
 """
 effective = int(max_tokens * TOKEN_BUFFER_RATIO)
 return {
 "rag": int(effective * self.rag),
 "graph": int(effective * self.graph),
 }
 @classmethod
 def from_settings(cls) -> HybridBudget:
 """读取 Django settings.GRAPHRAG_BUDGET_RATIO 构造实例。
 - settings 缺失 / 非法 → fallback 到 ``GRAPHRAG_BUDGET_RATIO_DEFAULT``
 - ratio ∉ [RATIO_MIN, RATIO_MAX] → clamp 到边界 + structlog warning
 """
 from django.conf import settings
 raw = getattr(settings, "GRAPHRAG_BUDGET_RATIO", GRAPHRAG_BUDGET_RATIO_DEFAULT)
 try:
 requested = float(raw)
 except (TypeError, ValueError):
 logger.warning(
 "hybrid_budget_ratio_invalid",
 raw=repr(raw),
 fallback=GRAPHRAG_BUDGET_RATIO_DEFAULT,
 )
 requested = GRAPHRAG_BUDGET_RATIO_DEFAULT
 clamped = max(RATIO_MIN, min(RATIO_MAX, requested))
 if clamped != requested:
 logger.warning(
 "hybrid_budget_ratio_clamped",
 requested=requested,
 clamped=clamped,
 )
 return cls(rag=clamped, graph=1.0 - clamped)
__all__ = [
 "GRAPHRAG_BUDGET_RATIO_DEFAULT",
 "RATIO_MAX",
 "RATIO_MIN",
 "HybridBudget",
]
