"""Phase 131 统一门禁契约与五门语义（GATE-01/02/03；D-02/D-04~D-11）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.process_runtime.funnel_gates import (
    GateResult,
    FunnelGateReport,
    evaluate_funnel_gates,
)


def _placement(
    unit_id: str,
    *,
    primary: str | None = "core-1",
    hard_scope: list[str] | None = None,
    confidence: str = "high",
    evidence: list[dict] | None = None,
    open_questions: list[str] | None = None,
    kind: str | None = None,
    reuse: bool = False,
):
    p: dict = {
        "unit_id": unit_id,
        "primary_repo": primary,
        "supporting_repos": [],
        "confidence": confidence,
        "evidence": evidence
        if evidence is not None
        else [
            {"kind": "charter"},
            {"kind": "role_map"},
        ],
        "open_questions": open_questions or [],
        "hard_scope": hard_scope if hard_scope is not None else ["core-1", "core-2", "host-1"],
    }
    if kind:
        p["kind"] = kind
        p["unit_kind"] = kind
    if reuse:
        p["reuse"] = True
        p["placement_mode"] = "reuse"
    return p


def _role_map_ok() -> dict:
    return {
        "status": "ok",
        "roles": {
            "app_shell": {"primary": "core-1", "supporting": [], "forbidden": []},
            "practice_reuse_host": {"primary": "host-1", "supporting": [], "forbidden": []},
            "course_config": {"primary": "core-2", "supporting": [], "forbidden": []},
            "learning_state": {"primary": "core-2", "supporting": [], "forbidden": []},
        },
        "per_repo": [
            {"repository_id": "core-1", "role": "app_shell", "assignment": "primary"},
            {"repository_id": "host-1", "role": "practice_reuse_host", "assignment": "primary"},
            {"repository_id": "core-2", "role": "learning_state", "assignment": "primary"},
        ],
    }


def _team_ok() -> dict:
    return {
        "status": "ok",
        "team_core": ["core-1", "core-2", "host-1"],
        "membership": {
            "core-1": "team_core",
            "core-2": "team_core",
            "host-1": "team_core",
            "outsider": "out_of_team",
        },
    }


class TestGateContract:
    def test_report_has_unified_fields_per_gate(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1")],
            confirmation_acked=True,
        )
        assert isinstance(report, FunnelGateReport)
        assert report.status in {"pass", "clarify", "block"}
        assert isinstance(report.reason_codes, list)
        assert len(report.gates) == 5
        for g in report.gates:
            assert isinstance(g, GateResult)
            assert g.gate_id in {
                "team",
                "shortlist_coverage",
                "unit_placement",
                "global_consistency",
                "publish",
            }
            assert g.status in {"pass", "clarify", "block"}
            assert isinstance(g.reason_codes, list)
            assert isinstance(g.evidence, list)


class TestTeamGate:
    def test_missing_team_clarify(self):
        report = evaluate_funnel_gates(
            team=None,
            shortlist_ids=["core-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1")],
        )
        team = report.gate("team")
        assert team.status == "clarify"
        assert "missing_team" in team.reason_codes
        assert report.status == "clarify"

    def test_out_of_team_primary_block(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1", primary="outsider", hard_scope=["core-1", "outsider"])],
        )
        team = report.gate("team")
        assert team.status == "block"
        assert "out_of_team_primary" in team.reason_codes
        assert report.status == "block"


class TestShortlistCoverage:
    def test_empty_shortlist_with_units_clarify(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=[],
            role_map=_role_map_ok(),
            placements=[_placement("u1")],
        )
        g = report.gate("shortlist_coverage")
        assert g.status == "clarify"
        assert "empty_shortlist" in g.reason_codes

    def test_coverage_hole_empty_hard_scope(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1", hard_scope=[])],
        )
        g = report.gate("shortlist_coverage")
        assert g.status == "clarify"
        assert "coverage_hole" in g.reason_codes


class TestUnitPlacement:
    def test_missing_primary_clarify(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1", primary=None)],
        )
        g = report.gate("unit_placement")
        assert g.status == "clarify"
        assert "missing_primary" in g.reason_codes

    def test_primary_out_of_scope_block(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1", primary="core-2", hard_scope=["core-1"])],
        )
        g = report.gate("unit_placement")
        assert g.status == "block"
        assert "primary_out_of_scope" in g.reason_codes


class TestGlobalConsistency:
    def test_dual_state_domain_writer_block(self):
        placements = [
            _placement("u-state-a", primary="core-1", kind="learning_state"),
            _placement("u-state-b", primary="core-2", kind="learning_state"),
        ]
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=placements,
        )
        g = report.gate("global_consistency")
        assert g.status == "block"
        assert "dual_state_domain_writer" in g.reason_codes

    def test_app_shell_scattered_block(self):
        placements = [
            _placement("u-shell-a", primary="core-1", kind="app_shell"),
            _placement("u-shell-b", primary="core-2", kind="app_shell"),
        ]
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=placements,
        )
        g = report.gate("global_consistency")
        assert g.status in {"block", "clarify"}
        assert "app_shell_scattered" in g.reason_codes

    def test_reuse_modify_forbidden_block(self):
        placements = [
            _placement("u-reuse", primary="host-1", reuse=True),
        ]
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=placements,
            reuse_hosts=["host-1"],
        )
        g = report.gate("global_consistency")
        assert g.status == "block"
        assert "reuse_modify_forbidden" in g.reason_codes

    def test_out_of_universe_primary_block(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2"],
            role_map=_role_map_ok(),
            placements=[_placement("u1", primary="ghost", hard_scope=["core-1", "ghost"])],
        )
        g = report.gate("global_consistency")
        assert g.status == "block"
        assert (
            "out_of_team_primary" in g.reason_codes
            or "primary_outside_universe" in g.reason_codes
        )


class TestPublishGate:
    def test_default_confirmation_clarify(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1")],
        )
        g = report.gate("publish")
        assert g.status == "clarify"
        assert "needs_confirmation" in g.reason_codes
        assert report.allow_auto_selected is False

    def test_d02_auto_selected_when_three_conditions_met(self):
        placements = [
            _placement(
                "u1",
                evidence=[{"kind": "charter"}, {"kind": "v2"}],
                confidence="high",
            ),
            _placement(
                "u2",
                primary="core-2",
                evidence=[{"kind": "history"}, {"kind": "shortlist"}],
                confidence="high",
            ),
        ]
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=placements,
        )
        g = report.gate("publish")
        assert g.status == "pass"
        assert report.allow_auto_selected is True

    def test_confirmation_acked_pass_without_auto(self):
        report = evaluate_funnel_gates(
            team=_team_ok(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map_ok(),
            placements=[_placement("u1", confidence="medium")],
            confirmation_acked=True,
        )
        g = report.gate("publish")
        assert g.status == "pass"
        assert report.allow_auto_selected is False


class TestAggregation:
    def test_block_beats_clarify(self):
        report = evaluate_funnel_gates(
            team=None,
            shortlist_ids=[],
            role_map=_role_map_ok(),
            placements=[_placement("u1", primary="outsider", hard_scope=["outsider"])],
            membership={"outsider": "out_of_team"},
        )
        # missing team clarify + out_of_team may still block via membership
        assert report.status in {"block", "clarify"}
        if any(g.status == "block" for g in report.gates):
            assert report.status == "block"


class TestObservability:
    def test_structlog_events_without_requirement_text(self):
        events: list[tuple[str, dict]] = []

        def _capture(event, **kwargs):
            events.append((event, kwargs))

        with patch("services.process_runtime.funnel_gates.logger") as mock_logger:
            mock_logger.info.side_effect = lambda event, **kw: _capture(event, **kw)
            mock_logger.warning.side_effect = lambda event, **kw: _capture(event, **kw)
            mock_logger.error.side_effect = lambda event, **kw: _capture(event, **kw)
            evaluate_funnel_gates(
                team=_team_ok(),
                shortlist_ids=["core-1"],
                role_map=_role_map_ok(),
                placements=[_placement("u1")],
                confirmation_acked=True,
            )

        names = [e for e, _ in events]
        assert any(n.startswith("funnel_gates_") for n in names)
        for _n, kw in events:
            blob = " ".join(str(v) for v in kw.values())
            assert "高三提分" not in blob
            assert len(blob) < 4000
            if "category" in kw:
                assert kw["category"] == "sampling"
            if "component" in kw:
                assert kw["component"] == "process_runtime"
