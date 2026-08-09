"""端到端仓库路由召回评测：指标与分层归因（纯函数，零 I/O）。

**为什么需要它（这是本模块存在的全部理由）。** 仓里已有 golden 门禁
``repo_router_eval`` + ``test_repo_router_golden``，指标齐全（Recall@5 / MRR@10 /
bootstrap CI），但它的 case **直接内联 ``node_hits``**，模块契约明写「零 I/O、零
网络、不依赖 embedding」。也就是说它测的是「**给定候选池之后**排序对不对」，
embedding 与 Qdrant 这一阶召回整个在门禁之外。

2026-08 的实证：``_QUERY_CHAR_BUDGET=4000`` 把 45 个功能点截到只剩 7 个，目标仓
``study-course`` 因此从未进入候选，5 次路由 0 次全中——而这套 golden 门禁**在结构上
看不见**这类失败（把预算改成 40 或 40000，它的结果一个字都不会变）。这个缺陷因此
在线上活了两个月。

本模块补的正是另一半：**端到端 Recall@k**，且按层归因。离线 golden 守排序层的
确定性，本评测守召回层的天花板，两者互补，都不可替代对方。

分层归因是核心设计。只报一个 Recall 数字说明不了任何问题——「漏了」可能发生在
四个完全不同的地方，修法也完全不同：

===============  ====================================  ==========================
 lost_at          含义                                  修的方向
===============  ====================================  ==========================
``retrieval``     该仓的节点压根没进 Stage 0 融合结果    索引/切块/召回预算/query 形态
``aggregation``   节点进了，但仓级聚合没让它进候选池    打分权重（如 breadth 失真）
``llm``           进了候选池，但 Stage 1 把它排掉了      prompt / 候选数 / 精排
``none``          命中                                  —
===============  ====================================  ==========================

（``study-course`` 实测就是 ``aggregation``：融合节点里排 #58 稳稳在内，却因节点数
少而挤不进仓级 top-12。若只看总 Recall，极易误判成"检索没召回"而去调索引，方向全错。）

本模块**只做算术**：case 的实际执行（embedding / Qdrant / LLM）在
``codegraph.management.commands.evaluate_repo_route_recall`` 里，本模块保持零 I/O
以便单测与 ``--disable-socket`` 下运行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "LOST_AT_RETRIEVAL",
    "LOST_AT_AGGREGATION",
    "LOST_AT_LLM",
    "LOST_AT_NONE",
    "CaseOutcome",
    "RecallReport",
    "attribute_losses",
    "evaluate_case",
    "aggregate_report",
    "compare_to_baseline",
]

LOST_AT_RETRIEVAL = "retrieval"
LOST_AT_AGGREGATION = "aggregation"
LOST_AT_LLM = "llm"
LOST_AT_NONE = "none"


@dataclass
class CaseOutcome:
    """单条 case 的评测结果（进报告 JSON，供逐例 diff）。"""

    case_id: str
    corpus_kind: str
    query_len: int
    probe_count: int
    expected: list[str] = field(default_factory=list)
    # 三层实际到达集合（均为 repository_id 字符串）
    retrieved: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    final: list[str] = field(default_factory=list)
    # expected 中每个仓的丢失层（命中记 LOST_AT_NONE）
    lost_at: dict[str, str] = field(default_factory=dict)
    node_recall: float = 0.0
    candidate_recall: float = 0.0
    final_recall: float = 0.0
    duration_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "corpus_kind": self.corpus_kind,
            "query_len": self.query_len,
            "probe_count": self.probe_count,
            "expected": list(self.expected),
            "retrieved": list(self.retrieved),
            "candidates": list(self.candidates),
            "final": list(self.final),
            "lost_at": dict(self.lost_at),
            "node_recall": round(self.node_recall, 4),
            "candidate_recall": round(self.candidate_recall, 4),
            "final_recall": round(self.final_recall, 4),
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class RecallReport:
    """整轮评测的聚合报告。"""

    cases: list[CaseOutcome] = field(default_factory=list)
    node_recall: float = 0.0
    candidate_recall: float = 0.0
    final_recall: float = 0.0
    # 各层丢失计数（跨全部 case 的 expected 仓维度）
    lost_counts: dict[str, int] = field(default_factory=dict)
    full_recall_cases: int = 0
    total_cases: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_recall": round(self.node_recall, 4),
            "candidate_recall": round(self.candidate_recall, 4),
            "final_recall": round(self.final_recall, 4),
            "lost_counts": dict(self.lost_counts),
            "full_recall_cases": self.full_recall_cases,
            "total_cases": self.total_cases,
            "cases": [c.to_dict() for c in self.cases],
        }


def _recall(expected: list[str], actual: list[str]) -> float:
    """|expected ∩ actual| / |expected|；expected 为空记 1.0（无可漏即满分）。"""
    if not expected:
        return 1.0
    got = set(actual)
    return sum(1 for e in expected if e in got) / len(expected)


def attribute_losses(
    expected: list[str],
    retrieved: list[str],
    candidates: list[str],
    final: list[str],
) -> dict[str, str]:
    """给 ``expected`` 里每个仓判定丢失层（命中记 ``none``）。

    判定按管线顺序**从前往后**：一个仓若在检索层就没出现，即记 ``retrieval``，
    不再追问后面两层——最靠前的缺失才是根因，后面的缺失只是它的必然后果。
    """
    got_r, got_c, got_f = set(retrieved), set(candidates), set(final)
    out: dict[str, str] = {}
    for repo_id in expected:
        if repo_id in got_f:
            out[repo_id] = LOST_AT_NONE
        elif repo_id not in got_r:
            out[repo_id] = LOST_AT_RETRIEVAL
        elif repo_id not in got_c:
            out[repo_id] = LOST_AT_AGGREGATION
        else:
            out[repo_id] = LOST_AT_LLM
    return out


def evaluate_case(
    *,
    case_id: str,
    corpus_kind: str,
    query_len: int,
    probe_count: int,
    expected: list[str],
    retrieved: list[str],
    candidates: list[str],
    final: list[str],
    duration_ms: int = 0,
    error: str = "",
) -> CaseOutcome:
    """把一条 case 的三层实际到达集合折算成 :class:`CaseOutcome`。"""
    return CaseOutcome(
        case_id=case_id,
        corpus_kind=corpus_kind,
        query_len=query_len,
        probe_count=probe_count,
        expected=list(expected),
        retrieved=list(retrieved),
        candidates=list(candidates),
        final=list(final),
        lost_at=attribute_losses(expected, retrieved, candidates, final),
        node_recall=_recall(expected, retrieved),
        candidate_recall=_recall(expected, candidates),
        final_recall=_recall(expected, final),
        duration_ms=duration_ms,
        error=error,
    )


def aggregate_report(cases: list[CaseOutcome]) -> RecallReport:
    """跨 case 聚合。

    三个 recall 用**按 case 取平均**（macro）而非按仓合并（micro）：case 之间
    expected 数量差异很大（有的 1 个仓、有的 4 个），micro 会让"仓多的 case"
    主导指标，掩盖小 case 的整体失败。
    """
    if not cases:
        return RecallReport()
    lost_counts: dict[str, int] = {}
    for c in cases:
        for layer in c.lost_at.values():
            lost_counts[layer] = lost_counts.get(layer, 0) + 1
    n = len(cases)
    return RecallReport(
        cases=list(cases),
        node_recall=sum(c.node_recall for c in cases) / n,
        candidate_recall=sum(c.candidate_recall for c in cases) / n,
        final_recall=sum(c.final_recall for c in cases) / n,
        lost_counts=lost_counts,
        full_recall_cases=sum(1 for c in cases if c.final_recall >= 1.0),
        total_cases=n,
    )


# 基线持久化时保留的小数位。比对**必须先按同精度取整**，否则未舍入的当前值
# （0.916666…）会输给舍入后的基线（0.9167），把"完全没变"报成回退。
_BASELINE_PRECISION = 4

# 最终层默认容差。检索层与聚合层是确定性的（同输入同输出），可以零容差严卡；
# 但 Stage 1 是 LLM，**天然有轮次抖动**——实测同一条 case 相邻两次 final 在
# 1.00 与 0.00 之间跳（opus 4.8 拒收 temperature，"固定 decode 参数"这道幂等
# 防线在该模型上完全失效）。用同一把尺子卡两类层，门禁会被抖动淹没，最后没人
# 再看它——那就退化成当初那个"存在但看不见真问题"的门禁了。
DEFAULT_LLM_TOLERANCE = 0.34


def compare_to_baseline(
    report: RecallReport,
    baseline: dict[str, Any] | None,
    *,
    tolerance: float = 0.0,
    llm_tolerance: float | None = None,
) -> tuple[bool, list[str]]:
    """与基线比对，返回 ``(是否通过, 失败原因列表)``。

    三个 recall **逐层**比对而非只看最终值：只卡 ``final_recall`` 会让「检索层退步
    但恰好被 LLM 蒙对」这类掩盖式回归溜过去，而它随时会翻车。

    Args:
        tolerance: 确定性层（``node_recall`` / ``candidate_recall``）允许的下滑幅度，
            默认 0（不许退步）。
        llm_tolerance: ``final_recall`` 允许的下滑幅度，缺省
            :data:`DEFAULT_LLM_TOLERANCE`（理由见该常量注释）。

    无基线时视为通过（首次跑即生成基线）。
    """
    if not baseline:
        return True, []
    llm_tol = DEFAULT_LLM_TOLERANCE if llm_tolerance is None else llm_tolerance
    failures: list[str] = []
    for key, tol in (
        ("node_recall", tolerance),
        ("candidate_recall", tolerance),
        ("final_recall", llm_tol),
    ):
        base = baseline.get(key)
        if not isinstance(base, (int, float)):
            continue
        now = round(getattr(report, key), _BASELINE_PRECISION)
        if now + tol < round(float(base), _BASELINE_PRECISION):
            failures.append(
                f"{key} 回退：基线 {base:.4f} → 本次 {now:.4f}（容差 {tol:.4f}）"
            )
    base_full = baseline.get("full_recall_cases")
    # 全中 case 数同样受 LLM 抖动影响，按容差折算成允许少中几条。
    if isinstance(base_full, int):
        allowed_drop = int(round(llm_tol * max(1, report.total_cases)))
        if report.full_recall_cases + allowed_drop < base_full:
            failures.append(
                f"full_recall_cases 回退：基线 {base_full} → 本次 "
                f"{report.full_recall_cases}（允许少 {allowed_drop} 条）"
            )
    return (not failures), failures
