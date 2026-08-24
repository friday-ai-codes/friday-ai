"""BENCH-03/04/05：逐 case 指标 scorer、空结果规则、分桶、INSUFFICIENT_DATA 与无阈值报告。

全部为零 I/O 纯函数单测（默认 ``--disable-socket`` 套件可跑）：注入合成 arrival
set 与 :class:`GoldCase`，直接断言各 scorer 与聚合报告的口径，不触网络/ORM/Qdrant。

覆盖三条红线（PITFALLS B0）：
- 空 gold 记 ``NO_GOLD``（非满分）、无预测记 ``N/A``、seed 缺失记 ``SEED_MISSING``、
  ``node_not_in_graph`` 单列不进成功率分母；
- 分桶按 ``language × framework × entry_type``，``n < MIN_BUCKET_SAMPLES`` 标
  ``INSUFFICIENT_DATA`` 且不进 overall；受保护桶单列不被 overall 抵消；
- 报告只含原始值与空结果标记，绝无任何回归门/比对字段。
"""

from __future__ import annotations

from codegraph.services.graph_bench_eval import (
    BUCKET_OK,
    INSUFFICIENT_DATA,
    MIN_BUCKET_SAMPLES,
    NO_GOLD,
    NOT_APPLICABLE,
    SEED_MISSING,
    GoldCase,
    rank_process_candidates,
    score_edge_pr,
    score_impact_precision,
    score_process_recall,
    score_symbol_recall,
    score_trace,
)


def _gold(**overrides) -> GoldCase:
    base = {
        "case_id": "c-1",
        "split": "dev",
        "query": "q",
        "language": "python",
        "framework": "django",
        "entry_type": "http_endpoint",
    }
    base.update(overrides)
    return GoldCase(**base)


class TestScoreSymbolRecall:
    def test_empty_gold_is_no_gold(self) -> None:
        assert score_symbol_recall([], ["a", "b"]) == NO_GOLD

    def test_empty_prediction_with_gold_is_zero(self) -> None:
        assert score_symbol_recall(["a", "b"], []) == 0.0

    def test_partial_hit(self) -> None:
        assert score_symbol_recall(["a", "b"], ["a", "x"]) == 0.5

    def test_full_hit(self) -> None:
        assert score_symbol_recall(["a", "b"], ["b", "a", "c"]) == 1.0


class TestRankProcessCandidates:
    def test_deterministic_overlap_then_key_order(self) -> None:
        retrieved = ["s1", "s2"]
        candidates = [
            {"process_key": "p_b", "step_symbol_uids": ["s1"]},
            {"process_key": "p_a", "step_symbol_uids": ["s1", "s2"]},
            {"process_key": "p_c", "step_symbol_uids": ["s1"]},
        ]
        # p_a 交集 2 居首；p_b/p_c 交集均 1，按 process_key 升序决胜
        assert rank_process_candidates(retrieved, candidates) == ["p_a", "p_b", "p_c"]

    def test_empty_retrieved_falls_back_to_key_order(self) -> None:
        candidates = [
            {"process_key": "p_b", "step_symbol_uids": ["x"]},
            {"process_key": "p_a", "step_symbol_uids": ["y"]},
        ]
        assert rank_process_candidates([], candidates) == ["p_a", "p_b"]


class TestScoreProcessRecall:
    def test_empty_gold_is_no_gold(self) -> None:
        assert score_process_recall([], ["p1"]) == NO_GOLD

    def test_exact_key_miss_is_zero(self) -> None:
        assert score_process_recall(["p1"], ["p2", "p3"]) == 0.0

    def test_exact_key_hit(self) -> None:
        assert score_process_recall(["p1", "p2"], ["p2", "p9"]) == 0.5

    def test_no_fuzzy_name_match(self) -> None:
        # 名称相近但 process_key 不同 → 不算命中（禁名称模糊命中）
        assert score_process_recall(["checkout"], ["checkout_flow"]) == 0.0


class TestScoreEdgePr:
    def test_no_prediction_precision_na(self) -> None:
        golds = [{"caller_uid": "a", "callee_uid": "b"}]
        out = score_edge_pr(golds, [])
        assert out["precision"] == NOT_APPLICABLE
        assert out["recall"] == 0.0

    def test_empty_gold_recall_no_gold(self) -> None:
        preds = [{"caller_uid": "a", "callee_uid": "b"}]
        out = score_edge_pr([], preds)
        assert out["recall"] == NO_GOLD
        assert out["precision"] == 0.0

    def test_pr_values(self) -> None:
        golds = [
            {"caller_uid": "a", "callee_uid": "b"},
            {"caller_uid": "c", "callee_uid": "d"},
        ]
        preds = [
            {"caller_uid": "a", "callee_uid": "b"},
            {"caller_uid": "x", "callee_uid": "y"},
        ]
        out = score_edge_pr(golds, preds)
        assert out["precision"] == 0.5  # 1/2 预测边命中
        assert out["recall"] == 0.5  # 1/2 gold 边被召回


class TestScoreImpactPrecision:
    def test_seed_missing(self) -> None:
        assert (
            score_impact_precision(["a"], ["a"], seed_in_graph=False) == SEED_MISSING
        )

    def test_empty_prediction_is_na(self) -> None:
        assert score_impact_precision(["a"], [], seed_in_graph=True) == NOT_APPLICABLE

    def test_empty_expected_is_no_gold(self) -> None:
        assert score_impact_precision([], ["a"], seed_in_graph=True) == NO_GOLD

    def test_precision_value(self) -> None:
        # 分母 = 预测受影响数
        assert score_impact_precision(["a", "b"], ["a", "x"], seed_in_graph=True) == 0.5


class TestScoreTrace:
    def test_success_and_no_path(self) -> None:
        golds = [
            {"source_uid": "a", "target_uid": "b"},
            {"source_uid": "c", "target_uid": "d"},
        ]
        results = [
            {"found": True, "path": ["a", "b"]},
            {"found": False, "reason": "no_path"},
        ]
        out = score_trace(golds, results)
        assert out["denominator"] == 2
        assert out["success_rate"] == 0.5
        assert out["error_path_rate"] == 0.0
        assert out["node_not_in_graph_count"] == 0

    def test_error_path_when_path_mismatches_expected(self) -> None:
        golds = [{"source_uid": "a", "target_uid": "b", "expected_path": ["a", "b"]}]
        results = [{"found": True, "path": ["a", "zz", "b"]}]
        out = score_trace(golds, results)
        assert out["success_rate"] == 0.0
        assert out["error_path_rate"] == 1.0

    def test_node_not_in_graph_excluded_from_denominator(self) -> None:
        golds = [
            {"source_uid": "a", "target_uid": "b"},
            {"source_uid": "ghost", "target_uid": "b"},
        ]
        results = [
            {"found": True, "path": ["a", "b"]},
            {"found": False, "reason": "node_not_in_graph"},
        ]
        out = score_trace(golds, results)
        assert out["node_not_in_graph_count"] == 1
        assert out["denominator"] == 1  # ghost 查询不进分母
        assert out["success_rate"] == 1.0

    def test_no_measurable_query_is_no_gold(self) -> None:
        out = score_trace([], [])
        assert out["denominator"] == 0
        assert out["success_rate"] == NO_GOLD
        assert out["error_path_rate"] == NO_GOLD


class TestConstants:
    def test_min_bucket_samples_default(self) -> None:
        assert MIN_BUCKET_SAMPLES >= 1
        assert BUCKET_OK == "OK"
        assert INSUFFICIENT_DATA == "INSUFFICIENT_DATA"
