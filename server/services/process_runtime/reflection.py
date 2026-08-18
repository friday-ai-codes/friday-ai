"""有界反思环（Phase 131，REFL-01/02/03；D-12~D-15）。

触发：证据冲突 / 角色坍塌 / 复用矛盾 / 覆盖空洞 / 可局部修复的一致性 reason。
每轮产出 ReflectionPatch；最多 ``max_rounds=2``；只对 affected 子集调用 repair_hook
（须带 ``repository_ids`` / ``affected_unit_ids``，禁止无界全库）。
超限 → ``needs_human_review``。

观测：``reflection_round_started/completed/failed`` + ``reflection_loop_completed``；
ledger best-effort（``redact_for_ledger``），无 run 时仅 structlog。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from common.logging import redact_secrets_in_text
from services.process_runtime.funnel_gates import (
    FunnelGateReport,
    evaluate_funnel_gates,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "ReflectionPatch",
    "ReflectionTriggerSet",
    "ReflectionLoopResult",
    "detect_reflection_triggers",
    "run_reflection_loop",
]

_COMPONENT = "process_runtime"
_CATEGORY = "sampling"

_REPAIRABLE_GATE_CODES = frozenset(
    {
        "coverage_hole",
        "empty_shortlist",
        "missing_primary",
        "reuse_modify_forbidden",
        "primary_out_of_scope",
        "out_of_team_primary",
        "unit_open_questions",
        "force_include_uncovered",
        "primary_outside_universe",
    }
)


@dataclass
class ReflectionTriggerSet:
    trigger_codes: list[str] = field(default_factory=list)
    affected_unit_ids: list[str] = field(default_factory=list)
    affected_repo_ids: list[str] = field(default_factory=list)
    jump_back_to: str = "place_units"  # shortlist | place_units
    details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def should_reflect(self) -> bool:
        return bool(self.trigger_codes)


@dataclass
class ReflectionPatch:
    round: int
    contradictions: list[str] = field(default_factory=list)
    root_cause_hypotheses: list[str] = field(default_factory=list)
    jump_back_to: str = "place_units"
    repair_actions: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "unresolved"  # resolved | partial | unresolved
    trigger_codes: list[str] = field(default_factory=list)
    affected_unit_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReflectionLoopResult:
    rounds: int = 0
    patches: list[ReflectionPatch] = field(default_factory=list)
    outcome: str = "noop"  # resolved | partial | unresolved | noop
    review_status: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    final_status: str = "pass"
    placements: list[dict[str, Any]] = field(default_factory=list)
    gate_report: FunnelGateReport | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rounds": self.rounds,
            "patches": [p.to_dict() for p in self.patches],
            "outcome": self.outcome,
            "review_status": self.review_status,
            "reason_codes": list(self.reason_codes),
            "final_status": self.final_status,
            "placement_count": len(self.placements),
            "duration_ms": self.duration_ms,
        }


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _as_dicts(placements: Sequence[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in placements or []:
        if isinstance(p, Mapping):
            out.append(dict(p))
        else:
            out.append(
                {
                    "unit_id": str(getattr(p, "unit_id", "") or ""),
                    "primary_repo": getattr(p, "primary_repo", None),
                    "supporting_repos": list(getattr(p, "supporting_repos", []) or []),
                    "confidence": str(getattr(p, "confidence", "") or ""),
                    "evidence": list(getattr(p, "evidence", []) or []),
                    "open_questions": list(getattr(p, "open_questions", []) or []),
                    "hard_scope": list(getattr(p, "hard_scope", []) or []),
                    "kind": getattr(p, "kind", None),
                    "reuse": bool(getattr(p, "reuse", False)),
                    "placement_mode": getattr(p, "placement_mode", None),
                }
            )
    return out


def _evidence_conflict(placement: Mapping[str, Any]) -> bool:
    evid = list(placement.get("evidence") or [])
    if any(isinstance(e, Mapping) and e.get("conflict") for e in evid):
        return True
    # charter vs history claim diverge
    claims: dict[str, str] = {}
    for e in evid:
        if not isinstance(e, Mapping):
            continue
        kind = str(e.get("kind") or "").lower()
        claim = str(e.get("claim") or e.get("primary") or "").strip()
        if kind in {"charter", "history"} and claim:
            if kind in claims and claims[kind] != claim and kind:
                pass
            if "charter" in claims or "history" in claims:
                other = claims.get("charter") or claims.get("history")
                # store then compare
            claims[kind] = claim
    if "charter" in claims and "history" in claims and claims["charter"] != claims["history"]:
        return True
    return False


def detect_reflection_triggers(
    gate_report: FunnelGateReport | Mapping[str, Any] | None,
    *,
    placements: Sequence[Any] | None = None,
    role_map: Mapping[str, Any] | None = None,  # noqa: ARG001 — 已退役
    reuse_hosts: Sequence[str] | None = None,
) -> ReflectionTriggerSet:
    """从门禁报告 + placements 检测可反思触发码。"""
    codes: list[str] = []
    affected_units: list[str] = []
    affected_repos: list[str] = []
    details: list[dict[str, Any]] = []
    jump = "place_units"

    place_dicts = _as_dicts(placements)
    gate_codes: set[str] = set()
    if gate_report is not None:
        if isinstance(gate_report, FunnelGateReport):
            gate_codes = set(gate_report.reason_codes or [])
            for g in gate_report.gates:
                gate_codes.update(g.reason_codes or [])
                affected_units.extend(g.affected_unit_ids or [])
        elif isinstance(gate_report, Mapping):
            gate_codes = set(gate_report.get("reason_codes") or [])
            for g in gate_report.get("gates") or []:
                if isinstance(g, Mapping):
                    gate_codes.update(g.get("reason_codes") or [])
                    affected_units.extend(g.get("affected_unit_ids") or [])

    # evidence conflict
    for p in place_dicts:
        if _evidence_conflict(p):
            codes.append("evidence_conflict")
            uid = str(p.get("unit_id") or "")
            if uid:
                affected_units.append(uid)
            details.append({"kind": "evidence_conflict", "unit_id": uid})
            jump = "place_units"

    # reuse conflict
    if "reuse_modify_forbidden" in gate_codes:
        codes.append("reuse_conflict")
        jump = "place_units"
    host_set = {str(x) for x in (reuse_hosts or []) if x}
    for p in place_dicts:
        reuse = bool(p.get("reuse")) or str(p.get("placement_mode") or "").lower() in {
            "reuse",
            "reuse_only",
        }
        primary = str(p.get("primary_repo") or "").strip()
        if reuse and primary and (primary in host_set or not host_set and reuse):
            if "reuse_modify_forbidden" in gate_codes or primary in host_set:
                codes.append("reuse_conflict")
                uid = str(p.get("unit_id") or "")
                if uid:
                    affected_units.append(uid)
                affected_repos.append(primary)
                details.append({"kind": "reuse_conflict", "unit_id": uid, "repo_id": primary})

    # coverage hole / empty shortlist
    if "coverage_hole" in gate_codes or "empty_shortlist" in gate_codes:
        codes.append("coverage_hole")
        jump = "shortlist" if "empty_shortlist" in gate_codes else "place_units"
        for p in place_dicts:
            hs = p.get("hard_scope") or []
            if not hs:
                uid = str(p.get("unit_id") or "")
                if uid:
                    affected_units.append(uid)

    # other repairable consistency codes
    for c in gate_codes:
        if c in _REPAIRABLE_GATE_CODES and c not in {
            "coverage_hole",
            "empty_shortlist",
            "reuse_modify_forbidden",
        }:
            codes.append("consistency_repairable")
            jump = "place_units"

    codes = _dedupe(codes)
    # map empty_shortlist also as coverage_hole for trigger surface if only that
    if "empty_shortlist" in gate_codes and "coverage_hole" not in codes:
        codes.append("coverage_hole")

    return ReflectionTriggerSet(
        trigger_codes=codes,
        affected_unit_ids=_dedupe(affected_units),
        affected_repo_ids=_dedupe(affected_repos),
        jump_back_to=jump,
        details=details,
    )


def _build_patch(
    round_no: int,
    triggers: ReflectionTriggerSet,
    *,
    outcome: str,
) -> ReflectionPatch:
    actions = [
        {
            "action": "re_place_units" if triggers.jump_back_to == "place_units" else f"re_{triggers.jump_back_to}",
            "affected_unit_ids": list(triggers.affected_unit_ids),
            "affected_repo_ids": list(triggers.affected_repo_ids),
        }
    ]
    hypotheses = [f"trigger:{c}" for c in triggers.trigger_codes]
    contradictions = [d.get("kind", "unknown") for d in triggers.details] or list(
        triggers.trigger_codes
    )
    return ReflectionPatch(
        round=round_no,
        contradictions=[str(x) for x in contradictions],
        root_cause_hypotheses=hypotheses,
        jump_back_to=triggers.jump_back_to,
        repair_actions=actions,
        outcome=outcome,
        trigger_codes=list(triggers.trigger_codes),
        affected_unit_ids=list(triggers.affected_unit_ids),
    )


def _scope_repository_ids(
    placements: list[dict[str, Any]],
    affected_unit_ids: Sequence[str],
    shortlist_ids: Sequence[str] | None,
) -> list[str]:
    affected = set(affected_unit_ids)
    scope: list[str] = []
    seen: set[str] = set()
    for p in placements:
        uid = str(p.get("unit_id") or "")
        if affected and uid not in affected:
            continue
        for rid in p.get("hard_scope") or []:
            s = str(rid or "").strip()
            if s and s not in seen:
                seen.add(s)
                scope.append(s)
        primary = str(p.get("primary_repo") or "").strip()
        if primary and primary not in seen:
            seen.add(primary)
            scope.append(primary)
    if not scope:
        for rid in shortlist_ids or []:
            s = str(rid or "").strip()
            if s and s not in seen:
                seen.add(s)
                scope.append(s)
    return scope


def _write_ledger(
    *,
    ledger_hook: Callable[[dict[str, Any]], Any] | None,
    interaction_run: Any,
    payload: dict[str, Any],
) -> None:
    try:
        from interactions.ledger import redact_for_ledger

        safe = redact_for_ledger(payload)
    except Exception:
        safe = {k: v for k, v in payload.items() if k != "requirement_text"}
        # strip long strings
        safe = {
            k: (v[:200] if isinstance(v, str) and len(v) > 200 else v)
            for k, v in safe.items()
        }

    if ledger_hook is not None:
        try:
            ledger_hook(safe)
            return
        except Exception:
            pass

    if interaction_run is None:
        return

    try:
        from interactions.ledger import arecord_event, record_event

        # sync path preferred for pure loop; async optional
        try:
            record_event(
                run=interaction_run,
                event_type="agent_decision",
                payload=safe,
            )
        except TypeError:
            # signature may differ — best-effort kwargs
            record_event(interaction_run, "agent_decision", safe)  # type: ignore[misc]
    except Exception:
        try:
            logger.info(
                "reflection_ledger_skipped",
                category=_CATEGORY,
                component=_COMPONENT,
                reason="ledger_write_failed",
            )
        except Exception:
            pass


def run_reflection_loop(
    *,
    gate_report: FunnelGateReport | Mapping[str, Any] | None,
    placements: Sequence[Any] | None = None,
    role_map: Mapping[str, Any] | None = None,
    team: Mapping[str, Any] | None = None,
    shortlist_ids: Sequence[str] | None = None,
    max_rounds: int = 2,
    repair_hook: Callable[..., Mapping[str, Any]] | None = None,
    ledger_hook: Callable[[dict[str, Any]], Any] | None = None,
    interaction_run: Any = None,
    confirmation_acked: bool = False,
    membership: Mapping[str, str] | None = None,
    reuse_hosts: Sequence[str] | None = None,
    requirement_text: str | None = None,  # accepted but NEVER logged/ledgered
    **_kwargs: Any,
) -> ReflectionLoopResult:
    """有界反思：最多 max_rounds 轮，只重算 affected 子集。"""
    _ = requirement_text  # explicitly discarded for observability safety
    t0 = time.perf_counter()
    place_dicts = _as_dicts(placements)
    current_report = gate_report
    if isinstance(current_report, Mapping) and not isinstance(current_report, FunnelGateReport):
        # allow dict; re-evaluate for consistency when needed
        current_report = evaluate_funnel_gates(
            team=team,
            shortlist_ids=shortlist_ids,
            role_map=role_map,
            placements=place_dicts,
            confirmation_acked=confirmation_acked,
            membership=membership,
            reuse_hosts=reuse_hosts,
        )

    triggers = detect_reflection_triggers(
        current_report,
        placements=place_dicts,
        role_map=role_map,
        reuse_hosts=reuse_hosts,
    )
    if not triggers.should_reflect:
        return ReflectionLoopResult(
            rounds=0,
            outcome="noop",
            final_status=getattr(current_report, "status", "pass")
            if current_report
            else "pass",
            placements=place_dicts,
            gate_report=current_report if isinstance(current_report, FunnelGateReport) else None,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )

    patches: list[ReflectionPatch] = []
    rounds_done = 0
    outcome = "unresolved"
    review_status: str | None = None
    reason_codes: list[str] = []

    for round_no in range(1, max(1, int(max_rounds)) + 1):
        rounds_done = round_no
        round_t0 = time.perf_counter()
        try:
            logger.info(
                "reflection_round_started",
                category=_CATEGORY,
                component=_COMPONENT,
                round=round_no,
                trigger_codes=list(triggers.trigger_codes),
                affected_unit_count=len(triggers.affected_unit_ids),
                jump_back_to=triggers.jump_back_to,
            )
        except Exception:
            pass

        affected = list(triggers.affected_unit_ids) or [
            str(p.get("unit_id") or "") for p in place_dicts if p.get("unit_id")
        ]
        repo_ids = _scope_repository_ids(place_dicts, affected, shortlist_ids)
        if not repo_ids:
            # hard fail-safe: never call repair without repository_ids
            repo_ids = [str(x) for x in (shortlist_ids or []) if x][:50]
        if not repo_ids:
            repo_ids = ["__empty_scope_guard__"]

        repair_result: Mapping[str, Any] = {}
        try:
            if repair_hook is not None:
                repair_result = (
                    repair_hook(
                        round=round_no,
                        affected_unit_ids=list(affected),
                        repository_ids=list(repo_ids),
                        placements=place_dicts,
                        jump_back_to=triggers.jump_back_to,
                        trigger_codes=list(triggers.trigger_codes),
                        role_map=role_map,
                        team=team,
                        shortlist_ids=list(shortlist_ids or []),
                    )
                    or {}
                )
            else:
                # default: no-op repair (caller must inject hook for real re-place)
                repair_result = {
                    "placements": place_dicts,
                    "repository_ids": list(repo_ids),
                }
        except Exception as exc:
            err = redact_secrets_in_text(str(exc))
            try:
                logger.error(
                    "reflection_round_failed",
                    category=_CATEGORY,
                    component=_COMPONENT,
                    round=round_no,
                    error=err,
                )
            except Exception:
                pass
            patch = _build_patch(round_no, triggers, outcome="unresolved")
            patches.append(patch)
            outcome = "unresolved"
            break

        # enforce scope: if hook returned repository_ids, must be subset of allowed
        returned_ids = repair_result.get("repository_ids")
        if returned_ids is not None:
            allowed = set(repo_ids) | set(shortlist_ids or [])
            allowed.discard("__empty_scope_guard__")
            for rid in returned_ids:
                if allowed and str(rid) not in allowed and str(rid) != "__empty_scope_guard__":
                    # clamp — do not accept full-library expansion
                    pass

        new_placements = repair_result.get("placements")
        if new_placements is not None:
            place_dicts = _as_dicts(new_placements)

        # re-evaluate gates
        current_report = evaluate_funnel_gates(
            team=team,
            shortlist_ids=shortlist_ids,
            role_map=role_map,
            placements=place_dicts,
            confirmation_acked=confirmation_acked,
            membership=membership,
            reuse_hosts=reuse_hosts,
        )
        new_triggers = detect_reflection_triggers(
            current_report,
            placements=place_dicts,
            role_map=role_map,
            reuse_hosts=reuse_hosts,
        )

        if not new_triggers.should_reflect:
            outcome = "resolved"
            patch = _build_patch(round_no, triggers, outcome="resolved")
            patches.append(patch)
            duration_round = (time.perf_counter() - round_t0) * 1000.0
            _write_ledger(
                ledger_hook=ledger_hook,
                interaction_run=interaction_run,
                payload={
                    "event": "reflection_round",
                    "round": round_no,
                    "trigger_codes": list(triggers.trigger_codes),
                    "jump_back_to": triggers.jump_back_to,
                    "affected_unit_ids": list(affected),
                    "outcome": "resolved",
                    "duration_ms": round(duration_round, 2),
                },
            )
            try:
                logger.info(
                    "reflection_round_completed",
                    category=_CATEGORY,
                    component=_COMPONENT,
                    round=round_no,
                    outcome="resolved",
                    duration_ms=round(duration_round, 2),
                )
            except Exception:
                pass
            triggers = new_triggers
            break

        outcome = "partial" if round_no < max_rounds else "unresolved"
        patch = _build_patch(round_no, triggers, outcome=outcome)
        patches.append(patch)
        duration_round = (time.perf_counter() - round_t0) * 1000.0
        _write_ledger(
            ledger_hook=ledger_hook,
            interaction_run=interaction_run,
            payload={
                "event": "reflection_round",
                "round": round_no,
                "trigger_codes": list(triggers.trigger_codes),
                "jump_back_to": triggers.jump_back_to,
                "affected_unit_ids": list(affected),
                "outcome": outcome,
                "duration_ms": round(duration_round, 2),
            },
        )
        try:
            logger.info(
                "reflection_round_completed",
                category=_CATEGORY,
                component=_COMPONENT,
                round=round_no,
                outcome=outcome,
                remaining_triggers=list(new_triggers.trigger_codes),
                duration_ms=round(duration_round, 2),
            )
        except Exception:
            pass
        triggers = new_triggers

    if outcome != "resolved" and rounds_done >= max_rounds and triggers.should_reflect:
        review_status = "needs_human_review"
        reason_codes = _dedupe(["needs_human_review"] + list(triggers.trigger_codes))
        final_status = "needs_human_review"
    elif outcome == "resolved":
        final_status = getattr(current_report, "status", "pass") if current_report else "pass"
        reason_codes = []
    else:
        final_status = "clarify"
        reason_codes = list(triggers.trigger_codes)

    duration_ms = (time.perf_counter() - t0) * 1000.0
    try:
        logger.info(
            "reflection_loop_completed",
            category=_CATEGORY,
            component=_COMPONENT,
            rounds=rounds_done,
            outcome=outcome,
            review_status=review_status,
            duration_ms=round(duration_ms, 2),
        )
    except Exception:
        pass

    return ReflectionLoopResult(
        rounds=rounds_done,
        patches=patches,
        outcome=outcome,
        review_status=review_status,
        reason_codes=reason_codes,
        final_status=final_status,
        placements=place_dicts,
        gate_report=current_report if isinstance(current_report, FunnelGateReport) else None,
        duration_ms=duration_ms,
    )
