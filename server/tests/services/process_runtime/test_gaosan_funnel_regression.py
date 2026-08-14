"""Phase 132 INT-02 — 合成 Learning-tools 漏斗路径 D2 回归。

Eval path = Learning-tools 合成宇宙 + funnel（role_map / place_units）；
参照 quick 260809/260811 仅作语料/失败模式，非 pass 标准（D-07）。
验收不得以裸 RepoRouterV2.route（无 repository_ids）为唯一决策（D-04）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.process_runtime.gaosan_eval import score_placement_bar
from services.process_runtime.place_units import place_units
from services.process_runtime.role_map import PLACEMENT_DEFAULTS
from tests.services.process_runtime.fixtures import gaosan_learning_tools as fx
from tests.services.process_runtime.fixtures.gaosan_learning_tools import (
    ROLE_EXPECTATIONS,
    TEAM_CORE_IDS,
    build_funnel_units,
    make_scoped_v2_router,
    team_payload,
)


@pytest.mark.asyncio
async def test_gaosan_funnel_passes_d2_placement_bar():
    """漏斗 → placements → score_placement_bar.passed；out_of_team primary=0。"""
    team = team_payload()
    role_map = fx.role_map_payload()
    units = build_funnel_units()
    router, call_log = make_scoped_v2_router()

    # shortlist 仅 team_core（诱饵在 membership 宇宙内，不得进 hard_scope primary）
    shortlist_ids = list(TEAM_CORE_IDS)

    result = await place_units(
        units,
        shortlist_ids=shortlist_ids,
        role_map=role_map,
        placement_defaults={
            **dict(PLACEMENT_DEFAULTS),
            **(role_map.get("placement_defaults") or {}),
        },
        team_core=list(TEAM_CORE_IDS),
        router=router,
        use_llm=False,
    )

    placements = [
        {
            "unit_id": p.unit_id,
            "primary_repo": p.primary_repo,
            "hard_scope": list(p.hard_scope),
        }
        for p in result.placements
    ]
    bar = score_placement_bar(placements, team["membership"])
    assert bar["passed"] is True, bar
    assert bar["missing_baselines"] == []
    assert bar["out_of_team_primary_count"] == 0

    # D-04：凡 V2 调用必带非空 repository_ids ⊆ team/shortlist 宇宙
    assert call_log, "expected V2 route calls via place_units"
    allowed = set(TEAM_CORE_IDS) | set(shortlist_ids)
    for call in call_log:
        ids = call.get("repository_ids")
        assert ids, "bare V2 (empty repository_ids) forbidden as eval path"
        assert set(ids) <= allowed


@pytest.mark.asyncio
async def test_gaosan_funnel_four_roles_have_primary_coverage():
    """附加：四角色各有 primary（与四基线映射一致）。"""
    role_map = fx.role_map_payload()
    units = build_funnel_units()
    router, _ = make_scoped_v2_router()
    result = await place_units(
        units,
        shortlist_ids=list(TEAM_CORE_IDS),
        role_map=role_map,
        placement_defaults=dict(PLACEMENT_DEFAULTS),
        team_core=list(TEAM_CORE_IDS),
        router=router,
    )
    primaries = {p.primary_repo for p in result.placements if p.primary_repo}
    for role, expected in ROLE_EXPECTATIONS.items():
        assert expected in primaries, f"role {role} expected primary {expected} missing"


@pytest.mark.live_space
@pytest.mark.skip(reason="活 Learning-tools Space 可选；默认 CI skip（D-07；参照 260809 Space）")
def test_gaosan_live_space_placeholder():
    """可选 live：project/Space id 见 .planning/quick/260809-repo-route-eval/SUMMARY.md。"""
    pytest.skip("live_space not configured")
