"""仓库路由 golden set 离线评估 harness（Phase 105 ROUTE-08 / Phase 106-08 六信号扩展）。

指标计算（Recall@5 / MRR@10 / Top-1 / 误自动选中率）+ bootstrap 95% CI +
逐例 diff——三件套全部是纯函数，供 golden 门禁测试与未来调参脚本复用。

模块契约（与 repo_router_scoring 同款）：
- 零 I/O、零 ORM、零 Django import、零网络——仅 stdlib（math/random/dataclasses）。
- **禁止引入 numpy/scipy**（105-RESEARCH 选型结论：bootstrap 用 stdlib random）。
- 打分唯一入口是 ``aggregate_and_score`` + ``derive_confidence``——与 router /
  离线 replay 走同一代码路径（CONTEXT ROUTE-09 的结构保证）。
- θ 阈值由调用方注入，本模块不读任何配置。

case 输入形状（与 fixture 对齐）::

    {
        "id": str,
        "query": str,
        "label_source": "human" | "weak",
        "cross_group": bool,
        "expected_repos": [repo_id, ...],
        "node_hits": [Stage 0 hit 形状: {"score": float, "payload": {...}}, ...],
        # —— Phase 106 六信号离线评估字段（106-08，全部可选）——
        # repo_meta 存在 → 新路径（六信号）；缺失 → legacy 三信号（向后兼容）。
        "repo_meta": {rid: {n_r, last_commit_at, dense_cos_max?, facet_scores?,
                            criticality_value?}},  # 键契约见 repo_router_scoring
        "scored_at": str,          # ISO 8601 固定时间锚点（活跃度衰减确定性）
        "constants": {"n_bar": float, ...},   # 与 DEFAULT_WEIGHT_CONFIG merge
        "weight_overrides": {signal: float},  # 与 DEFAULT 权重 merge（调参脚本用）
    }

离线评估口径（106-RESEARCH §8 裁决）：T1-only + fixture 内联 facet 匹配分
（repo_meta.facet_scores 直接给数值）——不依赖 T2/embedding，零网络。

指标定义权威来源：.planning/research/ROUTING-RANKING.md §7.1/§7.2 与
105-CONTEXT §golden set 与 CI 门禁。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from codegraph.services.repo_router_scoring import (
    DEFAULT_WEIGHT_CONFIG,
    WEIGHT_SET_VERSION,
    Confidence,
    ScoredCandidate,
    aggregate_and_score,
    derive_confidence,
)

# 指标窗口常量（ROUTING-RANKING §7.1：Recall@5 主指标 / MRR@10 次指标）。
RECALL_K = 5
MRR_K = 10


@dataclass
class CaseResult:
    """单条 golden case 的评估结果（进 baseline JSON，供逐例 diff 对照）。"""

    case_id: str
    label_source: str
    cross_group: bool
    expected_repos: list[str]
    ranked_repo_ids: list[str]
    top1_repo_id: str
    top1_breakdown: dict[str, float]
    confidence: Confidence
    recall_at_5: float
    mrr_at_10: float
    top1_correct: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "label_source": self.label_source,
            "cross_group": self.cross_group,
            "expected_repos": list(self.expected_repos),
            "ranked_repo_ids": list(self.ranked_repo_ids),
            "top1_repo_id": self.top1_repo_id,
            "top1_breakdown": dict(self.top1_breakdown),
            "confidence": self.confidence,
            "recall_at_5": self.recall_at_5,
            "mrr_at_10": self.mrr_at_10,
            "top1_correct": self.top1_correct,
        }


@dataclass
class EvalReport:
    """全量评估报告：汇总指标 + human/weak 分组统计 + per-case 明细。"""

    case_count: int
    recall_at_5: float
    mrr_at_10: float
    top1_correct_count: int
    high_conf_count: int
    false_auto_select_rate: float
    recall_at_5_ci: tuple[float, float]
    mrr_at_10_ci: tuple[float, float]
    by_label_source: dict[str, dict[str, Any]]
    per_case: list[CaseResult] = field(default_factory=list)
    weight_set_version: str = WEIGHT_SET_VERSION

    def to_dict(self) -> dict[str, Any]:
        """序列化为 baseline JSON 结构（GENERATE_GOLDEN=1 路径直接落盘）。"""
        return {
            "weight_set_version": self.weight_set_version,
            "case_count": self.case_count,
            "recall_at_5": self.recall_at_5,
            "mrr_at_10": self.mrr_at_10,
            "top1_correct_count": self.top1_correct_count,
            "high_conf_count": self.high_conf_count,
            "false_auto_select_rate": self.false_auto_select_rate,
            "bootstrap_ci": {
                "recall_at_5": list(self.recall_at_5_ci),
                "mrr_at_10": list(self.mrr_at_10_ci),
            },
            "by_label_source": self.by_label_source,
            "per_case": [c.to_dict() for c in self.per_case],
        }


@dataclass
class RegressedCase:
    """一条变坏的 case：baseline 首位 vs 当前首位 + 两版 breakdown 对照。"""

    case_id: str
    baseline_top1: str
    current_top1: str
    baseline_breakdown: dict[str, float]
    current_breakdown: dict[str, float]
    baseline_metrics: tuple[float, float, bool]
    current_metrics: tuple[float, float, bool]


@dataclass
class CaseDiff:
    """逐例 diff：变好/变坏清单 + 变坏用例的 breakdown 变化（多行文本可读）。"""

    improved: list[str] = field(default_factory=list)
    regressed: list[RegressedCase] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    only_in_baseline: list[str] = field(default_factory=list)
    only_in_current: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """格式化为多行字符串，供 pytest 门禁失败消息直接输出。"""
        lines = [
            "=== golden set 逐例 diff ===",
            f"improved: {self.improved or '(无)'}",
            f"unchanged: {len(self.unchanged)} 条",
        ]
        if self.only_in_baseline:
            lines.append(f"only_in_baseline（当前缺失）: {self.only_in_baseline}")
        if self.only_in_current:
            lines.append(f"only_in_current（baseline 缺失）: {self.only_in_current}")
        if not self.regressed:
            lines.append("regressed: (无)")
        for r in self.regressed:
            lines.extend(
                [
                    f"--- regressed: {r.case_id} ---",
                    (
                        f"  metrics (recall@5, mrr@10, top1_correct): "
                        f"baseline={r.baseline_metrics} -> current={r.current_metrics}"
                    ),
                    f"  top1: baseline={r.baseline_top1!r} -> current={r.current_top1!r}",
                    f"  baseline top1 breakdown: {r.baseline_breakdown}",
                    f"  current  top1 breakdown: {r.current_breakdown}",
                ]
            )
        return "\n".join(lines)

    def __str__(self) -> str:  # pragma: no cover - 便捷别名
        return self.to_text()


def score_case(case: dict[str, Any]) -> list[ScoredCandidate]:
    """单 case 打分入口——evaluate_cases 与 golden 门禁机制断言共用。

    case 携带 ``repo_meta`` → 新路径（Phase 106 六信号，与 route()/replay 同一
    纯函数）：weights/constants 以 ``DEFAULT_WEIGHT_CONFIG`` 为底与 case 级
    ``weight_overrides``/``constants`` merge，时间锚点取 ``scored_at``；
    不携带 → legacy 三信号路径（Phase 105 口径，向后兼容）。
    """
    repo_meta = case.get("repo_meta")
    if repo_meta is None:
        return aggregate_and_score(case["node_hits"])
    return aggregate_and_score(
        case["node_hits"],
        weights={**DEFAULT_WEIGHT_CONFIG["weights"], **case.get("weight_overrides", {})},
        repo_meta=repo_meta,
        constants={**DEFAULT_WEIGHT_CONFIG["constants"], **case.get("constants", {})},
        criticality_anchors={
            **DEFAULT_WEIGHT_CONFIG["criticality_anchors"],
            **case.get("criticality_anchors", {}),
        },
        now=case.get("scored_at"),
    )


def _evaluate_one(
    case: dict[str, Any],
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> CaseResult:
    """单 case 评估：调打分核心 → 排序候选 → per-case 指标。"""
    candidates = score_case(case)
    ranked = [c.repo_id for c in candidates]
    expected = [str(r) for r in case.get("expected_repos", [])]
    expected_set = set(expected)

    top5 = set(ranked[:RECALL_K])
    recall_at_5 = len(expected_set & top5) / len(expected_set) if expected_set else 0.0

    mrr_at_10 = 0.0
    for idx, rid in enumerate(ranked[:MRR_K], start=1):
        if rid in expected_set:
            mrr_at_10 = 1.0 / idx
            break

    top1_repo_id = ranked[0] if ranked else ""
    top1_correct = bool(top1_repo_id) and top1_repo_id in expected_set
    confidence = derive_confidence(
        [c.score for c in candidates],
        theta_abs=theta_abs,
        theta_margin=theta_margin,
        theta_med=theta_med,
    )
    top1_breakdown = dict(candidates[0].breakdown) if candidates else {}

    return CaseResult(
        case_id=str(case["id"]),
        label_source=str(case.get("label_source", "human")),
        cross_group=bool(case.get("cross_group", False)),
        expected_repos=expected,
        ranked_repo_ids=ranked,
        top1_repo_id=top1_repo_id,
        top1_breakdown=top1_breakdown,
        confidence=confidence,
        recall_at_5=recall_at_5,
        mrr_at_10=mrr_at_10,
        top1_correct=top1_correct,
    )


def _summarize(results: list[CaseResult]) -> dict[str, Any]:
    """一组 CaseResult 的汇总指标（全量与 human/weak 分组共用）。"""
    n = len(results)
    high = [r for r in results if r.confidence == "high"]
    false_auto = sum(1 for r in high if not r.top1_correct)
    return {
        "case_count": n,
        "recall_at_5": math.fsum(r.recall_at_5 for r in results) / n if n else 0.0,
        "mrr_at_10": math.fsum(r.mrr_at_10 for r in results) / n if n else 0.0,
        "top1_correct_count": sum(1 for r in results if r.top1_correct),
        "high_conf_count": len(high),
        # 护栏指标：分母（high 数）为 0 时返回 0.0——无 high 不误报。
        "false_auto_select_rate": (false_auto / len(high)) if high else 0.0,
    }


def evaluate_cases(
    cases: list[dict[str, Any]],
    *,
    theta_abs: float,
    theta_margin: float,
    theta_med: float,
) -> EvalReport:
    """全量评估：逐 case 走打分核心纯函数，汇总四指标 + bootstrap CI。

    human/weak 标签来源分开统计（per CONTEXT），进 ``by_label_source``。
    """
    per_case = [
        _evaluate_one(c, theta_abs=theta_abs, theta_margin=theta_margin, theta_med=theta_med)
        for c in cases
    ]
    overall = _summarize(per_case)

    by_label_source: dict[str, dict[str, Any]] = {}
    for label in sorted({r.label_source for r in per_case}):
        subset = [r for r in per_case if r.label_source == label]
        by_label_source[label] = _summarize(subset)

    return EvalReport(
        case_count=overall["case_count"],
        recall_at_5=overall["recall_at_5"],
        mrr_at_10=overall["mrr_at_10"],
        top1_correct_count=overall["top1_correct_count"],
        high_conf_count=overall["high_conf_count"],
        false_auto_select_rate=overall["false_auto_select_rate"],
        recall_at_5_ci=bootstrap_ci([r.recall_at_5 for r in per_case]),
        mrr_at_10_ci=bootstrap_ci([r.mrr_at_10 for r in per_case]),
        by_label_source=by_label_source,
        per_case=per_case,
    )


def _quantile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数（sorted_vals 必须已升序）。"""
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def bootstrap_ci(
    per_case_values: list[float], *, b: int = 1000, seed: int = 42
) -> tuple[float, float]:
    """均值的 bootstrap 95% CI（有放回重采样 B 次，固定 seed 幂等）。

    n=20 时 CI 宽度通常 ±0.15~0.20——必须打印进报告，防止对 0.02 的均值
    波动过度解读（ROUTING-RANKING §7.2）。纯 stdlib ``random.Random``，
    禁止 numpy/scipy。
    """
    n = len(per_case_values)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(b):
        sample = [per_case_values[rng.randrange(n)] for _ in range(n)]
        means.append(math.fsum(sample) / n)
    means.sort()
    return (_quantile(means, 0.025), _quantile(means, 0.975))


def _metrics_tuple(entry: dict[str, Any]) -> tuple[float, float, bool]:
    return (
        float(entry["recall_at_5"]),
        float(entry["mrr_at_10"]),
        bool(entry["top1_correct"]),
    )


def diff_reports(baseline: dict[str, Any], current: EvalReport) -> CaseDiff:
    """逐例 diff：对照 baseline JSON（dict）与当前 EvalReport。

    变好 = 任一指标提升且无指标下降；变坏 = 任一指标下降（附首位与
    breakdown 两版对照）；其余为 unchanged。
    """
    baseline_by_id = {str(e["case_id"]): e for e in baseline.get("per_case", [])}
    current_by_id = {c.case_id: c for c in current.per_case}

    diff = CaseDiff(
        only_in_baseline=sorted(set(baseline_by_id) - set(current_by_id)),
        only_in_current=sorted(set(current_by_id) - set(baseline_by_id)),
    )
    for case_id in sorted(set(baseline_by_id) & set(current_by_id)):
        base = baseline_by_id[case_id]
        cur = current_by_id[case_id]
        b_metrics = _metrics_tuple(base)
        c_metrics = _metrics_tuple(cur.to_dict())
        b_cmp = (b_metrics[0], b_metrics[1], 1 if b_metrics[2] else 0)
        c_cmp = (c_metrics[0], c_metrics[1], 1 if c_metrics[2] else 0)
        if any(c < b for c, b in zip(c_cmp, b_cmp)):
            diff.regressed.append(
                RegressedCase(
                    case_id=case_id,
                    baseline_top1=str(base.get("top1_repo_id", "")),
                    current_top1=cur.top1_repo_id,
                    baseline_breakdown=dict(base.get("top1_breakdown", {})),
                    current_breakdown=dict(cur.top1_breakdown),
                    baseline_metrics=b_metrics,
                    current_metrics=c_metrics,
                )
            )
        elif any(c > b for c, b in zip(c_cmp, b_cmp)):
            diff.improved.append(case_id)
        else:
            diff.unchanged.append(case_id)
    return diff


__all__ = [
    "MRR_K",
    "RECALL_K",
    "CaseDiff",
    "CaseResult",
    "EvalReport",
    "RegressedCase",
    "bootstrap_ci",
    "diff_reports",
    "evaluate_cases",
    "score_case",
]
