"""去固定角色化回归：无 role_map 时直接 shortlist→place；确认门 shortlist 兜底。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.process_runtime.blueprint_confirm_gate import BlueprintConfirmGateAdapter
from services.process_runtime.placement_units import PlacementUnit
from services.process_runtime.place_units import place_units

# 旧关键词不得作为本回归路径的必要条件
_LEGACY_KEYWORDS = ("视频AI答疑", "试卷库", "错题本", "练习复用")


def _fake_router_result(repo_ids: list[str], scores: list[float] | None = None):
    scores = scores or [0.9 - 0.1 * i for i in range(len(repo_ids))]
    candidates = [
        SimpleNamespace(
            repo_id=rid,
            repo_name=f"name-{rid}",
            score=scores[i],
            confidence="high",
            reasoning="hit",
            matched_node_paths=[],
        )
        for i, rid in enumerate(repo_ids)
    ]
    return SimpleNamespace(
        candidates=candidates,
        router_version="v2",
        auto_selected=True,
        degrade_reason="",
    )


@pytest.mark.asyncio
async def test_place_units_nonempty_primary_without_legacy_charter_keywords():
    """章程域不含旧关键词的 shortlist → place_units 仍产出非空 primary。"""
    shortlist = ["repo-billing", "repo-ops", "repo-gateway"]
    team = list(shortlist)
    unit = PlacementUnit(
        unit_id="u-billing",
        feature_ids=["fp-invoice"],
        module_names=["结算"],
        query_text="结算对账与开票入口改造",
        reuse_host_hints=[],
    )
    blob = " ".join(
        [
            unit.query_text,
            " ".join(unit.module_names),
            "domains=finance billing ops",
        ]
    )
    for kw in _LEGACY_KEYWORDS:
        assert kw not in blob

    router = MagicMock()
    router.route = AsyncMock(
        return_value=_fake_router_result(
            ["repo-billing", "repo-ops"], scores=[0.92, 0.55]
        )
    )
    result = await place_units(
        [unit],
        shortlist_ids=shortlist,
        team_core=team,
        router=router,
        use_llm=True,
    )
    assert result.placements, "expected non-empty placements"
    primary = result.placements[0].primary_repo
    assert primary, "primary must be non-empty without role_map"
    assert primary in set(shortlist)
    assert set(result.hard_scope) == set(shortlist)


@pytest.mark.asyncio
async def test_abuild_snapshot_falls_back_to_shortlist_when_candidates_empty():
    """routing.candidates=[] 但 shortlist 有仓时，确认门快照非空。"""
    gate = BlueprintConfirmGateAdapter(fitness_loader=AsyncMock(return_value={}))
    session = SimpleNamespace(
        id="s-direct-place",
        stage_state={
            "routing": {
                "candidates": [],
                "router_version": "v2",
                "shortlist": [
                    {
                        "repository_id": "repo-alpha",
                        "repository_name": "alpha",
                        "score": 0.81,
                    },
                    {
                        "repository_id": "repo-beta",
                        "repository_name": "beta",
                        "score": 0.55,
                    },
                ],
            }
        },
        initiated_by_user_id="u1",
    )
    snapshot = await gate._abuild_snapshot(session)
    assert snapshot, "shortlist fallback must yield non-empty snapshot"
    ids = {str(e.get("repository_id") or "") for e in snapshot}
    assert "repo-alpha" in ids
    assert "repo-beta" in ids
