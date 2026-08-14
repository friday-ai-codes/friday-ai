"""Phase 129 历史先验分桶单测（LIST-03；D-05）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.process_runtime.history_prior import HistoryPriorResult, asplit_history_priors


@pytest.mark.asyncio
async def test_split_demand_vs_launch_and_team_intersect():
    """tech_plan→demand；document/code_change→launch；force_include ∩ team_core。"""

    async def _fake_retrieve(**kwargs):
        return SimpleNamespace(
            hits=[
                {"repository_id": "A", "kind": "tech_plan", "score": 0.9, "entity_id": "e1"},
                {"repository_id": "B", "kind": "document", "score": 0.8, "entity_id": "e2"},
                {"repository_id": "C", "kind": "code_change", "score": 0.85, "entity_id": "e3"},
            ],
            unavailable_reason="",
        )

    with patch(
        "services.process_runtime.history_prior._aretrieve_history_hits",
        new=AsyncMock(side_effect=_fake_retrieve),
    ):
        result = await asplit_history_priors(
            query="同类需求",
            team_core=["A", "B"],
            candidate_repository_ids=["A", "B", "C"],
        )

    assert isinstance(result, HistoryPriorResult) or isinstance(result, dict)
    if isinstance(result, HistoryPriorResult):
        force = result.force_include_ids
        reasons = result.reasons_by_repo
        demand = result.demand_repo_ids
        launch = result.launch_repo_ids
        unavailable = result.unavailable_reason
    else:
        force = result["force_include_ids"]
        reasons = result["reasons_by_repo"]
        demand = result["demand_repo_ids"]
        launch = result["launch_repo_ids"]
        unavailable = result.get("unavailable_reason", "")

    assert unavailable == ""
    assert set(demand) == {"A"}
    assert set(launch) >= {"B"}  # C may be in launch but out of team
    assert "C" in launch or "C" not in force
    assert set(force) == {"A", "B"}
    assert "C" not in force
    assert "history_demand" in reasons.get("A", [])
    assert "history_launch" in reasons.get("B", [])


@pytest.mark.asyncio
async def test_no_acting_user_fail_soft():
    """no_acting_user → force_include 空 + unavailable_reason，不抛。"""

    async def _fake_retrieve(**kwargs):
        return SimpleNamespace(hits=[], unavailable_reason="no_acting_user")

    with patch(
        "services.process_runtime.history_prior._aretrieve_history_hits",
        new=AsyncMock(side_effect=_fake_retrieve),
    ):
        result = await asplit_history_priors(
            query="x",
            team_core=["A"],
            candidate_repository_ids=["A"],
        )
    force = result.force_include_ids if hasattr(result, "force_include_ids") else result["force_include_ids"]
    unavailable = (
        result.unavailable_reason
        if hasattr(result, "unavailable_reason")
        else result["unavailable_reason"]
    )
    assert force == []
    assert unavailable == "no_acting_user"


@pytest.mark.asyncio
async def test_retrieval_error_fail_soft():
    """retrieval_error → 空 force_include + reason，不抛。"""

    async def _fake_retrieve(**kwargs):
        return SimpleNamespace(hits=[], unavailable_reason="retrieval_error")

    with patch(
        "services.process_runtime.history_prior._aretrieve_history_hits",
        new=AsyncMock(side_effect=_fake_retrieve),
    ):
        result = await asplit_history_priors(
            query="x",
            team_core=["A"],
            candidate_repository_ids=["A"],
        )
    force = result.force_include_ids if hasattr(result, "force_include_ids") else result["force_include_ids"]
    unavailable = (
        result.unavailable_reason
        if hasattr(result, "unavailable_reason")
        else result["unavailable_reason"]
    )
    assert force == []
    assert unavailable == "retrieval_error"
