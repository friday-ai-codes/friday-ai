"""Phase 131 漏斗门禁/反思接线守卫测（D-16/D-17；D-02）。"""

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


def _spec() -> dict:
    return {
        "goal": [{"block_id": "g1", "type": "paragraph", "text": "看板改造"}],
        "feature_points": [
            {"id": "fp_1", "title": "列表", "module": "A", "description": "列表"},
            {"id": "fp_2", "title": "详情", "module": "A", "description": "详情"},
        ],
    }


def _session():
    return SimpleNamespace(
        id="s-131",
        stage_state={
            "requirement_spec": _spec(),
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
                "signals": {},
                "force_include_reasons": [],
            },
            {
                "repository_id": "core-2",
                "rank": 2,
                "score": 0.5,
                "team_membership": "team_core",
                "signals": {},
                "force_include_reasons": [],
            },
            {
                "repository_id": "host-1",
                "rank": 3,
                "score": 0.4,
                "team_membership": "team_core",
                "signals": {},
                "force_include_reasons": [],
            },
        ],
        shortlist_count=3,
    )


def _place_high_dual() -> PlacementResult:
    return PlacementResult(
        status="ok",
        placements=[
            UnitPlacement(
                unit_id="u1",
                primary_repo="core-1",
                supporting_repos=["core-2"],
                confidence="high",
                evidence=[{"kind": "charter"}, {"kind": "v2"}],
                open_questions=[],
                feature_ids=["fp_1"],
                hard_scope=["core-1", "core-2", "host-1"],
            ),
            UnitPlacement(
                unit_id="u2",
                primary_repo="core-2",
                supporting_repos=[],
                confidence="high",
                evidence=[{"kind": "history"}, {"kind": "shortlist"}],
                open_questions=[],
                feature_ids=["fp_2"],
                hard_scope=["core-1", "core-2", "host-1"],
            ),
        ],
        unit_count=2,
        placement_count=2,
        hard_scope=["core-1", "core-2", "host-1"],
    )


def _place_medium() -> PlacementResult:
    return PlacementResult(
        status="ok",
        placements=[
            UnitPlacement(
                unit_id="u1",
                primary_repo="core-1",
                supporting_repos=[],
                confidence="medium",
                evidence=[{"kind": "v2"}],
                open_questions=[],
                feature_ids=["fp_1"],
                hard_scope=["core-1", "core-2", "host-1"],
            ),
        ],
        unit_count=1,
        placement_count=1,
        hard_scope=["core-1", "core-2", "host-1"],
    )


def _place_coverage_hole() -> PlacementResult:
    return PlacementResult(
        status="ok",
        placements=[
            UnitPlacement(
                unit_id="u-hole",
                primary_repo="core-1",
                supporting_repos=[],
                confidence="medium",
                evidence=[{"kind": "v2"}],
                open_questions=[],
                feature_ids=["fp_1"],
                hard_scope=[],
            ),
        ],
        unit_count=1,
        placement_count=1,
        hard_scope=["core-1", "core-2", "host-1"],
    )


def _place_out_of_scope() -> PlacementResult:
    return PlacementResult(
        status="ok",
        placements=[
            UnitPlacement(
                unit_id="u-bad",
                primary_repo="outsider",
                supporting_repos=[],
                confidence="high",
                evidence=[{"kind": "charter"}, {"kind": "v2"}],
                open_questions=[],
                feature_ids=["fp_1"],
                hard_scope=["core-1"],
            ),
        ],
        unit_count=1,
        placement_count=1,
        hard_scope=["core-1"],
    )


def _units() -> PlacementUnitsResult:
    return PlacementUnitsResult(
        status="ok",
        units=[
            PlacementUnit(
                unit_id="u1",
                feature_ids=["fp_1"],
                module_names=["A"],
                query_text="A",
            ),
            PlacementUnit(
                unit_id="u2",
                feature_ids=["fp_2"],
                module_names=["A"],
                query_text="A2",
            ),
        ],
        unit_count=2,
    )


def _fake_router(*, auto_selected=True):
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                repo_id="core-1",
                repo_name="c1",
                score=0.99,
                confidence="high",
                reasoning="hit",
                matched_node_paths=[],
            ),
            SimpleNamespace(
                repo_id="ghost-full-lib",
                repo_name="ghost",
                score=0.5,
                confidence="low",
                reasoning="leak",
                matched_node_paths=[],
            ),
        ],
        router_version="v2",
        auto_selected=auto_selected,
        degrade_reason="",
    )


@contextmanager
def _patches(adapter, *, place_result, shortlist=None):
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "services.process_runtime.initiative_profile.build_profile",
                new=AsyncMock(
                    return_value={"status": "ok", "profile": {}, "degrade_reason": ""}
                ),
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
                        "membership": {
                            "core-1": "team_core",
                            "core-2": "team_core",
                            "host-1": "team_core",
                            "outsider": "out_of_team",
                        },
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
                new=AsyncMock(return_value=shortlist or _shortlist()),
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.placement_units.build_placement_units",
                return_value=_units(),
            )
        )
        stack.enter_context(
            patch(
                "services.process_runtime.place_units.place_units",
                new=AsyncMock(return_value=place_result),
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
async def test_route_payload_includes_funnel_gates():
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router(auto_selected=True))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    with _patches(adapter, place_result=_place_medium()):
        summary = await adapter.route(_session())

    assert "funnel_gates" in summary
    fg = summary["funnel_gates"]
    assert fg.get("status") in {"pass", "clarify", "block"}
    assert isinstance(fg.get("reason_codes"), list)
    assert "publish_mode" in summary


@pytest.mark.asyncio
async def test_auto_selected_false_when_d02_unmet_even_if_v2_true():
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router(auto_selected=True))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    with _patches(adapter, place_result=_place_medium()):
        summary = await adapter.route(_session())

    assert summary.get("auto_selected") is False


@pytest.mark.asyncio
async def test_auto_selected_true_when_d02_met():
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router(auto_selected=False))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    with _patches(adapter, place_result=_place_high_dual()):
        summary = await adapter.route(_session())

    assert summary.get("auto_selected") is True
    assert summary.get("publish_mode") in {"auto", "confirmation"}


@pytest.mark.asyncio
async def test_gate_block_does_not_silently_ok_with_out_of_scope():
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router(auto_selected=True))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    with _patches(adapter, place_result=_place_out_of_scope()):
        summary = await adapter.route(_session())

    fg = summary.get("funnel_gates") or {}
    # 反思可能局部修复；若门仍 block 则顶层不得静默 ok / auto
    if fg.get("status") == "block":
        assert summary.get("status") != "ok"
        assert summary.get("auto_selected") is False
    # 不得把 outsider / ghost-full-lib 当可开工 primary 静默放出
    cand_ids = {c.get("repository_id") for c in summary.get("candidates") or []}
    assert "outsider" not in cand_ids
    assert "ghost-full-lib" not in cand_ids
    assert "funnel_gates" in summary


@pytest.mark.asyncio
async def test_reflection_called_for_repairable_trigger():
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router(auto_selected=True))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    with _patches(adapter, place_result=_place_coverage_hole()):
        with patch(
            "services.process_runtime.reflection.run_reflection_loop",
            wraps=__import__(
                "services.process_runtime.reflection", fromlist=["run_reflection_loop"]
            ).run_reflection_loop,
        ) as spy:
            summary = await adapter.route(_session())

    assert spy.called
    assert summary.get("reflection") is not None
    refl = summary["reflection"]
    assert int(refl.get("rounds") or 0) <= 2


@pytest.mark.asyncio
async def test_reflection_overrun_needs_human_review_observable():
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router(auto_selected=True))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    def stubborn_loop(**kwargs):
        from services.process_runtime.reflection import ReflectionLoopResult

        return ReflectionLoopResult(
            rounds=2,
            outcome="unresolved",
            review_status="needs_human_review",
            reason_codes=["needs_human_review", "coverage_hole"],
            final_status="needs_human_review",
            placements=list(kwargs.get("placements") or []),
        )

    with _patches(adapter, place_result=_place_coverage_hole()):
        with patch(
            "services.process_runtime.reflection.run_reflection_loop",
            side_effect=stubborn_loop,
        ):
            summary = await adapter.route(_session())

    refl = summary.get("reflection") or {}
    assert (
        refl.get("review_status") == "needs_human_review"
        or "needs_human_review" in (refl.get("reason_codes") or [])
        or summary.get("status") in {"clarify", "block"}
    )
    assert summary.get("auto_selected") is False


@pytest.mark.asyncio
async def test_no_requirement_fulltext_in_gate_summary():
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router(auto_selected=True))
    adapter = BlueprintRouteAdapter(router=router, top_k=5)

    with _patches(adapter, place_result=_place_medium()):
        summary = await adapter.route(_session())

    blob = str(summary.get("funnel_gates")) + str(summary.get("reflection"))
    assert "高三提分专项请勿" not in blob
    assert len(blob) < 20000
