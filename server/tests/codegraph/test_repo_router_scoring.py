"""repo_router_scoring 纯函数打分核心的不变量与确定性性质测试。

Phase 105-01（legacy 三信号路径，用例保持不变）覆盖 ROUTING-RANKING §4：
- INV-R1：任意输入下每个候选 0 <= score <= 1（无 min(score, 1.0) 截断）。
- INV-R3：Σbreakdown == score 恒成立，含活跃度缺失触发权重重归一化的情形。

以及：乱序确定性（100 seed）、tie-break 先量化再按 repo_id、margin 规则边界、
LLM 调节只降不升穷举、废弃惩罚落在活跃度项内、repo_name 缺失容错。

Phase 106-01（六信号新路径，repo_meta 注入）新增覆盖：
- INV-R1/INV-R2/INV-R3/INV-R4 在六信号下重验（TestMultiSignalInvariants）。
- 活跃度真值表四行：连续衰减/枚举回退/皆无→不可用/废弃封顶跨来源
  （TestActivityDecay）。
- 关键程度同分带 tie-break（TestCriticalityTieBreak）。
- 尺寸偏置消除机制（§2.4 数值，TestSizeBiasMechanism）。
- 新路径乱序确定性 + legacy 路径逐字段守护（TestNewPathDeterminismAndLegacy）。

纯函数测试——零 Django DB / 零网络，机制级断言优先（锁性质不锁名次，
per ROUTING-RANKING §7.4）。
"""

from __future__ import annotations

import inspect
import json
import math
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import codegraph.services.repo_router_scoring as scoring_module
from codegraph.services.repo_router_scoring import (
    ACTIVITY_ENUM_MAP,
    DEFAULT_WEIGHT_CONFIG,
    DEPRECATED_ACTIVITY_CAP,
    PHASE105_WEIGHTS,
    S_TOP_SOURCE_DENSE,
    S_TOP_SOURCE_RRF,
    SIGNAL_ACTIVITY,
    SIGNAL_BREADTH,
    SIGNAL_DOMAIN,
    SIGNAL_STACK,
    SIGNAL_TEAM,
    SIGNAL_TEXT,
    WEIGHT_SET_VERSION,
    aggregate_and_score,
    apply_llm_adjustment,
    derive_confidence,
    resolve_s_top_source,
)

# RRF 融合分的真实量级（rank-1 双列表命中 ≈ 0.0328，单列表 ≈ 0.0164）
_RRF_BASE = 0.0164


def _make_hit(
    repo_id: str,
    score: float,
    node_id: str,
    facets: dict[str, Any] | None = None,
    *,
    repo_name: str | None = "auto",
) -> dict[str, Any]:
    """构造与 repo_index_tree.py 写入 payload 同形状的 node_hit。

    facets 以 JSON str 入 payload（真实索引写入即如此）。
    repo_name="auto" 时按 repo_id 派生；显式 None 时省略该键（容错测试用）。
    """
    payload: dict[str, Any] = {
        "repository_id": repo_id,
        "node_id": node_id,
        "node_path": f"能力/{repo_id}/{node_id}",
        "sub_project": "",
    }
    if repo_name == "auto":
        payload["repo_name"] = f"repo-{repo_id}"
    elif repo_name is not None:
        payload["repo_name"] = repo_name
    if facets is not None:
        payload["facets"] = json.dumps(facets, ensure_ascii=False)
    return {"id": node_id, "score": score, "payload": payload}


@pytest.fixture
def diverse_node_hits() -> list[dict[str, Any]]:
    """8+ 仓、分数悬殊、含疑似废弃仓与 facets 缺失仓的 node_hits。"""
    hits: list[dict[str, Any]] = []
    # r1：多命中活跃仓（6 个命中，广度饱和）
    for i in range(6):
        hits.append(
            _make_hit(
                "r1",
                _RRF_BASE * (1.0 - 0.05 * i),
                f"r1-n{i}",
                {"活跃度": "活跃开发", "关键程度": "核心"},
            )
        )
    # r2：单强命中小仓（维护中）
    hits.append(_make_hit("r2", _RRF_BASE * 0.98, "r2-n0", {"活跃度": "维护中"}))
    # r3：疑似废弃仓（两个命中）
    hits.append(_make_hit("r3", _RRF_BASE * 0.90, "r3-n0", {"活跃度": "疑似废弃"}))
    hits.append(_make_hit("r3", _RRF_BASE * 0.60, "r3-n1", {"活跃度": "疑似废弃"}))
    # r4：facets 缺失仓（活跃度信号不可用 → 重归一化）
    hits.append(_make_hit("r4", _RRF_BASE * 0.85, "r4-n0"))
    # r5：facets 有值但活跃度不在映射表（同样视为不可用）
    hits.append(_make_hit("r5", _RRF_BASE * 0.40, "r5-n0", {"活跃度": "未知状态"}))
    # r6：低频仓，分数很低
    hits.append(_make_hit("r6", _RRF_BASE * 0.05, "r6-n0", {"活跃度": "低频"}))
    # r7：中等分，3 命中
    for i in range(3):
        hits.append(_make_hit("r7", _RRF_BASE * (0.7 - 0.1 * i), f"r7-n{i}", {"活跃度": "维护中"}))
    # r8：facets 为坏 JSON —— 解析容错为空 dict（活跃度不可用）
    bad = _make_hit("r8", _RRF_BASE * 0.30, "r8-n0")
    bad["payload"]["facets"] = "{not-valid-json"
    hits.append(bad)
    # 空 repository_id 的 hit 应被跳过
    hits.append(_make_hit("", _RRF_BASE * 0.99, "orphan-n0"))
    return hits


class TestInvariants:
    def test_inv_r1_scores_within_unit_interval(self, diverse_node_hits):
        """INV-R1：任意候选 0 <= score <= 1，且信号值全部 ∈ [0,1]。"""
        candidates = aggregate_and_score(diverse_node_hits)
        assert len(candidates) == 8  # 空 rid 被跳过
        for c in candidates:
            assert 0.0 <= c.score <= 1.0, f"{c.repo_id} score={c.score}"
            for sig, contrib in c.breakdown.items():
                assert contrib >= 0.0, f"{c.repo_id}.{sig} 贡献为负"

    def test_inv_r3_breakdown_sums_to_score(self, diverse_node_hits):
        """INV-R3：Σbreakdown 恰等于 score；重归一化候选同样成立。"""
        candidates = aggregate_and_score(diverse_node_hits)
        renormalized = 0
        for c in candidates:
            assert abs(math.fsum(c.breakdown.values()) - c.score) < 1e-9
            if SIGNAL_ACTIVITY not in c.breakdown:
                renormalized += 1
        # r4（facets 缺失）/ r5（枚举外值）/ r8（坏 JSON）触发重归一化
        assert renormalized == 3

    def test_missing_activity_has_no_activity_key(self, diverse_node_hits):
        """活跃度缺失 → breakdown 无 activity 键（缺失≠补 0）。"""
        by_id = {c.repo_id: c for c in aggregate_and_score(diverse_node_hits)}
        assert SIGNAL_ACTIVITY not in by_id["r4"].breakdown
        assert SIGNAL_ACTIVITY not in by_id["r5"].breakdown
        assert set(by_id["r4"].breakdown) == {SIGNAL_TEXT, SIGNAL_BREADTH}
        # 有活跃度的仓三信号齐全
        assert set(by_id["r1"].breakdown) == {
            SIGNAL_TEXT,
            SIGNAL_BREADTH,
            SIGNAL_ACTIVITY,
        }


class TestDeterminism:
    def test_shuffle_invariance_100_seeds(self, diverse_node_hits):
        """乱序确定性：打乱输入 100 个 seed，输出逐字段相等（含 breakdown）。"""
        base = aggregate_and_score(diverse_node_hits)
        for seed in range(100):
            shuffled = random.Random(seed).sample(diverse_node_hits, len(diverse_node_hits))
            assert aggregate_and_score(shuffled) == base, f"seed={seed} 输出漂移"

    def test_tie_break_quantizes_then_sorts_by_repo_id(self):
        """数学等值但浮点表示差 1e-9 级的两仓：round(·,6) 吸收差异后按 repo_id 升序。"""
        # zzz 的原始分微高（1e-9 级），但 round 6 位后与 aaa 同分
        hits = [
            _make_hit("zzz", _RRF_BASE, "z-n0"),
            _make_hit("aaa", _RRF_BASE * (1.0 - 1e-9), "a-n0"),
        ]
        candidates = aggregate_and_score(hits)
        assert round(candidates[0].score, 6) == round(candidates[1].score, 6)
        assert [c.repo_id for c in candidates] == ["aaa", "zzz"]

    def test_empty_and_zero_score_inputs(self):
        """空输入 → 空列表；rrf_max <= 0 → 防除零，分数全 0。"""
        assert aggregate_and_score([]) == []
        zero_hits = [_make_hit("r1", 0.0, "n0"), _make_hit("r2", 0.0, "n1")]
        candidates = aggregate_and_score(zero_hits)
        assert all(c.score == 0.0 for c in candidates)
        assert [c.repo_id for c in candidates] == ["r1", "r2"]  # 同分按 repo_id


class TestMarginRule:
    @pytest.mark.parametrize(
        ("scores", "expected"),
        [
            ([0.55, 0.47], "high"),  # s1==θ_abs 且 margin==θ_margin（边界含等号）
            ([0.55, 0.4701], "medium"),  # margin 0.0799 < 0.08 → 降为 medium
            ([0.549, 0.30], "medium"),  # s1 < θ_abs，但 >= θ_med
            ([0.349], "low"),  # s1 < θ_med
            ([0.7], "high"),  # 单候选：margin = s1 = 0.7
            ([0.36, 0.36], "medium"),  # margin=0 → 非 high，s1 >= θ_med
            ([], "low"),  # 空列表
        ],
    )
    def test_margin_rule_boundaries(self, scores, expected):
        assert (
            derive_confidence(scores, theta_abs=0.55, theta_margin=0.08, theta_med=0.35) == expected
        )

    def test_margin_just_below_threshold_is_medium(self):
        """margin 0.079（差 0.001 不达标）→ medium 而非 high。"""
        # 用整数构造避免浮点减法边界歧义：0.6 - 0.521 = 0.079
        assert (
            derive_confidence([0.6, 0.521], theta_abs=0.55, theta_margin=0.08, theta_med=0.35)
            == "medium"
        )


class TestLlmAdjustment:
    @pytest.mark.parametrize(
        ("deterministic", "llm", "expected"),
        [
            # 穷举 3×3：只降不升（min 语义）
            ("low", "low", "low"),
            ("low", "medium", "low"),
            ("low", "high", "low"),
            ("medium", "low", "low"),
            ("medium", "medium", "medium"),
            ("medium", "high", "medium"),
            ("high", "low", "low"),
            ("high", "medium", "medium"),
            ("high", "high", "high"),
            # llm 缺失或非法 → 保持确定性结果
            ("low", None, "low"),
            ("medium", None, "medium"),
            ("high", None, "high"),
            ("high", "bogus", "high"),
        ],
    )
    def test_never_upgrades(self, deterministic, llm, expected):
        assert apply_llm_adjustment(deterministic, llm) == expected


class TestDeprecatedCap:
    def test_deprecated_penalty_confined_to_activity_signal(self, diverse_node_hits):
        """疑似废弃仓的惩罚完全落在活跃度项内（机制级断言）。"""
        by_id = {c.repo_id: c for c in aggregate_and_score(diverse_node_hits)}
        deprecated = by_id["r3"]
        # 三信号齐全 → 有效权重和为全权重和
        effective_w = math.fsum(PHASE105_WEIGHTS[s] for s in deprecated.breakdown)
        cap_contrib = PHASE105_WEIGHTS[SIGNAL_ACTIVITY] * DEPRECATED_ACTIVITY_CAP / effective_w
        assert deprecated.breakdown[SIGNAL_ACTIVITY] <= cap_contrib + 1e-12
        # 且活跃仓的活跃度贡献严格高于废弃仓（惩罚生效的方向性）
        assert by_id["r1"].breakdown[SIGNAL_ACTIVITY] > deprecated.breakdown[SIGNAL_ACTIVITY]

    def test_activity_enum_map_values_in_unit_interval(self):
        assert all(0.0 <= v <= 1.0 for v in ACTIVITY_ENUM_MAP.values())
        assert abs(math.fsum(PHASE105_WEIGHTS.values()) - 1.0) < 1e-12


class TestRepoNameFallback:
    def test_missing_repo_name_falls_back_to_repo_id(self):
        """带/不带 repo_name 的等值输入：score/breakdown/顺序逐字段相等。

        快照回放契约（供 105-07 复用）：replay 从最小字段集快照重建的 hit
        不含 repo_name，打分与排序必须不受影响。
        """
        facets = {"活跃度": "维护中"}
        named = [
            _make_hit("r1", _RRF_BASE, "n0", facets),
            _make_hit("r1", _RRF_BASE * 0.8, "n1", facets),
            _make_hit("r2", _RRF_BASE * 0.9, "n2", facets),
        ]
        bare = [
            _make_hit("r1", _RRF_BASE, "n0", facets, repo_name=None),
            _make_hit("r1", _RRF_BASE * 0.8, "n1", facets, repo_name=None),
            _make_hit("r2", _RRF_BASE * 0.9, "n2", facets, repo_name=None),
        ]
        a = aggregate_and_score(named)
        b = aggregate_and_score(bare)
        assert [c.repo_id for c in a] == [c.repo_id for c in b]
        assert [c.score for c in a] == [c.score for c in b]
        assert [c.breakdown for c in a] == [c.breakdown for c in b]
        for c in b:
            assert c.repo_name == c.repo_id  # 确定性回退
        for c in a:
            assert c.repo_name == f"repo-{c.repo_id}"


# ======================================================================
# Phase 106-01：六信号新路径（repo_meta 注入）的性质测试
# ======================================================================

# 固定时间锚点（活跃度衰减确定性——now 参数注入，绝不取系统时间）
_NOW = "2026-07-29T00:00:00+00:00"
_NOW_DT = datetime(2026, 7, 29, tzinfo=timezone.utc)

# 新路径默认权重/常数（唯一默认值来源，测试期望值据此复算）
_W6: dict[str, float] = DEFAULT_WEIGHT_CONFIG["weights"]
_C6: dict[str, Any] = DEFAULT_WEIGHT_CONFIG["constants"]


def _days_before(days: int) -> str:
    """距 _NOW 指定天数之前的 ISO 时间戳。"""
    return (_NOW_DT - timedelta(days=days)).isoformat()


def _make_meta(**overrides: Any) -> dict[str, Any]:
    """构造单仓 repo_meta 条目：默认全缺，kwargs 按需覆盖。

    facet 三信号用快捷键 domain/stack/team（float 匹配分）展开成
    ``facet_scores`` 契约形状；其余键（n_r/last_commit_at/dense_cos_max/
    criticality_value）原样透传。
    """
    meta: dict[str, Any] = {}
    facet_scores: dict[str, dict[str, Any]] = {}
    for key, value in overrides.items():
        if key in (SIGNAL_DOMAIN, SIGNAL_STACK, SIGNAL_TEAM):
            facet_scores[key] = {"score": value, "layer": "t1"}
        else:
            meta[key] = value
    if facet_scores:
        meta["facet_scores"] = facet_scores
    return meta


def _expected_breadth(s_hats: list[float], n_r: float | None, n_bar: float | None) -> float:
    """按 ROUTING-RANKING §2.3 三步字面复算 breadth 期望值。"""
    top = s_hats[0]
    n_eff = math.fsum((s / top) ** _C6["p"] for s in s_hats)
    if n_r is not None and n_bar is not None:
        denom = 1.0 - _C6["b"] + _C6["b"] * (n_r / n_bar)
    else:
        denom = 1.0
    return min(math.log1p(n_eff / denom) / math.log1p(_C6["n_cap"]), 1.0)


def _activity_from_breakdown(cand, available_weight: float) -> float:
    """从重归一化后的 breakdown 反解 activity 原始信号值 A。"""
    return cand.breakdown[SIGNAL_ACTIVITY] * available_weight / _W6[SIGNAL_ACTIVITY]


class TestMultiSignalInvariants:
    """INV-R1 ~ INV-R4 对六信号新路径成立（机制级断言）。"""

    def _diverse_meta_hits(self):
        """8 仓：cos 超界（>c_hi / <c_lo）、facet 全有/全缺、废弃仓等极端组合。"""
        hits: list[dict[str, Any]] = []
        meta: dict[str, dict[str, Any]] = {}
        # m1：cos 超上界 + facet 全有 + 近期 commit + 核心
        hits.append(_make_hit("m1", _RRF_BASE, "m1-n0", {"活跃度": "活跃开发"}))
        meta["m1"] = _make_meta(
            n_r=30,
            last_commit_at=_days_before(10),
            dense_cos_max=0.99,  # > c_hi=0.55 → clip 到 1.0
            domain=1.0,
            stack=1.0,
            team=1.0,
            criticality_value="核心",
        )
        # m2：cos 超下界（< c_lo=0.25 → clip 到 0.0）
        hits.append(_make_hit("m2", _RRF_BASE * 0.9, "m2-n0"))
        meta["m2"] = _make_meta(n_r=100, dense_cos_max=0.05)
        # m3：facet 全缺 + 无任何活跃度信息（退化为 text+breadth）
        hits.append(_make_hit("m3", _RRF_BASE * 0.8, "m3-n0"))
        meta["m3"] = _make_meta()
        # m4：疑似废弃仓（近期 commit 也被封顶）
        hits.append(_make_hit("m4", _RRF_BASE * 0.7, "m4-n0", {"活跃度": "疑似废弃"}))
        meta["m4"] = _make_meta(last_commit_at=_days_before(3), domain=0.6)
        # m5：多命中大仓
        for i in range(6):
            hits.append(_make_hit("m5", _RRF_BASE * (0.9 - 0.05 * i), f"m5-n{i}"))
        meta["m5"] = _make_meta(n_r=620, dense_cos_max=0.45, stack=0.8)
        # m6：facet score 类型非法（str）→ 信号不可用（trust boundary 容错）
        hits.append(_make_hit("m6", _RRF_BASE * 0.5, "m6-n0"))
        meta["m6"] = _make_meta()
        meta["m6"]["facet_scores"] = {"domain": {"score": "high", "layer": "t1"}}
        # m7：不在 repo_meta 里的仓（meta 整体缺失）
        hits.append(_make_hit("m7", _RRF_BASE * 0.4, "m7-n0"))
        # m8：last_commit_at 非法字符串 + 枚举回退
        hits.append(_make_hit("m8", _RRF_BASE * 0.3, "m8-n0", {"活跃度": "低频"}))
        meta["m8"] = _make_meta(last_commit_at="not-a-timestamp", team=0.5)
        return hits, meta

    def test_inv_r1_new_path_scores_within_unit_interval(self):
        """INV-R1：极端 meta 组合下所有候选 0 <= score <= 1，贡献非负。"""
        hits, meta = self._diverse_meta_hits()
        candidates = aggregate_and_score(hits, repo_meta=meta, constants={"n_bar": 60.0}, now=_NOW)
        assert len(candidates) == 8
        for c in candidates:
            assert 0.0 <= c.score <= 1.0, f"{c.repo_id} score={c.score}"
            for sig, contrib in c.breakdown.items():
                assert contrib >= 0.0, f"{c.repo_id}.{sig} 贡献为负"

    def test_inv_r1_no_score_truncation_in_source(self):
        """INV-R1：源码无 min(score, 1.0) 式截断（分数上界由构造保证）。"""
        source = inspect.getsource(scoring_module)
        assert re.search(r"min\(\s*(c\.)?score", source) is None

    def test_inv_r2_text_dominance_metadata_cannot_flip_leader(self):
        """INV-R2（可证明推论落测试）：S_text 落后首位 0.5 以上的仓，
        任意元数据组合（全给 1.0 + 核心）都无法升至第一。"""
        hits = [
            _make_hit("leader", _RRF_BASE, "l-n0"),
            _make_hit("trail", _RRF_BASE, "t-n0"),
        ]
        # leader：S_top=1.0（cos 超 c_hi），零元数据；trail：S_top=0.0
        # （cos 低于 c_lo），元数据全满 —— S_text 差 = 0.75 >= 0.5
        meta = {
            "leader": _make_meta(dense_cos_max=0.9),
            "trail": _make_meta(
                dense_cos_max=0.20,
                last_commit_at=_days_before(1),
                domain=1.0,
                stack=1.0,
                team=1.0,
                criticality_value="核心",
            ),
        }
        candidates = aggregate_and_score(hits, repo_meta=meta, now=_NOW)
        assert candidates[0].repo_id == "leader"
        assert candidates[0].score > candidates[1].score

    def test_inv_r3_breakdown_sums_to_score_across_meta_combinations(self):
        """INV-R3：任意 repo_meta 组合下 |Σbreakdown - score| < 1e-9，
        且 breakdown 无 criticality 键。"""
        hits, meta = self._diverse_meta_hits()
        candidates = aggregate_and_score(hits, repo_meta=meta, constants={"n_bar": 60.0}, now=_NOW)
        for c in candidates:
            assert abs(math.fsum(c.breakdown.values()) - c.score) < 1e-9
            assert "criticality" not in c.breakdown

    def test_inv_r3_text_breadth_two_keys_sum_equals_wtext_stext(self):
        """text+breadth 两键之和 == w_text·S_text/D（λ 合成的扁平表示）。"""
        hits = [_make_hit("r1", _RRF_BASE, "n0")]
        meta = {"r1": _make_meta(n_r=60, dense_cos_max=0.40, domain=1.0)}
        cand = aggregate_and_score(hits, repo_meta=meta, constants={"n_bar": 60.0}, now=_NOW)[0]
        s_top = (0.40 - _C6["s_top_c_lo"]) / (_C6["s_top_c_hi"] - _C6["s_top_c_lo"])  # = 0.5
        breadth = _expected_breadth([1.0], 60.0, 60.0)
        s_text = (1.0 - _C6["lam"]) * s_top + _C6["lam"] * breadth
        d = _W6[SIGNAL_TEXT] + _W6[SIGNAL_DOMAIN]
        expected = _W6[SIGNAL_TEXT] * s_text / d
        two_keys = cand.breakdown[SIGNAL_TEXT] + cand.breakdown[SIGNAL_BREADTH]
        assert abs(two_keys - expected) < 1e-9

    def test_inv_r4_zeroing_one_weight_preserves_relative_ratios(self):
        """INV-R4：关掉任一信号（权重置 0）后，其余信号贡献两两比值不变。"""
        hits = [
            _make_hit("r1", _RRF_BASE, "n0"),
            _make_hit("r1", _RRF_BASE * 0.8, "n1"),
        ]
        meta = {
            "r1": _make_meta(
                n_r=30,
                last_commit_at=_days_before(60),
                dense_cos_max=0.50,
                domain=0.9,
                stack=0.7,
                team=0.4,
            )
        }
        base = aggregate_and_score(hits, repo_meta=meta, constants={"n_bar": 60.0}, now=_NOW)[0]
        zeroed_weights = dict(_W6)
        zeroed_weights[SIGNAL_TEAM] = 0.0
        zeroed = aggregate_and_score(
            hits,
            repo_meta=meta,
            weights=zeroed_weights,
            constants={"n_bar": 60.0},
            now=_NOW,
        )[0]
        remaining = [SIGNAL_TEXT, SIGNAL_BREADTH, SIGNAL_ACTIVITY, SIGNAL_DOMAIN, SIGNAL_STACK]
        for i, sig_a in enumerate(remaining):
            for sig_b in remaining[i + 1 :]:
                ratio_base = base.breakdown[sig_a] / base.breakdown[sig_b]
                ratio_zeroed = zeroed.breakdown[sig_a] / zeroed.breakdown[sig_b]
                assert abs(ratio_base - ratio_zeroed) < 1e-9, (sig_a, sig_b)

    def test_missing_facets_degenerate_to_text_breadth(self):
        """facet 全缺 + 无活跃度信息 → 退化为 text+breadth 两键（纯文本分数）。"""
        hits = [_make_hit("r1", _RRF_BASE, "n0")]
        cand = aggregate_and_score(hits, repo_meta={"r1": _make_meta()})[0]
        assert set(cand.breakdown) == {SIGNAL_TEXT, SIGNAL_BREADTH}
        assert cand.criticality is None

    def test_dense_cos_clip_bounds_and_rrf_fallback(self):
        """S_top：cos 超上界 clip 1.0、超下界 clip 0.0；缺失回退桶内 max s_hat。"""
        w_text = _W6[SIGNAL_TEXT]
        lam = _C6["lam"]
        # cos=0.99 > c_hi → S_top=1.0（仅 text 可用，D=w_text）
        hi = aggregate_and_score(
            [_make_hit("r1", _RRF_BASE, "n0")],
            repo_meta={"r1": _make_meta(dense_cos_max=0.99)},
        )[0]
        assert abs(hi.breakdown[SIGNAL_TEXT] - (1.0 - lam) * 1.0) < 1e-9
        # cos=0.05 < c_lo → S_top=0.0（缺失不打死是回退语义，超界打 0 是校准语义）
        lo = aggregate_and_score(
            [_make_hit("r1", _RRF_BASE, "n0")],
            repo_meta={"r1": _make_meta(dense_cos_max=0.05)},
        )[0]
        assert lo.breakdown[SIGNAL_TEXT] == 0.0
        # cos 缺失 → 回退 RRF s_hat（Pitfall 6：dense top-50 未覆盖的仓不打死）
        hits = [
            _make_hit("top", _RRF_BASE, "t-n0"),
            _make_hit("fb", _RRF_BASE * 0.5, "f-n0"),
        ]
        by_id = {
            c.repo_id: c
            for c in aggregate_and_score(hits, repo_meta={"top": _make_meta(), "fb": _make_meta()})
        }
        assert abs(by_id["fb"].breakdown[SIGNAL_TEXT] - (1.0 - lam) * 0.5) < 1e-9
        assert w_text > 0  # 权重表健全性（防手滑改零）


class TestSTopSingleScalePerQuery:
    """BL-01：S_top 口径在一次查询内唯一（校准余弦 / RRF 二选一，绝不混用）。

    混用的病理：校准余弦把 cos=0.30 压到 0.167，而 RRF query-local 比值的
    rank-1 恒为 1.0——「没被 dense 覆盖」恰恰意味着 dense 相似度低，混用会
    让这类仓反拿最高 S_top（结构性偏袒换形状重演，与 ROUTE-03 相反）。
    """

    def _mixed_coverage(self):
        """有 dense 证据的强仓（cos=0.30）vs 无 dense 证据的次强仓。"""
        hits = [
            _make_hit("with_cos", _RRF_BASE, "w-n0"),
            _make_hit("no_cos", _RRF_BASE * 0.95, "n-n0"),
        ]
        meta = {
            "with_cos": _make_meta(dense_cos_max=0.30),
            "no_cos": _make_meta(),  # dense top-K 未覆盖
        }
        return hits, meta

    def test_source_is_rrf_when_any_repo_lacks_cosine(self):
        """任一仓缺 dense_cos_max → 整条查询统一走 RRF 口径。"""
        _, meta = self._mixed_coverage()
        assert resolve_s_top_source(meta.keys(), meta) == S_TOP_SOURCE_RRF

    def test_source_is_dense_only_when_all_repos_covered(self):
        """全仓都有 dense_cos_max → 才启用校准余弦口径。"""
        meta = {
            "a": _make_meta(dense_cos_max=0.30),
            "b": _make_meta(dense_cos_max=0.28),
        }
        assert resolve_s_top_source(meta.keys(), meta) == S_TOP_SOURCE_DENSE

    def test_missing_cosine_repo_never_outranks_covered_repo_by_fallback(self):
        """回归复现：覆盖不全时缺 dense 的次强仓不得因「缺失红利」反超。

        修复前 with_cos 走校准余弦 (0.30-0.25)/0.30 = 0.167、no_cos 走 RRF
        0.95 —— S_top 差 5.7 倍，text 分项直接把弱仓抬到首位。
        """
        hits, meta = self._mixed_coverage()
        ranked = aggregate_and_score(hits, repo_meta=meta, now=_NOW)
        assert [c.repo_id for c in ranked] == ["with_cos", "no_cos"]
        # 同一标尺下 text 分项按 RRF s_hat 单调（1.0 vs 0.95）
        assert ranked[0].breakdown[SIGNAL_TEXT] > ranked[1].breakdown[SIGNAL_TEXT]

    def test_all_candidates_share_one_source_value(self):
        """口径值随候选回传且全候选恒等（trace/快照记录同一口径）。"""
        hits, meta = self._mixed_coverage()
        ranked = aggregate_and_score(hits, repo_meta=meta, now=_NOW)
        assert {c.s_top_source for c in ranked} == {S_TOP_SOURCE_RRF}

        covered_meta = {
            "with_cos": _make_meta(dense_cos_max=0.30),
            "no_cos": _make_meta(dense_cos_max=0.28),
        }
        covered = aggregate_and_score(hits, repo_meta=covered_meta, now=_NOW)
        assert {c.s_top_source for c in covered} == {S_TOP_SOURCE_DENSE}

    def test_s_top_source_not_in_breakdown(self):
        """口径是旁路 informational 字段——不进 breakdown（INV-R3 不受影响）。"""
        hits, meta = self._mixed_coverage()
        for cand in aggregate_and_score(hits, repo_meta=meta, now=_NOW):
            assert "s_top_source" not in cand.breakdown
            assert math.fsum(cand.breakdown.values()) == cand.score

    def test_empty_or_non_dict_meta_falls_back_to_rrf(self):
        """空仓集 / repo_meta 非 dict（trust boundary）→ RRF 口径，不抛。"""
        assert resolve_s_top_source([], {}) == S_TOP_SOURCE_RRF
        assert resolve_s_top_source(["a"], None) == S_TOP_SOURCE_RRF
        assert resolve_s_top_source(["a"], {"a": "not-a-dict"}) == S_TOP_SOURCE_RRF


class TestActivityDecay:
    """活跃度真值表（Pitfall 4 四行）+ 指数衰减单调性。"""

    def _single_repo_activity(self, **meta_kwargs) -> float | None:
        """单仓单命中打分，反解 activity 原始信号值；不可用返回 None。"""
        facets = meta_kwargs.pop("facets", None)
        hits = [_make_hit("r1", _RRF_BASE, "n0", facets)]
        cand = aggregate_and_score(hits, repo_meta={"r1": _make_meta(**meta_kwargs)}, now=_NOW)[0]
        if SIGNAL_ACTIVITY not in cand.breakdown:
            return None
        available_w = _W6[SIGNAL_TEXT] + _W6[SIGNAL_ACTIVITY]
        return _activity_from_breakdown(cand, available_w)

    def test_decay_strictly_decreasing_30_180_365_730(self):
        """真值表第 1 行（连续衰减）：30/180/365/730 天贡献严格递减。"""
        values = [
            self._single_repo_activity(last_commit_at=_days_before(d)) for d in (30, 180, 365, 730)
        ]
        assert all(v is not None for v in values)
        for earlier, later in zip(values, values[1:]):
            assert earlier > later, values

    def test_decay_180d_matches_formula_literal(self):
        """180 天时 A == 0.5^((180-14)/180)（公式字面复算）。"""
        actual = self._single_repo_activity(last_commit_at=_days_before(180))
        expected = 0.5 ** ((180.0 - _C6["offset_days"]) / _C6["half_life_days"])
        assert actual is not None
        assert abs(actual - expected) < 1e-9

    def test_floor_applies_at_extreme_age(self):
        """floor=0.05 生效：衰减值低于 floor 的极老仓被托底。

        注：0.5^((730-14)/180) ≈ 0.063 仍高于 floor，floor 实际在
        约 792 天后才绑定——用 1500 天构造 floor 生效路径。
        """
        actual = self._single_repo_activity(last_commit_at=_days_before(1500))
        assert actual is not None
        assert abs(actual - _C6["activity_floor"]) < 1e-9
        # 730 天尚未触底（严格大于 floor），衰减曲线连续性佐证
        at_730 = self._single_repo_activity(last_commit_at=_days_before(730))
        assert at_730 is not None and at_730 > _C6["activity_floor"]

    def test_recent_commit_within_offset_is_full_score(self):
        """offset=14d 平顶：14 天内的 commit 衰减 delta=0 → A=1.0。"""
        actual = self._single_repo_activity(last_commit_at=_days_before(5))
        assert actual is not None
        assert abs(actual - 1.0) < 1e-9

    def test_enum_fallback_without_timestamp(self):
        """真值表第 2 行（枚举回退）：无 last_commit_at → ACTIVITY_ENUM_MAP。"""
        actual = self._single_repo_activity(facets={"活跃度": "维护中"})
        assert actual is not None
        assert abs(actual - ACTIVITY_ENUM_MAP["维护中"]) < 1e-9

    def test_unavailable_when_no_timestamp_and_no_enum(self):
        """真值表第 3 行（皆无 → 不可用）：走重归一化，无 activity 键。"""
        assert self._single_repo_activity() is None

    def test_deprecated_cap_with_recent_commit(self):
        """真值表第 4 行（封顶跨来源）：疑似废弃 + 近期 commit → A <= 0.10。"""
        actual = self._single_repo_activity(
            last_commit_at=_days_before(3), facets={"活跃度": "疑似废弃"}
        )
        assert actual is not None
        assert actual <= _C6["deprecated_cap"] + 1e-9

    def test_deprecated_cap_with_enum_source(self):
        """真值表第 4 行（枚举来源同样封顶）：疑似废弃枚举值 → A <= 0.10。"""
        actual = self._single_repo_activity(facets={"活跃度": "疑似废弃"})
        assert actual is not None
        assert actual <= _C6["deprecated_cap"] + 1e-9

    def test_now_none_activity_unavailable_no_exception(self):
        """now=None 且无枚举 facet → activity 不可用走重归一化，不抛异常。"""
        hits = [_make_hit("r1", _RRF_BASE, "n0")]
        cand = aggregate_and_score(
            hits,
            repo_meta={"r1": _make_meta(last_commit_at=_days_before(30))},
            now=None,
        )[0]
        assert SIGNAL_ACTIVITY not in cand.breakdown
        assert set(cand.breakdown) == {SIGNAL_TEXT, SIGNAL_BREADTH}

    def test_invalid_timestamp_falls_back_to_enum(self):
        """last_commit_at 解析失败（T-106-01 容错）→ 回退枚举映射，不抛。"""
        actual = self._single_repo_activity(
            last_commit_at="not-a-timestamp", facets={"活跃度": "低频"}
        )
        assert actual is not None
        assert abs(actual - ACTIVITY_ENUM_MAP["低频"]) < 1e-9

    def test_naive_timestamp_treated_as_utc(self):
        """naive 时间戳按 UTC 处理（now 与 last_commit_at 同规则）。"""
        aware = self._single_repo_activity(last_commit_at=_days_before(90))
        naive = self._single_repo_activity(
            last_commit_at=(_NOW_DT - timedelta(days=90)).replace(tzinfo=None).isoformat()
        )
        assert aware is not None and naive is not None
        assert abs(aware - naive) < 1e-9


class TestCriticalityTieBreak:
    """关键程度：不进加性和，仅同分带（crit_band 量化桶）内决序。"""

    def _pair_hits(self, id_a: str, id_b: str) -> list[dict[str, Any]]:
        return [
            _make_hit(id_a, _RRF_BASE, f"{id_a}-n0"),
            _make_hit(id_b, _RRF_BASE, f"{id_b}-n0"),
        ]

    def test_same_band_core_ranks_before_edge(self):
        """同分带（分数相同）：核心排前——即使 repo_id 序相反。"""
        # aaa=边缘、zzz=核心：无 tie-break 时 repo_id 升序会把 aaa 排前
        meta = {
            "aaa": _make_meta(dense_cos_max=0.40, criticality_value="边缘"),
            "zzz": _make_meta(dense_cos_max=0.40, criticality_value="核心"),
        }
        candidates = aggregate_and_score(self._pair_hits("aaa", "zzz"), repo_meta=meta)
        assert [c.repo_id for c in candidates] == ["zzz", "aaa"]
        assert round(candidates[0].score, 6) == round(candidates[1].score, 6)

    def test_cross_band_score_decides_despite_criticality(self):
        """分差跨带（>= 一个 crit_band 桶）：分数决序，criticality 不翻盘。"""
        meta = {
            "strong": _make_meta(dense_cos_max=0.90, criticality_value="边缘"),
            "weak": _make_meta(dense_cos_max=0.25, criticality_value="核心"),
        }
        candidates = aggregate_and_score(self._pair_hits("strong", "weak"), repo_meta=meta)
        assert [c.repo_id for c in candidates] == ["strong", "weak"]
        assert candidates[0].score - candidates[1].score >= _C6["crit_band"]

    def test_missing_criticality_is_neutral_between_anchors(self):
        """criticality 缺失按 0.4 居中：重要(0.7) > 缺失(0.4) > 边缘(0.15)。"""
        meta = {
            "aaa": _make_meta(dense_cos_max=0.40, criticality_value="边缘"),
            "bbb": _make_meta(dense_cos_max=0.40),  # 缺失 → 0.4 居中
            "ccc": _make_meta(dense_cos_max=0.40, criticality_value="重要"),
        }
        hits = [_make_hit(rid, _RRF_BASE, f"{rid}-n0") for rid in ("aaa", "bbb", "ccc")]
        candidates = aggregate_and_score(hits, repo_meta=meta)
        assert [c.repo_id for c in candidates] == ["ccc", "bbb", "aaa"]

    def test_criticality_anchor_values_exposed_on_candidate(self):
        """四档锚点值经旁路字段透出（含人工 pin 的「一般」，Pitfall 1）。"""
        anchors = DEFAULT_WEIGHT_CONFIG["criticality_anchors"]
        for value, expected in anchors.items():
            cand = aggregate_and_score(
                [_make_hit("r1", _RRF_BASE, "n0")],
                repo_meta={"r1": _make_meta(criticality_value=value)},
            )[0]
            assert cand.criticality == expected, value
            # 绝不进加性和：breakdown 无 criticality 键
            assert "criticality" not in cand.breakdown

    def test_unknown_criticality_enum_is_none(self):
        """枚举外值 → criticality=None（不可用，不奖不罚）。"""
        cand = aggregate_and_score(
            [_make_hit("r1", _RRF_BASE, "n0")],
            repo_meta={"r1": _make_meta(criticality_value="不存在的档位")},
        )[0]
        assert cand.criticality is None


class TestSizeBiasMechanism:
    """尺寸偏置消除（ROUTE-03）：§2.4 数值代入的机制级断言。"""

    def test_breadth_reverse_tilt_study_app_vs_onion_learning(self):
        """§2.4：study-app（N_r=620 命中 6）breadth < onion-learning
        （N_r=30 命中 1），n_bar=60——106-08 golden 机制断言的纯函数前置。"""
        hits: list[dict[str, Any]] = []
        for i in range(6):
            hits.append(_make_hit("study-app", _RRF_BASE, f"sa-n{i}"))
        hits.append(_make_hit("onion-learning", _RRF_BASE, "ol-n0"))
        meta = {
            "study-app": _make_meta(n_r=620),
            "onion-learning": _make_meta(n_r=30),
        }
        by_id = {
            c.repo_id: c
            for c in aggregate_and_score(hits, repo_meta=meta, constants={"n_bar": 60.0})
        }
        big = by_id["study-app"].breakdown[SIGNAL_BREADTH]
        small = by_id["onion-learning"].breakdown[SIGNAL_BREADTH]
        assert big < small, (big, small)
        # 数值锚定（等分命中 → n_eff=6 / n_eff=1，denom=6.6 / 0.7）
        d = _W6[SIGNAL_TEXT]  # 两仓均只有 text 可用，D 相同可比
        lam = _C6["lam"]
        assert abs(big - _W6[SIGNAL_TEXT] * lam * _expected_breadth([1.0] * 6, 620, 60) / d) < 1e-9
        assert abs(small - _W6[SIGNAL_TEXT] * lam * _expected_breadth([1.0], 30, 60) / d) < 1e-9

    def test_breadth_defined_when_n_bar_missing(self):
        """n_bar 缺失（None）→ denom_size=1.0 降级路径，breadth 仍有定义。"""
        hits = [
            _make_hit("r1", _RRF_BASE, "n0"),
            _make_hit("r1", _RRF_BASE, "n1"),
        ]
        cand = aggregate_and_score(hits, repo_meta={"r1": _make_meta(n_r=620)})[0]
        expected = _expected_breadth([1.0, 1.0], None, None)
        lam = _C6["lam"]
        assert abs(cand.breakdown[SIGNAL_BREADTH] - lam * expected) < 1e-9  # D=w_text → w_text 约掉

    def test_soft_count_discounts_weak_hits(self):
        """软计数 p=2：弱命中不算满分——分数为桶首一半的节点只贡献 0.25。"""
        equal_hits = [
            _make_hit("eq", _RRF_BASE, "eq-n0"),
            _make_hit("eq", _RRF_BASE, "eq-n1"),
        ]
        weak_hits = [
            _make_hit("wk", _RRF_BASE, "wk-n0"),
            _make_hit("wk", _RRF_BASE * 0.5, "wk-n1"),
        ]
        meta = {"eq": _make_meta(), "wk": _make_meta()}
        eq = aggregate_and_score(equal_hits, repo_meta={"eq": meta["eq"]})[0]
        wk = aggregate_and_score(weak_hits, repo_meta={"wk": meta["wk"]})[0]
        assert eq.breakdown[SIGNAL_BREADTH] > wk.breakdown[SIGNAL_BREADTH]


class TestNewPathDeterminismAndLegacy:
    """新路径确定性 + legacy 路径（repo_meta=None）零破坏守护。"""

    def _full_meta_inputs(self):
        hits: list[dict[str, Any]] = []
        meta: dict[str, dict[str, Any]] = {}
        specs = [
            ("ra", 1.0, "核心", 90),
            ("rb", 0.9, "边缘", 30),
            ("rc", 0.88, None, 400),
            ("rd", 0.5, "重要", 800),
        ]
        for rid, factor, crit, age in specs:
            for i in range(3):
                hits.append(_make_hit(rid, _RRF_BASE * factor * (1 - 0.1 * i), f"{rid}-n{i}"))
            kwargs: dict[str, Any] = {
                "n_r": 30 + len(rid) * 10,
                "last_commit_at": _days_before(age),
                "dense_cos_max": 0.3 + factor * 0.2,
                "domain": factor * 0.9,
                "stack": 0.5,
                "team": 0.3,
            }
            if crit is not None:
                kwargs["criticality_value"] = crit
            meta[rid] = _make_meta(**kwargs)
        return hits, meta

    def test_new_path_shuffle_invariance_100_seeds(self):
        """新路径（完整 repo_meta）乱序 100 seed：输出逐字段相等（含 criticality）。"""
        hits, meta = self._full_meta_inputs()
        base = aggregate_and_score(hits, repo_meta=meta, constants={"n_bar": 60.0}, now=_NOW)
        for seed in range(100):
            shuffled = random.Random(seed).sample(hits, len(hits))
            result = aggregate_and_score(
                shuffled, repo_meta=meta, constants={"n_bar": 60.0}, now=_NOW
            )
            assert result == base, f"seed={seed} 输出漂移"

    def test_legacy_path_matches_phase105_field_by_field(self):
        """repo_meta=None → Phase 105 三信号公式逐字段复算相等（零破坏守护）。"""
        hits = [
            _make_hit("r1", _RRF_BASE, "n0", {"活跃度": "维护中"}),
            _make_hit("r1", _RRF_BASE * 0.8, "n1", {"活跃度": "维护中"}),
        ]
        cand = aggregate_and_score(hits)[0]
        # 手工复算：text=1.0、breadth=min(1,5)/5=0.2、activity=0.6，权重 0.7/0.2/0.1
        expected_breakdown = {
            SIGNAL_TEXT: 0.70 * 1.0,
            SIGNAL_BREADTH: 0.20 * 0.2,
            SIGNAL_ACTIVITY: 0.10 * 0.6,
        }
        assert set(cand.breakdown) == set(expected_breakdown)
        for sig, expected in expected_breakdown.items():
            assert abs(cand.breakdown[sig] - expected) < 1e-9, sig
        assert abs(cand.score - math.fsum(expected_breakdown.values())) < 1e-9
        assert cand.criticality is None  # legacy 路径旁路字段恒为 None

    def test_legacy_default_equals_explicit_phase105_weights(self, diverse_node_hits):
        """legacy 默认权重 == 显式传 PHASE105_WEIGHTS（默认值来源未被改动）。"""
        assert aggregate_and_score(diverse_node_hits) == aggregate_and_score(
            diverse_node_hits, weights=PHASE105_WEIGHTS
        )

    def test_default_weight_config_shape(self):
        """DEFAULT_WEIGHT_CONFIG 契约：版本、五信号权重、常数键齐全。"""
        # 版本字面绑定只在 golden 门禁一处（bump 必须与 baseline 重建同提交）；
        # 此处只校验形状与单一来源一致性，避免版本字面量散落多个文件。
        assert DEFAULT_WEIGHT_CONFIG["weight_set_version"] == WEIGHT_SET_VERSION
        assert DEFAULT_WEIGHT_CONFIG["weight_set_version"].startswith("phase106-")
        assert set(_W6) == {
            SIGNAL_TEXT,
            SIGNAL_DOMAIN,
            SIGNAL_ACTIVITY,
            SIGNAL_STACK,
            SIGNAL_TEAM,
        }
        # 元数据权重和 <= 全权重和的一半（INV-R2 的静态前提）
        meta_sum = math.fsum(_W6[s] for s in (SIGNAL_DOMAIN, SIGNAL_STACK, SIGNAL_TEAM))
        assert meta_sum <= 0.5 * math.fsum(_W6.values())
        for key in (
            "p",
            "b",
            "n_cap",
            "lam",
            "n_bar",
            "half_life_days",
            "offset_days",
            "activity_floor",
            "deprecated_cap",
            "s_top_c_lo",
            "s_top_c_hi",
            "t2_c_lo",
            "t2_c_hi",
            "crit_band",
        ):
            assert key in _C6, key
        assert DEFAULT_WEIGHT_CONFIG["criticality_anchors"] == {
            "核心": 1.0,
            "重要": 0.7,
            "一般": 0.4,
            "边缘": 0.15,
        }

    def test_invalid_constants_fall_back_to_defaults(self):
        """T-106-02：非法常数（crit_band<=0 / n_cap<=0 / 类型错误）按默认处理。"""
        hits = [_make_hit("r1", _RRF_BASE, "n0")]
        meta = {"r1": _make_meta(dense_cos_max=0.40, n_r=60)}
        sane = aggregate_and_score(hits, repo_meta=meta, constants={"n_bar": 60.0}, now=_NOW)
        hostile = aggregate_and_score(
            hits,
            repo_meta=meta,
            constants={
                "n_bar": 60.0,
                "crit_band": -1.0,
                "n_cap": 0.0,
                "half_life_days": "abc",
                "lam": 5.0,
                "unknown_key": 42,
            },
            now=_NOW,
        )
        assert hostile == sane  # 非法项全部回退默认 → 结果一致
