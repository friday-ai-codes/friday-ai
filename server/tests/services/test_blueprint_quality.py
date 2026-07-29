"""blueprint_quality 指标纯函数测试（Phase 111-04 Task 1，GATE-02）。

覆盖：引用覆盖率精确比值与边界（全引用 1.0 / 剥一条 findings 引用的分子递减 /
三类条目全空回 1.0 / 非 dict 输入防御）、目标仓命中率四象限（全中 / 半中 /
expected 空 / role 全 indirect）、DB 统计接口占位返回 None。
"""

from __future__ import annotations

import pytest

from services.process_runtime.blueprint_quality import (
    ai_rejection_rate,
    citation_coverage,
    clarification_rounds,
    human_edit_volume,
    target_repo_hit_rate,
)
from tests.helpers.blueprint_samples import make_blueprint


def _fully_cited_blueprint() -> dict:
    """三类条目全引用样例：工厂样例的 indirect 仓 rationale 无 citations，此处补齐。"""
    blueprint = make_blueprint()
    blueprint["repo_associations"][2]["rationale"]["citations"] = ["cit_knowledge"]
    return blueprint


# ---- citation_coverage ----


def test_citation_coverage_fully_cited_is_one() -> None:
    assert citation_coverage(_fully_cited_blueprint()) == 1.0


def test_citation_coverage_factory_sample_counts_uncited_indirect_rationale() -> None:
    """工厂原样：indirect 仓 rationale 无 citations → 6 条目命中 5。"""
    assert citation_coverage(make_blueprint()) == pytest.approx(5 / 6)


def test_citation_coverage_drops_exactly_when_one_finding_uncited() -> None:
    blueprint = _fully_cited_blueprint()
    blueprint["current_state_analysis"][0]["findings"][0]["citations"] = []
    # 条目总数 6 = findings 2 + repo_associations 3 + affected_features 1
    assert citation_coverage(blueprint) == pytest.approx(5 / 6)


def test_citation_coverage_empty_categories_returns_one() -> None:
    blueprint = make_blueprint(
        current_state_analysis=[],
        repo_associations=[],
        impact_analysis={"business_impact": [], "affected_features": []},
    )
    assert citation_coverage(blueprint) == 1.0


def test_citation_coverage_non_dict_input_never_raises() -> None:
    assert citation_coverage(None) == 1.0  # type: ignore[arg-type]
    assert citation_coverage("坏输入") == 1.0  # type: ignore[arg-type]


# ---- target_repo_hit_rate ----


def test_target_repo_hit_rate_full_hit() -> None:
    # 工厂样例 direct 仓：onion-practice + study-app
    assert target_repo_hit_rate(make_blueprint(), ["onion-practice", "study-app"]) == 1.0


def test_target_repo_hit_rate_half_hit() -> None:
    assert target_repo_hit_rate(make_blueprint(), ["onion-practice", "不存在的仓"]) == 0.5


def test_target_repo_hit_rate_empty_expected_returns_one() -> None:
    assert target_repo_hit_rate(make_blueprint(), []) == 1.0


def test_target_repo_hit_rate_all_indirect_is_zero() -> None:
    blueprint = make_blueprint()
    for assoc in blueprint["repo_associations"]:
        assoc["role"] = "indirect"
    assert target_repo_hit_rate(blueprint, ["onion-practice"]) == 0.0


def test_target_repo_hit_rate_non_dict_blueprint_never_raises() -> None:
    assert target_repo_hit_rate(None, ["onion-practice"]) == 0.0  # type: ignore[arg-type]


# ---- DB 统计接口占位（数据由 112–114 填充） ----


def test_db_stat_placeholders_return_none() -> None:
    assert ai_rejection_rate("artifact-0001") is None
    assert human_edit_volume("artifact-0001") is None
    assert clarification_rounds("artifact-0001") is None
