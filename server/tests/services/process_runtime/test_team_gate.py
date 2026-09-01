"""团队硬门禁单测（Phase 128-02，TEAM-01/02/03；D1/D3）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.process_runtime.team_gate import (
    TeamMembership,
    annotate_team_membership,
    apply_team_gate,
    resolve_team_core,
)


@pytest.mark.asyncio
async def test_resolve_team_core_from_confirmed_project_associations():
    with patch(
        "services.process_runtime.team_gate._load_project_repo_ids",
        new=AsyncMock(
            return_value=("space-1", ["repo-a", "repo-b"], ["repo-a", "repo-b", "repo-c"])
        ),
    ):
        result = await resolve_team_core(project_id="proj-1")

    assert result["should_clarify"] is False
    assert set(result["team_core"]) == {"repo-a", "repo-b"}
    assert result["accessible_repository_ids"] == ["repo-a", "repo-b", "repo-c"]
    assert result["space_id"] == "space-1"
    assert result["clarify_reason"] == ""


@pytest.mark.asyncio
async def test_space_is_accessible_universe_not_team_identity():
    with patch(
        "services.process_runtime.team_gate._load_space_repo_ids",
        new=AsyncMock(return_value=["repo-x", "repo-y"]),
    ):
        result = await resolve_team_core(space_id="space-x")

    assert result["team_core"] == []
    assert result["accessible_repository_ids"] == ["repo-x", "repo-y"]
    assert result["should_clarify"] is True
    assert result["clarify_reason"] == "missing_team"


async def test_explicit_team_resolves_repository_facets_within_space():
    with (
        patch(
            "services.process_runtime.team_gate._load_space_repo_ids",
            new=AsyncMock(return_value=["repo-x", "repo-y"]),
        ),
        patch(
            "services.process_runtime.team_gate._load_team_repo_ids",
            new=AsyncMock(return_value=["repo-y", "repo-z"]),
        ),
    ):
        result = await resolve_team_core(space_id="space-x", primary_team="学习A")

    assert result["team_core"] == ["repo-y"]
    assert result["accessible_repository_ids"] == ["repo-x", "repo-y"]
    assert result["resolution"] == "team_facet"


@pytest.mark.asyncio
async def test_resolve_missing_team():
    result = await resolve_team_core()
    assert result["should_clarify"] is True
    assert result["clarify_reason"] == "missing_team"
    assert result["team_core"] == []


@pytest.mark.asyncio
async def test_resolve_empty_team_core():
    with patch(
        "services.process_runtime.team_gate._load_space_repo_ids",
        new=AsyncMock(return_value=[]),
    ):
        result = await resolve_team_core(space_id="space-empty")
    assert result["clarify_reason"] == "empty_team_core"
    assert result["should_clarify"] is True


@pytest.mark.asyncio
async def test_resolve_unindexed_intersection_empty():
    with patch(
        "services.process_runtime.team_gate._load_space_repo_ids",
        new=AsyncMock(return_value=["repo-a", "repo-b"]),
    ):
        result = await resolve_team_core(
            space_id="space-1",
            indexed_repository_ids=["repo-z"],
        )
    assert result["clarify_reason"] == "empty_team_core"
    assert result["team_core"] == []


def test_annotate_membership_core_and_out():
    annotated = annotate_team_membership(
        [{"repo_id": "a", "score": 0.9}, {"repository_id": "b", "score": 0.8}],
        ["a"],
    )
    by_id = {c["repository_id"]: c["team_membership"] for c in annotated}
    assert by_id["a"] == TeamMembership.TEAM_CORE.value
    assert by_id["b"] == TeamMembership.OUT_OF_TEAM.value


def test_apply_team_gate_out_of_team_not_primary():
    resolved = {
        "team_core": ["core-1"],
        "space_id": "s1",
        "should_clarify": False,
        "clarify_reason": "",
    }
    gated = apply_team_gate(
        resolve_result=resolved,
        candidates=[
            {"repo_id": "out-9", "score": 0.99},
            {"repo_id": "core-1", "score": 0.5},
        ],
    )
    assert gated["status"] == "ok"
    assert gated["primary"]["repository_id"] == "core-1"
    assert all(c["team_membership"] == "team_core" for c in gated["candidates"])
    assert any(c["repository_id"] == "out-9" for c in gated["bypass_candidates"])


def test_apply_team_gate_empty_clarify():
    gated = apply_team_gate(
        resolve_result={
            "team_core": [],
            "space_id": "s1",
            "should_clarify": True,
            "clarify_reason": "empty_team_core",
        },
        candidates=[{"repo_id": "anywhere", "score": 1.0}],
    )
    assert gated["status"] == "clarify"
    assert gated["clarify_reason"] == "empty_team_core"
    assert gated["candidates"] == []
    assert gated["primary"] is None


def test_team_adjacent_reserved_not_auto_primary():
    resolved = {
        "team_core": ["core-1"],
        "space_id": "s1",
        "should_clarify": False,
        "clarify_reason": "",
    }
    gated = apply_team_gate(
        resolve_result=resolved,
        candidates=[{"repo_id": "adj-1", "score": 0.95}],
        adjacent_ids=["adj-1"],
    )
    assert gated["primary"] is None
    assert gated["candidates"] == []
    assert gated["bypass_candidates"][0]["team_membership"] == "team_adjacent"
