"""漏斗统一门禁（Phase 131，GATE-01/02/03；去固定角色化）。

五门固定顺序：team → shortlist_coverage → unit_placement →
global_consistency → publish。统一输出 ``pass|clarify|block`` +
``reason_codes[]`` + evidence；聚合最严重 status（block > clarify > pass）。

发布门：默认 confirmation；``allow_auto_selected`` 仅当全 unit high +
双证据（charter/history ∪ shortlist/v2/reuse）。

观测：``funnel_gates_started/completed/failed`` 与分门 ``funnel_gate_<id>_evaluated``；
``category=sampling``，``component=process_runtime``；禁止需求全文。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "GateResult",
    "FunnelGateReport",
    "evaluate_funnel_gates",
    "GATE_ORDER",
    "REASON_CODES",
]

_COMPONENT = "process_runtime"
_CATEGORY = "sampling"

GATE_ORDER = (
    "team",
    "shortlist_coverage",
    "unit_placement",
    "global_consistency",
    "publish",
)

# 稳定 reason_code 集合（可测契约）
REASON_CODES = frozenset(
    {
        "missing_team",
        "empty_team_core",
        "out_of_team_primary",
        "empty_shortlist",
        "coverage_hole",
        "force_include_uncovered",
        "missing_primary",
        "primary_out_of_scope",
        "unit_open_questions",
        "primary_outside_universe",
        "reuse_modify_forbidden",
        "needs_confirmation",
        "confidence_not_high",
        "dual_evidence_missing",
    }
)

_STATUS_RANK = {"pass": 0, "clarify": 1, "block": 2}

_CHARTER_HISTORY = frozenset({"charter", "history"})
_ROUTE_EVIDENCE = frozenset({"shortlist", "v2", "reuse", "repo_router_v2", "hard_scope"})


@dataclass
class GateResult:
    """单门结果（统一契约）。"""

    gate_id: str
    status: str = "pass"  # pass | clarify | block
    reason_codes: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    affected_unit_ids: list[str] = field(default_factory=list)
    allow_auto_selected: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("allow_auto_selected") is None:
            d.pop("allow_auto_selected", None)
        return d


@dataclass
class FunnelGateReport:
    """五门聚合报告。"""

    status: str = "pass"
    reason_codes: list[str] = field(default_factory=list)
    gates: list[GateResult] = field(default_factory=list)
    allow_auto_selected: bool = False
    publish_mode: str = "confirmation"
    duration_ms: float = 0.0

    def gate(self, gate_id: str) -> GateResult:
        for g in self.gates:
            if g.gate_id == gate_id:
                return g
        raise KeyError(gate_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "gates": [g.to_dict() for g in self.gates],
            "allow_auto_selected": self.allow_auto_selected,
            "publish_mode": self.publish_mode,
            "duration_ms": self.duration_ms,
        }


def _worst_status(*statuses: str) -> str:
    worst = "pass"
    for s in statuses:
        if _STATUS_RANK.get(s, 0) > _STATUS_RANK.get(worst, 0):
            worst = s
    return worst


def _as_list(values: Sequence[str] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        rid = str(v or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out


def _placements_as_dicts(placements: Sequence[Any] | None) -> list[dict[str, Any]]:
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
                    "kind": getattr(p, "kind", None) or getattr(p, "unit_kind", None),
                    "reuse": bool(getattr(p, "reuse", False)),
                    "placement_mode": getattr(p, "placement_mode", None),
                }
            )
    return out


def _membership_map(
    team: Mapping[str, Any] | None,
    membership: Mapping[str, str] | None,
) -> dict[str, str]:
    out: dict[str, str] = {}
    if membership:
        for k, v in membership.items():
            if k:
                out[str(k)] = str(v or "")
    if isinstance(team, Mapping):
        mem = team.get("membership")
        if isinstance(mem, Mapping):
            for k, v in mem.items():
                if k and str(k) not in out:
                    out[str(k)] = str(v or "")
        for rid in team.get("team_core") or []:
            sid = str(rid or "").strip()
            if sid and sid not in out:
                out[sid] = "team_core"
        for rid in team.get("team_adjacent") or []:
            sid = str(rid or "").strip()
            if sid and sid not in out:
                out[sid] = "team_adjacent"
    return out


def _team_core_ids(team: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(team, Mapping):
        return []
    return _as_list(team.get("team_core") or [])


def _evidence_kinds(placement: Mapping[str, Any]) -> set[str]:
    kinds: set[str] = set()
    for e in placement.get("evidence") or []:
        if isinstance(e, Mapping):
            k = str(e.get("kind") or e.get("source") or "").strip().lower()
            if k:
                kinds.add(k)
        elif isinstance(e, str) and e.strip():
            kinds.add(e.strip().lower())
    return kinds


def _is_reuse_unit(placement: Mapping[str, Any]) -> bool:
    if placement.get("reuse") is True:
        return True
    mode = str(placement.get("placement_mode") or "").lower()
    if mode in {"reuse", "reuse_only", "reuse_host"}:
        return True
    tags = placement.get("tags") or []
    if isinstance(tags, (list, tuple)) and any(str(t).lower() == "reuse" for t in tags):
        return True
    return False


def _eval_team(
    team: Mapping[str, Any] | None,
    placements: list[dict[str, Any]],
    membership: dict[str, str],
) -> GateResult:
    codes: list[str] = []
    evidence: list[dict[str, Any]] = []
    affected: list[str] = []

    if team is None or (isinstance(team, Mapping) and not team):
        return GateResult(
            gate_id="team",
            status="clarify",
            reason_codes=["missing_team"],
            evidence=[{"kind": "team", "detail": "missing"}],
        )

    core = _team_core_ids(team)
    if not core and str(team.get("status") or "") in {"", "missing", "clarify"}:
        if not membership:
            return GateResult(
                gate_id="team",
                status="clarify",
                reason_codes=["empty_team_core"],
                evidence=[{"kind": "team", "detail": "empty_team_core"}],
            )

    status = "pass"
    for p in placements:
        primary = str(p.get("primary_repo") or "").strip()
        if not primary:
            continue
        mem = membership.get(primary, "")
        if mem == "out_of_team" or (
            core
            and primary not in set(core)
            and mem not in {"team_core", "team_adjacent"}
            and membership
            and primary in membership
            and membership[primary] == "out_of_team"
        ):
            status = "block"
            codes.append("out_of_team_primary")
            uid = str(p.get("unit_id") or "")
            if uid:
                affected.append(uid)
            evidence.append(
                {"kind": "team", "unit_id": uid, "repo_id": primary, "membership": mem}
            )

    if "out_of_team_primary" not in codes:
        for p in placements:
            primary = str(p.get("primary_repo") or "").strip()
            if primary and membership.get(primary) == "out_of_team":
                status = "block"
                codes.append("out_of_team_primary")
                uid = str(p.get("unit_id") or "")
                if uid:
                    affected.append(uid)
                evidence.append(
                    {
                        "kind": "team",
                        "unit_id": uid,
                        "repo_id": primary,
                        "membership": "out_of_team",
                    }
                )

    return GateResult(
        gate_id="team",
        status=status,
        reason_codes=_dedupe(codes),
        evidence=evidence,
        affected_unit_ids=_dedupe(affected),
    )


def _eval_shortlist_coverage(
    shortlist_ids: Sequence[str] | None,
    placements: list[dict[str, Any]],
    reuse_hosts: Sequence[str] | None,
    force_include_ids: Sequence[str] | None = None,
) -> GateResult:
    codes: list[str] = []
    evidence: list[dict[str, Any]] = []
    affected: list[str] = []
    shortlist = set(_as_list(shortlist_ids))
    hosts = set(_as_list(reuse_hosts))
    universe = shortlist | hosts
    status = "pass"

    if placements and not shortlist:
        status = "clarify"
        codes.append("empty_shortlist")
        evidence.append({"kind": "shortlist", "detail": "empty", "unit_count": len(placements)})

    for p in placements:
        uid = str(p.get("unit_id") or "")
        hs = set(_as_list(p.get("hard_scope")))
        if not hs:
            status = _worst_status(status, "clarify")
            codes.append("coverage_hole")
            if uid:
                affected.append(uid)
            evidence.append({"kind": "coverage", "unit_id": uid, "detail": "empty_hard_scope"})
            continue
        if universe and not (hs & universe):
            status = _worst_status(status, "clarify")
            codes.append("coverage_hole")
            if uid:
                affected.append(uid)
            evidence.append(
                {"kind": "coverage", "unit_id": uid, "detail": "no_intersection_with_shortlist"}
            )

    for fid in _as_list(force_include_ids):
        if fid not in universe:
            status = _worst_status(status, "clarify")
            codes.append("force_include_uncovered")
            evidence.append({"kind": "force_include", "repo_id": fid})

    return GateResult(
        gate_id="shortlist_coverage",
        status=status,
        reason_codes=_dedupe(codes),
        evidence=evidence,
        affected_unit_ids=_dedupe(affected),
    )


def _eval_unit_placement(placements: list[dict[str, Any]]) -> GateResult:
    codes: list[str] = []
    evidence: list[dict[str, Any]] = []
    affected: list[str] = []
    open_qs: list[str] = []
    status = "pass"

    for p in placements:
        uid = str(p.get("unit_id") or "")
        primary = str(p.get("primary_repo") or "").strip() or None
        hs = set(_as_list(p.get("hard_scope")))
        oqs = [str(x) for x in (p.get("open_questions") or []) if x]

        if not primary:
            status = _worst_status(status, "clarify")
            codes.append("missing_primary")
            if uid:
                affected.append(uid)
            evidence.append({"kind": "placement", "unit_id": uid, "detail": "missing_primary"})
            open_qs.extend(oqs)
            continue

        if hs and primary not in hs:
            status = _worst_status(status, "block")
            codes.append("primary_out_of_scope")
            if uid:
                affected.append(uid)
            evidence.append(
                {
                    "kind": "placement",
                    "unit_id": uid,
                    "repo_id": primary,
                    "detail": "primary_out_of_scope",
                }
            )

        priority = str(p.get("priority") or "").upper()
        if oqs and (priority in {"P0", "HIGH"} or p.get("blocking_open_questions")):
            status = _worst_status(status, "clarify")
            codes.append("unit_open_questions")
            if uid:
                affected.append(uid)
            open_qs.extend(oqs)
            evidence.append({"kind": "placement", "unit_id": uid, "detail": "open_questions"})

    return GateResult(
        gate_id="unit_placement",
        status=status,
        reason_codes=_dedupe(codes),
        evidence=evidence,
        affected_unit_ids=_dedupe(affected),
        open_questions=_dedupe(open_qs),
    )


def _eval_global_consistency(
    team: Mapping[str, Any] | None,
    shortlist_ids: Sequence[str] | None,
    placements: list[dict[str, Any]],
    membership: dict[str, str],
    reuse_hosts: Sequence[str] | None,
) -> GateResult:
    codes: list[str] = []
    evidence: list[dict[str, Any]] = []
    affected: list[str] = []
    status = "pass"

    core = set(_team_core_ids(team))
    shortlist = set(_as_list(shortlist_ids))
    hosts = set(_as_list(reuse_hosts))
    universe = shortlist | hosts | core
    for rid, mem in membership.items():
        if mem in {"team_core", "team_adjacent"}:
            universe.add(rid)

    for p in placements:
        primary = str(p.get("primary_repo") or "").strip()
        if not primary:
            continue
        uid = str(p.get("unit_id") or "")
        if membership.get(primary) == "out_of_team":
            status = "block"
            codes.append("out_of_team_primary")
            if uid:
                affected.append(uid)
            evidence.append({"kind": "consistency", "unit_id": uid, "repo_id": primary})
        elif universe and primary not in universe:
            status = "block"
            codes.append("primary_outside_universe")
            if uid:
                affected.append(uid)
            evidence.append(
                {
                    "kind": "consistency",
                    "unit_id": uid,
                    "repo_id": primary,
                    "detail": "outside_universe",
                }
            )

    host_set = hosts
    for p in placements:
        if not _is_reuse_unit(p):
            continue
        primary = str(p.get("primary_repo") or "").strip()
        if not primary:
            continue
        if primary in host_set or _looks_like_reuse_host(p, primary):
            status = "block"
            codes.append("reuse_modify_forbidden")
            uid = str(p.get("unit_id") or "")
            if uid:
                affected.append(uid)
            evidence.append(
                {
                    "kind": "consistency",
                    "unit_id": uid,
                    "repo_id": primary,
                    "detail": "reuse_modify_forbidden",
                }
            )

    return GateResult(
        gate_id="global_consistency",
        status=status,
        reason_codes=_dedupe(codes),
        evidence=evidence,
        affected_unit_ids=_dedupe(affected),
    )


def _looks_like_reuse_host(placement: Mapping[str, Any], primary: str) -> bool:
    for e in placement.get("evidence") or []:
        if not isinstance(e, Mapping):
            continue
        if str(e.get("kind") or "").lower() == "reuse" and str(
            e.get("repo_id") or e.get("host") or ""
        ) == primary:
            return True
    return False


def _eval_publish(
    placements: list[dict[str, Any]],
    confirmation_acked: bool,
) -> GateResult:
    codes: list[str] = []
    evidence: list[dict[str, Any]] = []

    all_high = bool(placements) and all(
        str(p.get("confidence") or "").lower() == "high" for p in placements
    )
    dual_ok = bool(placements) and all(_has_dual_evidence(p) for p in placements)

    allow_auto = bool(all_high and dual_ok)

    if placements and not all_high:
        codes.append("confidence_not_high")
        evidence.append({"kind": "publish", "detail": "confidence_not_high"})
    if placements and not dual_ok:
        codes.append("dual_evidence_missing")
        evidence.append({"kind": "publish", "detail": "dual_evidence_missing"})

    if allow_auto:
        return GateResult(
            gate_id="publish",
            status="pass",
            reason_codes=[],
            evidence=[{"kind": "publish", "detail": "d02_auto_selected"}],
            allow_auto_selected=True,
        )

    if confirmation_acked:
        return GateResult(
            gate_id="publish",
            status="pass",
            reason_codes=_dedupe(codes),
            evidence=evidence or [{"kind": "publish", "detail": "confirmation_acked"}],
            allow_auto_selected=False,
        )

    codes = _dedupe(["needs_confirmation"] + codes)
    return GateResult(
        gate_id="publish",
        status="clarify",
        reason_codes=codes,
        evidence=evidence or [{"kind": "publish", "detail": "needs_confirmation"}],
        allow_auto_selected=False,
    )


def _has_dual_evidence(placement: Mapping[str, Any]) -> bool:
    kinds = _evidence_kinds(placement)
    return bool(kinds & _CHARTER_HISTORY) and bool(kinds & _ROUTE_EVIDENCE)


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


def _log_gate(result: GateResult) -> None:
    try:
        logger.info(
            f"funnel_gate_{result.gate_id}_evaluated",
            category=_CATEGORY,
            component=_COMPONENT,
            gate_id=result.gate_id,
            status=result.status,
            reason_codes=list(result.reason_codes),
            evidence_count=len(result.evidence),
            affected_unit_count=len(result.affected_unit_ids),
        )
    except Exception:
        pass


def evaluate_funnel_gates(
    *,
    team: Mapping[str, Any] | None = None,
    shortlist_ids: Sequence[str] | None = None,
    role_map: Mapping[str, Any] | None = None,  # noqa: ARG001 — 已退役，保留签名兼容
    placements: Sequence[Any] | None = None,
    confirmation_acked: bool = False,
    membership: Mapping[str, str] | None = None,
    reuse_hosts: Sequence[str] | None = None,
    force_include_ids: Sequence[str] | None = None,
) -> FunnelGateReport:
    """按固定顺序求值五门并聚合最严重 status。

    纯函数优先；异常时 fail-soft 返回 block + failed reason（脱敏）。
    """
    t0 = time.perf_counter()
    try:
        logger.info(
            "funnel_gates_started",
            category=_CATEGORY,
            component=_COMPONENT,
            placement_count=len(placements or []),
            shortlist_count=len(shortlist_ids or []),
            confirmation_acked=bool(confirmation_acked),
        )
    except Exception:
        pass

    try:
        place_dicts = _placements_as_dicts(placements)
        mem = _membership_map(team, membership)

        results: list[GateResult] = [
            _eval_team(team, place_dicts, mem),
            _eval_shortlist_coverage(
                shortlist_ids, place_dicts, reuse_hosts, force_include_ids
            ),
            _eval_unit_placement(place_dicts),
            _eval_global_consistency(
                team, shortlist_ids, place_dicts, mem, reuse_hosts
            ),
            _eval_publish(place_dicts, confirmation_acked),
        ]

        for g in results:
            _log_gate(g)

        overall = "pass"
        all_codes: list[str] = []
        for g in results:
            overall = _worst_status(overall, g.status)
            all_codes.extend(g.reason_codes)

        publish = results[-1]
        allow_auto = bool(publish.allow_auto_selected)

        duration_ms = (time.perf_counter() - t0) * 1000.0
        report = FunnelGateReport(
            status=overall,
            reason_codes=_dedupe(all_codes),
            gates=results,
            allow_auto_selected=allow_auto,
            publish_mode="auto" if allow_auto else "confirmation",
            duration_ms=duration_ms,
        )

        try:
            logger.info(
                "funnel_gates_completed",
                category=_CATEGORY,
                component=_COMPONENT,
                status=report.status,
                reason_codes=list(report.reason_codes),
                allow_auto_selected=report.allow_auto_selected,
                publish_mode=report.publish_mode,
                duration_ms=round(duration_ms, 2),
                gate_count=len(results),
            )
        except Exception:
            pass

        return report
    except Exception as exc:
        duration_ms = (time.perf_counter() - t0) * 1000.0
        err = redact_secrets_in_text(str(exc))
        try:
            logger.error(
                "funnel_gates_failed",
                category=_CATEGORY,
                component=_COMPONENT,
                error=err,
                duration_ms=round(duration_ms, 2),
            )
        except Exception:
            pass
        failed = GateResult(
            gate_id="publish",
            status="block",
            reason_codes=["funnel_gates_failed"],
            evidence=[{"kind": "error", "detail": err[:200]}],
            allow_auto_selected=False,
        )
        return FunnelGateReport(
            status="block",
            reason_codes=["funnel_gates_failed"],
            gates=[
                GateResult(gate_id=gid, status="pass") for gid in GATE_ORDER[:-1]
            ]
            + [failed],
            allow_auto_selected=False,
            publish_mode="confirmation",
            duration_ms=duration_ms,
        )
