"""仓库路由 golden set 回归门禁（Phase 105-04，ROUTE-08）。

作为普通 pytest 测试进默认 suite（随 `.github/workflows/ci.yaml` server-ci job
自动跑，零 CI 配置改动，per CONTEXT）。评估主路径纯函数零 DB/零网络
（105-RESEARCH Pitfall 4）——θ 阈值用与 settings 默认一致的字面量注入，
门禁不依赖 Django settings 加载。

门禁规则（CONTEXT §golden set 与 CI 门禁原文）：
- ``Recall@5 >= baseline``（不允许任何下降）
- ``Top-1 正确数 >= baseline - 1``（允许 1 例波动）
- ``误自动选中率 <= 10%``
任一失败时 pytest 失败消息包含 ``diff_reports`` 的逐例 diff 全文。

**hold-out 纪律（105-RESEARCH Pitfall 6）**：本文件只加载 golden_main.json
（文件名硬编码 main）；30% hold-out 样本封存于独立文件，仅里程碑验收开箱，
绝不被门禁或调参流程加载。

baseline 重生成流程（沿用既有 golden idiom，
参考 tests/services/retrieval/test_hybrid_graph_capable_golden.py）::

    cd server && GENERATE_GOLDEN=1 uv run pytest \
      tests/codegraph/test_repo_router_golden.py -q
    git diff server/tests/codegraph/fixtures/repo_router_golden/  # 人工 review 逐例 diff
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codegraph.services.repo_router_eval import (
    CaseResult,
    EvalReport,
    diff_reports,
    evaluate_cases,
    score_case,
)
from codegraph.services.repo_router_scoring import (
    WEIGHT_SET_VERSION,
    ScoredCandidate,
)

FIXTURE_DIR: Path = Path(__file__).resolve().parent / "fixtures" / "repo_router_golden"
MAIN_FIXTURE: Path = FIXTURE_DIR / "golden_main.json"
BASELINE_FIXTURE: Path = FIXTURE_DIR / "golden_baseline.json"

# 事故锚点 case（SC-1）：study-app 以命中广度碾压 onion-learning 的真实场景。
GK001_CASE_ID = "gk-001-gaosan-tifen"

# θ 阈值字面量——与 settings 默认（REPO_ROUTER_CONF_THETA_*）一致，
# 但门禁不读 settings：离线纯函数评估不依赖 Django 配置加载。
THETA_ABS = 0.55
THETA_MARGIN = 0.08
THETA_MED = 0.35

# 耗时预算：硬断言 <10s（防 CI 抖动误报），目标 <5s 超出记 log（Pitfall 4）。
HARD_TIME_BUDGET_S = 10.0
SOFT_TIME_BUDGET_S = 5.0

# 护栏指标硬上限（ROUTING-RANKING §7.1：误自动选中率 <= 10%）。
FALSE_AUTO_SELECT_CEILING = 0.10

_GENERATE_MODE: bool = os.environ.get("GENERATE_GOLDEN") == "1"


@pytest.fixture(scope="module")
def golden_cases() -> list[dict[str, Any]]:
    """module-scope 一次性加载主集（绝不加载 hold-out 文件——Pitfall 6）。"""
    return json.loads(MAIN_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def timed_report(
    golden_cases: list[dict[str, Any]],
) -> tuple[EvalReport, float]:
    """全量评估一次并计时（module-scope：门禁/耗时/机制断言共用）。"""
    start = time.monotonic()
    report = evaluate_cases(
        golden_cases,
        theta_abs=THETA_ABS,
        theta_margin=THETA_MARGIN,
        theta_med=THETA_MED,
    )
    elapsed = time.monotonic() - start
    return report, elapsed


@pytest.fixture(scope="module")
def gk001_ranked(golden_cases: list[dict[str, Any]]) -> list[ScoredCandidate]:
    """gk-001 的打分结果（走 score_case——与门禁 evaluate_cases 同一入口）。"""
    case = next(c for c in golden_cases if c["id"] == GK001_CASE_ID)
    return score_case(case)


def _rank_of(ranked: list[ScoredCandidate], repo_id: str) -> int:
    """候选序列中的 0-based 名次；不在候选内直接失败（召回缺失也是退化）。"""
    for idx, cand in enumerate(ranked):
        if cand.repo_id == repo_id:
            return idx
    raise AssertionError(f"{repo_id} 未进候选：{[c.repo_id for c in ranked]}")


def _breadth_of(ranked: list[ScoredCandidate], repo_id: str) -> float:
    """候选的 breadth 分项贡献（信号缺失时该键不存在，按 0 计）。"""
    return ranked[_rank_of(ranked, repo_id)].breakdown.get("breadth", 0.0)


def _load_baseline() -> dict[str, Any]:
    assert BASELINE_FIXTURE.exists(), (
        f"missing baseline: {BASELINE_FIXTURE}; rerun with GENERATE_GOLDEN=1 to generate"
    )
    return json.loads(BASELINE_FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 门禁主测试（含 GENERATE_GOLDEN=1 重生成路径）
# ---------------------------------------------------------------------------


def test_golden_gate_vs_baseline(timed_report: tuple[EvalReport, float]) -> None:
    """三规则门禁：Recall@5 不降 / Top-1 允许 1 例波动 / 误自动选中率 <=10%。"""
    report, _ = timed_report

    if _GENERATE_MODE:
        payload = report.to_dict()
        payload["generated_at"] = datetime.now(UTC).isoformat()
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        BASELINE_FIXTURE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        pytest.skip(
            f"GENERATE_GOLDEN=1 → wrote baseline {BASELINE_FIXTURE.name} "
            f"(recall@5={report.recall_at_5:.4f} "
            f"top1={report.top1_correct_count}/{report.case_count})"
        )

    baseline = _load_baseline()

    # 版本绑定守护（ROUTING-RANKING §6.2-9）：跨打分版本的指标不可比。
    assert baseline["weight_set_version"] == WEIGHT_SET_VERSION, (
        f"baseline weight_set_version={baseline['weight_set_version']!r} != "
        f"当前 {WEIGHT_SET_VERSION!r}：打分版本变更须 GENERATE_GOLDEN=1 "
        f"重建 baseline 并 review 逐例 diff"
    )

    diff_text = diff_reports(baseline, report).to_text()

    assert report.recall_at_5 >= baseline["recall_at_5"] - 1e-9, (
        f"门禁失败：Recall@5 退化 {baseline['recall_at_5']:.4f} -> "
        f"{report.recall_at_5:.4f}（不允许任何下降）\n{diff_text}"
    )
    assert report.top1_correct_count >= baseline["top1_correct_count"] - 1, (
        f"门禁失败：Top-1 正确数 {baseline['top1_correct_count']} -> "
        f"{report.top1_correct_count}（超出 1 例波动容忍）\n{diff_text}"
    )
    assert report.false_auto_select_rate <= FALSE_AUTO_SELECT_CEILING, (
        f"门禁失败：误自动选中率 {report.false_auto_select_rate:.4f} > "
        f"{FALSE_AUTO_SELECT_CEILING}（编排被错误自动推进的护栏）\n{diff_text}"
    )


def test_baseline_carries_version_and_ci_fields() -> None:
    """baseline JSON 必含 weight_set_version / bootstrap_ci /（生成时间）字段。"""
    if _GENERATE_MODE:
        pytest.skip("GENERATE_GOLDEN=1 生成模式，跳过 baseline 字段校验")
    baseline = _load_baseline()
    # 版本守护字面绑定（Pitfall 8）：bump WEIGHT_SET_VERSION 必须与 baseline
    # 重建同一提交生效——任一单独改动都会使本断言或上面的守护断言失败。
    assert WEIGHT_SET_VERSION == "phase106-v1"
    assert baseline["weight_set_version"] == WEIGHT_SET_VERSION
    assert "generated_at" in baseline
    ci = baseline["bootstrap_ci"]
    lo, hi = ci["recall_at_5"]
    assert 0.0 <= lo <= hi <= 1.0
    lo2, hi2 = ci["mrr_at_10"]
    assert 0.0 <= lo2 <= hi2 <= 1.0


# ---------------------------------------------------------------------------
# 耗时断言（Pitfall 4：全量离线纯函数零网络）
# ---------------------------------------------------------------------------


def test_full_eval_within_time_budget(
    timed_report: tuple[EvalReport, float],
) -> None:
    """全量评估 < 10s 硬断言；> 5s 记 log（目标 <5s，宽松防 CI 抖动）。"""
    _, elapsed = timed_report
    assert elapsed < HARD_TIME_BUDGET_S, (
        f"golden 全量评估耗时 {elapsed:.2f}s >= {HARD_TIME_BUDGET_S}s——"
        f"检查是否混入 DB/网络依赖（Pitfall 4）"
    )
    if elapsed > SOFT_TIME_BUDGET_S:
        print(
            f"WARNING: golden 全量评估耗时 {elapsed:.2f}s 超过软目标 "
            f"{SOFT_TIME_BUDGET_S}s（硬上限 {HARD_TIME_BUDGET_S}s）"
        )


# ---------------------------------------------------------------------------
# 机制级断言（ROUTING-RANKING §7.4：锁因果性质，不锁权重敏感的绝对名次）
#
# 下面三条是 Phase 106 SC-1 的验收锚点：断言的是「尺寸偏置已被消除」这一机制，
# 而非某组权重下的偶然名次——权重微调不应使其变色（脆弱断言反例见 §7.4）。
# ---------------------------------------------------------------------------


def test_all_candidates_satisfy_score_invariants(
    golden_cases: list[dict[str, Any]],
) -> None:
    """INV-R1/R3 对 golden set 全部候选成立（无截断 + 分解恒等）。"""
    for case in golden_cases:
        for cand in score_case(case):
            assert 0.0 <= cand.score <= 1.0, (case["id"], cand.repo_id, cand.score)
            assert math.fsum(cand.breakdown.values()) == cand.score, (
                case["id"],
                cand.repo_id,
            )


def test_gk001_mechanism_breadth_not_favor_monolith(
    gk001_ranked: list[ScoredCandidate],
) -> None:
    """尺寸偏置已消除：巨仓 study-app 的 breadth 贡献不高于小仓 onion-learning。

    pivoted normalization 的因果性质——命中数多但仓体量更大（N_r=620 vs 30）时，
    广度分项不再奖励巨仓。这是机制断言，与两者最终名次无关。
    """
    monolith = _breadth_of(gk001_ranked, "study-app")
    focused = _breadth_of(gk001_ranked, "onion-learning")
    assert monolith <= focused, (
        f"breadth 仍偏袒巨仓：study-app={monolith:.4f} > "
        f"onion-learning={focused:.4f}（pivoted normalization 失效）"
    )


def test_gk001_mechanism_rank_flipped(
    gk001_ranked: list[ScoredCandidate],
) -> None:
    """事故翻转：onion-learning 排在 study-app 之前（Phase 105 baseline 为反）。"""
    assert _rank_of(gk001_ranked, "onion-learning") < _rank_of(gk001_ranked, "study-app"), (
        f"gk-001 未翻转：{[c.repo_id for c in gk001_ranked]}"
    )


def test_gk001_cross_group_repos_in_top5(
    gk001_ranked: list[ScoredCandidate],
) -> None:
    """跨组两仓进 Top-5：新信号不得把 study-course / study-user-status 压出窗口。"""
    top5 = [c.repo_id for c in gk001_ranked[:5]]
    assert "study-course" in top5, top5
    assert "study-user-status" in top5, top5


def test_evaluation_is_deterministic(
    golden_cases: list[dict[str, Any]],
) -> None:
    """同一 golden set 评估两遍，报告逐字段相等（含 per-case 与 CI）。"""
    kwargs = dict(theta_abs=THETA_ABS, theta_margin=THETA_MARGIN, theta_med=THETA_MED)
    first = evaluate_cases(golden_cases, **kwargs)
    second = evaluate_cases(golden_cases, **kwargs)
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# diff_reports 自测：退化可被检出且失败消息含逐例 breakdown 对照
# ---------------------------------------------------------------------------


def _case_result(
    *,
    case_id: str,
    top1: str,
    top1_correct: bool,
    recall: float,
    breakdown: dict[str, float],
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        label_source="human",
        cross_group=False,
        expected_repos=["right-repo"],
        ranked_repo_ids=[top1, "other-repo"],
        top1_repo_id=top1,
        top1_breakdown=breakdown,
        confidence="medium",
        recall_at_5=recall,
        mrr_at_10=recall,
        top1_correct=top1_correct,
    )


def test_diff_reports_surfaces_regressed_case_with_breakdown() -> None:
    """构造退化 report：diff 输出必须含 regressed case id 与 breakdown 对照。"""
    baseline = {
        "per_case": [
            {
                "case_id": "gk-regress-demo",
                "recall_at_5": 1.0,
                "mrr_at_10": 1.0,
                "top1_correct": True,
                "top1_repo_id": "right-repo",
                "top1_breakdown": {"text": 0.7, "breadth": 0.2},
            },
            {
                "case_id": "gk-improve-demo",
                "recall_at_5": 0.5,
                "mrr_at_10": 0.5,
                "top1_correct": False,
                "top1_repo_id": "wrong-repo",
                "top1_breakdown": {"text": 0.4},
            },
        ]
    }
    current = EvalReport(
        case_count=2,
        recall_at_5=0.5,
        mrr_at_10=0.5,
        top1_correct_count=1,
        high_conf_count=0,
        false_auto_select_rate=0.0,
        recall_at_5_ci=(0.0, 1.0),
        mrr_at_10_ci=(0.0, 1.0),
        by_label_source={},
        per_case=[
            _case_result(
                case_id="gk-regress-demo",
                top1="wrong-repo",
                top1_correct=False,
                recall=0.0,
                breakdown={"text": 0.35, "breadth": 0.2},
            ),
            _case_result(
                case_id="gk-improve-demo",
                top1="right-repo",
                top1_correct=True,
                recall=1.0,
                breakdown={"text": 0.7},
            ),
        ],
    )

    diff = diff_reports(baseline, current)
    assert [r.case_id for r in diff.regressed] == ["gk-regress-demo"]
    assert diff.improved == ["gk-improve-demo"]

    text = diff.to_text()
    assert "gk-regress-demo" in text
    assert "breakdown" in text
    assert "'right-repo' -> current='wrong-repo'" in text
