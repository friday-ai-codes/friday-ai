"""``codegraph.services.repo_route_recall_eval`` 单测：分层归因与门禁比对。

纯函数、零 I/O、零网络（与 ``repo_router_eval`` 同款纪律）。

守的核心契约：**分层归因必须指向最靠前的缺失层**。只报一个 Recall 数字说明不了
任何问题——「漏了」发生在检索/聚合/LLM 三层的修法完全不同（实测 study-course 是
聚合层丢的，若误判成检索层就会去调索引，方向全错）。
"""

from __future__ import annotations

from codegraph.services.repo_route_recall_eval import (
    LOST_AT_AGGREGATION,
    LOST_AT_LLM,
    LOST_AT_NONE,
    LOST_AT_RETRIEVAL,
    aggregate_report,
    attribute_losses,
    compare_to_baseline,
    evaluate_case,
)

# ---------------------------------------------------------------------------
# 分层归因
# ---------------------------------------------------------------------------


def test_hit_is_attributed_none() -> None:
    assert attribute_losses(["a"], ["a"], ["a"], ["a"]) == {"a": LOST_AT_NONE}


def test_missing_from_retrieval_is_attributed_retrieval() -> None:
    assert attribute_losses(["a"], [], [], []) == {"a": LOST_AT_RETRIEVAL}


def test_retrieved_but_not_candidate_is_aggregation() -> None:
    """study-course 的真实形态：融合节点里有它，却挤不进仓级候选池。"""
    assert attribute_losses(["a"], ["a"], [], []) == {"a": LOST_AT_AGGREGATION}


def test_candidate_but_not_final_is_llm() -> None:
    assert attribute_losses(["a"], ["a"], ["a"], []) == {"a": LOST_AT_LLM}


def test_attribution_points_at_earliest_missing_layer() -> None:
    """检索层就没有的仓，后两层必然也没有——根因是最靠前那次缺失，不是后果。"""
    assert attribute_losses(["a"], [], ["a"], ["a"]) == {"a": LOST_AT_NONE}
    assert attribute_losses(["a"], [], [], ["a"]) == {"a": LOST_AT_NONE}
    assert attribute_losses(["a"], [], ["a"], []) == {"a": LOST_AT_RETRIEVAL}


def test_mixed_expectations_each_get_own_layer() -> None:
    got = attribute_losses(
        ["hit", "lost_retrieval", "lost_agg", "lost_llm"],
        ["hit", "lost_agg", "lost_llm"],
        ["hit", "lost_llm"],
        ["hit"],
    )
    assert got == {
        "hit": LOST_AT_NONE,
        "lost_retrieval": LOST_AT_RETRIEVAL,
        "lost_agg": LOST_AT_AGGREGATION,
        "lost_llm": LOST_AT_LLM,
    }


# ---------------------------------------------------------------------------
# case / 聚合
# ---------------------------------------------------------------------------


def _case(cid: str, expected, retrieved, candidates, final):
    return evaluate_case(
        case_id=cid,
        corpus_kind="requirement",
        query_len=100,
        probe_count=1,
        expected=expected,
        retrieved=retrieved,
        candidates=candidates,
        final=final,
    )


def test_case_recalls_are_monotonic_down_the_pipeline() -> None:
    c = _case("x", ["a", "b"], ["a", "b"], ["a"], ["a"])
    assert c.node_recall == 1.0
    assert c.candidate_recall == 0.5
    assert c.final_recall == 0.5


def test_empty_expected_scores_full() -> None:
    c = _case("x", [], [], [], [])
    assert c.final_recall == 1.0


def test_aggregate_uses_macro_average() -> None:
    """按 case 取平均而非按仓合并：否则 expected 多的 case 会主导指标，
    掩盖小 case 的整体失败。"""
    big = _case("big", ["a", "b", "c", "d"], ["a", "b", "c", "d"], ["a", "b", "c", "d"],
                ["a", "b", "c", "d"])
    small = _case("small", ["z"], [], [], [])
    report = aggregate_report([big, small])
    # micro 会是 4/5 = 0.8；macro 是 (1.0 + 0.0)/2 = 0.5
    assert report.final_recall == 0.5
    assert report.full_recall_cases == 1
    assert report.total_cases == 2


def test_aggregate_counts_losses_by_layer() -> None:
    report = aggregate_report([
        _case("a", ["x"], ["x"], [], []),
        _case("b", ["y"], [], [], []),
        _case("c", ["z"], ["z"], ["z"], ["z"]),
    ])
    assert report.lost_counts == {
        LOST_AT_AGGREGATION: 1,
        LOST_AT_RETRIEVAL: 1,
        LOST_AT_NONE: 1,
    }


def test_aggregate_empty_is_safe() -> None:
    report = aggregate_report([])
    assert report.total_cases == 0
    assert report.final_recall == 0.0


# ---------------------------------------------------------------------------
# 门禁比对
# ---------------------------------------------------------------------------


def test_no_baseline_passes() -> None:
    report = aggregate_report([_case("a", ["x"], [], [], [])])
    passed, failures = compare_to_baseline(report, None)
    assert passed is True
    assert failures == []


def test_regression_fails_the_gate() -> None:
    report = aggregate_report([_case("a", ["x"], [], [], [])])
    passed, failures = compare_to_baseline(
        report, {"node_recall": 1.0, "candidate_recall": 1.0, "final_recall": 1.0}
    )
    assert passed is False
    assert len(failures) == 3


def test_rounded_baseline_does_not_self_trigger() -> None:
    """基线持久化会四舍五入（0.916666… → 0.9167）。比对若拿未舍入值直接比，
    "完全没变"会被报成回退——门禁一旦开始误报就没人再看它。"""
    cases = [
        _case("a", ["x", "y", "z", "w"], ["x", "y", "z", "w"], ["x", "y", "z"], ["x", "y", "z"]),
        _case("b", ["p"], ["p"], ["p"], ["p"]),
        _case("c", ["q"], ["q"], ["q"], ["q"]),
    ]
    report = aggregate_report(cases)
    assert abs(report.candidate_recall - 0.916666) < 1e-4
    passed, failures = compare_to_baseline(report, {"candidate_recall": 0.9167})
    assert passed is True, failures


def test_llm_layer_has_slack_but_deterministic_layers_do_not() -> None:
    """Stage 1 是 LLM，轮次抖动是常态；检索/聚合是确定性的，必须严卡。"""
    # 只有最终层下滑（LLM 排掉一个），检索与聚合都满分
    llm_only = aggregate_report([_case("a", ["x", "y"], ["x", "y"], ["x", "y"], ["x"])])
    assert llm_only.candidate_recall == 1.0
    passed, _ = compare_to_baseline(
        llm_only, {"candidate_recall": 1.0, "final_recall": 1.0}, llm_tolerance=0.5
    )
    assert passed is True

    # 同样幅度的下滑发生在聚合层：零容差，必须拦下
    agg_drop = aggregate_report([_case("b", ["x", "y"], ["x", "y"], ["x"], ["x"])])
    assert agg_drop.candidate_recall == 0.5
    passed, failures = compare_to_baseline(
        agg_drop, {"candidate_recall": 1.0}, llm_tolerance=0.5
    )
    assert passed is False
    assert any("candidate_recall" in f for f in failures)


def test_improvement_passes_the_gate() -> None:
    report = aggregate_report([_case("a", ["x"], ["x"], ["x"], ["x"])])
    passed, failures = compare_to_baseline(
        report, {"node_recall": 0.5, "candidate_recall": 0.5, "final_recall": 0.5}
    )
    assert passed is True
    assert failures == []


def test_masked_regression_is_caught_by_layered_comparison() -> None:
    """检索层退步、但最终层恰好被 LLM 蒙对——只卡 final_recall 会放过这种掩盖式
    回归，而它随时会翻车。逐层比对必须拦下。"""
    report = aggregate_report([_case("a", ["x"], [], ["x"], ["x"])])
    assert report.final_recall == 1.0
    passed, failures = compare_to_baseline(
        report, {"node_recall": 1.0, "candidate_recall": 1.0, "final_recall": 1.0}
    )
    assert passed is False
    assert any("node_recall" in f for f in failures)


def test_tolerance_allows_configured_slack() -> None:
    report = aggregate_report([_case("a", ["x", "y"], ["x", "y"], ["x", "y"], ["x"])])
    assert report.final_recall == 0.5
    passed, _ = compare_to_baseline(report, {"final_recall": 0.6}, llm_tolerance=0.2)
    assert passed is True


def test_full_recall_case_count_regression_fails() -> None:
    report = aggregate_report([_case("a", ["x"], ["x"], ["x"], [])])
    passed, failures = compare_to_baseline(
        report, {"full_recall_cases": 1}, llm_tolerance=0.0
    )
    assert passed is False
    assert any("full_recall_cases" in f for f in failures)
