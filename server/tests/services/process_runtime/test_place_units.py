"""Phase 130 place_units 细落点单测（UNIT-02/03；去固定角色化）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.process_runtime.placement_units import PlacementUnit
from services.process_runtime.place_units import PlacementResult, place_units, resolve_hard_scope


def _unit(
    *,
    unit_id: str = "pu_1",
    query_text: str = "模块B 练习入口",
    feature_ids: list[str] | None = None,
) -> PlacementUnit:
    return PlacementUnit(
        unit_id=unit_id,
        feature_ids=feature_ids or ["f1"],
        module_names=["模块B"],
        query_text=query_text,
        reuse_edges=[{"phrase": "复用端内做题组件", "target": "端内做题组件"}],
        reuse_host_hints=[],
    )


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
        candidates=candidates, router_version="v2", auto_selected=True, degrade_reason=""
    )


def test_resolve_hard_scope_is_shortlist_intersect_team():
    """hard_scope = (shortlist ∪ hosts) ∩ team。"""
    assert resolve_hard_scope(
        shortlist_ids=["A", "B", "X"],
        team_core=["A", "B", "C"],
    ) == ["A", "B"]
    assert resolve_hard_scope(
        shortlist_ids=["A", "B"],
        reuse_host_repo_ids=["D", "outsider"],
        team_core=["A", "B", "C", "D"],
    ) == ["A", "B", "D"]
    # team 空则仅用 shortlist∪hosts
    assert resolve_hard_scope(
        shortlist_ids=["A"],
        reuse_host_repo_ids=["H"],
        team_core=[],
    ) == ["A", "H"]


@pytest.mark.asyncio
async def test_place_units_primary_in_shortlist_with_fields():
    """每个 unit 返回 primary∈hard_scope，含完整字段。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(["A", "B", "C"]))
    units = [_unit(unit_id="u1"), _unit(unit_id="u2", query_text="模块A 看板")]
    result = await place_units(
        units,
        shortlist_ids=["A", "B", "C"],
        team_core=["A", "B", "C", "D"],
        router=router,
    )
    assert isinstance(result, PlacementResult) or isinstance(result, dict)
    placements = (
        result.placements if hasattr(result, "placements") else result["placements"]
    )
    assert len(placements) == 2
    for p in placements:
        payload = p if isinstance(p, dict) else p.__dict__
        primary = payload.get("primary_repo")
        assert primary in {"A", "B", "C"}
        assert "supporting_repos" in payload
        assert "confidence" in payload
        assert "evidence" in payload
        assert "open_questions" in payload


@pytest.mark.asyncio
async def test_v2_repository_ids_hard_scoped():
    """V2.route 的 repository_ids ⊆ hard_scope，从未 None/全库。"""
    recorded: list[dict] = []

    async def _route(query, **kwargs):
        recorded.append({"query": query, **kwargs})
        ids = kwargs.get("repository_ids") or []
        return _fake_router_result(list(ids)[:2] or ["A"])

    router = MagicMock()
    router.route = AsyncMock(side_effect=_route)
    await place_units(
        [_unit()],
        shortlist_ids=["A", "B", "C"],
        reuse_host_repo_ids=["D"],
        team_core=["A", "B", "C", "D"],
        router=router,
    )
    assert recorded, "router.route must be called"
    for call in recorded:
        ids = call.get("repository_ids")
        assert ids is not None
        assert len(ids) > 0
        # hard_scope = (shortlist ∪ reuse hosts) ∩ team
        assert set(ids) <= {"A", "B", "C", "D"}
        assert "D" in ids
        assert call.get("use_llm") is True


@pytest.mark.asyncio
async def test_reuse_host_repo_ids_expand_hard_scope():
    """reuse_host_repo_ids 可并入 hard_scope（仍受 team 约束）。"""
    recorded: list[list[str]] = []

    async def _route(query, **kwargs):
        recorded.append(list(kwargs.get("repository_ids") or []))
        return _fake_router_result(["H", "A"], scores=[0.95, 0.5])

    router = MagicMock()
    router.route = AsyncMock(side_effect=_route)
    result = await place_units(
        [_unit()],
        shortlist_ids=["A"],
        reuse_host_repo_ids=["H"],
        team_core=["A", "H"],
        router=router,
    )
    assert recorded and set(recorded[0]) == {"A", "H"}
    primary = result.placements[0].primary_repo
    assert primary in {"A", "H"}


@pytest.mark.asyncio
async def test_primary_outside_scope_discarded():
    """stub 返回 scope 外仓 E → primary 不得为 E。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(["E", "A"], scores=[0.99, 0.1]))
    result = await place_units(
        [_unit()],
        shortlist_ids=["A", "B"],
        team_core=["A", "B"],
        router=router,
    )
    placements = (
        result.placements if hasattr(result, "placements") else result["placements"]
    )
    payload = placements[0] if isinstance(placements[0], dict) else placements[0].__dict__
    assert payload.get("primary_repo") != "E"
    assert payload.get("primary_repo") in {None, "A", "B"}
    oq = payload.get("open_questions") or []
    degrade = []
    if hasattr(result, "degrade_reasons"):
        degrade = result.degrade_reasons
    else:
        degrade = result.get("degrade_reasons") or []
    assert oq or degrade or payload.get("primary_repo") == "A"


@pytest.mark.asyncio
async def test_forbidden_repo_not_primary():
    """forbidden_repo_ids 仓不得为 primary。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(["B", "A"], scores=[0.99, 0.5]))
    result = await place_units(
        [_unit()],
        shortlist_ids=["A", "B"],
        team_core=["A", "B"],
        forbidden_repo_ids=["B"],
        router=router,
    )
    placements = (
        result.placements if hasattr(result, "placements") else result["placements"]
    )
    payload = placements[0] if isinstance(placements[0], dict) else placements[0].__dict__
    assert payload.get("primary_repo") != "B"
    assert payload.get("primary_repo") == "A"


@pytest.mark.asyncio
async def test_place_units_observability_no_requirement_body(monkeypatch):
    """观测 place_units_started/completed；无需求原文。"""
    events: list[tuple[str, dict]] = []

    class _FakeLogger:
        def info(self, event, **kwargs):
            events.append((event, kwargs))

        def warning(self, event, **kwargs):
            events.append((event, kwargs))

        def error(self, event, **kwargs):
            events.append((event, kwargs))

    monkeypatch.setattr(
        "services.process_runtime.place_units.logger",
        _FakeLogger(),
    )
    long_req = "这是一段很长很长很长很长很长很长很长很长很长很长很长很长的需求原文" * 5
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(["A"]))
    await place_units(
        [_unit(query_text=long_req)],
        shortlist_ids=["A"],
        team_core=["A"],
        router=router,
    )
    names = [e[0] for e in events]
    assert any("place_units_started" in n for n in names)
    assert any("place_units_completed" in n for n in names)
    for _name, kwargs in events:
        blob = " ".join(str(v) for v in kwargs.values())
        assert "很长很长很长很长很长很长很长很长很长很长很长很长的需求原文" not in blob
        assert kwargs.get("category") == "sampling"
        assert kwargs.get("component") == "process_runtime"
    completed = next(kw for n, kw in events if "place_units_completed" in n)
    assert "duration_ms" in completed
    assert "unit_count" in completed
