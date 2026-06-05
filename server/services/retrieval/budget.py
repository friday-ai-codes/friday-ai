"""HybridBudget —— implementation 编排器 token 预算分配策略（per contract / work item）。

implementation 升级：扩 cross_repo 第三字段（默认 0.0 向后兼容）。

`HybridBudget(rag=0.6, graph=0.4).allocate(8000)` 返回
`{"rag": 4320, "graph": 2880, "cross_repo": 0}`：

- buffer：`max_tokens * TOKEN_BUFFER_RATIO`（复用 token_budget.py 的 0.9，
  剩 10% 冗余防 `estimate_tokens` 误差）
- 默认 rag=0.6 / graph=0.4 / cross_repo=0.0（success criterion；cross_repo=0 backward compat）
- `from_settings()` 读 `settings.GRAPHRAG_BUDGET_RATIO`（rag）+
  `settings.CROSS_REPO_BUDGET_RATIO`（cross_repo，默认 0.0）
- ratio ∉ [0.1, 0.9] 自动 clamp 到边界并 structlog warning
  事件名 `hybrid_budget_ratio_clamped`，字段 `requested` / `clamped`
- 50/30/20 预算由 GRAPHRAG_BUDGET_RATIO=0.5 + CROSS_REPO_BUDGET_RATIO=0.2 配置实现

**Pitfall 5 grep gate**：本模块**不读** codegraph 启用开关——图谱启停全部走
`isinstance(provider, GraphCapableProvider)` 守卫，本模块只关心 RAG/图谱
预算比例。CI 的 `rg "settings\\.ENABLE_CODEGRAP[H]" server/services/retrieval/`
必须 0 命中（**故意不在源码中写出该 setting 的完整 attribute 形式**以满足 grep gate）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import structlog

from services.retrieval.token_budget import TOKEN_BUFFER_RATIO

logger = structlog.get_logger(__name__)

GRAPHRAG_BUDGET_RATIO_DEFAULT: float = 0.6
"""settings.GRAPHRAG_BUDGET_RATIO 缺省值（rag=0.6 / graph=0.4，per contract）。"""

CROSS_REPO_BUDGET_RATIO_DEFAULT: float = 0.0
"""settings.CROSS_REPO_BUDGET_RATIO 缺省值（默认 0.0 = 未启用跨仓预算，per work item）。

设置为 0.20 时开启 50/30/20 预算（需同时设 GRAPHRAG_BUDGET_RATIO=0.50）。
"""

RATIO_MIN: float = 0.1
"""ratio 下界——防止把 RAG 主线压到几乎不可用（per contract clamp）。"""

RATIO_MAX: float = 0.9
"""ratio 上界——防止把图谱 enrichment 完全挤掉（per contract clamp）。"""


@dataclass(frozen=True, slots=True)
class HybridBudget:
    """token 预算三比例策略类（frozen + slots，不可修改；implementation 扩 cross_repo 字段）。

    Attributes:
        rag: RAG 主线分配比例，默认 0.6（success criterion）
        graph: 图谱 enrichment 分配比例，默认 0.4
        cross_repo: 跨仓 API 扩散分配比例，默认 0.0（向后兼容；per work item）

    向后兼容：
        ``HybridBudget(rag=0.6, graph=0.4)`` 等价 ``HybridBudget(rag=0.6, graph=0.4,
        cross_repo=0.0)``——sum=1.0 ✓，不破坏既有 callsite。

    50/30/20 预算：
        通过 settings ``GRAPHRAG_BUDGET_RATIO=0.5`` + ``CROSS_REPO_BUDGET_RATIO=0.2``
        触发 ``HybridBudget(rag=0.5, graph=0.3, cross_repo=0.2)``。
    """

    rag: float = 0.6
    graph: float = 0.4
    cross_repo: float = 0.0

    def __post_init__(self) -> None:
        """contract: 强制 ``rag + graph + cross_repo == 1.0`` + 非负——避免静默超 budget。

        implementation 升级：三字段 sum 校验（原双字段 rag+graph，现三字段总和）。
        ``HybridBudget(rag=0.6, graph=0.4)`` → cross_repo=0.0 → sum=1.0 ✓（向后兼容）。
        """
        if self.rag < 0 or self.graph < 0 or self.cross_repo < 0:
            raise ValueError(
                f"HybridBudget(rag={self.rag}, graph={self.graph}, "
                f"cross_repo={self.cross_repo}) components must be non-negative"
            )
        total = self.rag + self.graph + self.cross_repo
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(
                f"HybridBudget(rag={self.rag}, graph={self.graph}, "
                f"cross_repo={self.cross_repo}) sum={total:.6f} != 1.0; "
                "rag + graph + cross_repo must total 1.0"
            )

    def allocate(self, max_tokens: int) -> dict[str, int]:
        """按 buffer_ratio 折算后再按 rag/graph/cross_repo 切分子预算。

        例：``HybridBudget().allocate(8000)`` →
        effective = int(8000 * 0.9) = 7200 →
        {"rag": int(7200 * 0.6) = 4320, "graph": int(7200 * 0.4) = 2880, "cross_repo": 0}

        implementation: 新增 cross_repo key（默认 0，不影响现有 budgets["rag"] / budgets["graph"] 读取）。

        Raises:
            ValueError: ``max_tokens`` 为负——避免 ``trim_to_budget`` 全空 final_context
                难以排查根因（per contract）。
        """
        if max_tokens < 0:
            raise ValueError(
                f"max_tokens must be non-negative, got {max_tokens}"
            )
        effective = int(max_tokens * TOKEN_BUFFER_RATIO)
        return {
            "rag": int(effective * self.rag),
            "graph": int(effective * self.graph),
            "cross_repo": int(effective * self.cross_repo),
        }

    @classmethod
    def from_settings(cls) -> "HybridBudget":
        """读取 Django settings 构造实例（implementation 扩 CROSS_REPO_BUDGET_RATIO）。

        - GRAPHRAG_BUDGET_RATIO（rag 比）：缺失/非法 → fallback 到 0.6，
          ∉ [0.1, 0.9] → clamp + structlog warning
        - CROSS_REPO_BUDGET_RATIO（cross_repo 比）：缺失/非法 → fallback 到 0.0
          （默认不启用跨仓预算，保持 v24 行为零漂移）
        - graph = 1.0 - rag - cross_repo（补余）
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

        # contract: 显式拒绝 NaN / ±Inf——不依赖 CPython min/max 参数顺序的 NaN 行为。
        if not math.isfinite(requested):
            logger.warning(
                "hybrid_budget_ratio_non_finite",
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
        rag = clamped

        # cross_repo ratio（implementation）
        raw_cross = getattr(settings, "CROSS_REPO_BUDGET_RATIO", CROSS_REPO_BUDGET_RATIO_DEFAULT)
        try:
            cross_repo = max(0.0, min(0.5, float(raw_cross)))
        except (TypeError, ValueError):
            cross_repo = CROSS_REPO_BUDGET_RATIO_DEFAULT

        # graph 补余（浮点误差修正保证 sum == 1.0）
        graph = round(1.0 - rag - cross_repo, 10)
        graph = max(0.0, graph)

        return cls(rag=rag, graph=graph, cross_repo=cross_repo)


__all__ = [
    "CROSS_REPO_BUDGET_RATIO_DEFAULT",
    "GRAPHRAG_BUDGET_RATIO_DEFAULT",
    "RATIO_MAX",
    "RATIO_MIN",
    "HybridBudget",
]
