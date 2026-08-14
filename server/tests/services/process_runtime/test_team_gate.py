"""团队硬门禁单测（Phase 128-02，TEAM-01/02/03；D1/D3）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.process_runtime.team_gate import (
    TeamMembership,
    annotate_team_membership,
    apply_team_gate,
    resolve_team_core,
)


@pytest.mark.asyncio
async def test_resolve_team_core_from_project_space():
    space = SimpleNamespace(id="space-1", repositories=SimpleNamespace())
    project = SimpleNamespace(id="proj-1", space=space, space_id="space-1")

    with patch(
        "services.process_runtime.team_gate.sync_to_async",
        side_effect=lambda fn: AsyncMock(return_value=["repo-a", "repo-b"])
        if callable(fn)
        else fn,
    ):
        # Direct path: mock values_list via sync_to_async lambda — use resolve with
        # pre-baked space repos by patching _load_project_space_repo_ids instead.
        pass

    with patch(
        "services.process_runtime.team_gate._load_project_space_repo_ids",
        new=AsyncMock(return_value=("space-1", ["repo-a", "repo-b"])),
    ):
        result = await resolve_team_core(project_id="proj-1")

    assert result["should_clarify"] is False
    assert set(result["team_core"]) == {"repo-a", "repo-b"}
    assert result["space_id"] == "space-1"
    assert result["clarify_reason"] == ""


@pytest.mark.asyncio
async def test_resolve_team_core_explicit_space_and_primary_team_alias():
    with patch(
        "services.process_runtime.team_gate._load_space_repo_ids",
        new=AsyncMock(return_value=["repo-x"]),
    ):
        by_space = await resolve_team_core(space_id="space-x")
        by_team = await resolve_team_core(primary_team="space-x")

    assert by_space["team_core"] == ["repo-x"]
    assert by_team["team_core"] == ["repo-x"]
    assert by_space["resolution"] == "explicit_space"


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
