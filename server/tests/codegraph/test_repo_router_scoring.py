"""repo_router_scoring 纯函数打分核心的不变量与确定性性质测试（Phase 105-01）。

覆盖 ROUTING-RANKING §4 不变量表：
- INV-R1：任意输入下每个候选 0 <= score <= 1（无 min(score, 1.0) 截断）。
- INV-R3：Σbreakdown == score 恒成立，含活跃度缺失触发权重重归一化的情形。

以及：乱序确定性（100 seed）、tie-break 先量化再按 repo_id、margin 规则边界、
LLM 调节只降不升穷举、废弃惩罚落在活跃度项内、repo_name 缺失容错。

纯函数测试——零 Django DB / 零网络，机制级断言优先（锁性质不锁名次）。
"""

from __future__ import annotations

import json
import math
import random
from typing import Any

import pytest

from codegraph.services.repo_router_scoring import (
    ACTIVITY_ENUM_MAP,
    DEPRECATED_ACTIVITY_CAP,
    PHASE105_WEIGHTS,
    SIGNAL_ACTIVITY,
    SIGNAL_BREADTH,
    SIGNAL_TEXT,
    aggregate_and_score,
    apply_llm_adjustment,
    derive_confidence,
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
        hits.append(
            _make_hit("r7", _RRF_BASE * (0.7 - 0.1 * i), f"r7-n{i}", {"活跃度": "维护中"})
        )
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
            shuffled = random.Random(seed).sample(
                diverse_node_hits, len(diverse_node_hits)
            )
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
            derive_confidence(
                scores, theta_abs=0.55, theta_margin=0.08, theta_med=0.35
            )
            == expected
        )

    def test_margin_just_below_threshold_is_medium(self):
        """margin 0.079（差 0.001 不达标）→ medium 而非 high。"""
        # 用整数构造避免浮点减法边界歧义：0.6 - 0.521 = 0.079
        assert (
            derive_confidence(
                [0.6, 0.521], theta_abs=0.55, theta_margin=0.08, theta_med=0.35
            )
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
        effective_w = math.fsum(
            PHASE105_WEIGHTS[s] for s in deprecated.breakdown
        )
        cap_contrib = (
            PHASE105_WEIGHTS[SIGNAL_ACTIVITY] * DEPRECATED_ACTIVITY_CAP / effective_w
        )
        assert deprecated.breakdown[SIGNAL_ACTIVITY] <= cap_contrib + 1e-12
        # 且活跃仓的活跃度贡献严格高于废弃仓（惩罚生效的方向性）
        assert (
            by_id["r1"].breakdown[SIGNAL_ACTIVITY]
            > deprecated.breakdown[SIGNAL_ACTIVITY]
        )

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
