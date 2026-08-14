"""Phase 131 有界反思环（REFL-01/02/03；D-12~D-15）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.process_runtime.funnel_gates import evaluate_funnel_gates
from services.process_runtime.reflection import (
    ReflectionPatch,
    detect_reflection_triggers,
    run_reflection_loop,
)


def _team():
    return {
        "status": "ok",
        "team_core": ["core-1", "core-2", "host-1"],
        "membership": {
            "core-1": "team_core",
            "core-2": "team_core",
            "host-1": "team_core",
        },
    }


def _role_map(*, status="ok", forbidden_as_primary=False):
    roles = {
        "app_shell": {"primary": "core-1", "supporting": [], "forbidden": ["bad-1"]},
        "practice_reuse_host": {"primary": "host-1", "supporting": [], "forbidden": []},
        "course_config": {"primary": "core-2", "supporting": [], "forbidden": []},
        "learning_state": {"primary": "core-2", "supporting": [], "forbidden": []},
    }
    if forbidden_as_primary:
        roles["app_shell"]["primary"] = "bad-1"
    return {"status": status, "roles": roles}


def _placement(uid, **kw):
    base = {
        "unit_id": uid,
        "primary_repo": kw.get("primary", "core-1"),
        "supporting_repos": [],
        "confidence": kw.get("confidence", "high"),
        "evidence": kw.get(
            "evidence",
            [{"kind": "charter"}, {"kind": "role_map"}],
        ),
        "open_questions": kw.get("open_questions", []),
        "hard_scope": kw.get("hard_scope", ["core-1", "core-2", "host-1"]),
    }
    for k in ("kind", "reuse", "placement_mode"):
        if k in kw:
            base[k] = kw[k]
    return base


class TestDetectTriggers:
    def test_evidence_conflict(self):
        placements = [
            _placement(
                "u1",
                evidence=[
                    {"kind": "charter", "claim": "primary=core-1"},
                    {"kind": "history", "claim": "primary=core-2", "conflict": True},
                ],
            )
        ]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )
        triggers = detect_reflection_triggers(
            report, placements=placements, role_map=_role_map()
        )
        assert "evidence_conflict" in triggers.trigger_codes

    def test_role_collapse(self):
        placements = [_placement("u1", primary="bad-1", hard_scope=["core-1", "bad-1"])]
        role_map = _role_map()
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=role_map,
            placements=placements,
            confirmation_acked=True,
            membership={**_team()["membership"], "bad-1": "team_core"},
        )
        triggers = detect_reflection_triggers(
            report, placements=placements, role_map=role_map
        )
        assert "role_collapse" in triggers.trigger_codes

    def test_reuse_conflict(self):
        placements = [_placement("u1", primary="host-1", reuse=True)]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
            reuse_hosts=["host-1"],
        )
        triggers = detect_reflection_triggers(
            report, placements=placements, role_map=_role_map(), reuse_hosts=["host-1"]
        )
        assert "reuse_conflict" in triggers.trigger_codes

    def test_coverage_hole(self):
        placements = [_placement("u1", hard_scope=[])]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )
        triggers = detect_reflection_triggers(
            report, placements=placements, role_map=_role_map()
        )
        assert "coverage_hole" in triggers.trigger_codes


class TestReflectionLoop:
    def test_repair_hook_only_receives_affected_unit_ids(self):
        placements = [_placement("u-fix", hard_scope=[]), _placement("u-ok")]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )
        calls: list[dict] = []

        def repair_hook(**kwargs):
            calls.append(kwargs)
            # fix coverage
            fixed = []
            for p in kwargs.get("placements") or placements:
                p = dict(p)
                if p["unit_id"] in (kwargs.get("affected_unit_ids") or []):
                    p["hard_scope"] = ["core-1", "core-2", "host-1"]
                fixed.append(p)
            return {"placements": fixed, "repository_ids": ["core-1", "core-2", "host-1"]}

        result = run_reflection_loop(
            gate_report=report,
            placements=placements,
            role_map=_role_map(),
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            max_rounds=2,
            repair_hook=repair_hook,
            confirmation_acked=True,
        )
        assert calls, "repair_hook should be called"
        affected = set(calls[0].get("affected_unit_ids") or [])
        assert affected
        assert affected <= {"u-fix", "u-ok"}
        # must not request full-library V2
        for c in calls:
            repo_ids = c.get("repository_ids")
            if repo_ids is not None:
                assert set(repo_ids) <= {"core-1", "core-2", "host-1"}
                assert repo_ids  # never empty/full-lib sentinel

    def test_v2_mock_never_called_without_repository_ids(self):
        placements = [_placement("u1", hard_scope=[])]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )
        v2_calls: list[dict] = []

        def repair_hook(**kwargs):
            # simulate place_units calling V2 — must pass repository_ids
            repo_ids = kwargs.get("repository_ids")
            assert repo_ids is not None and len(repo_ids) > 0
            v2_calls.append({"repository_ids": list(repo_ids)})
            fixed = [dict(placements[0], hard_scope=["core-1", "core-2"])]
            return {"placements": fixed, "repository_ids": list(repo_ids)}

        run_reflection_loop(
            gate_report=report,
            placements=placements,
            role_map=_role_map(),
            team=_team(),
            shortlist_ids=["core-1", "core-2"],
            max_rounds=2,
            repair_hook=repair_hook,
            confirmation_acked=True,
        )
        assert v2_calls
        for c in v2_calls:
            assert "repository_ids" in c and c["repository_ids"]

    def test_overrun_needs_human_review(self):
        placements = [_placement("u1", hard_scope=[])]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )

        def noop_repair(**kwargs):
            return {"placements": list(kwargs.get("placements") or placements)}

        result = run_reflection_loop(
            gate_report=report,
            placements=placements,
            role_map=_role_map(),
            team=_team(),
            shortlist_ids=["core-1"],
            max_rounds=2,
            repair_hook=noop_repair,
            confirmation_acked=True,
        )
        assert result.rounds == 2
        assert result.review_status == "needs_human_review" or "needs_human_review" in (
            result.reason_codes or []
        )
        assert result.final_status in {"needs_human_review", "clarify", "unresolved"}

    def test_resolve_in_one_round(self):
        placements = [_placement("u1", hard_scope=[])]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )
        call_count = {"n": 0}

        def repair_once(**kwargs):
            call_count["n"] += 1
            return {
                "placements": [
                    _placement("u1", hard_scope=["core-1", "core-2", "host-1"])
                ],
                "repository_ids": ["core-1", "core-2", "host-1"],
            }

        result = run_reflection_loop(
            gate_report=report,
            placements=placements,
            role_map=_role_map(),
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            max_rounds=2,
            repair_hook=repair_once,
            confirmation_acked=True,
        )
        assert call_count["n"] == 1
        assert result.rounds == 1
        assert result.outcome == "resolved"
        assert result.review_status != "needs_human_review"

    def test_ledger_hook_redacted_no_requirement_text(self):
        placements = [_placement("u1", hard_scope=[])]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )
        ledger_payloads: list[dict] = []

        def ledger_hook(payload):
            ledger_payloads.append(payload)

        def repair(**kwargs):
            return {
                "placements": [_placement("u1", hard_scope=["core-1"])],
                "repository_ids": ["core-1"],
            }

        run_reflection_loop(
            gate_report=report,
            placements=placements,
            role_map=_role_map(),
            team=_team(),
            shortlist_ids=["core-1"],
            max_rounds=2,
            repair_hook=repair,
            ledger_hook=ledger_hook,
            interaction_run=SimpleNamespace(id="run-1"),
            confirmation_acked=True,
            requirement_text="这是超长需求全文高三提分专项请勿写入ledger" * 5,
        )
        assert ledger_payloads
        for p in ledger_payloads:
            blob = str(p)
            assert "高三提分" not in blob
            assert "requirement_text" not in blob.lower() or not p.get("requirement_text")

    def test_missing_run_does_not_raise(self):
        placements = [_placement("u1", hard_scope=[])]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )

        def repair(**kwargs):
            return {
                "placements": [_placement("u1", hard_scope=["core-1"])],
                "repository_ids": ["core-1"],
            }

        result = run_reflection_loop(
            gate_report=report,
            placements=placements,
            role_map=_role_map(),
            team=_team(),
            shortlist_ids=["core-1"],
            max_rounds=2,
            repair_hook=repair,
            interaction_run=None,
            confirmation_acked=True,
        )
        assert result.rounds >= 1

    def test_role_collapse_repair_path_for_int03_hook(self):
        """合成：角色坍塌 → 反思修复 → 可再评估（132/INT-03 钩子）。"""
        placements = [_placement("u1", primary="bad-1", hard_scope=["core-1", "bad-1"])]
        role_map = _role_map()
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=role_map,
            placements=placements,
            confirmation_acked=True,
            membership={**_team()["membership"], "bad-1": "team_core"},
        )
        assert "role_collapse" in detect_reflection_triggers(
            report, placements=placements, role_map=role_map
        ).trigger_codes

        def repair(**kwargs):
            return {
                "placements": [_placement("u1", primary="core-1")],
                "repository_ids": ["core-1", "core-2", "host-1"],
            }

        result = run_reflection_loop(
            gate_report=report,
            placements=placements,
            role_map=role_map,
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            max_rounds=2,
            repair_hook=repair,
            confirmation_acked=True,
            membership={**_team()["membership"], "bad-1": "team_core"},
        )
        assert result.outcome == "resolved"
        assert isinstance(result.patches[-1], ReflectionPatch)
        # re-evaluate gates after repair
        new_report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1", "core-2", "host-1"],
            role_map=role_map,
            placements=result.placements,
            confirmation_acked=True,
        )
        triggers_after = detect_reflection_triggers(
            new_report, placements=result.placements, role_map=role_map
        )
        assert "role_collapse" not in triggers_after.trigger_codes


class TestObservability:
    def test_structlog_reflection_events(self):
        events: list[str] = []
        placements = [_placement("u1", hard_scope=[])]
        report = evaluate_funnel_gates(
            team=_team(),
            shortlist_ids=["core-1"],
            role_map=_role_map(),
            placements=placements,
            confirmation_acked=True,
        )

        def repair(**kwargs):
            return {
                "placements": [_placement("u1", hard_scope=["core-1"])],
                "repository_ids": ["core-1"],
            }

        with patch("services.process_runtime.reflection.logger") as mock_logger:
            mock_logger.info.side_effect = lambda e, **kw: events.append(e)
            mock_logger.warning.side_effect = lambda e, **kw: events.append(e)
            mock_logger.error.side_effect = lambda e, **kw: events.append(e)
            run_reflection_loop(
                gate_report=report,
                placements=placements,
                role_map=_role_map(),
                team=_team(),
                shortlist_ids=["core-1"],
                max_rounds=2,
                repair_hook=repair,
                confirmation_acked=True,
            )
        assert any(e.startswith("reflection_round_") for e in events)
        assert any(e == "reflection_loop_completed" for e in events)
