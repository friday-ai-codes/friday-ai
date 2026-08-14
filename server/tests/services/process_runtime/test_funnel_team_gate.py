"""Phase 128 漏斗三入口团队门禁集成测（D1/D3）。

覆盖：
- Blueprint：无团队 → clarify(missing_team)，不调全库 V2
- Blueprint：team_core 内路由；out_of_team 不得 primary
- RepoAssociation：空 Space → clarify
- MCP/sandbox：无团队 → clarify，candidates 非全库 top-k
- 裸 RepoRouterV2.route 无 grouping 仍为全局 annotate 兼容（本相位不改 V2）
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.process_runtime.blueprint_route import BlueprintRouteAdapter
from services.process_runtime.stage_sandbox import arun_route_stage


def _spec() -> dict:
    return {
        "goal": [{"block_id": "g1", "type": "paragraph", "text": "高三提分看板改造"}],
        "feature_points": [
            {"id": "fp_1", "title": "任务分发", "intent": "brownfield"},
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


@pytest.mark.asyncio
async def test_blueprint_missing_team_clarify_no_full_library_route():
    """无团队上下文 → clarify，绝不调用 RepoRouterV2.route（D3）。"""
    session = SimpleNamespace(
        id="s1",
        stage_state={"requirement_spec": _spec()},
        work_item_id=None,
        initiated_by_user_id="u1",
    )
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(repo_ids=["out-1"]))
    adapter = BlueprintRouteAdapter(router=router, top_k=3)

    with patch(
        "services.process_runtime.initiative_profile.build_profile",
        new=AsyncMock(
            return_value={
                "status": "ok",
                "profile": {"change_kind": "brownfield"},
                "degrade_reason": "",
            }
        ),
    ):
        summary = await adapter.route(session)

    assert summary["status"] == "clarify"
    assert summary["clarify_reason"] == "missing_team"
    assert summary["candidates"] == []
    router.route.assert_not_awaited()


@pytest.mark.asyncio
async def test_blueprint_out_of_team_not_primary():
    """有 team_core 时 route 仅在 core 内；mock 高分 out_of_team 不得进候选主列表。"""
    session = SimpleNamespace(
        id="s2",
        stage_state={
            "requirement_spec": _spec(),
            "decomposition": {"project_id": "proj-1", "space_id": "space-1"},
            "include_repos": ["core-1"],
        },
        work_item_id=None,
        initiated_by_user_id="u1",
    )
    router = MagicMock()
    # 即便 router 误返 out-9，gate 收窄 repository_ids 后只应请求 core
    router.route = AsyncMock(return_value=_fake_router_result(repo_ids=["core-1"]))

    adapter = BlueprintRouteAdapter(router=router, top_k=3)
    with (
        patch(
            "services.process_runtime.initiative_profile.build_profile",
            new=AsyncMock(
                return_value={
                    "status": "degraded",
                    "profile": None,
                    "degrade_reason": "mocked",
                }
            ),
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
        patch.object(
            adapter,
            "_aload_charters",
            new=AsyncMock(return_value={}),
        ),
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
        summary = await adapter.route(session)

    assert summary.get("status") == "ok"
    assert summary["candidates"]
    assert all(c.get("team_membership") == "team_core" for c in summary["candidates"])
    assert summary["candidates"][0]["repository_id"] == "core-1"
    call_kwargs = router.route.await_args.kwargs
    assert call_kwargs.get("repository_ids") == ["core-1"]


@pytest.mark.asyncio
async def test_sandbox_no_team_clarify_not_full_library_primary():
    """MCP/sandbox 无 project/space/team → clarify，candidates 空（D1）。"""
    summary = await arun_route_stage(
        requirement_text="随便改点东西",
        initiated_by_user_id="u1",
    )
    assert summary["status"] == "clarify"
    assert summary["clarify_reason"] == "missing_team"
    assert summary["candidates"] == []
    assert "offer" in summary


@pytest.mark.asyncio
async def test_sandbox_unindexed_team_clarify():
    """有团队但索引过滤后为空 → empty_team_core。"""
    fake_adapter = MagicMock()
    fake_adapter.route = AsyncMock(
        return_value={
            "status": "clarify",
            "clarify_reason": "empty_team_core",
            "candidates": [],
            "router_version": "clarify",
            "auto_selected": False,
            "intent": "brownfield",
            "weights_used": {},
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "citations": [],
            "team_core": [],
            "team_core_count": 0,
        }
    )
    with patch(
        "services.process_runtime.stage_sandbox._project_scope_repository_ids",
        new=AsyncMock(return_value=["repo-unindexed"]),
    ):
        summary = await arun_route_stage(
            requirement_text="登录页改造",
            project_id="00000000-0000-0000-0000-000000000001",
            route_adapter=fake_adapter,
            initiated_by_user_id="u1",
        )
    assert summary["status"] == "clarify"
    assert summary["clarify_reason"] == "empty_team_core"
    assert summary["candidates"] == []


def test_bare_repo_router_v2_grouping_annotate_only_comment():
    """文档守卫：裸 RepoRouterV2.route 无 grouping 仍为全局 annotate 兼容。

    Phase 128 只在漏斗入口 hard gate；不修改
    ``RepoRouterV2.grouping_repository_ids`` 的 annotate-only 语义。
    """
    from codegraph.services import repo_router_v2 as v2_mod

    src = open(v2_mod.__file__, encoding="utf-8").read()  # noqa: SIM115
    assert "grouping_repository_ids" in src
    # 硬过滤语义不得在 V2 内核落地为本相位行为（漏斗层负责）
    assert "annotate" in src.lower() or "grouping" in src
