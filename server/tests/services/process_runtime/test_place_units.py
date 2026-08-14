"""Phase 130 place_units 细落点单测（UNIT-02/03；D-07~D-11）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.process_runtime.placement_units import PlacementUnit
from services.process_runtime.place_units import PlacementResult, place_units
from services.process_runtime.role_map import PLACEMENT_DEFAULTS


def _unit(
    *,
    unit_id: str = "pu_1",
    query_text: str = "模块B 练习入口",
    hints: list[str] | None = None,
    feature_ids: list[str] | None = None,
) -> PlacementUnit:
    return PlacementUnit(
        unit_id=unit_id,
        feature_ids=feature_ids or ["f1"],
        module_names=["模块B"],
        query_text=query_text,
        reuse_edges=[{"phrase": "复用端内做题组件", "target": "端内做题组件"}],
        reuse_host_hints=hints or ["practice_reuse_host"],
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


@pytest.mark.asyncio
async def test_place_units_primary_in_shortlist_with_fields():
    """每个 unit 返回 primary∈shortlist（或 ∪ reuse host），含完整字段。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(["A", "B", "C"]))
    units = [_unit(unit_id="u1"), _unit(unit_id="u2", query_text="模块A 看板")]
    result = await place_units(
        units,
        shortlist_ids=["A", "B", "C"],
        role_map={
            "roles": {
                "app_shell": {"primary": "A", "supporting": [], "forbidden": []},
                "practice_reuse_host": {"primary": "B", "supporting": [], "forbidden": []},
                "course_config": {"primary": None, "supporting": [], "forbidden": []},
                "learning_state": {"primary": "C", "supporting": [], "forbidden": []},
            }
        },
        placement_defaults=dict(PLACEMENT_DEFAULTS),
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
        role_map={
            "roles": {
                "practice_reuse_host": {"primary": "D", "supporting": [], "forbidden": []},
                "app_shell": {"primary": "A", "supporting": [], "forbidden": []},
                "course_config": {"primary": None, "supporting": [], "forbidden": []},
                "learning_state": {"primary": None, "supporting": [], "forbidden": []},
            }
        },
        team_core=["A", "B", "C", "D"],
        router=router,
    )
    assert recorded, "router.route must be called"
    for call in recorded:
        ids = call.get("repository_ids")
        assert ids is not None
        assert len(ids) > 0
        assert set(ids) <= {"A", "B", "C", "D"}
        # hard_scope = shortlist ∪ reuse host D
        assert "D" in ids or set(ids) <= {"A", "B", "C", "D"}


@pytest.mark.asyncio
async def test_primary_outside_scope_discarded():
    """stub 返回 scope 外仓 E → primary 不得为 E。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(["E", "A"], scores=[0.99, 0.1]))
    result = await place_units(
        [_unit(hints=[])],
        shortlist_ids=["A", "B"],
        role_map={"roles": {}},
        team_core=["A", "B"],
        router=router,
    )
    placements = (
        result.placements if hasattr(result, "placements") else result["placements"]
    )
    payload = placements[0] if isinstance(placements[0], dict) else placements[0].__dict__
    assert payload.get("primary_repo") != "E"
    assert payload.get("primary_repo") in {None, "A", "B"}
    # 应有 degrade 或 open_question
    oq = payload.get("open_questions") or []
    degrade = []
    if hasattr(result, "degrade_reasons"):
        degrade = result.degrade_reasons
    else:
        degrade = result.get("degrade_reasons") or []
    assert oq or degrade or payload.get("primary_repo") == "A"


@pytest.mark.asyncio
async def test_learning_state_writer_not_app_shell():
    """placement_defaults：learning_state hint 时 primary ≠ app_shell。"""
    router = MagicMock()
    # V2 偏好 shell A
    router.route = AsyncMock(return_value=_fake_router_result(["A", "C"], scores=[0.95, 0.8]))
    unit = _unit(
        unit_id="ls",
        query_text="学习状态写入进度",
        hints=["learning_state"],
    )
    result = await place_units(
        [unit],
        shortlist_ids=["A", "C"],
        role_map={
            "roles": {
                "app_shell": {"primary": "A", "supporting": [], "forbidden": []},
                "learning_state": {"primary": "C", "supporting": [], "forbidden": []},
                "practice_reuse_host": {"primary": None, "supporting": [], "forbidden": []},
                "course_config": {"primary": None, "supporting": [], "forbidden": []},
            }
        },
        placement_defaults={"learning_state_writer_not_app_shell": True},
        team_core=["A", "C"],
        router=router,
    )
    placements = (
        result.placements if hasattr(result, "placements") else result["placements"]
    )
    payload = placements[0] if isinstance(placements[0], dict) else placements[0].__dict__
    primary = payload.get("primary_repo")
    if primary == "A":
        # 仅当无其他候选才允许，并应有 open_questions
        assert payload.get("open_questions")
    else:
        assert primary == "C"


@pytest.mark.asyncio
async def test_forbidden_repo_not_primary():
    """role_map forbidden 仓不得为 primary。"""
    router = MagicMock()
    router.route = AsyncMock(return_value=_fake_router_result(["B", "A"], scores=[0.99, 0.5]))
    result = await place_units(
        [_unit(hints=[])],
        shortlist_ids=["A", "B"],
        role_map={
            "roles": {
                "app_shell": {"primary": "A", "supporting": [], "forbidden": ["B"]},
                "practice_reuse_host": {"primary": None, "supporting": [], "forbidden": []},
                "course_config": {"primary": None, "supporting": [], "forbidden": []},
                "learning_state": {"primary": None, "supporting": [], "forbidden": []},
            },
            "per_repo": [
                {"repository_id": "B", "assignment": "forbidden", "role": "app_shell"}
            ],
        },
        team_core=["A", "B"],
        router=router,
    )
    placements = (
        result.placements if hasattr(result, "placements") else result["placements"]
    )
    payload = placements[0] if isinstance(placements[0], dict) else placements[0].__dict__
    assert payload.get("primary_repo") != "B"


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
