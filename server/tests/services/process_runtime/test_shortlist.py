"""Phase 129 shortlist 行为单测（LIST-01/02/04；D-01、D-04、D-06~D-10）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.process_runtime.shortlist import ShortlistResult, build_shortlist


@pytest.mark.asyncio
async def test_build_shortlist_team_universe_sorted_with_signals():
    """team_core 内合成信号，按综合分排序，每仓含 activity/capability/charter。"""
    activity = {"A": 0.9, "B": 0.5, "C": 0.2}
    capability = {"A": 0.4, "B": 0.8, "C": 0.1}
    charter = {"A": 0.3, "B": 0.1, "C": 0.9}

    result = await build_shortlist(
        team_core=["A", "B", "C"],
        adjacent_ids=[],
        out_of_team_ids=["Z"],
        activity_scores=activity,
        capability_scores=capability,
        charter_domain_scores=charter,
        planned_charter_ids=[],
        force_include_ids=[],
        top_n=10,
    )

    assert isinstance(result, ShortlistResult) or isinstance(result, dict)
    if isinstance(result, ShortlistResult):
        repos = result.repositories
        meta_count = result.shortlist_count
    else:
        repos = result["repositories"]
        meta_count = result.get("shortlist_count") or result.get("meta", {}).get("shortlist_count")

    ids = [r["repository_id"] for r in repos]
    assert set(ids) <= {"A", "B", "C"}
    assert "Z" not in ids
    # 综合分：A=0.9+0.4+0.3=1.6, B=0.5+0.8+0.1=1.4, C=0.2+0.1+0.9=1.2
    assert ids == ["A", "B", "C"]
    for repo in repos:
        signals = repo["signals"]
        assert "activity" in signals
        assert "capability_coarse" in signals
        assert "charter_domain" in signals
    assert meta_count == 3


@pytest.mark.asyncio
async def test_planned_charter_force_include_when_capability_zero():
    """planned 章程命中仓 D 能力粗分为 0 时仍进 shortlist，reason=charter_planned。"""
    result = await build_shortlist(
        team_core=["A", "B"],
        adjacent_ids=["D"],
        activity_scores={"A": 0.5, "B": 0.4, "D": 0.0},
        capability_scores={"A": 0.5, "B": 0.4, "D": 0.0},
        charter_domain_scores={"A": 0.1, "B": 0.1, "D": 0.7},
        planned_charter_ids=["D"],
        force_include_ids=[],
        top_n=2,  # 正常 top2 可能挤掉 D；force 应突破上界
    )
    repos = result.repositories if hasattr(result, "repositories") else result["repositories"]
    by_id = {r["repository_id"]: r for r in repos}
    assert "D" in by_id
    assert "charter_planned" in (by_id["D"].get("force_include_reasons") or [])


@pytest.mark.asyncio
async def test_out_of_team_never_enters_shortlist():
    """out_of_team 即使分数高也不进 shortlist（D-01）。"""
    result = await build_shortlist(
        team_core=["A"],
        adjacent_ids=[],
        out_of_team_ids=["OUT"],
        activity_scores={"A": 0.1, "OUT": 1.0},
        capability_scores={"A": 0.1, "OUT": 1.0},
        charter_domain_scores={"A": 0.1, "OUT": 1.0},
        force_include_ids=["OUT"],  # 即使误传 force 也应拒绝
        planned_charter_ids=["OUT"],
    )
    repos = result.repositories if hasattr(result, "repositories") else result["repositories"]
    ids = [r["repository_id"] for r in repos]
    assert "OUT" not in ids
    assert ids == ["A"]


@pytest.mark.asyncio
async def test_force_include_ids_hook_merges_without_out_of_team(caplog):
    """force_include_ids 钩子：空时不变；非空且在宇宙内则合并。"""
    result_empty = await build_shortlist(
        team_core=["A", "B", "C"],
        activity_scores={"A": 0.9, "B": 0.5, "C": 0.1},
        capability_scores={"A": 0.1, "B": 0.1, "C": 0.1},
        charter_domain_scores={"A": 0.0, "B": 0.0, "C": 0.0},
        force_include_ids=[],
        top_n=2,
    )
    repos_empty = (
        result_empty.repositories
        if hasattr(result_empty, "repositories")
        else result_empty["repositories"]
    )
    assert [r["repository_id"] for r in repos_empty] == ["A", "B"]

    result = await build_shortlist(
        team_core=["A", "B", "C"],
        activity_scores={"A": 0.9, "B": 0.5, "C": 0.1},
        capability_scores={"A": 0.1, "B": 0.1, "C": 0.1},
        charter_domain_scores={"A": 0.0, "B": 0.0, "C": 0.0},
        force_include_ids=["C"],
        force_include_reasons_by_id={"C": ["history_demand"]},
        top_n=2,
    )
    repos = result.repositories if hasattr(result, "repositories") else result["repositories"]
    by_id = {r["repository_id"]: r for r in repos}
    assert "C" in by_id
    assert "history_demand" in by_id["C"]["force_include_reasons"]


@pytest.mark.asyncio
async def test_shortlist_observability_no_requirement_body(monkeypatch):
    """观测事件 shortlist_started/completed；kwargs 无超长需求正文；meta 含 shortlist_count。"""
    events: list[tuple[str, dict]] = []

    class _FakeLogger:
        def info(self, event, **kwargs):
            events.append((event, kwargs))

        def warning(self, event, **kwargs):
            events.append((event, kwargs))

    monkeypatch.setattr(
        "services.process_runtime.shortlist.logger",
        _FakeLogger(),
    )

    result = await build_shortlist(
        team_core=["A"],
        activity_scores={"A": 0.5},
        capability_scores={"A": 0.5},
        charter_domain_scores={"A": 0.5},
        query="这是一段很长很长很长很长很长很长很长很长很长很长很长很长的需求原文" * 5,
    )
    names = [e[0] for e in events]
    assert any("shortlist_started" in n for n in names)
    assert any("shortlist_completed" in n for n in names)
    for _name, kwargs in events:
        blob = " ".join(str(v) for v in kwargs.values())
        assert "很长很长很长很长很长很长很长很长很长很长很长很长的需求原文" not in blob
        assert kwargs.get("category") in (None, "sampling") or kwargs.get("category") == "sampling"
    meta_count = (
        result.shortlist_count
        if hasattr(result, "shortlist_count")
        else result.get("shortlist_count")
    )
    assert meta_count == 1
    completed = next(kw for n, kw in events if "shortlist_completed" in n)
    assert "shortlist_count" in completed
    assert "duration_ms" in completed
