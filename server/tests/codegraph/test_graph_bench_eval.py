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
    NODE_NOT_IN_GRAPH,
    NOT_APPLICABLE,
    SEED_MISSING,
    CaseOutcome,
    GoldCase,
    aggregate_report,
    bucket_metrics,
    bucket_status,
    build_report,
    build_run_identity,
    evaluate_case,
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
        assert NODE_NOT_IN_GRAPH == "node_not_in_graph"


def _full_gold() -> GoldCase:
    return _gold(
        expected_symbols=[{"uid": "s1"}, {"uid": "s2"}],
        expected_processes=[{"process_key": "p1"}],
        edge_golds=[{"caller_uid": "a", "callee_uid": "b", "call_shape": "direct"}],
        trace_golds=[{"source_uid": "a", "target_uid": "b"}],
        impact_golds=[{"seed_uid": "b", "expected_affected_uids": ["a"]}],
    )


class TestEvaluateCase:
    def test_full_arrival_set_scores_all_metrics(self) -> None:
        outcome = evaluate_case(
            gold=_full_gold(),
            predicted_symbol_uids=["s1", "s9"],
            candidate_processes=[{"process_key": "p1", "step_symbol_uids": ["s1"]}],
            predicted_edges=[{"caller_uid": "a", "callee_uid": "b"}],
            impact_result={"affected_uids": ["a", "x"], "seed_in_graph": True},
            trace_results=[{"found": True, "path": ["a", "b"]}],
            cold_ms=120,
            warm_ms=30,
            tokens=42,
        )
        assert outcome.symbol_recall == 0.5
        assert outcome.process_recall == 1.0
        assert outcome.edge_precision == 1.0
        assert outcome.edge_recall == 1.0
        assert outcome.impact_precision == 0.5  # 1/2 预测受影响命中
        assert outcome.trace_success_rate == 1.0
        assert outcome.trace_error_path_rate == 0.0
        assert outcome.trace_node_not_in_graph_count == 0
        assert outcome.cold_ms == 120
        assert outcome.warm_ms == 30
        assert outcome.tokens == 42
        assert outcome.error == ""

    def test_symbol_recall_uses_top5_and_process_uses_ranked_top3(self) -> None:
        gold = _gold(
            expected_symbols=[{"uid": "s6"}],
            expected_processes=[{"process_key": "p_low"}],
        )
        outcome = evaluate_case(
            gold=gold,
            # s6 排在第 6 位（超出 Recall@5 窗口）
            predicted_symbol_uids=["s1", "s2", "s3", "s4", "s5", "s6"],
            candidate_processes=[
                {"process_key": "p_high", "step_symbol_uids": ["s1", "s2", "s3"]},
                {"process_key": "p_low", "step_symbol_uids": ["s6"]},
            ],
            predicted_edges=[],
            impact_result={},
            trace_results=[],
        )
        assert outcome.symbol_recall == 0.0  # s6 在 top5 之外
        # p_high 交集大排前，p_low 挤出 top3 之外？仅 2 个候选，p_low 仍在 top3
        assert outcome.process_recall == 1.0

    def test_impact_seed_missing_propagates(self) -> None:
        outcome = evaluate_case(
            gold=_full_gold(),
            predicted_symbol_uids=["s1"],
            candidate_processes=[],
            predicted_edges=[],
            impact_result={"affected_uids": ["a"], "seed_in_graph": False},
            trace_results=[],
        )
        assert outcome.impact_precision == SEED_MISSING

    def test_all_gold_dims_empty_no_error_no_full_marks(self) -> None:
        outcome = evaluate_case(
            gold=_gold(),  # 全部 gold 维度为空
            predicted_symbol_uids=[],
            candidate_processes=[],
            predicted_edges=[],
            impact_result={},
            trace_results=[],
        )
        assert outcome.symbol_recall == NO_GOLD
        assert outcome.process_recall == NO_GOLD
        assert outcome.edge_recall == NO_GOLD
        assert outcome.edge_precision == NOT_APPLICABLE
        assert outcome.impact_precision == NOT_APPLICABLE
        assert outcome.trace_success_rate == NO_GOLD
        assert outcome.trace_node_not_in_graph_count == 0

    def test_error_blanks_metrics_but_keeps_dims(self) -> None:
        outcome = evaluate_case(
            gold=_full_gold(),
            predicted_symbol_uids=["s1"],
            candidate_processes=[],
            predicted_edges=[],
            impact_result={},
            trace_results=[],
            error="boom",
        )
        assert outcome.error == "boom"
        assert outcome.symbol_recall == ""
        assert outcome.impact_precision == ""
        assert outcome.language == "python"
        assert outcome.framework == "django"
        assert outcome.entry_type == "http_endpoint"

    def test_to_dict_contains_bucket_dims_and_timing(self) -> None:
        outcome = evaluate_case(
            gold=_full_gold(),
            predicted_symbol_uids=["s1", "s2"],
            candidate_processes=[{"process_key": "p1", "step_symbol_uids": ["s1"]}],
            predicted_edges=[{"caller_uid": "a", "callee_uid": "b"}],
            impact_result={"affected_uids": ["a"], "seed_in_graph": True},
            trace_results=[{"found": True, "path": ["a", "b"]}],
            cold_ms=1,
            warm_ms=2,
            tokens=3,
        )
        d = outcome.to_dict()
        for key in (
            "case_id",
            "split",
            "language",
            "framework",
            "entry_type",
            "protected",
            "symbol_recall",
            "process_recall",
            "edge_precision",
            "edge_recall",
            "impact_precision",
            "trace_success_rate",
            "trace_error_path_rate",
            "trace_node_not_in_graph_count",
            "cold_ms",
            "warm_ms",
            "tokens",
            "error",
        ):
            assert key in d
        # float 按精度取整；str 标记原样
        assert d["symbol_recall"] == 1.0
        assert isinstance(outcome, CaseOutcome)


def _outcome(
    case_id: str,
    language: str,
    framework: str,
    entry_type: str,
    *,
    protected: bool = False,
    symbol_recall: float | str = 1.0,
    process_recall: float | str = 1.0,
    edge_precision: float | str = 1.0,
    edge_recall: float | str = 1.0,
    impact_precision: float | str = 1.0,
    trace_success_rate: float | str = 1.0,
    trace_error_path_rate: float | str = 0.0,
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        split="dev",
        language=language,
        framework=framework,
        entry_type=entry_type,
        protected=protected,
        symbol_recall=symbol_recall,
        process_recall=process_recall,
        edge_precision=edge_precision,
        edge_recall=edge_recall,
        impact_precision=impact_precision,
        trace_success_rate=trace_success_rate,
        trace_error_path_rate=trace_error_path_rate,
    )


class TestBucketStatus:
    def test_ok_at_or_above_min(self) -> None:
        assert bucket_status(MIN_BUCKET_SAMPLES) == BUCKET_OK
        assert bucket_status(MIN_BUCKET_SAMPLES + 5) == BUCKET_OK

    def test_insufficient_below_min(self) -> None:
        assert bucket_status(0) == INSUFFICIENT_DATA
        assert bucket_status(MIN_BUCKET_SAMPLES - 1) == INSUFFICIENT_DATA

    def test_run_specific_minimum(self) -> None:
        assert bucket_status(2, min_samples=2) == BUCKET_OK
        assert bucket_status(2, min_samples=3) == INSUFFICIENT_DATA


class TestBucketMetrics:
    def test_groups_by_language_framework_entry(self) -> None:
        cases = [
            _outcome("c1", "python", "django", "http_endpoint", symbol_recall=1.0),
            _outcome("c2", "python", "django", "http_endpoint", symbol_recall=0.0),
            _outcome("c3", "go", "gin", "process_entry", symbol_recall=0.5),
        ]
        buckets = bucket_metrics(cases)
        keys = {(b["key"]["language"], b["key"]["framework"], b["key"]["entry_type"]) for b in buckets}
        assert ("python", "django", "http_endpoint") in keys
        assert ("go", "gin", "process_entry") in keys

    def test_macro_average_skips_markers(self) -> None:
        cases = [
            _outcome("c1", "python", "django", "http_endpoint", symbol_recall=1.0),
            _outcome("c2", "python", "django", "http_endpoint", symbol_recall=NO_GOLD),
            _outcome("c3", "python", "django", "http_endpoint", symbol_recall=0.0),
        ]
        buckets = bucket_metrics(cases)
        assert len(buckets) == 1
        b = buckets[0]
        assert b["n"] == 3
        assert b["status"] == BUCKET_OK
        # macro：仅对数值 case 平均 → (1.0 + 0.0) / 2
        assert b["metrics"]["symbol_recall"] == 0.5

    def test_sparse_bucket_marked_insufficient(self) -> None:
        cases = [_outcome("c1", "go", "gin", "process_entry")]
        buckets = bucket_metrics(cases)
        assert buckets[0]["status"] == INSUFFICIENT_DATA

    def test_has_protected_flag(self) -> None:
        cases = [
            _outcome("c1", "python", "django", "http_endpoint", protected=True),
            _outcome("c2", "python", "django", "http_endpoint"),
            _outcome("c3", "python", "django", "http_endpoint"),
        ]
        buckets = bucket_metrics(cases)
        assert buckets[0]["has_protected"] is True


class TestAggregateReport:
    def test_overall_excludes_insufficient_and_protected(self) -> None:
        cases = [
            # OK 非保护桶（python/django）：3 个数值 case
            _outcome("c1", "python", "django", "http_endpoint", symbol_recall=1.0),
            _outcome("c2", "python", "django", "http_endpoint", symbol_recall=0.5),
            _outcome("c3", "python", "django", "http_endpoint", symbol_recall=0.0),
            # 稀疏桶（go/gin）：仅 1 个，标 INSUFFICIENT_DATA，不进 overall
            _outcome("c4", "go", "gin", "process_entry", symbol_recall=1.0),
        ]
        report = aggregate_report(cases)
        # overall 只聚合 OK 桶的 3 个 case：(1.0+0.5+0.0)/3
        assert report["overall"]["symbol_recall"] == 0.5
        assert report["total_cases"] == 4
        assert len(report["insufficient_buckets"]) == 1
        assert report["insufficient_buckets"][0]["key"]["language"] == "go"

    def test_protected_bucket_listed_separately_not_in_overall(self) -> None:
        cases = [
            _outcome("c1", "python", "django", "http_endpoint", symbol_recall=1.0),
            _outcome("c2", "python", "django", "http_endpoint", symbol_recall=1.0),
            _outcome("c3", "python", "django", "http_endpoint", symbol_recall=1.0),
            # 受保护桶（ts/vue）：退化但不被 overall 抵消
            _outcome("c4", "typescript", "vue", "plain_symbol", protected=True, symbol_recall=0.0),
            _outcome("c5", "typescript", "vue", "plain_symbol", protected=True, symbol_recall=0.0),
            _outcome("c6", "typescript", "vue", "plain_symbol", protected=True, symbol_recall=0.0),
        ]
        report = aggregate_report(cases)
        # overall 只含 python/django 桶 → 1.0，不被 ts/vue 的 0.0 拉低
        assert report["overall"]["symbol_recall"] == 1.0
        protected = report["protected_buckets"]
        assert len(protected) == 1
        assert protected[0]["key"]["language"] == "typescript"
        assert protected[0]["metrics"]["symbol_recall"] == 0.0

    def test_empty_cases(self) -> None:
        report = aggregate_report([])
        assert report["total_cases"] == 0
        assert report["per_bucket"] == []


class TestBuildReport:
    def _report(self) -> dict:
        cases = [
            _outcome("c1", "python", "django", "http_endpoint", symbol_recall=1.0),
            _outcome("c2", "python", "django", "http_endpoint", symbol_recall=0.0),
            _outcome("c3", "python", "django", "http_endpoint", symbol_recall=0.5),
        ]
        identity = build_run_identity(
            repository="friday-ai",
            branch="main",
            commit_sha="abc123",
            index_key="abc123",
            gold_version="1",
        )
        return build_report(identity=identity, watermark="OK", split="dev", cases=cases)

    def test_report_shape_and_identity_echo(self) -> None:
        report = self._report()
        assert report["identity"]["repository"] == "friday-ai"
        assert report["identity"]["commit_sha"] == "abc123"
        assert report["watermark"] == "OK"
        assert report["split"] == "dev"
        for key in (
            "per_case",
            "per_bucket",
            "overall",
            "protected_buckets",
            "insufficient_buckets",
            "legend",
        ):
            assert key in report
        assert len(report["per_case"]) == 3

    def test_legend_explains_empty_markers(self) -> None:
        legend = self._report()["legend"]
        for marker in (NO_GOLD, NOT_APPLICABLE, SEED_MISSING, NODE_NOT_IN_GRAPH, INSUFFICIENT_DATA):
            assert marker in legend

    def test_report_has_no_regression_gate_fields(self) -> None:
        forbidden = {"tolerance", "threshold", "compare_to_baseline", "target_value"}

        def _walk(node: object) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    assert k not in forbidden
                    _walk(v)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(self._report())
