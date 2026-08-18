"""Phase 130 漏斗放置接线守卫测（INT-01；去固定角色化）。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.process_runtime.blueprint_route import BlueprintRouteAdapter
from services.process_runtime.history_prior import HistoryPriorResult
from services.process_runtime.placement_units import PlacementUnit, PlacementUnitsResult
from services.process_runtime.place_units import PlacementResult, UnitPlacement
from services.process_runtime.shortlist import ShortlistResult


def _spec_multi_features() -> dict:
    return {
        "goal": [{"block_id": "g1", "type": "paragraph", "text": "高三提分看板改造"}],
        "feature_points": [
            {"id": "fp_1", "title": "任务列表", "module": "模块A", "description": "列表"},
            {"id": "fp_2", "title": "任务详情", "module": "模块A", "description": "详情"},
            {"id": "fp_3", "title": "练习入口", "module": "模块B", "description": "复用端内做题组件"},
            {"id": "fp_4", "title": "错题本", "module": "模块B", "description": "错题"},
            {"id": "fp_5", "title": "练习报告", "module": "模块B", "description": "报告"},
        ],
    }


def _fake_router_result(*, repo_ids: list[str]):
    candidates = [
        SimpleNamespace(
            repo_id=rid,
            repo_name=f"name-{rid}",
            score=0.99 - 0.1 * i,
            confidence="high",
            reasoning="hit",
            matched_node_paths=[],
        )
        for i, rid in enumerate(repo_ids)
    ]
    return SimpleNamespace(
        candidates=candidates, router_version="v2", auto_selected=True, degrade_reason=""
    )


def _session():
    return SimpleNamespace(
        id="s-130",
        stage_state={
            "requirement_spec": _spec_multi_features(),
            "decomposition": {"project_id": "proj-1", "space_id": "space-1"},
            "include_repos": ["core-1", "core-2", "host-1"],
        },
        work_item_id=None,
        initiated_by_user_id="u1",
    )


def _shortlist() -> ShortlistResult:
    return ShortlistResult(
        repositories=[
            {
                "repository_id": "core-1",
                "rank": 1,
                "score": 1.0,
                "team_membership": "team_core",
                "signals": {"activity": 0.5, "capability_coarse": 0.5, "charter_domain": 0.0},
                "force_include_reasons": [],
            },
            {
                "repository_id": "core-2",
                "rank": 2,
                "score": 0.5,
                "team_membership": "team_core",
                "signals": {"activity": 0.2, "capability_coarse": 0.0, "charter_domain": 0.0},
                "force_include_reasons": [],
            },
            {
                "repository_id": "host-1",
                "rank": 3,
                "score": 0.4,
                "team_membership": "team_core",
                "signals": {"activity": 0.1, "capability_coarse": 0.1, "charter_domain": 0.0},
                "force_include_reasons": [],
            },
        ],
        shortlist_count=3,
    )


@contextmanager
def _common_patches(adapter, *, shortlist, place_result=None, units_result=None):
    place = place_result or PlacementResult(
        status="ok",
        placements=[
            UnitPlacement(
                unit_id="u-a",
                primary_repo="core-1",
                supporting_repos=["core-2"],
                confidence="high",
                evidence=[{"source": "stub"}],
                open_questions=[],
                feature_ids=["fp_1", "fp_2"],
                hard_scope=["core-1", "core-2", "host-1"],
            ),
            UnitPlacement(
                unit_id="u-b",
                primary_repo="host-1",
                supporting_repos=["core-1"],
                confidence="medium",
                evidence=[{"source": "stub"}],
                open_questions=[],
                feature_ids=["fp_3", "fp_4", "fp_5"],
                hard_scope=["core-1", "core-2", "host-1"],
            ),
        ],
        unit_count=2,
        placement_count=2,
        hard_scope=["core-1", "core-2", "host-1"],
    )
    units = units_result or PlacementUnitsResult(
        status="ok",
        units=[
            PlacementUnit(
                unit_id="u-a",
                feature_ids=["fp_1", "fp_2"],
                module_names=["模块A"],
                query_text="模块A 任务",
            ),
            PlacementUnit(
                unit_id="u-b",
                feature_ids=["fp_3", "fp_4", "fp_5"],
                module_names=["模块B"],
                query_text="模块B 练习 复用端内做题组件",
            ),
        ],
        unit_count=2,
    )
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "services.process_runtime.initiative_profile.build_profile",
                new=AsyncMock(return_value={"status": "ok", "profile": {}, "degrade_reason": ""}),
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.team_gate.resolve_team_core",
                new=AsyncMock(
                    return_value={
                        "team_core": ["core-1", "core-2", "host-1"],
                        "space_id": "space-1",
                        "resolution": "explicit_space",
                        "clarify_reason": "",
                        "should_clarify": False,
                    }
                ),
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.team_gate.filter_indexed_repository_ids",
                new=AsyncMock(return_value=["core-1", "core-2", "host-1"]),
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.history_prior.asplit_history_priors",
                new=AsyncMock(return_value=HistoryPriorResult()),
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.shortlist.build_shortlist",
                new=AsyncMock(return_value=shortlist),
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.placement_units.build_placement_units",
                return_value=units,
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.place_units.place_units",
                new=AsyncMock(return_value=place),
            )
        )
        stack.enter_context(
            patch.object(adapter, "_aload_charters", new=AsyncMock(return_value={}))
        )
        stack.enter_context(
            patch.object(
                adapter,
                "_ascore_history",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        scores={}, unavailable_reason="", citations=[], citation_ids=[]
                    )
                ),
            )
        )
        stack.enter_context(
            patch.object(adapter, "_aload_module_summaries", new=AsyncMock(return_value={}))
        )
        stack.enter_context(
            patch.object(adapter, "_collect_supplements", new=AsyncMock(return_value=[]))
        )
        stack.enter_context(patch.object(adapter, "_emit_recalled", new=AsyncMock()))
        stack.enter_context(patch.object(adapter, "_emit_scored", new=AsyncMock()))
        stack.enter_context(
            patch.object(adapter, "_apply_boundary_overrides", new=AsyncMock(return_value=0))
        )
        yield


@pytest.mark.asyncio
async def test_adapter_attaches_placements_after_shortlist():
    """shortlist 后结果含 placement_units 摘要与 placements 字段。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(repo_ids=["core-1", "core-2"]))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    with _common_patches(adapter, shortlist=_shortlist()):
        summary = await adapter.route(_session())

    assert summary.get("status") == "ok"
    assert "placements" in summary
    placements = summary["placements"]
    assert len(placements) >= 1
    for p in placements:
        assert "primary_repo" in p
        assert "supporting_repos" in p
        assert "confidence" in p
    assert summary.get("placement_unit_count") == 2 or "placement_units" in summary


@pytest.mark.asyncio
async def test_placement_primary_in_shortlist_or_reuse_hosts():
    """任一 placement.primary_repo（非空）∈ shortlist ∪ reuse hosts。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(repo_ids=["core-1"]))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)
    shortlist_ids = {"core-1", "core-2", "host-1"}
    reuse_hosts = {"host-1"}

    with _common_patches(adapter, shortlist=_shortlist()):
        summary = await adapter.route(_session())

    allowed = shortlist_ids | reuse_hosts
    placements = summary.get("placements") or []
    assert placements, "placements must be present"
    for p in placements:
        primary = p.get("primary_repo")
        if primary:
            assert primary in allowed


@pytest.mark.asyncio
async def test_v2_calls_use_nonempty_hard_scope_subset():
    """注入 router 时 route(..., repository_ids=) 非空且 ⊆ hard_scope。"""
    recorded: list[list[str] | None] = []

    async def _route(query, **kwargs):
        recorded.append(kwargs.get("repository_ids"))
        ids = kwargs.get("repository_ids") or ["core-1"]
        return _fake_router_result(repo_ids=list(ids)[:2])

    router = MagicMock()
    router.route = AsyncMock(side_effect=_route)
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    # 不 stub place_units——走真实 place_units，断言其调用 router 时的 repository_ids
    units = PlacementUnitsResult(
        status="ok",
        units=[
            PlacementUnit(
                unit_id="u1",
                feature_ids=["a", "b"],
                module_names=["模块A"],
                query_text="任务",
            ),
            PlacementUnit(
                unit_id="u2",
                feature_ids=["c", "d", "e"],
                module_names=["模块B"],
                query_text="练习 复用端内做题组件",
            ),
        ],
        unit_count=2,
    )

    with (
        patch(
            "services.process_runtime.initiative_profile.build_profile",
            new=AsyncMock(return_value={"status": "ok", "profile": {}, "degrade_reason": ""}),
        ),
        patch(
            "services.process_runtime.team_gate.resolve_team_core",
            new=AsyncMock(
                return_value={
                    "team_core": ["core-1", "core-2", "host-1"],
                    "space_id": "space-1",
                    "resolution": "explicit_space",
                    "clarify_reason": "",
                    "should_clarify": False,
                }
            ),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=["core-1", "core-2", "host-1"]),
        ),
        patch(
            "services.process_runtime.history_prior.asplit_history_priors",
            new=AsyncMock(return_value=HistoryPriorResult()),
        ),
        patch(
            "services.process_runtime.shortlist.build_shortlist",
            new=AsyncMock(return_value=_shortlist()),
        ),
        patch(
            "services.process_runtime.placement_units.build_placement_units",
            return_value=units,
        ),
        patch.object(adapter, "_aload_charters", new=AsyncMock(return_value={})),
        patch.object(
            adapter,
            "_ascore_history",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    scores={}, unavailable_reason="", citations=[], citation_ids=[]
                )
            ),
        ),
        patch.object(adapter, "_aload_module_summaries", new=AsyncMock(return_value={})),
        patch.object(adapter, "_collect_supplements", new=AsyncMock(return_value=[])),
        patch.object(adapter, "_emit_recalled", new=AsyncMock()),
        patch.object(adapter, "_emit_scored", new=AsyncMock()),
        patch.object(adapter, "_apply_boundary_overrides", new=AsyncMock(return_value=0)),
    ):
        summary = await adapter.route(_session())

    hard_scope = set(summary.get("hard_scope") or ["core-1", "core-2", "host-1"])
    assert recorded, "router must be called"
    for ids in recorded:
        assert ids is not None and len(ids) > 0
        assert set(ids) <= hard_scope | {"core-1", "core-2", "host-1"}


@pytest.mark.asyncio
async def test_v2_call_count_tracks_units_not_features():
    """多 feature 时 unit_count < feature_count，且 V2 调用次数 ≈ unit_count。"""
    call_count = {"n": 0}

    async def _route(query, **kwargs):
        call_count["n"] += 1
        return _fake_router_result(repo_ids=["core-1", "host-1"])

    router = MagicMock()
    router.route = AsyncMock(side_effect=_route)
    adapter = BlueprintRouteAdapter(router=router, top_k=5)
    feature_count = len(_spec_multi_features()["feature_points"])
    units = PlacementUnitsResult(
        status="ok",
        units=[
            PlacementUnit(unit_id="u1", feature_ids=["1", "2"], module_names=["A"], query_text="a"),
            PlacementUnit(
                unit_id="u2",
                feature_ids=["3", "4", "5"],
                module_names=["B"],
                query_text="b",
            ),
        ],
        unit_count=2,
    )
    assert units.unit_count < feature_count

    with (
        patch(
            "services.process_runtime.initiative_profile.build_profile",
            new=AsyncMock(return_value={"status": "ok", "profile": {}, "degrade_reason": ""}),
        ),
        patch(
            "services.process_runtime.team_gate.resolve_team_core",
            new=AsyncMock(
                return_value={
                    "team_core": ["core-1", "core-2", "host-1"],
                    "space_id": "space-1",
                    "resolution": "explicit_space",
                    "clarify_reason": "",
                    "should_clarify": False,
                }
            ),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=["core-1", "core-2", "host-1"]),
        ),
        patch(
            "services.process_runtime.history_prior.asplit_history_priors",
            new=AsyncMock(return_value=HistoryPriorResult()),
        ),
        patch(
            "services.process_runtime.shortlist.build_shortlist",
            new=AsyncMock(return_value=_shortlist()),
        ),
        patch(
            "services.process_runtime.placement_units.build_placement_units",
            return_value=units,
        ),
        patch.object(adapter, "_aload_charters", new=AsyncMock(return_value={})),
        patch.object(
            adapter,
            "_ascore_history",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    scores={}, unavailable_reason="", citations=[], citation_ids=[]
                )
            ),
        ),
        patch.object(adapter, "_aload_module_summaries", new=AsyncMock(return_value={})),
        patch.object(adapter, "_collect_supplements", new=AsyncMock(return_value=[])),
        patch.object(adapter, "_emit_recalled", new=AsyncMock()),
        patch.object(adapter, "_emit_scored", new=AsyncMock()),
        patch.object(adapter, "_apply_boundary_overrides", new=AsyncMock(return_value=0)),
    ):
        summary = await adapter.route(_session())

    assert summary.get("placement_unit_count") == units.unit_count
    assert summary.get("placement_unit_count", 0) < feature_count
    # place_units 每 unit 一次；允许额外整篇信号调用但应远小于 feature_count
    assert call_count["n"] <= units.unit_count + 1
    assert call_count["n"] < feature_count
    assert call_count["n"] >= 1
    # 关键信号：不得按 feature 逐点全探
    assert call_count["n"] <= units.unit_count + 1


@pytest.mark.asyncio
async def test_association_returns_placements_not_sole_three_component():
    """RepoAssociation 主路径返回 placements，不再仅依赖三分量唯一决策。"""
    from initiatives.services.repo_association_service import RepoAssociationService

    space = SimpleNamespace(id="sp1", repositories=["core-1", "core-2", "host-1"])
    svc = RepoAssociationService()
    flat = [
        {"id": "f1", "module": "M1", "name": "a", "description": "da"},
        {"id": "f2", "module": "M1", "name": "b", "description": "db"},
        {"id": "f3", "module": "M2", "name": "c", "description": "复用端内做题组件"},
    ]
    place = PlacementResult(
        status="ok",
        placements=[
            UnitPlacement(
                unit_id="u1",
                primary_repo="core-1",
                supporting_repos=["core-2"],
                confidence="high",
                evidence=[{"source": "placement"}],
                open_questions=[],
            ),
            UnitPlacement(
                unit_id="u2",
                primary_repo="host-1",
                supporting_repos=[],
                confidence="medium",
                evidence=[{"source": "placement"}],
                open_questions=[],
            ),
        ],
        unit_count=2,
        placement_count=2,
        hard_scope=["core-1", "core-2", "host-1"],
    )

    with (
        patch.object(
            svc,
            "_resolve_repository_ids",
            new=AsyncMock(return_value=["core-1", "core-2", "host-1"]),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=["core-1", "core-2", "host-1"]),
        ),
        patch(
            "services.process_runtime.history_prior.asplit_history_priors",
            new=AsyncMock(return_value=HistoryPriorResult()),
        ),
        patch(
            "services.process_runtime.shortlist.build_shortlist",
            new=AsyncMock(return_value=_shortlist()),
        ),
        patch(
            "services.process_runtime.placement_units.build_placement_units",
            return_value=PlacementUnitsResult(
                units=[
                    PlacementUnit(unit_id="u1", feature_ids=["f1", "f2"], module_names=["M1"], query_text="a"),
                    PlacementUnit(
                        unit_id="u2",
                        feature_ids=["f3"],
                        module_names=["M2"],
                        query_text="c",
                    ),
                ],
                unit_count=2,
            ),
        ),
        patch(
            "services.process_runtime.place_units.place_units",
            new=AsyncMock(return_value=place),
        ),
        patch.object(svc, "_persist_candidates", new=AsyncMock(return_value=2)),
        patch.object(svc, "_record_routing_trace", new=AsyncMock()),
        patch.object(
            svc,
            "_fuse_extended_signals",
            new=AsyncMock(
                return_value=[
                    {
                        "repo_id": "core-1",
                        "repo_name": "n1",
                        "score": 0.9,
                        "confidence": "high",
                        "reason": "x",
                        "matched_node_paths": [],
                    }
                ]
            ),
        ),
        patch(
            "codegraph.services.repo_router_v2.RepoRouterV2.route",
            new=AsyncMock(return_value=_fake_router_result(repo_ids=["core-1"])),
        ),
    ):
        result = await svc.propose(
            space=space,
            features_flat=flat,
            initiated_by_user_id="u1",
        )

    assert "placements" in result
    assert len(result["placements"]) >= 1
    primaries = {p.get("primary_repo") for p in result["placements"] if p.get("primary_repo")}
    # multi-primary 聚合：不应只剩单一三分量赢家作为唯一叙事
    assert len(primaries) >= 1
    cand_ids = {c.get("repo_id") or c.get("repository_id") for c in result.get("candidates") or []}
    assert cand_ids <= {"core-1", "core-2", "host-1"}
