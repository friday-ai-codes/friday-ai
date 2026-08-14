"""Phase 132 INT-02 — D2 placement-unit bar（非 43 点 top1）。

评测粒度：placement-unit / module-level（D-01）。
门槛：四基线各 ≥1 unit primary，且 out_of_team_primary_count == 0（D-02/D-03/D-08）。
"""

from __future__ import annotations

import pytest

from services.process_runtime.gaosan_eval import (
    BASELINE_REPOS,
    EVAL_GRANULARITY,
    normalize_repo_key,
    score_placement_bar,
)

# 评测粒度必须声明为 placement-unit（非 feature-point top1）— D-01
assert EVAL_GRANULARITY == "placement-unit"


def _placement(unit_id: str, primary: str | None) -> dict:
    return {"unit_id": unit_id, "primary_repo": primary}


class TestNormalizeRepoKey:
    def test_onion_practice_alias(self):
        assert normalize_repo_key("frontend/onion-practice") == normalize_repo_key(
            "onion-practice"
        )

    def test_study_course_alias(self):
        assert normalize_repo_key("backend/study-course") == normalize_repo_key("study-course")

    def test_onion_learning_self(self):
        assert normalize_repo_key("frontend/onion-learning") == normalize_repo_key(
            "frontend/onion-learning"
        )
        assert "onion-learning" in normalize_repo_key("frontend/onion-learning")

    def test_study_user_status_self(self):
        assert normalize_repo_key("backend/study-user-status") == normalize_repo_key(
            "backend/study-user-status"
        )
        assert "study-user-status" in normalize_repo_key("backend/study-user-status")

    def test_whitespace_and_case(self):
        assert normalize_repo_key("  Frontend/Onion-Practice  ") == normalize_repo_key(
            "onion-practice"
        )


class TestBaselineConstants:
    def test_four_baselines(self):
        assert len(BASELINE_REPOS) == 4
        norms = {normalize_repo_key(r) for r in BASELINE_REPOS}
        assert norms == {
            normalize_repo_key("frontend/onion-learning"),
            normalize_repo_key("frontend/onion-practice"),
            normalize_repo_key("backend/study-course"),
            normalize_repo_key("backend/study-user-status"),
        }


class TestScorePlacementBar:
    def _membership_ok(self) -> dict[str, str]:
        return {
            "frontend/onion-learning": "team_core",
            "frontend/onion-practice": "team_core",
            "backend/study-course": "team_core",
            "backend/study-user-status": "team_core",
            "onion-practice": "team_core",
            "study-course": "team_core",
            "study-app": "out_of_team",
            "study-practice": "out_of_team",
        }

    def test_all_baselines_hit_passes(self):
        placements = [
            _placement("u-shell", "frontend/onion-learning"),
            _placement("u-practice", "onion-practice"),  # alias
            _placement("u-course", "study-course"),  # alias
            _placement("u-state", "backend/study-user-status"),
        ]
        result = score_placement_bar(placements, self._membership_ok())
        assert result["passed"] is True
        assert result["missing_baselines"] == []
        assert result["out_of_team_primary_count"] == 0
        assert len(result["baseline_primary_hits"]) == 4
        assert len(result["normalized_primaries"]) >= 4

    def test_missing_baseline_fails(self):
        placements = [
            _placement("u-shell", "frontend/onion-learning"),
            _placement("u-practice", "frontend/onion-practice"),
            _placement("u-state", "backend/study-user-status"),
            # missing study-course
        ]
        result = score_placement_bar(placements, self._membership_ok())
        assert result["passed"] is False
        missing_norms = {normalize_repo_key(m) for m in result["missing_baselines"]}
        assert normalize_repo_key("backend/study-course") in missing_norms

    def test_out_of_team_primary_fails_even_if_baselines_complete(self):
        membership = self._membership_ok()
        placements = [
            _placement("u-shell", "frontend/onion-learning"),
            _placement("u-practice", "frontend/onion-practice"),
            _placement("u-course", "backend/study-course"),
            _placement("u-state", "backend/study-user-status"),
            _placement("u-bait", "study-app"),  # out_of_team
        ]
        result = score_placement_bar(placements, membership)
        assert result["out_of_team_primary_count"] >= 1
        assert result["passed"] is False

    def test_empty_placements_fails_all_missing(self):
        result = score_placement_bar([], self._membership_ok())
        assert result["passed"] is False
        assert len(result["missing_baselines"]) == 4
        assert result["out_of_team_primary_count"] == 0
        assert result["baseline_primary_hits"] == []


def test_eval_granularity_is_placement_unit():
    """D-01：常量/注释声明评测粒度为 placement-unit。"""
    assert EVAL_GRANULARITY == "placement-unit"
