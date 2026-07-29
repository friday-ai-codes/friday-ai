"""仓库路由 v2 纯函数打分核心（Phase 105）。

router（RepoRouterV2）/ 离线 replay / golden harness 三方共用同一份打分
纯函数（per CONTEXT ROUTE-09）——这是「快照回放零网络同结果」的结构保证。

模块契约：
- 零 I/O、零 ORM、零 Django import、零网络——仅 stdlib（math/json/dataclasses/typing）。
- 输入是 dict（Qdrant node_hits 形状），输出是 dataclass；同输入必得同输出
  （稳定 tie-break + math.fsum 消除浮点顺序依赖）。
- θ 阈值（REPO_ROUTER_CONF_THETA_ABS/MARGIN/MED）由调用方读 settings 后以
  参数注入，本模块不读任何配置。
- 本模块不加日志——观测埋点在调用方 router 层（105-03 处理）。

公式与常数权威来源：.planning/research/ROUTING-RANKING.md（§1.3a margin 规则、
§2.3 归一化、§3.4 缺失信号重归一化、§4 活跃度枚举映射、§6.2 tie-break）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

# 本模块自定义 Confidence，不 import repo_router_v2（防循环依赖）。
Confidence = Literal["high", "medium", "low"]

# breakdown 字典 key——前端信号名映射表与之对齐，禁止改名。
SIGNAL_TEXT = "text"
SIGNAL_BREADTH = "breadth"
SIGNAL_ACTIVITY = "activity"

# Phase 105 临时权重（Σ=1.0）：golden set 校准后可调；
# 完整权重表外置 SystemSetting 归 Phase 106。
PHASE105_WEIGHTS: dict[str, float] = {
    SIGNAL_TEXT: 0.70,
    SIGNAL_BREADTH: 0.20,
    SIGNAL_ACTIVITY: 0.10,
}

# 版本绑定四元组之一（weight_set_version + prompt_hash + model_id + index_version），
# 快照与 golden baseline 都必须记录。
WEIGHT_SET_VERSION = "phase105-v1"

# 活跃度枚举映射（ROUTING-RANKING §4）；连续时间衰减归 Phase 106。
ACTIVITY_ENUM_MAP: dict[str, float] = {
    "活跃开发": 0.9,
    "维护中": 0.6,
    "低频": 0.3,
    "疑似废弃": 0.1,
}

# 废弃惩罚：从乘性 `score *= 0.5` 改为对活跃度项封顶（per CONTEXT ROUTE-07），
# 惩罚完全落在 activity 一项内，贡献仍可单独拆解展示。
DEPRECATED_ACTIVITY_CAP = 0.10

_SENTINEL_UNAVAILABLE = None  # 信号不可用标记（缺失 ≠ 确认不匹配，走权重重归一化）


@dataclass
class ScoredCandidate:
    """一个候选仓库的可拆解打分结果。

    repo_name 容错契约：payload 缺 repo_name（如 replay 从最小字段集快照重建）
    时确定性回退为 repo_id，且分数/breakdown/排序不受 repo_name 有无影响
    （tie-break 第二键本就是 repo_id）。
    """

    repo_id: str
    repo_name: str
    score: float
    breakdown: dict[str, float] = field(default_factory=dict)
    facets: dict[str, Any] = field(default_factory=dict)
    # hits 透传：供 Stage 1 组 prompt / finalize 取 node_path。
    hits: list[dict[str, Any]] = field(default_factory=list)


def _parse_facets(value: Any) -> dict[str, Any]:
    """容错解析 payload.facets（可能是 dict 或 JSON str；坏 JSON → 空 dict）。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _activity_signal(facets: dict[str, Any]) -> float | None:
    """活跃度信号：facet 缺失或值不在映射表 → 不可用（None，非补 0）。

    「未知 ≠ 确认不匹配」（ROUTING-RANKING §3.4）——缺失走权重重归一化。
    """
    raw = facets.get("活跃度")
    if not isinstance(raw, str):
        return _SENTINEL_UNAVAILABLE
    mapped = ACTIVITY_ENUM_MAP.get(raw)
    if mapped is None:
        return _SENTINEL_UNAVAILABLE
    if raw == "疑似废弃":
        return min(mapped, DEPRECATED_ACTIVITY_CAP)
    return mapped


def aggregate_and_score(
    node_hits: list[dict[str, Any]],
    *,
    weights: dict[str, float] | None = None,
) -> list[ScoredCandidate]:
    """按仓库聚合 node_hits 并产出可拆解加性分数（INV-R1/R3）。

    流程：
    1. 按 payload.repository_id 分桶（空 rid 跳过）；桶内按
       ``(-round(score, 6), str(node_id))`` 排序——先量化再比较 + node_id
       第二键，消除 Qdrant 返回序依赖。
    2. query-local max 归一：``s_hat = score / rrf_max``（rrf_max <= 0 时全 0）。
    3. 每桶三信号（全部 ∈ [0,1]）：text（max s_hat）、breadth（命中广度）、
       activity（枚举映射 + 废弃封顶；缺失 → 不可用）。
    4. 加性合成 + 缺失重归一化：breakdown[j] = w_j·M_j / Σ_available w，
       score = Σ breakdown——Σbreakdown == score 恒成立（INV-R3），
       各信号 ∈ [0,1] 且权重凸组合 → S ∈ [0,1] 无需截断（INV-R1）。
    5. 候选列表按 ``(-round(score, 6), repo_id)`` 稳定排序。

    求和一律 ``math.fsum``（对真实和精确舍入，顺序无关）。
    """
    w = weights if weights is not None else PHASE105_WEIGHTS

    # 1. 分桶 + 桶内稳定排序
    buckets: dict[str, list[dict[str, Any]]] = {}
    for hit in node_hits:
        payload = hit.get("payload") or {}
        rid = str(payload.get("repository_id", "") or "")
        if rid:
            buckets.setdefault(rid, []).append(hit)
    for hits in buckets.values():
        hits.sort(
            key=lambda h: (
                -round(float(h.get("score", 0.0)), 6),
                str((h.get("payload") or {}).get("node_id", "")),
            )
        )

    # 2. query-local max 归一
    all_scores = [
        float(h.get("score", 0.0)) for hits in buckets.values() for h in hits
    ]
    rrf_max = max(all_scores) if all_scores else 0.0

    def _s_hat(hit: dict[str, Any]) -> float:
        if rrf_max <= 0.0:
            return 0.0  # 防除零：全部退化为 0
        return float(hit.get("score", 0.0)) / rrf_max

    candidates: list[ScoredCandidate] = []
    for rid, hits in buckets.items():
        top_payload = hits[0].get("payload") or {}
        facets = _parse_facets(top_payload.get("facets"))

        # 3. 三信号（不可用 → None，参与重归一化而非补 0）
        signals: dict[str, float | None] = {
            SIGNAL_TEXT: max(_s_hat(h) for h in hits),
            SIGNAL_BREADTH: min(len(hits) - 1, 5) / 5.0,
            SIGNAL_ACTIVITY: _activity_signal(facets),
        }

        # 4. 加性合成 + 缺失重归一化（math.fsum 消除顺序依赖）
        available = {
            sig: val for sig, val in signals.items() if val is not None
        }
        denom = math.fsum(w.get(sig, 0.0) for sig in available)
        breakdown: dict[str, float] = {}
        if denom > 0.0:
            breakdown = {
                sig: w.get(sig, 0.0) * val / denom
                for sig, val in available.items()
            }
        score = math.fsum(breakdown.values())

        repo_name = str(top_payload.get("repo_name") or "") or rid
        candidates.append(
            ScoredCandidate(
                repo_id=rid,
                repo_name=repo_name,
                score=score,
                breakdown=breakdown,
                facets=facets,
                hits=hits,
            )
        )

    # 5. 稳定排序：先量化再比较；第二键不可变 repo_id（禁止 name/path）
    candidates.sort(key=lambda c: (-round(c.score, 6), c.repo_id))
    return candidates


def derive_confidence(
    sorted_scores: list[float],
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> Confidence:
    """确定性 confidence 推导（RELY-04，ROUTING-RANKING §1.3a）。

    ``S(1) >= θ_abs 且 margin >= θ_margin → high；S(1) >= θ_med → medium；
    否则 low``。空列表 → low；单候选时 margin = S(1)（s2 视为 0.0）。
    """
    if not sorted_scores:
        return "low"
    s1 = sorted_scores[0]
    s2 = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
    margin = s1 - s2
    if s1 >= theta_abs and margin >= theta_margin:
        return "high"
    if s1 >= theta_med:
        return "medium"
    return "low"


def apply_llm_adjustment(
    deterministic: Confidence, llm: Confidence | None
) -> Confidence:
    """LLM confidence 调节：只降不升（per CONTEXT RELY-04）。

    llm 为 None 或非法值 → 返回 deterministic；否则取两者中较低档
    （min 语义）——LLM 绝不能把 low/medium 升为 high。
    """
    order = {"low": 0, "medium": 1, "high": 2}
    if llm not in order:
        return deterministic
    return llm if order[llm] < order[deterministic] else deterministic


__all__ = [
    "ACTIVITY_ENUM_MAP",
    "Confidence",
    "DEPRECATED_ACTIVITY_CAP",
    "PHASE105_WEIGHTS",
    "SIGNAL_ACTIVITY",
    "SIGNAL_BREADTH",
    "SIGNAL_TEXT",
    "ScoredCandidate",
    "WEIGHT_SET_VERSION",
    "aggregate_and_score",
    "apply_llm_adjustment",
    "derive_confidence",
]
