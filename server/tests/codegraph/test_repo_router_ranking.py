"""仓库路由分组/重排纯函数单测（Phase 107-01，ROUTE-01 / ROUTE-02 / RELY-05）。

覆盖 `codegraph.services.repo_router_ranking` 六个纯函数：
- `annotate_groups`：分组标注（含「无项目上下文全部 global」降级路径）；
- `decide_block_order`：delta 迟滞置顶（阈值上下不同向 + 幂等 + 长度契约）；
- `clamp_llm_permutation`：rank-swap 预算后置条件（**含「LLM 只返回 Stage 0 子集」
  的常态**——base rank 取子集内相对位次，见模块 docstring）；
- `blend_ranked_scores`：凸组合（α=0 / N==1 防除零）；
- `classify_degrade_reason`：6 值受控闭集映射；
- `clamp_ranking_params`：非法参数 clamp 且绝不抛。

零 DB / 零网络 / 零 Django settings 依赖——被测模块本身是纯函数（另有静态守护
测试断言它零 Django import，见 `test_module_has_no_django_import`）。
"""

from __future__ import annotations

import itertools
import math
import re
from pathlib import Path

import pytest

from codegraph.services.repo_router_ranking import (
    CROSS_GROUP_NOTE,
    DEGRADE_REASONS,
    GROUP_GLOBAL,
    GROUP_IN_PROJECT,
    TRUST_NEEDS_CONFIRMATION,
    TRUST_TRUSTED,
    annotate_groups,
    blend_ranked_scores,
    clamp_llm_permutation,
    clamp_ranking_params,
    classify_degrade_reason,
    decide_block_order,
    is_retryable_upstream_failure,
)

DELTA = 0.15
K = 3


# ---------------------------------------------------------------------------
# annotate_groups（ROUTE-01 / ROUTE-02）
# ---------------------------------------------------------------------------


def test_annotate_groups_without_project_context_is_all_global() -> None:
    """无项目上下文（MCP / REST 入口）→ 全部 global 且不抛。"""
    result = annotate_groups(["a", "b"], project_repo_ids=None)
    assert result == {
        "a": (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION),
        "b": (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION),
    }


def test_annotate_groups_splits_by_project_membership() -> None:
    """有项目上下文 → 关联仓 in_project/trusted，其余 global/needs_confirmation。"""
    result = annotate_groups(["a", "b"], project_repo_ids=frozenset({"a"}))
    assert result["a"] == (GROUP_IN_PROJECT, TRUST_TRUSTED)
    assert result["b"] == (GROUP_GLOBAL, TRUST_NEEDS_CONFIRMATION)


def test_annotate_groups_returns_no_float() -> None:
    """机制守护（SC-2 后半句）：组别绝不进分数——返回值里不存在任何数值。"""
    result = annotate_groups(["a", "b", "c"], project_repo_ids=frozenset({"b"}))
    assert all(isinstance(v, str) for pair in result.values() for v in pair)


def test_annotate_groups_empty_input() -> None:
    result = annotate_groups([], project_repo_ids=frozenset({"a"}))
    assert result == {}


def test_cross_group_note_is_non_empty_constant() -> None:
    """跨组标注文案是后端留痕常量（前端不渲染后端自由文本，T-107-06）。"""
    assert isinstance(CROSS_GROUP_NOTE, str)
    assert CROSS_GROUP_NOTE.strip()


# ---------------------------------------------------------------------------
# decide_block_order（ROUTE-01 迟滞 + 长度契约 + 幂等）
# ---------------------------------------------------------------------------


def test_block_order_without_project_context_is_single_global() -> None:
    """无项目上下文 → 长度 1 的 ['global']，前端据此跳过分组呈现。"""
    assert decide_block_order(None, 0.9, delta=DELTA, has_project_context=False) == [GROUP_GLOBAL]


def test_block_order_below_threshold_keeps_in_project_on_top() -> None:
    """差值恰在阈值下 → 不翻转（迟滞的下侧）。"""
    in_project_top = 0.4
    global_top = in_project_top + DELTA - 1e-9
    assert global_top - in_project_top < DELTA
    assert decide_block_order(
        in_project_top, global_top, delta=DELTA, has_project_context=True
    ) == [GROUP_IN_PROJECT, GROUP_GLOBAL]


def test_block_order_at_threshold_promotes_global() -> None:
    """差值达到阈值 → 全局组置顶（`>= delta`，不是 `> 0`）。"""
    in_project_top = 0.4
    global_top = in_project_top + DELTA
    assert global_top - in_project_top >= DELTA
    assert decide_block_order(
        in_project_top, global_top, delta=DELTA, has_project_context=True
    ) == [GROUP_GLOBAL, GROUP_IN_PROJECT]


def test_block_order_with_project_context_is_always_length_two() -> None:
    """有项目上下文时恒长度 2（即使某组/两组皆空）——UI-SPEC covered 11 的后端契约。"""
    cases = [
        (0.5, 0.6),
        (None, 0.6),
        (0.5, None),
        (None, None),
    ]
    for in_project_top, global_top in cases:
        order = decide_block_order(
            in_project_top, global_top, delta=DELTA, has_project_context=True
        )
        assert len(order) == 2, (in_project_top, global_top, order)
        assert set(order) == {GROUP_IN_PROJECT, GROUP_GLOBAL}


def test_block_order_empty_group_falls_back_to_the_other() -> None:
    """某组为空 → 另一组置顶。"""
    assert decide_block_order(None, 0.6, delta=DELTA, has_project_context=True) == [
        GROUP_GLOBAL,
        GROUP_IN_PROJECT,
    ]
    assert decide_block_order(0.6, None, delta=DELTA, has_project_context=True) == [
        GROUP_IN_PROJECT,
        GROUP_GLOBAL,
    ]


def test_block_order_is_idempotent() -> None:
    """同一输入重复调用结果恒等（ROUTING-RANKING §6 幂等清单）。"""
    args = (0.42, 0.61)
    results = [decide_block_order(*args, delta=DELTA, has_project_context=True) for _ in range(3)]
    assert results[0] == results[1] == results[2]


# ---------------------------------------------------------------------------
# clamp_llm_permutation（RELY-05 rank-swap 预算）
# ---------------------------------------------------------------------------


def _base_order(llm_order: list[str], stage0_order: list[str]) -> list[str]:
    """被 LLM 返回子集内的 Stage 0 相对次序（与被测函数的 base 语义一致）。"""
    returned = set(llm_order)
    return [rid for rid in stage0_order if rid in returned]


def _assert_budget_postcondition(
    order: list[str], llm_order: list[str], stage0_order: list[str], *, k: int
) -> None:
    base = _base_order(llm_order, stage0_order)
    for idx, rid in enumerate(order):
        assert abs(idx - base.index(rid)) <= k, (order, base, rid)


def test_clamp_identity_permutation_is_unchanged() -> None:
    stage0 = [f"r{i}" for i in range(1, 7)]
    order, violations = clamp_llm_permutation(list(stage0), stage0, k=K)
    assert order == stage0
    assert violations == 0


def test_clamp_drops_hallucinated_repo_ids() -> None:
    """LLM 编造的 repo_id 不进结果（也不进 base 子集）。"""
    stage0 = ["r1", "r2", "r3"]
    order, _ = clamp_llm_permutation(["r2", "ghost", "r1"], stage0, k=K)
    assert order == ["r2", "r1"]
    assert "ghost" not in order


def test_clamp_deduplicates_repeated_repo_ids() -> None:
    stage0 = ["r1", "r2", "r3"]
    order, _ = clamp_llm_permutation(["r2", "r2", "r1"], stage0, k=K)
    assert order == ["r2", "r1"]


def test_clamp_llm_returning_only_tail_subset_keeps_subset() -> None:
    """子集常态（BLOCKER 修复的核心用例）：LLM 只返回 8 元窗口的末三位。

    base rank 必须按「被返回子集」内的相对位次算——若拿全量 stage0 下标去减，
    位移恒 > k，修复循环无法收敛并整体回退全量窗口，等于把 LLM 重排完全丢弃。
    """
    stage0 = [f"r{i}" for i in range(1, 9)]
    llm_order = ["r8", "r7", "r6"]
    order, violations = clamp_llm_permutation(llm_order, stage0, k=K)
    assert len(order) == 3, order
    assert set(order) == {"r6", "r7", "r8"}
    assert violations == 0
    _assert_budget_postcondition(order, llm_order, stage0, k=K)


def test_clamp_out_of_budget_move_is_clipped() -> None:
    """越界仍被裁剪：r8 从相对第 7 位提到第 0 位，违规被记录且位移被压回预算内。"""
    stage0 = [f"r{i}" for i in range(1, 9)]
    llm_order = ["r8", "r1", "r2", "r3", "r4", "r5", "r6", "r7"]
    order, violations = clamp_llm_permutation(llm_order, stage0, k=K)
    assert violations >= 1
    assert order.index("r8") >= 7 - K
    _assert_budget_postcondition(order, llm_order, stage0, k=K)


def test_clamp_empty_inputs() -> None:
    assert clamp_llm_permutation([], ["r1"], k=K) == ([], 0)
    assert clamp_llm_permutation(["r1"], [], k=K) == ([], 0)


def test_clamp_zero_k_pins_back_to_stage0_relative_order() -> None:
    """k=0 → 只允许保持子集内的 Stage 0 相对次序。"""
    stage0 = ["r1", "r2", "r3"]
    order, violations = clamp_llm_permutation(["r3", "r1"], stage0, k=0)
    assert order == ["r1", "r3"]
    assert violations >= 1


def test_clamp_postcondition_holds_for_all_subsets_and_permutations() -> None:
    """穷举「6 元窗口的全部非空子集 × 该子集全排列」（1956 例）。

    等长全排列只是 `m == 6` 那一层——只跑等长排列结构上抓不到子集缺陷。
    逐例断言：(a) 后置条件恒成立；(b) 返回元素集合恒 == 输入子集（不因回退
    而膨胀回全量窗口）；(c) 函数不抛。
    """
    stage0 = [f"r{i}" for i in range(1, 7)]
    checked = 0
    for m in range(1, len(stage0) + 1):
        for subset in itertools.combinations(stage0, m):
            for perm in itertools.permutations(subset):
                llm_order = list(perm)
                order, violations = clamp_llm_permutation(llm_order, stage0, k=K)
                assert set(order) == set(subset), (llm_order, order)
                assert len(order) == m, (llm_order, order)
                assert violations >= 0
                _assert_budget_postcondition(order, llm_order, stage0, k=K)
                checked += 1
    assert checked == 1956, checked


# ---------------------------------------------------------------------------
# blend_ranked_scores（RELY-05 凸组合）
# ---------------------------------------------------------------------------


def test_blend_with_alpha_zero_is_identity() -> None:
    """α=0（Stage 1 降级）→ 逐键等于 Stage 0 分数。"""
    stage0 = {"a": 0.5, "b": 0.9}
    assert blend_ranked_scores(stage0, ["b", "a"], alpha=0.0) == stage0


def test_blend_with_single_candidate_does_not_divide_by_zero() -> None:
    """N==1 无重排空间 → 恒等返回（分母 N-1 为 0 必须短路）。"""
    stage0 = {"a": 0.5}
    assert blend_ranked_scores(stage0, ["a"], alpha=0.35) == stage0


def test_blend_convex_combination_values() -> None:
    """S_ranked = (1-α)·S_final + α·S_llm，S_llm = 1 - idx/(N-1)。"""
    stage0 = {"a": 0.5, "b": 0.9}
    out = blend_ranked_scores(stage0, ["a", "b"], alpha=0.35)
    assert math.isclose(out["a"], 0.65 * 0.5 + 0.35 * 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(out["b"], 0.65 * 0.9 + 0.35 * 0.0, rel_tol=0, abs_tol=1e-12)


def test_blend_skips_ids_absent_from_stage0_scores() -> None:
    stage0 = {"a": 0.5, "b": 0.9}
    out = blend_ranked_scores(stage0, ["a", "ghost", "b"], alpha=0.35)
    assert set(out) == {"a", "b"}


def test_blend_does_not_mutate_input() -> None:
    stage0 = {"a": 0.5, "b": 0.9}
    snapshot = dict(stage0)
    blend_ranked_scores(stage0, ["a", "b"], alpha=0.35)
    assert stage0 == snapshot


def test_blend_ignores_unknown_ids_in_denominator() -> None:
    """IN-03：不在 stage0_scores 里的 id 先过滤再算 N —— 否则有效候选的 S_llm 被压低。

    ["a", "ghost", "b"] 里 ghost 无对应候选。修复前 n=3 且 b 的 idx=2 →
    S_llm(b) = 1 - 2/2 = 0；过滤后 n=2、idx=1 → S_llm(b) 同为 0，但 a 之外的中间项
    （见下方三有效项对照）会明显不同。这里用「与等价的纯净输入完全一致」来锁定。
    """
    stage0 = {"a": 0.9, "b": 0.5, "c": 0.3}
    with_noise = blend_ranked_scores(
        stage0, ["a", "ghost-1", "b", "ghost-2", "c"], alpha=0.35
    )
    clean = blend_ranked_scores(stage0, ["a", "b", "c"], alpha=0.35)
    assert with_noise == clean


# ---------------------------------------------------------------------------
# classify_degrade_reason（RELY-03，T-107-02）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("skipped_reason", "expected"),
    [
        ("provider_missing", "provider_missing"),
        ("no_model_configured", "provider_missing"),
        ("unparsable_llm_output", "unparsable"),
        ("no_valid_candidates_in_llm_output", "unparsable"),
        ("v1_fallback", "no_node_index"),
        ("no_stage0_candidates", ""),
        ("use_llm_false", ""),
        ("something_new", "unknown"),
    ],
)
def test_classify_degrade_reason_maps_skipped_reasons(skipped_reason: str, expected: str) -> None:
    assert classify_degrade_reason(skipped_reason) == expected


@pytest.mark.parametrize(
    ("exc_type_name", "expected"),
    [
        ("TimeoutError", "timeout"),
        ("APIConnectionError", "upstream_error"),
        ("APIStatusError", "upstream_error"),
        ("ConnectError", "upstream_error"),
        ("BadRequestError", "upstream_error"),
        ("ValueError", "unknown"),
    ],
)
def test_classify_degrade_reason_maps_exception_type_names(
    exc_type_name: str, expected: str
) -> None:
    assert classify_degrade_reason("", exc_type_name=exc_type_name) == expected


def test_classify_degrade_reason_return_is_in_controlled_closed_set() -> None:
    """返回值恒 ∈ 6 值闭集 ∪ {''}（基数受控，可直接做指标维度）。"""
    allowed = DEGRADE_REASONS | {""}
    probes = [
        "",
        "provider_missing",
        "use_llm_false",
        "whatever",
        "stage1_failed:RuntimeError",
    ]
    for reason in probes:
        for exc_name in (None, "TimeoutError", "Mystery"):
            assert classify_degrade_reason(reason, exc_type_name=exc_name) in allowed


# ---------------------------------------------------------------------------
# MJ-01：状态码优先的分类与重试判定
#
# 只按类名子串匹配对 SDK 具体异常类不成立——`APIStatusError` 是基类，生产抛的永远是
# `RateLimitError` / `InternalServerError` / `OverloadedError` 这类子类，名字里不含
# "APIStatus"。修复前：429/500/529 全落 `unknown`（既不重试，用户还只看到「未知原因」），
# 而 `BadRequestError` 反被判可重试（白烧一次上游调用）。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc_type_name", "status_code", "expected_reason", "expected_retry"),
    [
        # 上游抖动的主要形态：分类为 upstream_error 且必须重试
        ("RateLimitError", 429, "upstream_error", True),
        ("InternalServerError", 500, "upstream_error", True),
        ("APIStatusError", 502, "upstream_error", True),
        ("APIStatusError", 503, "upstream_error", True),
        ("OverloadedError", 529, "upstream_error", True),
        # 超时语义（408 请求超时 / 504 网关超时）与纯超时异常
        ("APITimeoutError", None, "timeout", True),
        ("APIStatusError", 408, "timeout", True),
        ("APIStatusError", 504, "timeout", True),
        # 连接类无状态码 → 类名兜底，可重试
        ("APIConnectionError", None, "upstream_error", True),
        # 确定性 4xx：分类仍是「网关错误」，但**不重试**
        ("BadRequestError", 400, "upstream_error", False),
        ("AuthenticationError", 401, "upstream_error", False),
        ("PermissionDeniedError", 403, "upstream_error", False),
        ("NotFoundError", 404, "upstream_error", False),
        ("UnprocessableEntityError", 422, "upstream_error", False),
        # 无状态码的确定性 4xx 也不重试（类名兜底表）
        ("BadRequestError", None, "upstream_error", False),
        # 解析/编程错误：未知原因且不重试
        ("ValueError", None, "unknown", False),
        ("JSONDecodeError", None, "unknown", False),
    ],
)
def test_upstream_failure_classification_and_retry(
    exc_type_name: str, status_code: int | None, expected_reason: str, expected_retry: bool
) -> None:
    assert (
        classify_degrade_reason("", exc_type_name=exc_type_name, status_code=status_code)
        == expected_reason
    )
    assert (
        is_retryable_upstream_failure(exc_type_name=exc_type_name, status_code=status_code)
        is expected_retry
    )


@pytest.mark.parametrize("status_code", ["", None, "abc", 0, 999, float("nan")])
def test_non_numeric_status_code_falls_back_to_type_name(status_code: object) -> None:
    """非法状态码不得让判定抛，也不得夺走类名兜底（fail-safe 纪律）。"""
    assert (
        classify_degrade_reason("", exc_type_name="APITimeoutError", status_code=status_code)
        == "timeout"
    )
    assert is_retryable_upstream_failure(
        exc_type_name="APITimeoutError", status_code=status_code
    )


def test_skipped_reason_map_still_wins_over_status_code() -> None:
    """内部 skipped_reason 的优先级最高（provider_missing 不因带状态码变成网关错误）。"""
    assert (
        classify_degrade_reason("provider_missing", exc_type_name="RateLimitError", status_code=429)
        == "provider_missing"
    )


def test_retry_judgement_is_false_without_any_signal() -> None:
    assert is_retryable_upstream_failure() is False


def test_degrade_reasons_is_six_valued_frozenset() -> None:
    assert DEGRADE_REASONS == frozenset(
        {
            "timeout",
            "upstream_error",
            "provider_missing",
            "unparsable",
            "no_node_index",
            "unknown",
        }
    )


# ---------------------------------------------------------------------------
# clamp_ranking_params（T-107-05 fail-safe）
# ---------------------------------------------------------------------------


def test_clamp_params_clips_out_of_range_values() -> None:
    assert clamp_ranking_params(delta=-1.0, alpha=2.0, k=-5) == (0.0, 1.0, 0)


def test_clamp_params_passes_legal_values_through() -> None:
    assert clamp_ranking_params(delta=0.15, alpha=0.35, k=3) == (0.15, 0.35, 3)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_clamp_params_falls_back_on_non_finite(bad: float) -> None:
    delta, alpha, k = clamp_ranking_params(delta=bad, alpha=bad, k=3)
    assert 0.0 <= delta <= 1.0
    assert 0.0 <= alpha <= 1.0
    assert k == 3


def test_clamp_params_never_raises_on_garbage() -> None:
    """非数值输入也不得抛（fail-safe：参数永不反噬路由）。"""
    delta, alpha, k = clamp_ranking_params(delta="x", alpha=None, k="y")  # type: ignore[arg-type]
    assert 0.0 <= delta <= 1.0
    assert 0.0 <= alpha <= 1.0
    assert k >= 0


# ---------------------------------------------------------------------------
# 静态守护：零 Django import（纯函数纪律，便于进 golden 与单测）
# ---------------------------------------------------------------------------


def test_module_has_no_django_import() -> None:
    """按行首正则守护——docstring 里提及 Django 不算违规。"""
    module_path = (
        Path(__file__).resolve().parents[2] / "codegraph" / "services" / "repo_router_ranking.py"
    )
    pattern = re.compile(r"^\s*(import|from)\s+django")
    offenders = [
        line for line in module_path.read_text(encoding="utf-8").splitlines() if pattern.match(line)
    ]
    assert offenders == [], offenders
