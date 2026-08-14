"""Phase 129 漏斗 shortlist + role_map 接线守卫测（LIST+ROLE；D-15）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.process_runtime.blueprint_route import BlueprintRouteAdapter
from services.process_runtime.history_prior import HistoryPriorResult
from services.process_runtime.role_map import RoleMapResult
from services.process_runtime.shortlist import ShortlistResult


def _spec() -> dict:
    return {
        "goal": [{"block_id": "g1", "type": "paragraph", "text": "高三提分看板改造"}],
        "feature_points": [{"id": "fp_1", "title": "任务分发", "intent": "brownfield"}],
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


def _session(*, team_include: list[str] | None = None):
    return SimpleNamespace(
        id="s-129",
        stage_state={
            "requirement_spec": _spec(),
            "decomposition": {"project_id": "proj-1", "space_id": "space-1"},
            "include_repos": team_include or ["core-1", "core-2"],
        },
        work_item_id=None,
        initiated_by_user_id="u1",
    )


@pytest.mark.asyncio
async def test_adapter_attaches_shortlist_and_role_map():
    """team_gate 通过后结果含 shortlist 与 role_map/placement_defaults。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(repo_ids=["core-1", "core-2"]))
    adapter = BlueprintRouteAdapter(router=router, top_k=3)

    shortlist = ShortlistResult(
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
                "force_include_reasons": ["history_demand"],
            },
        ],
        shortlist_count=2,
    )
    role_map = RoleMapResult(
        status="ok",
        roles={
            "app_shell": {"primary": "core-1", "supporting": [], "forbidden": []},
            "practice_reuse_host": {"primary": None, "supporting": [], "forbidden": []},
            "course_config": {"primary": None, "supporting": [], "forbidden": []},
            "learning_state": {"primary": None, "supporting": [], "forbidden": []},
        },
        per_repo=[{"repository_id": "core-1", "role": "app_shell", "assignment": "primary"}],
        placement_defaults={"learning_state_writer_not_app_shell": True},
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
                    "team_core": ["core-1", "core-2"],
                    "space_id": "space-1",
                    "resolution": "explicit_space",
                    "clarify_reason": "",
                    "should_clarify": False,
                }
            ),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=["core-1", "core-2"]),
        ),
        patch(
            "services.process_runtime.history_prior.asplit_history_priors",
            new=AsyncMock(
                return_value=HistoryPriorResult(
                    force_include_ids=["core-2"],
                    reasons_by_repo={"core-2": ["history_demand"]},
                )
            ),
        ),
        patch(
            "services.process_runtime.shortlist.build_shortlist",
            new=AsyncMock(return_value=shortlist),
        ),
        patch(
            "services.process_runtime.role_map.build_role_map",
            return_value=role_map,
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

    assert summary.get("status") == "ok"
    assert "shortlist" in summary
    assert summary.get("shortlist_count") == 2 or len(summary["shortlist"]) == 2
    assert "role_map" in summary
    assert summary.get("placement_defaults", {}).get("learning_state_writer_not_app_shell") is True


@pytest.mark.asyncio
async def test_fusion_candidates_subset_of_shortlist():
    """融合候选 repository_id ⊆ shortlist ids。"""
    router = MagicMock()
    # V2 误返回 shortlist 外仓 out-9
    router.route = AsyncMock(
        return_value=_fake_router_result(repo_ids=["core-1", "out-9"])
    )
    adapter = BlueprintRouteAdapter(router=router, top_k=5)
    shortlist = ShortlistResult(
        repositories=[
            {
                "repository_id": "core-1",
                "rank": 1,
                "score": 1.0,
                "team_membership": "team_core",
                "signals": {"activity": 1.0, "capability_coarse": 1.0, "charter_domain": 0.0},
                "force_include_reasons": [],
            }
        ],
        shortlist_count=1,
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
                    "team_core": ["core-1"],
                    "space_id": "space-1",
                    "resolution": "explicit_space",
                    "clarify_reason": "",
                    "should_clarify": False,
                }
            ),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=["core-1"]),
        ),
        patch(
            "services.process_runtime.history_prior.asplit_history_priors",
            new=AsyncMock(return_value=HistoryPriorResult()),
        ),
        patch(
            "services.process_runtime.shortlist.build_shortlist",
            new=AsyncMock(return_value=shortlist),
        ),
        patch(
            "services.process_runtime.role_map.build_role_map",
            return_value=RoleMapResult(status="ok", placement_defaults={}),
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
        summary = await adapter.route(_session(team_include=["core-1"]))

    cand_ids = {c["repository_id"] for c in summary.get("candidates") or []}
    assert cand_ids <= {"core-1"}
    assert "out-9" not in cand_ids


@pytest.mark.asyncio
async def test_history_force_include_appears_in_shortlist_payload():
    """history force-include（能力分 0）出现在 shortlist。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(repo_ids=["core-1"]))
    adapter = BlueprintRouteAdapter(router=router, top_k=3)
    shortlist = ShortlistResult(
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
                "repository_id": "hist-1",
                "rank": 2,
                "score": 0.0,
                "team_membership": "team_core",
                "signals": {"activity": 0.0, "capability_coarse": 0.0, "charter_domain": 0.0},
                "force_include_reasons": ["history_demand"],
            },
        ],
        shortlist_count=2,
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
                    "team_core": ["core-1", "hist-1"],
                    "space_id": "space-1",
                    "resolution": "explicit_space",
                    "clarify_reason": "",
                    "should_clarify": False,
                }
            ),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=["core-1", "hist-1"]),
        ),
        patch(
            "services.process_runtime.history_prior.asplit_history_priors",
            new=AsyncMock(
                return_value=HistoryPriorResult(
                    force_include_ids=["hist-1"],
                    reasons_by_repo={"hist-1": ["history_demand"]},
                )
            ),
        ),
        patch(
            "services.process_runtime.shortlist.build_shortlist",
            new=AsyncMock(return_value=shortlist),
        ),
        patch(
            "services.process_runtime.role_map.build_role_map",
            return_value=RoleMapResult(status="ok", placement_defaults={}),
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
        summary = await adapter.route(_session(team_include=["core-1", "hist-1"]))

    sl = summary.get("shortlist") or []
    if isinstance(sl, dict):
        repos = sl.get("repositories") or []
    else:
        repos = sl
    ids = {r["repository_id"] for r in repos}
    assert "hist-1" in ids
    hist = next(r for r in repos if r["repository_id"] == "hist-1")
    assert "history_demand" in (hist.get("force_include_reasons") or [])


@pytest.mark.asyncio
async def test_role_map_unmapped_clarify_no_full_library():
    """role_map clarify(unmapped_role) → status=clarify，candidates 不塞全库。"""
    router = MagicMock()
    router.route = AsyncMock(
        return_value=_fake_router_result(repo_ids=["core-1", "core-2", "core-3"])
    )
    adapter = BlueprintRouteAdapter(router=router, top_k=10)

    with (
        patch(
            "services.process_runtime.initiative_profile.build_profile",
            new=AsyncMock(return_value={"status": "ok", "profile": {}, "degrade_reason": ""}),
        ),
        patch(
            "services.process_runtime.team_gate.resolve_team_core",
            new=AsyncMock(
                return_value={
                    "team_core": ["core-1"],
                    "space_id": "space-1",
                    "resolution": "explicit_space",
                    "clarify_reason": "",
                    "should_clarify": False,
                }
            ),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=["core-1"]),
        ),
        patch(
            "services.process_runtime.history_prior.asplit_history_priors",
            new=AsyncMock(return_value=HistoryPriorResult()),
        ),
        patch(
            "services.process_runtime.shortlist.build_shortlist",
            new=AsyncMock(
                return_value=ShortlistResult(
                    repositories=[
                        {
                            "repository_id": "core-1",
                            "rank": 1,
                            "score": 0.1,
                            "team_membership": "team_core",
                            "signals": {
                                "activity": 0.1,
                                "capability_coarse": 0.1,
                                "charter_domain": 0.0,
                            },
                            "force_include_reasons": [],
                        }
                    ],
                    shortlist_count=1,
                )
            ),
        ),
        patch(
            "services.process_runtime.role_map.build_role_map",
            return_value=RoleMapResult(
                status="clarify",
                clarify_reason="unmapped_role",
                placement_defaults={"learning_state_writer_not_app_shell": True},
            ),
        ),
        patch.object(adapter, "_aload_charters", new=AsyncMock(return_value={})),
        patch.object(adapter, "_emit_scored", new=AsyncMock()),
    ):
        summary = await adapter.route(_session(team_include=["core-1"]))

    assert summary["status"] == "clarify"
    assert summary["clarify_reason"] == "unmapped_role"
    assert summary["candidates"] == []
    # V2 可能已调用取信号，但不得把全库候选塞进 clarify 结果
    assert len(summary["candidates"]) == 0
